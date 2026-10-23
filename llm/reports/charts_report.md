# LLM 驱动图表报告

生成时间：2026-10-23 19:43

模型：`qwen3.5:4b`｜可用统计表 17 个｜生成图表 10 张

| 图表 | 类型 | 数据源 | 标题 | Top-N | 理由 |
|---|---|---|---|---|---|
| company_size_profile | bar | profile_llm_company_size.csv | 受访者公司规模分布 | 10 | 展示不同规模公司的受访者占比，了解样本结构。 |
| editor_pref_profile | hbar | profile_llm_editor_preferences.csv | 受访者首选编辑器排名 | 10 | 横向条形图适合长选项名，清晰展示编辑器偏好。 |
| employment_status_profile | bar | profile_llm_employment_status.csv | 受访者就业状态分布 | 10 | 直观呈现全职、兼职及自由职业者的比例。 |
| lang_pref_profile | hbar | profile_llm_preferred_language.csv | 受访者首选编程语言排名 | 10 | 展示各类语言（如 JS, SQL）的受欢迎程度。 |
| primary_ide_profile | hbar | profile_llm_primary_ide.csv | 受访者主要开发工具排名 | 10 | 对比 Jupyter Notebook 等主流 IDE 的使用情况。 |
| python_usage_profile | bar | profile_llm_python_usage.csv | 受访者 Python 使用情况 | 10 | 区分主要使用 Python 与仅作为辅助语言的群体。 |
| company_size_trend | line | trends_llm_company_size.csv | 近五年公司规模变化趋势 | 10 | 观察不同规模公司在样本中的比例随时间波动。 |
| editor_trend | line | trends_llm_editor_preferences.csv | 近五年编辑器偏好演变 | 10 | 追踪 Atom 到 JupyterLab 等工具的流行度变迁。 |
| lang_trend | line | trends_llm_programming_languages.csv | 近五年编程语言流行度 | 10 | 分析 Bash、C++ 等语言使用率的年度变化。 |
| team_size_trend | line | trends_llm_team_size.csv | 近五年团队规模变化趋势 | 10 | 展示不同团队规模受访者的比例随时间变化。 |

缓存：chart_spec: 缓存命中 1 / 新增 0

图表文件：`llm/charts/*.png`
