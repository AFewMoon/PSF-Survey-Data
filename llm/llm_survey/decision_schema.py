"""决策校验：算子白名单 + 引用完整性 + 覆盖率 + 阈值。

模型输出一律先过这里；校验失败不静默丢弃，而是记录 problems 并降级到安全默认值。
"""
from __future__ import annotations

from typing import Any, Iterable

from . import config
from .textnorm import norm_key


class DecisionError(ValueError):
    """决策结构非法（不可降级，直接失败），携带可定位信息。"""

    def __init__(self, message: str, details: Iterable[str] | None = None) -> None:
        self.details = list(details or [])
        super().__init__(message + (f"：{'; '.join(self.details)}" if self.details else ""))


# ---------------------------------------------------------------- 列语义


def validate_semantics(
    response: dict[str, Any], batch: list[str], year: int
) -> tuple[list[dict[str, Any]], list[str]]:
    """校验逐列语义标注，返回 (合法条目, problems)。缺失列由调用方补默认。"""
    items = response.get("columns")
    if not isinstance(items, list):
        raise DecisionError(f"{year} 年语义标注缺少 columns 数组")
    allowed = set(batch)
    valid: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("columns 内含非对象元素")
            continue
        col = str(raw.get("column", "")).strip()
        if col not in allowed:
            problems.append(f"列不存在于本批：{col!r}")
            continue
        if col in seen:
            problems.append(f"列重复标注：{col}")
            continue
        kind = str(raw.get("kind", "")).strip()
        if kind not in config.KINDS:
            problems.append(f"{col}: kind 非法 {kind!r}")
            kind = "metadata"
        group = str(raw.get("group", "")).strip()
        option = str(raw.get("option", "")).strip()
        if kind == "multi_option" and not group:
            problems.append(f"{col}: multi_option 缺少 group")
            group = col.rsplit(".", 1)[0] if "." in col else col
        if kind in {"single_choice", "multi_option"} and not option and kind == "single_choice":
            option = ""
        valid.append(
            {
                "column": col,
                "kind": kind,
                "group": group,
                "option": option,
                "missing_tokens": [str(t) for t in raw.get("missing_tokens", []) or []][:5]
                if isinstance(raw.get("missing_tokens", []), list) else [],
                "reason": str(raw.get("reason", ""))[:200],
                "year": year,
            }
        )
        seen.add(col)
    return valid, problems


def default_semantics(column: str, year: int) -> dict[str, Any]:
    """降级默认：按列名结构猜测，标记 fallback。"""
    option = column.rsplit(".", 1)[-1] if "." in column else ""
    group = column[: len(column) - len(option) - 1] if option else column
    kind = "multi_option" if option else "single_choice"
    return {
        "column": column,
        "kind": kind,
        "group": group,
        "option": option,
        "missing_tokens": [],
        "reason": "fallback：模型未返回该列，按表头结构默认判定",
        "year": year,
    }


# ---------------------------------------------------------------- 清洗算子


GLOBAL_OPS = ("drop_empty_rows", "drop_empty_cols", "drop_dup_rows", "drop_dup_cols")


def validate_global_plan(
    response: dict[str, Any],
    evidence: dict[str, Any],
    candidates: list[dict[str, Any]],
    year: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    """校验年度整体清洗计划（模型只对候选算子集合做 yes/no + 指定候选编号）。

    返回 (执行的算子集合, 待确认的删列项, problems)。缺省一律不执行（保守）。
    """
    ops_raw = response.get("ops")
    if not isinstance(ops_raw, list):
        raise DecisionError(f"{year} 年清洗计划缺少 ops 数组")
    problems: list[str] = []
    decisions: dict[str, dict[str, Any]] = {}
    for raw in ops_raw:
        if not isinstance(raw, dict):
            problems.append("ops 内含非对象元素")
            continue
        op = str(raw.get("op", "")).strip()
        if op not in GLOBAL_OPS:
            problems.append(f"算子不在白名单：{op!r}")
            continue
        decisions[op] = {
            "apply": bool(raw.get("apply", False)),
            "reason": str(raw.get("reason", ""))[:200],
        }
    for op in GLOBAL_OPS:
        if op not in decisions:
            problems.append(f"模型未给出 {op} 决定，按不执行处理")
            decisions[op] = {"apply": False, "reason": "模型未返回该算子，默认保留"}

    # 证据反向约束：删行不得超上限，全空/重复为 0 时不允许执行
    for op, key, cap in (
        ("drop_empty_rows", "empty_rows", config.MAX_DROP_ROW_SHARE),
        ("drop_dup_rows", "dup_rows", config.MAX_DROP_ROW_SHARE),
    ):
        count = int(evidence.get(key, 0))
        if decisions[op]["apply"] and count == 0:
            problems.append(f"{op} 无证据（{key}=0），已忽略")
            decisions[op]["apply"] = False
        if decisions[op]["apply"] and count > int(evidence.get("rows", 0) * cap):
            problems.append(f"{op} 计划删除 {count} 行，超过 {cap:.0%} 上限，已忽略")
            decisions[op]["apply"] = False
    for op, key in (("drop_empty_cols", "empty_cols"), ("drop_dup_cols", "dup_col_groups")):
        if decisions[op]["apply"] and not evidence.get(key):
            problems.append(f"{op} 无证据（{key} 为空），已忽略")
            decisions[op]["apply"] = False

    # 候选元数据列：只能从给定编号中选，且全部进人工确认队列
    by_id = {str(c["id"]): c for c in candidates}
    requested = response.get("drop_cols") or []
    if isinstance(requested, (str, int)):
        requested = [requested]
    review: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rid in requested:
        rid = str(rid).strip()
        if rid not in by_id:
            problems.append(f"drop_cols 含未知候选编号：{rid!r}")
            continue
        if rid in seen:
            continue
        seen.add(rid)
        review.append(
            {
                "op": "drop_col",
                "column": by_id[rid]["column"],
                "year": year,
                "reason": str(response.get("reason", ""))[:160] or "模型判定为无用元数据列",
                "approved": False,
            }
        )
    limit = int(evidence.get("cols", 0) * config.MAX_DROP_COL_SHARE)
    if len(review) > max(1, limit):
        problems.append(f"drop_cols 数量 {len(review)} 超过上限 {max(1, limit)}，全部挂起")
        for item in review:
            item["reason"] += "（超上限，需人工确认）"

    plan = {
        "ops": decisions,
        "drop_cols": [item["column"] for item in review],
        "reason": str(response.get("reason", ""))[:200],
    }
    return plan, review, problems


# ---------------------------------------------------------------- 对齐映射


def validate_group_map(
    response: dict[str, Any], groups: list[str]
) -> tuple[dict[str, str], list[str]]:
    """组路径标准化：每个输入组必须给出非空标准路径。"""
    items = response.get("groups")
    if not isinstance(items, list):
        raise DecisionError("组路径决策缺少 groups 数组")
    allowed = set(groups)
    mapping: dict[str, str] = {}
    problems: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("groups 内含非对象元素")
            continue
        src = str(raw.get("name", "")).strip()
        dst = str(raw.get("canonical", "")).strip()
        if src not in allowed:
            problems.append(f"未知组路径：{src!r}")
            continue
        if not dst or " " in dst:
            problems.append(f"{src} 的标准路径非法：{dst!r}")
            continue
        mapping[src] = dst
    return mapping, problems


def validate_option_clusters(
    response: dict[str, Any], options: list[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """选项同义聚类：每个选项最多归入一个簇，canonical 非空。"""
    items = response.get("options")
    if not isinstance(items, list):
        raise DecisionError("选项聚类缺少 options 数组")
    allowed = {norm_key(o): o for o in options}
    used: set[str] = set()
    clusters: list[dict[str, Any]] = []
    problems: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("options 内含非对象元素")
            continue
        variants_raw = raw.get("variants")
        variants_raw = variants_raw if isinstance(variants_raw, list) else [variants_raw]
        keys: list[str] = []
        for v in variants_raw:
            key = norm_key(str(v))
            if key not in allowed:
                problems.append(f"未知选项：{v!r}")
                continue
            if key in used:
                problems.append(f"选项重复归簇：{v!r}")
                continue
            keys.append(key)
        canonical = str(raw.get("canonical", "")).strip()
        if not canonical:
            problems.append("聚类缺少 canonical")
            continue
        if len(keys) < 2:
            continue
        used.update(keys)
        clusters.append(
            {"variants": [allowed[k] for k in keys], "canonical": canonical,
             "reason": str(raw.get("reason", ""))[:160]}
        )
    return clusters, problems


def validate_cluster_batch(
    response: dict[str, Any], units: dict[str, list[str]]
) -> tuple[dict[str, dict[str, str]], list[str]]:
    """批量选项聚类：返回 {组名: {norm_key(原文本): 标准文本}}。"""
    groups = response.get("groups")
    if not isinstance(groups, list):
        raise DecisionError("聚类决策缺少 groups 数组")
    mapping: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    for raw in groups:
        if not isinstance(raw, dict):
            problems.append("groups 内含非对象元素")
            continue
        name = str(raw.get("name", "")).strip()
        if name not in units:
            problems.append(f"聚类返回了未知组：{name!r}")
            continue
        allowed = {norm_key(v): v for v in units[name]}
        used: set[str] = set()
        per_group: dict[str, str] = {}
        options = raw.get("options")
        if isinstance(options, dict):
            options = [options]
        for opt in options or []:
            if not isinstance(opt, dict):
                problems.append(f"{name}: options 内含非对象元素")
                continue
            variants = opt.get("variants")
            variants = variants if isinstance(variants, list) else [variants]
            canonical = str(opt.get("canonical", "")).strip()
            keys: list[str] = []
            for v in variants:
                key = norm_key(str(v))
                if key not in allowed:
                    problems.append(f"{name}: 未知文本 {v!r}")
                    continue
                if key in used:
                    problems.append(f"{name}: 文本重复归簇 {v!r}")
                    continue
                keys.append(key)
            if not canonical or len(keys) < 2:
                continue
            # 防「整组塌缩」：4B 模型偶发把同组所有选项并成一个（如全部并成 "In Docker containers"）
            total = len(units[name])
            collapse = len(keys) >= total
            too_big = (len(keys) > config.MAX_CLUSTER_SIZE
                       or (len(keys) >= 3 and len(keys) > total * config.MAX_CLUSTER_SHARE))
            if collapse or too_big:
                problems.append(
                    f"{name}: 归并吞并 {len(keys)}/{total} 个选项，超过安全上限，已忽略"
                )
                continue
            used.update(keys)
            for key in keys:
                per_group[key] = canonical
        if per_group:
            mapping[name] = per_group
    return mapping, problems


# ---------------------------------------------------------------- 统计计划


def validate_stats_plan(
    response: dict[str, Any], columns: list[str]
) -> tuple[dict[str, Any], list[str]]:
    """统计口径计划：主题前缀必须在真实列集合中存在。"""
    topics_raw = response.get("topics")
    if not isinstance(topics_raw, list):
        raise DecisionError("统计计划缺少 topics 数组")
    existing = set(columns)
    topics: list[dict[str, Any]] = []
    problems: list[str] = []
    names: set[str] = set()
    for raw in topics_raw:
        if not isinstance(raw, dict):
            problems.append("topics 内含非对象元素")
            continue
        name = str(raw.get("name", "")).strip()
        if not name or not name.replace("_", "").isalnum():
            problems.append(f"主题名非法：{name!r}")
            continue
        if name in names:
            problems.append(f"主题名重复：{name}")
            continue
        prefixes = [str(p).strip() for p in raw.get("prefixes", []) or [] if str(p).strip()]
        hit = [p for p in prefixes if p in existing
               or any(c.startswith(p + ".") for c in existing)]
        if not hit:
            problems.append(f"主题 {name} 的前缀在数据中不存在：{prefixes[:3]}")
            continue
        top_n = raw.get("top_n", 10)
        top_n = int(top_n) if isinstance(top_n, (int, float)) else 10
        top_n = max(2, min(30, top_n))
        denominator = str(raw.get("denominator", "total")).strip()
        if denominator not in {"total", "answered"}:
            denominator = "total"
        topics.append(
            {"name": name, "prefixes": hit, "top_n": top_n, "denominator": denominator,
             "reason": str(raw.get("reason", ""))[:160]}
        )
        names.add(name)
    singles: list[str] = []
    for col in response.get("singles", []) or []:
        col = str(col).strip()
        if col in existing:
            singles.append(col)
        else:
            problems.append(f"单列统计引用了不存在的列：{col!r}")
    if not topics and not singles:
        raise DecisionError("统计计划为空（没有任何合法主题或单列）")
    return {"topics": topics, "singles": singles}, problems


# ---------------------------------------------------------------- 图表规格

CHART_KINDS = ("bar", "hbar", "line", "grouped_bar", "heatmap")


def validate_chart_specs(
    response: dict[str, Any], available: list[str], max_charts: int = 12
) -> tuple[list[dict[str, Any]], list[str]]:
    items = response.get("charts")
    if not isinstance(items, list):
        raise DecisionError("图表决策缺少 charts 数组")
    allowed = set(available)
    specs: list[dict[str, Any]] = []
    problems: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("charts 内含非对象元素")
            continue
        source = str(raw.get("source", "")).strip()
        kind = str(raw.get("kind", "")).strip()
        if source not in allowed:
            problems.append(f"图表数据源不存在：{source!r}")
            continue
        if kind not in CHART_KINDS:
            problems.append(f"图表类型不支持：{kind!r}")
            continue
        name = str(raw.get("name", "")).strip() or f"chart_{len(specs) + 1}"
        name = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)[:48]
        top_n = raw.get("top_n", 10)
        top_n = int(top_n) if isinstance(top_n, (int, float)) else 10
        specs.append(
            {
                "name": name,
                "kind": kind,
                "source": source,
                "title": str(raw.get("title", ""))[:80] or name,
                "top_n": max(3, min(30, top_n)),
                "reason": str(raw.get("reason", ""))[:160],
            }
        )
        if len(specs) >= max_charts:
            break
    return specs, problems


def validate_narrative(response: dict[str, Any], min_chars: int = 40) -> str:
    """叙述性输出：接受 {"text": "..."} 或 {"narrative": "..."}。"""
    for key in ("text", "narrative", "summary"):
        value = response.get(key)
        if isinstance(value, str) and len(value.strip()) >= min_chars:
            return value.strip()
    raise DecisionError("叙述内容为空或过短")
