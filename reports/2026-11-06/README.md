# 2026-11-06 组会汇报：跨年对齐的两条路

**主题**：2019–2024 PSF 调查数据的跨年对齐——先人工映射到 153 列，再用本地 `qwen3.5:4b` 独立跑一遍清洗与对齐，对账看差异。

**时长**：7 页 / 口播 1,091 字，约 5.5–6 分钟。附录不占讲述时间。

## 文件

| 文件 | 说明 |
|---|---|
| `组会汇报稿_数据对齐与LLM尝试.md` | 逐页讲述稿：每节含【一句话】【要点】口播【来源】；附录 A 五个追问、附录 B 数字索引 |
| `figures/f1_coverage.png` | 列覆盖：42 → 153（人工）/ 110（LLM）/ 105（同名匹配） |
| `figures/f2_mapping_scale.png` | 映射规模：列名 382 vs 305；取值 109,745 vs 5,217（对数轴） |
| `figures/f3_parity.png` | 对账结构：并集 158 = 105 匹配 + 48 仅人工 + 5 仅 LLM |
| `beamer/alignment_slides.pdf` | 7 页 16:9 幻灯片（成品） |
| `beamer/alignment_slides.tex` | 幻灯片源码，ctexbeamer + metropolis |
| `build_figures.py` | 从四份机器报告与决策目录取数、画图，并打印 KPI 核对表 |

## 重新生成

```bash
# 在仓库根目录
python reports/2026-11-06/build_figures.py

# 幻灯片（两遍，第二遍才有正确总页数）
cd reports/2026-11-06/beamer
xelatex alignment_slides.tex
xelatex alignment_slides.tex
```

`build_figures.py` 只读报告、不重算数据；解析失败会直接 `raise`，不会用默认值兜底。改动报告后重跑，终端会打印一行 KPI 核对表，再对照讲述稿与幻灯片同步文案。

## 数字来源

| 数字 | 来源 |
|---|---|
| 原始 203,643 行 → 清洗后 185,632 行（删 18,011，8.8%） | `cleaned/cleaning_report.md` 分年表合计 |
| 跨年共有列 42 → 153；重命名 382；取值统一 109,745；行数 185,632 | `aligned/alignment_report.md` |
| LLM 110 列；重命名 305；同义簇 31；取值统一 5,217；`__dup` 15；行 185,586 | `llm/reports/alignment_report.md` |
| 164 个题目组、20 处改道、162 对判定（接受 34）、词表统一写法 78 处 | `llm/reports/alignment_report.md` |
| 304 个决策文件（clean 149 / align 130 / stats 14 / profile 6 / parity 4 / chart 1） | `llm/decisions/` 目录计数 |
| 105 匹配、Jaccard 66.5%、非空率差 0 条、同主题最大差 0.1pp；并集 158 = 105 + 48 + 5 | `llm/reports/parity_report.md` |
| 2021 行数 23,201 vs 23,178；2022 23,009 vs 22,986 | `llm/reports/parity_report.md` |
| 2020 清洗 54,462 → 37,793（空行 12,554、重复 4,115） | `llm/reports/cleaning_report.md` |

## 替换点

- **换年份**：讲述稿的"2019–2024"、`build_figures.py` 不用改（数字全从报告解析）；只需确认两份 `alignment_report.md` 已更新。
- **换模型**：`llm/config.py` 的 `MODEL_NAME`；幻灯片封面"本地 4B 模型"与第 5 页的 304/30 分钟/2.7 分钟需同步。
- **改数字**：先改报告来源，再跑 `build_figures.py`，最后同步讲述稿、`.tex` 与 README 三处。
- **调页数**：幻灯片按 7 页设计；删页时同步删讲述稿对应小节，口播保持在 900–1,100 字。

## 约定

- 本目录只写汇报产物；`cleaned/`、`aligned/`、`analysis/`、`charts/`、`llm/` 与根目录原始 CSV 一律只读。
- 图与 PDF 由脚本生成，不手工编辑；`figures/` 与 `beamer/*.pdf` 随源码一起保留，方便直接使用。
- 数字口径以机器报告为准，讲述稿只做摘录与解释；两者冲突时改稿，不改报告。

## 与 2026-10-23 的关系

上一期（`reports/2026-10-23/`）讲的是数据清洗：8.8% 的行怎么删、2024 年为什么多出 300 列。这一期接着讲清洗之后的对齐，以及本地小模型的尝试。两期的清洗数字（203,643 → 185,632）一致，可以直接衔接。
