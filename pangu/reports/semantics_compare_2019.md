# 清洗语义判定对账（2019）：qwen3.5:4b vs pangu-emb-7b

口径：同一批原始列名上的 kind / group / option 三项判定，只比两侧都覆盖的列。

| 指标 | 一致 | 占比 |
| --- | --- | --- |
| 覆盖列数 | 138 | — |
| 三项全同 | 7 | 5.1% |
| kind（单选/多选/数值/文本） | 133 | 96.4% |
| group（题目组） | 7 | 5.1% |
| option（选项名） | 98 | 71.0% |

## 组名基数

同一批 138 列上，qwen3.5:4b 给出 40 个不同 group，pangu-emb-7b 给出 91 个。多选题的选项本应共用 group，基数接近列数说明模型是按选项各自造组。

## 按对照侧批大小拆分

| 批大小 | 列数 | group 一致 | 占比 |
| --- | --- | --- | --- |
| 1 | 21 | 0 | 0.0% |
| 2 | 8 | 0 | 0.0% |
| 4 | 109 | 7 | 6.4% |

## kind 分歧矩阵

| qwen3.5:4b | pangu-emb-7b | 列数 |
| --- | --- | --- |
| free_text | multi_option | 5 |

## group 分歧 Top

| qwen3.5:4b | pangu-emb-7b | 列数 |
| --- | --- | --- |
| `ide.tools.ci` | `ci.systems` | 4 |
| `other.lang` | `other.languages` | 4 |
| `ide.editor` | `cloud.development` | 4 |
| `ide.editor` | `what_ide editors_ide_s_python_development_in_addition_to_primary_ide` | 4 |
| `frameworks.data` | `frameworks.ml` | 4 |
| `cloud.platforms` | `cloud.platforms.do_you_use` | 4 |
| `other.lang` | `language.usage` | 4 |
| `other.lang` | `language_languages` | 4 |
| `frameworks.cm` | `configuration_management_tools` | 4 |
| `ide.os` | `operating_systems` | 3 |

## 分歧样例

| 列 | qwen3.5:4b | pangu-emb-7b |
| --- | --- | --- |
| `AWS:Which of the following cloud platforms do yo` | multi_option / cloud.platforms | multi_option / clouds |
| `Ansible:Which configuration management tools do ` | multi_option / frameworks.cm | multi_option / ansible |
| `Apache Beam:Which of the following Big Data tool` | multi_option / ide.tools | multi_option / Apache Beam:Which of the following Big Data tool(s) do you use, if any? |
| `Apache Hive:Which of the following Big Data tool` | multi_option / ide.tools.bigdata | multi_option / bigdata |
| `Apache Kafka:Which of the following Big Data too` | multi_option / ide.tools.bigdata | multi_option / bigdata |
| `Apache Samza:Which of the following Big Data too` | multi_option / ide.tools.bigdata | multi_option / apache.samza |
| `Apache Spark:Which of the following Big Data too` | multi_option / ide.tools.bigdata | multi_option / apache.spark |
| `Apache Tez:Which of the following Big Data tool(` | multi_option / ide.tools.bigdata | multi_option / apache.tez |
| `AppVeyor:Which Continuous Integration (CI) syste` | multi_option / ide.tools.ci | multi_option / appveyor |
| `Automatic upgrade via cloud provider:What do you` | multi_option / ide.upgrade.cloud | multi_option / python.version.upgrades |
| `BSD:What operating system(s) are your developmen` | multi_option / ide.os | multi_option / operating_systems |
| `Bamboo:Which Continuous Integration (CI) system(` | multi_option / ide.tools.ci | multi_option / ci.systems |
| `Bash / Shell:What other language(s) do you use?` | multi_option / other.lang | multi_option / bash_shell_languages |
| `Bottle:What web frameworks / libraries do you us` | multi_option / frameworks.web | multi_option / web.frameworks.bottle |
| `Build from source:What do you typically use to u` | multi_option / ide.upgrade.source | multi_option / python.version.upgrades |
