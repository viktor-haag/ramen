from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JOBTRACKER_")

    data_dir: Path = REPO_ROOT / "data"
    plugin_dirs: Annotated[list[Path], NoDecode] = [REPO_ROOT / "plugins"]
    pool_size: int = 2
    port: int = 8000
    frontend_dist: Path | None = None
    update_check: bool = True
    update_repo: str = "viktor-haag/ramen"
    tectonic: Path | None = None
    tectonic_user: str | None = None

    @field_validator("plugin_dirs", mode="before")
    @classmethod
    def _split_plugin_dirs(cls, v):
        if isinstance(v, str):
            return [Path(p) for p in v.split(";") if p.strip()]
        return v

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.data_dir / 'jobtracker.db'}"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def profile_dir(self) -> Path:
        return self.data_dir / "profile"

    @property
    def cover_letters_dir(self) -> Path:
        return self.data_dir / "cover_letters"

    @property
    def tectonic_cache_dir(self) -> Path:
        return self.data_dir / "tectonic_cache"
