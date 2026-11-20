"""模型调用：一个极薄的 OpenAI 兼容客户端。

只做三件事：发请求、重试、把 usage 带回来。不引 SDK、不做工具调用，
因为整条链路只需要「文本进、文本出」。
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from app.config import settings


class LLMError(RuntimeError):
    """模型不可用或返回了无法处理的内容。"""


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    def merge(self, other: Usage) -> None:
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens


@dataclass
class Completion:
    text: str
    usage: Usage = field(default_factory=Usage)
    model: str = ""


class ChatModel(Protocol):
    name: str

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 900,
    ) -> Completion: ...


class OpenAICompatibleModel:
    """DashScope / DeepSeek / vLLM 等 OpenAI 兼容端点都能用。"""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 60,
        temperature: float = 0.0,
        retries: int = 2,
        seed: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.name = model
        self.timeout = timeout
        self.temperature = temperature
        self.retries = retries
        self.seed = seed

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 900,
    ) -> Completion:
        if not self.api_key:
            raise LLMError("未配置模型密钥（SQLAGENT_LLM_API_KEY）")

        payload: dict[str, Any] = {
            "model": self.name,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens,
        }
        if self.seed is not None:
            payload["seed"] = self.seed
        headers = {"Authorization": f"Bearer {self.api_key}"}

        last_error: str = ""
        for attempt in range(self.retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/chat/completions", headers=headers, json=payload
                    )
                if response.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {response.status_code}"
                    await asyncio.sleep(1.2 * (attempt + 1))
                    continue
                if response.status_code >= 400:
                    raise LLMError(f"模型返回 HTTP {response.status_code}: {response.text[:200]}")

                data = response.json()
                choice = (data.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                raw_usage = data.get("usage") or {}
                return Completion(
                    text=content.strip(),
                    usage=Usage(
                        prompt_tokens=int(raw_usage.get("prompt_tokens") or 0),
                        completion_tokens=int(raw_usage.get("completion_tokens") or 0),
                    ),
                    model=str(data.get("model") or self.name),
                )
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                await asyncio.sleep(1.2 * (attempt + 1))

        raise LLMError(f"模型调用失败：{last_error}")


def get_default_model() -> OpenAICompatibleModel:
    return OpenAICompatibleModel(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout=settings.llm_timeout,
        temperature=settings.llm_temperature,
        seed=settings.llm_seed,
    )


@dataclass
class ProbeResult:
    ok: bool
    message: str
    latency_ms: int = 0
    model: str = ""


def _short_body(text: str, limit: int = 200) -> str:
    return " ".join(text.split())[:limit]


async def probe_endpoint(
    *, base_url: str, api_key: str, model: str, timeout: int = 20
) -> ProbeResult:
    """验证一组模型配置是否可用。

    先打 /models（不消耗 token）；端点没实现该接口时退回一次 1 token 的补全。
    """
    if not api_key:
        return ProbeResult(ok=False, message="没有可用的 API Key，请先填写")
    if not base_url.startswith(("http://", "https://")):
        return ProbeResult(ok=False, message="Base URL 必须以 http:// 或 https:// 开头")

    base = base_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    started = time.perf_counter()

    def elapsed() -> int:
        return int((time.perf_counter() - started) * 1000)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            listing = await client.get(f"{base}/models", headers=headers)
            if listing.status_code == 200:
                return ProbeResult(
                    ok=True,
                    message="连接成功",
                    latency_ms=elapsed(),
                    model=model,
                )
            if listing.status_code in (401, 403):
                return ProbeResult(
                    ok=False,
                    message=f"鉴权失败（HTTP {listing.status_code}）：{_short_body(listing.text)}",
                    latency_ms=elapsed(),
                )

            completion = await client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0,
                },
            )
            if completion.status_code == 200:
                return ProbeResult(
                    ok=True, message="连接成功", latency_ms=elapsed(), model=model
                )
            return ProbeResult(
                ok=False,
                message=(
                    f"调用失败（HTTP {completion.status_code}）："
                    f"{_short_body(completion.text)}"
                ),
                latency_ms=elapsed(),
            )
    except httpx.HTTPError as exc:
        return ProbeResult(
            ok=False,
            message=f"网络错误：{type(exc).__name__}",
            latency_ms=elapsed(),
        )


# ---------------- 输出解析 ----------------

_FENCE = ("```json", "```JSON", "```")


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出里抠出第一个 JSON 对象。

    模型经常加解释、加 ``` 围栏，甚至把 JSON 包在句子里，这里都容忍。
    """
    cleaned = text.strip()
    for fence in _FENCE:
        if cleaned.startswith(fence):
            cleaned = cleaned[len(fence) :]
        cleaned = cleaned.replace(fence, "")
    cleaned = cleaned.strip()

    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    try:
                        data = json.loads(cleaned[start : index + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(data, dict):
                        return data
                    break

    raise LLMError("模型输出不是合法 JSON")


# ---------------- 测试替身 ----------------


class FakeModel:
    """测试用：按顺序吐出预设文本，同时记录收到的 prompt。"""

    def __init__(self, responses: list[str], name: str = "fake-model") -> None:
        self.responses = list(responses)
        self.name = name
        self.prompts: list[tuple[str, str]] = []

    async def complete(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
        max_tokens: int = 900,
    ) -> Completion:
        self.prompts.append((system, user))
        if not self.responses:
            raise LLMError("FakeModel 没有更多预设响应")
        text = self.responses.pop(0)
        return Completion(text=text, usage=Usage(prompt_tokens=10, completion_tokens=10), model=self.name)