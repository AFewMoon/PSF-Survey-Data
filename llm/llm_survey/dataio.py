"""CSV 读写：统一 UTF-8 BOM 读取、缺失为空的约定。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import ALIGNED_DIR, CLEANED_DIR, RAW_ENC, RAW_FILES, ROOT, YEARS


def read_raw(year: int) -> pd.DataFrame:
    """读取原始 CSV（全字符串，缺失保持空字符串）。"""
    path = ROOT / RAW_FILES[year]
    if not path.exists():
        raise FileNotFoundError(f"原始数据缺失：{path}")
    return pd.read_csv(path, dtype=str, keep_default_na=False, encoding=RAW_ENC)


def read_cleaned(year: int) -> pd.DataFrame:
    path = CLEANED_DIR / f"cleaned_llm_{year}.csv"
    return pd.read_csv(path, keep_default_na=False, encoding=RAW_ENC)


def read_aligned(year: int) -> pd.DataFrame:
    path = ALIGNED_DIR / f"cleaned_aligned_llm_{year}.csv"
    return pd.read_csv(path, keep_default_na=False, encoding=RAW_ENC)


def read_master() -> pd.DataFrame:
    path = ALIGNED_DIR / f"survey_{YEARS[0]}_{YEARS[-1]}_master_llm.csv"
    return pd.read_csv(path, keep_default_na=False, encoding=RAW_ENC)


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
