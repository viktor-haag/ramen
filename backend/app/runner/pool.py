import logging
import multiprocessing
import threading
from concurrent.futures import Future

from pebble import ProcessPool

from app.plugins.base import SearchProfileDTO
from app.plugins.loader import PluginInfo, load_extractor
from app.runner.failures import to_failure

log = logging.getLogger(__name__)


def execute_search(module_path: str, class_name: str, profile: dict, settings: dict) -> list[dict]:
    """Runs in a spawned worker: plain dicts in, plain dicts out (never a PluginInfo).

    Any plugin exception is replaced by a picklable PluginFailure carrying the traceback text.
    """
    try:
        extractor = load_extractor(module_path, class_name)
        parsed = type(extractor).settings_schema.model_validate(settings)
        results = extractor.search(SearchProfileDTO.model_validate(profile), parsed)
        return [p.model_dump(mode="json") for p in results]
    except Exception as exc:
        raise to_failure(exc) from None


def execute_fetch(module_path: str, class_name: str, url: str, settings: dict) -> dict:
    """Runs in a spawned worker: fetch one posting by URL; plain dict out (errors as in execute_search)."""
    try:
        extractor = load_extractor(module_path, class_name)
        parsed = type(extractor).settings_schema.model_validate(settings)
        return extractor.fetch(url, parsed).model_dump(mode="json")
    except Exception as exc:
        raise to_failure(exc) from None


class RunnerPool:
    """Process pool for plugin searches. Workers start lazily on the first submit.

    A pool that stopped working (pebble reports "The Pool is not active" / "Unexpected error
    within the Pool") is replaced on the next submit instead of failing every later run.
    """

    def __init__(self, size: int):
        self._size = size
        self._lock = threading.Lock()
        self._pool = self._new_pool()

    def _new_pool(self) -> ProcessPool:
        return ProcessPool(max_workers=self._size, context=multiprocessing.get_context("spawn"))

    def _replace(self) -> None:
        old, self._pool = self._pool, self._new_pool()
        try:
            old.stop()
            old.join(timeout=5)
        except Exception:
            log.exception("Stopping the broken process pool failed")

    def _schedule(self, function, args: tuple, timeout: int) -> Future:
        with self._lock:
            if not self._pool.active:
                log.warning("Process pool is not active; starting a new one")
                self._replace()
            try:
                return self._pool.schedule(function, args=args, timeout=timeout)
            except RuntimeError:
                log.exception("Process pool rejected a task; starting a new one")
                self._replace()
                return self._pool.schedule(function, args=args, timeout=timeout)

    def submit(
        self, info: PluginInfo, profile: SearchProfileDTO, settings: dict, timeout: int
    ) -> Future[list[dict]]:
        return self._schedule(
            execute_search, (info.module_path, info.class_name, profile.model_dump(), dict(settings)), timeout
        )

    def submit_fetch(self, info: PluginInfo, url: str, settings: dict, timeout: int) -> Future[dict]:
        return self._schedule(execute_fetch, (info.module_path, info.class_name, url, dict(settings)), timeout)

    def close(self) -> None:
        """Abort pending/running searches and wait for the workers to exit."""
        with self._lock:
            self._pool.close()
            self._pool.stop()
            self._pool.join()
