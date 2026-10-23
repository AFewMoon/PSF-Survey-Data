"""清洗阶段：模型判定列语义与年度清洗计划，Python 确定性执行。

流程：
  画像 -> 逐批语义标注（模型） -> 组路径/选项命名（模型） -> 年度算子决策（模型）
       -> 校验（白名单/证据/阈值） -> 执行器（纯函数） -> cleaned_llm_<year>.csv + 报告
"""
from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterator

import pandas as pd

from . import config, decision_schema, prompts, reporting
from .cache import CacheStore
from .dataio import read_json, read_raw, write_csv, write_json
from .ollama_client import ChatMeta, OllamaClient, TruncatedOutput
from .profiles import column_index, compact_row, load_profile
from .textnorm import (
    clean_cell, dedup_names, norm_key, norm_ws, option_from_header,
)


@dataclass
class CleanResult:
    year: int
    rows_in: int = 0
    cols_in: int = 0
    rows_out: int = 0
    cols_out: int = 0
    empty_rows: int = 0
    empty_cols: int = 0
    dup_rows: int = 0
    dup_cols: int = 0
    binarized: int = 0
    numeric: int = 0
    renamed: int = 0
    dropped_cols: list[str] = field(default_factory=list)
    pending_review: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    kind_counts: dict[str, int] = field(default_factory=dict)
    model_ops: dict[str, Any] = field(default_factory=dict)
    extra_missing: list[str] = field(default_factory=list)
    fallback_cols: int = 0
    cache_line: str = ""


# ---------------------------------------------------------------- 批处理


def _batches(columns: list[str], profile: dict[str, Any],
             batch_size: int) -> Iterator[list[str]]:
    """按「列数 + 字符预算」切批，避免单请求超上下文。"""
    batch: list[str] = []
    size = 0
    for col in columns:
        cost = len(json.dumps(compact_row(profile, col), ensure_ascii=False)) + 2
        if batch and (len(batch) >= batch_size or size + cost > config.BATCH_CHAR_BUDGET):
            yield batch
            batch, size = [], 0
        batch.append(col)
        size += cost
    if batch:
        yield batch


def _semantics_batch(
    year: int, batch: list[str], profile: dict[str, Any],
    client: OllamaClient, cache: CacheStore, depth: int = 0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """请求一批列的语义；截断则对半拆批递归。"""
    payload = [compact_row(profile, c) for c in batch]
    key = cache.key(
        {"year": year, "batch": batch, "profile": config.PROFILE_VERSION},
        config.PROMPT_VERSION["clean_semantics"],
    )
    record = cache.load(key)
    if record is not None:
        return list(record["response"].get("columns", [])), []

    system, user = prompts.semantics_messages(year, payload)
    num_predict = max(config.NUM_PREDICT_MIN, len(batch) * config.NUM_PREDICT_PER_COL)
    try:
        response, meta = client.chat_json(system, user, num_predict=num_predict,
                                          tag=f"semantics-{year}")
    except TruncatedOutput as exc:
        if len(batch) <= 1 or depth >= 3:
            return [], [f"{year} 年 {batch[:2]} 语义标注截断：{exc}"]
        mid = len(batch) // 2
        left, p1 = _semantics_batch(year, batch[:mid], profile, client, cache, depth + 1)
        right, p2 = _semantics_batch(year, batch[mid:], profile, client, cache, depth + 1)
        return left + right, p1 + p2

    items, problems = decision_schema.validate_semantics(response, batch, year)
    record = cache.record(
        "clean_semantics", config.PROMPT_VERSION["clean_semantics"],
        {"year": year, "batch": f"{batch[0]}…{batch[-1]}", "n": len(batch)},
        {"columns": items}, meta,
    )
    record["input_hash"] = key
    cache.save(key, record)
    cache.misses += 1
    return items, problems


def classify_columns(
    year: int, profile: dict[str, Any], client: OllamaClient,
    cache: CacheStore, batch_size: int,
) -> tuple[dict[str, dict[str, Any]], list[str], int]:
    """全列语义标注，返回 (列->语义, problems, 降级列数)。"""
    columns = [c["name"] for c in profile["columns"]]
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for batch in _batches(columns, profile, batch_size):
        items, batch_problems = _semantics_batch(year, batch, profile, client, cache)
        problems += batch_problems
        for item in items:
            found[item["column"]] = item

    idx = column_index(profile)
    fallback = 0
    for col in columns:
        if col not in found:
            found[col] = decision_schema.default_semantics(col, year)
            fallback += 1
        _align_kind_with_evidence(col, found[col], idx.get(col, {}), year,
                                  int(profile.get("rows", 0)))
        _set_naming(col, found[col], year)
    if year < 2020:
        _stabilize_2019_groups(columns, found)
    return found, problems, fallback


def _question_of(col: str) -> str:
    return norm_ws(col.split(":", 1)[1]).lower() if ":" in col else ""


def _stabilize_2019_groups(
    columns: list[str], semantics: dict[str, dict[str, Any]]
) -> None:
    """2019 同题选项列强制同组：同一问句下模型偶尔给出五花八门的组，按多数票统一。"""
    votes: dict[str, list[str]] = {}
    for col in columns:
        question = _question_of(col)
        if not question:
            continue
        kind = semantics[col]["kind"]
        if kind not in {"multi_option", "multi_level", "single_choice"}:
            continue
        group = semantics[col]["group"]
        if group:
            votes.setdefault(question, []).append(group)
    majority = {
        question: Counter(groups).most_common(1)[0][0] for question, groups in votes.items()
    }
    for col in columns:
        question = _question_of(col)
        target = majority.get(question)
        if not target:
            continue
        item = semantics[col]
        if item["kind"] not in {"multi_option", "multi_level", "single_choice"}:
            continue
        if item["group"] != target:
            item["group"] = target
            item["reason"] = _note(item["reason"], f"同题选项按多数票统一为 {target}")


def _align_kind_with_evidence(
    col: str, item: dict[str, Any], info: dict[str, Any], year: int, rows: int
) -> None:
    """用确定性画像证据纠正模型判定（证据优先，纠正写进 reason 便于审计）。"""
    kind = item["kind"]
    structured = bool(info.get("multi_like") or info.get("binary_like")
                      or info.get("level_like"))
    # 结构约束：2020+ 的选项列必有「组路径.选项」，2019 的选项列必有「选项:问句」
    has_option_structure = ("." in col) if year >= 2020 else (":" in col)
    if (kind != "identifier" and info.get("numeric_like") and rows
            and info.get("n_unique") == rows and info.get("non_empty_pct", 0) >= 99.0):
        item["kind"] = "identifier"
        item["group"], item["option"] = col, ""
        item["reason"] = _note(item["reason"], "画像显示取值唯一且无缺失，按样本标识纠正")
    elif info.get("level_like") and kind != "multi_level":
        item["kind"] = "multi_level"
        item["reason"] = _note(item["reason"],
                              "画像显示取值为「选项+程度」，按多选程度网格纠正")
    elif (info.get("multi_like") or info.get("binary_like")) and kind in {
        "free_text", "single_choice", "metadata"
    }:
        item["kind"] = "multi_option"
        item["reason"] = _note(item["reason"], "画像显示为勾选标记列，按多选题选项列纠正")
    elif (kind in {"multi_option", "multi_level"} and not structured
          and not has_option_structure):
        item["kind"] = "numeric" if info.get("numeric_like") else "single_choice"
        item["reason"] = _note(item["reason"], "列名为整题且无勾选证据，按单选题纠正")
    elif (info.get("redacted") and not structured
          and kind in {"single_choice", "multi_option", "multi_level"}):
        item["kind"] = "free_text"
        item["reason"] = _note(item["reason"], "画像显示为自由文本，已按脱敏规则纠正")


def _note(reason: str, extra: str) -> str:
    base = reason.strip()
    return f"{base}（{extra}）"[:200] if base else extra[:200]


def _set_naming(col: str, item: dict[str, Any], year: int) -> None:
    """列命名：2020+ 表头本身即 `组路径.选项`，直接按结构拆分，避免模型改写。

    2019 的表头是完整问句，需要模型给出的 group/option 才能得到点分标准名。
    """
    if year < 2020:
        return
    if item["kind"] in {"multi_option", "multi_level"} and "." in col:
        item["group"], item["option"] = col.rsplit(".", 1)
    elif item["kind"] in {"multi_option", "multi_level"}:
        item["group"] = item.get("group") or col
    else:
        item["group"], item["option"] = col, ""


# ---------------------------------------------------------------- 列名统一


def _clean_group(group: str) -> str:
    """组路径规范化：小写、空格转点、只保留字母数字与 . _ -。"""
    text = norm_ws(group).lower()
    text = re.sub(r"[^0-9a-z._-]+", ".", text)
    return re.sub(r"\.{2,}", ".", text).strip(".")


_DIMENSION_TOKENS = ("version", "years", "age")


def _invented_dimension(column: str, group: str) -> bool:
    """组名是否凭空引入原表头没有的「量纲词」。

    典型错误：把 `is.python.main`（是否以 Python 为主语言）命名为
    `ide.python_version`（Python 版本），会让两个不同问题在跨年对齐时合并。
    """
    low_col, low_group = column.lower(), group.lower()
    return any(tok in low_group and tok not in low_col for tok in _DIMENSION_TOKENS)


def _proposed_names(
    columns: list[str], semantics: dict[str, dict[str, Any]], year: int
) -> tuple[list[str], list[dict[str, Any]]]:
    """由 group/option 构造新列名：多选 group.option，单选 group。

    2020+ 的 group/option 来自原始表头（不改写大小写），2019 来自模型结果（需规范化）。
    """
    proposed: list[str] = []
    meta: list[dict[str, Any]] = []
    for col in columns:
        item = semantics[col]
        kind = item["kind"]
        group = _clean_group(item["group"]) if year < 2020 else norm_ws(item["group"])
        option = norm_ws(item["option"])
        # 2019 的 `选项:问句` 表头：选项文本直接取自表头，保证同一题的各选项列不会撞名
        if year < 2020 and ":" in col and option_from_header(col):
            option = norm_ws(option_from_header(col))
        has_option = bool(option) and (kind in {"multi_option", "multi_level"}
                                       or (year < 2020 and ":" in col))
        if has_option:
            name = f"{group}.{option}" if group else option
        elif kind in {"single_choice", "numeric"} and group:
            name = group
            option = ""
            if year >= 2020 and _invented_dimension(col, group):
                # 模型给单选列编造了新维度，退回原表头，避免跨年把不同问题并到一起
                name = col
                group = col
        else:
            name = col
            option = ""
        proposed.append(name)
        meta.append({**item, "group": group, "option": option, "proposed": name})
    final = dedup_names(proposed)
    for row, name in zip(meta, final):
        row["new"] = name
    return final, meta


# ---------------------------------------------------------------- 年度计划


def _plan_evidence(profile: dict[str, Any], semantics: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {
        "rows": profile["rows"],
        "cols": profile["cols"],
        "empty_rows": profile["empty_rows"],
        "empty_rows_pct": round(profile["empty_rows"] / profile["rows"] * 100, 1)
        if profile["rows"] else 0.0,
        "empty_cols_count": len(profile["empty_cols"]),
        "empty_cols_sample": profile["empty_cols"][:5],
        "dup_rows": profile["dup_rows"],
        "dup_col_groups": len(profile["dup_col_groups"]),
        "dup_col_sample": profile["dup_col_groups"][:3],
        "kinds": {
            k: sum(1 for v in semantics.values() if v["kind"] == k)
            for k in config.KINDS
        },
    }


def _metadata_candidates(
    profile: dict[str, Any], semantics: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates = []
    for col in [c["name"] for c in profile["columns"]]:
        info = semantics[col]
        if info["kind"] != "metadata":
            continue
        candidates.append({
            "id": f"M{len(candidates) + 1}",
            "column": col,
            "non_empty_pct": column_index(profile)[col]["non_empty_pct"],
            "reason": info["reason"][:80],
        })
        if len(candidates) >= 40:
            break
    return candidates


def clean_year(
    year: int, client: OllamaClient | None, refresh: bool,
    batch_size: int, apply_review: bool,
) -> CleanResult:
    result = CleanResult(year=year)
    profile = load_profile(year)
    result.rows_in, result.cols_in = profile["rows"], profile["cols"]
    if client is None:
        return result

    cache = CacheStore("clean_semantics", client.digest, refresh=refresh)
    semantics, problems, fallback = classify_columns(year, profile, client, cache, batch_size)
    result.problems += problems
    result.fallback_cols = fallback
    result.kind_counts = {
        k: sum(1 for v in semantics.values() if v["kind"] == k) for k in config.KINDS
    }

    # 年度整体算子（模型决策）
    evidence = _plan_evidence(profile, semantics)
    candidates = _metadata_candidates(profile, semantics)
    plan_cache = CacheStore("clean_plan", client.digest, refresh=refresh)
    system, user = prompts.clean_plan_messages(year, evidence, candidates)
    plan_key = plan_cache.key({"year": year, "cols": profile["cols"]},
                              config.PROMPT_VERSION["clean_plan"])

    def call_plan() -> tuple[dict[str, Any], ChatMeta]:
        return client.chat_json(system, user, num_predict=700, tag=f"clean-plan-{year}")

    raw_plan, plan_record, from_cache = plan_cache.get_or_call(
        plan_key, config.PROMPT_VERSION["clean_plan"],
        {"year": year, "candidates": len(candidates)},
        call_plan,
        fallback=lambda: {"ops": [], "drop_cols": [], "reason": "fallback：模型不可用，全部保留"},
    )
    plan, review, plan_problems = decision_schema.validate_global_plan(
        raw_plan, evidence, candidates, year
    )
    result.problems += plan_problems
    result.model_ops = plan["ops"]
    result.pending_review = review

    approved = _approved_columns(apply_review)
    drop_cols = [c for c in plan["drop_cols"] if c in approved]

    df, stats = _execute(year, profile, semantics, plan, drop_cols, result.problems)
    result.rows_out, result.cols_out = df.shape
    result.empty_rows = stats["empty_rows"]
    result.empty_cols = stats["empty_cols"]
    result.dup_rows = stats["dup_rows"]
    result.dup_cols = stats["dup_cols"]
    result.binarized = stats["binarized"]
    result.numeric = stats["numeric"]
    result.renamed = stats["renamed"]
    result.dropped_cols = stats["dropped_cols"]
    result.extra_missing = stats["extra_missing"]

    write_csv(df, config.CLEANED_DIR / f"cleaned_llm_{year}.csv")
    write_json(
        config.CLEAN_DECISIONS_DIR / f"{year}.columns.json",
        {"year": year, "columns": stats["meta"]},
    )
    result.cache_line = f"{cache.report()} | {plan_cache.report()}"
    result.model_ops["_plan_reason"] = plan.get("reason", "")
    result.model_ops["_from_cache"] = from_cache
    result.model_ops["_fallback"] = bool(plan_record.get("fallback"))
    return result


def _approved_columns(apply_review: bool) -> set[str]:
    if not apply_review or not config.REVIEW_FILE.exists():
        return set()
    try:
        payload = read_json(config.REVIEW_FILE)
    except (json.JSONDecodeError, OSError):
        return set()
    return {str(c) for c in payload.get("approved_drop_cols", [])}


def _extra_missing_tokens(
    semantics: dict[str, dict[str, Any]], profile: dict[str, Any], problems: list[str]
) -> set[str]:
    """模型新增的缺失标记：跳过受保护文本，且覆盖率需 < 阈值。"""
    idx = column_index(profile)
    tokens: set[str] = set()
    for col, item in semantics.items():
        info = idx.get(col, {})
        top = [str(v).lower() for v in info.get("top", [])]
        top_share = float(info.get("top_share", 0.0))
        for token in item.get("missing_tokens", []):
            low = norm_ws(token).lower()
            if not low or low in config.MISSING_TOKENS:
                continue
            if low in config.PROTECTED_TOKENS:
                problems.append(f"{col}: 缺失标记 {token!r} 是合法选项，已忽略")
                continue
            if len(low) > 24:
                problems.append(f"{col}: 缺失标记过长，已忽略")
                continue
            if top and low == top[0] and top_share > config.MAX_EXTRA_MISSING_SHARE * 100:
                problems.append(
                    f"{col}: 缺失标记 {token!r} 是该列主取值（{top_share:.1f}%），已忽略"
                )
                continue
            tokens.add(low)
    return tokens


def _execute(
    year: int, profile: dict[str, Any], semantics: dict[str, dict[str, Any]],
    plan: dict[str, Any], drop_cols: list[str], problems: list[str],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """确定性执行器：纯函数式，不修改入参，返回新 df。"""
    df = read_raw(year)
    stats: dict[str, Any] = {
        "empty_rows": 0, "empty_cols": 0, "dup_rows": 0, "dup_cols": 0,
        "binarized": 0, "numeric": 0, "renamed": 0, "dropped_cols": [],
        "extra_missing": [], "meta": [],
    }

    extra_tokens = _extra_missing_tokens(semantics, profile, problems)
    stats["extra_missing"] = sorted(extra_tokens)
    df = df.map(lambda v: clean_cell(v, extra_tokens))

    new_names, meta = _proposed_names(list(df.columns), semantics, year)
    stats["renamed"] = sum(1 for a, b in zip(df.columns, new_names) if a != b)
    df = df.set_axis(new_names, axis=1)

    ops = plan["ops"]
    if ops.get("drop_empty_cols", {}).get("apply"):
        empty = [c for c in df.columns if (df[c] == "").all()]
        stats["empty_cols"] = len(empty)
        df = df.drop(columns=empty)
    if ops.get("drop_empty_rows", {}).get("apply"):
        mask = (df == "").all(axis=1)
        stats["empty_rows"] = int(mask.sum())
        df = df.loc[~mask].reset_index(drop=True)
    if ops.get("drop_dup_rows", {}).get("apply"):
        stats["dup_rows"] = int(df.duplicated().sum())
        df = df.drop_duplicates().reset_index(drop=True)
    if ops.get("drop_dup_cols", {}).get("apply"):
        seen: dict[int, str] = {}
        dup: list[str] = []
        for col in df.columns:
            key = int(pd.util.hash_pandas_object(df[col], index=False).sum())
            if key in seen:
                dup.append(col)
            else:
                seen[key] = col
        stats["dup_cols"] = len(dup)
        df = df.drop(columns=dup)

    if drop_cols:
        present = [c for c in drop_cols if c in df.columns]
        df = df.drop(columns=present)
        stats["dropped_cols"] = present
    else:
        stats["dropped_cols"] = []

    # 类型归一：完全由模型给出的 kind + 画像证据共同决定
    idx = column_index(profile)
    sem_by_new = {m["new"]: m for m in meta}
    for col in list(df.columns):
        item = sem_by_new.get(col, {})
        info = idx.get(item.get("column", col), {})
        kind = item.get("kind", "")
        if kind == "multi_option" and (info.get("multi_like") or info.get("binary_like")):
            df[col] = (df[col] != "").astype("int64")
            stats["binarized"] += 1
        elif kind == "numeric" and info.get("numeric_like") and col != "response_id":
            numeric = pd.to_numeric(df[col].replace("", None))
            df[col] = numeric.astype("Int64") if (numeric.dropna() % 1 == 0).all() \
                else numeric.astype("float64")
            stats["numeric"] += 1
        elif kind == "identifier" and col.lower().startswith("response"):
            if pd.to_numeric(df[col], errors="coerce").notna().all():
                df[col] = pd.to_numeric(df[col]).astype("int64")
                stats["numeric"] += 1

    stat_by_new = {m["new"]: m for m in meta}
    for name in df.columns:
        item = stat_by_new.get(name, {})
        stats["meta"].append({
            "original": item.get("column", name),
            "new": name,
            "kind": item.get("kind", ""),
            "group": item.get("group", ""),
            "option": item.get("option", ""),
            "reason": item.get("reason", ""),
            "fallback": item.get("reason", "").startswith("fallback"),
        })
    return df, stats


# ---------------------------------------------------------------- 报告


def write_report(results: list[CleanResult], usage: Any = None) -> None:
    lines = ["# LLM 驱动清洗报告", "", f"生成时间：{reporting.now_str()}", ""]
    lines.append(
        f"模型：`{config.MODEL}`（temperature={config.TEMPERATURE}, seed={config.SEED}, "
        f"think=off）｜管线：列画像 → 模型语义标注 → 模型年度算子决策 → 校验 → 确定性执行"
    )
    lines.append("")
    lines.append(reporting.md_table(
        ["年份", "行(前/后)", "列(前/后)", "空列", "空行", "重复行", "重复列", "多选归一", "数值列", "重命名"],
        [[r.year, f"{r.rows_in}/{r.rows_out}", f"{r.cols_in}/{r.cols_out}",
          r.empty_cols, r.empty_rows, r.dup_rows, r.dup_cols, r.binarized,
          r.numeric, r.renamed] for r in results],
    ))
    for r in results:
        lines += ["", f"## {r.year} 年", ""]
        kinds = "、".join(f"{k}={v}" for k, v in r.kind_counts.items() if v) or "无"
        lines.append(f"- 列语义分布：{kinds}")
        lines.append(f"- 模型列标注降级：{r.fallback_cols} 列（模型未覆盖，按表头结构默认）")
        ops = {k: v for k, v in r.model_ops.items() if not k.startswith("_")}
        if ops:
            detail = "；".join(
                f"{k}={'执行' if v.get('apply') else '保留'}（{reporting.truncate(v.get('reason', ''), 40)}）"
                for k, v in ops.items()
            )
            lines.append(f"- 算子决策：{detail}")
        if r.model_ops.get("_plan_reason"):
            lines.append(f"- 决策说明：{r.model_ops['_plan_reason']}")
        if r.extra_missing:
            lines.append(f"- 模型新增缺失标记（已生效）：{', '.join(r.extra_missing)}")
        if r.dropped_cols:
            lines.append(f"- 已删除列（人工确认）：{', '.join(r.dropped_cols)}")
        if r.pending_review:
            lines += ["", "**待人工确认的删列（默认不执行）**", ""]
            lines.append(reporting.md_table(
                ["年份", "列名", "理由"],
                [[i["year"], i["column"], i["reason"]] for i in r.pending_review],
            ))
            lines += ["", f"确认后在 `llm/decisions/review_approved.json` 的 "
                          f"`approved_drop_cols` 中列出列名，并加 `--apply-review` 重跑。"]
        if r.problems:
            lines += ["", "**校验提示（已按安全默认值处理，不静默丢弃）**", ""]
            lines.append(reporting.md_list(r.problems[:40]))
            if len(r.problems) > 40:
                lines.append(f"- …… 另有 {len(r.problems) - 40} 条")
        lines.append("")
        lines.append(f"缓存：{r.cache_line}")

    lines += ["", "## 产出", "",
              f"- 清洗数据：`llm/cleaned/cleaned_llm_<year>.csv`",
              f"- 列决策明细：`llm/decisions/clean/<year>.columns.json`",
              f"- 决策缓存：`llm/decisions/clean/*.json`（含模型、耗时、理由，可人工修订后重放）"]
    if usage is not None:
        lines += ["", f"模型调用统计：{usage.summary()}"]
    lines.append("")
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (config.REPORTS_DIR / "cleaning_report.md").write_text("\n".join(lines), encoding="utf-8")
