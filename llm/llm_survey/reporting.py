"""Markdown 报告工具：表格、章节、决策记录（不依赖 tabulate）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Sequence


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def md_table(header: Sequence[str], rows: Iterable[Sequence[Any]]) -> str:
    lines = ["| " + " | ".join(str(h) for h in header) + " |",
             "|" + "|".join(["---"] * len(header)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(v) for v in row) + " |")
    return "\n".join(lines)


def _cell(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("|", "\\|").replace("\n", " ")
    return text if len(text) <= 120 else text[:117] + "..."


def md_list(items: Iterable[str], empty: str = "无") -> str:
    materialized = [i for i in items if str(i).strip()]
    return "\n".join(f"- {i}" for i in materialized) if materialized else f"- {empty}"


def section(title: str, body: str, level: int = 2) -> str:
    return f"{'#' * level} {title}\n\n{body.strip()}\n"


def decision_table(records: list[dict[str, Any]]) -> str:
    """模型决策审计表：谁做的决定、耗时、是否降级。"""
    if not records:
        return "_（无模型调用记录）_"
    rows = []
    for r in records:
        rows.append([
            r.get("stage", ""),
            r.get("model", ""),
            r.get("prompt_version", ""),
            f"{r.get('duration_s', 0)}s",
            r.get("output_tokens", 0),
            "是" if r.get("fallback") else "否",
            "是" if r.get("manual_edit") else "否",
            str(r.get("payload_summary", {}).get("year", "")) or
            str(r.get("payload_summary", {}).get("batch", ""))[:24],
        ])
    return md_table(
        ["阶段", "模型", "提示词版本", "耗时", "输出 tok", "降级", "人工修订", "对象"],
        rows,
    )


def pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}%"


def truncate(text: str, limit: int = 60) -> str:
    text = str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"
