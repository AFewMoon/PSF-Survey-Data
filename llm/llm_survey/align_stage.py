"""对齐阶段：模型统一跨年组路径、选项写法与单选取值，Python 执行重命名与合并。

输入：llm/cleaned/cleaned_llm_<year>.csv + llm/decisions/clean/<year>.columns.json
输出：llm/aligned/cleaned_aligned_llm_<year>.csv、survey_2019_2024_master_llm.csv、
      column_mapping.csv、value_mapping.csv、reports/alignment_report.md
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from . import config, decision_schema, fewshot, prompts, reporting
from .cache import CacheStore
from .dataio import read_cleaned, read_json, write_csv, write_json
from .ollama_client import ChatMeta, OllamaClient
from .textnorm import dedup_names, norm_key, norm_text


@dataclass
class AlignResult:
    per_year_cols: dict[int, int] = field(default_factory=dict)
    common_cols: list[str] = field(default_factory=list)
    renames: int = 0
    value_changes: int = 0
    dup_cols: int = 0
    groups: int = 0
    group_merges: list[dict[str, Any]] = field(default_factory=list)
    option_clusters: int = 0
    problems: list[str] = field(default_factory=list)
    cache_lines: list[str] = field(default_factory=list)
    missing_meta: int = 0
    holdout_years: list[int] = field(default_factory=list)
    path_candidates: int = 0
    fewshot_notes: list[str] = field(default_factory=list)
    pairs_judged: int = 0
    pairs_accepted: int = 0


# ---------------------------------------------------------------- 读取


def load_column_meta(year: int) -> dict[str, dict[str, Any]]:
    """读取清洗阶段写下的列决策（新列名 -> 语义）。"""
    path = config.CLEAN_DECISIONS_DIR / f"{year}.columns.json"
    if not path.exists():
        return {}
    payload = read_json(path)
    return {str(row["new"]): row for row in payload.get("columns", [])}


def split_name(name: str) -> tuple[str, str]:
    """无元数据时按表头拆分（多级组路径无法还原，退化为最后一段）。"""
    if "." not in name:
        return name, ""
    group, option = name.rsplit(".", 1)
    return group, option


def column_meta(df: pd.DataFrame, meta: dict[str, dict[str, Any]]) -> tuple[
    dict[str, str], dict[str, str], dict[str, str], int
]:
    """返回 (列->组, 列->选项, 列->kind, 缺元数据列数)。"""
    groups: dict[str, str] = {}
    options: dict[str, str] = {}
    kinds: dict[str, str] = {}
    missing = 0
    for col in df.columns:
        row = meta.get(col)
        if row and row.get("group"):
            groups[col] = str(row["group"])
            options[col] = str(row.get("option") or "")
            kinds[col] = str(row.get("kind") or "")
        else:
            group, option = split_name(col)
            groups[col], options[col], kinds[col] = group, option, ""
            missing += 1
    return groups, options, kinds, missing


# ---------------------------------------------------------------- 模型决策


def _chunk_by_chars(
    payload: list[dict[str, Any]], budget: int, max_items: int
) -> list[list[dict[str, Any]]]:
    """按字符预算切批：4B 模型的 8k 上下文装不下全部题目组。"""
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    size = 0
    for row in payload:
        cost = len(json.dumps(row, ensure_ascii=False)) + 2
        if current and (size + cost > budget or len(current) >= max_items):
            chunks.append(current)
            current, size = [], 0
        current.append(row)
        size += cost
    if current:
        chunks.append(current)
    return chunks


def _unify_groups(
    inventory: dict[str, dict[str, Any]], client: OllamaClient, refresh: bool,
    bundle: fewshot.FewShotBundle,
    fingerprints: dict[str, dict[str, Any]] | None = None,
) -> tuple[dict[str, str], list[str], str, int, int, int]:
    """跨年组路径统一，三段式（证据 → 判定 → 命名）：

    1. **快对齐（不问模型）**：`norm_key` 命中人工词表、或多选选项 Jaccard ≥ GROUP_SNAP_STRONG，
       直接定案。人工对齐靠维护同义词表，这里用「人工词表 + 选项证据」替代。
    2. **判定**：只有证据处于 [WEAK, STRONG) 的组对交模型做「是否同一道题」的二元判断。
    3. **命名**：仍未对齐的组，从封闭候选词表里选标准写法，缺省 keep。

    理由：让 4B「自由选择标准路径」时它习惯性输出 keep（实测 164 组仅 1 处改动）；
    而「两组选项重合 70%，是否同题」是它能稳定判定的分类任务。合并关系由数据与词表决定，
    模型只处理两边都不确定的边界，且始终没有机会自造路径。
    """
    names = sorted(inventory)
    problems: list[str] = []
    snapped, ambiguous = fewshot.match_groups(inventory, bundle)

    # 第二段：证据不足的组对，逐对问模型（不外推、不批量重排）
    cache_pair = CacheStore("group_pair", client.digest, refresh=refresh)
    judges = 0
    accepted: list[dict[str, str]] = []
    snap_years: dict[str, set[int]] = {}
    for name, target in snapped.items():
        snap_years.setdefault(target, set()).update(inventory[name]["years"])
    for batch in _chunk_pairs(ambiguous, config.BATCH_CHAR_BUDGET, config.PAIR_BATCH_SIZE):
        payload = [
            {
                "id": f"p{i + 1}",
                "a": name,
                "b": target,
                "a_years": sorted(inventory[name]["years"]),
                "b_years": sorted(snap_years.get(target, set())),
                "a_sample": inventory[name]["sample"][:5],
                "b_sample": list(bundle.vocab_options.get(target, ()))[:5],
            }
            for i, (name, target) in enumerate(batch)
        ]
        system, user = prompts.group_pair_messages(payload)
        key = cache_pair.key(
            {"pairs": [list(p) for p in batch], "holdout": sorted(bundle.holdout_years)},
            config.PROMPT_VERSION["group_pair"],
        )
        judges += len(batch)

        def call(sys_msg=system, usr_msg=user,
                 n=len(batch)) -> tuple[dict[str, Any], ChatMeta]:
            return client.chat_json(sys_msg, usr_msg, num_predict=max(500, n * 70),
                                    tag="group-pair")

        response, _, _ = cache_pair.get_or_call(
            key, config.PROMPT_VERSION["group_pair"], {"n_pairs": len(batch)}, call,
            fallback=lambda: {"pairs": []},
        )
        ok, chunk_problems = decision_schema.validate_group_pairs(response, payload)
        problems += chunk_problems
        accepted += ok

    cluster_map, cluster_problems = decision_schema.clusters_from_pairs(
        accepted, names + [target for _name, target in ambiguous], "groups")
    problems += cluster_problems
    merged = {name: cluster_map.get(norm_key(name), snapped.get(name, name)) for name in names}

    # 第三段：封闭候选词表命名，只处理「快对齐与判定都没定案」的组
    vocab = set(bundle.path_vocab)
    pending = sorted({target for target in merged.values() if target not in vocab})
    candidates = fewshot.build_path_candidates(bundle, []) if pending else []
    cache_name = CacheStore("group_path", client.digest, refresh=refresh)
    renamed: dict[str, str] = {}
    if pending:
        payload = [
            {
                "name": name,
                "years": sorted({y for src, dst in merged.items() if dst == name
                                 for y in inventory[src]["years"]}),
                "n_options": sum(inventory[src]["n_options"] for src, dst in merged.items()
                                 if dst == name),
                "sample": sorted({opt for src, dst in merged.items() if dst == name
                                  for opt in inventory[src]["sample"]})[:6],
            }
            for name in pending
        ]
        for chunk in _chunk_by_chars(payload, config.BATCH_CHAR_BUDGET, 40):
            chunk_names = [row["name"] for row in chunk]
            shortlist = fewshot.path_shortlist(candidates, chunk_names)
            shortlist = fewshot.filter_candidates(shortlist, chunk_names, inventory)
            system, user = prompts.group_messages(
                chunk, shortlist, list(bundle.path_examples), list(bundle.value_examples)
            )
            key = cache_name.key(
                {"groups": chunk_names, "candidates": shortlist, "mode": "closed",
                 "holdout": sorted(bundle.holdout_years)},
                config.PROMPT_VERSION["group_path"],
            )

            def call(sys_msg=system, usr_msg=user,
                     n=len(chunk_names)) -> tuple[dict[str, Any], ChatMeta]:
                return client.chat_json(sys_msg, usr_msg, num_predict=max(600, n * 32),
                                        tag="group-path")

            response, _, _ = cache_name.get_or_call(
                key, config.PROMPT_VERSION["group_path"],
                {"n_groups": len(chunk_names), "n_candidates": len(shortlist)}, call,
                fallback=lambda: {"groups": []},
            )
            chunk_map, chunk_problems = decision_schema.validate_group_map_closed(
                response, chunk_names, shortlist, fingerprints
            )
            problems += chunk_problems
            for src, dst in chunk_map.items():
                if dst == src:
                    continue
                options = tuple(inventory.get(src, {}).get("options", ()))
                if not fewshot.compatible_target(src, options, dst):
                    problems.append(
                        f"{src} → {dst}: 目标路径会与本组选项重复拼接，已保留原名"
                    )
                    continue
                renamed[src] = dst

    final = {
        name: (target if target in vocab else renamed.get(target, target))
        for name, target in merged.items()
    }
    # 兜底护栏：整条映射再过一遍取值指纹（防止快对齐/命名绕开语义检查）
    final, guard_problems = decision_schema.guard_group_mapping(final, fingerprints or {})
    problems += guard_problems
    cache_line = cache_pair.report()
    if pending:
        cache_line += f"；{cache_name.report()}"
    return final, problems, cache_line, len(candidates), judges, len(accepted)


def _chunk_pairs(
    pairs: list[tuple[str, str]],
    budget: int = config.BATCH_CHAR_BUDGET,
    max_items: int = config.PAIR_BATCH_SIZE,
) -> list[list[tuple[str, str]]]:
    """候选对切批：控制单次请求的对数与字符量。"""
    chunks: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    size = 0
    for left, right in pairs:
        cost = len(left) + len(right) + 24
        if current and (size + cost > budget or len(current) >= max_items):
            chunks.append(current)
            current, size = [], 0
        current.append((left, right))
        size += cost
    if current:
        chunks.append(current)
    return chunks


def _dedup_units(
    values: list[str], counts: dict[tuple[str, str], int] | None = None, unit: str = ""
) -> tuple[list[str], dict[str, str]]:
    """确定性第一段：`norm_key` 相同的写法先合并（大小写/标点/空白），返回代表值与本段映射。"""
    by_key: dict[str, list[str]] = {}
    for value in values:
        key = norm_key(value)
        if key:
            by_key.setdefault(key, []).append(value)
    reps: list[str] = []
    mapping: dict[str, str] = {}
    for key, group in by_key.items():
        canonical = max(
            group,
            key=lambda v: ((counts or {}).get((unit, v), 0), len(v), v),
        )
        reps.append(canonical)
        for value in group:
            mapping[key] = canonical
    return sorted(reps), mapping


def _judge_units(
    units: dict[str, list[str]], client: OllamaClient, refresh: bool, kind: str,
    counts: dict[tuple[str, str], int] | None = None,
) -> tuple[dict[str, dict[str, str]], int, int, int, list[str], str]:
    """两段式归并：确定性 norm_key 合并 → 候选对逐对判断 → 并查集聚簇。

    返回 ({单元: {norm_key: 标准文本}}, 簇数, 判定对数, 接受对数, problems, 缓存行)。
    逐对判断替代整组开放聚类：4B 只会整列塌缩，但判断「两个文本是否同义」是可靠分类任务。
    """
    cache = CacheStore("pair_judge", client.digest, refresh=refresh)
    merged: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    clusters = 0
    judged = 0
    accepted_n = 0
    for unit, values in units.items():
        reps, det_map = _dedup_units(values, counts, unit)
        pairs = fewshot.candidate_pairs(reps)
        cluster_map: dict[str, str] = {}
        if pairs:
            accepted: list[dict[str, str]] = []
            for batch in _chunk_pairs(pairs):
                payload = [
                    {"id": f"p{i + 1}", "group": unit, "a": left, "b": right}
                    for i, (left, right) in enumerate(batch)
                ]
                system, user = prompts.pair_judge_messages(payload)
                key = cache.key(
                    {"unit": unit, "kind": kind, "pairs": [list(p) for p in batch]},
                    config.PROMPT_VERSION["pair_judge"],
                )
                judged += len(batch)

                def call(sys_msg=system, usr_msg=user,
                         n=len(batch)) -> tuple[dict[str, Any], ChatMeta]:
                    return client.chat_json(sys_msg, usr_msg, num_predict=max(400, n * 60),
                                            tag=f"pair-{kind}")

                response, _, _ = cache.get_or_call(
                    key, config.PROMPT_VERSION["pair_judge"],
                    {"unit": unit, "n_pairs": len(batch)}, call,
                    fallback=lambda: {"pairs": []},
                )
                ok, chunk_problems = decision_schema.validate_pair_judgments(response, payload)
                problems += chunk_problems
                accepted += ok
            accepted_n += len(accepted)
            cluster_map, cluster_problems = decision_schema.clusters_from_pairs(
                accepted, reps, unit
            )
            problems += cluster_problems
            clusters += len(set(cluster_map.values()))
        final: dict[str, str] = {}
        for key, det_canon in det_map.items():
            target = cluster_map.get(norm_key(det_canon), det_canon)
            final[key] = cluster_map.get(key, target)
        if final:
            merged[unit] = final
    return merged, clusters, judged, accepted_n, problems, cache.report()


def dry_run_group_map(inventory: dict[str, dict[str, Any]]) -> dict[str, str]:
    """离线：仅按归一键合并同名组（不调模型）。"""
    by_key: dict[str, str] = {}
    for name in sorted(inventory):
        by_key.setdefault(norm_key(name), name)
    return {name: by_key[norm_key(name)] for name in inventory}


def build_fingerprints(
    years: list[int],
    dfs: dict[int, pd.DataFrame],
    group_by_year: dict[int, dict[str, str]],
    kind_by_year: dict[int, dict[str, str]],
    inventory: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """组级取值指纹：多选题用选项名，单选题用单元格 top 值，另记 Yes/No 占比。

    用途：组映射合并前后指纹应当相似；指纹完全不重合说明「名字像、内容不像」，
    这正是 `is.python.main → ide.python_version` 类错误的可检测信号。
    """
    acc: dict[str, dict[str, Any]] = {}
    for year in years:
        df = dfs[year]
        for col, group in group_by_year[year].items():
            if kind_by_year[year].get(col) != "single_choice":
                continue
            series = df[col]
            if series.dtype.kind in "biuf":
                continue
            texts = series.map(lambda v: str(v).strip())
            texts = texts[texts != ""]
            if texts.empty:
                continue
            counts = texts.value_counts()
            entry = acc.setdefault(group, {"values": {}, "yesno": 0, "total": 0})
            for text, count in counts.head(5).items():
                key = norm_key(str(text))
                if key:
                    entry["values"][key] = entry["values"].get(key, 0) + int(count)
            entry["total"] += int(counts.sum())
            entry["yesno"] += int(
                sum(c for t, c in counts.items() if norm_key(str(t)).startswith(("yes", "no")))
            )
    for name, entry in inventory.items():
        values: dict[str, int] = {}
        for option in entry.get("options", ()):
            key = norm_key(option)
            if key:
                values[key] = values.get(key, 0) + 1
        merged = acc.setdefault(name, {"values": {}, "yesno": 0, "total": 0})
        for key, count in values.items():
            merged["values"][key] = merged["values"].get(key, 0) + count
    kind_acc: dict[str, set[str]] = {}
    for year in years:
        for col, group in group_by_year[year].items():
            kind = kind_by_year[year].get(col) or ""
            if kind:
                kind_acc.setdefault(group, set()).add(kind)
    fingerprints: dict[str, dict[str, Any]] = {}
    for name, entry in acc.items():
        total = int(entry["total"])
        top = sorted(entry["values"].items(), key=lambda kv: (-kv[1], kv[0]))[:8]
        fingerprints[name] = {
            "values": [key for key, _count in top],
            "yesno_share": (entry["yesno"] / total) if total else 0.0,
            "kinds": sorted(kind_acc.get(name, ())),
        }
    return fingerprints


# ---------------------------------------------------------------- 主流程


def run(years: list[int], client: OllamaClient | None, refresh: bool,
        dry_run: bool = False, holdout_years: set[int] | None = None) -> AlignResult:
    result = AlignResult()
    bundle = fewshot.load_manual_mappings(holdout_years)
    result.holdout_years = sorted(bundle.holdout_years)
    result.fewshot_notes = list(bundle.notes)
    dfs: dict[int, pd.DataFrame] = {}
    metas: dict[int, dict[str, dict[str, Any]]] = {}
    group_by_year: dict[int, dict[str, str]] = {}
    option_by_year: dict[int, dict[str, str]] = {}
    kind_by_year: dict[int, dict[str, str]] = {}

    for year in years:
        df = read_cleaned(year)
        meta = load_column_meta(year)
        groups, options, kinds, missing = column_meta(df, meta)
        result.missing_meta += missing
        dfs[year] = df
        metas[year] = meta
        group_by_year[year] = groups
        option_by_year[year] = options
        kind_by_year[year] = kinds

    # ---- 1. 组路径统一 ----
    inventory: dict[str, dict[str, Any]] = {}
    for year in years:
        for col, group in group_by_year[year].items():
            entry = inventory.setdefault(group, {"years": set(), "options": set()})
            entry["years"].add(year)
            option = option_by_year[year].get(col, "")
            if option:
                entry["options"].add(option)
    for entry in inventory.values():
        entry["n_options"] = len(entry["options"])
        entry["sample"] = sorted(entry["options"])[:5]
    result.groups = len(inventory)

    if dry_run or client is None:
        group_map = dry_run_group_map(inventory)
        result.cache_lines.append("group_path: 离线模式（归一键合并）")
    else:
        fingerprints = build_fingerprints(
            years, dfs, group_by_year, kind_by_year, inventory
        )
        group_map, problems, cache_line, n_candidates, judged, accepted = _unify_groups(
            inventory, client, refresh, bundle, fingerprints
        )
        result.path_candidates = n_candidates
        result.pairs_judged += judged
        result.pairs_accepted += accepted
        result.problems += problems
        result.cache_lines.append(cache_line)
    result.group_merges = [
        {"from": name, "to": target, "years": sorted(inventory[name]["years"])}
        for name, target in sorted(group_map.items()) if name != target
    ]

    # ---- 2. 选项文本统一（多选列名） ----
    canon_group_by_year: dict[int, dict[str, str]] = {
        year: {col: group_map.get(g, g) for col, g in group_by_year[year].items()}
        for year in years
    }
    option_units: dict[str, list[str]] = {}
    for year in years:
        for col, canon_group in canon_group_by_year[year].items():
            option = option_by_year[year].get(col, "")
            if option:
                option_units.setdefault(canon_group, []).append(option)
    option_units = {g: sorted(set(vals)) for g, vals in option_units.items()}
    option_units = {g: v for g, v in option_units.items() if len(v) > 1}

    if dry_run or client is None:
        option_clusters: dict[str, dict[str, str]] = {}
        result.cache_lines.append("pair_judge: 离线模式（只做归一键合并）")
    else:
        option_clusters, n_clusters, judged, accepted, problems, cache_line = _judge_units(
            option_units, client, refresh, "option")
        result.option_clusters = n_clusters
        result.pairs_judged += judged
        result.pairs_accepted += accepted
        result.problems += problems
        result.cache_lines.append(cache_line)

    # 选项写法对齐人工词表（闭集）：模型只判同义，写哪个用哪个人工词表说了算
    option_final: dict[str, dict[str, str]] = {}
    for group, values in option_units.items():
        option_final[group] = fewshot.snap_option_names(
            group, values, bundle, option_clusters.get(group, {})
        )
    snapped_options = sum(
        1 for group, mapping in option_final.items()
        for key, text in mapping.items()
        if text != option_clusters.get(group, {}).get(key, "")
    )
    if snapped_options:
        result.cache_lines.append(f"option_vocab: 按人工词表统一写法 {snapped_options} 处")

    # ---- 3. 重命名 ----
    col_map_rows: list[dict[str, Any]] = []
    aligned: dict[int, pd.DataFrame] = {}
    kind_by_new: dict[int, dict[str, str]] = {}
    meta_by_new: dict[int, dict[str, dict[str, str]]] = {year: {} for year in years}
    for year in years:
        proposed: list[str] = []
        for col in dfs[year].columns:
            group = canon_group_by_year[year][col]
            option = option_by_year[year].get(col, "")
            if option:
                canon_option = option_final.get(group, {}).get(
                    norm_key(option), norm_text(option))
                proposed.append(f"{group}.{canon_option}")
            else:
                proposed.append(group or col)
        # 冲突回退：模型归并若造成同年撞名，回退到确定性归一文本（避免 __dup 掩盖误并）
        if len(set(proposed)) < len(proposed):
            result.problems.append(
                f"{year} 年模型归并导致 {len(proposed) - len(set(proposed))} 处同名冲突，已回退确定性归一"
            )
            proposed = [
                f"{canon_group_by_year[year][col]}.{norm_text(option_by_year[year].get(col) or '')}"
                if option_by_year[year].get(col)
                else (canon_group_by_year[year][col] or col)
                for col in dfs[year].columns
            ]
        final = dedup_names(proposed)
        renames = dict(zip(dfs[year].columns, final))
        aligned[year] = dfs[year].rename(columns=renames)
        kind_by_new[year] = {
            renames[col]: kind_by_year[year].get(col, "") for col in renames
        }
        for col in dfs[year].columns:
            canon_group = canon_group_by_year[year][col]
            option = option_by_year[year].get(col, "")
            canon_option = ""
            if option:
                canon_option = option_final.get(canon_group, {}).get(
                    norm_key(option), norm_text(option))
            meta_by_new[year][renames[col]] = {
                "kind": kind_by_year[year].get(col, ""),
                "group": canon_group,
                "option": canon_option,
            }
        result.renames += sum(1 for a, b in renames.items() if a != b)
        result.dup_cols += sum(1 for name in final if "__dup" in name)
        for original, new in renames.items():
            if original != new:
                col_map_rows.append({
                    "year": year,
                    "original": original,
                    "canonical": new,
                    "level": "normalized" if norm_key(original) == norm_key(new) else "llm",
                })
        result.per_year_cols[year] = aligned[year].shape[1]

    # ---- 4. 单选取值统一 ----
    value_units: dict[str, set[str]] = {}
    value_counts: dict[tuple[str, str], int] = {}
    for year in years:
        for col in aligned[year].columns:
            if kind_by_new[year].get(col, "") != "single_choice":
                continue
            s = aligned[year][col]
            if s.dtype.kind in "biuf" or s.nunique(dropna=False) > 60:
                continue
            texts = s.map(lambda v: str(v).strip())
            texts = texts[texts != ""]
            for text, count in texts.value_counts().items():
                value_units.setdefault(col, set()).add(str(text))
                key = (col, str(text))
                value_counts[key] = value_counts.get(key, 0) + int(count)
    value_units = {c: sorted(v) for c, v in value_units.items() if len(v) > 1}

    if dry_run or client is None:
        value_clusters: dict[str, dict[str, str]] = {}
    else:
        value_clusters, _, judged, accepted, problems, cache_line = _judge_units(
            value_units, client, refresh, "value", counts=value_counts)
        result.pairs_judged += judged
        result.pairs_accepted += accepted
        result.problems += problems
        result.cache_lines.append(f"{cache_line}（取值）")

    value_rows: list[dict[str, Any]] = []
    for year in years:
        df = aligned[year].copy()
        for col in df.columns:
            mapping = value_clusters.get(col)
            if not mapping:
                continue
            s = df[col]
            if s.dtype.kind in "biuf":
                continue
            converted = s.map(lambda v, m=mapping: _canon_value(v, m))
            changed = converted != s
            if changed.any():
                value_rows += [
                    {"year": year, "column": col, "original": str(old), "canonical": str(new)}
                    for old, new in zip(s[changed], converted[changed])
                ][:500]
                df[col] = converted
        aligned[year] = df
    result.value_changes = len(value_rows)

    # ---- 5. 输出 ----
    common = sorted(set.intersection(*(set(aligned[y].columns) for y in years)))
    result.common_cols = common
    for year in years:
        write_csv(aligned[year], config.ALIGNED_DIR / f"cleaned_aligned_llm_{year}.csv")
    master = pd.concat(
        [aligned[y].assign(year=y)[["year"] + common] for y in years], ignore_index=True
    )
    write_csv(master, config.ALIGNED_DIR / f"survey_{years[0]}_{years[-1]}_master_llm.csv")
    write_csv(pd.DataFrame(col_map_rows, columns=["year", "original", "canonical", "level"]),
              config.ALIGNED_DIR / "column_mapping.csv")
    write_csv(pd.DataFrame(value_rows, columns=["year", "column", "original", "canonical"]),
              config.ALIGNED_DIR / "value_mapping.csv")
    # 下游统计/核对需要的列语义（对齐后的列名 -> kind/group/option）
    write_json(
        config.ALIGNED_DIR / "columns_llm.json",
        {str(year): meta_by_new[year] for year in years},
    )

    write_report(result, years, len(master), col_map_rows, value_rows)
    return result


def _canon_value(value: Any, mapping: dict[str, str]) -> str:
    text = str(value).strip()
    if not text:
        return text
    return mapping.get(norm_key(text), text)


def write_report(result: AlignResult, years: list[int], master_rows: int,
                 col_rows: list[dict[str, Any]], value_rows: list[dict[str, Any]]) -> None:
    lines = ["# LLM 驱动跨年对齐报告", "", f"生成时间：{reporting.now_str()}", ""]
    lines.append(
        f"模型：`{config.MODEL}`（temperature={config.TEMPERATURE}, seed={config.SEED}）｜"
        "管线：组路径快对齐 → 逐对判同题 → 闭集命名 → 重命名 → 候选对归并选项/取值 → 共有列纵向合并"
    )
    lines += ["", "## 对齐统计", ""]
    lines.append(f"- 跨年共有列：{len(result.common_cols)}")
    lines.append(f"- 题目组：{result.groups} 个（其中 {len(result.group_merges)} 个被映射到其他标准路径）")
    lines.append(f"- 封闭候选路径：{result.path_candidates} 个")
    lines.append(f"- 列名重命名：{result.renames}")
    lines.append(f"- 选项同义簇：{result.option_clusters}")
    lines.append(f"- 候选对判定：{result.pairs_judged} 对（接受 {result.pairs_accepted} 对）")
    lines.append(f"- 取值统一记录：{result.value_changes}")
    lines.append(f"- `__dup` 冲突列：{result.dup_cols}")
    lines.append(f"- 总表行数：{master_rows}")
    if result.missing_meta:
        lines.append(f"- 缺少清洗阶段元数据的列：{result.missing_meta}（按表头结构退化处理）")

    lines += ["", "## Few-shot 与评测口径", ""]
    lines.append(
        f"- 留出年份：{','.join(str(y) for y in result.holdout_years) or '无'}"
        "（这些年份的人工映射**不进入**提示词，仅用于对账）"
    )
    lines += [f"- {note}" for note in result.fewshot_notes]

    lines += ["", "## 各年列数", "", reporting.md_table(
        ["年份", "对齐后列数", "进入总表的列数"],
        [[y, result.per_year_cols.get(y, 0), len(result.common_cols)] for y in years],
    )]

    if result.group_merges:
        lines += ["", "## 模型判定的组路径统一（部分）", "", reporting.md_table(
            ["原路径", "标准路径", "涉及年份"],
            [[m["from"], m["to"], ",".join(str(y) for y in m["years"])]
             for m in result.group_merges[:30]],
        )]
        if len(result.group_merges) > 30:
            lines.append(f"\n（共 {len(result.group_merges)} 条，仅列出前 30 条）")

    if col_rows:
        lines += ["", "## 列名重命名示例（每年 8 条）", ""]
        for year in years:
            sample = [r for r in col_rows if r["year"] == year][:8]
            if not sample:
                continue
            lines.append(f"**{year}**")
            lines += [f"- `{r['original']}` -> `{r['canonical']}`（{r['level']}）" for r in sample]
            lines.append("")

    if value_rows:
        lines += ["", "## 取值统一示例", ""]
        lines += [f"- {r['year']} `{r['column']}`：`{r['original']}` -> `{r['canonical']}`"
                  for r in value_rows[:15]]
    else:
        lines += [
            "", "## 取值统一", "",
            "本轮没有产生单选取值统一：",
            "- 确定性部分只合并 `norm_key` 完全相同（仅大小写/标点/空白差异）的取值；"
            "清洗阶段已做单元格归一，剩余变体为零",
            "- 候选对（difflib 相似度 / 缩写一致 / 词元包含）未命中任何可合并的取值，"
            "或模型判定全部不同义；拒绝记录见「校验提示」",
        ]

    if result.problems:
        lines += ["", "## 校验提示", "", reporting.md_list(result.problems[:30])]
        if len(result.problems) > 30:
            lines.append(f"- …… 另有 {len(result.problems) - 30} 条")

    lines += ["", "## 缓存", "", reporting.md_list(result.cache_lines), ""]
    lines += ["", "## 产出", "",
              "- `llm/aligned/cleaned_aligned_llm_<year>.csv`",
              f"- `llm/aligned/survey_{years[0]}_{years[-1]}_master_llm.csv`",
              "- `llm/aligned/column_mapping.csv`、`llm/aligned/value_mapping.csv`", ""]
    (config.REPORTS_DIR / "alignment_report.md").write_text("\n".join(lines), encoding="utf-8")
