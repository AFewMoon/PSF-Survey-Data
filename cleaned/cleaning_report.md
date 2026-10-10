# PSF Survey 数据清洗报告

生成时间：2026-10-10 12:01
清洗管线：clean_survey.py（缺失标记归空 -> 列名规范化 -> 去空/去重 -> 多选归一 -> 数值转换）

| 年份 | 行数(前/后) | 列数(前/后) | 空列 | 空行 | 重复行 | 重复列 | 多选归一 | 数值列 |
|---|---|---|---|---|---|---|---|---|
| 2019 | 47308/47308 | 290/290 | 0 | 0 | 0 | 0 | 218 | 1 |
| 2020 | 54462/37793 | 264/264 | 0 | 12554 | 4115 | 0 | 227 | 0 |
| 2021 | 23616/23201 | 387/387 | 0 | 0 | 415 | 0 | 356 | 0 |
| 2022 | 23288/23009 | 403/403 | 0 | 0 | 279 | 0 | 344 | 0 |
| 2023 | 25701/25324 | 491/491 | 0 | 0 | 377 | 0 | 417 | 0 |

## 2019 年详情

源文件：`2019_python_psf_external_19.csv`

### 缺失率最高的列

- `how_do_you_develop_for_the_cloud[Other – Write In]`：99.7%
- `what_operating_system_s_are_your_development_environment[Other – Write In]`：99.4%
- `which_python_unit_testing_framework_s_do_you_use_if_any[Other – Write In]`：99.2%
- `which_of_the_following_big_data_tool_s_do_you_use_if_any[Other – Write In]`：99.2%
- `how_do_you_run_code_in_the_cloud_in_the_production_environme[Other – Write In]`：99.2%
- `what_orm_s_do_you_use_together_with_python_if_any[Other – Write In]`：99.0%
- `which_configuration_management_tools_do_you_use_if_any[Other – Write In]`：98.5%
- `what_do_you_typically_use_to_upgrade_your_python_version[Other – Write In]`：98.3%
- `do_you_use_any_of_the_following_tools_to_isolate_python_envi[Other – Write In]`：98.0%
- `what_data_science_framework_s_do_you_use_in_addition_to_pyth[Other - Write In]`：97.8%

### 列名映射（前 20 条）

- `Is Python the main language you use for your current projects?` -> `is.python.main`
- `Bash / Shell:What other language(s) do you use?` -> `other.lang.Bash / Shell`
- `C/C++:What other language(s) do you use?` -> `other.lang.C/C++`
- `C#:What other language(s) do you use?` -> `other.lang.C#`
- `Clojure:What other language(s) do you use?` -> `other.lang.Clojure`
- `CoffeeScript:What other language(s) do you use?` -> `other.lang.CoffeeScript`
- `Go:What other language(s) do you use?` -> `other.lang.Go`
- `Groovy:What other language(s) do you use?` -> `other.lang.Groovy`
- `HTML/CSS:What other language(s) do you use?` -> `other.lang.HTML/CSS`
- `Java:What other language(s) do you use?` -> `other.lang.Java`
- `JavaScript:What other language(s) do you use?` -> `other.lang.JavaScript`
- `Kotlin:What other language(s) do you use?` -> `other.lang.Kotlin`
- `None:What other language(s) do you use?` -> `other.lang.None`
- `Objective-C:What other language(s) do you use?` -> `other.lang.Objective-C`
- `Other - Write In::What other language(s) do you use?` -> `what_other_language_s_do_you_use[Other - Write In]`
- `Perl:What other language(s) do you use?` -> `other.lang.Perl`
- `PHP:What other language(s) do you use?` -> `other.lang.PHP`
- `R:What other language(s) do you use?` -> `other.lang.R`
- `Ruby:What other language(s) do you use?` -> `other.lang.Ruby`
- `Rust:What other language(s) do you use?` -> `other.lang.Rust`
- （共 289 列重命名）

### 转换为数值的列

- `response_id`


## 2020 年详情

源文件：`2020_2020_sharing_data_outside.csv`

### 缺失率最高的列

- `how.involved.Multimedia applications development`：95.8%
- `unittesting.Tox`：94.8%
- `how.involved.Mobile development`：94.7%
- `python2.version.most`：94.6%
- `how.involved.Embedded development`：92.5%
- `how.involved.Game development`：92.3%
- `how.involved.Computer graphics`：89.5%
- `how.involved.Desktop development`：83.3%
- `how.involved.Network programming`：83.1%
- `how.involved.Software prototyping`：78.9%

### 列名映射（前 20 条）

- `isolate.environments.Vagrant  / virtual machines` -> `isolate.environments.Vagrant / virtual machines`
- `web.frameworks.CherryPy ` -> `web.frameworks.CherryPy`
- `web.frameworks.Flask ` -> `web.frameworks.Flask`
- `web.frameworks.Pyramid ` -> `web.frameworks.Pyramid`
- （共 4 列重命名）


## 2021 年详情

源文件：`2021_2021_sharing_data_outside.csv`

### 缺失率最高的列

- `python2.version.most`：95.3%
- `ide.editor.None_300`：88.9%
- `issue.solved`：88.0%
- `packaging.tools.Containers (eg via Docker)`：81.4%
- `team.size`：71.1%
- `company.size`：53.3%
- `are.you.datascientist`：42.2%
- `age`：40.1%
- `country.live`：40.1%
- `job.team`：39.7%

### 列名映射（前 20 条）

- `isolate.environments.Vagrant  / virtual machines` -> `isolate.environments.Vagrant / virtual machines`
- `communicate.channels.I’ve never contacted  the core developers` -> `communicate.channels.I’ve never contacted the core developers`
- （共 2 列重命名）


## 2022 年详情

源文件：`2022_2022_sharing_data_outside.csv`

### 缺失率最高的列

- `how.involved.Multimedia applications development`：94.8%
- `how.involved.Mobile development`：94.2%
- `python2.version.most`：94.2%
- `how.involved.Other - Write In:`：93.9%
- `how.involved.Embedded development`：92.6%
- `how.involved.Game development`：91.6%
- `how.involved.Computer graphics`：88.8%
- `how.involved.Network programming`：83.9%
- `how.involved.Desktop development`：82.3%
- `packaging.tools.Containers (eg via Docker)`：81.6%

### 列名映射（前 20 条）

- `isolate.environments.Vagrant  / virtual machines` -> `isolate.environments.Vagrant / virtual machines`
- （共 1 列重命名）


## 2023 年详情

源文件：`2023_2023_sharing_data_outside.csv`

### 缺失率最高的列

- `jupyter.dataspell`：99.8%
- `jupyter.intellij`：99.2%
- `documentation.tool.Other language, please specify`：98.8%
- `documentation.tool.Other systems, please specify`：98.1%
- `how.involved.Mobile development`：95.2%
- `how.involved.Other, please specify:`：94.9%
- `python2.version.most`：94.5%
- `how.involved.Multimedia applications development (apps handling various types of multimedia content, e.g. audio, graphics, etc.)`：94.2%
- `how.involved.Embedded development`：93.9%
- `how.involved.MLOps`：93.1%

### 列名映射（前 20 条）

- `ide.editor.features.Use autocompletion  in your editor` -> `ide.editor.features.Use autocompletion in your editor`
- （共 1 列重命名）
