import multiprocessing
from concurrent.futures import Future

from pebble import ProcessPool

from app.plugins.base import SearchProfileDTO
from app.plugins.loader import PluginInfo, load_extractor


def execute_search(module_path: str, class_name: str, profile: dict, settings: dict) -> list[dict]:
    """Runs in a spawned worker: plain dicts in, plain dicts out (never a PluginInfo)."""
    extractor = load_extractor(module_path, class_name)
    parsed = type(extractor).settings_schema.model_validate(settings)
    results = extractor.search(SearchProfileDTO.model_validate(profile), parsed)
    return [p.model_dump(mode="json") for p in results]


def execute_fetch(module_path: str, class_name: str, url: str, settings: dict) -> dict:
    """Runs in a spawned worker: fetch one posting by URL; plain dict out."""
    extractor = load_extractor(module_path, class_name)
    parsed = type(extractor).settings_schema.model_validate(settings)
    return extractor.fetch(url, parsed).model_dump(mode="json")


class RunnerPool:
    """Process pool for plugin searches. Workers start lazily on the first submit."""

    def __init__(self, size: int):
        self._pool = ProcessPool(max_workers=size, context=multiprocessing.get_context("spawn"))

    def submit(
        self, info: PluginInfo, profile: SearchProfileDTO, settings: dict, timeout: int
    ) -> Future[list[dict]]:
        return self._pool.schedule(
            execute_search,
            args=(info.module_path, info.class_name, profile.model_dump(), dict(settings)),
            timeout=timeout,
        )

    def submit_fetch(self, info: PluginInfo, url: str, settings: dict, timeout: int) -> Future[dict]:
        return self._pool.schedule(
            execute_fetch,
            args=(info.module_path, info.class_name, url, dict(settings)),
            timeout=timeout,
        )

    def close(self) -> None:
        """Abort pending/running searches and wait for the workers to exit."""
        self._pool.close()
        self._pool.stop()
        self._pool.join()
