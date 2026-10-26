"""Tectonic wrapper: compiles LaTeX source to PDF in an isolated temp directory.

The compiler compiles whatever it is given; callers must run ``guard.check`` first.
"""

import os
import re
import shutil
import signal
import subprocess
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings

_LOCK = threading.Lock()


@dataclass(frozen=True)
class CompileResult:
    pdf: bytes | None
    log: str | None
    error_code: str | None  # None | "latex_unavailable" | "latex_failed" | "latex_timeout"


class Compiler(Protocol):
    def available(self) -> bool: ...

    def compile(self, tex: str, timeout: float | None = None) -> CompileResult: ...


def error_excerpt(log: str, limit: int = 3000) -> str:
    """Error lines ('!' or 'error:') with 3 following lines each, else the log tail."""
    lines = log.splitlines()
    keep: list[str] = []
    last = -1
    for i, line in enumerate(lines):
        if line.startswith("!") or line.startswith("error:"):
            start = max(i, last + 1)
            keep.extend(lines[start : i + 4])
            last = i + 3
    if not keep:
        return log[-limit:]
    return "\n".join(keep)[:limit]


class TectonicCompiler:
    def __init__(
        self,
        executable: Path | None,
        cache_dir: Path,
        user: str | None = None,
        timeout: float = 180.0,
    ):
        self.executable = Path(executable) if executable else None
        self.cache_dir = Path(cache_dir)
        self.user = user
        self.timeout = timeout

    @classmethod
    def from_settings(cls, s: Settings) -> "TectonicCompiler":
        exe = s.tectonic or (Path(w) if (w := shutil.which("tectonic")) else None)
        env_cache = os.environ.get("TECTONIC_CACHE_DIR")
        cache = Path(env_cache) if env_cache else s.tectonic_cache_dir
        return cls(exe, cache, user=s.tectonic_user)

    def available(self) -> bool:
        return self.executable is not None and self.executable.exists()

    def _env(self) -> dict[str, str]:
        keep = ["PATH", "HOME", "USERPROFILE", "TEMP", "TMP", "TMPDIR", "SYSTEMROOT", "LANG", "LC_ALL"]
        env = {k: os.environ[k] for k in keep if k in os.environ}
        env["TECTONIC_UNTRUSTED_MODE"] = "1"
        env["TECTONIC_CACHE_DIR"] = str(self.cache_dir)
        return env

    def _mask(self, log: str, tmp: str) -> str:
        variants: list[tuple[str, str]] = []
        for base, label in ((tmp, "<tmp>"), (str(self.cache_dir), "<cache>")):
            p = Path(base)
            for v in {base, p.as_posix(), str(p.resolve()), p.resolve().as_posix()}:
                variants.append((v, label))
        variants.sort(key=lambda t: len(t[0]), reverse=True)
        for v, label in variants:
            if os.name == "nt":
                log = re.sub(re.escape(v), lambda _m, lb=label: lb, log, flags=re.IGNORECASE)
            else:
                log = log.replace(v, label)
        return log

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (OSError, subprocess.SubprocessError):
            pass
        try:
            proc.kill()
        except OSError:
            pass

    def compile(self, tex: str, timeout: float | None = None) -> CompileResult:
        """`timeout` (seconds) overrides the instance default for this run; waiting for the lock is not counted."""
        timeout = self.timeout if timeout is None else timeout
        if not self.available():
            return CompileResult(None, None, "latex_unavailable")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        if self.user:  # POSIX only (Docker): Tectonic must be able to write the cache
            shutil.chown(self.cache_dir, self.user, self.user)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
            kwargs: dict = {}
            if self.user:
                shutil.chown(tmp_path, self.user, self.user)
                shutil.chown(tmp_path / "main.tex", self.user, self.user)
                kwargs = {"user": self.user, "group": self.user}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            args = [str(self.executable), "-X", "compile", "--untrusted", "main.tex"]
            with _LOCK:
                try:
                    proc = subprocess.Popen(
                        args,
                        cwd=tmp,
                        env=self._env(),
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        **kwargs,
                    )
                except OSError as e:
                    return CompileResult(None, str(e), "latex_unavailable")
                try:
                    out, err = proc.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self._kill_tree(proc)
                    try:
                        proc.communicate(timeout=10)
                    except subprocess.TimeoutExpired:
                        pass
                    return CompileResult(None, None, "latex_timeout")
                log = self._mask((out + err).decode("utf-8", errors="replace"), tmp)
                pdf_path = tmp_path / "main.pdf"
                if proc.returncode != 0 or not pdf_path.exists():
                    return CompileResult(None, log, "latex_failed")
                return CompileResult(pdf_path.read_bytes(), log, None)
