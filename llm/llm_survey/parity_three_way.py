"""三方对账：规则管线 / qwen 4B / 盘古 7B，按年逐列比对。

与 `parity.py` 的区别：
- `parity.py` 比的是"总表 vs 总表"，且只有两方，还带一次模型解读；
- 本模块读各管线的**分年对齐表**，支持任意多方可比，纯确定性计算，不调模型。

之所以要分年：盘古没有跑完全部年份，总表无从生成；按年比对可以只对已产出的年份下结论，
未产出的年份在报告里显式标为"未产出"，而不是装作一致。

用法：
  python -m llm_survey.parity_three_way --years 2019
  python -m llm_survey.parity_three_way --years 2019 --out pangu/reports
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .textnorm import norm_key

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    "规则": REPO_ROOT / "aligned",
    "qwen4B": REPO_ROOT / "llm" / "aligned",
    "pangu7B": REPO_ROOT / "pangu" / "aligned",
}
# 分年对齐表的命名差异：规则管线不带模型后缀，两条模型管线共用 _llm 后缀。
FILENAMES = {
    "规则": "cleaned_aligned_{year}.csv",
    "qwen4B": "cleaned_aligned_llm_{year}.csv",
    "pangu7B": "cleaned_aligned_llm_{year}.csv",
}


@dataclass
class YearRow:
    year: int
    rows: dict[str, int] = field(default_factory=dict)
    cols: dict[str, int] = field(default_factory=dict)


@dataclass
class PairRow:
    left: str
    right: str
    left_cols: int = 0
    right_cols: int = 0
    matched: int = 0
    jaccard: float = 0.0
    recall: float = 0.0          # 右方复现了左方多少列
    missing_diffs: list[list[Any]] = field(default_factory=list)


@dataclass
class MappingRow:
    source: str
    column_mapping: int = 0      # 列名重命名条数
    value_mapping: int = 0       # 取值统一条数
    note: str = ""


@dataclass
class Report:
    years: list[int] = field(default_factory=list)
    produced: dict[str, list[int]] = field(default_factory=dict)
    missing: dict[str, list[int]] = field(default_factory=dict)
    rows: list[YearRow] = field(default_factory=list)
    pairs: list[PairRow] = field(default_factory=list)
    common_all: dict[str, int] = field(default_factory=dict)
    common_sources: dict[str, int] = field(default_factory=dict)
    mappings: list[MappingRow] = field(default_factory=list)
    master_cols: dict[str, int] = field(default_factory=dict)
    master_pairs: list[PairRow] = field(default_factory=list)
    master_missing: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _read_csv(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    return pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig", low_memory=False)


def _non_empty_share(df: pd.DataFrame, col: str) -> float:
    """与 parity.py 同口径：二值列看 1 的占比，其余看非空占比。"""
    series = df[col]
    if series.dtype.kind in "iu":
        return float((series == 1).mean() * 100)
    if series.dtype.kind == "f":
        return float(series.notna().mean() * 100)
    return float((series != "").mean() * 100)


def _index(df: pd.DataFrame) -> dict[str, str]:
    return {norm_key(c): c for c in df.columns if c != "year"}


def _count_mapping(align_dir: Path) -> tuple[int, int, str]:
    """列名映射与取值映射的条数；文件缺失时返回 0 并给出说明。"""
    col_path = align_dir / "column_mapping.csv"
    val_path = align_dir / "value_mapping.csv"
    if not col_path.exists() and not val_path.exists():
        return 0, 0, "未产出映射表"
    col_rows = 0
    val_rows = 0
    if col_path.exists():
        frame = pd.read_csv(col_path, keep_default_na=False, encoding="utf-8-sig")
        col_rows = len(frame)
    if val_path.exists():
        frame = pd.read_csv(val_path, keep_default_na=False, encoding="utf-8-sig")
        val_rows = len(frame)
    return col_rows, val_rows, ""


def compare_pair(left_name: str, left: pd.DataFrame, right_name: str, right: pd.DataFrame,
                 limit: int = 10) -> PairRow:
    """两侧列集合的重合度 + 匹配列的非空率差异。"""
    left_index, right_index = _index(left), _index(right)
    keys = set(left_index) & set(right_index)
    union = set(left_index) | set(right_index)
    row = PairRow(left=left_name, right=right_name,
                  left_cols=len(left_index), right_cols=len(right_index),
                  matched=len(keys),
                  jaccard=round(len(keys) / len(union) * 100, 1) if union else 0.0,
                  recall=round(len(keys) / len(left_index) * 100, 1) if left_index else 0.0)
    diffs: list[list[Any]] = []
    for key in sorted(keys):
        share_left = _non_empty_share(left, left_index[key])
        share_right = _non_empty_share(right, right_index[key])
        if abs(share_left - share_right) >= 1.0:
            diffs.append([left_index[key], round(share_left, 1), round(share_right, 1),
                          round(share_right - share_left, 1)])
    diffs.sort(key=lambda item: abs(item[3]), reverse=True)
    row.missing_diffs = diffs[:limit]
    return row


def _master_columns(align_dir: Path) -> dict[str, str] | None:
    """只读总表表头，拿到列集合；表不存在返回 None。

    用 nrows=0 读表头，几 MB 的 CSV 也不会整表进内存——总表比对只需要列名。
    """
    hits = sorted(align_dir.glob("survey_*_master*.csv"))
    if not hits:
        return None
    header = pd.read_csv(hits[0], nrows=0, encoding="utf-8-sig")
    return {norm_key(c): c for c in header.columns if c != "year"}


def compare_cols(left_name: str, left_index: dict[str, str],
                 right_name: str, right_index: dict[str, str]) -> PairRow:
    """只比列集合（总表口径）；分年表的非空率差异走 compare_pair。"""
    keys = set(left_index) & set(right_index)
    union = set(left_index) | set(right_index)
    return PairRow(left=left_name, right=right_name,
                   left_cols=len(left_index), right_cols=len(right_index),
                   matched=len(keys),
                   jaccard=round(len(keys) / len(union) * 100, 1) if union else 0.0,
                   recall=round(len(keys) / len(left_index) * 100, 1) if left_index else 0.0)


def run(years: list[int], sources: dict[str, Path] | None = None) -> Report:
    sources = sources or SOURCES
    report = Report(years=list(years))
    frames: dict[tuple[str, int], pd.DataFrame] = {}

    for name, directory in sources.items():
        report.produced[name] = []
        report.missing[name] = []
        for year in years:
            pattern = FILENAMES.get(name, "cleaned_aligned_llm_{year}.csv")
            frame = _read_csv(directory / pattern.format(year=year))
            if frame is None:
                report.missing[name].append(year)
                continue
            frames[(name, year)] = frame
            report.produced[name].append(year)
        col_rows, val_rows, note = _count_mapping(directory)
        report.mappings.append(MappingRow(name, col_rows, val_rows, note))

    # 总表口径：跨年共有列的复现率，与分年口径并列展示
    master_index: dict[str, dict[str, str]] = {}
    for name, directory in sources.items():
        index = _master_columns(directory)
        if index is None:
            report.master_missing.append(name)
            continue
        master_index[name] = index
        report.master_cols[name] = len(index)
    if "规则" in master_index:
        for name, index in master_index.items():
            if name == "规则":
                continue
            report.master_pairs.append(compare_cols("规则", master_index["规则"], name, index))

    for year in years:
        row = YearRow(year)
        for name in sources:
            frame = frames.get((name, year))
            if frame is None:
                continue
            row.rows[name] = int(len(frame))
            row.cols[name] = len([c for c in frame.columns if c != "year"])
        report.rows.append(row)

    rule = "规则"
    others = [name for name in sources if name != rule]
    for name in others:
        pairs: list[PairRow] = []
        for year in years:
            left, right = frames.get((rule, year)), frames.get((name, year))
            if left is None or right is None:
                report.problems.append(
                    f"{year} 年无法比对：{'规则' if left is None else name}侧缺分年对齐表")
                continue
            pairs.append(compare_pair(rule, left, name, right))
        if pairs:
            combined = PairRow(left=rule, right=name)
            combined.left_cols = max(p.left_cols for p in pairs)
            combined.right_cols = max(p.right_cols for p in pairs)
            combined.matched = min(p.matched for p in pairs)
            combined.jaccard = round(sum(p.jaccard for p in pairs) / len(pairs), 1)
            combined.recall = round(sum(p.recall for p in pairs) / len(pairs), 1)
            combined.missing_diffs = [diff for p in pairs for diff in p.missing_diffs][:10]
            report.pairs.append(combined)

    # 三方同时存在的列（跨年都齐的年份才统计）
    for year in years:
        present = [frames[(name, year)] for name in sources if (name, year) in frames]
        if len(present) < 2:
            continue
        common = set(_index(present[0]))
        for frame in present[1:]:
            common &= set(_index(frame))
        report.common_all[str(year)] = len(common)
        report.common_sources[str(year)] = len(present)

    return report


def md(report: Report) -> str:
    lines = ["# 三方对账：规则管线 / qwen 4B / 盘古 7B", ""]
    lines.append("口径：各管线的**分年对齐表**，按归一化列名比对；"
                 "未产出的年份显式标注，不参与均值。")
    lines.append("")
    lines.append("## 产出情况")
    lines.append("")
    table_rows = []
    for name in report.produced:
        produced = "、".join(str(y) for y in report.produced[name]) or "—"
        missing = "、".join(str(y) for y in report.missing.get(name, [])) or "—"
        table_rows.append([name, produced, missing])
    lines.append(_table(["管线", "已产出年份", "未产出年份"], table_rows))
    lines.append("")

    if report.rows:
        lines.append("## 分年规模")
        lines.append("")
        names = [n for n in report.produced]
        rows = []
        for item in report.rows:
            cells = [item.year]
            for name in names:
                cells.append(f"{item.rows[name]:,} 行 / {item.cols[name]} 列"
                             if name in item.rows else "未产出")
            rows.append(cells)
        lines.append(_table(["年份"] + names, rows))
        lines.append("")

    if report.pairs:
        lines.append("## 相对规则管线的复现率")
        lines.append("")
        rows = [[p.right, p.left_cols, p.right_cols, p.matched,
                 f"{p.recall}%", f"{p.jaccard}%"] for p in report.pairs]
        lines.append(_table(["能力方", "规则列数", "本侧列数", "同名匹配", "复现率", "Jaccard"],
                            rows))
        lines.append("")

    if report.master_pairs or report.master_missing:
        lines.append("## 总表口径（跨年共有列）")
        lines.append("")
        lines.append("这一节的基数是跨年总表（人工 153 列那一套），与上面的分年表口径不同："
                     "分年表含该年全部列，所以复现率不能与 110/153 直接相加比较。")
        lines.append("")
        rows = []
        for name, count in report.master_cols.items():
            rows.append([name, count])
        if rows:
            lines.append(_table(["管线", "总表列数（不含 year）"], rows))
            lines.append("")
        if report.master_pairs:
            lines.append(_table(
                ["能力方", "规则列数", "本侧列数", "同名匹配", "复现率", "Jaccard"],
                [[p.right, p.left_cols, p.right_cols, p.matched,
                  f"{p.recall}%", f"{p.jaccard}%"] for p in report.master_pairs]))
            lines.append("")
        if report.master_missing:
            lines.append("未产出总表的管线：" + "、".join(report.master_missing))
            lines.append("")

    if report.common_all:
        lines.append("## 交集")
        lines.append("")
        lines.append("按已产出的管线取交集；盘古未产出时这一列只反映两方，不写成三方结论。")
        lines.append("")
        lines.append(_table(["年份", "参与管线数", "共有列"],
                            [[year, report.common_sources.get(year, 0), count]
                             for year, count in report.common_all.items()]))
        lines.append("")

    if report.mappings:
        lines.append("## 映射规模")
        lines.append("")
        lines.append(_table(["管线", "列名映射条数", "取值统一条数", "备注"],
                            [[m.source, m.column_mapping, m.value_mapping, m.note or "—"]
                             for m in report.mappings]))
        lines.append("")

    diffs = [p for p in report.pairs if p.missing_diffs]
    if diffs:
        lines.append("## 非空率差异 Top（相对规则管线）")
        lines.append("")
        for pair in diffs:
            lines.append(f"**{pair.right}**")
            lines.append("")
            lines.append(_table(["规则列", "规则非空%", "本侧非空%", "差值(pp)"],
                                pair.missing_diffs))
            lines.append("")

    if report.problems:
        lines.append("## 说明")
        lines.append("")
        lines.extend(f"- {item}" for item in report.problems)
        lines.append("")
    return "\n".join(lines)


def _table(header: list[str], rows: list[list[Any]]) -> str:
    out = ["| " + " | ".join(str(h) for h in header) + " |",
           "| " + " | ".join("---" for _ in header) + " |"]
    for row in rows:
        out.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="三方对账（只读对齐表，不调模型）")
    parser.add_argument("--years", nargs="*", type=int, default=[2019])
    parser.add_argument("--out", default=str(REPO_ROOT / "pangu" / "reports"))
    args = parser.parse_args(argv)

    report = run(args.years)
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = REPO_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "parity_three_way.md").write_text(md(report), encoding="utf-8")
    payload = {
        "years": report.years,
        "produced": report.produced,
        "missing": report.missing,
        "rows": [item.__dict__ for item in report.rows],
        "pairs": [item.__dict__ for item in report.pairs],
        "common_all": report.common_all,
        "common_sources": report.common_sources,
        "mappings": [item.__dict__ for item in report.mappings],
        "master_cols": report.master_cols,
        "master_pairs": [item.__dict__ for item in report.master_pairs],
        "master_missing": report.master_missing,
        "problems": report.problems,
    }
    (out_dir / "parity_three_way.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    for name, years in report.produced.items():
        print(f"[parity] {name}: 已产出 {years or '—'}；缺 {report.missing.get(name) or '—'}")
    for pair in report.pairs:
        print(f"[parity] 分年口径 {pair.right} vs 规则：{pair.matched}/{pair.left_cols} 列，"
              f"复现率 {pair.recall}%，Jaccard {pair.jaccard}%")
    for pair in report.master_pairs:
        print(f"[parity] 总表口径 {pair.right} vs 规则：{pair.matched}/{pair.left_cols} 列，"
              f"复现率 {pair.recall}%，Jaccard {pair.jaccard}%")
    if report.master_missing:
        print(f"[parity] 无总表：{', '.join(report.master_missing)}")
    print(f"[parity] 写出 {out_dir / 'parity_three_way.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
