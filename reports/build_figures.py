"""reports/build_figures.py — 组会汇报用清洗过程图（3 张，按 beamer 版面尺寸定制）。

只读仓库既有产物，写入 reports/figures/，不改动 charts/ 下已有 8 张图。
画布按幻灯片正文宽度（约 5.7 in）设计，导出后在 beamer 里按 1:1 插入，
避免整图缩小导致字号过小。

用法：
    python reports/build_figures.py
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 配置区：路径、年份、配色、尺寸
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"
FIG_DIR = REPORTS_DIR / "figures"

CLEANING_MD = ROOT / "cleaned" / "cleaning_report.md"
CLEANED_2024 = ROOT / "cleaned" / "cleaned_2024.csv"

YEARS = [2019, 2020, 2021, 2022, 2023, 2024]
PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3"]
INK = "#14213D"
MUTED = "#5A6472"
LIGHT = "#B9C4D4"

FIGSIZE = (5.7, 2.45)
FS_TICK = 8
FS_LABEL = 8
FS_VALUE = 7.5


def setup_matplotlib() -> None:
    """沿用 plot_survey.py 的中文字体与网格约定。"""
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.linestyle"] = "--"
    plt.rcParams["grid.alpha"] = 0.35
    plt.rcParams["axes.edgecolor"] = "#CCD3DD"
    plt.rcParams["axes.labelcolor"] = MUTED
    plt.rcParams["xtick.color"] = MUTED
    plt.rcParams["ytick.color"] = MUTED


# ---------------------------------------------------------------------------
# 解析：报告是机器生成的固定格式，解析失败必须报错而非回退默认值
# ---------------------------------------------------------------------------
def parse_cleaning_table(path: Path) -> dict[int, dict[str, int]]:
    """从 cleaning_report.md 的统计表读取分年行数、列数与多选列数。"""
    text = path.read_text(encoding="utf-8")
    stats: dict[int, dict[str, int]] = {}
    for line in text.splitlines():
        if not line.startswith("| 20"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 9:
            raise ValueError(f"清洗报告表格列数异常（期望 9 列，实际 {len(cells)}）：{line}")
        rows_before, rows_after = cells[1].split("/")
        cols_before, cols_after = cells[2].split("/")
        stats[int(cells[0])] = {
            "rows_before": int(rows_before),
            "rows_after": int(rows_after),
            "cols_before": int(cols_before),
            "cols_after": int(cols_after),
            "empty_cols": int(cells[3]),
            "empty_rows": int(cells[4]),
            "dup_rows": int(cells[5]),
            "multi": int(cells[7]),
        }
    if sorted(stats) != YEARS:
        raise ValueError(f"清洗报告年份解析失败：期望 {YEARS}，实际 {sorted(stats)}。请检查 {path}")
    return stats


def missing_rates_2024() -> tuple[pd.Series, int]:
    """分块统计 2024 年各列缺失率（空字符串占比，单位 %）。"""
    header = pd.read_csv(CLEANED_2024, encoding="utf-8-sig", nrows=0)
    cols = list(header.columns)
    empty = pd.Series(0, index=cols, dtype="int64")
    total = 0
    for chunk in pd.read_csv(CLEANED_2024, encoding="utf-8-sig", keep_default_na=False,
                             dtype=str, usecols=cols, chunksize=5000):
        total += len(chunk)
        for col in cols:
            empty[col] += int((chunk[col].str.strip() == "").sum())
    if total == 0:
        raise ValueError(f"2024 清洗数据为空：{CLEANED_2024}")
    return empty / total * 100, total


# ---------------------------------------------------------------------------
# 绘图工具
# ---------------------------------------------------------------------------
def _strip(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def _finish(fig: plt.Figure, path: Path) -> Path:
    """统一收尾：保存 + 关闭。图注写在幻灯片/文稿那头，图内不再重复。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 图 1：分年行数清洗前后
# ---------------------------------------------------------------------------
def fig_rows(stats: dict[int, dict[str, int]], path: Path) -> Path:
    years = sorted(stats)
    before = np.array([stats[y]["rows_before"] for y in years], dtype=float) / 1000
    after = np.array([stats[y]["rows_after"] for y in years], dtype=float) / 1000

    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(years))
    w = 0.36
    ax.bar(x - w / 2, before, w, color=LIGHT, label="清洗前", zorder=3)
    ax.bar(x + w / 2, after, w, color=PALETTE[0], label="清洗后", zorder=3)

    top = before.max()
    for i, y in enumerate(years):
        removed = stats[y]["rows_before"] - stats[y]["rows_after"]
        pct = removed / stats[y]["rows_before"] * 100
        ax.text(i - w / 2, before[i] + top * 0.02, f"{before[i]:.1f}", ha="center",
                va="bottom", fontsize=FS_VALUE, color=MUTED)
        ax.text(i + w / 2, after[i] + top * 0.02, f"{after[i]:.1f}", ha="center",
                va="bottom", fontsize=FS_VALUE, color=PALETTE[0], fontweight="bold")
        if removed:
            hot = y == 2020
            ax.annotate(f"−{removed:,}（{pct:.1f}%）",
                        xy=(i + w / 2, after[i]),
                        xytext=(i + w / 2 + (0.12 if hot else 0.0), after[i] + top * 0.2),
                        ha="left" if hot else "center", va="bottom",
                        fontsize=FS_VALUE + (1.2 if hot else 0),
                        color=PALETTE[3] if hot else MUTED,
                        fontweight="bold" if hot else "normal",
                        arrowprops=dict(arrowstyle="-", lw=0.7,
                                        color=PALETTE[3] if hot else "#C9D0DB",
                                        shrinkA=1, shrinkB=1))

    ax.set_xticks(x, [str(y) for y in years], fontsize=FS_TICK)
    ax.set_ylabel("受访行数（千）", fontsize=FS_LABEL)
    ax.set_ylim(0, top * 1.3)
    ax.legend(loc="upper right", frameon=False, fontsize=FS_TICK)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.set_axisbelow(True)
    _strip(ax)
    fig.subplots_adjust(left=0.115, right=0.985, top=0.97, bottom=0.135)
    return _finish(fig, path)


# ---------------------------------------------------------------------------
# 图 2：列数结构增长
# ---------------------------------------------------------------------------
def fig_structure(stats: dict[int, dict[str, int]], path: Path) -> Path:
    years = sorted(stats)
    cols = np.array([stats[y]["cols_before"] for y in years], dtype=float)
    multi = np.array([stats[y]["multi"] for y in years], dtype=float)

    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(years))
    w = 0.36
    ax.bar(x - w / 2, cols, w, color=PALETTE[0], label="总列数", zorder=3)
    ax.bar(x + w / 2, multi, w, color=PALETTE[2], label="多选二值列", zorder=3)
    for i in range(len(years)):
        ax.text(i - w / 2, cols[i] + 9, f"{int(cols[i])}", ha="center", va="bottom",
                fontsize=FS_VALUE, color=PALETTE[0], fontweight="bold")
        ax.text(i + w / 2, multi[i] + 9, f"{int(multi[i])}", ha="center", va="bottom",
                fontsize=FS_VALUE, color=PALETTE[2], fontweight="bold")

    ax.set_xticks(x, [str(y) for y in years], fontsize=FS_TICK)
    ax.set_ylabel("列数", fontsize=FS_LABEL)
    ax.set_ylim(0, cols.max() * 1.24)
    ax.legend(loc="upper left", frameon=False, fontsize=FS_TICK)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.set_axisbelow(True)
    _strip(ax)
    fig.subplots_adjust(left=0.11, right=0.985, top=0.97, bottom=0.135)
    return _finish(fig, path)


# ---------------------------------------------------------------------------
# 图 3：2024 年分列缺失率分布
# ---------------------------------------------------------------------------
def fig_missing(rates: pd.Series, n_rows: int, path: Path) -> Path:
    edges = [0, 1e-9, 10, 30, 50, 70, 90, 100.0001]
    labels = ["0%", "0–10%", "10–30%", "30–50%", "50–70%", "70–90%", "90–100%"]
    counts = [int(((rates >= edges[i]) & (rates < edges[i + 1])).sum())
              for i in range(len(labels))]
    colors = ["#DFE5EC", "#C3D1E3", LIGHT, PALETTE[0], PALETTE[4], PALETTE[1], PALETTE[3]]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(labels))
    ax.bar(x, counts, 0.6, color=colors, zorder=3)
    for i, c in enumerate(counts):
        ax.text(i, c + max(counts) * 0.025, str(c), ha="center", va="bottom",
                fontsize=FS_VALUE + 0.5, color=INK, fontweight="bold")

    over_half = int((rates >= 50).sum())
    over_60 = int((rates >= 60).sum())
    ax.text(0.60, 0.80, f"{over_half} 列超一半为空\n其中 {over_60} 列超 60%",
            transform=ax.transAxes, ha="center", va="top", fontsize=FS_LABEL,
            color=PALETTE[3], fontweight="bold", linespacing=1.5)
    ax.text(0.985, 0.42, "多选列二值化后\n未回答被记成 0", transform=ax.transAxes,
            ha="right", va="top", fontsize=FS_VALUE,
            bbox=dict(boxstyle="round,pad=0.35", fc="#F5F7FA", ec="none"), color=MUTED)

    ax.set_xticks(x, labels, fontsize=FS_TICK)
    ax.set_ylabel("列数", fontsize=FS_LABEL)
    ax.set_ylim(0, max(counts) * 1.22)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.set_axisbelow(True)
    _strip(ax)
    fig.subplots_adjust(left=0.11, right=0.985, top=0.97, bottom=0.135)
    return _finish(fig, path)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    setup_matplotlib()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    stats = parse_cleaning_table(CLEANING_MD)
    rates, n_rows = missing_rates_2024()

    made = [
        fig_rows(stats, FIG_DIR / "f1_rows_before_after.png"),
        fig_structure(stats, FIG_DIR / "f2_structure_growth.png"),
        fig_missing(rates, n_rows, FIG_DIR / "f3_missing_profile.png"),
    ]
    for p in made:
        print(f"[figures] {p.relative_to(ROOT)}  {p.stat().st_size // 1024} KB")
    print(f"[figures] 2024 行数 {n_rows:,}；列数 {len(rates)}；"
          f"有缺失的列 {(rates > 0).sum()}；缺失过半 {(rates >= 50).sum()}")


if __name__ == "__main__":
    main()
