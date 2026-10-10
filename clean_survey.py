# -*- coding: utf-8 -*-
"""PSF 年度开发者调查原始数据清洗管线（2019-2023）。

用法：
    python clean_survey.py            # 清洗全部年份
    python clean_survey.py 2023 2019  # 只清洗指定年份

输入：根目录下的 *_sharing_data_outside.csv / python_psf_external_19.csv
输出：cleaned/cleaned_<year>.csv 与 cleaned/cleaning_report.md
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "cleaned"

# 各年输入文件（主数据）
FILES: dict[int, str] = {
    2019: "2019_python_psf_external_19.csv",
    2020: "2020_2020_sharing_data_outside.csv",
    2021: "2021_2021_sharing_data_outside.csv",
    2022: "2022_2022_sharing_data_outside.csv",
    2023: "2023_2023_sharing_data_outside.csv",
}

# 统一缺失标记（注意 'None' 是合法选项文本，不作缺失处理）
MISSING_TOKENS = {"", "na", "n/a", "nan", "null", "none.", "unknown"}

# 2019 问题文本 -> 2020-2023 前缀命名方案的组前缀映射（跨年题目对齐）
QUESTION_GROUP_ALIASES: dict[str, str] = {
    "what other language(s) do you use?": "other.lang",
    " what do you use python for?": "other.purposes",
    "for what purposes do you mainly use python?": "main.purposes",
    "to what extent are you involved in the following activities?": "how.involved",
    "what editors/ides do you use for python development in addition to your main one?": "ide",
    "which database(s) do you regularly use, if any?": "database",
    "what data science framework(s) do you use in addition to python?": "frameworks",
    "what web frameworks do you use in addition to python?": "web",
    "which testing frameworks do you use?": "unittesting",
    "what cloud platforms do you use?": "cloud",
    "what ci/cd systems do you use?": "ci",
}

# 2019 单选题 -> 2020-2023 命名方案映射
SINGLE_COL_ALIASES: dict[str, str] = {
    "is python the main language you use for your current projects?": "is.python.main",
    "how long have you been programming in python?": "python.years",
    "how many years of professional coding experience do you have?": "years.of.coding",
    "what do you use python for the most?": "use.python.most",
    "do you contribute to open-source projects?": "opensource.contribution",
}


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^0-9a-z]+", "_", text.lower()).strip("_")
    return s[:max_len].rstrip("_")


def norm_ws(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def is_missing(value: str) -> bool:
    return norm_ws(value).lower() in MISSING_TOKENS


def clean_cell(value: str) -> str:
    """单元格规范化：去首尾空白、压缩内部空白、统一连字符/省略号、缺失标记归空。"""
    s = norm_ws(value)
    s = s.replace("\u2013", "-").replace("\u2026", "...")
    return "" if is_missing(s) else s


def rename_columns(df: pd.DataFrame, style: str) -> tuple[pd.DataFrame, dict[str, str]]:
    """列名规范化，返回 (新df, 旧->新映射)。"""
    mapping: dict[str, str] = {}
    used = Counter()
    for col in df.columns:
        if col == "response_id":
            new = col
        elif style == "question":
            m = re.match(r"^(.*?):(.*)$", col, flags=re.S)
            if m and len(m.group(1)) <= 80 and m.group(2).strip():
                value_part, question_part = m.group(1), norm_ws(m.group(2))
                group_slug = QUESTION_GROUP_ALIASES.get(question_part.lower())
                if group_slug:
                    new = f"{group_slug}.{norm_ws(value_part)}"
                else:
                    new = f"{slugify(question_part)}[{norm_ws(value_part)}]"
            else:
                q = norm_ws(col).lower()
                new = SINGLE_COL_ALIASES.get(q, slugify(q))
        else:  # prefixed（2020-2023）：保留点分结构，仅规范空白
            new = norm_ws(col)
        if used[new]:
            new = f"{new}__dup{used[new]}"
        used[new] += 1
        mapping[col] = new
    return df.rename(columns=mapping), mapping


def binarize_multiselect(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """多选二值列归一为 0/1。

    判定规则（两种命名风格通用）：非缺失取值基本只有一种、且该值出现在列名中
    （前缀列取最后一个'.'后的文本，括号列取[...]内文本）的列视为多选列。
    """
    converted: list[str] = []
    df = df.copy()
    for col in df.columns:
        m = re.search(r"\[(.+)\]$", col)
        option = m.group(1) if m else (col.rsplit(".", 1)[-1] if "." in col else "")
        if not option:
            continue
        vals = df[col][df[col] != ""]
        if vals.empty:
            continue
        distinct = set(vals.unique())
        if len(distinct) == 1 and distinct.pop().lower() == option.lower():
            df[col] = (df[col] != "").astype(int)
            converted.append(col)
    return df, converted


def convert_numeric(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """将整列可解析为数值的列转换为 int/float。"""
    converted: list[str] = []
    df = df.copy()
    for col in df.columns:
        if col == "response_id":
            df[col] = pd.to_numeric(df[col], errors="raise").astype("int64")
            converted.append(col)
            continue
        if not pd.api.types.is_object_dtype(df[col]):
            continue  # 已是数值/布尔等类型，跳过
        vals = df[col][df[col] != ""]
        if vals.empty or not bool(vals.str.fullmatch(r"-?\d+(\.\d+)?").all()):
            continue
        num = pd.to_numeric(vals)
        if (num == num.astype("int64")).all():
            df[col] = pd.to_numeric(df[col].replace("", None)).astype("Int64")
        else:
            df[col] = pd.to_numeric(df[col].replace("", None)).astype("float64")
        converted.append(col)
    return df, converted


def clean_year(year: int) -> dict:
    src = ROOT / FILES[year]
    style = "question" if year == 2019 else "prefixed"
    raw = pd.read_csv(src, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    report: dict = {"year": year, "src": src.name, "rows_in": len(raw), "cols_in": raw.shape[1]}

    df, name_map = rename_columns(raw, style)

    # 单元格规范化
    df = df.apply(lambda s: s.map(clean_cell))

    # 删除全空列 / 全空行
    empty_cols = [c for c in df.columns if (df[c] == "").all()]
    df = df.drop(columns=empty_cols)
    empty_rows = df.index[(df == "").all(axis=1)]
    df = df.drop(index=empty_rows).reset_index(drop=True)

    # 删除完全重复行 / 重复列（按内容判定，保留首个）
    dup_rows = int(df.duplicated().sum())
    df = df.drop_duplicates().reset_index(drop=True)
    dedup_cols: list[str] = []
    seen: dict[tuple, str] = {}
    for col in list(df.columns):
        key = tuple(df[col].tolist())
        if key in seen:
            dedup_cols.append(col)
        else:
            seen[key] = col
    df = df.drop(columns=dedup_cols)

    # 多选归一与类型转换
    df, bin_cols = binarize_multiselect(df)
    df, num_cols = convert_numeric(df)

    missing_pct = (df == "").mean().sort_values(ascending=False)
    report.update(
        rows_out=len(df),
        cols_out=df.shape[1],
        dropped_empty_cols=len(empty_cols),
        dropped_empty_rows=len(empty_rows),
        dropped_dup_rows=dup_rows,
        dropped_dup_cols=len(dedup_cols),
        binarized=len(bin_cols),
        numeric=len(num_cols),
        top_missing=[
            (c, round(float(p) * 100, 1)) for c, p in missing_pct.head(10).items() if p > 0
        ],
        renames=name_map,
        bin_col_names=bin_cols,
        num_col_names=num_cols,
    )
    OUT_DIR.mkdir(exist_ok=True)
    df.to_csv(OUT_DIR / f"cleaned_{year}.csv", index=False)
    return report


def write_report(reports: list[dict]) -> None:
    lines = ["# PSF Survey 数据清洗报告", ""]
    lines.append(f"生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}")
    lines.append("清洗管线：clean_survey.py（缺失标记归空 -> 列名规范化 -> 去空/去重 -> 多选归一 -> 数值转换）")
    lines.append("")
    lines.append("| 年份 | 行数(前/后) | 列数(前/后) | 空列 | 空行 | 重复行 | 重复列 | 多选归一 | 数值列 |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in reports:
        lines.append(
            f"| {r['year']} | {r['rows_in']}/{r['rows_out']} | {r['cols_in']}/{r['cols_out']} "
            f"| {r['dropped_empty_cols']} | {r['dropped_empty_rows']} | {r['dropped_dup_rows']} "
            f"| {r['dropped_dup_cols']} | {r['binarized']} | {r['numeric']} |"
        )
    for r in reports:
        lines += ["", f"## {r['year']} 年详情", ""]
        lines.append(f"源文件：`{r['src']}`")
        lines += ["", "### 缺失率最高的列", ""]
        if r["top_missing"]:
            lines += [f"- `{c}`：{p}%" for c, p in r["top_missing"]]
        else:
            lines.append("- 无")
        renamed = {k: v for k, v in r["renames"].items() if k != v}
        if renamed:
            lines += ["", "### 列名映射（前 20 条）", ""]
            lines += [f"- `{k}` -> `{v}`" for k, v in list(renamed.items())[:20]]
            lines.append(f"- （共 {len(renamed)} 列重命名）")
        if r["num_col_names"]:
            lines += ["", "### 转换为数值的列", ""]
            lines += [f"- `{c}`" for c in r["num_col_names"]]
        lines.append("")
    (OUT_DIR / "cleaning_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    years = [int(a) for a in sys.argv[1:]] or sorted(FILES)
    reports = [clean_year(y) for y in years]
    write_report(reports)
    for r in reports:
        print(
            f"{r['year']}: {r['rows_in']}x{r['cols_in']} -> {r['rows_out']}x{r['cols_out']} | "
            f"空列{r['dropped_empty_cols']} 空行{r['dropped_empty_rows']} "
            f"重复行{r['dropped_dup_rows']} 重复列{r['dropped_dup_cols']} "
            f"多选归一{r['binarized']} 数值列{r['numeric']}"
        )
    print(f"报告：{OUT_DIR / 'cleaning_report.md'}")


if __name__ == "__main__":
    main()
