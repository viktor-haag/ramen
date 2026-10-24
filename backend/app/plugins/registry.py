from app.errors import NotFoundError
from app.plugins.base import Capability, url_matches
from app.plugins.loader import PluginInfo


class PluginRegistry:
    def __init__(self, infos: dict[str, PluginInfo]):
        self._infos = infos

    def all(self) -> list[PluginInfo]:
        return list(self._infos.values())

    def items(self) -> list[tuple[str, PluginInfo]]:
        """(registry key, info) pairs; the key is the canonical plugin name (may differ from info.name)."""
        return list(self._infos.items())

    def get(self, name: str) -> PluginInfo:
        info = self._infos.get(name)
        if info is None:
            raise NotFoundError("plugin_not_found", f"Plugin '{name}' not found", {"name": name})
        return info

    def usable(self) -> list[PluginInfo]:
        return [i for i in self._infos.values() if i.error is None]

    def for_url(self, url: str) -> PluginInfo | None:
        for info in self.usable():
            if Capability.FETCH in info.capabilities and url_matches(info.url_patterns, url):
                return info
        return None
