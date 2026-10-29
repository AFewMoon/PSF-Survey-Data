"""清洗层逐列语义判定的跨模型对账。

用途：三方对比里，"对齐"这一段盘古没跑到，但"清洗的列语义判定"两个模型都产出了，
且落在同名的 2019 原始列上。于是可以在同一批列上比 kind / group / option 三项，
把"判断质量是否随模型变大而变好"从 8 对样本扩到上百列。

口径：
- 两个决策目录各取 stage=clean_semantics 且 payload_summary.year 匹配的记录；
- 按原始列名索引，同一列出现多次时按 created_at 取最新一条，并计入 duplicates；
- 逐列比较三项，option 为空视为一项缺失而非不同；
- 只比两模型都判过的列，未覆盖的列不参与分母。

用法：
  python pangu/probe/semantics_compare.py --year 2019
  python pangu/probe/semantics_compare.py --left llm/decisions --right pangu/decisions
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PANGU_DIR = HERE.parent
ROOT = PANGU_DIR.parent

FIELDS = ("kind", "group", "option")


@dataclass
class Judgement:
    column: str
    kind: str
    group: str
    option: str
    created_at: str
    batch_n: int
    model: str


def load_judgements(decisions_dir: Path, year: int) -> tuple[dict[str, Judgement], int]:
    """返回 (列名 -> 判定, 重复列数)；同一列多次出现取最新。"""
    best: dict[str, Judgement] = {}
    duplicates = 0
    for path in sorted(decisions_dir.rglob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(item, dict) or item.get("stage") != "clean_semantics":
            continue
        payload = item.get("payload_summary") or {}
        if payload.get("year") != year:
            continue
        columns = (item.get("response") or {}).get("columns") or []
        for row in columns:
            name = str(row.get("column") or "")
            if not name:
                continue
            created = str(item.get("created_at") or "")
            if name in best:
                duplicates += 1
                if best[name].created_at >= created:
                    continue
            best[name] = Judgement(
                column=name,
                kind=str(row.get("kind") or ""),
                group=str(row.get("group") or ""),
                option=str(row.get("option") or ""),
                created_at=created,
                batch_n=int(payload.get("n") or 0),
                model=str(item.get("model") or ""),
            )
    return best, duplicates


def compare(left: dict[str, Judgement], right: dict[str, Judgement]) -> dict[str, Any]:
    shared = sorted(set(left) & set(right))
    stats = {f: 0 for f in FIELDS}
    exact = 0
    diffs: list[dict[str, Any]] = []
    for name in shared:
        a, b = left[name], right[name]
        same_all = True
        for field in FIELDS:
            va, vb = getattr(a, field), getattr(b, field)
            if va and vb and va == vb:
                stats[field] += 1
            elif not va or not vb:
                continue
            else:
                same_all = False
        if same_all:
            exact += 1
        else:
            diffs.append({
                "column": name,
                "left": {f: getattr(a, f) for f in FIELDS},
                "right": {f: getattr(b, f) for f in FIELDS},
            })

    n = len(shared)
    pct = lambda k: round(k / n * 100, 1) if n else 0.0  # noqa: E731
    field_rates = {f: {"same": stats[f], "pct": pct(stats[f])} for f in FIELDS}
    group_pairs = Counter(
        (left[c].group, right[c].group) for c in shared if left[c].group != right[c].group
    )
    # 组名基数：同一批列上，模型给出的不同 group 个数。同一道多选题的选项应当共用一个 group，
    # 所以这个数字越接近"题目数"越合理；接近"列数"说明模型按选项各自造组。
    cardinality = {
        "left": len({left[c].group for c in shared}),
        "right": len({right[c].group for c in shared}),
    }
    # 按对照侧的批大小拆分，排除"小批看不到同题兄弟列"造成的偏差。
    by_batch: dict[int, dict[str, int]] = {}
    for name in shared:
        bucket = by_batch.setdefault(right[name].batch_n, {"columns": 0, "group_same": 0})
        bucket["columns"] += 1
        if left[name].group and left[name].group == right[name].group:
            bucket["group_same"] += 1
    return {
        "columns_compared": n,
        "exact_match": exact,
        "exact_match_pct": pct(exact),
        "fields": field_rates,
        "group_cardinality": cardinality,
        "by_batch_size": {
            str(k): {"columns": v["columns"], "group_same": v["group_same"],
                     "group_same_pct": round(v["group_same"] / v["columns"] * 100, 1) if v["columns"] else 0.0}
            for k, v in sorted(by_batch.items())
        },
        "kind_confusion": [
            {"left": a, "right": b, "n": k}
            for (a, b), k in Counter(
                (left[c].kind, right[c].kind) for c in shared if left[c].kind != right[c].kind
            ).most_common()
        ],
        "group_mismatch_top": [
            {"left": a, "right": b, "n": k} for (a, b), k in group_pairs.most_common(10)
        ],
        "disagreements": diffs[:50],
        "disagreement_total": len(diffs),
    }


def md_report(result: dict[str, Any], left_label: str, right_label: str, year: int) -> str:
    fields = result["fields"]
    lines = [
        f"# 清洗语义判定对账（{year}）：{left_label} vs {right_label}",
        "",
        "口径：同一批原始列名上的 kind / group / option 三项判定，只比两侧都覆盖的列。",
        "",
        "| 指标 | 一致 | 占比 |",
        "| --- | --- | --- |",
        f"| 覆盖列数 | {result['columns_compared']} | — |",
        f"| 三项全同 | {result['exact_match']} | {result['exact_match_pct']}% |",
    ]
    for field, label in (("kind", "kind（单选/多选/数值/文本）"),
                         ("group", "group（题目组）"),
                         ("option", "option（选项名）")):
        row = fields[field]
        lines.append(f"| {label} | {row['same']} | {row['pct']}% |")

    card = result["group_cardinality"]
    lines += [
        "",
        "## 组名基数",
        "",
        f"同一批 {result['columns_compared']} 列上，{left_label} 给出 {card['left']} 个不同 group，"
        f"{right_label} 给出 {card['right']} 个。多选题的选项本应共用 group，"
        "基数接近列数说明模型是按选项各自造组。",
        "",
        "## 按对照侧批大小拆分",
        "",
        f"| 批大小 | 列数 | group 一致 | 占比 |",
        "| --- | --- | --- | --- |",
    ]
    for size, row in result["by_batch_size"].items():
        lines.append(f"| {size} | {row['columns']} | {row['group_same']} | {row['group_same_pct']}% |")

    if result["kind_confusion"]:
        lines += ["", "## kind 分歧矩阵", "", "| " + left_label + " | " + right_label + " | 列数 |",
                  "| --- | --- | --- |"]
        for row in result["kind_confusion"]:
            lines.append(f"| {row['left'] or '—'} | {row['right'] or '—'} | {row['n']} |")

    if result["group_mismatch_top"]:
        lines += ["", "## group 分歧 Top", "", "| " + left_label + " | " + right_label + " | 列数 |",
                  "| --- | --- | --- |"]
        for row in result["group_mismatch_top"]:
            lines.append(f"| `{row['left']}` | `{row['right']}` | {row['n']} |")

    if result["disagreements"]:
        lines += ["", "## 分歧样例", "", "| 列 | " + left_label + " | " + right_label + " |",
                  "| --- | --- | --- |"]
        for row in result["disagreements"][:15]:
            a, b = row["left"], row["right"]
            lines.append(
                "| `{col}` | {ak} / {ag} | {bk} / {bg} |".format(
                    col=row["column"][:48], ak=a["kind"], ag=a["group"] or "—",
                    bk=b["kind"], bg=b["group"] or "—",
                )
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="清洗语义判定跨模型对账（只读）")
    parser.add_argument("--left", default="llm/decisions", help="基准侧决策目录")
    parser.add_argument("--right", default="pangu/decisions", help="对照侧决策目录")
    parser.add_argument("--year", type=int, default=2019)
    parser.add_argument("--out-dir", default=str(PANGU_DIR / "reports"))
    args = parser.parse_args(argv)

    def resolve(raw: str) -> Path:
        path = Path(raw)
        return path if path.is_absolute() else (ROOT / path).resolve()

    left_dir, right_dir = resolve(args.left), resolve(args.right)
    for path in (left_dir, right_dir):
        if not path.is_dir():
            print(f"[error] 决策目录不存在：{path}", file=sys.stderr)
            return 2

    left, left_dups = load_judgements(left_dir, args.year)
    right, right_dups = load_judgements(right_dir, args.year)
    if not left or not right:
        print(f"[error] 决策不足：左侧 {len(left)} 列，右侧 {len(right)} 列", file=sys.stderr)
        return 1

    result = compare(left, right)
    result["year"] = args.year
    result["left"] = {"dir": str(left_dir), "columns": len(left), "duplicates": left_dups,
                      "model": next(iter(left.values())).model if left else ""}
    result["right"] = {"dir": str(right_dir), "columns": len(right), "duplicates": right_dups,
                       "model": next(iter(right.values())).model if right else ""}

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"semantics_compare_{args.year}.json"
    md_path = out_dir / f"semantics_compare_{args.year}.md"
    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    left_label = result["left"]["model"] or left_dir.name
    right_label = result["right"]["model"] or right_dir.name
    md_path.write_text(md_report(result, left_label, right_label, args.year), encoding="utf-8")

    print(f"[compare] {args.year}：左侧 {len(left)} 列 / 右侧 {len(right)} 列，"
          f"共同 {result['columns_compared']} 列")
    print(f"[compare] 三项全同 {result['exact_match']}（{result['exact_match_pct']}%）；"
          f"kind {result['fields']['kind']['pct']}%，"
          f"group {result['fields']['group']['pct']}%，"
          f"option {result['fields']['option']['pct']}%")
    print(f"[compare] 写出 {json_path}")
    print(f"[compare] 写出 {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
