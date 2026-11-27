"""出站地址校验：用户填的模型端点不能指向内网。

背景：BYOK 允许每个人自己填 `base_url`，服务端会去请求它。如果没有校验，
任何人都能把它指到 `127.0.0.1`、`169.254.169.254`（云元数据）或内网服务上，
把「测试连接」当成一个内网探测跳板——错误信息里还会回显对方响应体。

策略：
- 只允许 http / https
- 解析出的每个 IP 必须是公网地址（`is_global`），否则拒绝
- 允许显式放行：本地跑 Ollama / vLLM 时设 SQLAGENT_LLM_ALLOW_PRIVATE_HOSTS=true

已知残留风险：校验在「保存/测试」时做，实际请求时不再解析一次，
所以理论上存在 DNS rebinding（解析结果在两次之间变化）。
要彻底堵住需要把连接固定到校验通过的 IP，属于后续加固。
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit

BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "metadata",
    "metadata.google.internal",
    "instance-data",
}


class UnsafeUrlError(ValueError):
    """地址不合法或指向内网，不允许请求。"""


def _resolve(host: str, port: int | None) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"域名解析失败：{host}") from exc
    return sorted({str(info[4][0]) for info in infos})


def check_base_url(
    url: str,
    *,
    allow_private: bool = False,
    resolver=None,
) -> str:
    """校验一个 OpenAI 兼容端点，返回去掉尾部斜杠的规范形式。

    resolver 可注入：测试里不依赖真实 DNS。
    """
    resolve = resolver or _resolve
    text = (url or "").strip()
    if not text:
        raise UnsafeUrlError("地址不能为空")

    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"}:
        raise UnsafeUrlError("地址必须以 http:// 或 https:// 开头")
    if not parts.hostname:
        raise UnsafeUrlError("地址里没有主机名")

    host = parts.hostname.lower()
    if allow_private:
        return text.rstrip("/")

    if host in BLOCKED_HOSTNAMES or host.endswith(".local"):
        raise UnsafeUrlError("不允许指向本机或内网地址")

    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        addresses = resolve(host, parts.port)
        if not addresses:
            raise UnsafeUrlError(f"域名解析失败：{host}") from None
    else:
        addresses = [str(literal)]

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            raise UnsafeUrlError(
                f"不允许指向内网/本机地址（{address}）。"
                "如果你在本地跑 Ollama / vLLM，请设置 SQLAGENT_LLM_ALLOW_PRIVATE_HOSTS=true"
            )

    return text.rstrip("/")