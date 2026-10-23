"""LLM 驱动管线 CLI 入口（本地 Qwen3.5-4B via Ollama）。

用法：
  python llm/run_llm_pipeline.py --stage ping
  python llm/run_llm_pipeline.py --stage profile
  python llm/run_llm_pipeline.py --stage clean --years 2024
  python llm/run_llm_pipeline.py --stage all
  python llm/run_llm_pipeline.py --stage all --refresh          # 忽略缓存重算
  python llm/run_llm_pipeline.py --stage all --dry-run          # 不调模型
  python llm/run_llm_pipeline.py --stage clean --apply-review   # 执行已确认的删列
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from llm_survey import (  # noqa: E402
    align_stage,
    chart_stage,
    clean_stage,
    config,
    parity,
    profiles,
    selftest,
    stats_stage,
)
from llm_survey.ollama_client import OllamaClient, OllamaError  # noqa: E402

STAGES = ("ping", "selftest", "profile", "clean", "align", "stats", "charts", "parity", "all")


def build_client(dry_run: bool) -> OllamaClient | None:
    if dry_run:
        return None
    client = OllamaClient()
    digest = client.health()
    print(f"模型：{client.model}（digest={digest}，think={client.think}，"
          f"temperature={config.TEMPERATURE}，seed={config.SEED}）")
    return client


def stage_profile(years: list[int], rebuild: bool) -> None:
    for year in years:
        profile = profiles.load_profile(year, rebuild=rebuild)
        print(f"  {year}: {profile['rows']:,} 行 × {profile['cols']} 列，"
              f"全空行 {profile['empty_rows']:,}，全空列 {len(profile['empty_cols'])}，"
              f"重复行 {profile['dup_rows']:,}，重复列组 {len(profile['dup_col_groups'])}")


def stage_clean(years: list[int], client: OllamaClient | None, batch: int,
                refresh: bool, apply_review: bool) -> None:
    results = []
    for year in years:
        started = time.perf_counter()
        result = clean_stage.clean_year(year, client, refresh, batch, apply_review)
        elapsed = time.perf_counter() - started
        results.append(result)
        print(f"  {year}: {result.rows_in:,}→{result.rows_out:,} 行，"
              f"{result.cols_in}→{result.cols_out} 列，二值化 {result.binarized}，"
              f"数值 {result.numeric}，重命名 {result.renamed}，"
              f"待确认删列 {len(result.pending_review)}，耗时 {elapsed:.1f}s")
        if result.cache_line:
            print(f"      缓存：{result.cache_line}")
    clean_stage.write_report(results)


def stage_align(years: list[int], client: OllamaClient | None, refresh: bool,
                dry_run: bool, holdout_years: set[int]) -> None:
    result = align_stage.run(years, client, refresh, dry_run=dry_run,
                             holdout_years=holdout_years)
    print(f"  共有列 {len(result.common_cols)}，组路径 {result.groups}，"
          f"统一映射 {len(result.group_merges)}，重命名 {result.renames}，"
          f"取值统一 {result.value_changes}，__dup {result.dup_cols}")
    print(f"  候选路径 {result.path_candidates}，候选对 {result.pairs_judged}"
          f"（接受 {result.pairs_accepted}），留出年份 {sorted(result.holdout_years)}")
    for line in result.cache_lines:
        print(f"      缓存：{line}")


def stage_stats(years: list[int], client: OllamaClient | None, refresh: bool,
                dry_run: bool) -> None:
    result = stats_stage.run(years, client, refresh, dry_run=dry_run)
    print(f"  主题 {len(result.topics)}，统计文件 {len(result.files)}，"
          f"解读 {len(result.narratives)} 节")
    for line in result.cache_lines:
        print(f"      缓存：{line}")


def stage_charts(client: OllamaClient | None, refresh: bool) -> None:
    result = chart_stage.run(client, refresh)
    print(f"  图表 {len(result.rendered)} 张：{', '.join(result.rendered[:8])}")
    for problem in result.problems[:5]:
        print(f"      提示：{problem}")


def stage_parity(client: OllamaClient | None, refresh: bool, holdout_years: set[int]) -> None:
    result = parity.run(client, refresh, holdout_years)
    print(f"  规则列 {result.rule_cols} / LLM 列 {result.llm_cols} / 匹配 {result.matched}"
          f"（Jaccard {result.jaccard}%），缺失率差异 {len(result.missing_diffs)} 条，"
          f"占比差异 {len(result.topic_diffs)} 条")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM 驱动的 PSF 调查数据管线")
    parser.add_argument("--stage", default="all", choices=STAGES)
    parser.add_argument("--years", nargs="*", type=int, default=None,
                        help="默认全部年份（2019-2024）")
    parser.add_argument("--refresh", action="store_true", help="忽略缓存重新调用模型")
    parser.add_argument("--dry-run", action="store_true", help="不调用模型，使用默认决策")
    parser.add_argument("--batch-size", type=int, default=config.BATCH_COLS,
                        help=f"每批列数（默认 {config.BATCH_COLS}）")
    parser.add_argument("--apply-review", action="store_true",
                        help="执行 review_approved.json 中已确认的删列")
    parser.add_argument("--rebuild-profile", action="store_true", help="强制重算列画像")
    parser.add_argument("--holdout-years", default=None,
                        help="留出年份（人工映射不进提示词，默认 2023,2024，"
                             "或环境变量 LLM_SURVEY_HOLDOUT）")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    years = args.years or config.YEARS
    unknown = [y for y in years if y not in config.YEARS]
    if unknown:
        print(f"未知年份：{unknown}")
        return 2

    holdout = config.HOLDOUT_YEARS
    if args.holdout_years:
        holdout = {int(y) for y in args.holdout_years.replace(" ", "").split(",") if y}

    started = time.perf_counter()
    client: OllamaClient | None = None
    if args.stage in {"selftest", "profile"} or args.dry_run:
        client = None
    else:
        try:
            client = build_client(args.dry_run)
        except OllamaError as exc:
            print(f"[错误] {exc}")
            return 2

    try:
        if args.stage == "ping":
            print(f"模型可用：{config.MODEL}")
        elif args.stage == "selftest":
            print("离线自检：")
            return selftest.run()
        elif args.stage in {"profile", "all"}:
            print("[profile] 列画像")
            stage_profile(years, args.rebuild_profile)
            if args.stage == "profile":
                return 0
        if args.stage in {"clean", "all"}:
            print("[clean] 模型判定列语义与清洗算子")
            stage_clean(years, client, args.batch_size, args.refresh, args.apply_review)
        if args.stage in {"align", "all"}:
            print("[align] 模型统一组路径与取值")
            stage_align(years, client, args.refresh, args.dry_run, holdout)
        if args.stage in {"stats", "all"}:
            print("[stats] 模型定口径 + 计算 + 解读")
            stage_stats(years, client, args.refresh, args.dry_run)
        if args.stage in {"charts", "all"}:
            print("[charts] 模型给规格 + 渲染")
            stage_charts(client, args.refresh)
        if args.stage in {"parity", "all"}:
            print("[parity] 与规则管线核对")
            stage_parity(client, args.refresh, holdout)
    except OllamaError as exc:
        print(f"[错误] 模型调用失败：{exc}")
        return 2
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"[错误] {exc}")
        print(traceback.format_exc(limit=3))
        return 1

    elapsed = time.perf_counter() - started
    print(f"\n完成，用时 {elapsed / 60:.1f} 分钟。产物目录：llm/")
    if client is not None:
        print(client.usage.summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
