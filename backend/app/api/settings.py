"""模型配置（BYOK）：界面里填 base_url / model / api_key。

优先级：工作空间配置 > 环境变量。key 加密落库，接口只回显掩码。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Auditor
from app.config import settings
from app.deps import Principal, get_auditor, get_principal, get_session
from app.engine.llm import probe_endpoint
from app.models import LlmSetting
from app.schemas import LlmSettingIn, LlmSettingOut, LlmTestIn, LlmTestOut
from app.security import get_secret_box

router = APIRouter(prefix="/settings", tags=["settings"])


def _mask(key: str) -> str:
    if len(key) <= 10:
        return "已配置"
    return f"{key[:5]}…{key[-4:]}"


async def _load(session: AsyncSession, workspace_id: int) -> LlmSetting | None:
    return await session.scalar(
        select(LlmSetting).where(LlmSetting.workspace_id == workspace_id)
    )


def _to_out(row: LlmSetting | None) -> LlmSettingOut:
    if row is not None and row.api_key_enc:
        plaintext = get_secret_box().decrypt(row.api_key_enc)
        return LlmSettingOut(
            base_url=row.base_url or settings.llm_base_url,
            model=row.model or settings.llm_model,
            api_key_masked=_mask(plaintext),
            configured=True,
            source="workspace",
            env_model=settings.llm_model,
            updated_at=row.updated_at,
        )

    env_ok = bool(settings.llm_api_key)
    return LlmSettingOut(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        api_key_masked=None,
        configured=env_ok,
        source="env" if env_ok else "none",
        env_model=settings.llm_model,
        updated_at=row.updated_at if row else None,
    )


@router.get("/llm", response_model=LlmSettingOut)
async def get_llm_setting(
    user: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> LlmSettingOut:
    return _to_out(await _load(session, user.workspace_id))


@router.put("/llm", response_model=LlmSettingOut)
async def save_llm_setting(
    body: LlmSettingIn,
    user: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> LlmSettingOut:
    row = await _load(session, user.workspace_id)
    if row is None:
        row = LlmSetting(workspace_id=user.workspace_id)
        session.add(row)

    if body.base_url.strip():
        row.base_url = body.base_url.strip().rstrip("/")
    if body.model.strip():
        row.model = body.model.strip()
    if body.api_key is not None:
        key = body.api_key.strip()
        row.api_key_enc = get_secret_box().encrypt(key) if key else None

    await session.commit()
    await session.refresh(row)

    await auditor.log(
        "settings.llm",
        target_type="workspace",
        target_id=user.workspace_id,
        detail={
            "base_url": row.base_url,
            "model": row.model,
            "key_changed": body.api_key is not None,
        },
    )
    return _to_out(row)


@router.post("/llm/test", response_model=LlmTestOut)
async def test_llm_setting(
    body: LlmTestIn,
    user: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> LlmTestOut:
    row = await _load(session, user.workspace_id)

    base_url = (body.base_url or (row.base_url if row else "") or settings.llm_base_url).rstrip("/")
    model = body.model or (row.model if row else "") or settings.llm_model

    if body.api_key is not None:
        api_key = body.api_key
    elif row is not None and row.api_key_enc:
        api_key = get_secret_box().decrypt(row.api_key_enc)
    else:
        api_key = settings.llm_api_key

    result = await probe_endpoint(base_url=base_url, api_key=api_key, model=model)
    await auditor.log(
        "settings.llm_test",
        result="ok" if result.ok else "error",
        detail={"base_url": base_url, "model": model, "message": result.message[:200]},
    )
    return LlmTestOut(
        ok=result.ok,
        message=result.message,
        latency_ms=result.latency_ms,
        model=result.model or model,
    )