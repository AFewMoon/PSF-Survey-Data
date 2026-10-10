"""plot_survey.py — PSF/JetBrains Python 开发者调查跨年统计图表生成脚本。

数据源：aligned/survey_2019_2023_master.csv（只读，产物写入 charts/）。
依赖：pandas、numpy、matplotlib（本项目新增绘图依赖）。

用法：
    python plot_survey.py            # 生成全部 8 张图
    python plot_survey.py 1 5        # 只生成编号 1 与 5 的图
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 配置区：路径、年份、列清单、口径映射（修改图表口径只改这里）
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
MASTER = ROOT / "aligned" / "survey_2019_2023_master.csv"
CHARTS_DIR = ROOT / "charts"

YEARS = [2019, 2020, 2021, 2022, 2023]
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]

SINGLE_COLS = [
    "is.python.main",
    "main.purposes",
    "use.python.most",
    "python.years",
    "years.of.coding",
]

MULTI_GROUPS: dict[str, list[str]] = {
    "web.frameworks": [
        "web.frameworks.Bottle",
        "web.frameworks.CherryPy",
        "web.frameworks.Django",
        "web.frameworks.Falcon",
        "web.frameworks.Flask",
        "web.frameworks.Hug",
        "web.frameworks.None",
        "web.frameworks.Pyramid",
        "web.frameworks.Tornado",
        "web.frameworks.web2py",
    ],
    "database": [
        "database.Amazon Redshift",
        "database.Cassandra",
        "database.Couchbase",
        "database.DB2",
        "database.HBase",
        "database.MS SQL Server",
        "database.MongoDB",
        "database.MySQL",
        "database.Neo4j",
        "database.None",
        "database.Oracle Database",
        "database.PostgreSQL",
        "database.Redis",
        "database.SQLite",
        "database.h2",
    ],
    "ide.editor": [
        "ide.editor.Atom",
        "ide.editor.Emacs",
        "ide.editor.IDLE",
        "ide.editor.IntelliJ IDEA",
        "ide.editor.Jupyter Notebook",
        "ide.editor.JupyterLab",
        "ide.editor.NotePad++",
        "ide.editor.PyCharm Community Edition",
        "ide.editor.PyCharm Professional Edition",
        "ide.editor.Python Tools for Visual Studio",
        "ide.editor.Spyder",
        "ide.editor.Sublime Text",
        "ide.editor.Vim",
        "ide.editor.Visual Studio Code",
    ],
}

# 同义取值归并（跨年问卷措辞差异），未匹配的取值保留原文
MAIN_LANG_CANON = {
    "Yes": "作为主要语言",
    "No, I use Python as a secondary language": "作为副语言",
    "No, I don't use Python for my current projects": "当前未用于项目",
}

PURPOSE_CANON = {
    "For work": "工作用途",
    "Work": "工作用途",
    "For personal, educational or side projects": "个人/学习/副业项目",
    "Personal, educational, or side projects": "个人/学习/副业项目",
    "Both for work and personal": "工作与个人兼顾",
    "Both for work and personal projects": "工作与个人兼顾",
}

USE_CASE_CANON = {
    "Web development": "Web 开发",
    "Data analysis": "数据分析",
    "Machine learning": "机器学习",
    "DevOps / System administration / Writing automation scripts": "DevOps/系统管理/自动化",
    "Educational purposes": "教学",
    "Desktop development": "桌面开发",
    "Programming of web parsers / scrapers / crawlers": "爬虫/解析器",
    "Software prototyping": "软件原型",
    "Software testing / Writing automated tests": "软件测试/自动化测试",
    "Network programming": "网络编程",
    "Game development": "游戏开发",
    "Embedded development": "嵌入式开发",
    "Data engineering": "数据工程",
    "Computer graphics": "计算机图形",
    "Academic research": "学术研究",
    "Mobile development": "移动开发",
    "Multimedia applications development": "多媒体应用",
    "Design / Data visualization": "设计/数据可视化",
    "MLOps": "MLOps",
    "Other": "其他",
    "Other - Write In": "其他（自填）",
}

YEARS_EXP_ORDER = ["Less than 1 year", "1-2 years", "3-5 years", "6-10 years", "11+ years"]
YEARS_EXP_CANON = {
    "Less than 1 year": "不足 1 年",
    "1-2 years": "1–2 年",
    "3-5 years": "3–5 年",
    "6-10 years": "6–10 年",
    "11+ years": "11 年以上",
}

SOURCE_NOTE = "数据来源：PSF/JetBrains 年度 Python 开发者调查 2019–2023（自报抽样数据，跨年比较请注意问卷措辞差异）。"
MULTI_NOTE = "多选题：各选项使用率为独立比例，合计可超 100%；排名时已排除「None（不使用）」选项。"


# ---------------------------------------------------------------------------
# 通用工具：字体、读取、聚合（纯函数，传入 df 返回聚合表）
# ---------------------------------------------------------------------------
def setup_matplotlib() -> None:
    """Windows 中文字体与全局样式。"""
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.linestyle"] = "--"
    plt.rcParams["grid.alpha"] = 0.35


def load_master() -> pd.DataFrame:
    """按需读取 master 表（usecols 控制内存），year 转为 int。"""
    usecols = ["year"] + SINGLE_COLS + [c for cs in MULTI_GROUPS.values() for c in cs]
    df = pd.read_csv(MASTER, encoding="utf-8-sig", keep_default_na=False, usecols=usecols)
    df = df[df["year"].astype(str).str.strip().ne("")].copy()
    df["year"] = df["year"].astype(int)
    return df


def _footnote(fig: plt.Figure, n_by_year: dict[int, int], miss_by_year: dict[int, float],
              extra: str = "") -> None:
    """在图底部添加脚注：数据来源 + 各年样本量/缺失率 + 口径说明。"""
    n_str = "；".join(
        f"{y} n={n_by_year[y]:,}（缺失 {miss_by_year[y]:.1f}%）" for y in YEARS if y in n_by_year
    )
    parts = [SOURCE_NOTE, f"各年有效样本：{n_str}。"]
    if extra:
        parts.append(extra)
    fig.text(0.01, 0.012, "  ".join(parts), fontsize=7.5, color="#555555",
             va="bottom", ha="left", wrap=True)


def _print_summary(num: int, fname: str, n_by_year: dict[int, int],
                   miss_by_year: dict[int, float]) -> None:
    n_str = ", ".join(f"{y}={n_by_year[y]:,}" for y in YEARS if y in n_by_year)
    valid_miss = [v for v in miss_by_year.values() if pd.notna(v)]
    lo, hi = (min(valid_miss), max(valid_miss)) if valid_miss else (0.0, 0.0)
    print(f"[{num:02d}] {fname} 已生成；各年有效样本 {n_str}；缺失率 {lo:.1f}%–{hi:.1f}%")


def agg_single_by_year(df: pd.DataFrame, col: str, canon: dict[str, str] | None = None
                       ) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """单选题按年聚合。

    返回 (占比表[行=年份, 列=类别, 单位 %], 各年有效样本数, 各年缺失率 %)。
    canon: 取值归并映射；空字符串视为缺失。
    """
    v = df[col].replace("", np.nan)
    if canon is not None:
        v = v.map(canon)
    year = df["year"]
    valid = v.notna()
    tab = pd.crosstab(year[valid], v[valid], normalize="index") * 100
    tab = tab.reindex(index=YEARS, fill_value=0.0)
    n = valid.groupby(year).sum().astype(int).reindex(index=YEARS, fill_value=0)
    miss = (1.0 - valid.groupby(year).mean()).reindex(index=YEARS, fill_value=np.nan) * 100
    return tab, n, miss


def agg_multi_by_year(df: pd.DataFrame, group: str
                      ) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series, pd.Series]:
    """多选题组按年聚合。

    返回 (使用率表[行=选项, 列=年份, 单位 %], 人数表[行=选项, 列=年份],
          各年有效样本数, 各年缺失率 %)。
    有效样本 = 该组至少勾选一项（含 None）的受访者。
    """
    cols = MULTI_GROUPS[group]
    any_sel = (df[cols] == 1).any(axis=1)
    year = df["year"]
    rates = df.groupby("year")[cols].mean().reindex(index=YEARS).T * 100
    counts = df.groupby("year")[cols].sum().reindex(index=YEARS).T.astype(int)
    n = any_sel.groupby(year).sum().astype(int).reindex(index=YEARS, fill_value=0)
    miss = (1.0 - any_sel.groupby(year).mean()).reindex(index=YEARS, fill_value=np.nan) * 100
    return rates, counts, n, miss


def top_options(rates: pd.DataFrame, n_top: int = 10) -> list[str]:
    """按跨年总均值排序取 Top N（排除 *.None 选项）。"""
    ranked = rates.mean(axis=1).sort_values(ascending=False)
    ranked = ranked[~ranked.index.str.endswith(".None")]
    return list(ranked.head(n_top).index)


def option_label(col: str) -> str:
    """列名 -> 显示名（去前缀；无点分前缀的类别名原样返回）。"""
    return col.rsplit(".", 1)[1] if "." in col else col


# ---------------------------------------------------------------------------
# 通用绘图函数
# ---------------------------------------------------------------------------
def plot_stacked(tab: pd.DataFrame, n_by_year: pd.Series, miss_by_year: pd.Series,
                 title: str, ylabel: str, fname: str, extra_note: str = "",
                 order: list[str] | None = None) -> None:
    """按年份的 100% 堆叠柱状图，段内标注百分比（>=4% 才标注）。"""
    cats = order if order is not None else list(tab.columns)
    tab = tab.reindex(columns=cats, fill_value=0.0)
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    x = [str(y) for y in tab.index]
    bottom = np.zeros(len(tab))
    for i, cat in enumerate(cats):
        vals = tab[cat].to_numpy(dtype=float)
        ax.bar(x, vals, bottom=bottom, color=PALETTE[i % len(PALETTE)],
               label=cat, edgecolor="white", width=0.62)
        for j, (b, v) in enumerate(zip(bottom, vals)):
            if v >= 4.0:
                ax.text(j, b + v / 2, f"{v:.1f}%", ha="center", va="center",
                        fontsize=9, color="white", fontweight="bold")
        bottom += vals
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.set_ylim(0, 100)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=9)
    fig.subplots_adjust(left=0.09, right=0.76, top=0.90, bottom=0.20)
    _footnote(fig, n_by_year.to_dict(), miss_by_year.to_dict(), extra_note)
    fig.savefig(CHARTS_DIR / fname, dpi=300)
    plt.close(fig)


def plot_grouped_hbar(rates: pd.DataFrame, counts: pd.DataFrame | None,
                      options: list[str], n_by_year: pd.Series, miss_by_year: pd.Series,
                      title: str, xlabel: str, fname: str, extra_note: str = "",
                      labels: list[str] | None = None) -> None:
    """跨年分组水平条形图：每选项 5 个年份条，标注百分比（及人数）。"""
    n_opt = len(options)
    fig, ax = plt.subplots(figsize=(12, 1.05 * n_opt + 3.0))
    ypos = np.arange(n_opt, dtype=float)[::-1]
    bh = 0.8 / len(YEARS)
    show_counts = counts is not None
    vmax = float(rates.loc[options].to_numpy().max())
    for i, y in enumerate(YEARS):
        if y not in rates.columns:
            continue
        vals = rates.loc[options, y].to_numpy(dtype=float)
        cnts = counts.loc[options, y].to_numpy(dtype=int) if show_counts else None
        offset = (i - (len(YEARS) - 1) / 2) * bh
        ax.barh(ypos + offset, vals, height=bh * 0.9, color=PALETTE[i],
                label=str(y), edgecolor="white")
        for j, v in enumerate(vals):
            if v <= 0:
                continue
            txt = f"{v:.1f}%" + (f"（{cnts[j]:,}人）" if show_counts else "")
            ax.text(v + vmax * 0.01, ypos[j] + offset, txt, va="center",
                    fontsize=7.5, color="#333333")
    cat_names = labels if labels is not None else [option_label(c) for c in options]
    ax.set_yticks(ypos)
    ax.set_yticklabels(cat_names, fontsize=9.5)
    ax.set_ylim(-0.6, n_opt - 0.4)
    ax.set_xlim(0, vmax * 1.32)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)
    ax.legend(loc="lower right", frameon=False, fontsize=9, title="年份", title_fontsize=9)
    fig.subplots_adjust(left=0.24, right=0.97, top=0.93, bottom=0.16)
    _footnote(fig, n_by_year.to_dict(), miss_by_year.to_dict(), extra_note)
    fig.savefig(CHARTS_DIR / fname, dpi=300)
    plt.close(fig)


def plot_heatmap(tab: pd.DataFrame, counts: pd.DataFrame, row_order: list[str],
                 title: str, xlabel: str, ylabel: str, fname: str,
                 n_by_year: dict[int, int], miss_by_year: dict[int, float],
                 extra_note: str = "") -> None:
    """交叉热力图，单元格标注行内占比与人数。"""
    tab = tab.reindex(index=row_order, fill_value=0.0)
    counts = counts.reindex(index=row_order, fill_value=0)
    vmax = max(35.0, float(tab.to_numpy().max()))
    fig, ax = plt.subplots(figsize=(12.5, 6.5))
    im = ax.imshow(tab.to_numpy(), cmap="YlGnBu", aspect="auto", vmin=0, vmax=vmax)
    ax.set_xticks(range(tab.shape[1]))
    ax.set_xticklabels(list(tab.columns), rotation=25, ha="right", fontsize=9)
    ax.set_yticks(range(tab.shape[0]))
    ax.set_yticklabels(list(tab.index), fontsize=10)
    for r in range(tab.shape[0]):
        for c in range(tab.shape[1]):
            p = float(tab.iat[r, c])
            n = int(counts.iat[r, c])
            color = "white" if p > vmax * 0.55 else "#222222"
            ax.text(c, r, f"{p:.1f}%\n({n:,})", ha="center", va="center",
                    fontsize=8.5, color=color)
    cbar = fig.colorbar(im, ax=ax, shrink=0.85)
    cbar.set_label("组内占比（%）", fontsize=9)
    ax.set_title(title, fontsize=13, fontweight="bold", pad=14)
    ax.set_xlabel(xlabel, fontsize=10)
    ax.set_ylabel(ylabel, fontsize=10)
    ax.grid(False)
    fig.subplots_adjust(left=0.14, right=0.98, top=0.89, bottom=0.22)
    _footnote(fig, n_by_year, miss_by_year, extra_note)
    fig.savefig(CHARTS_DIR / fname, dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 图表定义（编号 -> 函数）
# ---------------------------------------------------------------------------
def chart_01(df: pd.DataFrame) -> None:
    tab, n, miss = agg_single_by_year(df, "is.python.main", MAIN_LANG_CANON)
    order = ["作为主要语言", "作为副语言", "当前未用于项目"]
    plot_stacked(tab, n, miss, "Python 作为主语言 / 副语言的比例（按年）",
                 "受访者占比（%）", "01_python_main_language.png", order=order)
    _print_summary(1, "01_python_main_language.png", n.to_dict(), miss.to_dict())


def chart_02(df: pd.DataFrame) -> None:
    tab, n, miss = agg_single_by_year(df, "main.purposes", PURPOSE_CANON)
    order = ["工作用途", "工作与个人兼顾", "个人/学习/副业项目"]
    plot_stacked(tab, n, miss, "Python 用途分布：工作 vs 个人（按年）",
                 "受访者占比（%）", "02_work_vs_personal.png", order=order,
                 extra_note="跨年问卷措辞不同（如 “For work” 与 “Work”），已归并为同一口径。")
    _print_summary(2, "02_work_vs_personal.png", n.to_dict(), miss.to_dict())


def chart_03(df: pd.DataFrame) -> None:
    v = df["use.python.most"].replace("", np.nan).map(USE_CASE_CANON)
    year = df["year"]
    valid = v.notna()
    top = list(v[valid].value_counts().head(8).index)
    v2 = v.where(v.isin(top), "其他（合并）")
    order = top + ["其他（合并）"]
    tab = pd.crosstab(year[valid], v2[valid], normalize="index") * 100
    tab = tab.reindex(index=YEARS, columns=order, fill_value=0.0)
    cnt = pd.crosstab(year[valid], v2[valid]).reindex(index=YEARS, columns=order, fill_value=0)
    n = valid.groupby(year).sum().astype(int)
    miss = (1.0 - valid.groupby(year).mean()) * 100
    plot_grouped_hbar(tab.T, cnt.T, order, n, miss,
                      "Python 最主要用途领域 Top 8（按年分组）", "受访者占比（%）",
                      "03_primary_use_case.png",
                      extra_note="仅保留跨年合计前 8 的领域，其余并入「其他（合并）」。")
    _print_summary(3, "03_primary_use_case.png", n.to_dict(), miss.to_dict())


def chart_04(df: pd.DataFrame) -> None:
    tab, n, miss = agg_single_by_year(df, "python.years", YEARS_EXP_CANON)
    order = [YEARS_EXP_CANON[c] for c in YEARS_EXP_ORDER]
    plot_stacked(tab, n, miss, "Python 使用年限分布（按年）",
                 "受访者占比（%）", "04_python_years_experience.png", order=order)
    _print_summary(4, "04_python_years_experience.png", n.to_dict(), miss.to_dict())


def _multi_chart(df: pd.DataFrame, group: str, num: int, title: str, fname: str,
                 n_top: int = 10) -> None:
    rates, counts, n, miss = agg_multi_by_year(df, group)
    options = top_options(rates, n_top)
    plot_grouped_hbar(rates, counts, options, n, miss, title, "受访者中使用率（%）",
                      fname, extra_note=MULTI_NOTE)
    _print_summary(num, fname, n.to_dict(), miss.to_dict())


def chart_05(df: pd.DataFrame) -> None:
    _multi_chart(df, "web.frameworks", 5,
                 "Web 框架使用率 Top 10（按年分组）", "05_web_frameworks.png")


def chart_06(df: pd.DataFrame) -> None:
    _multi_chart(df, "database", 6, "数据库使用率 Top 10（按年分组）", "06_databases.png")


def chart_07(df: pd.DataFrame) -> None:
    _multi_chart(df, "ide.editor", 7,
                 "IDE / 编辑器使用率 Top 10（按年分组）", "07_ide_editors.png")


def chart_08(df: pd.DataFrame) -> None:
    exp = df["years.of.coding"].replace("", np.nan).map(YEARS_EXP_CANON)
    use = df["use.python.most"].replace("", np.nan).map(USE_CASE_CANON)
    valid = exp.notna() & use.notna()
    top = list(use[valid].value_counts().head(8).index)
    use2 = use.where(use.isin(top), "其他（合并）")
    cols = top + ["其他（合并）"]
    row_order = [YEARS_EXP_CANON[c] for c in YEARS_EXP_ORDER]
    tab = pd.crosstab(exp[valid], use2[valid], normalize="index") * 100
    tab = tab.reindex(index=row_order, columns=cols, fill_value=0.0)
    cnt = pd.crosstab(exp[valid], use2[valid]).reindex(index=row_order, columns=cols,
                                                       fill_value=0)
    n_by_year = valid.groupby(df["year"]).sum().astype(int).to_dict()
    miss_by_year = ((1.0 - valid.groupby(df["year"]).mean()) * 100).to_dict()
    plot_heatmap(tab, cnt, row_order,
                 "编码年限 × Python 最主要用途（2019–2023 合并，行内占比）",
                 "最主要用途", "总编码年限", "08_coding_years_by_use_case.png",
                 n_by_year, miss_by_year,
                 extra_note="行内占比：每行合计 100%；仅保留使用频次前 8 的领域，其余并入「其他（合并）」。")
    _print_summary(8, "08_coding_years_by_use_case.png", n_by_year, miss_by_year)


CHARTS: dict[int, tuple[str, object]] = {
    1: ("01_python_main_language.png", chart_01),
    2: ("02_work_vs_personal.png", chart_02),
    3: ("03_primary_use_case.png", chart_03),
    4: ("04_python_years_experience.png", chart_04),
    5: ("05_web_frameworks.png", chart_05),
    6: ("06_databases.png", chart_06),
    7: ("07_ide_editors.png", chart_07),
    8: ("08_coding_years_by_use_case.png", chart_08),
}


def main(argv: list[str]) -> None:
    setup_matplotlib()
    CHARTS_DIR.mkdir(exist_ok=True)

    nums = sorted({int(a) for a in argv[1:] if a.isdigit()})
    unknown = [a for a in argv[1:] if not a.isdigit() or int(a) not in CHARTS]
    if unknown:
        print(f"忽略未知编号: {', '.join(unknown)}（可用编号 1–{len(CHARTS)}）")

    df = load_master()
    print(f"已读取 master 表：{len(df):,} 行 × {df.shape[1]} 列")

    for num, (fname, func) in CHARTS.items():
        if nums and num not in nums:
            continue
        func(df)

    print(f"完成。图表输出目录：{CHARTS_DIR}")


if __name__ == "__main__":
    main(sys.argv)
