"""开发者 API Key 管理：创建、列表、吊销。

明文只在创建时返回一次；库里只存 SHA-256 哈希。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.apikeys import generate_api_key
from app.audit import Auditor
from app.deps import Principal, get_auditor, get_principal, get_session
from app.models import ApiKey, utcnow
from app.schemas import ApiKeyCreatedOut, ApiKeyIn, ApiKeyOut

router = APIRouter(prefix="/keys", tags=["keys"])


def _to_out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked=row.revoked_at is not None,
    )


@router.get("", response_model=list[ApiKeyOut])
async def list_keys(
    user: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> list[ApiKeyOut]:
    rows = await session.scalars(
        select(ApiKey).where(ApiKey.workspace_id == user.workspace_id).order_by(ApiKey.id.desc())
    )
    return [_to_out(row) for row in rows]


@router.post("", response_model=ApiKeyCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_key(
    body: ApiKeyIn,
    user: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> ApiKeyCreatedOut:
    plaintext, prefix, key_hash = generate_api_key()
    row = ApiKey(
        workspace_id=user.workspace_id,
        name=body.name.strip() or "default",
        prefix=prefix,
        key_hash=key_hash,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    await auditor.log(
        "apikey.create",
        target_type="api_key",
        target_id=row.id,
        detail={"name": row.name, "prefix": row.prefix},
    )
    return ApiKeyCreatedOut(key=plaintext, item=_to_out(row))


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: int,
    user: Principal = Depends(get_principal),
    auditor: Auditor = Depends(get_auditor),
    session: AsyncSession = Depends(get_session),
) -> None:
    row = await session.get(ApiKey, key_id)
    if row is None or row.workspace_id != user.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "API Key 不存在")
    if row.revoked_at is None:
        row.revoked_at = utcnow()
        await session.commit()
        await auditor.log(
            "apikey.revoke",
            target_type="api_key",
            target_id=row.id,
            detail={"name": row.name, "prefix": row.prefix},
        )