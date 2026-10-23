# LLM 驱动跨年对齐报告

生成时间：2026-10-23 23:25

模型：`qwen3.5:4b`（temperature=0.0, seed=42）｜管线：组路径快对齐 → 逐对判同题 → 闭集命名 → 重命名 → 候选对归并选项/取值 → 共有列纵向合并

## 对齐统计

- 跨年共有列：110
- 题目组：164 个（其中 20 个被映射到其他标准路径）
- 封闭候选路径：84 个
- 列名重命名：305
- 选项同义簇：31
- 候选对判定：162 对（接受 34 对）
- 取值统一记录：5217
- `__dup` 冲突列：15
- 总表行数：185586

## Few-shot 与评测口径

- 留出年份：2023,2024（这些年份的人工映射**不进入**提示词，仅用于对账）
- few-shot 来源年份：(2019, 2020, 2021, 2022)；留出年份：[2023, 2024]（不参与提示词）

## 各年列数

| 年份 | 对齐后列数 | 进入总表的列数 |
|---|---|---|
| 2019 | 290 | 110 |
| 2020 | 264 | 110 |
| 2021 | 387 | 110 |
| 2022 | 403 | 110 |
| 2023 | 491 | 110 |
| 2024 | 573 | 110 |

## 模型判定的组路径统一（部分）

| 原路径 | 标准路径 | 涉及年份 |
|---|---|---|
| bigdata.solution | bigdata | 2023,2024 |
| bigdata.work | bigdata | 2023,2024 |
| cloud.platforms | cloud.platform | 2019 |
| data.frameworks | frameworks | 2020,2021,2022 |
| frameworks.cm | configuration.management | 2019 |
| frameworks.data | frameworks | 2019 |
| frameworks.web | web.frameworks | 2019 |
| ide.databases | database | 2019 |
| ide.isolate | environments.isolate | 2019 |
| ide.os | devenv.os | 2019 |
| ide.python2_version | python2.version.most | 2019 |
| ide.python3_version | python3.version.most | 2019 |
| ide.tools.bigdata | bigdata | 2019 |
| ide.tools.ci | ci | 2019 |
| ide.upgrade | python.version.upgrade | 2019 |
| industry.company | which_of_the_following_industries_do_you_develop_for | 2019 |
| isolate.environments | environments.isolate | 2020,2021,2022 |
| job | employment.status | 2021,2022,2023,2024 |
| most.of.the.time.do.you | most_of_the_time_do_you | 2019 |
| role.architect | job.role | 2019 |

## 列名重命名示例（每年 8 条）

**2019**
- `ide.python2_version` -> `python2.version.most`（llm）
- `ide.python3_version` -> `python3.version.most`（llm）
- `ide.upgrade.ActivePython` -> `python.version.upgrade.ActivePython`（llm）
- `ide.upgrade.Anaconda` -> `python.version.upgrade.Anaconda`（llm）
- `ide.upgrade.Automatic upgrade via cloud provider` -> `python.version.upgrade.Automatic upgrade via cloud provider`（llm）
- `ide.upgrade.Build from source` -> `python.version.upgrade.Build from source`（llm）
- `ide.upgrade.Enthought` -> `python.version.upgrade.Enthought`（llm）
- `ide.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（llm）

**2020**
- `other.lang.Other` -> `other.lang.Other - Write In`（llm）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`（normalized）
- `python.version.upgrade.Other` -> `python.version.upgrade.Other - Write In`（llm）
- `isolate.environments.None` -> `environments.isolate.None`（llm）
- `isolate.environments.Virtualenv` -> `environments.isolate.virtualenv`（llm）
- `isolate.environments.Pipenv` -> `environments.isolate.Pipenv`（llm）
- `isolate.environments.Poetry` -> `environments.isolate.Poetry`（llm）

**2021**
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`（normalized）
- `isolate.environments.None` -> `environments.isolate.None`（llm）
- `isolate.environments.Virtualenv` -> `environments.isolate.Virtualenv`（llm）
- `isolate.environments.Pipenv` -> `environments.isolate.Pipenv`（llm）
- `isolate.environments.Poetry` -> `environments.isolate.Poetry`（llm）
- `isolate.environments.Conda` -> `environments.isolate.Conda`（llm）
- `isolate.environments.Docker` -> `environments.isolate.Docker`（llm）

**2022**
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-provided Python (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-provided Python`（normalized）
- `isolate.environments.None` -> `environments.isolate.None`（llm）
- `isolate.environments.Virtualenv` -> `environments.isolate.Virtualenv`（llm）
- `isolate.environments.Pipenv` -> `environments.isolate.Pipenv`（llm）
- `isolate.environments.Poetry` -> `environments.isolate.Poetry`（llm）
- `isolate.environments.Conda` -> `environments.isolate.Conda`（llm）
- `isolate.environments.Docker` -> `environments.isolate.Docker`（llm）

**2023**
- `other.purposes.Multimedia applications development (apps handling various types of multimedia content, e_g_ audio, graphics, etc_)` -> `other.purposes.Multimedia applications development`（normalized）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-wide package-management tool (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-wide package-management tool`（normalized）
- `run.in.cloud.On a platform-as-a-service (such as Heroku or Google App Engine)` -> `run.in.cloud.On a platform-as-a-service`（normalized）
- `run.in.cloud.Serverless (such as via AWS Lambda or Cloud Functions)` -> `run.in.cloud.Serverless`（normalized）
- `develop.for.cloud.Locally with virtualenv (or similar)` -> `develop.for.cloud.Locally with virtualenv`（normalized）
- `develop.for.cloud.In remote development environments (like Gitpod, GitHub Codespaces, etc_)` -> `develop.for.cloud.In remote development environments`（normalized）
- `orm.I don’t do database development` -> `orm.I don't do database development`（normalized）

**2024**
- `other.purposes.Multimedia applications development (apps handling various types of multimedia content, e_g_ audio, graphics, etc_)` -> `other.purposes.Multimedia applications development`（normalized）
- `python.version.upgrade.I don’t update` -> `python.version.upgrade.I don't update`（normalized）
- `python.version.upgrade.OS-wide package-management tool (via apt-get, yum, homebrew, etc_)` -> `python.version.upgrade.OS-wide package-management tool`（normalized）
- `python.version.why.The version I’m using meets all my needs` -> `python.version.why.The version I'm using meets all my needs`（normalized）
- `python.version.why.I haven’t had the time to update` -> `python.version.why.I haven't had the time to update`（normalized）
- `python.version.why.I’m concerned about the stability of the latest Python version` -> `python.version.why.I'm concerned about the stability of the latest Python version`（normalized）
- `python.version.why.It is our organization’s policy to only use a specific Python version` -> `python.version.why.It is our organization's policy to only use a specific Python version`（normalized）
- `python.version.why.I wasn’t aware that the latest Python version is available` -> `python.version.why.I wasn't aware that the latest Python version is available`（normalized）


## 取值统一示例

- 2019 `python2.version.most`：`Python 2.3` -> `Python 2_3`
- 2019 `python2.version.most`：`Python 2.6` -> `Python 2_6`
- 2019 `python2.version.most`：`Python 2.6` -> `Python 2_6`
- 2019 `python2.version.most`：`Python 2.1` -> `Python 2_1`
- 2019 `python2.version.most`：`Python 2.6` -> `Python 2_6`
- 2019 `python2.version.most`：`Python 2.0` -> `Python 2_0`
- 2019 `python2.version.most`：`Python 2.5` -> `Python 2_5`
- 2019 `python2.version.most`：`Python 2.0` -> `Python 2_0`
- 2019 `python2.version.most`：`Python 2.0` -> `Python 2_0`
- 2019 `python2.version.most`：`Python 2.0` -> `Python 2_0`
- 2019 `python2.version.most`：`Python 2.3` -> `Python 2_3`
- 2019 `python2.version.most`：`Python 2.3` -> `Python 2_3`
- 2019 `python2.version.most`：`Python 2.0` -> `Python 2_0`
- 2019 `python2.version.most`：`Python 2.6` -> `Python 2_6`
- 2019 `python2.version.most`：`Python 2.0` -> `Python 2_0`

## 校验提示

- binary.modules.language → other.lang: 取值指纹 Jaccard 0.15 低于 0.2，已保留原名
- 未知组路径：'how.involved.Multimedia applications development...'
- 未知组路径：'ide.editor.features.Run / debug...'
- app.publish → app.publish.where: 目标路径会与本组选项重复拼接，已保留原名
- are.you → are.you.datascientist: 目标路径会与本组选项重复拼接，已保留原名
- company.develop → company.develop.for: 目标路径会与本组选项重复拼接，已保留原名
- dependency → dependency.version: 目标路径会与本组选项重复拼接，已保留原名
- employment → employment.status: 目标路径会与本组选项重复拼接，已保留原名
- environments → environments.container: 目标路径会与本组选项重复拼接，已保留原名
- ide → ide.main: 目标路径会与本组选项重复拼接，已保留原名
- issue → issue.report: 目标路径会与本组选项重复拼接，已保留原名
- main → main.purposes: 目标路径会与本组选项重复拼接，已保留原名
- missing.features.main → missing.features.main.ide: 目标路径会与本组选项重复拼接，已保留原名
- python → python.years: 目标路径会与本组选项重复拼接，已保留原名
- python.version → python.version.most: 目标路径会与本组选项重复拼接，已保留原名
- python2.version → python2.version.most: 目标路径会与本组选项重复拼接，已保留原名
- python3.version → python3.version.most: 目标路径会与本组选项重复拼接，已保留原名
- several → several.projects: 目标路径会与本组选项重复拼接，已保留原名
- team → team.size: 目标路径会与本组选项重复拼接，已保留原名
- use.python → use.python.most: 目标路径会与本组选项重复拼接，已保留原名
- years.of → years.of.coding: 目标路径会与本组选项重复拼接，已保留原名
- p1: canonical 必须取自该对（"I don't do database development"），已忽略
- 2019 年模型归并导致 9 处同名冲突，已回退确定性归一
- 2021 年模型归并导致 5 处同名冲突，已回退确定性归一
- 2022 年模型归并导致 5 处同名冲突，已回退确定性归一
- 2023 年模型归并导致 3 处同名冲突，已回退确定性归一
- 2024 年模型归并导致 3 处同名冲突，已回退确定性归一

## 缓存

- group_pair: 缓存命中 1 / 新增 0；group_path: 缓存命中 3 / 新增 0
- pair_judge: 缓存命中 36 / 新增 0
- option_vocab: 按人工词表统一写法 78 处
- pair_judge: 缓存命中 11 / 新增 0（取值）


## 产出

- `llm/aligned/cleaned_aligned_llm_<year>.csv`
- `llm/aligned/survey_2019_2024_master_llm.csv`
- `llm/aligned/column_mapping.csv`、`llm/aligned/value_mapping.csv`
