import importlib.util
import inspect
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from app.plugins.base import Extractor

MODULE_PREFIX = "jobtracker_plugin_"


@dataclass
class PluginInfo:
    name: str
    display_name: str
    capabilities: set[str]
    url_patterns: list[str]
    settings_schema: type[BaseModel] | None
    timeout_seconds: int
    module_path: str
    class_name: str
    error: str | None = None


def _import_file(path: Path, stem: str):
    """Import `path` as `jobtracker_plugin_<stem>`; no sys.modules trace on failure."""
    modname = MODULE_PREFIX + stem
    spec = importlib.util.spec_from_file_location(modname, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: pickling classes/dataclasses defined in the plugin needs it.
    sys.modules[modname] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(modname, None)
        raise
    return module


def _entries(dirs: list[Path]):
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            continue
        for p in sorted(d.iterdir()):
            if p.name.startswith(("_", ".")):
                continue
            if p.is_file() and p.suffix == ".py":
                yield p.stem, p.resolve(), d
            elif p.is_dir() and (p / "__init__.py").is_file():
                yield p.name, (p / "__init__.py").resolve(), d


def _extractor_classes(module) -> list[type[Extractor]]:
    """Extractor subclasses defined in the plugin module or its submodules (re-exports)."""
    prefix = module.__name__ + "."
    found = [
        c
        for _, c in inspect.getmembers(module, inspect.isclass)
        if issubclass(c, Extractor)
        and c is not Extractor
        and not inspect.isabstract(c)
        and (c.__module__ == module.__name__ or c.__module__.startswith(prefix))
    ]
    # drop intermediate bases: a class that another found class derives from
    return [c for c in found if not any(o is not c and issubclass(o, c) for o in found)]


_REQUIRED = ("name", "display_name", "capabilities")


def _missing(cls: type[Extractor]) -> str | None:
    return next((a for a in _REQUIRED if not hasattr(cls, a)), None)


def _error_info(stem: str, path: Path, error: str) -> PluginInfo:
    return PluginInfo(
        name=stem, display_name=stem, capabilities=set(), url_patterns=[],
        settings_schema=None, timeout_seconds=0, module_path=str(path),
        class_name="", error=error,
    )


def _build_info(cls: type[Extractor], path: Path) -> PluginInfo:
    patterns = list(cls.url_patterns)
    for pattern in patterns:
        re.compile(pattern)  # invalid regex -> plugin error at discovery time
    return PluginInfo(
        name=cls.name,
        display_name=cls.display_name,
        capabilities={str(c) for c in cls.capabilities},
        url_patterns=patterns,
        settings_schema=cls.settings_schema,
        timeout_seconds=cls.timeout_seconds,
        module_path=str(path),
        class_name=cls.__name__,
    )


def _free_key(result: dict, *candidates: str) -> str:
    for c in candidates:
        if c not in result:
            return c
    base, n = candidates[-1], 2
    while f"{base}#{n}" in result:
        n += 1
    return f"{base}#{n}"


def _describe(exc: BaseException) -> str:
    text = str(exc)
    if isinstance(exc, Exception):
        return text or type(exc).__name__
    return f"{type(exc).__name__}: {text}" if text else type(exc).__name__


def discover_plugins(dirs: list[Path]) -> dict[str, PluginInfo]:
    """Load all plugins; never raises because of a plugin."""
    ok: list[tuple[str, Path, type[Extractor]]] = []
    errors: list[tuple[str, Path, Path, str]] = []  # stem, path, dir, message
    for stem, path, d in _entries(dirs):
        try:
            module = _import_file(path, stem)
            classes = _extractor_classes(module)
            valid = [c for c in classes if _missing(c) is None]
            if not classes:
                raise ImportError("No Extractor subclass found")
            if not valid:
                raise ImportError(f"Extractor class {classes[0].__name__} lacks '{_missing(classes[0])}'")
        except KeyboardInterrupt:
            raise
        except BaseException as exc:  # a broken plugin must never crash the app
            errors.append((stem, path, d, _describe(exc)))
            continue
        ok.extend((stem, path, c) for c in valid)

    result: dict[str, PluginInfo] = {}
    # Duplicate names: first wins. Directory order is alphabetical, so a plugin whose
    # file/folder name equals its extractor name takes precedence (stable sort).
    ok.sort(key=lambda f: f[0] != f[2].name)
    for stem, path, cls in ok:
        try:
            info = _build_info(cls, path)
        except Exception as exc:
            errors.append((stem, path, path.parent, _describe(exc)))
            continue
        if info.name in result:
            info.error = "Name bereits vergeben"
            result[_free_key(result, f"{info.name}@{stem}")] = info
        else:
            result[info.name] = info
    # Error entries come last so they can never take a working plugin's name.
    for stem, path, d, message in errors:
        result[_free_key(result, stem, f"{stem}@{d.name}")] = _error_info(stem, path, message)
    return result


def load_extractor(module_path: str, class_name: str) -> Extractor:
    """Instantiate a plugin class; works in a fresh (spawned) process."""
    path = Path(module_path)
    stem = path.parent.name if path.name == "__init__.py" else path.stem
    module = sys.modules.get(MODULE_PREFIX + stem)
    if module is None or Path(getattr(module, "__file__", "") or "") != path:
        module = _import_file(path, stem)
    return getattr(module, class_name)()
