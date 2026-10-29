"""组路径指令遵循探针：同一道多选题的多个选项列，模型是否给出同一个 group。

为什么单独测：`_SEMANTICS_SYSTEM` 的硬性要求第 1 条是"同一个多选题组的各选项列必须
给出完全相同的 group"，且 2020 及以后没有兜底（`_stabilize_2019_groups` 只对 2019 生
效）。所以 2020+ 的 group 一旦按选项各造一个，跨年组路径对齐就失去锚点。本探针取同一
前缀下的若干选项列，单次请求，看返回的 group 有几种。

用法：
  python pangu/probe/group_follow.py --year 2020            # 自动挑选项最多的前缀
  python pangu/probe/group_follow.py --year 2020 --prefix data.frameworks --limit 6
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PANGU_DIR = HERE.parent
ROOT = PANGU_DIR.parent

# 与 run_pangu.py 一致：先定产物根目录，再导入 llm_survey（config 在导入时求值）。
os.environ.setdefault("LLM_SURVEY_OUT_ROOT", str(PANGU_DIR))
os.environ.setdefault("LLM_SURVEY_MODEL", "pangu-emb-7b")
os.environ.setdefault("LLM_SURVEY_NUM_CTX", "8192")
os.environ.setdefault("LLM_SURVEY_PREDICT_MIN", "1024")
os.environ.setdefault("LLM_SURVEY_PREDICT_PER_COL", "900")

if str(ROOT / "llm") not in sys.path:
    sys.path.insert(0, str(ROOT / "llm"))

from llm_survey import config, prompts  # noqa: E402
from llm_survey.ollama_client import OllamaClient  # noqa: E402
from llm_survey.profiles import compact_row, load_profile  # noqa: E402


def pick_prefix(profile: dict[str, Any], want: str | None) -> tuple[str, list[str]]:
    """按前缀（= 组路径）分组；2020+ 的列名形如「前缀.选项」。"""
    groups: dict[str, list[str]] = {}
    for col in (c["name"] for c in profile["columns"]):
        if "." not in col:
            continue
        prefix = col.rsplit(".", 1)[0]
        groups.setdefault(prefix, []).append(col)
    if want:
        if want not in groups:
            raise SystemExit(f"[error] 前缀不存在：{want}；可选示例：{list(groups)[:8]}")
        return want, groups[want]
    prefix = max(groups, key=lambda k: len(groups[k]))
    return prefix, groups[prefix]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组路径指令遵循探针")
    parser.add_argument("--year", type=int, default=2020)
    parser.add_argument("--prefix", default=None, help="待测前缀（组路径），缺省自动选选项最多者")
    parser.add_argument("--limit", type=int, default=6, help="本次送入的选项列数")
    parser.add_argument("--out", default=None, help="结果 JSON 路径")
    args = parser.parse_args(argv)

    profile = load_profile(args.year)
    prefix, columns = pick_prefix(profile, args.prefix)
    columns = columns[: args.limit]
    rows = [compact_row(profile, c) for c in columns]

    client = OllamaClient()
    digest = client.health()
    system, user = prompts.semantics_messages(args.year, rows)
    num_predict = max(config.NUM_PREDICT_MIN, len(columns) * config.NUM_PREDICT_PER_COL)
    response, meta = client.chat_json(system, user, num_predict=num_predict,
                                      tag=f"group-follow-{args.year}")
    items = response.get("columns") or []

    groups = [str(item.get("group") or "") for item in items]
    counter = Counter(groups)
    result = {
        "year": args.year,
        "model": client.model,
        "digest": digest,
        "prefix": prefix,
        "columns_requested": columns,
        "columns_returned": len(items),
        "distinct_groups": len(counter),
        "top_group_share_pct": round(counter.most_common(1)[0][1] / len(groups) * 100, 1)
        if groups else 0.0,
        "groups": dict(counter),
        "items": [
            {"column": item.get("column"), "kind": item.get("kind"),
             "group": item.get("group"), "option": item.get("option")}
            for item in items
        ],
        "duration_s": meta.duration_s,
        "output_tokens": meta.output_tokens,
    }

    out = Path(args.out) if args.out else PANGU_DIR / "reports" / f"group_follow_{args.year}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[probe] {args.year} 前缀 {prefix}：请求 {len(columns)} 列，返回 {len(items)} 列")
    print(f"[probe] group 去重后 {len(counter)} 种，最高占比 {result['top_group_share_pct']}%")
    for group, count in counter.most_common():
        print(f"  - {group or '(空)'} × {count}")
    print(f"[probe] 耗时 {meta.duration_s}s / 输出 {meta.output_tokens} token")
    print(f"[probe] 写出 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
