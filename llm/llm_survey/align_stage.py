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

from . import config, decision_schema, prompts, reporting
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
    inventory: dict[str, dict[str, Any]], client: OllamaClient, refresh: bool
) -> tuple[dict[str, str], list[str], str]:
    """跨年组路径统一：模型给出每个组的标准路径（分批请求后合并）。"""
    names = sorted(inventory)
    payload = [
        {
            "name": name,
            "years": sorted(inventory[name]["years"]),
            "n_options": inventory[name]["n_options"],
            "sample": inventory[name]["sample"][:3],
        }
        for name in names
    ]
    cache = CacheStore("group_path", client.digest, refresh=refresh)
    mapping: dict[str, str] = {}
    problems: list[str] = []
    for chunk in _chunk_by_chars(payload, config.BATCH_CHAR_BUDGET, 60):
        chunk_names = [row["name"] for row in chunk]
        system, user = prompts.group_messages(chunk)
        key = cache.key({"groups": chunk_names}, config.PROMPT_VERSION["group_path"])

        def call(sys_msg=system, usr_msg=user, n=len(chunk_names)) -> tuple[dict[str, Any], ChatMeta]:
            return client.chat_json(sys_msg, usr_msg, num_predict=max(600, n * 32),
                                    tag="group-path")

        response, _, _ = cache.get_or_call(
            key, config.PROMPT_VERSION["group_path"], {"n_groups": len(chunk_names)}, call,
            fallback=lambda: {"groups": []},
        )
        chunk_map, chunk_problems = decision_schema.validate_group_map(response, chunk_names)
        problems += chunk_problems
        for name in chunk_names:
            target = chunk_map.get(name, name)
            if name in mapping and mapping[name] != target:
                problems.append(
                    f"组路径映射冲突：{name} -> {mapping[name]} / {target}，保留首个"
                )
                continue
            mapping[name] = target
    for name in names:
        mapping.setdefault(name, name)
    return mapping, problems, cache.report()


def _chunk_units(
    units: dict[str, list[str]], budget: int, max_units: int
) -> list[dict[str, list[str]]]:
    """按字符预算切批（同一批内才可能被模型判为同义）。"""
    chunks: list[dict[str, list[str]]] = []
    current: dict[str, list[str]] = {}
    size = 0
    for name, values in units.items():
        if not values:
            continue
        cost = len(name) + sum(len(v) + 4 for v in values)
        if current and (size + cost > budget or len(current) >= max_units):
            chunks.append(current)
            current, size = {}, 0
        current[name] = values
        size += cost
    if current:
        chunks.append(current)
    return chunks


def _cluster_units(
    units: dict[str, list[str]], client: OllamaClient, refresh: bool, stage: str,
    batch_units: int = 10,
) -> tuple[dict[str, dict[str, str]], int, list[str], str]:
    """批量聚类（多选选项文本 / 单选取值），返回 ({组: {norm_key: 标准文本}}, 簇数, problems, 缓存行)。"""
    cache = CacheStore(stage, client.digest, refresh=refresh)
    merged: dict[str, dict[str, str]] = {}
    problems: list[str] = []
    clusters = 0
    for chunk_units in _chunk_units(units, config.BATCH_CHAR_BUDGET, batch_units):
        chunk = list(chunk_units)
        system, user = prompts.cluster_messages(chunk_units)
        key = cache.key({"units": chunk_units}, config.PROMPT_VERSION["option_alias"])
        size = sum(len(v) for v in chunk_units.values())

        def call(units_chunk=chunk_units, sys_msg=system, usr_msg=user,
                 n=size) -> tuple[dict[str, Any], ChatMeta]:
            return client.chat_json(sys_msg, usr_msg, num_predict=max(700, n * 55),
                                    tag=f"cluster-{stage}")

        response, _, _ = cache.get_or_call(
            key, config.PROMPT_VERSION["option_alias"],
            {"groups": len(chunk), "values": size}, call,
            fallback=lambda: {"groups": []},
        )
        mapping, chunk_problems = decision_schema.validate_cluster_batch(response, chunk_units)
        problems += chunk_problems
        for name, value_map in mapping.items():
            merged[name] = value_map
            clusters += len({v for v in value_map.values()})
    return merged, clusters, problems, cache.report()


def dry_run_group_map(inventory: dict[str, dict[str, Any]]) -> dict[str, str]:
    """离线：仅按归一键合并同名组（不调模型）。"""
    by_key: dict[str, str] = {}
    for name in sorted(inventory):
        by_key.setdefault(norm_key(name), name)
    return {name: by_key[norm_key(name)] for name in inventory}


# ---------------------------------------------------------------- 主流程


def run(years: list[int], client: OllamaClient | None, refresh: bool,
        dry_run: bool = False) -> AlignResult:
    result = AlignResult()
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
        group_map, problems, cache_line = _unify_groups(inventory, client, refresh)
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
        result.cache_lines.append("option_alias: 离线模式（不做同义归并）")
    else:
        option_clusters, n_clusters, problems, cache_line = _cluster_units(
            option_units, client, refresh, "option_alias", batch_units=8)
        result.option_clusters = n_clusters
        result.problems += problems
        result.cache_lines.append(cache_line)

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
                canon_option = option_clusters.get(group, {}).get(norm_key(option), norm_text(option))
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
                canon_option = option_clusters.get(canon_group, {}).get(
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
        model_value_clusters, _, problems, cache_line = _cluster_units(
            value_units, client, refresh, "option_alias", batch_units=10)
        result.problems += problems
        result.cache_lines.append(f"{cache_line}（取值）")
        value_clusters = _merge_value_maps(value_units, value_counts, model_value_clusters)

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


def _related(a: str, b: str) -> bool:
    """两个 norm_key 是否「同一实体的不同写法」：互相包含即视为相关。"""
    if not a or not b or a == b:
        return False
    return a in b or b in a


def _merge_value_maps(
    units: dict[str, list[str]],
    counts: dict[tuple[str, str], int],
    model_clusters: dict[str, dict[str, str]],
) -> dict[str, dict[str, str]]:
    """合并单选取值：确定性归一（大小写/标点/空白）打底，模型建议只在文本相关时采纳。

    4B 模型在单选取值上倾向「整列塌缩」（把 24 个取值并成一个），此处用文本相关性把
    建议裁剪到安全范围内，宁可少合并也不误合并。
    """
    merged: dict[str, dict[str, str]] = {}
    for col, values in units.items():
        mapping: dict[str, str] = {}
        by_key: dict[str, list[str]] = {}
        for value in values:
            by_key.setdefault(norm_key(value), []).append(value)
        for key, group in by_key.items():
            if len(group) < 2:
                continue
            canonical = max(group, key=lambda v: (counts.get((col, v), 0), len(v)))
            for value in group:
                mapping[norm_key(value)] = canonical
        for key, canonical in (model_clusters.get(col) or {}).items():
            if key in mapping or key == norm_key(canonical):
                continue
            if not _related(key, norm_key(canonical)):
                continue
            mapping[key] = canonical
        if mapping:
            merged[col] = mapping
    return merged


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
        "管线：模型统一组路径 → 模型归并选项写法 → 重命名 → 模型归并单选取值 → 共有列纵向合并"
    )
    lines += ["", "## 对齐统计", ""]
    lines.append(f"- 跨年共有列：{len(result.common_cols)}")
    lines.append(f"- 题目组：{result.groups} 个（其中 {len(result.group_merges)} 个被模型映射到其他标准路径）")
    lines.append(f"- 列名重命名：{result.renames}")
    lines.append(f"- 选项同义簇：{result.option_clusters}")
    lines.append(f"- 取值统一记录：{result.value_changes}")
    lines.append(f"- `__dup` 冲突列：{result.dup_cols}")
    lines.append(f"- 总表行数：{master_rows}")
    if result.missing_meta:
        lines.append(f"- 缺少清洗阶段元数据的列：{result.missing_meta}（按表头结构退化处理）")

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
            "- 4B 模型的取值归并建议普遍是「整列塌缩」（把该列全部取值并成一个），"
            "被 `validate_cluster_batch` 的塌缩护栏全部拒绝，拒绝记录见「校验提示」",
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
