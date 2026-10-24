from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.plugin import PluginOut, PluginUpdate
from app.services import plugins

router = APIRouter()


@router.get("/plugins", response_model=list[PluginOut])
def list_plugins(request: Request, session: Session = Depends(get_session)) -> list[PluginOut]:
    return plugins.list_plugins(session, request.app.state.registry)


@router.put("/plugins/{name}", response_model=PluginOut)
def update_plugin(
    name: str, body: PluginUpdate, request: Request, session: Session = Depends(get_session)
) -> PluginOut:
    out = plugins.update_plugin(session, request.app.state.registry, name, body.enabled, body.settings)
    session.commit()
    return out
