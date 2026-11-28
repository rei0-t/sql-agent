"""模型配置（BYOK）：一个工作空间可以有多档，对话页当场切换。

三条设计约束：

1. **平台额度是一档，但它不暴露端点**。试用用户看得到"平台额度（试用）· 还剩 N 次"，
   看不到站点用的 Base URL 与模型名 —— 那是站长的配置，不是他的。
2. **Key 只进不出**。落库存密文，接口只回显 ``sk-ab…wxyz`` 形式的掩码。
3. **旧接口不废掉**。``/settings/llm`` 仍然可用，它读写"默认档"，
   老客户端与脚本不受影响。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import Auditor
from app.config import settings
from app.deps import Principal, get_auditor, get_principal, get_session
from app.engine.llm import probe_endpoint
from app.models import ModelProfile
from app.netguard import UnsafeUrlError, check_base_url
from app.models import Workspace
from app.quota import limit, remaining
from app.schemas import (
    LlmSettingIn,
    LlmSettingOut,
    LlmTestIn,
    LlmTestOut,
    ModelProfileIn,
    ModelProfileListOut,
    ModelProfileOut,
    PlatformProfileOut,
)
from app.security import get_secret_box

router = APIRouter(prefix="/settings", tags=["settings"])

PLATFORM_LABEL = "平台额度（试用）"


def _safe_base_url(url: str) -> str:
    """校验用户填的模型端点：不允许指向内网（BYOK 的 SSRF 面）。"""
    try:
        return check_base_url(url, allow_private=settings.llm_allow_private_hosts)
    except UnsafeUrlError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


def _mask(key: str) -> str:
    if len(key) <= 10:
        return "已配置"
    return f"{key[:5]}…{key[-4:]}"


def _to_out(row: ModelProfile) -> ModelProfileOut:
    plaintext = get_secret_box().decrypt(row.api_key_enc or "")
    return ModelProfileOut(
        id=row.id,
        label=row.label or "我的模型",
        base_url=row.base_url,
        model=row.model,
        api_key_masked=_mask(plaintext),
        created_at=row.created_at,
        last_used_at=row.last_used_at,
    )


async def profiles_of(session: AsyncSession, workspace_id: int) -> list[ModelProfile]:
    result = await session.scalars(
        select(ModelProfile)
        .where(ModelProfile.workspace_id == workspace_id)
        .order_by(ModelProfile.id)
    )
    return list(result)


async def default_profile(session: AsyncSession, workspace_id: int) -> ModelProfile | None:
    rows = await profiles_of(session, workspace_id)
    return rows[0] if rows else None


# ---------------- 多档配置 ----------------


@router.get("/models", response_model=ModelProfileListOut)
async def list_models(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> ModelProfileListOut:
    rows = await profiles_of(session, principal.workspace_id)
    # 平台这一档永远按"已用掉多少次"算，不因用户自带 Key 而豁免
    left = None
    if not principal.is_admin and limit() > 0:
        workspace = await session.get(Workspace, principal.workspace_id)
        left = remaining(workspace.questions_used if workspace else 0)
    return ModelProfileListOut(
        platform=PlatformProfileOut(
            label=PLATFORM_LABEL,
            available=bool(settings.llm_api_key),
            remaining=left,
        ),
        items=[_to_out(row) for row in rows],
    )


@router.post("/models", response_model=ModelProfileOut, status_code=status.HTTP_201_CREATED)
async def create_model(
    body: ModelProfileIn,
    principal: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> ModelProfileOut:
    row = ModelProfile(
        workspace_id=principal.workspace_id,
        label=(body.label or "我的模型").strip()[:64],
        base_url=_safe_base_url(body.base_url),
        model=body.model.strip(),
        api_key_enc=get_secret_box().encrypt(body.api_key.strip()),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await auditor.log(
        "settings.model.create",
        target_type="model_profile",
        target_id=row.id,
        detail={"label": row.label, "base_url": row.base_url, "model": row.model},
    )
    return _to_out(row)


@router.delete("/models/{profile_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_model(
    profile_id: int,
    principal: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> Response:
    row = await session.scalar(
        select(ModelProfile).where(
            ModelProfile.id == profile_id,
            ModelProfile.workspace_id == principal.workspace_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这档配置不存在")
    await session.delete(row)
    await session.commit()
    await auditor.log(
        "settings.model.delete", target_type="model_profile", target_id=profile_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/models/{profile_id}/test", response_model=LlmTestOut)
async def test_model(
    profile_id: int,
    principal: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> LlmTestOut:
    row = await session.scalar(
        select(ModelProfile).where(
            ModelProfile.id == profile_id,
            ModelProfile.workspace_id == principal.workspace_id,
        )
    )
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "这档配置不存在")

    result = await probe_endpoint(
        base_url=row.base_url or settings.llm_base_url,
        api_key=get_secret_box().decrypt(row.api_key_enc or ""),
        model=row.model or settings.llm_model,
    )
    await auditor.log(
        "settings.model.test",
        result="ok" if result.ok else "error",
        target_type="model_profile",
        target_id=profile_id,
        detail={"message": result.message[:200]},
    )
    return LlmTestOut(
        ok=result.ok,
        message=result.message,
        latency_ms=result.latency_ms,
        model=result.model or row.model,
    )


# ---------------- 旧接口：读写「默认档」 ----------------


@router.get("/llm", response_model=LlmSettingOut)
async def get_llm_setting(
    principal: Principal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> LlmSettingOut:
    """兼容接口。没有自己的配置时**不回传**站点的端点与模型名。"""
    row = await default_profile(session, principal.workspace_id)
    if row is not None:
        # 有自己的一档：回显**他自己填的**值；没填 Key 时状态按环境变量算
        masked = _mask(get_secret_box().decrypt(row.api_key_enc)) if row.api_key_enc else None
        env_ok = bool(settings.llm_api_key)
        return LlmSettingOut(
            base_url=row.base_url,
            model=row.model,
            api_key_masked=masked,
            configured=bool(row.api_key_enc) or env_ok,
            source="workspace" if row.api_key_enc else ("env" if env_ok else "none"),
            env_model=settings.llm_model if principal.is_admin else "",
            updated_at=row.created_at,
        )

    env_ok = bool(settings.llm_api_key)
    return LlmSettingOut(
        base_url="",  # 站点的端点不外泄
        model="",
        api_key_masked=None,
        configured=env_ok,
        source="env" if env_ok else "none",
        env_model=settings.llm_model if principal.is_admin else "",
        updated_at=None,
    )


@router.put("/llm", response_model=LlmSettingOut)
async def save_llm_setting(
    body: LlmSettingIn,
    principal: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> LlmSettingOut:
    row = await default_profile(session, principal.workspace_id)
    if row is None:
        row = ModelProfile(workspace_id=principal.workspace_id, label="默认模型")
        session.add(row)

    if body.base_url.strip():
        row.base_url = _safe_base_url(body.base_url)
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
        target_id=principal.workspace_id,
        detail={"model": row.model, "key_changed": body.api_key is not None},
    )
    return await get_llm_setting(principal=principal, session=session)


@router.post("/llm/test", response_model=LlmTestOut)
async def test_llm_setting(
    body: LlmTestIn,
    principal: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> LlmTestOut:
    row = await default_profile(session, principal.workspace_id)

    base_url = _safe_base_url(
        body.base_url or (row.base_url if row else "") or settings.llm_base_url
    )
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
        detail={"model": model, "message": result.message[:200]},
    )
    return LlmTestOut(
        ok=result.ok,
        message=result.message,
        latency_ms=result.latency_ms,
        model=result.model or model,
    )