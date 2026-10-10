# -*- coding: utf-8 -*-
"""PSF Survey 跨年数据对齐管线（2019-2023）。

读取 cleaned/cleaned_<year>.csv，输出 aligned/ 目录：
  - cleaned_aligned_<year>.csv   列名/取值统一后的分年文件
  - survey_2019_2023_master.csv  跨年共有列纵向合并总表（含 year 列）
  - column_mapping.csv           列名映射表
  - value_mapping.csv            取值映射表
  - alignment_report.md          对齐报告

对齐级别：
  exact       列名精确相同
  normalized  文本归一（大小写/引号/连字符/括号附注）后相同
"""
from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
IN_DIR = ROOT / "cleaned"
OUT_DIR = ROOT / "aligned"
YEARS = [2019, 2020, 2021, 2022, 2023]  # 取标准值时旧->新，新年份优先

# ---------------------------------------------------------------- 归一工具

PUNCT_TRANS = {
    "\u2019": "'", "\u2018": "'", "\u2013": "-", "\u2014": "-",
    "\u2026": "...", "\u00a0": " ", "\u201c": '"', "\u201d": '"',
}


def norm_text(text: str) -> str:
    """用于匹配的归一文本：统一标点、压缩空白、去尾部括号附注与冒号。"""
    s = str(text)
    for k, v in PUNCT_TRANS.items():
        s = s.replace(k, v)
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)
    s = re.sub(r"\s+", " ", s).strip().rstrip(":").strip()
    return s


def norm_key(text: str) -> str:
    """匹配键：归一 + 小写 + 去所有非字母数字字符。"""
    return re.sub(r"[^0-9a-z]+", "", norm_text(text).lower())


# ---------------------------------------------------------------- 语义映射表

# 2019 括号组 slug -> 标准组路径
GROUP_REMAP_2019: dict[str, str] = {
    "what_editors_ides_do_you_use_for_python_development_in_addit": "ide.editor",
    "what_do_you_use_python_for": "other.purposes",
    "which_of_the_following_frameworks_libraries_do_you_use_in_ad": "frameworks.ml",
    "what_do_you_typically_use_to_upgrade_your_python_version": "python.version.upgrade",
    "which_of_the_following_best_describes_your_job_role_s": "job.role",
    "what_web_frameworks_libraries_do_you_use_in_addition_to_pyth": "web.frameworks",
    "which_of_the_following_cloud_platforms_do_you_use": "cloud.platform",
    "which_of_the_following_big_data_tool_s_do_you_use_if_any": "bigdata",
    "which_continuous_integration_ci_system_s_do_you_regularly_us": "ci",
    "which_python_unit_testing_framework_s_do_you_use_if_any": "unittesting",
    "what_orm_s_do_you_use_together_with_python_if_any": "orm",
    "do_you_use_any_of_the_following_tools_to_isolate_python_envi": "environments.isolate",
    "how_do_you_develop_for_the_cloud": "develop.for.cloud",
    "which_configuration_management_tools_do_you_use_if_any": "configuration.management",
    "how_do_you_run_code_in_the_cloud_in_the_production_environme": "run.in.cloud",
    "what_operating_system_s_are_your_development_environment": "devenv.os",
    "what_other_language_s_do_you_use": "other.lang",
    "what_data_science_framework_s_do_you_use_in_addition_to_pyth": "frameworks.ml",
    "which_database_s_do_you_regularly_use_if_any": "database",
}

# 跨年组路径冲突的统一标准（适用于所有年份）
GROUP_PATH_CANON: dict[str, str] = {
    "data.frameworks": "frameworks.ml",
    "isolate.environments": "environments.isolate",
}

# 2019 单列 slug -> 标准列名
SINGLE_REMAP_2019: dict[str, str] = {
    "for_what_purposes_do_you_mainly_use_python": "main.purposes",
}

# 已知多级组路径（最长优先匹配，其后剩余部分为选项）
KNOWN_GROUP_PATHS: list[str] = [
    "python.version.upgrade", "configuration.management", "environments.isolate",
    "isolate.environments", "packages.install.from", "binary.modules.creation",
    "binary.modules.language", "opensource.description", "run.in.cloud",
    "develop.for.cloud", "web.frameworks", "frameworks.ml", "cloud.platform",
    "data.frameworks", "exploration.tools", "versioning.tools", "dashboard.libraries",
    "experiment.tools", "training.platforms", "deployment.tools", "ide.editor",
    "devenv.os", "how.involved", "other.lang", "other.purposes", "python.version.most",
    "python2.version.most", "python3.version.most", "job.role", "dependency.tools",
    "libraries.tools", "learning.source", "documentation.tool", "used.tools",
    "unittesting", "configuration", "environments", "bigdata", "database",
    "frameworks", "cloud", "ide", "orm", "ci", "web", "job",
]

# 同义词表（归一键 -> 标准文本；未覆盖的变体按年份优先级自动选取）
OPTION_ALIASES: dict[str, str] = {
    "visualstudiocode": "Visual Studio Code",
    "vscode": "Visual Studio Code",
    "vscode2": "Visual Studio Code",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "pycharmprofessionaledition": "PyCharm Professional Edition",
    "pycharmprofessional": "PyCharm Professional Edition",
    "pycharmcommunityedition": "PyCharm Community Edition",
    "pycharmcommunity": "PyCharm Community Edition",
    "aws": "AWS",
    "amazonwebservices": "AWS",
    "googlecloudplatform": "Google Cloud Platform",
    "gcp": "Google Cloud Platform",
    "azure": "Microsoft Azure",
    "microsoftazure": "Microsoft Azure",
    "devopssystemadministrationwritingautomationscripts":
        "DevOps / System administration / Writing automation scripts",
    "devopssystemsadministrationwritingautomationscripts":
        "DevOps / System administration / Writing automation scripts",
}


def canonical_option(option: str) -> str:
    key = norm_key(option)
    if key in OPTION_ALIASES:
        return OPTION_ALIASES[key]
    return norm_text(option)


# ---------------------------------------------------------------- 列名对齐


def split_path(name: str) -> tuple[str, str]:
    """将列名拆成 (标准组路径, 选项)。2019 括号列先转换为点分形式。"""
    if "[" in name and name.endswith("]"):
        group, option = name.split("[", 1)
        group = GROUP_REMAP_2019.get(group.strip(), group.strip())
        return group, option.rstrip("]").strip()
    for path in sorted(KNOWN_GROUP_PATHS, key=len, reverse=True):
        if name.startswith(path + "."):
            return path, name[len(path) + 1:]
    if name in SINGLE_REMAP_2019:
        return SINGLE_REMAP_2019[name], ""
    if "." in name:
        path, option = name.split(".", 1)
        return path, option
    return name, ""


def align_columns(dfs: dict[int, pd.DataFrame]) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """收集跨年列变体 -> 确定标准列名 -> 重命名。返回 (对齐df, 映射表)。"""
    # key=(标准路径, 归一选项键) -> {"canon": 标准选项文本, "canon_year": int, "by_year": {y: [原始列]}}
    variants: dict[tuple[str, str], dict] = {}
    for year in YEARS:
        for col in dfs[year].columns:
            path, option = split_path(col)
            path = GROUP_PATH_CANON.get(path, path)
            entry = variants.setdefault((path, norm_key(option)), {"canon": "", "canon_year": -1, "by_year": {}})
            entry["by_year"].setdefault(year, []).append(col)
            if option:
                idx = YEARS.index(year)
                if entry["canon_year"] <= idx:
                    entry["canon"] = canonical_option(option) or entry["canon"]
                    entry["canon_year"] = idx

    std_name: dict[tuple[str, str], str] = {}
    for (path, okey), entry in variants.items():
        std_name[(path, okey)] = f"{path}.{entry['canon']}" if okey and entry["canon"] else path

    mapping_rows: list[dict] = []
    aligned: dict[int, pd.DataFrame] = {}
    used = {y: Counter() for y in YEARS}
    for year in YEARS:
        renames: dict[str, str] = {}
        for col in dfs[year].columns:
            path, option = split_path(col)
            path = GROUP_PATH_CANON.get(path, path)
            new = std_name[(path, norm_key(option))]
            level = "exact" if col == new else "normalized"
            if used[year][new]:
                new = f"{new}__dup{used[year][new]}"
            used[year][new] += 1
            renames[col] = new
            if col != new:
                mapping_rows.append({"year": year, "original": col, "canonical": new, "level": level})
        aligned[year] = dfs[year].rename(columns=renames)
    return aligned, pd.DataFrame(mapping_rows)


# ---------------------------------------------------------------- 取值对齐


def align_values(dfs: dict[int, pd.DataFrame]) -> tuple[dict[int, pd.DataFrame], pd.DataFrame]:
    """统一类别列取值文案；二值列(0/1)与自由文本列(基数>60)不处理。"""
    rows: list[dict] = []
    # 跨年取值变体：(标准列名, 归一键) -> {year: 原值}
    variant_pref: dict[tuple[str, str], dict] = {}
    for year in YEARS:
        for col in dfs[year].columns:
            s = dfs[year][col]
            if s.dtype.kind in "bi" or s.nunique(dropna=False) > 60:
                continue
            for v in s.dropna().unique():
                v = str(v).strip()
                if not v or norm_key(v).startswith("otherplease"):
                    continue
                variant_pref.setdefault((col, norm_key(v)), {}).setdefault(year, v)
    canon_value: dict[tuple[str, str], str] = {}
    for (col, key), by_year in variant_pref.items():
        best = next((by_year[y] for y in reversed(YEARS) if y in by_year), next(iter(by_year.values())))
        canon_value[(col, key)] = canonical_option(best)

    aligned: dict[int, pd.DataFrame] = {}
    for year in YEARS:
        df = dfs[year].copy()
        for col in df.columns:
            s = df[col]
            if s.dtype.kind in "bi" or s.nunique(dropna=False) > 60:
                continue
            def conv(v, _col=col):
                v = str(v).strip()
                if not v:
                    return v
                c = canon_value.get((_col, norm_key(v)))
                if c is not None and c != v:
                    rows.append({"year": year, "column": _col, "original": v, "canonical": c})
                    return c
                return v
            df[col] = s.map(conv)
        aligned[year] = df
    return aligned, pd.DataFrame(rows)


# ---------------------------------------------------------------- 报告与主流程


def write_report(
    col_map: pd.DataFrame, val_map: pd.DataFrame,
    common: set[str], per_year_cols: dict[int, int], master_rows: int,
) -> None:
    lines = ["# PSF Survey 跨年数据对齐报告", "", f"生成时间：{pd.Timestamp.now():%Y-%m-%d %H:%M}", ""]
    lines.append("管线：文本归一 + 组路径重映射 + 同义词表 -> 列名统一 -> 取值文案统一 -> 共有列纵向合并")
    lines += ["", "## 对齐统计", ""]
    lines.append(f"- 跨年共有列：{len(common)}（对齐前为 42）")
    lines.append(f"- 重命名列：{len(col_map)}")
    lines.append(f"- 取值统一记录：{len(val_map)}")
    lines.append(f"- 跨年总表行数：{master_rows}")
    lines += ["", "| 年份 | 总列数 | 落在共有列中的列数 |", "|---|---|---|"]
    for y in YEARS:
        lines.append(f"| {y} | {per_year_cols[y][0]} | {per_year_cols[y][1]} |")
    if len(col_map):
        lines += ["", "### 列名重命名按年份统计", "", "| 年份 | 重命名列数 |", "|---|---|"]
        for y, g in col_map.groupby("year"):
            lines.append(f"| {y} | {len(g)} |")
        lines += ["", "### 重命名示例（每年前 8 条）", ""]
        for y, g in col_map.groupby("year"):
            lines.append(f"**{y}**")
            lines += [f"- `{r.original}` -> `{r.canonical}`" for r in g.head(8).itertuples()]
    lines.append("")
    (OUT_DIR / "alignment_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(exist_ok=True)
    dfs = {
        y: pd.read_csv(IN_DIR / f"cleaned_{y}.csv", keep_default_na=False, encoding="utf-8-sig")
        for y in YEARS
    }
    dfs, col_map = align_columns(dfs)
    dfs, val_map = align_values(dfs)

    common = sorted(set.intersection(*(set(dfs[y].columns) for y in YEARS)))
    per_year_cols = {y: (dfs[y].shape[1], len(set(dfs[y].columns) & set(common))) for y in YEARS}

    for y in YEARS:
        dfs[y].to_csv(OUT_DIR / f"cleaned_aligned_{y}.csv", index=False)

    master = pd.concat(
        [dfs[y].assign(year=y)[["year"] + common] for y in YEARS], ignore_index=True
    )
    master.to_csv(OUT_DIR / "survey_2019_2023_master.csv", index=False)

    col_map.to_csv(OUT_DIR / "column_mapping.csv", index=False)
    val_map.to_csv(OUT_DIR / "value_mapping.csv", index=False)
    write_report(col_map, val_map, set(common), per_year_cols, len(master))

    print(f"跨年共有列: {len(common)} (对齐前 42)")
    print(f"重命名列: {len(col_map)} | 取值统一: {len(val_map)} | 总表行数: {len(master)}")
    for y in YEARS:
        print(f"  {y}: {per_year_cols[y][0]} 列, 其中 {per_year_cols[y][1]} 列进入总表")
    print(f"输出目录: {OUT_DIR}")


if __name__ == "__main__":
    main()
