"""跨路由共用的小查询：只做「归属校验」与凭证读取，不含业务逻辑。

之所以单独一层：同一条隔离规则（数据源必须属于当前工作空间）原本在
chat / datasources / query 三处各写了一遍，改一处漏一处就是越权漏洞。
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Datasource
from app.security import get_secret_box


async def owned_datasource(
    session: AsyncSession, workspace_id: int, datasource_id: int
) -> Datasource:
    """取当前工作空间的数据源；不存在或不属于本空间都返回 404。

    刻意不区分「不存在」和「无权访问」：否则可以用 404/403 的差异探测别人的 id。
    """
    ds = await session.get(Datasource, datasource_id)
    if ds is None or ds.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "数据源不存在")
    return ds


def read_password(ds: Datasource) -> str:
    """解密只读口令。没有口令（如 SQLite）返回空串。"""
    if not ds.password_enc:
        return ""
    return get_secret_box().decrypt(ds.password_enc)


def snapshot(ds: Datasource) -> Datasource:
    """脱离 ORM 会话的副本。

    流式响应期间请求级 session 已经关闭，持有原对象会触发懒加载报错。
    按列复制而不是手抄字段：以后给 Datasource 加字段不会漏。
    """
    data = {column.key: getattr(ds, column.key) for column in Datasource.__mapper__.column_attrs}
    return Datasource(**data)