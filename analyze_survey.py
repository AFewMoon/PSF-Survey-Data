# -*- coding: utf-8 -*-
"""PSF Survey 统计分析管线：2024 年画像 + 2019-2024 跨年趋势。

读取 aligned/cleaned_aligned_<year>.csv，输出 analysis/ 目录：
  - analysis_report.md          分析报告（Markdown 表格）
  - stats/*.csv                 分主题统计（profile_2024_*.csv / trends_*.csv）

口径：占比 = 该选项非空受访者数 / 该题有回答的受访者数（缺失不入分母）；
多选二值列的非空率即选中率。
"""
from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / "aligned"
OUT_DIR = ROOT / "analysis"
STATS_DIR = OUT_DIR / "stats"
YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
LATEST = 2024

GROUP_TOPICS: list[tuple[str, list[str], list[str]]] = [
    ("other_lang", ["other.lang"], []),
    ("ide_editor", ["ide.editor"], ["ide.editor.features"]),
    ("ml_frameworks", ["frameworks.ml"], []),
    ("web_frameworks", ["web.frameworks"], []),
    ("databases", ["database"], []),
    ("cloud_platforms", ["cloud.platform"], []),
    ("ai_coding_tools", ["ai.tools.coding"], []),
    ("testing", ["unittesting"], []),
    ("orm", ["orm"], []),
    ("ci", ["ci"], []),
    ("bigdata", ["bigdata"], []),
    ("os", ["devenv.os"], []),
    ("env_isolation", ["environments.isolate"], []),
    ("dependency_tools", ["dependency.tools"], []),
    ("job_roles", ["job.role"], []),
    ("data_exploration", ["exploration.tools"], []),
    ("ml_training", ["training.platforms"], []),
    ("ml_deployment", ["deployment.tools"], []),
]

PROFILE_SINGLE: list[tuple[str, str]] = [
    ("is_python_main", "is.python.main"),
    ("python_years", "python.years"),
    ("years_of_coding", "years.of.coding"),
    ("main_purposes", "main.purposes"),
    ("use_python_most", "use.python.most"),
    ("opensource", "opensource.contribution"),
    ("employment", "employment.status"),
    ("company_size", "company.size"),
    ("age", "age"),
    ("region", "region"),
]

TOP_N_PROFILE = 15
TOP_N_TREND = 10


def load_years() -> dict[int, pd.DataFrame]:
    return {y: pd.read_csv(IN_DIR / f"cleaned_aligned_{y}.csv", keep_default_na=False,
                           encoding="utf-8-sig") for y in YEARS}


def group_columns(df: pd.DataFrame, prefixes: list[str]) -> list[str]:
    return [c for c in df.columns if any(c == p or c.startswith(p + ".") for p in prefixes)]


def option_of(col: str, prefixes: list[str] | None = None) -> str:
    """剥离组前缀得到选项文本；未提供前缀时剥离到首个'.'；清理尾部数字后缀（上游命名如 None_300）。"""
    if prefixes:
        for p in sorted(prefixes, key=len, reverse=True):
            if col == p:
                return col
            if col.startswith(p + "."):
                col = col[len(p) + 1:]
                break
    else:
        col = col.split(".", 1)[1] if "." in col else col
    return re.sub(r"_\d+$", "", col)


def nonempty_mask(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """非空掩码：二值/数值列按 !=0，字符串列按 != ''。"""
    parts = {}
    for c in cols:
        s = df[c]
        parts[c] = (s != 0) if s.dtype.kind in "biuf" else (s != "")
    return pd.DataFrame(parts, index=df.index)


def group_rates(dfs: dict[int, pd.DataFrame], prefixes: list[str], top_n: int,
                exclude: list[str] | None = None) -> pd.DataFrame:
    """组内选项跨年使用率矩阵（行=选项，列=年份，单位 %）。exclude 为需排除的子前缀。"""
    per_year = {}
    for y, df in dfs.items():
        cols = [c for c in group_columns(df, prefixes)
                if not exclude or not any(c.startswith(e + ".") for e in exclude)]
        if not cols:
            continue
        rate = (nonempty_mask(df, cols).sum() / len(df)).rename(
            lambda c: option_of(c, prefixes))
        per_year[y] = rate
    if not per_year:
        return pd.DataFrame()
    mat = pd.DataFrame(per_year)
    mat = mat.loc[mat.max(axis=1).sort_values(ascending=False).index].head(top_n)
    return (mat * 100).round(1)


def single_dist(df: pd.DataFrame, col: str, top_n: int = 12) -> tuple[pd.DataFrame, int]:
    s = df[col]
    answered = int((s != "").sum())
    vc = s[s != ""].value_counts().head(top_n)
    out = pd.DataFrame({"count": vc})
    out["pct"] = (out["count"] / answered * 100).round(1)
    out.index.name = "value"
    return out, answered


def trend_single(dfs: dict[int, pd.DataFrame], col: str) -> pd.DataFrame:
    """单选题各选项的跨年占比矩阵（单位 %，按当年回答人数）。"""
    per_year = {}
    for y, df in dfs.items():
        if col not in df.columns:
            continue
        s = df[col]
        answered = (s != "").sum()
        per_year[y] = (s.value_counts() / answered * 100).round(1)
    return pd.DataFrame(per_year)


def write_report(dfs: dict[int, pd.DataFrame]) -> None:
    df = dfs[LATEST]
    n = len(df)
    r: list[str] = [
        "# PSF Survey 2024 统计分析与跨年趋势（2019-2024）", "",
        f"生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}  |  数据：aligned/ 目录（清洗对齐后）", "",
        f"口径：占比 = 选项非空数 / 该题回答人数（多选组为选中者/当年总样本，单位 %）。", "",
    ]

    # ---- 2024 画像 ----
    r += [f"## 1. {LATEST} 年受访者画像", "", f"总样本：**{n:,}** 份回复。", ""]
    r += ["### 1.1 基本构成", ""]
    for topic, col in PROFILE_SINGLE:
        if col not in df.columns:
            continue
        dist, answered = single_dist(df, col)
        dist.reset_index().to_csv(STATS_DIR / f"profile_2024_{topic}.csv", index=False)
        r += [f"**{col}**（回答 {answered:,} 人）", "", dist.to_markdown(), ""]

    r += ["### 1.2 工具与技术使用率（Top 15）", ""]
    for topic, prefixes, excl in GROUP_TOPICS:
        mat = group_rates({LATEST: df}, prefixes, TOP_N_PROFILE, exclude=excl)
        if mat.empty:
            continue
        out = mat[LATEST].rename("pct").to_frame()
        out.index.name = "option"
        out.to_csv(STATS_DIR / f"profile_2024_{topic}.csv")
        r += [f"**{topic}**", "", out.to_markdown(), ""]

    # ---- 跨年趋势 ----
    r += ["## 2. 跨年趋势", ""]
    for topic, prefixes, excl in GROUP_TOPICS:
        mat = group_rates(dfs, prefixes, TOP_N_TREND, exclude=excl)
        if mat.empty:
            continue
        mat.index.name = "option"
        mat.to_csv(STATS_DIR / f"trends_{topic}.csv")
        r += [f"### {topic}", "", mat.to_markdown(), ""]
        if {2023, LATEST} <= set(mat.columns):
            delta = mat[LATEST] - mat[2023]
            if (delta > 0).any():
                r.append(f"- 上升最快：**{delta.idxmax()}**（+{delta.max():.1f} pp）")
            if (delta < 0).any():
                r.append(f"- 下降最快：**{delta.idxmin()}**（{delta.min():.1f} pp）")
            r.append("")

    for topic, col in [("is_python_main", "is.python.main"), ("python_years", "python.years"),
                       ("years_of_coding", "years.of.coding"), ("main_purposes", "main.purposes"),
                       ("employment", "employment.status")]:
        mat = trend_single(dfs, col)
        if mat.empty:
            continue
        mat.index.name = "value"
        mat.to_csv(STATS_DIR / f"trends_{topic}.csv")
        r += [f"### {topic}（{col}）", "", mat.to_markdown(), ""]

    # ---- 方法与注意事项 ----
    r += [
        "## 3. 方法与注意事项", "",
        "- 数据为自报抽样调查，占比受样本构成影响；跨年比较注意问卷措辞与选项增删。",
        f"- {LATEST} 年数据来源：JetBrains 官方发布（Google Drive 公开文件夹），经 clean_survey.py 与 align_survey.py 处理。",
        "- 2020 年原始数据含 12,554 个全空行（已删）；2019 年 is.python.main 约 25% 缺失。",
        "- 各年总样本：  " + "; ".join(f"{y}: {len(dfs[y]):,}" for y in YEARS),
        "",
    ]
    (OUT_DIR / "analysis_report.md").write_text("\n".join(r), encoding="utf-8")


def main() -> None:
    STATS_DIR.mkdir(parents=True, exist_ok=True)
    dfs = load_years()
    write_report(dfs)
    print(f"报告: {OUT_DIR / 'analysis_report.md'}")
    print(f"统计 CSV: {STATS_DIR}（{len(list(STATS_DIR.glob('*.csv')))} 个文件）")


if __name__ == "__main__":
    main()
