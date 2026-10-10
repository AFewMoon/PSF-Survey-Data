# AGENTS.md

本文件供 AI 编码助手（以及人类协作者）在本仓库中工作时参考。请先完整阅读本文件再动手修改。

## 项目背景

对 PSF（Python Software Foundation）年度 Python 开发者调查 2019–2023 的原始公开数据做清洗与跨年对齐。产出：

1. `cleaned/`：各年清洗后数据 + 清洗报告
2. `aligned/`：列名/取值统一后的分年数据、跨年总表 `survey_2019_2023_master.csv`、映射表与对齐报告

数据由 JetBrains 提供并源自 PSF 年度调查，**原始数据版权归 JetBrains / PSF 所有**。仓库许可证 GPL-3.0 仅覆盖脚本与文档。

## 目录结构与关键文件

```
PSF-Survey-Data/
├── <year>_*.csv                      # 原始数据（只读，禁止修改/重命名/删除）
├── clean_survey.py                   # 清洗管线（cleaned/ 的唯一来源）
├── align_survey.py                   # 对齐管线（aligned/ 的唯一来源）
├── cleaned/                          # 清洗产物（由脚本生成，不手工编辑）
│   ├── cleaned_<year>.csv
│   └── cleaning_report.md
├── aligned/                          # 对齐产物（由脚本生成，不手工编辑）
│   ├── cleaned_aligned_<year>.csv
│   ├── survey_2019_2023_master.csv   # 156,635 行 × 154 列（含 year 列）
│   ├── column_mapping.csv            # 列名映射（year, original, canonical, level）
│   ├── value_mapping.csv             # 取值映射（year, column, original, canonical）
│   └── alignment_report.md
├── analysis/                         # 分析报告（analysis_report.md）
├── charts/                           # 统计图表（由 plot_survey.py 生成）
├── tutorial/                         # 数据清洗/对齐/统计/分析教材（多章 Markdown，含练习与答案）
└── README.md / AGENTS.md / LICENSE
```

## 数据说明

- **文件编码**：全部 CSV 为 UTF-8（原始文件带 BOM，脚本用 `encoding="utf-8-sig"` 读取）。
- **缺失表示**：清洗后数据中缺失值一律为**空字符串**（不是 `NaN`、不是 `NA`），读取时用 `keep_default_na=False`。
- **多选题**：清洗后为二值列 `0/1`（int64），列名为 `前缀.选项`；含 `__dup` 后缀的是同名冲突列，内容不同，勿合并。
- **年份结构差异**：
  - 2019 原始表头为完整问题文本（`问题:选项`），清洗时已映射到统一命名；核心列如 `is.python.main`、`python.years`、`years.of.coding`。
  - 2020–2023 表头为 `前缀.题目.选项` 点分结构；部分组路径跨年不一致（如 2020 `data.frameworks` vs 2023 `frameworks.ml`、`isolate.environments` vs `environments.isolate`），已在 `align_survey.py` 的 `GROUP_PATH_CANON` 统一。
- **上游数据质量问题**：2020 年原始文件含 12,554 个全空行（已删）；2020 年问题清单仅有表头；2019 年 `is.python.main` 约 25% 缺失。

## 脚本用法与修改约定

```powershell
python clean_survey.py              # 清洗全部年份（cleaned/）
python clean_survey.py 2023 2019    # 只清洗指定年份
python align_survey.py              # 对齐 + 合并总表（aligned/）
```

- 重跑顺序：**先 `clean_survey.py`，后 `align_survey.py`**（对齐读取清洗产物）。
- 映射表/配置（`GROUP_REMAP_2019`、`GROUP_PATH_CANON`、`SINGLE_REMAP_2019`、`KNOWN_GROUP_PATHS`、`OPTION_ALIASES`）集中在两个脚本顶部，修改语义映射只改这些字典，不要改管线逻辑。
- 扩展对齐后必须重跑两个脚本，并核对 `cleaning_report.md` 与 `alignment_report.md` 中的统计变化。
- 脚本输出统计走 `print` 与 Markdown 报告，无需引入日志框架。

## 编码规范

- Python 3.14+，仅依赖 pandas 与标准库；类型标注用 `from __future__ import annotations` 风格。
- 函数保持纯函数风格（传入 df 返回新 df，不就地修改入参）。
- 字符串归一统一走 `norm_text()` / `norm_key()`，不要另写正则散落各处。
- 提交信息用中文或英文均可，一行主题 + 必要时正文说明。

## 注意事项（重要）

1. **禁止修改、重命名、删除根目录的原始 CSV**；禁止手工编辑 `cleaned/`、`aligned/` 下的任何生成文件。
2. 新产物一律写入新的独立目录，不要覆盖既有产物。
3. 大文件（原始/清洗/对齐 CSV 共约 600 MB）已纳入版本库，避免再生成超大中间文件；临时调试脚本用完即删，不要提交。
4. Windows PowerShell 环境：调用 Python 单行命令时引号转义易出错，复杂探查建议写临时 `.py` 文件执行后删除。
5. pandas 3.x 会就 `select_dtypes('object')` 包含 str 发出弃用警告，编写新校验代码时显式按 dtype 过滤。
6. 数据解读提示：调查为自报抽样数据，跨年比较注意问卷措辞变化；`value_mapping.csv` 记录了所有取值统一。
