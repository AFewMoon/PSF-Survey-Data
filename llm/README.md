# LLM 驱动管线（Qwen3.5-4B + Ollama）

用本地 `qwen3.5:4b` 端到端驱动 2019–2024 PSF 调查数据的**清洗 → 对齐 → 统计 → 图表 → 一致性核对**：
模型负责所有语义判断（列语义、清洗算子、跨年组路径/选项映射、统计口径、分节解读、图表规格），
Python 只负责取样、校验、执行与报告。全部产物写入本目录，**不改动**根目录既有的
`cleaned/`、`aligned/`、`analysis/`、`charts/`、`reports/` 与原始 CSV。

## 快速开始

```powershell
# 前置：本地 Ollama 服务（模型 qwen3.5:4b 已拉取）
ollama serve

cd llm
python run_llm_pipeline.py --stage ping           # 健康检查，打印模型名与 digest
python run_llm_pipeline.py --stage selftest       # 离线自检（12 项，不调模型）
python run_llm_pipeline.py --stage all            # 全流程（命中缓存约 2.6 分钟）
python run_llm_pipeline.py --stage clean --years 2023 2024
python run_llm_pipeline.py --stage all --refresh  # 忽略缓存重算（约 30 分钟）
python run_llm_pipeline.py --stage all --dry-run  # 不调模型，走确定性默认决策
python run_llm_pipeline.py --stage clean --apply-review  # 执行已人工确认的删列
```

> 若 `ollama serve` 启动失败并报 `mkdir ...\models: Access is denied`，说明 `OLLAMA_MODELS`
> 指向了受保护目录；改为 `$env:OLLAMA_MODELS="$env:USERPROFILE\.ollama\models"` 后再启动。

| 参数 | 说明 |
|---|---|
| `--stage` | `ping / selftest / profile / clean / align / stats / charts / parity / all` |
| `--years` | 只跑指定年份（默认 2019–2024） |
| `--refresh` | 忽略缓存重新请求模型 |
| `--dry-run` | 不调模型：只出画像/默认决策，链路上不产生任何模型决策 |
| `--batch-size` | 每批列数（默认 18，按字符预算二次切批） |
| `--apply-review` | 执行 `decisions/review_approved.json` 中已确认的删列 |
| `--rebuild-profile` | 强制重算列画像 |

## 工作方式

核心原则：**模型只产出可校验的决策 JSON，不接触数据本体**。模型看到的是「列名 + 非空率 +
基数 + 至多 6 个截断样本值」，永远不逐行处理 18.5 万行。

1. **画像**（`profiles.py`）：顺序扫描每年原始 CSV，产出 `decisions/profile/<year>.json`。
   自由文本列只保留结构特征（非空率/基数/主取值占比），不送原文。
2. **清洗**（`clean_stage.py`）：分批请求列语义（`single_choice / multi_option / multi_level /
   binary / numeric / id / free_text / meta`）与清洗计划；算子白名单
   `keep/rename/binarize/to_numeric/normalize_cell/drop_empty_rows/drop_empty_cols/drop_dup_rows/drop_dup_cols/drop_col`，
   每条附理由。`drop_col` 一律进人工确认，不直接执行。
3. **对齐**（`align_stage.py`）：三步——组路径统一 → 列名重命名（重名回退确定性归一，冲突列加
   `__dup`）→ 单选取值统一；最后取各年列名**交集**纵向合并总表。
4. **统计**（`stats_stage.py`）：模型给 `stats_plan`（主题→组前缀、Top-N、分母），Python 计算
   `stats/*.csv`，再逐主题请求解读，拼装 `reports/analysis_report.md`。
5. **图表**（`chart_stage.py`）：模型给图表规格（类型/数据文件/标题/Top-N/理由），校验数据引用
   存在后用 matplotlib（Agg）渲染 `charts/*.png`。
6. **一致性核对**（`parity.py`）：与规则管线总表做向量化比对（Jaccard、非空率差、同主题占比差），
   仅一次模型调用解读分歧。

确定性护栏（`decision_schema.py`）：算子白名单、列/选项必须存在、删行删列比例上限
（`MAX_DROP_ROW_SHARE` / `MAX_DROP_COL_SHARE`）、取值改写覆盖率（`MAX_EXTRA_MISSING_SHARE`）、
映射唯一性、**聚类塌缩防护**（一簇不得吞并 ≥50% 或全部选项，且 ≤4 项）、图表系列 ≤30。

## 目录与产物

```
llm/
├── run_llm_pipeline.py          # 唯一 CLI 入口
├── llm_survey/                  # 实现（config/textnorm/dataio/profiles/ollama_client/cache/
│                                #  decision_schema/prompts/clean_stage/align_stage/
│                                #  stats_stage/chart_stage/parity/reporting/selftest）
├── decisions/                   # 模型决策缓存（profile/clean/align/stats/chart/parity）
├── cleaned/cleaned_llm_<year>.csv
├── aligned/cleaned_aligned_llm_<year>.csv
│         /survey_2019_2024_master_llm.csv
│         /column_mapping.csv  /value_mapping.csv
├── stats/profile_llm_*.csv, trends_llm_*.csv, singles_llm.csv
├── charts/*.png
└── reports/cleaning_report.md, alignment_report.md, analysis_report.md,
           charts_report.md, parity_report.md
```

> `llm/.gitignore` 排除了 `cleaned/*.csv` 与 `aligned/cleaned_aligned_llm_*.csv`（约 386 MB）：
> 它们是可由 `decisions/` 缓存完全复现的逐年中转数据，且与根目录 `cleaned/`、`aligned/` 高度重复。
> 总表、映射表、统计表、图表与报告均已入库。

## 缓存、断点续跑与人工修订

- 缓存键 = `sha256(stage | model digest | prompt_version | payload)`，写盘为「临时文件 + 原子替换」。
- 决策文件即唯一事实来源，含 `response`（模型原始 JSON）、`duration_s`、`fallback`、`reviewed`、
  `payload_summary`、`prompt_version`，便于审计与重放。
- **断点续跑**：任何阶段中断后重跑同一命令即可，已完成的批次直接命中缓存。
- **人工修订**：直接编辑 `decisions/<stage>/<hash>.json` 的 `response` 字段并置 `reviewed: true`，
  再跑对应阶段即按修订结果执行（无需 `--refresh`）。
- **高危操作**：`drop_col` 写入清洗报告的「待确认」列表；把要执行的列写入
  `decisions/review_approved.json` 后用 `--apply-review` 重跑 clean 阶段。
- **提示词升级**：改 `config.PROMPT_VERSION` 中对应版本号即可让该阶段全部缓存失效。

## 模型配置与耗时

| 项 | 值 |
|---|---|
| 模型 | `qwen3.5:4b`（Ollama，digest `d8b0f5e9760cd168`） |
| 采样 | temperature=0、seed=42、`format=json`、`think=false`（**关闭 thinking 是可行性前提**：单批 87s → 10.8s） |
| 上下文/输出 | `num_ctx=8192`，`num_predict` 按列数估算（每列约 80 tok） |
| 串行请求 | 8 GB 显存下单并发 + `keep_alive=30m`，避免模型重载 |
| 决策文件 | 230 个（clean 149 / align 58 / stats 14 / profile 6 / chart 1 / parity 2） |
| 首次全量 | 约 30 分钟（本机 RTX 5070 Laptop 8 GB） |
| 缓存后全量 | 2.6 分钟（模型调用 0 次） |

## 本次运行结果

**清洗**：2019 288 处重命名（整句表头 → 点分标准名）；2020 删全空行 16,669 行
（54,462→37,793）；2021/2022/2023/2024 分别删重复行 438/302/377/271；多选题二值化
218/227/356/344/417/492 列；六年均无待确认删列。

**对齐**：164 个题目组，模型统一 21 个组路径、171 处列名重命名、9 个选项同义簇、16 个 `__dup`
冲突列；跨年共有列 40，总表 185,586 行。

**统计**：8 个主题、17 个统计 CSV、8 节模型解读。

**图表**：10 张 PNG（6 张 2024 画像 + 4 张跨年趋势）。

**一致性核对**：规则管线 153 列 / LLM 管线 40 列，归一后匹配 36 列（Jaccard 22.9%）；
匹配列的非空率差异为 0 条，同主题占比差异 12 条且最大仅 0.1 pp —— 说明**同一列名下的执行结果与
规则管线一致**，差异主要来自「哪些列被认定为同一题」以及行级去重口径（2021/2022 各差 23 行）。

## 已知局限

1. **选项级归并保守**：4B 模型在选项归并上频繁「整列塌缩」（把一列 24 个选项并成 1 个），被塌缩
   护栏全部拒绝，因此 `value_mapping.csv` 本次为空；`alignment_report.md`「校验提示」列出了每条被拒
   建议。宁可不合并，也不误合并。
2. **组路径统一覆盖有限**：模型只对 21 个组路径做出高置信映射（如 `isolate.environments` →
   `ide.isolate`），远少于规则管线内置的手工同义词表，故跨年共有列只有 40 列（规则管线 153 列）。
3. **2019 年结构差异**：2019 表头是整句问句 + 网格题，模型给出的组名与 2020+ 并不总能对齐
   （如 2019 的 `ide.editor.*` 与 2020 的 `ide.editor.*` 选项文本不同），进一步压缩了交集。
4. **叙述类输出不稳定**：4B 在分节解读中偶有自相矛盾的表述（如「从 35.8% 上升至 30.9%」），
   或把 `is.python.main`（是否以 Python 为主）当版本题解读；数值以 CSV 为准，文字仅作参考。
5. **统计计划有冗余**：模型给出的 8 个主题里 `preferred_language` 与 `programming_languages`
   都指向 `other.lang`，报告存在重复章节（保留模型原始计划，未做人工去重）。
6. **只做元数据级决策**：所有判断基于列名与聚合统计，不逐行调用模型，因此无法发现行级异常值。
