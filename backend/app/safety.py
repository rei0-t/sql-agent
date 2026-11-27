"""不可信内容的处理：清洗 + 注入检测。

为什么要单独一层：NL2SQL 的输入里有三处**不是我们写的**——
用户问题、数据库的表/列注释、采样出来的单元格值。后两者尤其容易被忽略：
任何人只要能改目标库的注释，就能往模型上下文里塞指令。

这里做两件事：
1. `sanitize`：把不可信文本压成"像数据"的样子（去控制字符、折叠空白、截断、拆掉分隔符）
2. `detect_injection`：识别典型的越权/越狱话术，用于审计留痕

注意边界：这些是**降低风险**，不是保证安全。真正的边界仍然是只读账号 + 闸门。
"""

from __future__ import annotations

import re
import unicodedata

# 我们自己在上下文里用的分隔符，出现在数据里必须拆掉，否则可以伪造"结束/开始"
_DELIMITER_LIKE = re.compile(r"[=<>#`~\-]{3,}")

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# (标记, 正则)：命中即视为可疑，用于审计，不直接拒绝
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "override_instructions",
        re.compile(
            r"(ignore|disregard|forget|override)\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+"
            r"(instructions?|rules?|prompts?)"
            r"|忽略(掉)?(以上|之前|前面|先前)(的)?(所有|全部)?(指令|规则|提示|要求)"
            r"|不要(再)?(遵守|理会)(以上|之前|前面)(的)?(指令|规则)",
            re.IGNORECASE,
        ),
    ),
    (
        "role_play",
        re.compile(
            r"you\s+are\s+now\b|act\s+as\s+(an?\s+)?(admin|root|developer|system)"
            r"|pretend\s+(to\s+be|you\s+are)"
            r"|你现在是|从现在(开始|起)你|扮演(一个)?(管理员|开发者|系统)",
            re.IGNORECASE,
        ),
    ),
    (
        "prompt_exfiltration",
        re.compile(
            r"(reveal|show|print|output|repeat)\s+(me\s+)?(your\s+)?"
            r"(system\s+prompt|instructions?|initial\s+prompt)"
            r"|(输出|泄露|告诉我|打印)(你的)?(系统)?(提示词|指令|prompt)",
            re.IGNORECASE,
        ),
    ),
    (
        "destructive_sql",
        re.compile(
            r"\b(drop|truncate|delete\s+from|update\s+\w+\s+set|alter\s+table|grant|revoke)\b"
            r"|(删库|删表|清空(表|库)|授权给|撤销权限)",
            re.IGNORECASE,
        ),
    ),
    (
        "stacked_statement",
        re.compile(r";\s*(--|#|/\*)|union\s+(all\s+)?select", re.IGNORECASE),
    ),
)


def sanitize(value: object, *, limit: int = 120) -> str:
    """把任意来源的文本压成一行、可安全放进 prompt 的短字符串。

    - 去掉控制字符（防止用 \\r 覆盖已有行）
    - 折叠所有空白
    - 拆掉像分隔符的连续符号（防止伪造上下文边界）
    - 截断
    """
    text = "" if value is None else str(value)
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL.sub(" ", text)
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    text = " ".join(text.split())
    text = _DELIMITER_LIKE.sub("—", text)
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return text


def detect_injection(text: str) -> list[str]:
    """返回命中的可疑模式名；正常问题应当返回空列表。"""
    if not text:
        return []
    return [name for name, pattern in _PATTERNS if pattern.search(text)]