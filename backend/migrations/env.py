from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401  (register tables)
from app.db import Base, UTCDateTime

config = context.config
target_metadata = Base.metadata


def _render_item(type_, obj, autogen_context):
    if type_ == "type" and isinstance(obj, UTCDateTime):
        autogen_context.imports.add("import app.db")
        return "app.db.UTCDateTime()"
    return False


_opts = dict(
    target_metadata=target_metadata,
    render_as_batch=True,
    compare_type=True,
    render_item=_render_item,
)


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True, **_opts)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, **_opts)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
