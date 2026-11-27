"""口令哈希、访问令牌、数据源口令的对称加密。

刻意只用标准库 + PyJWT + cryptography，避免引入 passlib / bcrypt 这类在
Windows 与新版本 Python 上经常装不上的依赖。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from functools import lru_cache
from typing import Any

import jwt
from cryptography.fernet import Fernet

from app.config import settings

_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1
_DKLEN = 32
_JWT_ALG = "HS256"


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.urlsafe_b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    """scrypt 加盐哈希，格式：scrypt$N$r$p$salt$hash。"""
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=_DKLEN
    )
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64e(salt)}${_b64e(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        expected = _b64d(hash_b64)
        dk = hashlib.scrypt(
            password.encode("utf-8"),
            salt=_b64d(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, expected)


def create_access_token(subject: str, token_version: int = 0) -> str:
    """签发访问令牌。

    ``token_version`` 与用户表上的字段对齐：改密码时自增，从而让**旧令牌立即失效**
    （JWT 本身无状态，不这样做的话"改密码"只是心理安慰）。
    """
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": subject,
        "ver": token_version,
        "iat": now,
        "exp": now + settings.access_token_ttl_minutes * 60,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=_JWT_ALG)


def decode_access_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[_JWT_ALG])
    except jwt.PyJWTError:
        return None


class SecretBox:
    """数据源口令落库前的对称加密。

    密钥由 SECRET_KEY 派生（SHA-256 → 32 字节 → urlsafe base64）。
    更换 SECRET_KEY 会导致已存口令无法解密，这是有意为之。
    """

    def __init__(self, secret_key: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode("utf-8")).digest())
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, token: str) -> str:
        return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")


@lru_cache
def get_secret_box() -> SecretBox:
    return SecretBox(settings.secret_key)