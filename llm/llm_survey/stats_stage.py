"""统计阶段：模型定口径 → Python 计算 → 模型分节解读。

口径与规则管线一致：
- 多选题：分子为该选项列"被选中"的行数，分母为当年总样本（denominator=total）或该题有作答的行数（answered）
- 单选题：分母为有作答的行数
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import config, decision_schema, prompts, reporting
from .cache import CacheStore
from .dataio import read_json, write_csv
from .ollama_client import ChatMeta, OllamaClient
from .textnorm import slugify


@dataclass
class StatsResult:
    topics: list[dict[str, Any]] = field(default_factory=list)
    singles: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    narratives: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    cache_lines: list[str] = field(default_factory=list)
    plan_reason: str = ""
    fallback: bool = False


def _columns_meta() -> dict[int, dict[str, dict[str, Any]]]:
    path = config.ALIGNED_DIR / "columns_llm.json"
    if not path.exists():
        return {}
    payload = read_json(path)
    return {int(y): {c: v for c, v in cols.items()} for y, cols in payload.items()}


def _master() -> pd.DataFrame:
    path = config.ALIGNED_DIR / f"survey_{config.YEARS[0]}_{config.YEARS[-1]}_master_llm.csv"
    return pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig")


def _inventory(master: pd.DataFrame,
               meta: dict[int, dict[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """列清单摘要：组 -> 涉及年份、选项数、样例。"""
    inv: dict[str, dict[str, Any]] = {}
    latest = int(master["year"].max())
    latest_meta = meta.get(latest, {})
    for col in master.columns:
        if col == "year":
            continue
        row = latest_meta.get(col) or {}
        group = row.get("group") or (col.rsplit(".", 1)[0] if "." in col else col)
        entry = inv.setdefault(group, {"years": set(), "options": set()})
        entry["options"].add(row.get("option") or
                             (col.rsplit(".", 1)[-1] if "." in col else col))
    out: dict[str, dict[str, Any]] = {}
    for group, entry in inv.items():
        out[group] = {
            "group": group,
            "n_options": len(entry["options"]),
            "sample": sorted(entry["options"])[:3],
        }
    # 只送最大的 60 个组，避免超上下文
    ordered = sorted(out.items(), key=lambda kv: kv[1]["n_options"], reverse=True)[:60]
    return dict(ordered)


def _single_candidates(meta: dict[int, dict[str, dict[str, Any]]],
                       master: pd.DataFrame) -> list[str]:
    latest = int(master["year"].max())
    out = [
        col for col, row in meta.get(latest, {}).items()
        if row.get("kind") == "single_choice" and col in master.columns
    ]
    return sorted(out)[:25]


def _selected(series: pd.Series) -> pd.Series:
    """被选中掩码：二值展开列为 ==1，文本列非空即选中。"""
    if series.dtype.kind in "iu":
        return series == 1
    return series.astype("string").str.strip().ne("") & series.notna()


def group_stats(df: pd.DataFrame, group: str, cols: list[str],
                denominator: str, single_choice: bool = False) -> pd.DataFrame:
    """一个题目组在某年的选项占比（%）。

    - 多选题：每个选项列一「选中即计入」，分母按 denominator 取总样本或作答人数
    - 单选题：列为整题，按取值分布统计（分母同上）
    """
    total = len(df)
    if not cols:
        return pd.DataFrame(columns=["group", "option", "n", "pct", "denominator"])
    if single_choice and len(cols) == 1:
        values = df[cols[0]].astype("string").str.strip()
        values = values[values.ne("") & values.notna()]
        base = total if denominator == "total" else max(len(values), 1)
        base = max(base, 1)
        rows = [
            {"group": group, "option": str(value), "n": int(count),
             "pct": round(int(count) / base * 100, 2), "denominator": base}
            for value, count in values.value_counts().items()
        ]
        return pd.DataFrame(rows)
    answered = 0
    if denominator == "answered":
        answered = int(
            pd.concat([_selected(df[c]) for c in cols], axis=1).any(axis=1).sum()
        )
    base = answered if denominator == "answered" else total
    base = max(base, 1)
    rows = []
    for col in cols:
        mask = _selected(df[col])
        n = int(mask.sum())
        option = col[len(group) + 1:] if col.startswith(group + ".") else col
        rows.append({"group": group, "option": option, "n": n,
                     "pct": round(n / base * 100, 2), "denominator": base})
    return pd.DataFrame(rows)


def _topic_tables(master: pd.DataFrame, topic: dict[str, Any],
                  meta: dict[int, dict[str, dict[str, Any]]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回 (最新年画像表, 跨年趋势长表)。"""
    latest = int(master["year"].max())
    profile_rows: list[pd.DataFrame] = []
    trend_rows: list[pd.DataFrame] = []
    for prefix in topic["prefixes"]:
        cols = [
            col for col in master.columns
            if col != "year"
            and (meta.get(latest, {}).get(col, {}).get("group") == prefix
                 or col.startswith(prefix + "."))
        ]
        if not cols:
            continue
        single = (len(cols) == 1
                  and meta.get(latest, {}).get(cols[0], {}).get("kind") == "single_choice")
        for year in sorted(master["year"].unique()):
            year_df = master[master["year"] == year]
            frame = group_stats(year_df, prefix, cols, topic["denominator"], single)
            frame["year"] = int(year)
            trend_rows.append(frame)
            if int(year) == latest:
                profile_rows.append(frame)
    profile = pd.concat(profile_rows, ignore_index=True) if profile_rows else pd.DataFrame()
    trends = pd.concat(trend_rows, ignore_index=True) if trend_rows else pd.DataFrame()
    if not profile.empty:
        profile = profile.sort_values(["group", "pct"], ascending=[True, False])
        profile = profile.groupby("group", group_keys=False).head(topic["top_n"])
    return profile, trends


def _pivot_markdown(trends: pd.DataFrame, top_options: list[str], groups: list[str]) -> str:
    if trends.empty:
        return ""
    years = sorted(trends["year"].unique())
    rows: list[list[str]] = []
    for group in groups:
        sub = trends[trends["group"] == group]
        if sub.empty:
            continue
        values = {y: sub[sub["year"] == y].set_index("option")["pct"] for y in years}
        ranked = [o for o in top_options if any(o in v.index for v in values.values())][:8]
        for option in ranked:
            rows.append(
                [group, option] + [
                    f"{values[y][option]:.1f}" if option in values[y].index else "-"
                    for y in years
                ]
            )
    if not rows:
        return ""
    return reporting.md_table(["题目组", "选项"] + [str(y) for y in years], rows)


def run(years: list[int], client: OllamaClient | None, refresh: bool,
        dry_run: bool = False) -> StatsResult:
    result = StatsResult()
    master = _master()
    meta = _columns_meta()
    inventory = _inventory(master, meta)
    singles = _single_candidates(meta, master)

    if dry_run or client is None:
        plan = _fallback_plan(inventory, singles)
        result.cache_lines.append("stats_plan: 离线默认计划")
        result.fallback = True
    else:
        cache = CacheStore("stats_plan", client.digest, refresh=refresh)
        system, user = prompts.stats_plan_messages(
            list(inventory.values()), singles, sorted(master["year"].unique().tolist()))
        key = cache.key({"groups": sorted(inventory), "singles": singles},
                        config.PROMPT_VERSION["stats_plan"])

        def call() -> tuple[dict[str, Any], ChatMeta]:
            return client.chat_json(system, user, num_predict=2200, tag="stats-plan")

        response, record, _ = cache.get_or_call(
            key, config.PROMPT_VERSION["stats_plan"],
            {"groups": len(inventory), "singles": len(singles)}, call,
            fallback=lambda: _fallback_plan(inventory, singles),
        )
        plan, problems = decision_schema.validate_stats_plan(response, list(master.columns))
        result.problems += problems
        result.fallback = bool(record.get("fallback"))
        result.plan_reason = str(response.get("reason", ""))[:200]
        result.cache_lines.append(cache.report())

    result.topics = plan["topics"]
    result.singles = plan["singles"]

    config.STATS_DIR.mkdir(parents=True, exist_ok=True)
    for topic in result.topics:
        profile, trends = _topic_tables(master, topic, meta)
        if profile.empty:
            result.problems.append(f"主题 {topic['name']} 未匹配到任何列，已跳过")
            continue
        latest = int(master["year"].max())
        profile = profile.assign(topic=topic["name"], year=latest)
        trends = trends.assign(topic=topic["name"])
        profile_path = config.STATS_DIR / f"profile_llm_{topic['name']}.csv"
        trend_path = config.STATS_DIR / f"trends_llm_{topic['name']}.csv"
        write_csv(profile[["topic", "group", "option", "n", "pct", "denominator", "year"]],
                  profile_path)
        write_csv(trends[["topic", "group", "option", "n", "pct", "denominator", "year"]],
                  trend_path)
        result.files += [profile_path.name, trend_path.name]
        result.narratives[topic["name"]] = _narrate(
            topic, profile, trends, client, refresh, result)

    _single_tables(master, result, meta)
    write_report(result, master)
    return result


def _fallback_plan(inventory: dict[str, dict[str, Any]],
                   singles: list[str]) -> dict[str, Any]:
    """离线/失败回退：按选项数挑前 10 个组。"""
    groups = sorted(inventory.values(), key=lambda g: g["n_options"], reverse=True)[:10]
    return {
        "topics": [
            {"name": slugify(g["group"]) or f"topic_{i}", "prefixes": [g["group"]],
             "top_n": 10, "denominator": "total",
             "reason": "fallback：按选项数自动挑选"}
            for i, g in enumerate(groups)
        ],
        "singles": singles[:5],
        "reason": "fallback：模型不可用，按列规模自动生成计划",
    }


def _narrate(topic: dict[str, Any], profile: pd.DataFrame, trends: pd.DataFrame,
             client: OllamaClient | None, refresh: bool, result: StatsResult) -> str:
    if client is None:
        return "（离线模式未生成解读）"
    top_options = profile.sort_values("pct", ascending=False)["option"].head(10).tolist()
    groups = sorted(profile["group"].unique())
    table = _pivot_markdown(trends, top_options, groups)
    if not table:
        return "（无可用统计表）"
    cache = CacheStore("stats_narrative", client.digest, refresh=refresh)
    system, user = prompts.narrative_messages(topic["name"], table)
    key = cache.key({"topic": topic["name"], "table": table[:1500]},
                    config.PROMPT_VERSION["stats_narrative"])

    def call() -> tuple[dict[str, Any], ChatMeta]:
        return client.chat_json(system, user, num_predict=600, tag=f"narrative-{topic['name']}")

    response, record, _ = cache.get_or_call(
        key, config.PROMPT_VERSION["stats_narrative"],
        {"topic": topic["name"]}, call,
        fallback=lambda: {"text": "（模型不可用，本节仅保留统计表）"},
    )
    try:
        text = decision_schema.validate_narrative(response, min_chars=20)
    except decision_schema.DecisionError as exc:
        result.problems.append(f"{topic['name']} 解读不可用：{exc}")
        text = "（模型返回的解读为空，本节仅保留统计表）"
    if record.get("fallback"):
        result.problems.append(f"{topic['name']} 解读降级为占位文本")
    result.cache_lines.append(cache.report())
    return text


def _single_tables(master: pd.DataFrame, result: StatsResult,
                   meta: dict[int, dict[str, dict[str, Any]]]) -> None:
    rows = []
    for col in result.singles:
        if col not in master.columns:
            continue
        for year in sorted(master["year"].unique()):
            series = master.loc[master["year"] == year, col]
            if series.dtype.kind in "iuf":
                continue
            counts = series.astype("string").str.strip().replace("", pd.NA).dropna().value_counts()
            if counts.empty:
                continue
            base = int(counts.sum())
            for value, n in counts.head(20).items():
                rows.append({"column": col, "year": int(year), "value": str(value),
                             "n": int(n), "pct": round(int(n) / base * 100, 2)})
    if rows:
        write_csv(pd.DataFrame(rows), config.STATS_DIR / "singles_llm.csv")
        result.files.append("singles_llm.csv")


def write_report(result: StatsResult, master: pd.DataFrame) -> None:
    lines = ["# LLM 驱动统计分析报告", "", f"生成时间：{reporting.now_str()}", ""]
    lines.append(
        f"模型：`{config.MODEL}`｜口径：多选题按当年总样本（或作答人数）为分母，单选题按作答人数为分母；"
        f"数据范围 {int(master['year'].min())}–{int(master['year'].max())}，"
        f"总表 {len(master):,} 行。"
    )
    if result.plan_reason:
        lines += ["", f"**分析计划思路（模型）**：{result.plan_reason}"]
    if result.fallback:
        lines += ["", "> 注意：本次统计计划来自降级默认值（模型不可用或被截断）。"]
    lines += ["", "## 主题清单", ""]
    lines.append(reporting.md_table(
        ["主题", "题目组", "Top-N", "分母", "理由"],
        [[t["name"], "、".join(t["prefixes"]), t["top_n"], t["denominator"], t.get("reason", "")]
         for t in result.topics],
    ))
    for topic in result.topics:
        name = topic["name"]
        profile_path = config.STATS_DIR / f"profile_llm_{name}.csv"
        if not profile_path.exists():
            continue
        profile = pd.read_csv(profile_path, keep_default_na=False, encoding="utf-8-sig")
        lines += ["", f"## {name}", ""]
        lines.append(f"数据文件：`llm/stats/{profile_path.name}`、`llm/stats/trends_llm_{name}.csv`")
        lines.append("")
        lines.append(reporting.md_table(
            ["题目组", "选项", "占比 %", "n"],
            [[r["group"], r["option"], r["pct"], r["n"]]
             for _, r in profile.head(10).iterrows()],
        ))
        lines += ["", result.narratives.get(name, "（无解读）"), ""]

    if result.singles:
        lines += ["", "## 单列分布", "",
                  f"覆盖列：{', '.join(f'`{c}`' for c in result.singles[:20])}",
                  "", "明细见 `llm/stats/singles_llm.csv`。", ""]

    if result.problems:
        lines += ["", "## 校验提示", "", reporting.md_list(result.problems[:30])]
    lines += ["", "## 模型调用", "", reporting.md_list(result.cache_lines), ""]
    (config.REPORTS_DIR / "analysis_report.md").write_text("\n".join(lines), encoding="utf-8")
