"""文本归一（与 align_survey.py / clean_survey.py 保持同一语义）。

项目约定：字符串归一统一走 norm_text() / norm_key()，不另写散落正则。
"""
from __future__ import annotations

import re

from .config import MISSING_TOKENS

PUNCT_TRANS = {
    "\u2019": "'", "\u2018": "'", "\u2013": "-", "\u2014": "-",
    "\u2026": "...", "\u00a0": " ", "\u201c": '"', "\u201d": '"',
}


def norm_ws(text: str) -> str:
    """压缩空白并去首尾。"""
    return re.sub(r"\s+", " ", str(text)).strip()


def norm_text(text: str) -> str:
    """用于匹配的归一文本：统一标点、压缩空白、去尾部括号附注与冒号。"""
    s = str(text)
    for k, v in PUNCT_TRANS.items():
        s = s.replace(k, v)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    return re.sub(r"\s+", " ", s).strip().rstrip(":").strip()


def norm_key(text: str) -> str:
    """匹配键：归一 + 小写 + 去所有非字母数字字符。"""
    return re.sub(r"[^0-9a-z]+", "", norm_text(text).lower())


def is_missing(value: str, extra_tokens: set[str] | None = None) -> bool:
    tokens = MISSING_TOKENS if extra_tokens is None else (MISSING_TOKENS | extra_tokens)
    return norm_ws(value).lower() in tokens


# 上游导出时把 "<br />" 直接删掉留下的粘连文本（如 "From timeto time"），显式修复
VALUE_FIXES = {
    "from timeto time": "From time to time",
}


def clean_cell(value: str, extra_tokens: set[str] | None = None) -> str:
    """单元格规范化：去 HTML 残留、压缩空白、统一连字符/省略号、缺失标记归空。"""
    s = re.sub(r"<[^<>]{1,24}>", " ", str(value))
    s = norm_ws(s)
    s = s.replace("\u2013", "-").replace("\u2026", "...")
    s = VALUE_FIXES.get(s.lower(), s)
    return "" if is_missing(s, extra_tokens) else s


def option_from_header(column: str) -> str:
    """从原始表头推断选项文本。

    - 2019：`选项:完整问句`，取第一个冒号前的内容
    - 2020+：`组路径.选项`，取最后一段点分
    - 兼容 `... [选项]` 写法
    """
    if ":" in column:
        head = column.split(":", 1)[0].strip()
        if head and len(head) <= 80:
            return head
    m = re.search(r"\[(.+)\]$", column)
    if m:
        return m.group(1).strip()
    return column.rsplit(".", 1)[-1].strip() if "." in column else ""


def slugify(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^0-9a-z]+", "_", str(text).lower()).strip("_")
    return s[:max_len].rstrip("_")


def dedup_names(names: list[str]) -> list[str]:
    """同名冲突追加 __dup<k> 后缀（与 clean_survey.py 一致，不合并内容不同的列）。"""
    used: dict[str, int] = {}
    out: list[str] = []
    for name in names:
        new = name
        if used.get(name):
            new = f"{name}__dup{used[name]}"
        used[name] = used.get(name, 0) + 1
        used.setdefault(new, 0)
        out.append(new)
    return out
