"""决策缓存：模型输出的唯一事实来源，支持断点续跑与人工修订。

缓存键 = sha256(model | digest | prompt_version | stage | payload)，
人工编辑过的缓存默认不被覆盖（除非 --refresh 且 --force）。
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .config import DECISIONS_DIR
from .ollama_client import ChatMeta, OllamaError

STAGE_DIRS: dict[str, Path] = {
    "profile": DECISIONS_DIR / "profile",
    "clean_semantics": DECISIONS_DIR / "clean",
    "clean_plan": DECISIONS_DIR / "clean",
    "group_path": DECISIONS_DIR / "align",
    "group_pair": DECISIONS_DIR / "align",
    "option_alias": DECISIONS_DIR / "align",
    "pair_judge": DECISIONS_DIR / "align",
    "stats_plan": DECISIONS_DIR / "stats",
    "stats_narrative": DECISIONS_DIR / "stats",
    "chart_spec": DECISIONS_DIR / "chart",
    "parity_note": DECISIONS_DIR / "parity",
}


def build_key(stage: str, payload: Any, digest: str, prompt_version: str) -> str:
    blob = json.dumps(
        {"stage": stage, "payload": payload, "digest": digest, "pv": prompt_version},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class CacheStore:
    """按阶段分目录存放决策 JSON。"""

    def __init__(self, stage: str, digest: str, refresh: bool = False) -> None:
        if stage not in STAGE_DIRS:
            raise KeyError(f"未知阶段：{stage}")
        self.stage = stage
        self.digest = digest
        self.refresh = refresh
        self.dir = STAGE_DIRS[stage]
        self.dir.mkdir(parents=True, exist_ok=True)
        self.hits = 0
        self.misses = 0
        self.manual_kept = 0

    def key(self, payload: Any, prompt_version: str) -> str:
        return build_key(self.stage, payload, self.digest, prompt_version)

    def path(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    def load(self, key: str) -> dict[str, Any] | None:
        if self.refresh:
            return None
        path = self.path(key)
        if not path.exists():
            return None
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(record, dict) or "response" not in record:
            return None
        self.hits += 1
        return record

    def save(self, key: str, record: dict[str, Any], force: bool = False) -> Path:
        """原子写；已人工编辑（manual_edit=true）的记录默认保留。"""
        path = self.path(key)
        if path.exists() and not force:
            try:
                old = json.loads(path.read_text(encoding="utf-8"))
                if old.get("manual_edit"):
                    self.manual_kept += 1
                    return path
            except (json.JSONDecodeError, OSError):
                pass
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def record(
        self,
        stage: str,
        prompt_version: str,
        payload_summary: dict[str, Any],
        response: dict[str, Any],
        meta: ChatMeta | None,
        fallback: bool = False,
        error: str = "",
    ) -> dict[str, Any]:
        return {
            "stage": stage,
            "model": meta.model if meta else "local-fallback",
            "model_digest": meta.digest if meta else self.digest,
            "prompt_version": prompt_version,
            "input_hash": "",
            "created_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "duration_s": round(meta.duration_s, 2) if meta else 0.0,
            "output_tokens": meta.output_tokens if meta else 0,
            "fallback": fallback,
            "error": error,
            "manual_edit": False,
            "reviewed": False,
            "payload_summary": payload_summary,
            "response": response,
        }

    def get_or_call(
        self,
        key: str,
        prompt_version: str,
        payload_summary: dict[str, Any],
        call: Callable[[], tuple[dict[str, Any], ChatMeta]],
        fallback: Callable[[], dict[str, Any]] | None = None,
        force: bool = False,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """返回 (response, record, from_cache)。失败时（有 fallback）降级并标记。"""
        cached = self.load(key)
        if cached is not None:
            return cached["response"], cached, True

        self.misses += 1
        try:
            response, meta = call()
            record = self.record(self.stage, prompt_version, payload_summary, response, meta)
        except (OllamaError, ValueError, KeyError) as exc:
            if fallback is None:
                raise
            response = fallback()
            record = self.record(
                self.stage, prompt_version, payload_summary, response, None,
                fallback=True, error=str(exc)[:300],
            )
        record["input_hash"] = key
        self.save(key, record, force=force)
        return response, record, False

    def report(self) -> str:
        kept = f" / 保留人工修订 {self.manual_kept}" if self.manual_kept else ""
        return f"{self.stage}: 缓存命中 {self.hits} / 新增 {self.misses}{kept}"


def load_all(stage: str) -> list[dict[str, Any]]:
    """读取某阶段全部缓存记录（用于报告拼装与人工复核）。"""
    directory = STAGE_DIRS[stage]
    if not directory.exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        record["_file"] = path.name
        records.append(record)
    return records
