# PSF Survey Data

对 Python Software Foundation（PSF）年度 Python 开发者调查（2019–2023）原始数据进行清洗与跨年对齐，产出可分析的分年数据集与跨年总表。

Cleaned and cross-year aligned datasets built from the raw Python Developers Survey (2019–2023) run by the Python Software Foundation.

[中文](#中文) | [English](#english)

---

## 中文

### 数据来源与版权

- 原始数据由 **JetBrains** 提供，源自 **PSF** 主办的年度 Python 开发者调查（2019–2023 公开分享数据）。
- **原始调查数据版权归 JetBrains / PSF 所有**，本仓库许可证不覆盖根目录下 9 个原始 `*.csv` 数据文件。
- 本仓库许可证（GPL-3.0）仅覆盖清洗/对齐脚本与文档。

### 目录结构

```
PSF-Survey-Data/
├── 2019_python_psf_external_19.csv        # 原始数据 2019（290 列 × 47,308 行）
├── 2020_2020_sharing_data_outside.csv     # 原始数据 2020（264 列 × 54,462 行）
├── 2021_2021_sharing_data_outside.csv     # 原始数据 2021（387 列 × 23,616 行）
├── 2022_2022_sharing_data_outside.csv     # 原始数据 2022（403 列 × 23,288 行）
├── 2023_2023_sharing_data_outside.csv     # 原始数据 2023（491 列 × 25,701 行）
├── *_questions_outside.csv                # 各年问题清单（2019 年无独立清单）
├── clean_survey.py                        # 清洗管线脚本
├── align_survey.py                        # 跨年对齐管线脚本
├── cleaned/                               # 清洗产物 + cleaning_report.md
└── aligned/                               # 对齐产物 + 跨年总表 + 映射表
```

### 环境要求与用法

- Python 3.14+，pandas（`pip install pandas`）

```powershell
python clean_survey.py    # 1. 清洗（默认全部年份，可指定：python clean_survey.py 2023）
python align_survey.py    # 2. 跨年对齐 + 合并总表
```

### 数据处理概要

| 年份 | 清洗前(行×列) | 清洗后(行×列) | 多选归一列 | 对齐后跨年共有列 |
|---|---|---|---|---|
| 2019 | 47,308 × 290 | 47,308 × 290 | 218 | 153 |
| 2020 | 54,462 × 264 | 37,793 × 264 | 227 | 153 |
| 2021 | 23,616 × 387 | 23,201 × 387 | 356 | 153 |
| 2022 | 23,288 × 403 | 23,009 × 403 | 344 | 153 |
| 2023 | 25,701 × 491 | 25,324 × 491 | 417 | 153 |

**清洗**：缺失标记归空（`NA`/`N/A` 等）→ 列名规范化 → 去全空行/列与重复行 → 多选二值列归一为 0/1 → 数值类型转换 → 全角标点统一。

**对齐**：列名三级匹配（精确同名 → 文本归一 → 组路径重映射 + 同义词表），2019 年问题文本表头映射到 2020–2023 的 `前缀.选项` 命名方案，类别列取值文案统一，按共有列纵向合并为跨年总表 `aligned/survey_2019_2023_master.csv`（含 `year` 列）。跨年共有列由 42 列提升至 153 列。

### 已知数据质量问题

- 2020 年原始数据含 **12,554 个全空行（23%）**，散布于整个文件，已删除。
- 2019 年 `is.python.main` 缺失约 25%（受访者跳答），属上游缺失。
- 2020 年问题清单上游即仅有表头（空文件）。
- 各年对齐文件各有 1 列因同名冲突带 `__dup` 后缀，内容互不相同，未合并。

### 许可证

脚本与文档以 [GPL-3.0](LICENSE) 发布。原始数据版权归 JetBrains / PSF 所有，使用数据请遵循其发布条款并注明来源。

---

## English

### Data Provenance & Copyright

- Raw data was provided by **JetBrains** and originates from the annual **Python Developers Survey** run by the **Python Software Foundation** (2019–2023 public sharing datasets).
- **The raw survey data is copyrighted by JetBrains / PSF.** The repository license does **not** cover the 9 raw `*.csv` data files in the root.
- The repository license (GPL-3.0) applies only to the cleaning/alignment scripts and documentation.

### Layout & Usage

Root contains the 5 raw main-dataset CSVs (one per year) plus per-year question lists. `cleaned/` holds per-year cleaned datasets with `cleaning_report.md`; `aligned/` holds per-year aligned datasets, the master table `survey_2019_2023_master.csv` (156,635 rows × 154 cols incl. `year`), column/value mapping CSVs, and `alignment_report.md`.

Requires Python 3.14+ and pandas:

```powershell
python clean_survey.py    # 1. clean all years (or: python clean_survey.py 2023)
python align_survey.py    # 2. align columns/values + build master table
```

Cleaning: normalize missing tokens, drop empty rows/columns and duplicates, binarize multi-select columns to 0/1, convert numeric columns, unify punctuation. Alignment: 3-level column matching (exact → normalized text → group-path remapping + synonym table), per-year value canonicalization, then vertical concat on the 153 common columns (up from 42).

### Known Data Quality Issues

- 2020 raw data contains **12,554 fully empty rows (23%)**, scattered throughout the file; removed.
- `is.python.main` is missing for ~25% of 2019 respondents (upstream skip logic).
- The 2020 question list is header-only upstream.
- Each aligned file has 1 `__dup`-suffixed column from name collisions; contents differ, kept unmerged.

### License

Scripts and documentation are released under the [GPL-3.0](LICENSE). Raw survey data remains copyrighted by JetBrains / PSF; follow their distribution terms and attribute the source when using the data.
