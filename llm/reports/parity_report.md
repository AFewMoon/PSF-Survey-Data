# 规则管线 vs LLM 管线一致性核对

生成时间：2026-10-23 22:59

评测口径：留出年份 2023,2024的人工映射未进入提示词；同名匹配列的一致性可视为留出测试结果。
| 指标 | 规则管线 | LLM 管线 |
|---|---|---|
| 总表列数（不含 year） | 153 | 110 |
| 归一后匹配列（Jaccard %） | — | 105（66.5%） |

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

- develop.for.cloud.Directly in the production environment
- develop.for.cloud.In Docker containers
- develop.for.cloud.In remote development environments
- develop.for.cloud.In virtual machines
- develop.for.cloud.Locally with virtualenv
- develop.for.cloud.With local system interpreter
- environments.isolate.virtualenv
- frameworks.ml.None
- ide.editor.Visual Studio Code
- main.purposes
- orm.Dejavu
- orm.Django ORM
- orm.Peewee
- orm.PonyORM
- orm.SQLAlchemy

## 仅 LLM 管线存在的列（示例）

- company.size
- employment.status
- python2.version.most
- python3.version.most
- team.size

## 差异摘要（送入模型）

```json
{'列集合': {'规则': 153, 'LLM': 110, '匹配': 105, 'Jaccard_pct': 66.5}, '仅规则管线有的列（示例）': ['develop.for.cloud.Directly in the production environment', 'develop.for.cloud.In Docker containers', 'develop.for.cloud.In remote development environments', 'develop.for.cloud.In virtual machines', 'develop.for.cloud.Locally with virtualenv', 'develop.for.cloud.With local system interpreter', 'environments.isolate.virtualenv', 'frameworks.ml.None'], '仅LLM管线有的列（示例）': ['company.size', 'employment.status', 'python2.version.most', 'python3.version.most', 'team.size'], '行数差异': [[2019, 47308, 47308], [2020, 37793, 37793], [2021, 23201, 23178], [2022, 23009, 22986], [2023, 25324, 25324], [2024, 28997, 28997]], '缺失率差异_Top': [], '同主题占比差异_Top': [['preferred_language', 'other.lang', 'C/C++', 28.1, 28.2, -0.1], ['programming_languages', 'other.lang', 'C/C++', 28.1, 28.2, -0.1], ['editor_preferences', 'ide.editor', 'Jupyter Notebook', 12.2, 12.2, 0.0], ['editor_preferences', 'ide.editor', 'Vim', 9.7, 9.7, 0.0], ['editor_preferences', 'ide.editor', 'PyCharm Community Edition', 8.4, 8.4, 0.0], ['editor_preferences', 'ide.editor', 'NotePad++', 7.4, 7.4, 0.0], ['editor_preferences', 'ide.editor', 'JupyterLab', 7.0, …
```

## 模型解读

两条管线在列集合上存在显著差异，规则管线多出 43 列涉及开发环境隔离细节，而 LLM 管线多出 5 列关于公司规模与语言版本的字段，导致整体 Jaccard 相似度仅为 66.5%。行数统计显示 2021 年和 2022 年存在微小差异，其余年份完全一致，表明数据源本身稳定但映射逻辑不同。同主题占比对比中，C/C++ 等核心语言数据高度吻合，差异主要源于命名粒度不一致及 LLM 对特定字段（如团队规模）的识别能力。鉴于规则管线在开发环境等具体场景下保留了更多原始分类信息，且核心统计指标一致，规则管线结果在细节覆盖上更可信。

