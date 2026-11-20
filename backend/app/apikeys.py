"""开发者 API Key 的生成、哈希与鉴权辅助。"""

from __future__ import annotations

import hashlib
import secrets

KEY_PREFIX = "sa_live_"
DISPLAY_LENGTH = 12


def generate_api_key() -> tuple[str, str, str]:
    """返回 (明文, 展示用前缀, 哈希)。明文只在这里出现一次。"""
    raw = secrets.token_urlsafe(32)
    plaintext = f"{KEY_PREFIX}{raw}"
    prefix = plaintext[:DISPLAY_LENGTH]
    return plaintext, prefix, hash_api_key(plaintext)


def hash_api_key(plaintext: str) -> str:
    # Key 本身是高熵随机串，用 SHA-256 足够；不需要 scrypt 的慢哈希
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def looks_like_api_key(token: str) -> bool:
    return token.startswith(KEY_PREFIX)


def mask_api_key(prefix: str) -> str:
    return f"{prefix}…" if prefix else "—"