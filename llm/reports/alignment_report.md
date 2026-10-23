# LLM 驱动跨年对齐报告

生成时间：2026-10-23 19:43

模型：`qwen3.5:4b`（temperature=0.0, seed=42）｜管线：模型统一组路径 → 模型归并选项写法 → 重命名 → 模型归并单选取值 → 共有列纵向合并

## 对齐统计

- 跨年共有列：40
- 题目组：164 个（其中 21 个被模型映射到其他标准路径）
- 列名重命名：171
- 选项同义簇：9
- 取值统一记录：0
- `__dup` 冲突列：16
- 总表行数：185586

## 各年列数

| 年份 | 对齐后列数 | 进入总表的列数 |
|---|---|---|
| 2019 | 290 | 40 |
| 2020 | 264 | 40 |
| 2021 | 387 | 40 |
| 2022 | 403 | 40 |
| 2023 | 491 | 40 |
| 2024 | 573 | 40 |

## 模型判定的组路径统一（部分）

| 原路径 | 标准路径 | 涉及年份 |
|---|---|---|
| documentation.tool.Other systems, please specify | documentation.tool.systems | 2023,2024 |
| first.learn.about.main | learning.source | 2021 |
| first.learn.about.main.ide | learning.source | 2020 |
| how.involved.Multimedia applications development (apps handling various types of multimedia content, e.g. audio, grap... | how.involved | 2023,2024 |
| how.involved.Other - Write In: | how.involved | 2022 |
| how.involved.Other, please specify: | how.involved | 2023,2024 |
| how.involved.fixed | how.involved | 2021 |
| how.often.use.main.ide | how.often.use.main | 2020 |
| ide.editor.features.Run / debug or edit code on remote machines (remote hosts, VMs, etc | ide.editor.features | 2023,2024 |
| ide.editor.features.Use NoSQL databases | ide.editor.features | 2024 |
| ide.editor.features.Use issue trackers | ide.editor.features | 2024 |
| ide.python2_version | ide.python_version | 2019 |
| ide.python3_version | ide.python_version | 2019 |
| ide.python_use | ide.python_version | 2019 |
| industry.development | industry.company | 2019 |
| is.python.main | ide.python_version | 2019,2020,2021,2022,2023,2024 |
| isolate.environments | ide.isolate | 2020,2021,2022 |
| missing.features.main.ide | missing.features.main | 2020 |
| ml.cloud.cost.impact | ml.cloud.budget | 2024 |
| other.-.write.in | other.write.in | 2019 |
| other.-.write.in.what.data.science.framework.s.do.you.use.in.addition.to.python | other.write.in.what.data.science.frameworks.do.you.use.in.addition.to.python | 2019 |

## 列名重命名示例（每年 8 条）

**2019**
- `is.python.main` -> `ide.python_version`（llm）
- `other.-.write.in.Other - Write In` -> `other.write.in.Other - Write In`（normalized）
- `ide.python_use` -> `ide.python_version__dup1`（llm）
- `ide.python_version` -> `ide.python_version__dup2`（llm）
- `ide.python2_version` -> `ide.python_version__dup3`（llm）
- `ide.python3_version` -> `ide.python_version__dup4`（llm）
- `ide.upgrade.I don’t update` -> `ide.upgrade.I don't update`（normalized）
- `ide.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc.)` -> `ide.upgrade.OS-provided Python`（normalized）

**2020**
- `is.python.main` -> `ide.python_version`（llm）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`（normalized）
- `isolate.environments.None` -> `ide.isolate.None`（llm）
- `isolate.environments.Virtualenv` -> `ide.isolate.Virtualenv`（llm）
- `isolate.environments.Pipenv` -> `ide.isolate.Pipenv`（llm）
- `isolate.environments.Poetry` -> `ide.isolate.Poetry`（llm）
- `isolate.environments.Conda` -> `ide.isolate.Conda`（llm）

**2021**
- `is.python.main` -> `ide.python_version`（llm）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`（normalized）
- `isolate.environments.None` -> `ide.isolate.None`（llm）
- `isolate.environments.Virtualenv` -> `ide.isolate.Virtualenv`（llm）
- `isolate.environments.Pipenv` -> `ide.isolate.Pipenv`（llm）
- `isolate.environments.Poetry` -> `ide.isolate.Poetry`（llm）
- `isolate.environments.Conda` -> `ide.isolate.Conda`（llm）

**2022**
- `is.python.main` -> `ide.python_version`（llm）
- `how.involved.Other - Write In:` -> `how.involved`（llm）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`（normalized）
- `isolate.environments.None` -> `ide.isolate.None`（llm）
- `isolate.environments.Virtualenv` -> `ide.isolate.Virtualenv`（llm）
- `isolate.environments.Pipenv` -> `ide.isolate.Pipenv`（llm）
- `isolate.environments.Poetry` -> `ide.isolate.Poetry`（llm）

**2023**
- `is.python.main` -> `ide.python_version`（llm）
- `other.purposes.Multimedia applications development (apps handling various types of multimedia content, e_g_ audio, graphics, etc_)` -> `other.purposes.Multimedia applications development`（normalized）
- `how.involved.Multimedia applications development (apps handling various types of multimedia content, e.g. audio, graphics, etc.)` -> `how.involved.)`（llm）
- `how.involved.Other, please specify:` -> `how.involved`（llm）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-wide package-management tool (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-wide package-management tool`（normalized）
- `run.in.cloud.On a platform-as-a-service (such as Heroku or Google App Engine)` -> `run.in.cloud.On a platform-as-a-service`（normalized）
- `run.in.cloud.Serverless (such as via AWS Lambda or Cloud Functions)` -> `run.in.cloud.Serverless`（normalized）

**2024**
- `is.python.main` -> `ide.python_version`（llm）
- `other.purposes.Multimedia applications development (apps handling various types of multimedia content, e_g_ audio, graphics, etc_)` -> `other.purposes.Multimedia applications development`（normalized）
- `how.involved.Multimedia applications development (apps handling various types of multimedia content, e.g. audio, graphics, etc.)` -> `how.involved.)`（llm）
- `how.involved.Other, please specify:` -> `how.involved`（llm）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-wide package-management tool (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-wide package-management tool`（normalized）
- `python.version.why.The version I’m using meets all my needs` -> `python.version.why.The version I'm using meets all my needs`（normalized）
- `python.version.why.I haven’t had the time to update` -> `python.version.why.I haven't had the time to update`（normalized）


## 取值统一

本轮没有产生单选取值统一：
- 确定性部分只合并 `norm_key` 完全相同（仅大小写/标点/空白差异）的取值；清洗阶段已做单元格归一，剩余变体为零
- 4B 模型的取值归并建议普遍是「整列塌缩」（把该列全部取值并成一个），被 `validate_cluster_batch` 的塌缩护栏全部拒绝，拒绝记录见「校验提示」

## 校验提示

- other.lang: 未知文本 'Bash'
- other.lang: 未知文本 'HTML'
- develop.for.cloud: 归并吞并 8/10 个选项，超过安全上限，已忽略
- packaging.tools: 归并吞并 15/15 个选项，超过安全上限，已忽略
- libraries: 归并吞并 2/2 个选项，超过安全上限，已忽略
- frameworks.support: 归并吞并 28/28 个选项，超过安全上限，已忽略
- dashboard.libraries: 归并吞并 8/8 个选项，超过安全上限，已忽略
- ai.tools.coding: 未知文本 'CodeWhisperer'
- ai.tools.coding: 未知文本 'Copilot'
- 2019 年模型归并导致 15 处同名冲突，已回退确定性归一
- 2020 年模型归并导致 1 处同名冲突，已回退确定性归一
- 2021 年模型归并导致 1 处同名冲突，已回退确定性归一
- 2022 年模型归并导致 1 处同名冲突，已回退确定性归一
- 2023 年模型归并导致 1 处同名冲突，已回退确定性归一
- 2024 年模型归并导致 4 处同名冲突，已回退确定性归一
- ide.python_version__dup2: 归并吞并 2/2 个选项，超过安全上限，已忽略
- ide.main: 归并吞并 24/24 个选项，超过安全上限，已忽略
- python3.version.most: 归并吞并 6/6 个选项，超过安全上限，已忽略

## 缓存

- group_path: 缓存命中 3 / 新增 0
- option_alias: 缓存命中 9 / 新增 0
- option_alias: 缓存命中 7 / 新增 0（取值）


## 产出

- `llm/aligned/cleaned_aligned_llm_<year>.csv`
- `llm/aligned/survey_2019_2024_master_llm.csv`
- `llm/aligned/column_mapping.csv`、`llm/aligned/value_mapping.csv`
