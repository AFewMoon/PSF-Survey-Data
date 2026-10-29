"""reports/2026-11-06/build_figures.py — 组会汇报配图（3 张主图 + 1 张能力探针对比图）。

只读仓库既有报告与决策缓存，写入本目录 figures/，不改动 charts/ 与 llm/ 下产物。
画布 5.7 × 2.45 in，插入 beamer 时按 1:1 使用，避免整图缩放导致字号过小。

用法：
    python reports/2026-11-06/build_figures.py
"""
from __future__ import annotations

import ast
import json
import re
import statistics
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# 配置区：路径、配色、尺寸
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIG_DIR = HERE / "figures"

RULE_ALIGN_MD = ROOT / "aligned" / "alignment_report.md"
LLM_ALIGN_MD = ROOT / "llm" / "reports" / "alignment_report.md"
LLM_PARITY_MD = ROOT / "llm" / "reports" / "parity_report.md"
LLM_DECISIONS = ROOT / "llm" / "decisions"
PANGU_REPORTS = ROOT / "pangu" / "reports"

INK = "#14213D"
MUTED = "#5A6472"
LIGHT = "#B9C4D4"
CALM = "#4C72B0"
ACCENT = "#DD8452"
WARN = "#C44E52"
GOOD = "#55A868"

FIGSIZE = (5.7, 2.45)
FS_TICK = 8
FS_LABEL = 8
FS_VALUE = 7.5


def setup_matplotlib() -> None:
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
# 解析：机器生成报告是固定格式，解析失败必须 raise，不用默认值兜底
# ---------------------------------------------------------------------------
def _search(pattern: str, text: str, where: str) -> re.Match[str]:
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"无法从 {where} 解析：{pattern}")
    return match


def parse_rule_alignment(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    where = str(path)
    shared = _search(r"跨年共有列：(\d+)（对齐前为 (\d+)）", text, where)
    return {
        "shared": int(shared.group(1)),
        "before": int(shared.group(2)),
        "renamed": int(_search(r"重命名列：(\d+)", text, where).group(1)),
        "values": int(_search(r"取值统一记录：(\d+)", text, where).group(1)),
        "rows": int(_search(r"跨年总表行数：(\d+)", text, where).group(1)),
    }


def parse_llm_alignment(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    where = str(path)
    groups = _search(r"题目组：(\d+) 个（其中 (\d+) 个", text, where)
    pairs = _search(r"候选对判定：(\d+) 对（接受 (\d+) 对）", text, where)
    return {
        "shared": int(_search(r"跨年共有列：(\d+)", text, where).group(1)),
        "groups": int(groups.group(1)),
        "remapped": int(groups.group(2)),
        "renamed": int(_search(r"列名重命名：(\d+)", text, where).group(1)),
        "clusters": int(_search(r"选项同义簇：(\d+)", text, where).group(1)),
        "values": int(_search(r"取值统一记录：(\d+)", text, where).group(1)),
        "dups": int(_search(r"`__dup` 冲突列：(\d+)", text, where).group(1)),
        "rows": int(_search(r"总表行数：(\d+)", text, where).group(1)),
        "pairs": int(pairs.group(1)),
        "pairs_ok": int(pairs.group(2)),
        # 按人工词表统一写法是可选统计，报告里没有就记 0，不阻断绘图
        "snapped": int(m.group(1)) if (m := re.search(r"按人工词表统一写法 (\d+) 处", text)) else 0,
    }


def parse_parity(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    where = str(path)

    columns = _search(r"\| 总表列数（不含 year） \| (\d+) \| (\d+) \|", text, where)
    match = _search(r"\| 归一后匹配列（Jaccard %） \| — \| (\d+)（([\d.]+)%） \|", text, where)

    years: list[int] = []
    diffs: list[int] = []
    for line in text.splitlines():
        if not re.match(r"\| 20\d\d \|", line):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3:
            raise ValueError(f"{where} 行数表列数异常：{line}")
        rule, llm = int(cells[1]), int(cells[2])
        years.append(int(cells[0]))
        diffs.append(rule - llm)

    topic_diffs: list[tuple[str, float]] = []
    for line in text.splitlines():
        if not line.startswith("| preferred_language |") and not line.startswith("| programming_languages |") \
                and not line.startswith("| editor_preferences |"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        topic_diffs.append((f"{cells[1]} / {cells[2]}", abs(float(cells[5]))))
    if not topic_diffs:
        raise ValueError(f"{where} 未找到同主题占比表")

    json_match = _search(r"'缺失率差异_Top': (\[[^\]]*\])", text, where)
    missing_diffs = ast.literal_eval(json_match.group(1))
    if missing_diffs:
        raise ValueError(f"{where} 出现非空缺失率差异，需要人工复核：{missing_diffs}")

    return {
        "rule_cols": int(columns.group(1)),
        "llm_cols": int(columns.group(2)),
        "matched": int(match.group(1)),
        "jaccard": float(match.group(2)),
        "years": years,
        "row_diffs": diffs,
        "topic_rows": len(topic_diffs),
        "topic_max": max(v for _, v in topic_diffs),
        "topic_nonzero": sum(1 for _, v in topic_diffs if v > 0),
        "missing_over_1pp": 0,
    }


def count_decisions(path: Path) -> dict[str, int]:
    if not path.is_dir():
        raise ValueError(f"决策目录不存在：{path}")
    counts = {sub.name: len(list(sub.glob("*.json"))) for sub in sorted(path.iterdir()) if sub.is_dir()}
    counts["total"] = sum(counts.values())
    return counts


# ---------------------------------------------------------------------------
# 绘图工具
# ---------------------------------------------------------------------------
def _strip(ax: plt.Axes) -> None:
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)


def _finish(fig: plt.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# 图 1：列覆盖——人工 153、LLM 110、原交集 42、实交集 105
# ---------------------------------------------------------------------------
def fig_coverage(rule: dict[str, int], llm: dict[str, int], parity: dict[str, object],
                 path: Path) -> Path:
    labels = ["对齐前\n共有列", "人工对齐\n（规则）", "LLM 对齐", "其中同名\n匹配"]
    values = [rule["before"], rule["shared"], llm["shared"], int(parity["matched"])]
    colors = [LIGHT, CALM, ACCENT, GOOD]

    fig, ax = plt.subplots(figsize=FIGSIZE)
    x = np.arange(len(values))
    bars = ax.bar(x, values, 0.56, color=colors, zorder=3)
    for bar, value in zip(bars, values):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 4, f"{value}",
                ha="center", va="bottom", fontsize=FS_VALUE + 1.5,
                color=INK, fontweight="bold")

    ax.set_xticks(x, labels, fontsize=FS_TICK)
    ax.set_ylabel("列数", fontsize=FS_LABEL)
    ax.set_ylim(0, max(values) * 1.24)
    ax.tick_params(axis="y", labelsize=FS_TICK)
    ax.set_axisbelow(True)
    _strip(ax)
    ax.text(0.99, 0.93, "覆盖范围 ≠ 重叠质量", transform=ax.transAxes,
            ha="right", va="top", fontsize=FS_VALUE, color=MUTED)
    fig.subplots_adjust(left=0.10, right=0.985, top=0.96, bottom=0.20)
    return _finish(fig, path)


# ---------------------------------------------------------------------------
# 图 2：映射规模——列名映射与取值统一，两个面板避免数量级压扁
# ---------------------------------------------------------------------------
def fig_mapping_scale(rule: dict[str, int], llm: dict[str, int], path: Path) -> Path:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=FIGSIZE, gridspec_kw={"width_ratios": [1, 1.25]})

    names = ["人工", "LLM"]
    rename = [rule["renamed"], llm["renamed"]]
    bars = ax1.bar(names, rename, 0.5, color=[CALM, ACCENT], zorder=3)
    for bar, value in zip(bars, rename):
        ax1.text(bar.get_x() + bar.get_width() / 2, value + 8, f"{value}",
                 ha="center", va="bottom", fontsize=FS_VALUE + 1, color=INK, fontweight="bold")
    ax1.set_title("列名重命名（条）", fontsize=FS_LABEL, color=INK, pad=6)
    ax1.set_ylim(0, max(rename) * 1.25)
    ax1.tick_params(labelsize=FS_TICK)
    ax1.set_axisbelow(True)
    _strip(ax1)

    values = [rule["values"], llm["values"]]
    bars = ax2.bar(names, values, 0.5, color=[CALM, ACCENT], zorder=3)
    ax2.set_yscale("log")
    ax2.set_ylim(1, max(values) * 2.2)
    for bar, value in zip(bars, values):
        text = f"{value:,}" if value else "0"
        ax2.text(bar.get_x() + bar.get_width() / 2, max(value, 1) * 1.12, text,
                 ha="center", va="bottom", fontsize=FS_VALUE + 1,
                 color=INK if value else WARN, fontweight="bold")
    ax2.set_title("取值范围统一（条，对数轴）", fontsize=FS_LABEL, color=INK, pad=6)
    ax2.tick_params(labelsize=FS_TICK)
    ax2.set_axisbelow(True)
    _strip(ax2)

    fig.subplots_adjust(left=0.10, right=0.985, top=0.86, bottom=0.15, wspace=0.28)
    return _finish(fig, path)


# ---------------------------------------------------------------------------
# 图 3：对账结构——并集 158 列如何拆成 105 / 48 / 5
# ---------------------------------------------------------------------------
def fig_parity(parity: dict[str, object], path: Path) -> Path:
    matched = int(parity["matched"])
    rule_only = int(parity["rule_cols"]) - matched
    llm_only = int(parity["llm_cols"]) - matched
    total = matched + rule_only + llm_only

    fig, ax = plt.subplots(figsize=FIGSIZE)
    segments = [
        (matched, CALM, "两边都有"),
        (rule_only, LIGHT, "仅规则"),
        (llm_only, ACCENT, "仅 LLM"),
    ]
    left = 0
    for value, color, label in segments:
        ax.barh(0, value, left=left, height=0.44, color=color, zorder=3)
        text_color = "white" if value > 20 else INK
        ax.text(left + value / 2, 0, f"{value}", ha="center", va="center",
                fontsize=FS_VALUE + 2, color=text_color, fontweight="bold")
        ax.text(left + value / 2, 0.30, label, ha="center", va="bottom",
                fontsize=FS_VALUE, color=MUTED)
        left += value

    ax.set_xlim(0, total)
    ax.set_ylim(-0.45, 0.85)
    ax.set_yticks([])
    ax.set_xlabel(f"归一后列并集：{total} 列", fontsize=FS_LABEL)
    ax.tick_params(axis="x", labelsize=FS_TICK)
    ax.set_axisbelow(True)
    _strip(ax)

    ax.text(0.0, 0.02,
            f"Jaccard {parity['jaccard']}%    "
            f"匹配列非空率差 ≥1pp：{parity['missing_over_1pp']} 条    "
            f"同主题最大差 {parity['topic_max']}pp",
            transform=ax.transAxes, ha="left", va="bottom", fontsize=FS_VALUE, color=INK)

    fig.subplots_adjust(left=0.035, right=0.985, top=0.97, bottom=0.24)
    return _finish(fig, path)


def load_capability(filename: str) -> dict[str, object] | None:
    """读取能力探针整份结果（summary + runs）；文件缺失时返回 None，由图函数跳过该图。"""
    path = PANGU_REPORTS / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def fig_capability(qwen: dict[str, object], pangu: dict[str, object], path: Path) -> Path:
    """同一条管线、同一组 8 对样本：4B 与盘古 7B 质量接近，耗时差近三倍。

    耗时取各轮中位数：首轮含模型加载（4B 首次 9.6s，稳态 4.7s），用均值会把加载
    算进推理成本。画布刻意做成扁条（5.6 × 1.55 in）并放大字号，插入幻灯片后
    仍有 10pt 上下，图上的数字就是这页的主证据。
    """
    labels = ["4B", "7B"]
    accuracy = [float(qwen["summary"]["mean_accuracy"]) * 100,
                float(pangu["summary"]["mean_accuracy"]) * 100]
    duration = [statistics.median(r["duration_s"] for r in model["runs"]) for model in (qwen, pangu)]
    colors = [CALM, ACCENT]

    fig, axes = plt.subplots(1, 2, figsize=(5.6, 1.55))

    ax = axes[0]
    ax.bar(labels, accuracy, color=colors, width=0.46, zorder=3)
    for idx, value in enumerate(accuracy):
        ax.text(idx, value + 3, f"{value:.0f}%", ha="center", va="bottom",
                fontsize=13, fontweight="bold", color=INK)
    ax.set_ylim(0, 128)
    ax.set_title("8 对判定准确率（%）", fontsize=11, color=INK, pad=3)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=12)
    ax.grid(False)
    _strip(ax)

    ax = axes[1]
    ax.bar(labels, duration, color=colors, width=0.46, zorder=3)
    for idx, value in enumerate(duration):
        ax.text(idx, value + max(duration) * 0.04, f"{value:.1f}s", ha="center", va="bottom",
                fontsize=13, fontweight="bold", color=INK)
    ax.set_ylim(0, max(duration) * 1.32)
    ax.set_title("耗时（秒，中位数）", fontsize=11, color=INK, pad=3)
    ax.set_yticks([])
    ax.tick_params(axis="x", labelsize=12)
    ax.grid(False)
    _strip(ax)

    fig.subplots_adjust(left=0.035, right=0.985, top=0.84, bottom=0.11, wspace=0.10)
    return _finish(fig, path)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def main() -> None:
    setup_matplotlib()
    FIG_DIR.mkdir(parents=True, exist_ok=True)

    rule = parse_rule_alignment(RULE_ALIGN_MD)
    llm = parse_llm_alignment(LLM_ALIGN_MD)
    parity = parse_parity(LLM_PARITY_MD)
    decisions = count_decisions(LLM_DECISIONS)

    if rule["shared"] - int(parity["matched"]) <= 0:
        raise ValueError("匹配列数大于规则管线列数，parity 解析有误")
    if int(parity["rule_cols"]) != rule["shared"] or int(parity["llm_cols"]) != llm["shared"]:
        raise ValueError("parity 报告列数与对齐报告不一致，先核对报告")
    if int(parity["matched"]) != 105 or llm["shared"] != 110:
        raise ValueError("预期 105/110 的匹配关系发生变化，需同步讲述稿与幻灯片")

    made = [
        fig_coverage(rule, llm, parity, FIG_DIR / "f1_coverage.png"),
        fig_mapping_scale(rule, llm, FIG_DIR / "f2_mapping_scale.png"),
        fig_parity(parity, FIG_DIR / "f3_parity.png"),
    ]

    cap_qwen = load_capability("capability_qwen.json")
    cap_pangu = load_capability("capability_7b.json")
    if cap_qwen and cap_pangu:
        made.append(fig_capability(cap_qwen, cap_pangu, FIG_DIR / "f4_capability.png"))
        for name, data in (("4B", cap_qwen), ("7B", cap_pangu)):
            print("[kpi] 能力探针 %s  准确率 %.0f%%；JSON 合法 %.0f%%；中位耗时 %.1fs；轮数 %d"
                  % (name, float(data["summary"]["mean_accuracy"]) * 100,
                     float(data["summary"]["json_ok_rate"]) * 100,
                     statistics.median(r["duration_s"] for r in data["runs"]),
                     int(data["summary"]["rounds"])))

    print("[kpi] 规则管线  列 %d → %d；重命名 %d；取值统一 %d；行 %d"
          % (rule["before"], rule["shared"], rule["renamed"], rule["values"], rule["rows"]))
    print("[kpi] LLM 管线  列 %d；重命名 %d；取值统一 %d；__dup %d；行 %d"
          % (llm["shared"], llm["renamed"], llm["values"], llm["dups"], llm["rows"]))
    print("[kpi] LLM 决策  组 %d（改路径 %d）；同义簇 %d" % (llm["groups"], llm["remapped"], llm["clusters"]))
    print("[kpi] 逐对判定  候选对 %d（接受 %d）；按词表统一写法 %d 处"
          % (llm["pairs"], llm["pairs_ok"], llm["snapped"]))
    print("[kpi] parity   匹配 %d / Jaccard %.1f%%；仅规则 %d；仅 LLM %d；并集 %d"
          % (parity["matched"], parity["jaccard"], parity["rule_cols"] - parity["matched"],
             parity["llm_cols"] - parity["matched"],
             parity["rule_cols"] + parity["llm_cols"] - parity["matched"]))
    print("[kpi] 非空率差 ≥1pp  %d 条；同主题 %d 条中 %d 条有差，最大 %.1fpp"
          % (parity["missing_over_1pp"], parity["topic_rows"], parity["topic_nonzero"],
             parity["topic_max"]))
    print("[kpi] 行数差  " + "；".join(
        f"{year}:{diff}" for year, diff in zip(parity["years"], parity["row_diffs"]) if diff))
    print("[kpi] 决策缓存  " + " / ".join(f"{k} {v}" for k, v in decisions.items()))

    for path in made:
        print(f"[figures] {path.relative_to(ROOT)}  {path.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
