import pickle
import sys
from pathlib import Path

from app.errors import NotFoundError
from app.plugins.base import SearchProfileDTO
from app.plugins.loader import discover_plugins, load_extractor
from app.plugins.registry import PluginRegistry

FAKE_PLUGINS = Path(__file__).parent / "fake_plugins"


def test_discovers_good_plugin():
    infos = discover_plugins([FAKE_PLUGINS])
    assert infos["good"].capabilities == {"search", "fetch"}
    assert infos["good"].error is None


def test_broken_plugin_listed_with_error():
    infos = discover_plugins([FAKE_PLUGINS])
    assert "kaputt" in infos["broken"].error
    assert infos["good"].error is None
    assert "jobtracker_plugin_broken" not in sys.modules


def test_duplicate_name_reported():
    infos = discover_plugins([FAKE_PLUGINS])
    assert infos["good@dup_name"].error == "Name bereits vergeben"
    assert infos["good"].module_path.endswith("good.py")


def test_for_url():
    registry = PluginRegistry(discover_plugins([FAKE_PLUGINS]))
    assert registry.for_url("https://good.test/job/1").name == "good"
    assert registry.for_url("https://x.test") is None


def test_registry_get_and_usable():
    registry = PluginRegistry(discover_plugins([FAKE_PLUGINS]))
    assert registry.get("good").name == "good"
    assert "broken" not in {i.name for i in registry.usable()}
    assert "broken" in {i.name for i in registry.all()}
    try:
        registry.get("nope")
    except NotFoundError as e:
        assert e.code == "plugin_not_found"
    else:
        raise AssertionError("expected NotFoundError")


def test_load_extractor_roundtrip():
    info = discover_plugins([FAKE_PLUGINS])["good"]
    ex = load_extractor(info.module_path, info.class_name)
    postings = ex.search(SearchProfileDTO(keywords="py"), info.settings_schema())
    assert len(postings) == 4  # max (3) per keyword + shared-1
    assert "py" in postings[0].title


def test_plugin_info_picklable():
    info = discover_plugins([FAKE_PLUGINS])["good"]
    assert pickle.loads(pickle.dumps(info)) == info


# --- fix round 1: robustness, packages, collisions (tmp plugin dirs) ---

HEADER = "from app.plugins.base import Capability, Extractor\n"


def _write(d: Path, name: str, body: str) -> None:
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(body)


def _ext(name: str, cls: str = "E", extra: str = "") -> str:
    return (
        f"{HEADER}\nclass {cls}(Extractor):\n    name = {name!r}\n    display_name = {name!r}\n"
        f"    capabilities = {{Capability.SEARCH, Capability.FETCH}}\n{extra}"
    )


def test_package_plugin_with_reexport_is_discovered(tmp_path):
    pkg = tmp_path / "pkgplug"
    _write(pkg, "impl.py", _ext("pkgex", "PkgEx", "    url_patterns = [r'https://pkg\\.test/.*']\n"))
    _write(pkg, "__init__.py", "from .impl import PkgEx\n")
    infos = discover_plugins([tmp_path])
    info = infos["pkgex"]
    assert info.error is None and info.class_name == "PkgEx"
    assert Path(info.module_path) == (pkg / "__init__.py").resolve()
    ex = load_extractor(info.module_path, info.class_name)
    assert type(ex).__name__ == "PkgEx"


def test_package_loads_in_fresh_process(tmp_path):
    import subprocess

    pkg = tmp_path / "pkgplug"
    _write(pkg, "impl.py", _ext("pkgex", "PkgEx"))
    _write(pkg, "__init__.py", "from .impl import PkgEx\n")
    code = (
        "from app.plugins.loader import load_extractor;"
        f"print(type(load_extractor({str(pkg / '__init__.py')!r}, 'PkgEx')).__name__)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd="/")
    assert out.stdout.strip() == "PkgEx", out.stderr


def test_class_without_name_does_not_crash(tmp_path):
    _write(tmp_path, "noname.py", f"{HEADER}\nclass NoName(Extractor):\n    pass\n")
    infos = discover_plugins([tmp_path])
    assert infos["noname"].error == "Extractor class NoName lacks 'name'"


def test_intermediate_base_is_ignored(tmp_path):
    _write(
        tmp_path,
        "withbase.py",
        f"{HEADER}\nclass Base(Extractor):\n    pass\n\n"
        "class Real(Base):\n    name = 'real'\n    display_name = 'Real'\n"
        "    capabilities = {Capability.SEARCH}\n",
    )
    infos = discover_plugins([tmp_path])
    assert infos["real"].error is None and infos["real"].class_name == "Real"
    assert "withbase" not in infos


def test_sys_exit_at_module_level_is_contained(tmp_path):
    _write(tmp_path, "exits.py", "import sys\nsys.exit(3)\n")
    _write(tmp_path, "fine.py", _ext("fine"))
    infos = discover_plugins([tmp_path])
    assert "SystemExit" in infos["exits"].error
    assert infos["fine"].error is None
    assert "jobtracker_plugin_exits" not in sys.modules


def test_error_entry_does_not_steal_working_name(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    _write(a, "good.py", "raise ImportError('kaputt')\n")
    _write(b, "good.py", _ext("good"))
    infos = discover_plugins([a, b])
    assert infos["good"].error is None
    assert Path(infos["good"].module_path).parent == b.resolve()
    assert "kaputt" in infos["good@a"].error


def test_invalid_regex_is_plugin_error(tmp_path):
    _write(tmp_path, "badre.py", _ext("badre", extra="    url_patterns = ['(unclosed']\n"))
    infos = discover_plugins([tmp_path])
    assert infos["badre"].error is not None
    assert PluginRegistry(infos).for_url("https://x.test") is None


def test_module_path_is_absolute(tmp_path, monkeypatch):
    _write(tmp_path / "p", "abs.py", _ext("abs"))
    monkeypatch.chdir(tmp_path)
    info = discover_plugins([Path("p")])["abs"]
    assert Path(info.module_path).is_absolute()
