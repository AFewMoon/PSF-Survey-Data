"""列画像：确定性统计 + 脱敏样本，作为模型决策的唯一输入。

模型永远看不到整表：只看「列名 + 非空率 + 基数 + 至多 6 个截断样本值」。
自由文本列（可能含个人信息）只给结构特征，不给原文。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

import pandas as pd

from . import config
from .dataio import read_raw, read_json, write_json
from .textnorm import option_from_header

FREE_TEXT_HINTS = (
    "other", "comment", "describe", "explain", "why", "email", "name",
    "feedback", "suggestion", "text", "reason", "url", "address",
)


def _is_free_text(column: str, n_unique: int, structured: bool) -> bool:
    """自由文本判定：结构化勾选列（取值恒等于选项/0,1/选项+程度）不算自由文本。"""
    if structured:
        return False
    low = column.lower()
    if any(h in low for h in FREE_TEXT_HINTS):
        return True
    return n_unique > config.PROFILE_FREE_TEXT_UNIQUE


def _is_level(option: str, values: list[str], n_unique: int) -> bool:
    """程度网格识别：取值均为「选项 + 冒号 + 程度」形式（如 "X : primary activity"）。"""
    if not option or not (2 <= n_unique <= 6):
        return False
    pattern = re.compile(re.escape(option.strip().lower()) + r"\s*[:：]\s*\S.*")
    return all(pattern.fullmatch(v.strip().lower()) for v in values)


def _hash_column(s: pd.Series) -> str:
    """列指纹，用于确定性识别内容完全相同的重复列。"""
    try:
        arr = pd.util.hash_pandas_object(s, index=False).to_numpy()
        return hashlib.sha1(arr.tobytes()).hexdigest()[:16]
    except (TypeError, ValueError):
        return hashlib.sha1(repr(s.tolist()).encode("utf-8")).hexdigest()[:16]


def build_profile(year: int) -> dict[str, Any]:
    df = read_raw(year)
    rows, cols = df.shape
    empty_rows = int((df == "").all(axis=1).sum())
    dup_rows = int(df.duplicated().sum())

    columns: list[dict[str, Any]] = []
    for col in df.columns:
        s = df[col]
        non_empty_s = s[s != ""]
        non_empty = int(len(non_empty_s))
        vc = non_empty_s.value_counts()
        n_unique = int(len(vc))
        numeric_like = bool(non_empty) and bool(
            non_empty_s.str.fullmatch(r"-?\d+(\.\d+)?").all()
        )
        binary_like = n_unique > 0 and set(vc.index.astype(str)) <= {"0", "1"}
        option = option_from_header(col)
        values = [str(v) for v in vc.index]
        # 2019 的勾选列用 "NA" 表示未选中，判定时要先排除缺失标记
        meaningful = [v for v in values if v.strip().lower() not in config.MISSING_TOKENS]
        multi_like = bool(
            option and len(meaningful) == 1
            and meaningful[0].strip().lower() == option.lower()
        )
        level_like = _is_level(option, meaningful, len(meaningful))
        structured = multi_like or binary_like or level_like
        redacted = _is_free_text(col, n_unique, structured)
        top = [] if redacted else [str(v)[: config.PROMPT_VALUE_MAXLEN]
                                   for v in vc.index[: config.PROMPT_SAMPLE_VALUES]]
        entry: dict[str, Any] = {
            "name": str(col),
            "non_empty_pct": round(non_empty / rows * 100, 1) if rows else 0.0,
            "n_unique": n_unique,
            "top_share": round(int(vc.iloc[0]) / non_empty * 100, 1) if non_empty else 0.0,
            "numeric_like": numeric_like,
            "binary_like": binary_like,
            "multi_like": multi_like,
            "level_like": level_like,
            "redacted": redacted,
            "col_hash": _hash_column(s),
        }
        if redacted:
            lengths = non_empty_s.str.len()
            entry["value_shape"] = {
                "note": "自由文本，样本已脱敏，仅给出结构特征",
                "len_min": int(lengths.min()) if non_empty else 0,
                "len_median": int(lengths.median()) if non_empty else 0,
                "len_max": int(lengths.max()) if non_empty else 0,
            }
        else:
            entry["top"] = top
        columns.append(entry)

    empty_cols = [c["name"] for c in columns if c["non_empty_pct"] == 0.0]
    hash_groups: dict[str, list[str]] = {}
    for c in columns:
        hash_groups.setdefault(c["col_hash"], []).append(c["name"])
    dup_col_groups = [g for g in hash_groups.values() if len(g) > 1]

    profile = {
        "year": year,
        "profile_version": config.PROFILE_VERSION,
        "rows": rows,
        "cols": cols,
        "empty_rows": empty_rows,
        "empty_cols": empty_cols,
        "dup_rows": dup_rows,
        "dup_col_groups": dup_col_groups,
        "columns": columns,
    }
    write_json(config.PROFILE_DIR / f"{year}.json", profile)
    return profile


def load_profile(year: int, rebuild: bool = False) -> dict[str, Any]:
    path = config.PROFILE_DIR / f"{year}.json"
    if path.exists() and not rebuild:
        payload = read_json(path)
        if payload.get("profile_version") == config.PROFILE_VERSION:
            return payload
    return build_profile(year)


def column_index(profile: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {c["name"]: c for c in profile["columns"]}


def compact_row(profile: dict[str, Any], column: str) -> dict[str, Any]:
    """送给模型的单列紧凑描述（不含原文自由文本）。"""
    info = column_index(profile).get(column, {})
    row: dict[str, Any] = {
        "column": column,
        "non_empty_pct": info.get("non_empty_pct", 0.0),
        "n_unique": info.get("n_unique", 0),
    }
    if info.get("redacted"):
        row["value_shape"] = info.get("value_shape", {})
    else:
        row["top"] = info.get("top", [])
    flags = [
        name for name in ("numeric_like", "binary_like", "multi_like", "level_like")
        if info.get(name)
    ]
    if flags:
        row["flags"] = flags
    return row
