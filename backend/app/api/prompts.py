from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.prompts import PromptIn, PromptOut
from app.services import prompts as prompts_service

router = APIRouter()


@router.get("/prompts", response_model=list[PromptOut])
def list_all(session: Session = Depends(get_session)) -> list[PromptOut]:
    return prompts_service.list_prompts(session)


@router.put("/prompts/{purpose}", response_model=PromptOut)
def update(purpose: str, data: PromptIn, session: Session = Depends(get_session)) -> PromptOut:
    out = prompts_service.set_prompt(session, purpose, data.text)
    session.commit()
    return out


@router.delete("/prompts/{purpose}", response_model=PromptOut)
def reset(purpose: str, session: Session = Depends(get_session)) -> PromptOut:
    out = prompts_service.reset_prompt(session, purpose)
    session.commit()
    return out
