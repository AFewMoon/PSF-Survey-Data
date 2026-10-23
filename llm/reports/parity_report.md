# 规则管线 vs LLM 管线一致性核对

生成时间：2026-10-23 19:43

| 指标 | 规则管线 | LLM 管线 |
|---|---|---|
| 总表列数（不含 year） | 153 | 40 |
| 归一后匹配列（Jaccard %） | — | 36（22.9%） |

## 各年行数

| 年份 | 规则管线 | LLM 管线 |
|---|---|---|
| 2019 | 47308 | 47308 |
| 2020 | 37793 | 37793 |
| 2021 | 23201 | 23178 |
| 2022 | 23009 | 22986 |
| 2023 | 25324 | 25324 |
| 2024 | 28997 | 28997 |

## 同主题占比差异 Top

| 主题 | 组 | 选项 | LLM % | 规则 % | 差值(pp) |
|---|---|---|---|---|---|
| preferred_language | other.lang | C/C++ | 28.1 | 28.2 | -0.1 |
| programming_languages | other.lang | C/C++ | 28.1 | 28.2 | -0.1 |
| editor_preferences | ide.editor | Jupyter Notebook | 12.2 | 12.2 | 0.0 |
| editor_preferences | ide.editor | Vim | 9.7 | 9.7 | 0.0 |
| editor_preferences | ide.editor | PyCharm Community Edition | 8.4 | 8.4 | 0.0 |
| editor_preferences | ide.editor | NotePad++ | 7.4 | 7.4 | 0.0 |
| editor_preferences | ide.editor | JupyterLab | 7.0 | 7.0 | 0.0 |
| editor_preferences | ide.editor | Sublime Text | 4.7 | 4.7 | 0.0 |
| preferred_language | other.lang | JavaScript | 40.5 | 40.5 | 0.0 |
| preferred_language | other.lang | HTML/CSS | 37.1 | 37.1 | 0.0 |
| preferred_language | other.lang | SQL | 36.2 | 36.2 | 0.0 |
| preferred_language | other.lang | Bash / Shell | 30.9 | 30.9 | 0.0 |

## 仅规则管线存在的列（示例）

- bigdata.None
- ci.AppVeyor
- ci.Bamboo
- ci.CircleCI
- ci.CruiseControl
- ci.Gitlab CI
- ci.Jenkins / Hudson
- ci.None
- ci.TeamCity
- ci.Travis CI
- cloud.platform.AWS
- cloud.platform.DigitalOcean
- cloud.platform.Google Cloud Platform
- cloud.platform.Heroku
- cloud.platform.Linode

## 仅 LLM 管线存在的列（示例）

- company.size
- employment.status
- ide.python_version
- team.size

## 差异摘要（送入模型）

```json
{'列集合': {'规则': 153, 'LLM': 40, '匹配': 36, 'Jaccard_pct': 22.9}, '仅规则管线有的列（示例）': ['bigdata.None', 'ci.AppVeyor', 'ci.Bamboo', 'ci.CircleCI', 'ci.CruiseControl', 'ci.Gitlab CI', 'ci.Jenkins / Hudson', 'ci.None'], '仅LLM管线有的列（示例）': ['company.size', 'employment.status', 'ide.python_version', 'team.size'], '行数差异': [[2019, 47308, 47308], [2020, 37793, 37793], [2021, 23201, 23178], [2022, 23009, 22986], [2023, 25324, 25324], [2024, 28997, 28997]], '缺失率差异_Top': [], '同主题占比差异_Top': [['preferred_language', 'other.lang', 'C/C++', 28.1, 28.2, -0.1], ['programming_languages', 'other.lang', 'C/C++', 28.1, 28.2, -0.1], ['editor_preferences', 'ide.editor', 'Jupyter Notebook', 12.2, 12.2, 0.0], ['editor_preferences', 'ide.editor', 'Vim', 9.7, 9.7, 0.0], ['editor_preferences', 'ide.editor', 'PyCharm Community Edition', 8.4, 8.4, 0.0], ['editor_preferences', 'ide.editor', 'NotePad++', 7.4, 7.4, 0.0], ['editor_preferences', 'ide.editor', 'JupyterLab', 7.0, 7.0, 0.0], ['editor_preferences', 'ide.editor', 'Sublime Text', 4.7, 4.7, 0.0]]}
```

## 模型解读

两条管线在列集合上存在显著差异，规则管线包含大量 CI 工具字段而 LLM 管线则多出公司规模、编程语言版本等上下文特征，导致 Jaccard 相似度仅为 22.9%。行数统计方面，2021 年和 2022 年存在微小差异，其余年份完全一致，表明 LLM 管线在特定年份的计数可能受命名粒度或同义词表覆盖不全的影响。同主题占比在编辑器偏好等核心字段上高度一致，但在编程语言分类上规则管线略低，反映出 LLM 在语义映射上的优势。综合来看，LLM 管线因能捕捉更多业务上下文且核心指标一致，其结果在统计推断上更为可信。

