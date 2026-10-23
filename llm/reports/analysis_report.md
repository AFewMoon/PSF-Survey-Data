# LLM 驱动统计分析报告

生成时间：2026-10-23 19:43

模型：`qwen3.5:4b`｜口径：多选题按当年总样本（或作答人数）为分母，单选题按作答人数为分母；数据范围 2019–2024，总表 185,586 行。

**分析计划思路（模型）**：聚焦开发者画像（语言、IDE、团队）与工具生态，利用 Python 版本作为关键单变量，通过总样本分母计算占比，对比 2019-2024 年技术演进趋势。

## 主题清单

| 主题 | 题目组 | Top-N | 分母 | 理由 |
|---|---|---|---|---|
| preferred_language | other.lang | 10 | total | 核心技能画像，跨年份对比最稳定 |
| primary_ide | ide.editor | 10 | total | 开发环境变迁，反映技术栈迭代 |
| python_usage | ide.python_version | 10 | total | Python 普及度与版本演进趋势 |
| team_size | team | 10 | total | 开发者所处组织规模分布变化 |
| employment_status | employment | 10 | total | 就业形态（全职/自由）结构演变 |
| company_size | company | 10 | total | 企业规模偏好，反映行业集中度 |
| programming_languages | other.lang | 8 | total | 多语言技能分布，补充画像维度 |
| editor_preferences | ide.editor | 8 | total | 编辑器生态竞争与主流更替 |

## preferred_language

数据文件：`llm/stats/profile_llm_preferred_language.csv`、`llm/stats/trends_llm_preferred_language.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| other.lang | JavaScript | 40.54 | 11754 |
| other.lang | HTML/CSS | 37.11 | 10761 |
| other.lang | SQL | 36.19 | 10493 |
| other.lang | Bash / Shell | 30.9 | 8959 |
| other.lang | C/C++ | 28.15 | 8163 |
| other.lang | Java | 18.78 | 5445 |
| other.lang | TypeScript | 16.67 | 4834 |
| other.lang | None | 12.82 | 3718 |
| other.lang | C# | 10.68 | 3097 |
| other.lang | Go | 8.71 | 2526 |

2024 年首选编程语言中，JavaScript、HTML/CSS 和 SQL 占比最高，分别为 40.5%、37.1% 和 36.2%。其中 TypeScript 从 2019 年的 6.1% 跃升至 2024 年的 16.7%，增幅达 10.6 个百分点最为显著，而 Bash/Shell 则从 27.4% 下降至 30.9% 后趋于平稳。需注意，此类自报数据受问卷措辞及选项变动影响，且未区分具体使用场景，可能高估前端相关语言的选择率。


## primary_ide

数据文件：`llm/stats/profile_llm_primary_ide.csv`、`llm/stats/trends_llm_primary_ide.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| ide.editor | Jupyter Notebook | 12.25 | 3552 |
| ide.editor | Vim | 9.66 | 2801 |
| ide.editor | PyCharm Community Edition | 8.38 | 2431 |
| ide.editor | NotePad++ | 7.4 | 2145 |
| ide.editor | JupyterLab | 6.98 | 2025 |
| ide.editor | Sublime Text | 4.74 | 1375 |
| ide.editor | PyCharm Professional Edition | 3.91 | 1133 |
| ide.editor | IDLE | 3.28 | 950 |
| ide.editor | Spyder | 2.13 | 619 |
| ide.editor | IntelliJ IDEA | 2.12 | 615 |

2024 年开发者首选编辑器中，Jupyter Notebook 占比 12.2% 位居第一，Vim 以 9.7% 紧随其后，PyCharm Community Edition 以 8.4% 位列第三。与 2023 年相比，Jupyter Notebook 和 Vim 的占比均出现下降，其中 Vim 降幅最为明显，从 10.8% 降至 9.7%，下降了 1.1 个百分点。这一趋势可能受到自报抽样误差、问卷措辞微调或选项排序变动等调查方法因素的影响。


## python_usage

数据文件：`llm/stats/profile_llm_python_usage.csv`、`llm/stats/trends_llm_python_usage.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| ide.python_version | Yes | 85.83 | 24887 |
| ide.python_version | No, I use Python as a secondary language | 14.17 | 4108 |

在 Python 使用场景中，2024 年选择“是”的比例最高，达到 85.8%，其次是“作为次要语言使用”的 14.2%。从 2020 年到 2024 年，将 Python 作为主要语言使用的比例上升最为显著，累计增长了 4.8 个百分点，而将其作为次要语言使用的比例则呈现下降趋势。这一变化趋势可能受到自报抽样误差、问卷措辞微调或选项设置变动等因素的影响。


## team_size

数据文件：`llm/stats/profile_llm_team_size.csv`、`llm/stats/trends_llm_team_size.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| team | size | 28.34 | 8219 |

在团队规模偏好中，2024 年选择 25 至 29 人的占比最高，达到 28.3%，紧随其后的是 2022 年的 31.7% 和 2020 年的 31.6%。与 2019 年相比，2024 年选择 25 至 29 人团队的占比下降了 6.8 个百分点，显示出对中等规模团队的偏好有所减弱。由于该数据基于自报抽样且选项范围固定，这一趋势可能受到受访者对团队效率认知变化或问卷措辞微调的影响。


## employment_status

数据文件：`llm/stats/profile_llm_employment_status.csv`、`llm/stats/trends_llm_employment_status.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| employment | status | 57.59 | 16698 |

2024 年选择'就业'的比例为 57.6%，是 2019 年以来第二低的水平，而 2020 年曾达到 66.3% 的峰值。从 2020 年到 2021 年，该选项占比下降了 6.9 个百分点，是期间变化最剧烈的年份。由于此类数据依赖受访者自报且选项设置可能随年份调整，实际趋势需结合具体问卷措辞和抽样方法谨慎解读。


## company_size

数据文件：`llm/stats/profile_llm_company_size.csv`、`llm/stats/trends_llm_company_size.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| company | size | 43.14 | 12508 |

在 2019 年至 2024 年的调查中，中型企业占比始终处于主流地位，其中 2020 年达到峰值 51.3%，随后在 2022 年回落至 52.9% 后持续下降，至 2024 年降至 43.1%。2020 年中型企业占比较 2019 年上升了 11.9 个百分点，是期间变化最显著的年份。由于该数据基于自报抽样且选项口径可能随年份调整，这一趋势需结合具体问卷措辞及统计边界谨慎解读。


## programming_languages

数据文件：`llm/stats/profile_llm_programming_languages.csv`、`llm/stats/trends_llm_programming_languages.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| other.lang | JavaScript | 40.54 | 11754 |
| other.lang | HTML/CSS | 37.11 | 10761 |
| other.lang | SQL | 36.19 | 10493 |
| other.lang | Bash / Shell | 30.9 | 8959 |
| other.lang | C/C++ | 28.15 | 8163 |
| other.lang | Java | 18.78 | 5445 |
| other.lang | TypeScript | 16.67 | 4834 |
| other.lang | None | 12.82 | 3718 |

2024 年编程语言选择中，JavaScript、HTML/CSS 和 Bash/Shell 占比最高，分别为 40.5%、37.1% 和 30.9%。其中 Bash/Shell 从 2020 年的 35.8% 上升至 2024 年的 30.9% 虽呈下降趋势，但结合 TypeScript 从 6.1% 激增至 16.7% 的显著增长来看，前端与脚本语言仍是主流。需注意，此类自报数据受问卷措辞及选项变动影响，可能无法完全反映实际技术栈的细微变化。


## editor_preferences

数据文件：`llm/stats/profile_llm_editor_preferences.csv`、`llm/stats/trends_llm_editor_preferences.csv`

| 题目组 | 选项 | 占比 % | n |
|---|---|---|---|
| ide.editor | Jupyter Notebook | 12.25 | 3552 |
| ide.editor | Vim | 9.66 | 2801 |
| ide.editor | PyCharm Community Edition | 8.38 | 2431 |
| ide.editor | NotePad++ | 7.4 | 2145 |
| ide.editor | JupyterLab | 6.98 | 2025 |
| ide.editor | Sublime Text | 4.74 | 1375 |
| ide.editor | PyCharm Professional Edition | 3.91 | 1133 |
| ide.editor | IDLE | 3.28 | 950 |

2024 年开发者编辑器偏好中，Jupyter Notebook 以 12.2% 位居第一，Vim 以 9.7% 紧随其后，PyCharm Community Edition 占比 8.4% 位列第三。与 2019 年相比，Jupyter Notebook 和 Vim 的占比均出现显著下降，分别减少了 0.9 和 0.9 个百分点，显示出传统编辑器与交互式环境在主流选择中的相对萎缩。这一趋势可能源于问卷选项的重新排序或开发者对编辑器功能认知的变化，需结合自报抽样数据的具体措辞进行审慎解读。


## 单列分布

覆盖列：`ide.python_version`

明细见 `llm/stats/singles_llm.csv`。


## 模型调用

- stats_plan: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
- stats_narrative: 缓存命中 1 / 新增 0
