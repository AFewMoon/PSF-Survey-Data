# LLM 驱动清洗报告

生成时间：2026-10-23 19:43

模型：`qwen3.5:4b`（temperature=0.0, seed=42, think=off）｜管线：列画像 → 模型语义标注 → 模型年度算子决策 → 校验 → 确定性执行

| 年份 | 行(前/后) | 列(前/后) | 空列 | 空行 | 重复行 | 重复列 | 多选归一 | 数值列 | 重命名 |
|---|---|---|---|---|---|---|---|---|---|
| 2019 | 47308/47308 | 290/290 | 0 | 0 | 0 | 0 | 218 | 1 | 288 |
| 2020 | 54462/37793 | 264/264 | 0 | 12554 | 4115 | 0 | 227 | 1 | 4 |
| 2021 | 23616/23178 | 387/387 | 0 | 0 | 438 | 0 | 356 | 1 | 2 |
| 2022 | 23288/22986 | 403/403 | 0 | 0 | 302 | 0 | 344 | 1 | 1 |
| 2023 | 25701/25324 | 491/491 | 0 | 0 | 377 | 0 | 417 | 1 | 1 |
| 2024 | 29268/28997 | 573/573 | 0 | 0 | 271 | 0 | 492 | 1 | 1 |

## 2019 年

- 列语义分布：single_choice=33、multi_option=218、multi_level=15、numeric=2、identifier=1、free_text=21
- 模型列标注降级：8 列（模型未覆盖，按表头结构默认）
- 算子决策：drop_empty_rows=保留（证据显示空行数为 0，无需删除。）；drop_empty_cols=保留（证据显示空列数为 0，无需删除。）；drop_dup_rows=保留（证据显示重复行数为 0，无需删除。）；drop_dup_cols=保留（证据显示重复列组数为 0，无需删除。）
- 决策说明：数据画像显示空行、空列、重复行及列均为 0，且无候选列，无需执行任何删除操作。

**校验提示（已按安全默认值处理，不静默丢弃）**

- Is Python the main language you use for your current projects?: 缺失标记过长，已忽略
- Is Python the main language you use for your current projects?: 缺失标记过长，已忽略

缓存：clean_semantics: 缓存命中 17 / 新增 0 | clean_plan: 缓存命中 1 / 新增 0

## 2020 年

- 列语义分布：single_choice=12、multi_option=239、multi_level=10、numeric=3
- 模型列标注降级：4 列（模型未覆盖，按表头结构默认）
- 算子决策：drop_empty_rows=执行（23.1% 空行过高，影响数据质量。）；drop_empty_cols=保留（无空列证据，保留现有数据。）；drop_dup_rows=执行（16668 行重复，占比 30.6%，需清洗。）；drop_dup_cols=保留（无重复列证据，保留现有数据。）
- 决策说明：删除 23.1% 空行及 30.6% 重复行，提升数据可用性。

缓存：clean_semantics: 缓存命中 15 / 新增 0 | clean_plan: 缓存命中 1 / 新增 0

## 2021 年

- 列语义分布：single_choice=12、multi_option=374、numeric=1
- 模型列标注降级：10 列（模型未覆盖，按表头结构默认）
- 算子决策：drop_empty_rows=保留（证据显示空行数为 0，无需删除。）；drop_empty_cols=保留（证据显示空列数为 0，无需删除。）；drop_dup_rows=执行（证据显示存在 415 条重复行，需删除。）；drop_dup_cols=保留（证据显示无重复列组，无需删除。）
- 决策说明：仅依据证据中 415 条重复行执行去重，其余操作因数据完整或无重复而拒绝。
- 模型新增缺失标记（已生效）：other, yes – please list:

**校验提示（已按安全默认值处理，不静默丢弃）**

- libraries.do: 缺失标记 'No' 是合法选项，已忽略
- libraries.publish: 缺失标记 'No' 是合法选项，已忽略

缓存：clean_semantics: 缓存命中 22 / 新增 0 | clean_plan: 缓存命中 1 / 新增 0

## 2022 年

- 列语义分布：single_choice=12、multi_option=356、multi_level=30、numeric=4、free_text=1
- 模型列标注降级：4 列（模型未覆盖，按表头结构默认）
- 算子决策：drop_empty_rows=保留（证据显示空行数为 0，无需删除。）；drop_empty_cols=保留（证据显示空列数为 0，无需删除。）；drop_dup_rows=执行（证据显示存在 279 条重复行，需删除。）；drop_dup_cols=保留（证据显示无重复列组，无需删除。）
- 决策说明：仅依据证据中 279 条重复行执行删除，其余列均无空或重复。
- 模型新增缺失标记（已生效）：other, python 2, python 2_1, python 2_2, python 2_3, python 2_5, python 2_7, python 3_5 or lower, python 3_6, python 3_7, python 3_8, python 3_9

**校验提示（已按安全默认值处理，不静默丢弃）**

- are.you.datascientist: 缺失标记 'No' 是合法选项，已忽略
- dependency.version: 缺失标记 'No' 是合法选项，已忽略
- libraries.do: 缺失标记 'No' 是合法选项，已忽略
- libraries.publish: 缺失标记 'No' 是合法选项，已忽略

缓存：clean_semantics: 缓存命中 23 / 新增 0 | clean_plan: 缓存命中 1 / 新增 0

## 2023 年

- 列语义分布：single_choice=19、multi_option=434、multi_level=33、numeric=2、free_text=3
- 模型列标注降级：4 列（模型未覆盖，按表头结构默认）
- 算子决策：drop_empty_rows=保留（证据显示空行数为 0，无需删除。）；drop_empty_cols=保留（证据显示空列数为 0，无需删除。）；drop_dup_rows=执行（证据显示存在 377 条重复行，需删除。）；drop_dup_cols=保留（证据显示无重复列组，无需删除。）
- 决策说明：仅依据证据中 377 条重复行执行删除，其余列均非空且无重复。

**校验提示（已按安全默认值处理，不静默丢弃）**

- kubernetes: 缺失标记 'No' 是合法选项，已忽略
- data.exploration: 缺失标记 'No' 是合法选项，已忽略
- ml.deployment: 缺失标记 'No' 是合法选项，已忽略
- collaborative.development: 缺失标记 'No' 是合法选项，已忽略

缓存：clean_semantics: 缓存命中 28 / 新增 0 | clean_plan: 缓存命中 1 / 新增 0

## 2024 年

- 列语义分布：single_choice=23、multi_option=514、multi_level=31、numeric=1、free_text=4
- 模型列标注降级：10 列（模型未覆盖，按表头结构默认）
- 算子决策：drop_empty_rows=保留（证据显示空行数为 0，无需删除。）；drop_empty_cols=保留（证据显示空列数为 0，无需删除。）；drop_dup_rows=执行（证据显示存在 271 条重复行，需删除。）；drop_dup_cols=保留（证据显示无重复列组，无需删除。）
- 决策说明：仅依据证据中 271 条重复行执行去重，其余操作因数据完整或无重复而拒绝。
- 模型新增缺失标记（已生效）：i'm not sure, less than usd 1,000, usd 1,000–5,000, usd 10,000–25,000, usd 5,000–10,000

**校验提示（已按安全默认值处理，不静默丢弃）**

- kubernetes: 缺失标记 'No' 是合法选项，已忽略
- data.exploration: 缺失标记 'No' 是合法选项，已忽略
- dashboard.creation: 缺失标记 'No' 是合法选项，已忽略
- ml.training: 缺失标记 'No' 是合法选项，已忽略
- ml.deployment: 缺失标记 'No' 是合法选项，已忽略
- ml.cloud: 缺失标记 'No' 是合法选项，已忽略
- ml.cloud.cost.impact: 缺失标记过长，已忽略
- ml.cloud.cost.impact: 缺失标记过长，已忽略
- ml.cloud.cost.impact: 缺失标记过长，已忽略
- ml.cloud.budget: 缺失标记 "I'm not sure" 是该列主取值（37.3%），已忽略
- collaborative.development: 缺失标记 'No' 是合法选项，已忽略
- monorepo: 缺失标记 'No' 是合法选项，已忽略
- binary.modules.creation: 缺失标记 'No' 是合法选项，已忽略

缓存：clean_semantics: 缓存命中 32 / 新增 0 | clean_plan: 缓存命中 1 / 新增 0

## 产出

- 清洗数据：`llm/cleaned/cleaned_llm_<year>.csv`
- 列决策明细：`llm/decisions/clean/<year>.columns.json`
- 决策缓存：`llm/decisions/clean/*.json`（含模型、耗时、理由，可人工修订后重放）
