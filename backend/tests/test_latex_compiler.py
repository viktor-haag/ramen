import os
import shutil
import sys
import textwrap

import pytest

from app.config import Settings
from app.latex import guard
from app.latex.compiler import CompileResult, TectonicCompiler, error_excerpt
from app.latex.default_template import DEFAULT_TEMPLATE

needs_tectonic = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic not installed"
)

FAKE = textwrap.dedent(
    """
    import os, sys, time
    tex = open("main.tex", encoding="utf-8").read()
    if "SLEEP" in tex:
        time.sleep(30)
    if "FAIL" in tex:
        print("error: failed in " + os.getcwd())
        print("posix: " + os.getcwd().replace(chr(92), "/"))
        print("! Undefined control sequence.")
        sys.exit(1)
    if "NOPDF" in tex:
        sys.exit(0)
    open("main.pdf", "wb").write(b"%PDF-fake")
    open("args.txt", "w").write(" ".join(sys.argv[1:]))
    open("env.txt", "w").write(os.environ.get("TECTONIC_UNTRUSTED_MODE", ""))
    """
)


@pytest.fixture
def fake_exe(tmp_path):
    script = tmp_path / "fake_tectonic.py"
    script.write_text(FAKE, encoding="utf-8")
    if os.name == "nt":
        wrapper = tmp_path / "fake_tectonic.bat"
        wrapper.write_text(f'@"{sys.executable}" "{script}" %*\r\n')
    else:
        wrapper = tmp_path / "fake_tectonic"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n')
        wrapper.chmod(0o755)
    return wrapper


def make_fake_popen(seen):
    class FakePopen:
        returncode = 0
        pid = 1

        def __init__(self, args, **kw):
            seen["args"], seen["env"], seen["kw"] = args, kw["env"], kw
            open(os.path.join(kw["cwd"], "main.pdf"), "wb").write(b"%PDF-x")

        def communicate(self, timeout=None):
            return b"", b""

    return FakePopen


def test_unavailable_without_executable(tmp_path):
    c = TectonicCompiler(None, tmp_path / "cache")
    assert c.available() is False
    r = c.compile("x")
    assert r.pdf is None and r.error_code == "latex_unavailable"


def test_fake_success(fake_exe, tmp_path):
    c = TectonicCompiler(fake_exe, tmp_path / "cache")
    assert c.available() is True
    r = c.compile("hello")
    assert r == CompileResult(pdf=b"%PDF-fake", log=r.log, error_code=None)


def test_fake_failure_masks_paths(fake_exe, tmp_path):
    c = TectonicCompiler(fake_exe, tmp_path / "cache")
    r = c.compile("FAIL")
    assert r.pdf is None and r.error_code == "latex_failed"
    assert "<tmp>" in r.log
    assert "posix: <tmp>" in r.log
    assert str(tmp_path) not in r.log
    assert "Undefined control sequence" in r.log


def test_oserror_is_unavailable(tmp_path):
    exe = tmp_path / "bad.exe"
    exe.write_text("not an executable")
    exe.chmod(0o644)
    r = TectonicCompiler(exe, tmp_path / "cache").compile("x")
    assert r.error_code == "latex_unavailable" and r.log


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX user/group handling")
def test_user_branch(tmp_path, monkeypatch):
    from app.latex import compiler as mod

    chowned, seen = [], {}
    monkeypatch.setattr(mod.shutil, "chown", lambda p, u, g: chowned.append((str(p), u, g)))
    monkeypatch.setattr(mod.subprocess, "Popen", make_fake_popen(seen))
    exe = tmp_path / "t"
    exe.write_text("")
    cache = tmp_path / "cache"
    assert TectonicCompiler(exe, cache, user="ramen-tex").compile("x").pdf == b"%PDF-x"
    assert (str(cache), "ramen-tex", "ramen-tex") in chowned
    assert any(p == seen["kw"]["cwd"] for p, _, _ in chowned)
    assert seen["kw"]["user"] == "ramen-tex" and seen["kw"]["group"] == "ramen-tex"


def test_no_pdf_is_failure(fake_exe, tmp_path):
    r = TectonicCompiler(fake_exe, tmp_path / "cache").compile("NOPDF")
    assert r.error_code == "latex_failed"


def test_fake_timeout(fake_exe, tmp_path):
    import time

    t0 = time.monotonic()
    r = TectonicCompiler(fake_exe, tmp_path / "cache", timeout=0.5).compile("SLEEP")
    assert time.monotonic() - t0 < 8
    assert r.pdf is None and r.error_code == "latex_timeout"


def test_args_and_env(tmp_path, monkeypatch):
    from app.latex import compiler as mod

    seen = {}

    monkeypatch.setenv("JOBTRACKER_SECRET", "s3cret")
    monkeypatch.setattr(mod.subprocess, "Popen", make_fake_popen(seen))
    (tmp_path / "tectonic").write_text("")
    c = TectonicCompiler(tmp_path / "tectonic", tmp_path / "cache")
    assert c.compile("x").pdf == b"%PDF-x"
    assert "--untrusted" in seen["args"] and "main.tex" in seen["args"]
    assert seen["env"]["TECTONIC_UNTRUSTED_MODE"] == "1"
    assert seen["env"]["TECTONIC_CACHE_DIR"] == str(tmp_path / "cache")
    assert "user" not in seen["kw"]
    assert "JOBTRACKER_SECRET" not in seen["env"]
    assert "PATH" in seen["env"]


def test_error_excerpt_two_blocks():
    log = "noise\n" * 50 + "! First error.\nl.1 a\nl.2 b\nl.3 c\n" + "more\n" * 50
    log += "error: second\nx\ny\nz\n" + "tail\n" * 500
    out = error_excerpt(log)
    assert "First error" in out and "second" in out
    assert len(out) <= 3000


def test_error_excerpt_fallback_tail():
    out = error_excerpt("a" * 5000 + "END", limit=100)
    assert len(out) == 100 and out.endswith("END")


def test_settings_properties(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBTRACKER_TECTONIC", str(tmp_path / "t"))
    monkeypatch.setenv("JOBTRACKER_TECTONIC_USER", "nobody")
    s = Settings(data_dir=tmp_path)
    assert s.tectonic == tmp_path / "t" and s.tectonic_user == "nobody"
    assert s.cover_letters_dir == tmp_path / "cover_letters"
    assert s.tectonic_cache_dir == tmp_path / "tectonic_cache"


def test_from_settings_cache_env(tmp_path, monkeypatch):
    s = Settings(data_dir=tmp_path, tectonic=tmp_path / "t")
    monkeypatch.delenv("TECTONIC_CACHE_DIR", raising=False)
    assert TectonicCompiler.from_settings(s).cache_dir == tmp_path / "tectonic_cache"
    monkeypatch.setenv("TECTONIC_CACHE_DIR", str(tmp_path / "envcache"))
    assert TectonicCompiler.from_settings(s).cache_dir == tmp_path / "envcache"


@pytest.mark.tectonic
@needs_tectonic
def test_default_template_compiles(tmp_path):
    r = TectonicCompiler(shutil.which("tectonic"), tmp_path / "cache", timeout=600).compile(
        DEFAULT_TEMPLATE
    )
    assert r.error_code is None, r.log
    assert r.pdf.startswith(b"%PDF")


@pytest.mark.tectonic
@needs_tectonic
def test_tectonic_reads_absolute_paths_without_guard(tmp_path):
    # Documents why the guard (Task 3) is necessary: untrusted mode does NOT stop
    # absolute-path input. If this test breaks, Tectonic changed behavior.
    secret = tmp_path / "secret.txt"
    secret.write_text(r"\def\SECRETOK{}", encoding="utf-8")
    doc = (
        r"\documentclass{article}\begin{document}\input{" + secret.as_posix() + "}"
        + r"\ifdefined\SECRETOK\else\errmessage{not read}\fi Done.\end{document}"
    )
    r = TectonicCompiler(shutil.which("tectonic"), tmp_path / "cache", timeout=600).compile(doc)
    assert r.error_code is None, r.log
    assert r.pdf.startswith(b"%PDF")


def test_guard_blocks_same_document(tmp_path):
    marker = r"\begin{document}"
    line = r"\input{" + (tmp_path / "s.txt").as_posix() + "}"
    doc = DEFAULT_TEMPLATE.replace(marker, marker + chr(10) + line, 1)
    v = guard.check(doc, DEFAULT_TEMPLATE)
    assert v is not None and v.command == r"\input"


@pytest.mark.tectonic
@needs_tectonic
def test_infinite_loop_times_out(tmp_path):
    doc = r"\documentclass{article}\begin{document}\def\x{\x}\x\end{document}"
    r = TectonicCompiler(shutil.which("tectonic"), tmp_path / "cache", timeout=5).compile(doc)
    assert r.error_code == "latex_timeout"
