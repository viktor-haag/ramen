from sqlalchemy import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PluginSetting(Base):
    __tablename__ = "plugin_setting"

    plugin: Mapped[str] = mapped_column(primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
