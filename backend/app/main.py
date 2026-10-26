import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    admin,
    applications,
    dashboard,
    details,
    feed,
    fit as fit_api,
    health,
    llm,
    me,
    plugins,
    postings,
    profiles,
    prompts as prompts_api,
    runs,
    settings as settings_api,
    version as version_api,
)
from app.config import Settings
from app.cover_letters.jobs import CoverLetterJobs
from app.db import make_engine, make_session_factory
from app.db_migrate import upgrade
from app.errors import install_handlers
from app.fit.queue import FitQueue
from app.latex.compiler import TectonicCompiler
from app.plugins.loader import discover_plugins
from app.plugins.registry import PluginRegistry
from app.runner.pool import RunnerPool
from app.runner.spacing import StartSpacer
from app.runner.scheduler import SchedulerManager
from app.runner.service import RunService
from app.services import settings as settings_service
from app.services.geocode import Geocoder
from app.services.updates import UpdateChecker
from app.version import __version__

log = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.attachments_dir.mkdir(parents=True, exist_ok=True)
    settings.cover_letters_dir.mkdir(parents=True, exist_ok=True)
    engine = make_engine(settings.db_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        upgrade(settings.db_url)
        fit_queue = FitQueue(app.state.session_factory)
        app.state.fit_queue = fit_queue
        with app.state.session_factory() as session:
            fit_queue.recover(session)
            session.commit()
        cover_letter_jobs = CoverLetterJobs(
            app.state.session_factory, settings, TectonicCompiler.from_settings(settings)
        )
        app.state.cover_letter_jobs = cover_letter_jobs
        with app.state.session_factory() as session:
            cover_letter_jobs.recover(session)
            session.commit()
        pool = RunnerPool(settings.pool_size)  # workers start lazily on the first run
        app.state.runner_pool = pool
        app.state.run_service = RunService(
            app.state.session_factory, app.state.registry, pool,
            on_new_postings=fit_queue.enqueue_auto, spacer=StartSpacer(),
        )
        with app.state.session_factory() as session:
            app.state.run_service.recover_stale_runs(session)
            session.commit()
        scheduler = SchedulerManager(app.state.run_service, app.state.session_factory)
        app.state.scheduler = scheduler
        try:
            scheduler.start()
            scheduler.sync()
            if settings.update_check:
                scheduler.add_update_check(app.state.run_update_check)
            yield
        finally:
            scheduler.shutdown()
            app.state.run_service.close()
            pool.close()
            fit_queue.shutdown()
            cover_letter_jobs.shutdown()
            engine.dispose()

    app = FastAPI(title="RAMEN", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = make_session_factory(engine)
    for plugin_dir in settings.plugin_dirs:
        if not plugin_dir.is_dir():
            log.warning("plugin directory %s does not exist", plugin_dir)
    discovered = discover_plugins(settings.plugin_dirs)
    log.info("loaded plugins: %s", ", ".join(sorted(discovered)) or "(none)")
    app.state.registry = PluginRegistry(discovered)
    app.state.geocoder = Geocoder()
    app.state.update_checker = UpdateChecker(settings.update_repo, __version__)

    def run_update_check() -> None:
        """Scheduled job: skipped while the app setting is off; never raises."""
        try:
            with app.state.session_factory() as session:
                if not settings_service.get_settings(session).update_check:
                    return
            app.state.update_checker.check()
        except Exception:
            log.exception("scheduled update check failed")

    app.state.run_update_check = run_update_check
    install_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
    app.include_router(feed.router, prefix="/api")
    app.include_router(fit_api.router, prefix="/api")
    app.include_router(applications.router, prefix="/api")
    app.include_router(details.router, prefix="/api")
    app.include_router(postings.router, prefix="/api")
    app.include_router(profiles.router, prefix="/api")
    app.include_router(runs.router, prefix="/api")
    app.include_router(plugins.router, prefix="/api")
    app.include_router(dashboard.router, prefix="/api")
    app.include_router(llm.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(prompts_api.router, prefix="/api")
    app.include_router(settings_api.router, prefix="/api")
    app.include_router(version_api.router, prefix="/api")

    dist = settings.frontend_dist.resolve() if settings.frontend_dist and settings.frontend_dist.is_dir() else None
    if dist is not None and (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            path = request.url.path
            if path == "/api" or path.startswith("/api/"):
                # unknown API path: the standard error body, for every method
                return JSONResponse(
                    status_code=404,
                    content={"code": "not_found", "params": {"path": path}, "detail": "Not found"},
                )
            if dist is not None and request.method in ("GET", "HEAD") and not path.startswith("/assets/"):
                return FileResponse(_static_file(dist, path.lstrip("/")) or dist / "index.html")
        return await http_exception_handler(request, exc)

    return app


def _static_file(dist: Path, path: str) -> Path | None:
    """The existing file below `dist` for a request path, or None (also for invalid or escaping paths)."""
    if not path:
        return None
    try:
        candidate = (dist / path).resolve()
        if candidate.is_file() and candidate.is_relative_to(dist):
            return candidate
    except (ValueError, OSError):
        pass
    return None
