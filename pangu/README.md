# pangu/：盘古本地模型实验

把 `openPangu-Embedded` 接到既有的清洗/对齐管线上，只换推理后端，其余全部沿用 `llm/llm_survey`：
提示词、护栏阈值、词表、留出年份策略一处不动。目的是回答一个问题——**换更大的本地模型，
跨年对齐这块判断能不能做得更好、值不值得。**

结论先给：判断层打平（8 对全对），成本高一个量级（同 8 对 13.7s vs 4.7s；2019 清洗每列
406.7 token 对 54.7、纯推理 6.6s 对 0.73s），跨年对齐阶段未跑完，因此**它的位置是分歧仲裁，
不是主力**。扩样到 138 列后另有一处缺口：2019 的 `group` 一致率只有 5.1%，2020 起同样的
探针 10/10 同组，详见 `reports/benchmark.md`。

三份报告：

- [`reports/model_selection.md`](reports/model_selection.md)：档位矩阵、为什么放弃 2.0-Flash、Q3/Q4 取舍
- [`reports/benchmark.md`](reports/benchmark.md)：三方实测指标与分歧归因
- [`reports/compliance.md`](reports/compliance.md)：本地/云端/纯规则三种形态的数据边界

## 目录

```
pangu/
├── run_pangu.py              # CLI 入口：设置 LLM_SURVEY_OUT_ROOT 后复用 llm/run_llm_pipeline.py
├── models/                   # GGUF 权重与 Modelfile（不入库，见 .gitignore）
├── probe/
│   ├── hardware.py           # 显存/内存/磁盘闸门 + 档位判定
│   ├── backend_check.py      # Ollama 与 llama.cpp 两条路径的连通性
│   ├── capability.py         # 能力探针：JSON 合法率、判断准确率、跨轮一致、耗时
│   ├── decisions_summary.py  # 决策缓存汇总：每列 token、单批耗时、降级率
│   ├── semantics_compare.py  # 清洗语义判定逐列对账（qwen vs 盘古，kind/group/option）
│   └── group_follow.py       # 组路径指令遵循探针（同一道多选题的选项是否共用一个 group）
├── decisions/                # 模型判断缓存（结构同 llm/decisions，digest 不同故互不污染）
├── cleaned/                  # 盘古版清洗表
├── aligned/                  # 盘古版对齐表
└── reports/                  # hardware.json、capability_*.json、decisions_summary.json、三份 md
```

## 环境

| 项 | 要求 |
|---|---|
| GPU | 8 GB 显存可跑 7B Q4_K_M（权重 + 8k KV 约 5.8 GiB，全量驻留） |
| 内存 | 15.6 GB；**可用内存决定大 MoE 能不能跑**，2.0-Flash 最小档 40.7 GiB 因此被排除 |
| Ollama | 需支持该自定义架构；不支持 `format=json` 会自动降级为提示词约束 |
| Python | 3.14+，依赖同 `llm/`（pandas、requests） |

导入模型：

```powershell
ollama create pangu-emb-7b -f pangu/models/Modelfile.7b
ollama create pangu-emb-1b -f pangu/models/Modelfile.1b
ollama list
```

## 运行

```powershell
# 0. 硬件闸门（不调模型，约 2 秒）
python pangu/probe/hardware.py

# 1. 连通性与格式能力
python pangu/run_pangu.py --stage ping
python pangu/probe/backend_check.py

# 2. 能力探针（8 对真实候选对，2 轮）
$env:LLM_SURVEY_MODEL="pangu-emb-7b"
python pangu/probe/capability.py --rounds 2

# 3. 清洗：7B 输出长，必须缩批 + 放宽预算，否则大批必然截断
$env:LLM_SURVEY_NUM_CTX="8192"          # 16384 会让 KV cache 溢出显存，触发层卸载
$env:LLM_SURVEY_PREDICT_MIN="1024"
$env:LLM_SURVEY_PREDICT_PER_COL="900"
python pangu/run_pangu.py --stage clean --years 2019 --batch-size 4

# 4. 对齐（尚未跑通，见下节）
python pangu/run_pangu.py --stage align --years 2019

# 5. 决策成本汇总
python pangu/probe/decisions_summary.py --md --layers 2019
python pangu/probe/decisions_summary.py --md --dir llm/decisions --layers 2019 `
    --out pangu/reports/decisions_qwen_2019.json

# 6. 判断质量对账（只读决策缓存，不调模型，秒级）
python pangu/probe/semantics_compare.py --year 2019
python pangu/probe/group_follow.py --year 2020 --limit 5
```

`--years` 不传默认六年全跑；`--refresh` 忽略缓存重算；`--dry-run` 不调模型。

## 与 llm/ 的两点差异

1. **产物隔离**：`run_pangu.py` 在导入 `llm_survey` 之前设置 `LLM_SURVEY_OUT_ROOT=pangu/`，
   `config` 的决策、清洗、对齐、报告路径全部跟着走，不会覆盖 `llm/` 的任何产物。
2. **后端能力探测**：`OllamaClient` 遇到 400 且报文含 `sampler`/`grammar` 时，判定该模型不支持
   JSON grammar，改为提示词约束 + 容错解析，并抛 `retry-without-format` 重发一次。盘古两档都会走这条路径。

提示词、`OPTION_ALIASES`、`GROUP_PATH_CANON`、`HOLDOUT_YEARS={2023,2024}`、护栏阈值一律不改——
这是三方可比的前提。

## 实测成本（2019 清洗）

| 指标 | qwen3.5:4b | openPangu-7B Q4_K_M |
|---|---|---|
| 主批数（batch=18 / 4） | 17 | 73 |
| 实际调用次数 | 17 | 61（覆盖 156 列，未跑完） |
| 每列输出 token（均摊） | 54.7 | 406.7 |
| 每列纯推理耗时 | 0.73 s | 6.6 s |
| 墙钟跨度 / 其中调用间空档 | 3.3 min / 0 | 126.6 min / 112.5 min |
| 单次调用中位耗时 | 13.1 s | 13.8 s |
| 吞吐 | 60.0 tok/s | 63.6 tok/s |
| JSON 合法率 | 100% | 100%（靠提示词约束） |
| 降级（fallback） | 0 | 0 |

吞吐其实略高，慢的是输出长度：模板里没有 thinking 分支，`think=false` 是空操作，
模型每列都要写 300–400 token 推理正文，关不掉。加上输出预算按 `900 × 列数` 给，4 列批常
整批作废再拆半重试，61 次调用里约 22 次是重试产生的。

wall clock 那个 126 分钟不能直接当成本：决策缓存里 61 次调用的时长合计只有 17.2 分钟，剩下
112 分钟是调用之间的空档（30 段超过 60 秒）。空档成因没查到，日志里没有排队与加载记录。按
纯推理时间折算，2019 全年清洗约 32 分钟。

## 已知限制

- 2019 清洗跑到 156/290 列时本文收数并终止进程，`aligned/` 尚无产物，所以三方对比只在
  "同题判定＋清洗列语义"这两层成立。按 6.6 s/列的纯推理折算，单年清洗约半小时、单年对齐另有
  一小时上下，六年全量在时间窗内偏紧但不是跑不动。重跑同一条命令即可接上，已判过的列走缓存。
- 判断层样本只有 8 对、2 轮，能否掉 1B，但不足以给 7B 一个准确率区间。
- 盘古不支持 `format=json`、不支持关闭推理正文；`num_ctx` 超过 8192 会触发层卸载到 CPU，
  吞吐掉一个档位（16% CPU / 84% GPU 时实测明显变慢）。
- `pangu/models/` 与 `*.gguf` 已在 `.gitignore`：权重体积 5.29 GB 且受上游许可约束，不入库。

## 与组会材料的关系

`reports/2026-11-06/` 的讲述稿第 07 页与幻灯片第 7 页引用本目录的
`capability_7b.json`、`capability_qwen.json`、`hardware.json`；图的取数脚本是
`reports/2026-11-06/build_figures.py`（读不到探针文件时该图自动跳过）。改数字时两边要同步。
