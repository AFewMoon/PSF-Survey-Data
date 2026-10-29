"""决策缓存汇总：把 decisions/ 下的调用记录压成可比指标。

用途：benchmark 报告需要"每列多少 token、单批多久、降级多少"这类成本指标，
而这些只有决策文件里才记全（stage / duration_s / output_tokens / fallback）。
本脚本只读不写数据，产物是一份 JSON（供报告引用）和一段 Markdown 表。

用法：
  python pangu/probe/decisions_summary.py                      # 汇总 pangu/decisions
  python pangu/probe/decisions_summary.py --dir llm/decisions  # 汇总 qwen 侧
  python pangu/probe/decisions_summary.py --layers 2019        # 只看 payload_summary.year=2019

口径说明：
- tokens_per_item 只在决策文件记录了 payload_summary.n 时统计（清洗阶段有，对齐阶段多数没有）。
- 耗时取每个阶段内的中位数，均值会被首发加载（模型冷启动）拉高。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PANGU_DIR = HERE.parent
ROOT = PANGU_DIR.parent


def load_records(decisions_dir: Path, year: int | None) -> list[dict[str, Any]]:
    """读入全部决策文件；解析失败的文件计入 parse_errors 而不是中断。"""
    records: list[dict[str, Any]] = []
    for path in sorted(decisions_dir.rglob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(item, dict):
            continue
        stage = item.get("stage")
        if not stage:
            continue
        payload = item.get("payload_summary") or {}
        if year is not None and payload.get("year") != year:
            continue
        records.append({
            "stage": str(stage),
            "year": payload.get("year"),
            "n_items": payload.get("n"),
            "duration_s": item.get("duration_s"),
            "output_tokens": item.get("output_tokens"),
            "fallback": bool(item.get("fallback")),
            "error": str(item.get("error") or ""),
            "model": str(item.get("model") or ""),
        })
    return records


def summarize(records: list[dict[str, Any]], decisions_dir: Path) -> dict[str, Any]:
    """按 stage 汇总；同时给出全量口径，便于跨模型对比。"""
    by_stage: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        by_stage.setdefault(row["stage"], []).append(row)

    def block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        durations = [float(r["duration_s"]) for r in rows if r["duration_s"] is not None]
        tokens = [int(r["output_tokens"]) for r in rows if r["output_tokens"] is not None]
        per_item = [
            int(r["output_tokens"]) / int(r["n_items"])
            for r in rows
            if r["output_tokens"] is not None and r["n_items"]
        ]
        fallbacks = sum(1 for r in rows if r["fallback"])
        errors = sum(1 for r in rows if r["error"])
        return {
            "calls": len(rows),
            "fallback": fallbacks,
            "fallback_pct": round(fallbacks / len(rows) * 100, 2) if rows else 0.0,
            "errors": errors,
            "duration_median_s": round(statistics.median(durations), 2) if durations else None,
            "duration_mean_s": round(statistics.fmean(durations), 2) if durations else None,
            "output_tokens_total": sum(tokens),
            "output_tokens_median": int(statistics.median(tokens)) if tokens else None,
            "tokens_per_item_median": round(statistics.median(per_item), 1) if per_item else None,
            "items_counted": len(per_item),
        }

    stages = {name: block(rows) for name, rows in sorted(by_stage.items())}
    return {
        "decisions": str(decisions_dir),
        "model": next((r["model"] for r in records if r["model"]), ""),
        "years": sorted({int(r["year"]) for r in records if r["year"] is not None}),
        "overall": block(records),
        "stages": stages,
    }


def md_table(summary: dict[str, Any]) -> str:
    lines = [
        "| 阶段 | 调用数 | 降级 | 中位耗时(s) | 输出 token 合计 | 每项 token(中位) |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, row in summary["stages"].items():
        lines.append(
            "| {stage} | {calls} | {fb} | {dur} | {tok} | {per} |".format(
                stage=name,
                calls=row["calls"],
                fb=f"{row['fallback']}" if row["fallback"] else "0",
                dur=row["duration_median_s"] if row["duration_median_s"] is not None else "—",
                tok=row["output_tokens_total"],
                per=row["tokens_per_item_median"] if row["tokens_per_item_median"] is not None else "—",
            )
        )
    overall = summary["overall"]
    lines.append(
        "| **合计** | {calls} | {fb} | {dur} | {tok} | {per} |".format(
            calls=overall["calls"],
            fb=overall["fallback"],
            dur=overall["duration_median_s"] if overall["duration_median_s"] is not None else "—",
            tok=overall["output_tokens_total"],
            per=overall["tokens_per_item_median"] or "—",
        )
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="决策缓存汇总（只读）")
    parser.add_argument("--dir", default=str(PANGU_DIR / "decisions"),
                        help="决策目录（默认 pangu/decisions）")
    parser.add_argument("--layers", type=int, default=None, help="只看某一年的决策")
    parser.add_argument("--out", default=None,
                        help="汇总 JSON 落盘路径（默认写到该目录所属实验的 reports/）")
    parser.add_argument("--md", action="store_true", help="额外打印 Markdown 表")
    args = parser.parse_args(argv)

    decisions_dir = Path(args.dir)
    if not decisions_dir.is_absolute():
        decisions_dir = (ROOT / decisions_dir).resolve()
    if not decisions_dir.is_dir():
        print(f"[error] 决策目录不存在：{decisions_dir}", file=sys.stderr)
        return 2
    records = load_records(decisions_dir, args.layers)
    if not records:
        print(f"[error] {decisions_dir} 下没有可解析的决策文件", file=sys.stderr)
        return 1

    summary = summarize(records, decisions_dir)
    out = Path(args.out) if args.out else decisions_dir.parent / "reports" / "decisions_summary.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    overall = summary["overall"]
    print("[summary] 目录 %s" % decisions_dir)
    print("[summary] 模型 %s；年份 %s" % (summary["model"] or "—",
                                         summary["years"] or "—"))
    print("[summary] 调用 %d 次（降级 %d，%s%%）；中位耗时 %ss；输出 %d token；每项 %s token"
          % (overall["calls"], overall["fallback"], overall["fallback_pct"],
             overall["duration_median_s"], overall["output_tokens_total"],
             overall["tokens_per_item_median"]))
    if args.md:
        print()
        print(md_table(summary))
    print("[summary] 写出 %s" % out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
