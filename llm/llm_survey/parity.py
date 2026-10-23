"""一致性核对：LLM 管线 vs 规则管线（向量化比对，仅一次模型调用解读分歧）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import config, decision_schema, prompts, reporting
from .cache import CacheStore
from .ollama_client import ChatMeta, OllamaClient
from .textnorm import norm_key


@dataclass
class ParityResult:
    rule_cols: int = 0
    llm_cols: int = 0
    matched: int = 0
    jaccard: float = 0.0
    rule_only: list[str] = field(default_factory=list)
    llm_only: list[str] = field(default_factory=list)
    row_diffs: list[list[Any]] = field(default_factory=list)
    missing_diffs: list[list[Any]] = field(default_factory=list)
    topic_diffs: list[list[Any]] = field(default_factory=list)
    note: str = ""
    problems: list[str] = field(default_factory=list)
    holdout_years: list[int] = field(default_factory=list)


def _rule_master() -> pd.DataFrame | None:
    path = config.RULE_ALIGNED_DIR / "survey_2019_2024_master.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig", low_memory=False)


def _llm_master() -> pd.DataFrame | None:
    path = config.ALIGNED_DIR / f"survey_{config.YEARS[0]}_{config.YEARS[-1]}_master_llm.csv"
    if not path.exists():
        return None
    return pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig", low_memory=False)


def _non_empty_share(df: pd.DataFrame, col: str) -> float:
    s = df[col]
    if s.dtype.kind in "iuf":
        return float((s == 1).mean() * 100) if s.dtype.kind in "iu" else float(
            s.notna().mean() * 100)
    return float((s != "").mean() * 100)


def run(client: OllamaClient | None, refresh: bool,
        holdout_years: set[int] | None = None) -> ParityResult:
    result = ParityResult()
    result.holdout_years = sorted(config.HOLDOUT_YEARS if holdout_years is None
                                  else holdout_years)
    rule = _rule_master()
    llm = _llm_master()
    if rule is None or llm is None:
        result.problems.append("缺少规则管线或 LLM 管线的总表，无法比对")
        write_report(result)
        return result

    rule_cols = [c for c in rule.columns if c != "year"]
    llm_cols = [c for c in llm.columns if c != "year"]
    result.rule_cols, result.llm_cols = len(rule_cols), len(llm_cols)

    rule_index = {norm_key(c): c for c in rule_cols}
    llm_index = {norm_key(c): c for c in llm_cols}
    keys = set(rule_index) & set(llm_index)
    union = set(rule_index) | set(llm_index)
    result.matched = len(keys)
    result.jaccard = round(len(keys) / len(union) * 100, 1) if union else 0.0
    result.rule_only = sorted(rule_index[k] for k in set(rule_index) - keys)[:15]
    result.llm_only = sorted(llm_index[k] for k in set(llm_index) - keys)[:15]

    # 行数对比
    rule_rows = rule["year"].value_counts().to_dict()
    llm_rows = llm["year"].value_counts().to_dict()
    for year in sorted(set(rule_rows) | set(llm_rows)):
        result.row_diffs.append([year, int(rule_rows.get(year, 0)), int(llm_rows.get(year, 0))])

    # 缺失率差异（按匹配列）
    diffs: list[list[Any]] = []
    for key in sorted(keys):
        share_rule = _non_empty_share(rule, rule_index[key])
        share_llm = _non_empty_share(llm, llm_index[key])
        if abs(share_rule - share_llm) >= 1.0:
            diffs.append([rule_index[key], llm_index[key],
                          round(share_rule, 1), round(share_llm, 1),
                          round(share_llm - share_rule, 1)])
    diffs.sort(key=lambda row: abs(row[4]), reverse=True)
    result.missing_diffs = diffs[:10]

    # 同主题占比差异
    result.topic_diffs = _topic_diffs(rule, llm)

    summary = {
        "列集合": {"规则": result.rule_cols, "LLM": result.llm_cols,
                 "匹配": result.matched, "Jaccard_pct": result.jaccard},
        "仅规则管线有的列（示例）": result.rule_only[:8],
        "仅LLM管线有的列（示例）": result.llm_only[:8],
        "行数差异": result.row_diffs,
        "缺失率差异_Top": result.missing_diffs[:6],
        "同主题占比差异_Top": result.topic_diffs[:8],
    }
    result.note = _note(client, refresh, summary, result)
    write_report(result, summary)
    return result


def _topic_diffs(rule: pd.DataFrame, llm: pd.DataFrame) -> list[list[Any]]:
    """用 LLM 管线统计表的主题口径，在规则管线上复算，比较百分点差。"""
    rows: list[list[Any]] = []
    for path in sorted(config.STATS_DIR.glob("profile_llm_*.csv")):
        try:
            profile = pd.read_csv(path, keep_default_na=False, encoding="utf-8-sig")
        except (pd.errors.ParserError, OSError):
            continue
        if profile.empty or "group" not in profile.columns:
            continue
        year = int(profile["year"].iloc[0])
        rule_year = rule[rule["year"] == year]
        if rule_year.empty:
            continue
        for _, item in profile.head(6).iterrows():
            group, option = str(item["group"]), str(item["option"])
            llm_pct = round(float(item["pct"]), 1)
            topic = path.stem.replace("profile_llm_", "")
            if group in rule.columns:  # 单选题：按取值占比比较
                values = rule_year[group].astype("string").str.strip()
                share = round(float((values == option).mean() * 100), 1)
                rows.append([topic, group, option, llm_pct, share, round(llm_pct - share, 1)])
                continue
            candidates = [
                c for c in rule.columns
                if c.startswith(group + ".") and norm_key(c[len(group) + 1:]) == norm_key(option)
            ]
            if len(candidates) != 1:
                continue
            share = round(_non_empty_share(rule_year, candidates[0]), 1)
            rows.append([topic, group, option, llm_pct, share, round(llm_pct - share, 1)])
    rows.sort(key=lambda row: abs(row[5]), reverse=True)
    return rows[:12]


def _note(client: OllamaClient | None, refresh: bool, summary: dict[str, Any],
          result: ParityResult) -> str:
    if client is None:
        return "（离线模式：未生成模型解读）"
    cache = CacheStore("parity_note", client.digest, refresh=refresh)
    system, user = prompts.parity_messages(summary)
    key = cache.key({"summary": summary, "rules": result.rule_cols, "llm": result.llm_cols,
                     "matched": result.matched}, config.PROMPT_VERSION["parity_note"])

    def call() -> tuple[dict[str, Any], ChatMeta]:
        return client.chat_json(system, user, num_predict=700, tag="parity-note")

    response, _record, _ = cache.get_or_call(
        key, config.PROMPT_VERSION["parity_note"],
        {"rule": result.rule_cols, "llm": result.llm_cols}, call,
        fallback=lambda: {"text": "（模型不可用，未生成分歧解读）"},
    )
    try:
        return decision_schema.validate_narrative(response, min_chars=20)
    except decision_schema.DecisionError as exc:
        result.problems.append(f"分歧解读不可用：{exc}")
        return "（模型返回的解读为空）"


def write_report(result: ParityResult, summary: dict[str, Any] | None = None) -> None:
    lines = ["# 规则管线 vs LLM 管线一致性核对", "", f"生成时间：{reporting.now_str()}", ""]
    lines.append(
        f"评测口径：留出年份 {','.join(str(y) for y in result.holdout_years) or '无'}"
        "的人工映射未进入提示词；同名匹配列的一致性可视为留出测试结果。"
    )
    if result.problems and result.rule_cols == 0:
        lines += [reporting.md_list(result.problems), ""]
        config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        (config.REPORTS_DIR / "parity_report.md").write_text("\n".join(lines), encoding="utf-8")
        return

    lines.append(reporting.md_table(
        ["指标", "规则管线", "LLM 管线"],
        [["总表列数（不含 year）", result.rule_cols, result.llm_cols],
         ["归一后匹配列（Jaccard %）", "—", f"{result.matched}（{result.jaccard}%）"]],
    ))
    lines += ["", "## 各年行数", "", reporting.md_table(
        ["年份", "规则管线", "LLM 管线"], result.row_diffs)]
    if result.missing_diffs:
        lines += ["", "## 非空率差异 Top 10", "",
                  reporting.md_table(["规则列", "LLM 列", "规则非空%", "LLM 非空%", "差值(pp)"],
                                     result.missing_diffs)]
    if result.topic_diffs:
        lines += ["", "## 同主题占比差异 Top", "",
                  reporting.md_table(["主题", "组", "选项", "LLM %", "规则 %", "差值(pp)"],
                                     result.topic_diffs)]
    if result.rule_only:
        lines += ["", "## 仅规则管线存在的列（示例）", "", reporting.md_list(result.rule_only)]
    if result.llm_only:
        lines += ["", "## 仅 LLM 管线存在的列（示例）", "", reporting.md_list(result.llm_only)]
    if summary:
        lines += ["", "## 差异摘要（送入模型）", "", "```json",
                  reporting.truncate(str(summary), 1200), "```"]
    lines += ["", "## 模型解读", "", result.note or "（无）", ""]
    if result.problems:
        lines += ["", "## 提示", "", reporting.md_list(result.problems)]
    lines.append("")
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.REPORTS_DIR / "parity_report.md").write_text("\n".join(lines), encoding="utf-8")
