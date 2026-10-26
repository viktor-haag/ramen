"""Tectonic wrapper: compiles LaTeX source to PDF in an isolated temp directory.

The compiler compiles whatever it is given; callers must run ``guard.check`` first.
"""

import os
import shutil
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

    def compile(self, tex: str) -> CompileResult: ...


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
        timeout: float = 60.0,
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

    def compile(self, tex: str) -> CompileResult:
        if not self.available():
            return CompileResult(None, None, "latex_unavailable")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "main.tex").write_text(tex, encoding="utf-8")
            kwargs: dict = {}
            if self.user:  # POSIX only (Docker)
                shutil.chown(tmp_path, self.user, self.user)
                shutil.chown(tmp_path / "main.tex", self.user, self.user)
                kwargs = {"user": self.user, "group": self.user}
            env = {
                **os.environ,
                "TECTONIC_UNTRUSTED_MODE": "1",
                "TECTONIC_CACHE_DIR": str(self.cache_dir),
            }
            args = [str(self.executable), "-X", "compile", "--untrusted", "main.tex"]
            with _LOCK:
                try:
                    proc = subprocess.run(
                        args,
                        cwd=tmp,
                        env=env,
                        capture_output=True,
                        timeout=self.timeout,
                        **kwargs,
                    )
                except subprocess.TimeoutExpired:
                    return CompileResult(None, None, "latex_timeout")
                log = (proc.stdout + proc.stderr).decode("utf-8", errors="replace")
                log = log.replace(tmp, "<tmp>").replace(str(self.cache_dir), "<cache>")
                pdf_path = tmp_path / "main.pdf"
                if proc.returncode != 0 or not pdf_path.exists():
                    return CompileResult(None, log, "latex_failed")
                return CompileResult(pdf_path.read_bytes(), log, None)
