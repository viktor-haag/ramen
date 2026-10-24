from fastapi import APIRouter, Request

from app.services import admin

router = APIRouter()


@router.post("/admin/clear-feed")
def clear_feed(request: Request) -> dict[str, int]:
    state = request.app.state
    with state.run_service.db_lock:  # from the running-check until the commit
        with state.session_factory() as session:
            result = admin.clear_feed(session)
            session.commit()
        state.fit_queue.discard_all()  # R4: after the commit, so a refused action keeps the queue
    return result


@router.post("/admin/reset")
def reset(request: Request) -> dict[str, dict[str, int]]:
    state = request.app.state
    with state.run_service.db_lock:
        with state.session_factory() as session:
            result = admin.reset_all(session)
            session.commit()
        state.fit_queue.discard_all()
    state.scheduler.sync()  # first: the data is gone, the scheduler must not outlive it
    admin.clear_attachments_dir(state.settings.attachments_dir)  # after the commit, best effort
    admin.clear_attachments_dir(state.settings.profile_dir)  # same: empty the folder, keep it
    return result


@router.post("/admin/delete-profile")
def delete_profile(request: Request) -> dict[str, int]:
    state = request.app.state
    with state.run_service.db_lock:
        with state.session_factory() as session:
            result, stored_paths = admin.delete_profile(session)
            session.commit()
        state.fit_queue.discard_all()
    admin.discard_profile_files(state.settings, stored_paths)  # after the commit, best effort
    return result
