"""能力探针：用管线里真实的提示词验证盘古能否承担判定角色。

考察四件事：
  1. JSON 合法率——原始输出能否被 extract_json 解析成对象
  2. 指令遵循——是否覆盖全部 id、字段是否齐备、有无越界新增
  3. 判断准确率——与人工标注的 ground truth 比对
  4. 一致性——同输入重复多次，结论是否稳定

样本刻意避开 _PAIR_JUDGE_SYSTEM 正文里已举的例子（VS Code / k8s / PyCharm
Professional 等），否则测到的只是模型对示例的复述，不是判断能力。

用法：
    python pangu/probe/capability.py --model pangu-emb-7b
    python pangu/probe/capability.py --model pangu-emb-1b --repeats 1
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLM_DIR = HERE.parent.parent / "llm"
if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from llm_survey import prompts  # noqa: E402
from llm_survey.ollama_client import (  # noqa: E402
    ChatMeta,
    OllamaClient,
    OllamaError,
    extract_json,
)

# 真实调查中会出现的写法差异；same 为人工标注答案。
CASES: list[dict[str, object]] = [
    {"id": "p1", "a": "AWS", "b": "Amazon Web Services", "same": True},
    {"id": "p2", "a": "GCP", "b": "Google Cloud Platform", "same": True},
    {"id": "p3", "a": "Notepad++", "b": "Notepad ++", "same": True},
    {"id": "p4", "a": "Less than 1 year", "b": "< 1 year", "same": True},
    {"id": "p5", "a": "Python 3.10", "b": "Python 3.11", "same": False},
    {"id": "p6", "a": "PyCharm", "b": "PyCharm Community Edition", "same": False},
    {"id": "p7", "a": "Django", "b": "Flask", "same": False},
    {"id": "p8", "a": "Docker", "b": "Docker Desktop", "same": False},
]


def _payload() -> list[dict[str, str]]:
    """剥离标注，只把 id/a/b 送给模型，避免答案泄漏。"""
    return [{"id": str(c["id"]), "a": str(c["a"]), "b": str(c["b"])} for c in CASES]


def _judgements(obj: dict[str, object]) -> dict[str, bool]:
    """从模型输出中抽出 id -> same，容忍 pairs 位置差异。"""
    items = obj.get("pairs")
    if not isinstance(items, list):
        return {}
    out: dict[str, bool] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("id") or "").strip()
        value = item.get("same")
        if key and isinstance(value, bool):
            out[key] = value
    return out


def evaluate(judged: dict[str, bool]) -> dict[str, object]:
    truth = {str(c["id"]): bool(c["same"]) for c in CASES}
    covered = [k for k in truth if k in judged]
    correct = [k for k in covered if judged[k] == truth[k]]
    wrong = {k: {"model": judged[k], "truth": truth[k]} for k in covered if judged[k] != truth[k]}
    return {
        "coverage": len(covered),
        "total": len(truth),
        "accuracy": round(len(correct) / len(covered), 3) if covered else 0.0,
        "wrong": wrong,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="盘古能力探针（真实提示词）")
    ap.add_argument("--model", default="pangu-emb-7b")
    ap.add_argument("--host", default="http://127.0.0.1:11434")
    ap.add_argument("--repeats", type=int, default=3, help="重复次数，用于测一致性")
    ap.add_argument("--num-predict", type=int, default=512)
    ap.add_argument("--json", default="", help="结果写入指定路径")
    args = ap.parse_args(argv)

    client = OllamaClient(model=args.model, host=args.host)
    try:
        digest = client.health()
    except OllamaError as exc:
        print(f"[错误] {exc}")
        return 2
    print(f"模型 {args.model}（digest={digest}）\n")

    system, user = prompts.pair_judge_messages(_payload())
    runs: list[dict[str, object]] = []
    for idx in range(args.repeats):
        try:
            text, meta = client.chat_text(system, user, num_predict=args.num_predict,
                                          tag=f"cap{idx}")
        except (OllamaError, ValueError) as exc:
            print(f"[FAIL] 第 {idx + 1} 轮调用失败：{exc}")
            runs.append({"round": idx + 1, "json_ok": False, "error": str(exc)})
            continue

        parsed: dict[str, object] | None = None
        try:
            parsed = extract_json(text)
        except OllamaError:
            parsed = None

        judged = _judgements(parsed) if parsed else {}
        report = evaluate(judged) if judged else {
            "coverage": 0, "total": len(CASES), "accuracy": 0.0, "wrong": {}
        }
        report.update({
            "round": idx + 1,
            "json_ok": parsed is not None,
            "schema_ok": bool(judged),
            "duration_s": round(meta.duration_s, 2),
            "output_tokens": meta.output_tokens,
            "tok_per_s": round(meta.output_tokens / meta.duration_s, 1) if meta.duration_s else 0.0,
            "judged": judged,
            "raw_preview": " ".join(text.split())[:200],
        })
        runs.append(report)
        flag = "OK  " if parsed is not None else "FAIL"
        print(f"[{flag}] 第 {idx + 1} 轮：覆盖 {report['coverage']}/{report['total']}  "
              f"准确率 {report['accuracy']}  {report['duration_s']}s  "
              f"{report['tok_per_s']} tok/s  JSON={report['json_ok']}")

    ok_runs = [r for r in runs if r.get("json_ok")]
    summary: dict[str, object] = {
        "model": args.model,
        "digest": digest,
        "rounds": len(runs),
        "json_ok_rate": round(len(ok_runs) / len(runs), 3) if runs else 0.0,
        "mean_accuracy": round(statistics.fmean([float(r["accuracy"]) for r in ok_runs]), 3)
        if ok_runs else 0.0,
        "mean_tok_per_s": round(statistics.fmean([float(r["tok_per_s"]) for r in ok_runs]), 1)
        if ok_runs else 0.0,
        "mean_duration_s": round(statistics.fmean([float(r["duration_s"]) for r in ok_runs]), 1)
        if ok_runs else 0.0,
    }

    # 一致性：各轮判为 same=true 的 id 集合是否完全相同，以及多少 id 达到多轮一致
    if ok_runs:
        pos_sets = [frozenset(k for k, v in r["judged"].items() if v) for r in ok_runs]
        summary["consistent"] = len(set(pos_sets)) == 1
        unanimous = 0
        for case in CASES:
            values = {r["judged"].get(str(case["id"])) for r in ok_runs}
            if len(values) == 1 and None not in values:
                unanimous += 1
        summary["unanimous_ids"] = unanimous

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"summary": summary, "runs": runs},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已写入 {out}")
    return 0 if summary["json_ok_rate"] >= 0.95 else 1


if __name__ == "__main__":
    raise SystemExit(main())
