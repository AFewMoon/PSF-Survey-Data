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


def _fingerprint_reject(
    src: str, dst: str, fingerprints: dict[str, dict[str, Any]]
) -> str:
    """取值指纹护栏：用数据本身否决「结构合法、语义错误」的组映射。"""
    if src == dst:
        return ""
    fsrc = fingerprints.get(src)
    if not fsrc:
        return ""  # 证据不足不拦，交给候选集与人工审核
    if fsrc.get("yesno_share", 0.0) >= config.YES_NO_SHARE_MAX and any(
        marker in segment
        for segment in dst.split(".")
        for marker in ("version", "release")
    ):
        return (
            f"{src}: 取值以 Yes/No 为主（{fsrc['yesno_share']:.0%}），"
            f"不能映射到版本类路径 {dst}，已保留原名"
        )
    fdst = fingerprints.get(dst)
    if not fdst:
        return ""
    kinds_src = set(fsrc.get("kinds", ()))
    kinds_dst = set(fdst.get("kinds", ()))
    if (kinds_src == {"multi_level"} and kinds_dst == {"multi_option"}) or (
        kinds_src == {"multi_option"} and kinds_dst == {"multi_level"}
    ):
        # 同一份选项清单可能来自不同题型：multi_level 是「程度网格」（primary/secondary/hobby），
        # multi_option 是「勾选集合」。两者题目不同，选项重合再高也不能合并。
        return (
            f"{src} → {dst}: 题型冲突（{next(iter(kinds_src))} vs {next(iter(kinds_dst))}），"
            "已保留原名"
        )
    if "multi_option" not in kinds_src and "multi_level" not in kinds_src:
        # 单选取值随年份变化是常态（版本号、年限区间），集合不重合不代表题目不同；
        # 只有多选题的选项文本才是稳定的「同题指纹」。
        return ""
    left = set(fsrc.get("values", []))
    right = set(fdst.get("values", []))
    if len(left) >= config.GROUP_FP_MIN_ITEMS and len(right) >= config.GROUP_FP_MIN_ITEMS:
        union = left | right
        jaccard = len(left & right) / len(union) if union else 0.0
        if jaccard < config.GROUP_FP_JACCARD_MIN:
            return (
                f"{src} → {dst}: 取值指纹 Jaccard {jaccard:.2f} 低于 "
                f"{config.GROUP_FP_JACCARD_MIN}，已保留原名"
            )
    return ""


def validate_group_map_closed(
    response: dict[str, Any],
    groups: list[str],
    candidates: list[str],
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, str], list[str]]:
    """封闭集分类：canonical 必须取自候选词表或 "keep"，并过取值指纹护栏。

    与 validate_group_map 的区别：后者只要求「非空且无空格」，模型可自造路径；
    这里把错误空间压到候选集内，越界一律回退原组名。
    """
    items = response.get("groups")
    if not isinstance(items, list):
        raise DecisionError("组路径决策缺少 groups 数组")
    allowed_src = set(groups)
    allowed_dst = set(candidates)
    fps = fingerprints or {}
    mapping: dict[str, str] = {}
    problems: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("groups 内含非对象元素")
            continue
        src = str(raw.get("name", "")).strip()
        dst = str(raw.get("canonical", "")).strip()
        if src not in allowed_src:
            problems.append(f"未知组路径：{src!r}")
            continue
        if not dst or dst == "keep":
            mapping[src] = src
            continue
        if dst not in allowed_dst:
            problems.append(f"{src}: canonical 不在候选集（{dst!r}），已保留原名")
            mapping[src] = src
            continue
        reject = _fingerprint_reject(src, dst, fps)
        if reject:
            problems.append(reject)
            mapping[src] = src
            continue
        mapping[src] = dst
    return mapping, problems


def guard_group_mapping(
    mapping: dict[str, str], fingerprints: dict[str, dict[str, Any]]
) -> tuple[dict[str, str], list[str]]:
    """对已有组映射做取值指纹兜底：不合法（证据与语义冲突）的条目回退原名。

    快对齐与封闭集命名各有一段校验，这里保证最终写进数据的映射整体再过一次，
    避免 「结构合法、语义错误」的改道（is.python.main → ide.python_version）漏网。
    """
    final: dict[str, str] = {}
    problems: list[str] = []
    for src, dst in mapping.items():
        reject = _fingerprint_reject(src, dst, fingerprints)
        if reject:
            problems.append(reject)
            final[src] = src
        else:
            final[src] = dst
    return final, problems


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


# ---------------------------------------------------------------- 逐对判断


def validate_pair_judgments(
    response: dict[str, Any], pairs: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[str]]:
    """逐对二元判断校验：id 必须存在且唯一，same=true 时 canonical 必须取自该对。

    返回 [{"group","a","b","canonical"}]，只保留判为同义的条目。
    """
    items = response.get("pairs")
    if not isinstance(items, list):
        raise DecisionError("逐对判断缺少 pairs 数组")
    by_id = {str(item["id"]): item for item in pairs}
    seen: set[str] = set()
    accepted: list[dict[str, str]] = []
    problems: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("pairs 内含非对象元素")
            continue
        pid = str(raw.get("id", "")).strip()
        if pid not in by_id:
            problems.append(f"未知候选对 id：{pid!r}")
            continue
        if pid in seen:
            problems.append(f"候选对重复判断：{pid}")
            continue
        seen.add(pid)
        if not bool(raw.get("same", False)):
            continue
        item = by_id[pid]
        canonical = str(raw.get("canonical", "")).strip()
        if canonical not in {item["a"], item["b"]}:
            problems.append(f"{pid}: canonical 必须取自该对（{canonical!r}），已忽略")
            continue
        accepted.append(
            {"group": item["group"], "a": item["a"], "b": item["b"],
             "canonical": canonical, "reason": str(raw.get("reason", ""))[:120]}
        )
    return accepted, problems


def validate_group_pairs(
    response: dict[str, Any], pairs: list[dict[str, Any]]
) -> tuple[list[dict[str, str]], list[str]]:
    """组对判断校验：same=true 时 canonical 必须是 "a"/"b"，转成实际组路径。"""
    items = response.get("pairs")
    if not isinstance(items, list):
        raise DecisionError("组对判断缺少 pairs 数组")
    by_id = {str(item["id"]): item for item in pairs}
    seen: set[str] = set()
    accepted: list[dict[str, str]] = []
    problems: list[str] = []
    for raw in items:
        if not isinstance(raw, dict):
            problems.append("pairs 内含非对象元素")
            continue
        pid = str(raw.get("id", "")).strip()
        if pid not in by_id:
            problems.append(f"未知组对 id：{pid!r}")
            continue
        if pid in seen:
            problems.append(f"组对重复判断：{pid}")
            continue
        seen.add(pid)
        if not bool(raw.get("same", False)):
            continue
        choice = str(raw.get("canonical", "")).strip().lower()
        if choice not in {"a", "b"}:
            problems.append(f"{pid}: canonical 必须为 a 或 b（{choice!r}），已忽略")
            continue
        item = by_id[pid]
        accepted.append(
            {"group": "groups", "a": item["a"], "b": item["b"],
             "canonical": item[choice], "reason": str(raw.get("reason", ""))[:120]}
        )
    return accepted, problems


def clusters_from_pairs(
    accepted: list[dict[str, str]], values: list[str], unit: str
) -> tuple[dict[str, str], list[str]]:
    """并查集聚簇：把逐对判断拼成簇，并继承塌缩护栏（≤4 项、不吞半数组）。"""
    parent: dict[str, str] = {}

    def find(key: str) -> str:
        parent.setdefault(key, key)
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left: str, right: str) -> None:
        root_l, root_r = find(left), find(right)
        if root_l != root_r:
            parent[root_r] = root_l

    edges: list[dict[str, str]] = []
    for item in accepted:
        left, right = norm_key(item["a"]), norm_key(item["b"])
        if not left or not right or left == right:
            continue
        union(left, right)
        edges.append(item)

    components: dict[str, set[str]] = {}
    for key in list(parent):
        components.setdefault(find(key), set()).add(key)

    total = len({norm_key(v) for v in values if norm_key(v)})
    mapping: dict[str, str] = {}
    problems: list[str] = []
    for members in components.values():
        if len(members) < 2:
            continue
        size = len(members)
        if size > config.MAX_CLUSTER_SIZE:
            problems.append(f"{unit}: 簇含 {size} 项，超过上限 {config.MAX_CLUSTER_SIZE}，已忽略")
            continue
        if total and size >= total:
            problems.append(f"{unit}: 簇吞并全部 {total} 个取值，判定为塌缩，已忽略")
            continue
        if total and size >= 3 and size > total * config.MAX_CLUSTER_SHARE:
            problems.append(
                f"{unit}: 簇含 {size}/{total} 个取值，超过安全上限，已忽略"
            )
            continue
        votes: dict[str, int] = {}
        for item in edges:
            if norm_key(item["a"]) in members and norm_key(item["b"]) in members:
                votes[item["canonical"]] = votes.get(item["canonical"], 0) + 1
        canonical = max(votes, key=lambda text: (votes[text], len(text))) if votes else ""
        if not canonical:
            continue
        for member in members:
            mapping[member] = canonical
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
