"""盘古 GGUF 后端加载与最小推理验证。

依次验证四件事，任一失败即说明该后端不可用于本项目管线：
  1. 模型已注册在 Ollama 的 /api/tags 中（可取得 digest，供缓存键使用）
  2. /api/show 能读出架构与上下文长度等元信息
  3. 不带 format 约束的基础 chat 能返回非空内容（延迟、吞吐可测）
  4. format="json" 与 think 参数被接受（盘古若为纯文本模型，think 可能被拒）

用法：
    python pangu/probe/backend_check.py --model pangu-emb-1b
    python pangu/probe/backend_check.py --model pangu-emb-7b --num-predict 256

日志只打印结构与计数，不打印数据样本原文。
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

import requests

DEFAULT_HOST = "http://127.0.0.1:11434"
CONNECT_TIMEOUT_S = 10
CHAT_TIMEOUT_S = 900

# 只考察"能否输出合法 JSON 对象"这一形式约束，不涉及任何调查数据内容。
_PROBE_PROMPT = (
    "你是数据清洗助手。请只输出一个 JSON 对象，包含两个键："
    'ok（布尔值 true）与 note（字符串 "ready"）。不要输出任何其他文字。'
)


def _short(text: str, limit: int = 160) -> str:
    flat = " ".join((text or "").split())
    return flat[:limit] + ("…" if len(flat) > limit else "")


def list_models(host: str) -> list[dict[str, Any]]:
    resp = requests.get(f"{host}/api/tags", timeout=(CONNECT_TIMEOUT_S, 30))
    resp.raise_for_status()
    return resp.json().get("models", [])


def find_model(models: list[dict[str, Any]], target: str) -> dict[str, Any] | None:
    base = target.split(":")[0]
    for item in models:
        name = item.get("name") or item.get("model") or ""
        if name == target or name.split(":")[0] == base:
            return item
    return None


def show_model(host: str, model: str) -> dict[str, Any]:
    resp = requests.post(
        f"{host}/api/show", json={"model": model}, timeout=(CONNECT_TIMEOUT_S, 30)
    )
    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {_short(resp.text)}"}
    return resp.json()


def chat(
    host: str,
    model: str,
    prompt: str,
    *,
    force_json: bool = False,
    think: bool | None = None,
    num_predict: int = 128,
    num_ctx: int = 8192,
) -> tuple[str, dict[str, Any]]:
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
            "top_p": 0.9,
        },
    }
    if force_json:
        payload["format"] = "json"
    if think is not None:
        payload["think"] = think

    resp = requests.post(f"{host}/api/chat", json=payload, timeout=(CONNECT_TIMEOUT_S, CHAT_TIMEOUT_S))
    if resp.status_code != 200:
        return "", {"http_status": resp.status_code, "error": _short(resp.text, 400)}

    data = resp.json()
    message = data.get("message") or {}
    content = message.get("content") or ""
    if not content and data.get("thinking"):
        content = str(data["thinking"])
    out_tokens = int(data.get("eval_count") or 0)
    duration = float(data.get("total_duration") or 0) / 1e9
    return content, {
        "http_status": 200,
        "duration_s": round(duration, 2),
        "prompt_tokens": int(data.get("prompt_eval_count") or 0),
        "output_tokens": out_tokens,
        "tok_per_s": round(out_tokens / duration, 1) if duration else 0.0,
        "done_reason": data.get("done_reason"),
    }


def _try_json_parse(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text.strip())
    except (json.JSONDecodeError, AttributeError):
        return None
    return data if isinstance(data, dict) else None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="盘古 GGUF 后端加载与最小推理验证")
    ap.add_argument("--model", default="pangu-emb-1b")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--num-predict", type=int, default=128)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--prompt", default="", help="自定义探测提示词，留空则用内置 JSON 约束提示")
    ap.add_argument("--repeat", type=int, default=2, help="稳态吞吐测量次数（含预热）")
    ap.add_argument("--skip-json", action="store_true", help="跳过 format=json 检查（已知架构不支持时）")
    args = ap.parse_args(argv)

    report: dict[str, Any] = {"model": args.model, "host": args.host, "checks": {}}
    failures: list[str] = []

    # 1. 模型注册状态
    try:
        models = list_models(args.host)
    except requests.RequestException as exc:
        print(f"[FAIL] 无法连接 Ollama（{args.host}）：{exc}", file=sys.stderr)
        print("       请确认 `ollama serve` 正在运行。", file=sys.stderr)
        return 2
    hit = find_model(models, args.model)
    if hit is None:
        print(f"[FAIL] Ollama 中未找到模型 {args.model}", file=sys.stderr)
        print("       已注册模型：" + ", ".join(m.get("name", "?") for m in models), file=sys.stderr)
        return 2
    report["registered"] = {
        "name": hit.get("name"),
        "digest": str(hit.get("digest", ""))[:16],
        "size_gb": round(float(hit.get("size") or 0) / 1e9, 2),
    }
    print(f"[OK]   模型已注册：{hit.get('name')}  "
          f"digest={report['registered']['digest']}  "
          f"size={report['registered']['size_gb']} GB")

    # 2. 元信息
    info = show_model(args.host, args.model)
    details = info.get("details") or {}
    model_info = info.get("model_info") or {}
    arch = next((v for k, v in model_info.items() if k.endswith(".architecture")), "")
    ctx_keys = [k for k in model_info if k.endswith(".context_length")]
    ctx_len = int(model_info[ctx_keys[0]]) if ctx_keys else 0
    has_template = bool((info.get("template") or "").strip())
    report["meta"] = {
        "architecture": arch,
        "parameter_size": details.get("parameter_size"),
        "quantization": details.get("quantization_level"),
        "context_length": ctx_len,
        "has_chat_template": has_template,
        "family": details.get("family"),
    }
    print(f"[OK]   元信息：arch={arch or '?'}  params={details.get('parameter_size') or '?'}  "
          f"quant={details.get('quantization_level') or '?'}  "
          f"ctx={ctx_len or '?'}  chat_template={has_template}")
    if not has_template:
        failures.append("缺少 chat template，对话格式将不可控")

    # 3. 基础 chat：先预热（含模型加载与 graph 分配），再测稳态吞吐
    prompt = args.prompt or _PROBE_PROMPT
    chat(args.host, args.model, "请输出 ok。", num_predict=8, num_ctx=args.num_ctx)
    runs: list[dict[str, Any]] = []
    text = ""
    for idx in range(max(1, args.repeat)):
        text, stat = chat(args.host, args.model, prompt + " " * idx,
                          num_predict=args.num_predict, num_ctx=args.num_ctx)
        runs.append(stat)
    report["checks"]["plain_chat"] = {"runs": runs, "preview": _short(text)}
    last = runs[-1]
    if last.get("http_status") != 200 or not text.strip():
        failures.append(f"基础 chat 失败：{last.get('error') or '返回空内容'}")
        print(f"[FAIL] 基础 chat：{last.get('error') or '返回空内容'}")
    else:
        tps_seq = ", ".join(str(r.get("tok_per_s")) for r in runs)
        print(f"[OK]   基础 chat：稳态 {last.get('tok_per_s')} tok/s（各轮 {tps_seq}）  "
              f"in={last.get('prompt_tokens')}tok  out={last.get('output_tokens')}tok")

    # 4. format=json（盘古 GGUF 在 Ollama 下可能因架构不支持 grammar sampler 而报 400）
    if args.skip_json:
        report["checks"]["force_json"] = {"skipped": True}
        print("[SKIP] format=json：按参数跳过")
    else:
        text_json, stat_json = chat(args.host, args.model, prompt, force_json=True,
                                    num_predict=args.num_predict, num_ctx=args.num_ctx)
        parsed = _try_json_parse(text_json)
        report["checks"]["force_json"] = {**stat_json, "parsed": parsed is not None,
                                          "preview": _short(text_json)}
        if stat_json.get("http_status") != 200:
            failures.append(f"format=json 被拒：{stat_json.get('error')}")
            print(f"[FAIL] format=json 被拒：{stat_json.get('error')}")
        elif parsed is None:
            failures.append("format=json 下输出仍不是合法 JSON 对象")
            print(f"[WARN] format=json 生效但解析失败：{_short(text_json)}")
        else:
            print(f"[OK]   format=json：解析成功 {list(parsed)[:4]}  "
                  f"{stat_json['tok_per_s']} tok/s")

    # 5. think 参数兼容性
    _text_think, stat_think = chat(args.host, args.model, prompt, think=False,
                                   num_predict=args.num_predict, num_ctx=args.num_ctx)
    report["checks"]["think_false"] = stat_think
    if stat_think.get("http_status") != 200:
        failures.append(f"think=false 被拒：{stat_think.get('error')}")
        print(f"[WARN] think=false 被拒（源码有降级路径，可自动移除该字段）："
              f"{stat_think.get('error')}")
    else:
        print(f"[OK]   think=false 被接受：{stat_think['tok_per_s']} tok/s")

    print()
    if failures:
        print("结论：后端不可直接复用，未通过项如下")
        for item in failures:
            print(f"  - {item}")
        print("\n" + json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    print("结论：后端四项检查全部通过，可直接复用 OllamaClient（仅需替换 model 名）")
    print("\n" + json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
