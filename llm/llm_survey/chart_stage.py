"""图表阶段：模型给规格，matplotlib 渲染（中文字体配置与 plot_survey.py 一致）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from . import config, decision_schema, prompts, reporting
from .cache import CacheStore
from .dataio import read_json
from .ollama_client import ChatMeta, OllamaClient


@dataclass
class ChartResult:
    specs: list[dict[str, Any]] = field(default_factory=list)
    rendered: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    cache_line: str = ""
    note: str = ""


def setup_matplotlib() -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "Arial Unicode MS"]
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["figure.facecolor"] = "white"
    plt.rcParams["axes.grid"] = True
    plt.rcParams["grid.linestyle"] = "--"
    plt.rcParams["grid.alpha"] = 0.35


def _catalog() -> list[dict[str, Any]]:
    """可用统计表清单（紧凑摘要，供模型选择数据源）。"""
    items: list[dict[str, Any]] = []
    for path in sorted(config.STATS_DIR.glob("*.csv")):
        try:
            df = pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig", nrows=2000)
        except (pd.errors.ParserError, OSError):
            continue
        if df.empty:
            continue
        entry: dict[str, Any] = {
            "file": path.name,
            "rows": int(len(df)),
            "columns": list(df.columns)[:8],
        }
        if "option" in df.columns:
            entry["top"] = df["option"].astype(str).drop_duplicates().head(6).tolist()
        elif "value" in df.columns:
            entry["top"] = df["value"].astype(str).drop_duplicates().head(6).tolist()
        item_kind = "trends" if path.name.startswith("trends") else (
            "profile" if path.name.startswith("profile") else "singles")
        entry["kind_hint"] = item_kind
        items.append(entry)
        if len(items) >= 24:
            break
    return items


def run(client: OllamaClient | None, refresh: bool) -> ChartResult:
    result = ChartResult()
    catalog = _catalog()
    if not catalog:
        result.problems.append("没有可用的统计表，跳过图表")
        return result
    available = [c["file"] for c in catalog]

    if client is None:
        specs = _fallback_specs(catalog)
        result.cache_line = "chart_spec: 离线默认规格"
    else:
        cache = CacheStore("chart_spec", client.digest, refresh=refresh)
        system, user = prompts.chart_messages(catalog)
        key = cache.key({"files": available}, config.PROMPT_VERSION["chart_spec"])

        def call() -> tuple[dict[str, Any], ChatMeta]:
            return client.chat_json(system, user, num_predict=1800, tag="chart-spec")

        response, record, _ = cache.get_or_call(
            key, config.PROMPT_VERSION["chart_spec"], {"files": len(available)}, call,
            fallback=lambda: {"charts": _fallback_specs(catalog)},
        )
        specs, problems = decision_schema.validate_chart_specs(response, available)
        result.problems += problems
        if not specs:
            specs = _fallback_specs(catalog)
            result.problems.append("模型未给出合法图表规格，已使用默认规格")
        result.cache_line = cache.report()
        result.note = str(response.get("reason", ""))[:200]
    result.specs = specs

    setup_matplotlib()
    config.CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        try:
            path = _render(spec)
        except (ValueError, KeyError, OSError, ZeroDivisionError) as exc:
            result.problems.append(f"图表 {spec['name']} 渲染失败：{exc}")
            continue
        result.rendered.append(path.name)
    write_report(result, available)
    return result


def _fallback_specs(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    trends = [c for c in catalog if c["kind_hint"] == "trends"][:6]
    profiles = [c for c in catalog if c["kind_hint"] == "profile"][:4]
    for item in trends:
        specs.append({
            "name": item["file"].replace("trends_llm_", "trend_").replace(".csv", ""),
            "kind": "line", "source": item["file"],
            "title": item["file"].replace("trends_llm_", "").replace(".csv", "") + " 跨年趋势",
            "top_n": 8, "reason": "fallback：按文件自动生成趋势图",
        })
    for item in profiles:
        specs.append({
            "name": item["file"].replace("profile_llm_", "profile_").replace(".csv", ""),
            "kind": "hbar", "source": item["file"],
            "title": item["file"].replace("profile_llm_", "").replace(".csv", "") + " 使用率",
            "top_n": 10, "reason": "fallback：按文件自动生成占比图",
        })
    return specs[:12]


def _load(name: str) -> pd.DataFrame:
    return pd.read_csv(config.STATS_DIR / name, keep_default_na=False, encoding="utf-8-sig")


def _footnote(fig: plt.Figure, spec: dict[str, Any], extra: str = "") -> None:
    parts = [f"数据源：llm/stats/{spec['source']}", f"模型：{config.MODEL}",
             "样本：PSF 年度 Python 开发者调查（自报抽样）"]
    if extra:
        parts.append(extra)
    fig.text(0.01, 0.012, "  ".join(parts), fontsize=7.5, color="#555555",
             va="bottom", ha="left")


def _render(spec: dict[str, Any]) -> Any:
    df = _load(spec["source"])
    kind = spec["kind"]
    if kind in {"bar", "hbar"}:
        return _render_profile(spec, df)
    if kind == "line":
        return _render_line(spec, df)
    if kind == "grouped_bar":
        return _render_grouped(spec, df)
    if kind == "heatmap":
        return _render_heatmap(spec, df)
    raise ValueError(f"未知图表类型：{kind}")


def _render_profile(spec: dict[str, Any], df: pd.DataFrame) -> Any:
    if "pct" not in df.columns or "option" not in df.columns:
        raise ValueError("数据表缺少 option/pct 列")
    data = df.sort_values("pct", ascending=False).head(spec["top_n"]).iloc[::-1]
    labels = [
        f"{row['group']}｜{row['option']}" if df["group"].nunique() > 1 else str(row["option"])
        for _, row in data.iterrows()
    ]
    values = data["pct"].astype(float).tolist()
    fig, ax = plt.subplots(figsize=(10, max(4.2, 0.36 * len(values) + 1.6)))
    if spec["kind"] == "bar":
        ax.bar(range(len(values)), values, color="#3b7dd8")
        ax.set_xticks(range(len(values)))
        ax.set_xticklabels(labels, rotation=35, ha="right", fontsize=8.5)
    else:
        ax.barh(range(len(values)), values, color="#3b7dd8")
        ax.set_yticks(range(len(values)))
        ax.set_yticklabels(labels, fontsize=8.5)
        for i, v in enumerate(values):
            ax.text(v + max(values) * 0.01, i, f"{v:.1f}%", va="center", fontsize=8)
        ax.set_xlim(0, max(values) * 1.18 if values else 1)
    ax.set_xlabel("占比（%）" if spec["kind"] == "bar" else "占比（%）", fontsize=10)
    ax.set_title(spec["title"], fontsize=13, fontweight="bold", pad=12)
    denominator = df["denominator"].iloc[0] if "denominator" in df.columns else ""
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    _footnote(fig, spec, f"分母 n={denominator}")
    path = config.CHARTS_DIR / f"{spec['name']}.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _trend_matrix(df: pd.DataFrame, spec: dict[str, Any]) -> tuple[pd.DataFrame, list[str]]:
    if "year" not in df.columns:
        raise ValueError("趋势表缺少 year 列")
    pivot = df.pivot_table(index="option", columns="year", values="pct", aggfunc="max")
    order = pivot.fillna(0).mean(axis=1).sort_values(ascending=False).head(spec["top_n"]).index
    return pivot.loc[order], [str(y) for y in pivot.columns]


def _render_line(spec: dict[str, Any], df: pd.DataFrame) -> Any:
    matrix, years = _trend_matrix(df, spec)
    fig, ax = plt.subplots(figsize=(10.5, 6))
    for option in matrix.index:
        ax.plot(years, matrix.loc[option].astype(float).tolist(), marker="o", linewidth=1.8,
                label=str(option))
    ax.set_xlabel("年份", fontsize=10)
    ax.set_ylabel("占比（%）", fontsize=10)
    ax.set_title(spec["title"], fontsize=13, fontweight="bold", pad=12)
    ax.legend(loc="center left", bbox_to_anchor=(1.01, 0.5), frameon=False, fontsize=8.5)
    fig.subplots_adjust(left=0.08, right=0.74, top=0.9, bottom=0.13)
    _footnote(fig, spec, f"分母：{df['denominator'].iloc[0] if 'denominator' in df else '—'}")
    path = config.CHARTS_DIR / f"{spec['name']}.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _render_grouped(spec: dict[str, Any], df: pd.DataFrame) -> Any:
    matrix, years = _trend_matrix(df, spec)
    options = list(matrix.index)[:8]
    x = np.arange(len(options))
    width = 0.8 / max(1, len(years))
    fig, ax = plt.subplots(figsize=(11, 5.6))
    for i, year in enumerate(years):
        values = [float(matrix.loc[o, int(year)]) if int(year) in matrix.columns
                  and not pd.isna(matrix.loc[o, int(year)]) else 0.0 for o in options]
        ax.bar(x + i * width, values, width, label=year)
    ax.set_xticks(x + width * (len(years) - 1) / 2)
    ax.set_xticklabels(options, rotation=25, ha="right", fontsize=8.5)
    ax.set_ylabel("占比（%）", fontsize=10)
    ax.set_title(spec["title"], fontsize=13, fontweight="bold", pad=12)
    ax.legend(title="年份", frameon=False, fontsize=9)
    fig.subplots_adjust(left=0.07, right=0.97, top=0.9, bottom=0.24)
    _footnote(fig, spec)
    path = config.CHARTS_DIR / f"{spec['name']}.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def _render_heatmap(spec: dict[str, Any], df: pd.DataFrame) -> Any:
    matrix, years = _trend_matrix(df, spec)
    fig, ax = plt.subplots(figsize=(10, max(4, 0.42 * len(matrix) + 1.8)))
    data = matrix.fillna(0).to_numpy(dtype=float)
    im = ax.imshow(data, cmap="YlGnBu", aspect="auto")
    ax.set_xticks(range(len(years)))
    ax.set_xticklabels(years, rotation=25, ha="right", fontsize=9)
    ax.set_yticks(range(len(matrix)))
    ax.set_yticklabels([str(i) for i in matrix.index], fontsize=9)
    for r in range(data.shape[0]):
        for c in range(data.shape[1]):
            value = data[r, c]
            ax.text(c, r, f"{value:.1f}", ha="center", va="center", fontsize=8,
                    color="white" if value > data.max() * 0.6 else "#222222")
    ax.grid(False)
    fig.colorbar(im, ax=ax, shrink=0.85, label="占比（%）")
    ax.set_title(spec["title"], fontsize=13, fontweight="bold", pad=12)
    fig.subplots_adjust(left=0.3, right=0.95, top=0.9, bottom=0.16)
    _footnote(fig, spec)
    path = config.CHARTS_DIR / f"{spec['name']}.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def write_report(result: ChartResult, available: list[str]) -> None:
    lines = ["# LLM 驱动图表报告", "", f"生成时间：{reporting.now_str()}", "",
             f"模型：`{config.MODEL}`｜可用统计表 {len(available)} 个｜生成图表 {len(result.rendered)} 张"]
    if result.note:
        lines += ["", f"**模型说明**：{result.note}"]
    if result.specs:
        lines += ["", reporting.md_table(
            ["图表", "类型", "数据源", "标题", "Top-N", "理由"],
            [[s["name"], s["kind"], s["source"], s["title"], s["top_n"], s["reason"]]
             for s in result.specs],
        )]
    if result.problems:
        lines += ["", "## 校验提示", "", reporting.md_list(result.problems[:20])]
    lines += ["", f"缓存：{result.cache_line}", "",
              "图表文件：`llm/charts/*.png`", ""]
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.REPORTS_DIR / "charts_report.md").write_text("\n".join(lines), encoding="utf-8")
