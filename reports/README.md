# reports：组会汇报材料（数据清洗专题）

本次汇报只覆盖数据清洗（教程第 1–3 章）。跨年对齐、统计与图表都还没做，幻灯片最后一页明确写了这一点。

## 文件

| 文件 | 说明 |
|---|---|
| `组会汇报稿_数据清洗.md` | 逐页对应的讲述稿：每节含一句话结论、要点、可直接念的口播、数字来源 |
| `beamer/data_cleaning_slides.tex` | LaTeX beamer 源文件（16:9，metropolis 主题，ctex 中文） |
| `beamer/data_cleaning_slides.pdf` | 编译产物，10 页，约 10 分钟 |
| `build_figures.py` | 生成汇报用的三张图，只读 `cleaned/` 与 `aligned/`，写入 `figures/` |
| `figures/f1_rows_before_after.png` | 分年行数清洗前后对比 |
| `figures/f2_structure_growth.png` | 列数与多选二值列的增长 |
| `figures/f3_missing_profile.png` | 2024 年 573 列缺失率分布 |

## 重新生成

```powershell
python reports/build_figures.py                       # 先出图

cd reports/beamer
xelatex data_cleaning_slides.tex                      # 跑两遍，页码才显示总页数
xelatex data_cleaning_slides.tex
```

环境要求：TeX Live（含 `ctex`、`beamer`、`beamertheme-metropolis`、`tcolorbox`、`booktabs`）；本机路径为 `C:\texlive\2026\bin\windows`。图片按幻灯片正文宽度（约 5.7 in）绘制，在 beamer 里按 `width=\textwidth` 插入，缩放比接近 1，字号不会被压小。

## 数字从哪来

- 行数、列数、空行、重复行、多选列：`cleaned/cleaning_report.md`（机器生成，脚本解析而非手抄）。
- 2019 年 `is.python.main` 缺失 25.5%：对 `cleaned/cleaned_2019.csv` 实测。
- 2024 年分列缺失率：对 `cleaned/cleaned_2024.csv` 分块统计。

完整对照见汇报稿附录 B。

## 替换点

- 汇报人与日期：`data_cleaning_slides.tex` 的封面帧（`汇报人：（待填）`）与汇报稿开头的元信息。
- 年份范围：`build_figures.py` 顶部的 `YEARS`；`cleaning_report.md` 增删年份后需同步。
- 文案：幻灯片正文与汇报稿各自独立，改动时保持两边的数字一致。

## 约定

`cleaned/`、`aligned/`、`charts/` 下的文件都是既有产物，本目录只读不写；本目录下的图与 PDF 全部由脚本生成，不手工编辑。
