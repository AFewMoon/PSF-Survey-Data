"""Ollama HTTP 客户端：严格 JSON 输出、超时重试、截断识别、耗时统计。

不引入 ollama / openai SDK，仅用标准库 + requests（项目已有依赖）。
日志遵循项目约定：只打印列名与计数，绝不打印样本原文。
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from .config import (
    CONNECT_TIMEOUT_S,
    KEEP_ALIVE,
    MAX_RETRIES,
    MODEL,
    NUM_CTX,
    OLLAMA_HOST,
    RETRY_BACKOFF_S,
    SEED,
    TEMPERATURE,
    THINK,
    TIMEOUT_S,
)


class OllamaError(RuntimeError):
    """模型服务不可用或返回不可解析内容。"""


class TruncatedOutput(OllamaError):
    """生成被 num_predict 截断：调用方应减小批大小重试。"""


@dataclass(frozen=True)
class ChatMeta:
    model: str
    digest: str
    duration_s: float
    prompt_tokens: int
    output_tokens: int
    attempts: int
    truncated: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "model_digest": self.digest,
            "duration_s": round(self.duration_s, 2),
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "attempts": self.attempts,
        }


@dataclass
class Usage:
    """会话级调用统计，用于报告与耗时估算。"""

    calls: int = 0
    retries: int = 0
    seconds: float = 0.0
    prompt_tokens: int = 0
    output_tokens: int = 0
    failures: list[str] = field(default_factory=list)

    def record(self, meta: ChatMeta) -> None:
        self.calls += 1
        self.seconds += meta.duration_s
        self.prompt_tokens += meta.prompt_tokens
        self.output_tokens += meta.output_tokens
        self.retries += max(0, meta.attempts - 1)

    def summary(self) -> str:
        avg = self.seconds / self.calls if self.calls else 0.0
        return (
            f"模型调用 {self.calls} 次 / 重试 {self.retries} 次 / 累计 {self.seconds:.1f}s"
            f"（均值 {avg:.1f}s）/ 输入 {self.prompt_tokens} tok / 输出 {self.output_tokens} tok"
        )


def _first_json_object(text: str) -> str | None:
    """扫描首个括号平衡的 {...} 片段（跳过字符串内的括号）。"""
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        escaped = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : i + 1]
        start = text.find("{", start + 1)
    return None


def extract_json(text: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象：剥代码围栏、取首个平衡对象、修复常见尾逗号。"""
    raw = (text or "").strip()
    if not raw:
        raise OllamaError("模型返回空内容")
    candidates: list[str] = []
    if "```" in raw:
        for chunk in raw.split("```"):
            body = chunk.strip()
            if body.startswith("json"):
                body = body[4:].strip()
            if body.startswith("{"):
                candidates.append(body)
    candidates.append(raw)
    balanced = _first_json_object(raw)
    if balanced:
        candidates.append(balanced)

    for cand in candidates:
        for attempt in (cand, _repair(cand)):
            try:
                data = json.loads(attempt)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
    raise OllamaError(f"无法从模型输出解析 JSON（前 200 字符）：{raw[:200]!r}")


def _repair(text: str) -> str:
    """去掉对象/数组末尾的多余逗号（4B 模型常见错误）。"""
    import re

    s = re.sub(r",\s*([}\]])", r"\1", text)
    return s.strip()


class OllamaClient:
    """串行调用本地 Ollama；8 GB 显存下并发会触发模型重载，故不并发。"""

    def __init__(
        self,
        model: str = MODEL,
        host: str = OLLAMA_HOST,
        timeout: float = TIMEOUT_S,
        num_ctx: int = NUM_CTX,
        keep_alive: str = KEEP_ALIVE,
        think: bool = THINK,
    ) -> None:
        self.model = model
        self.host = host
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.keep_alive = keep_alive
        self.think = think
        self.usage = Usage()
        self._session = requests.Session()
        self._digest: str | None = None
        self._supports_think = True
        # 部分自定义架构（如 pangu-embedded）无法初始化 JSON grammar sampler，
        # 传 format=json 会 400。首次失败后自动降级，改由 extract_json 兜底。
        self._supports_format_json = True

    # ------------------------------------------------------------ 元信息
    def health(self) -> str:
        """确认模型可用，返回模型 digest（缓存键的一部分）。"""
        try:
            resp = self._session.get(f"{self.host}/api/tags",
                                     timeout=(CONNECT_TIMEOUT_S, 20))
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(
                f"无法连接 Ollama（{self.host}）：{exc}. 请确认 `ollama serve` 正在运行"
            ) from exc
        for item in resp.json().get("models", []):
            name = item.get("name") or item.get("model") or ""
            if name == self.model or name.split(":")[0] == self.model.split(":")[0]:
                self._digest = str(item.get("digest", ""))[:16]
                return self._digest
        raise OllamaError(f"Ollama 中未找到模型 {self.model}，请先 `ollama pull {self.model}`")

    @property
    def digest(self) -> str:
        if self._digest is None:
            self.health()
        return self._digest or "unknown"

    # ------------------------------------------------------------ 调用
    def chat_json(self, system: str, user: str, num_predict: int = 768,
                  tag: str = "") -> tuple[dict[str, Any], ChatMeta]:
        text, meta = self._chat(system, user, num_predict, tag, force_json=True)
        try:
            return extract_json(text), meta
        except OllamaError:
            # 再给一次机会：把上次输出回灌要求修复
            repair_user = (
                f"{user}\n\n上一次输出无法解析为 JSON。请只输出一个合法的 JSON 对象，"
                f"不要任何解释、不要 Markdown 代码块。"
            )
            text2, meta2 = self._chat(system, repair_user, num_predict, f"{tag}:repair",
                                      force_json=True)
            return extract_json(text2), meta2

    def chat_text(self, system: str, user: str, num_predict: int = 700,
                  tag: str = "") -> tuple[str, ChatMeta]:
        return self._chat(system, user, num_predict, tag, force_json=False)

    def _chat(self, system: str, user: str, num_predict: int, tag: str,
              force_json: bool) -> tuple[str, ChatMeta]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": TEMPERATURE,
                "seed": SEED,
                "num_ctx": self.num_ctx,
                "num_predict": num_predict,
                "top_p": 0.9,
                "presence_penalty": 0.0,
            },
        }
        if force_json and self._supports_format_json:
            payload["format"] = "json"
        if self._supports_think:
            payload["think"] = self.think

        last_error: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            started = time.perf_counter()
            try:
                resp = self._session.post(
                    f"{self.host}/api/chat",
                    json=payload,
                    timeout=(CONNECT_TIMEOUT_S, self.timeout),
                )
                if resp.status_code == 400:
                    lowered = resp.text.lower()
                    if "think" in lowered and self._supports_think:
                        # 旧版本 Ollama 不认识 think 字段
                        self._supports_think = False
                        payload.pop("think", None)
                        raise OllamaError("retry-without-think")
                    if force_json and self._supports_format_json and (
                        "sampler" in lowered or "grammar" in lowered
                    ):
                        # 该架构不支持 JSON grammar 约束（实测 pangu-embedded 报
                        # "Failed to initialize samplers"）。改用提示词约束 + extract_json。
                        self._supports_format_json = False
                        payload.pop("format", None)
                        print(f"[warn] {self.model} 不支持 format=json，"
                              f"已降级为提示词约束 + 容错解析", file=sys.stderr)
                        raise OllamaError("retry-without-format")
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as exc:
                last_error = exc
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status is not None and 400 <= status < 500:
                    raise OllamaError(f"[{tag}] 请求被拒绝（HTTP {status}）：{exc}") from exc
                if attempt == MAX_RETRIES:
                    break
                self.usage.retries += 1
                time.sleep(RETRY_BACKOFF_S[min(attempt - 1, len(RETRY_BACKOFF_S) - 1)])
                continue
            except OllamaError as exc:
                if str(exc) in ("retry-without-think", "retry-without-format"):
                    return self._chat(system, user, num_predict, tag, force_json)
                raise

            elapsed = time.perf_counter() - started
            message = data.get("message") or {}
            content = message.get("content") or ""
            if data.get("thinking"):
                content = content or str(data["thinking"])
            meta = ChatMeta(
                model=self.model,
                digest=self.digest,
                duration_s=elapsed,
                prompt_tokens=int(data.get("prompt_eval_count") or 0),
                output_tokens=int(data.get("eval_count") or 0),
                attempts=attempt,
                truncated=data.get("done_reason") == "length",
            )
            self.usage.record(meta)
            if meta.truncated:
                raise TruncatedOutput(
                    f"[{tag}] 输出被 num_predict={num_predict} 截断（{meta.output_tokens} tok）"
                )
            self._invalidate_on_empty(content, tag)
            return content, meta

        raise OllamaError(f"[{tag}] 模型调用失败：{last_error}")

    @staticmethod
    def _invalidate_on_empty(content: str, tag: str) -> None:
        if not content.strip():
            raise OllamaError(f"[{tag}] 模型返回空内容")
