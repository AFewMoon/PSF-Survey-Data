# 盘古模型选型：在本机跑得动的前提下挑质量最高的档位

生成时间：2026-10-29
数据来源：`pangu/reports/hardware.json`（硬件闸门）、`pangu/reports/capability_1b.json` 与
`capability_7b.json`、`capability_qwen.json`（能力探针）、`llm/decisions/clean/`（qwen 基线用量）。

## 结论

选 **openPangu-Embedded-7B-V1.1 Q4_K_M（4.59 GiB）** 作为本次主力档位。

- `openPangu-2.0-Flash` 全系在本机不可运行：最小档 Q3_K_M 40.7 GiB，是本机可用内存（6.17 GiB）的 2.3 倍。
- 同系列 1B 档能跑，但判断准确率 68.8%、两轮结论不一致，不能承担跨年对齐的语义判断。
- 7B 的 Q5_K_M / Q8_0 需要显存内存混合 offload，吞吐掉一档；Q3_K_M 省下 0.8 GiB 却换不到可观测收益。

一句话：不是在盘古全家族里挑最强的，而是在「8 GB 显存、15.6 GB 内存」这台机器上挑跑得动且不误判的那一个。

## 一、硬件闸门

| 项目 | 实测 | 说明 |
|---|---|---|
| GPU | RTX 5070 Laptop，8151 MiB（空闲约 6.5 GiB） | 显存是硬上限，装不下就只能 mmap |
| 物理内存 | 15.61 GiB，可用 6.17 GiB | 真正决定 MoE 大模型能不能跑的量 |
| 磁盘可用 | 280.55 GiB | 够放下 51.5 GiB 权重，但读取速度跟不上逐 token 换页 |

`hardware.py` 的判定规则：权重 + KV cache 能全量驻留显存 → `GPU`；只能混合 offload → `MIXED`；
权重明显超过内存 → `NO`。`NO` 不是"不能加载"，而是 mmap 会退化成逐 token 磁盘换页，
单 token 延迟从几十毫秒掉到秒级，跑 149 批清洗不现实。

## 二、候选档位矩阵

| 模型 | 量化 | 体积 | 判定 | 理由 |
|---|---|---|---|---|
| openPangu-2.0-Flash (92B-A6B) | Q3_K_M | 40.7 GiB | NO | 超可用内存 2.3 倍 |
| openPangu-2.0-Flash (92B-A6B) | Q4_K_M | 51.5 GiB | NO | 超可用内存 3.0 倍；质量更好但用不上 |
| openPangu-Ultra-MoE (718B) | Int8 | 718 GiB | NO | 超 40 倍，只适合云端 |
| Embedded-7B-V1.1 | Q8_0 | 7.95 GiB | MIXED | 近无损，但显存放不下整个权重 + KV |
| Embedded-7B-V1.1 | Q5_K_M | 5.34 GiB | MIXED | 需在显存与内存之间切层 |
| **Embedded-7B-V1.1** | **Q4_K_M** | **4.59 GiB** | **GPU** | 权重 + 8k KV cache 共约 5.8 GiB，全量驻留 |
| Embedded-7B-V1.1 | Q3_K_M | 3.77 GiB | GPU | 质量下限候选，本次未取 |
| Embedded-1B-V1.1 | Q4_K_M | 0.70 GiB | GPU | 跑得动，质量不达标（见下节） |

## 三、为什么放弃 2.0-Flash

这是本次选型里最需要写清楚的一条，因为 2.0-Flash 才是原本想用的模型。

1. **内存不够，不是显存不够。** 本机可用内存 6.17 GiB，Q3_K_M 权重 40.7 GiB。llama.cpp/Ollama
   的 mmap 只映射不预取，缺页时按需从磁盘读；权重按层访问的模式决定它几乎每 token 都在换页。
2. **换页把吞吐压到不可用区间。** 7B 全驻显存时 57–64 tok/s；同一台机器上 MoE 大模型缺页推理
   通常是 1–5 tok/s 量级，而清洗阶段单批输出中位 602 token/列，量级差得太多。
3. **降级执行也救不回来。** 即便只跑 2019 一年（295 列 / 74 批），按上面的吞吐估计是"按天算"，
   而 7B 跑完 2019 的清洗是"按小时算"（实测仍在进行中）。
4. **结论不是"2.0-Flash 不行"。** 它是给 96 GB 级显存或 128 GB 内存的机器准备的；本机没有这个条件。
   若后续上服务器，这份矩阵里 `GPU/MIXED/NO` 的判定要按新硬件重算——`hardware.py` 会自动重算。

## 四、质量闸门（能力探针）

探针复用了对齐阶段真实的 `pair_judge_messages` 提示词和 8 组真实候选对（AWS 与
Amazon Web Services 这类），只换模型，其余不变；每个模型跑 2–3 轮，看结论是否稳定。

| 模型 | 判定准确率 | JSON 合法率 | 跨轮一致 | 中位耗时 | 吞吐 | 输出 token（8 对） |
|---|---|---|---|---|---|---|
| qwen3.5:4b（基线） | 100% | 100% | 是 | 4.7 s | 60.0 tok/s | 342 |
| openPangu-Embedded-7B Q4_K_M | 100% | 100% | 是 | 13.7 s | 63.6 tok/s | 871 |
| openPangu-Embedded-1B Q4_K_M | 68.8% | 100% | 否 | 1.1 s | 217.8 tok/s | 240 |

读法：

- **7B 在这 8 对上与 4B 打平**，两轮结论完全一致。慢在输出长度：同样 8 对，7B 花 871 token，
  4B 花 342 token——模型把"先推理再回答"写进了正文，而模板里没有可以关掉它的开关。
- 打平只覆盖"两个写法是不是同一个东西"。把样本扩到 2019 的 138 列之后，`kind` 一致 96.4%、
  `option` 71.0%、`group` 只有 5.1%：7B 倾向按选项各造一个组名。这条见
  [`benchmark.md`](benchmark.md)，选型的结论不受影响（2.0-Flash 是内存不够、1B 是准确率不够），
  但"7B 可以放心顶替 4B"这个说法不成立。
- 成本按同口径算每列 406.7 token、6.6 秒纯推理，是 4B 的 7.4 倍和 9 倍；早期版本用的"每列
  49.3 秒"把调用之间的空档也摊进了分母，那个数已经作废。
- **1B 不能用**。它在 p2/p3/p4（GCP 系、云服务系）上连续判错，两轮结论还不一致；这类错法恰好是
  取值统一最怕的：判成 false 就不合并，问题被留到下游。
- 1B 的失败不是"小模型一定不行"的普遍结论，只是这一档在本任务上不行。

## 五、Q3 与 Q4 的取舍

| 项 | Q4_K_M | Q3_K_M |
|---|---|---|
| 权重 | 4.59 GiB | 3.77 GiB |
| 权重 + 8k KV 实测占用 | 约 5.8 GiB，100% GPU | 预计低约 0.8 GiB |
| 实测吞吐 | 57–64 tok/s | 未测 |
| 实测风险 | 无解析失败、无降级 | 未测 |

省下的 0.8 GiB 换不到新能力（Q4 已经全量驻留，不会再被换出），却要承担量化损失，因此取 Q4。
Q5_K_M 与 Q8_0 需要切层到内存，吞吐必然掉，而 Q4 的质量闸门已经达标，没有升级动力。

## 六、成本侧观察（2019 清洗，进行中）

同一套提示词、同一份列画像，只换模型后每列的代价：

| 指标 | qwen3.5:4b | openPangu-7B Q4_K_M |
|---|---|---|
| 每列输出 token（中位） | 54.4 | 602.0 |
| 单次调用中位耗时 | 13.1 s | 13.8 s |
| 2019 清洗调用次数 | 17 | 49（截至 74 批中的 49 批） |
| 2019 清洗输出 token 合计 | 15,877 | 48,476（未跑完） |

token 是 11 倍——这个差不是提示词造成的，是 7B 每列都要写 300–400 token 推理正文。
批量越小差距越明显，所以这份数据只适用"每批 4 列"的盘古配置，不能直接外推到 qwen 的每批 18 列。

## 七、复现命令

```powershell
# 1. 硬件闸门（约 2 秒，不调模型）
python pangu/probe/hardware.py

# 2. 两条后端路径连通性（Ollama / llama.cpp，前者本次可用）
python pangu/probe/backend_check.py

# 3. 能力探针（每个模型 2–3 轮，约 1 分钟/轮）
$env:LLM_SURVEY_MODEL="pangu-emb-7b"; python pangu/probe/capability.py --rounds 2
$env:LLM_SURVEY_MODEL="pangu-emb-1b"; python pangu/probe/capability.py --rounds 2

# 4. 决策成本汇总（只读 decisions/，产出 decisions_summary.json）
python pangu/probe/decisions_summary.py --md --layers 2019
python pangu/probe/decisions_summary.py --md --dir llm/decisions --layers 2019
```

## 八、没验证的部分

- 只有 8 对样本、2 轮重复。它足以否掉 1B，不足以给 7B 一个精确的准确率区间。
- 温度固定 0、seed 42，没有测采样波动；跨轮一致只反映"同参数下是否稳定"。
- 2019 清洗跑到 156/290 列后终止，跨年对齐阶段（组路径统一、取值合并）没有实跑，因此判断层
  的结论不能推成"对齐产物也一致"。
- 2020 起的组路径一致性只抽了 2 个前缀各 5 列（都是 5/5 同组），不是全量统计。
- 盘古不支持 `format=json`（`Failed to initialize samplers`），实测靠提示词约束 + 容错解析达到
  100% 合法率；这是当前提示词和这批数据的结果，换更复杂的 schema 未必保持。
