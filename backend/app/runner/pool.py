import logging
import multiprocessing
import threading
import weakref
from concurrent.futures import Future, InvalidStateError
from concurrent.futures.process import BrokenProcessPool

from pebble import ProcessPool

from app.plugins.base import SearchProfileDTO
from app.plugins.loader import PluginInfo, load_extractor
from app.runner.failures import to_failure

log = logging.getLogger(__name__)


def execute_search(module_path: str, class_name: str, profile: dict, settings: dict) -> list[dict]:
    """Runs in a spawned worker: plain dicts in, plain dicts out (never a PluginInfo).

    Any plugin exception, including BaseExceptions like SystemExit (which would kill pebble's
    result thread in the parent), is replaced by a picklable PluginFailure with the traceback.
    """
    try:
        extractor = load_extractor(module_path, class_name)
        parsed = type(extractor).settings_schema.model_validate(settings)
        results = extractor.search(SearchProfileDTO.model_validate(profile), parsed)
        return [p.model_dump(mode="json") for p in results]
    except BaseException as exc:
        raise to_failure(exc) from None


def execute_fetch(module_path: str, class_name: str, url: str, settings: dict) -> dict:
    """Runs in a spawned worker: fetch one posting by URL; plain dict out (errors as in execute_search)."""
    try:
        extractor = load_extractor(module_path, class_name)
        parsed = type(extractor).settings_schema.model_validate(settings)
        return extractor.fetch(url, parsed).model_dump(mode="json")
    except BaseException as exc:
        raise to_failure(exc) from None


class RunnerPool:
    """Process pool for plugin searches. Workers start lazily on the first submit.

    A pool that stopped working (pebble reports "The Pool is not active" / "Unexpected error
    within the Pool") is replaced on the next submit or `ensure_active()`; tasks it left
    unresolved fail with BrokenProcessPool so no run waits forever. After `close()` the pool
    refuses work instead of starting a new one.
    """

    def __init__(self, size: int):
        self._size = size
        self._lock = threading.Lock()
        self._closed = False
        self._pool = self._new_pool()
        self._futures: weakref.WeakSet[Future] = weakref.WeakSet()  # tasks of the current pool

    def _new_pool(self) -> ProcessPool:
        return ProcessPool(max_workers=self._size, context=multiprocessing.get_context("spawn"))

    def _swap(self) -> tuple[ProcessPool, list[Future]]:
        """Under `_lock`: install a fresh pool; returns the old one and its tasks."""
        old, self._pool = self._pool, self._new_pool()
        futures, self._futures = list(self._futures), weakref.WeakSet()
        return old, futures

    @staticmethod
    def _retire(old: ProcessPool, futures: list[Future]) -> None:
        """Outside `_lock`: stop the broken pool and fail what it left unresolved."""
        try:
            old.stop()
            old.join(timeout=5)
        except Exception:
            log.exception("Stopping the broken process pool failed")
        for future in futures:
            if future.done():
                continue
            try:
                future.set_exception(BrokenProcessPool("The plugin process pool stopped working"))
            except InvalidStateError:  # resolved meanwhile
                pass

    def ensure_active(self) -> None:
        """Replace the pool if it is no longer active (no-op after close())."""
        with self._lock:
            if self._closed or self._pool.active:
                return
            log.warning("Process pool is not active; starting a new one")
            retired = self._swap()
        self._retire(*retired)

    def _schedule(self, function, args: tuple, timeout: int) -> Future:
        retired: list[tuple[ProcessPool, list[Future]]] = []
        try:
            with self._lock:
                if self._closed:
                    raise RuntimeError("The plugin process pool is closed")
                if not self._pool.active:
                    log.warning("Process pool is not active; starting a new one")
                    retired.append(self._swap())
                try:
                    future = self._pool.schedule(function, args=args, timeout=timeout)
                except RuntimeError:
                    log.exception("Process pool rejected a task; starting a new one")
                    retired.append(self._swap())
                    future = self._pool.schedule(function, args=args, timeout=timeout)
                self._futures.add(future)
                return future
        finally:
            for old in retired:
                self._retire(*old)

    def submit(
        self, info: PluginInfo, profile: SearchProfileDTO, settings: dict, timeout: int
    ) -> Future[list[dict]]:
        return self._schedule(
            execute_search, (info.module_path, info.class_name, profile.model_dump(), dict(settings)), timeout
        )

    def submit_fetch(self, info: PluginInfo, url: str, settings: dict, timeout: int) -> Future[dict]:
        return self._schedule(execute_fetch, (info.module_path, info.class_name, url, dict(settings)), timeout)

    def close(self) -> None:
        """Abort pending/running searches and wait for the workers to exit; no restart afterwards."""
        with self._lock:
            self._closed = True
            pool = self._pool
        pool.close()
        pool.stop()
        pool.join()
