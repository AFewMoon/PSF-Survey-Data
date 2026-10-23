# 第 10 章 LLM 驱动管线：模型做语义判断，代码做执行

> 目标：读懂 `llm/` 这套与规则管线并行的第二条实现。它用本地 `qwen3.5:4b` 完成列语义标注、跨年组路径统一、统计口径设计、图表选型与文字解读，用 Python 完成校验、执行与报告。本章重点不是"怎么调模型"，而是**怎样把不确定的模型输出接进一条必须可复现的数据管线**。

## 10.1 为什么还要一条管线

前九章的规则管线是完全确定的：算子、`GROUP_REMAP_2019`、`GROUP_PATH_CANON`、`OPTION_ALIASES`，每一条都是人工看过列名后写下的。代价也很清楚：

- 对齐后的总表有 153 列，背后是 382 条列名映射、109,745 条取值统一记录；
- 每新增一年（比如 2024 的 `ai` / `bi` / `region` / `trusted` 前缀），都要人工把新列翻一遍；
- 同义判断（`data.frameworks` 与 `frameworks.ml`、`isolate.environments` 与 `environments.isolate`）靠人肉维护同义词表，覆盖不全就丢列。

LLM 管线要验证的是一个工程问题：**这些语义决策能不能由模型从"列名 + 聚合画像"里提出来，再被确定性护栏约束到可接受的质量**。它有三条不可让步的原则：

1. **不替代规则管线**。两者产物各自独立，规则管线的 `cleaned/`、`aligned/`、`analysis/` 不被读写，最后用 `parity` 阶段对账。
2. **模型不接触数据本体**。模型只看到"列名 + 非空率 + 基数 + 至多 6 个截断样本值"，永远不逐行处理 18.5 万行，也不看自由文本原文。
3. **决策全部落盘、可校验、可重放**。模型输出只是候选 JSON，先过 `decision_schema.py`，再由纯函数执行；每次调用的响应、耗时、降级标记都写进 `decisions/`。

一句话概括分工：**模型是提建议的实习生，护栏是签字的主管，缓存是会议纪要。**

| 维度 | 规则管线 | LLM 管线 |
|---|---|---|
| 决策来源 | 人工映射表 + 固定逻辑 | 模型建议 + 证据纠错 + 护栏 |
| 可复现性 | 天然确定 | 靠 temperature=0 + seed + 决策缓存 |
| 扩展新一年 | 人工读列名、补映射 | 重跑，模型给候选，人只审高危项 |
| 语义覆盖面 | 153 列（手工同义词表较全） | 40 列（只统一了 21 个组路径） |
| 出错方式 | 漏映射（列丢失） | 误映射（列并错），需要 parity 兜底 |
| 适合场景 | 交付、长期维护 | 探索、辅助人工扩表、交叉验证 |

## 10.2 一次运行的全貌

```powershell
ollama serve                                      # 前置：本地 Ollama，模型已拉取
python llm/run_llm_pipeline.py --stage ping       # 健康检查，打印模型名与 digest
python llm/run_llm_pipeline.py --stage selftest   # 离线自检（12 项不变量检查，不调模型）
python llm/run_llm_pipeline.py --stage all        # 全流程
python llm/run_llm_pipeline.py --stage clean --years 2023 2024
python llm/run_llm_pipeline.py --stage all --refresh   # 忽略缓存重算
```

| 参数 | 说明 |
|---|---|
| `--stage` | `ping / selftest / profile / clean / align / stats / charts / parity / all` |
| `--years` | 只跑指定年份（默认 2019–2024） |
| `--refresh` | 忽略缓存，重新请求模型 |
| `--dry-run` | 不调模型；对齐/统计/图表走确定性默认分支 |
| `--batch-size` | 每批列数（默认 18，另受 6000 字符预算约束） |
| `--apply-review` | 执行 `review_approved.json` 里已人工确认的删列 |
| `--rebuild-profile` | 强制重算列画像 |

阶段依赖固定：`profile → clean → align → stats → charts → parity`（画像、清洗、对齐、统计、图表、对账）。

`--dry-run` 有一个容易误解的地方：`clean_stage.clean_year()` 在 `client is None` 时直接返回，**不产出清洗文件**；只有 align/stats/charts 有离线分支。所以它适合"已有清洗产物、只想看默认对齐/统计"的场景，不能当首次运行的预览。首次请先 `--stage selftest`，再小范围 `--stage clean --years 2024`。

本机实测规模（RTX 5070 Laptop 8 GB）：

| 项 | 值 |
|---|---|
| 决策文件 | 230 个（clean 149 / align 58 / stats 14 / profile 6 / chart 1 / parity 2） |
| 首次全量 | 约 30 分钟 |
| 命中缓存全量 | 2.6 分钟（模型调用 0 次） |
| 单批耗时 | 关闭 thinking 后 10.8s（默认 thinking 时 87s） |

最后一行是可行性前提。`config.THINK = False` 不是性能优化，而是"这条路走不走得通"的分界线：8k 上下文、每批 18 列、几百次调用，thinking 开着就跑不完。

## 10.3 列画像：模型能看到什么

`profiles.py` 是整条管线的信息闸门。它对每列只保留结构特征，并按内容哈希识别完全重复的列：

```42:48:llm/llm_survey/profiles.py
def _hash_column(s: pd.Series) -> str:
    """列指纹，用于确定性识别内容完全相同的重复列。"""
    try:
        arr = pd.util.hash_pandas_object(s, index=False).to_numpy()
        return hashlib.sha1(arr.tobytes()).hexdigest()[:16]
    except (TypeError, ValueError):
        return hashlib.sha1(repr(s.tolist()).encode("utf-8")).hexdigest()[:16]
```

画像里的四个布尔标志把"人眼能看出的列形态"固化成证据：

- `multi_like`：去掉缺失标记（2019 用 `NA`）后，非空取值恒等于列名中的选项文本（非空即选中）；
- `binary_like`：全列取值只有 `0/1`；
- `level_like`：取值均为「选项 + 冒号 + 程度」，如 `X : primary activity`；
- `numeric_like`：取值全为数字。

2023 年 `ide.editor.Vim` 的真实画像条目：

```json
{
  "name": "ide.editor.Vim",
  "non_empty_pct": 10.6,
  "n_unique": 1,
  "top_share": 100.0,
  "numeric_like": false,
  "binary_like": false,
  "multi_like": true,
  "level_like": false,
  "redacted": false,
  "col_hash": "cf39623a26fdc546",
  "top": ["Vim"]
}
```

它同时说明三件事：该年有 10.6% 的行在这一列非空；选中时取值恒为 `Vim`；因此它只能是一个多选题的选项列。送给模型的紧凑版本还会删掉 `top_share`、`col_hash` 等执行侧字段，只留 `column / non_empty_pct / n_unique / top / flags`。

自由文本列会被 `_is_free_text()` 判为 `redacted`，样本值不送模型，只给长度分布（节选，实际条目还含四个布尔标志）：

```json
{
  "name": "how.involved.Other, please specify:",
  "non_empty_pct": 5.1,
  "n_unique": 3,
  "redacted": true,
  "value_shape": {"len_min": 13, "len_median": 24, "len_max": 26}
}
```

判定规则两道：列名含 `other / comment / email / name / feedback ...` 等提示词，或基数超过 200。它是**保守的**，会误伤——上面这列只有 3 个取值，仍因列名带 `other` 被脱敏。这类误伤可以接受：少给模型一点信息，换掉"把受访者原话送进模型"的风险。

## 10.4 清洗阶段：模型标注，证据纠错

清洗分两步决策：先逐列标语义（7 类 `kind`），再对全年下一份算子计划。

`config.KINDS` 是封闭枚举：`single_choice / multi_option / multi_level / numeric / identifier / free_text / metadata`。模型输出枚举外的值，`validate_semantics()` 直接降级为 `metadata` 并记一条 problem；模型漏掉的列由 `default_semantics()` 按表头结构补默认，报告里单列"模型列标注降级 N 列"。

**模型会错，所以证据优先。** 下面是一条真实缓存里的列标注（节选），模型把勾选列判成了单选：

```json
{"column": "dependency.store.requirements_txt", "kind": "single_choice",
 "group": "dependency.store", "option": "requirements_txt",
 "reason": "全列值等于列名，符合 multi_like 特征。"}
```

理由自己都说"全列值等于列名"，结论却写成 `single_choice`。清洗管线不争论，直接用画像证据覆盖：

```186:194:llm/llm_survey/clean_stage.py
    elif info.get("level_like") and kind != "multi_level":
        item["kind"] = "multi_level"
        item["reason"] = _note(item["reason"],
                              "画像显示取值为「选项+程度」，按多选程度网格纠正")
    elif (info.get("multi_like") or info.get("binary_like")) and kind in {
        "free_text", "single_choice", "metadata"
    }:
        item["kind"] = "multi_option"
        item["reason"] = _note(item["reason"], "画像显示为勾选标记列，按多选题选项列纠正")
```

最终落盘的语义因此是 `multi_option`，理由里带上纠正痕迹（可审计）：

```json
{"original": "dependency.store.requirements_txt", "new": "dependency.store.requirements_txt",
 "kind": "multi_option", "group": "dependency.store", "option": "requirements_txt",
 "reason": "全列值等于列名，符合 multi_like 特征。（画像显示为勾选标记列，按多选题选项列纠正）"}
```

这一步的教学价值大于代码量：**当确定性证据与模型判断冲突时，永远让证据赢，并把冲突写进理由。** 模型只在"证据覆盖不到"的地方做判断，比如两列的语义关系、组路径该怎么起名。

年度算子计划只允许四个整体算子加一个高危项：

```json
{"ops": [
  {"op": "drop_empty_rows", "apply": true, "reason": "23.1% 空行过高，影响数据质量。"},
  {"op": "drop_empty_cols", "apply": false, "reason": "无空列证据，保留现有数据。"},
  {"op": "drop_dup_rows",   "apply": true, "reason": "16668 行重复，占比 30.6%，需清洗。"},
  {"op": "drop_dup_cols",   "apply": false, "reason": "无重复列证据，保留现有数据。"}
 ], "drop_cols": [], "reason": "删除 23.1% 空行及 30.6% 重复行，提升数据可用性。"}
```

`validate_global_plan()` 不相信任何理由文字，只核对证据与阈值：

- 算子不在 `GLOBAL_OPS` 白名单 → 拒绝；
- `empty_rows=0` 却要删空行 → 改为不执行；
- 删行数超过总行数 60%（`MAX_DROP_ROW_SHARE`）→ 改为不执行；
- `drop_cols` 只能引用给定候选编号，且全部进人工确认队列；数量超过列数 20% 则整批挂起。

于是 2020 年那 16,669 条"删除"被拆成可解释的两步：先删 12,554 条全空行，再删 4,115 条完全重复行，54,462 → 37,793。模型理由里的"16668 行重复"来自原始表 `duplicated()` 的计数——它把 12,553 条彼此重复的空行也算进去了；先删空行后，剩下的重复只有 4,115。**理由文字是参考，执行结果由证据与顺序决定。**

两个细节值得单独记：

- **2019 的组名多数票**。2019 表头是"选项:完整问句"，同一问句下的选项列，模型偶尔给出五花八门的组名。`_stabilize_2019_groups()` 按问句分组取众数组名统一，避免一道题被拆成七八个组。
- **截断就对半拆**。输出被截断（`done_reason == "length"`）时，`_semantics_batch()` 把这一批对半递归重试，最多 3 层；仍失败才记 problem 并留空给默认规则。这是"批大小不是越大越好"的直接体现。

六年清洗结果（`llm/reports/cleaning_report.md`）：

| 年份 | 行(前/后) | 列(前/后) | 空行 | 重复行 | 二值化 | 重命名 |
|---|---|---|---|---|---|---|
| 2019 | 47,308/47,308 | 290/290 | 0 | 0 | 218 | 288 |
| 2020 | 54,462/37,793 | 264/264 | 12,554 | 4,115 | 227 | 4 |
| 2021 | 23,616/23,178 | 387/387 | 0 | 438 | 356 | 2 |
| 2022 | 23,288/22,986 | 403/403 | 0 | 302 | 344 | 1 |
| 2023 | 25,701/25,324 | 491/491 | 0 | 377 | 417 | 1 |
| 2024 | 29,268/28,997 | 573/573 | 0 | 271 | 492 | 1 |

2021/2022 的重复行各比规则管线多 23 条，这是两条管线的口径差异，10.9 节会再遇到它。

## 10.5 对齐阶段：先统组路径，再改列名，最后统取值

`align_stage.run()` 是四步流水线，每步的输入都是上一步的产物。

**第一步：组路径统一。** 从清洗阶段留下的 `columns` 元数据收集 164 个题目组，连同涉及年份、选项数、3 个样例选项送模型。模型只回答"这个组路径的标准写法是什么"，不改数据。

真实映射（节选）：

| 原路径 | 标准路径 | 判断 |
|---|---|---|
| `isolate.environments` | `ide.isolate` | 合理：同义改写 |
| `first.learn.about.main` | `learning.source` | 合理：把整句题归到主题（2021） |
| `how.involved.fixed` | `how.involved` | 合理：同题选项被误当组名 |
| `ml.cloud.cost.impact` | `ml.cloud.budget` | 合理：措辞演进 |
| `is.python.main` | `ide.python_version` | **错误**：是否以 Python 为主，与版本题无关 |
| `ide.python2_version` / `ide.python3_version` | `ide.python_version` | 可讨论：合并版本题，但丢掉了 2/3 之分 |

`is.python.main → ide.python_version` 是本章最值钱的反例。它在结构上完全合法：标准路径非空、无空格、小写点分，护栏没有理由拒绝；模型对它六年一致地给出同一个错误映射。后果是 2019 年 5 个来源列被并成一组：`is.python.main` 占了 `ide.python_version`，四个真正的版本列降级为 `__dup1..4`；跨年总表的 `ide.python_version` 实际装的是"是否以 Python 为主"，而规则管线里的 `is.python.main` 在 LLM 总表中不存在。**格式护栏保证不了语义正确，只有对账能发现它。**

**第二步：重命名。** 按 `组路径.选项` 拼新列名。如果模型归并导致同年撞名（两个不同原始列拼成同一个新名），不硬加 `__dup` 掩盖，而是整年回退到确定性归一（`norm_text`）：

```295:306:llm/llm_survey/align_stage.py
        # 冲突回退：模型归并若造成同年撞名，回退到确定性归一文本（避免 __dup 掩盖误并）
        if len(set(proposed)) < len(proposed):
            result.problems.append(
                f"{year} 年模型归并导致 {len(proposed) - len(set(proposed))} 处同名冲突，已回退确定性归一"
            )
            proposed = [
                f"{canon_group_by_year[year][col]}.{norm_text(option_by_year[year].get(col) or '')}"
                if option_by_year[year].get(col)
                else (canon_group_by_year[year][col] or col)
                for col in dfs[year].columns
            ]
        final = dedup_names(proposed)
```

回退后仍重名的列由 `dedup_names()` 加 `__dup1`、`__dup2` 后缀。这些列内容不同，不能合并——它们往往是"模型把两道题并成一组"的痕迹，本次共 16 列。

**第三步：单选取值统一。** 模型给同义簇，代码只采纳"文本相关"的建议（`_related`：一个 `norm_key` 是另一个的子串），其余忽略。这一层很保守，原因见下一节。

**第四步：取交集合并。** 六年列名取交集得 40 列，纵向拼成 185,586 行。40 列集中在四个主题：

- `ide.editor.*`（13 个编辑器选项）
- `other.lang.*`（编程语言，23 个选项）
- 三个单选/数值列：`company.size`、`employment.status`、`team.size`
- 一列版本题：`ide.python_version`

对比规则管线的 153 列，差距不在执行质量，而在**同义词表覆盖**：模型只对 21 个组路径做了高置信映射，规则管线的手工表有 46 条组路径、19 条选项别名。这也解释了为什么本次 `value_mapping.csv` 是空的：不是没有变体，而是模型的归并建议全被下一节的护栏拒了。

## 10.6 护栏：为什么宁可不合并

4B 模型在"选项归并"任务上有一个稳定的失败模式：**整组塌缩**。给它一个 24 个选项的组，它可能输出一个簇，把 24 个选项全并成 `In Docker containers` 之类的单一文本。直接执行，这一列就从分布变成常数。

`validate_cluster_batch()` 专门拦这个：

```292:303:llm/llm_survey/decision_schema.py
            if not canonical or len(keys) < 2:
                continue
            # 防「整组塌缩」：4B 模型偶发把同组所有选项并成一个（如全部并成 "In Docker containers"）
            total = len(units[name])
            collapse = len(keys) >= total
            too_big = (len(keys) > config.MAX_CLUSTER_SIZE
                       or (len(keys) >= 3 and len(keys) > total * config.MAX_CLUSTER_SHARE))
            if collapse or too_big:
                problems.append(
                    f"{name}: 归并吞并 {len(keys)}/{total} 个选项，超过安全上限，已忽略"
                )
                continue
```

三条阈值同时生效：

| 阈值 | 值 | 含义 |
|---|---|---|
| `MAX_CLUSTER_SIZE` | 4 | 一个簇最多 4 种写法，超过多半是误并 |
| `MAX_CLUSTER_SHARE` | 0.50 | 簇大小 ≥3 时，不得吞并同组一半以上选项 |
| 塌缩判定 | `len(keys) >= total` | 簇覆盖全组，直接拒绝 |

算几个例子：24 个选项的组，2 项合并（8.3%）通过；4 项合并（16.7%）通过；5 项合并被 `MAX_CLUSTER_SIZE` 拒；5 个选项的组里合并 3 项（60% > 50%）被份额拒；合并全部 5 项被塌缩判定拒。被拒建议不静默丢弃，全部写进 `alignment_report.md` 的"校验提示"，供人判断是模型错了还是阈值太紧。

单选取值同样保守。`_merge_value_maps()` 先做确定性归一（大小写、标点、空白），模型建议只在文本互相包含时采纳：

```436:441:llm/llm_survey/align_stage.py
        for key, canonical in (model_clusters.get(col) or {}).items():
            if key in mapping or key == norm_key(canonical):
                continue
            if not _related(key, norm_key(canonical)):
                continue
            mapping[key] = canonical
```

于是像 `VS Code` 与 `Visual Studio Code` 这种缩写对（归一后 `vs code` 并非 `visual studio code` 的子串），即使模型提出来也会被拒。这是有意取舍：**在"少合并"和"误合并"之间选少合并。** 少合并的代价是列少、趋势断；误合并的代价是数字错，而且很难发现。

六类护栏放在一张表里：

| 校验函数 | 管什么 | 失败后的动作 |
|---|---|---|
| `validate_semantics` | 列必须在本批、kind 合法、不得重复标注 | 丢弃非法条目，缺列补默认 |
| `validate_global_plan` | 算子白名单、证据非零、删行≤60%、删列≤20% | 改判不执行，删列进人工队列 |
| `validate_group_map` | 组名在输入清单、标准路径非空且无空格 | 跳过该条，保留原名 |
| `validate_cluster_batch` | 文本存在、不得重复归簇、防整组塌缩 | 忽略该簇，记 problem |
| `validate_stats_plan` | 前缀命中真实列、top_n 夹到 2–30 | 丢弃主题，计划为空则报错 |
| `validate_chart_specs` | 数据源存在、图型在白名单、最多 12 张 | 丢该图，全空则用默认规格 |

## 10.7 统计与图表：模型定口径，Python 算数，模型写话

统计阶段把职责切成三段，互不越界：

1. 模型给 `stats_plan`：主题名、组前缀、Top-N、分母（`total` / `answered`）；
2. Python 按 `stats_stage.group_stats()` 计算，写 `stats/*.csv`；
3. 模型读统计表写 3–5 句解读，拼进 `reports/analysis_report.md`。

`group_stats()` 的口径与第 7 章完全一致：多选题分子是"该选项列非空"的行数，分母按 `denominator` 取当年总样本或该题作答人数；单选题按取值分布统计。这段代码是全管线最"传统"的部分，也是唯一产出数字的部分：

```90:100:llm/llm_survey/stats_stage.py
def group_stats(df: pd.DataFrame, group: str, cols: list[str],
                denominator: str, single_choice: bool = False) -> pd.DataFrame:
    """一个题目组在某年的选项占比（%）。

    - 多选题：每个选项列一「选中即计入」，分母按 denominator 取总样本或作答人数
    - 单选题：列为整题，按取值分布统计（分母同上）
    """
    total = len(df)
    if not cols:
        return pd.DataFrame(columns=["group", "option", "n", "pct", "denominator"])
```

模型的计划要被裁剪才能落地：前缀必须在真实列集合里存在，否则整个主题丢弃；`top_n` 夹到 2–30；分母只接受 `total/answered`。本次得到 8 个主题、17 个统计 CSV——注意 `preferred_language` 与 `programming_languages` 都指向 `other.lang`，报告里因此出现两节内容相近的章节。管线保留模型的原始计划，没有替它去重：**计划质量由人判断，代码不偷偷改语义。**

图表阶段更短：模型从"可用统计表清单"（文件名、行数、列名、前几个选项）里挑数据源、图型、Top-N、标题，`validate_chart_specs()` 核对数据源存在、图型在 `bar/hbar/line/grouped_bar/heatmap` 内，再由 matplotlib（Agg）渲染 10 张 PNG。模型不生成任何绘图代码——"决策与执行分离"的又一次应用。

文字解读是整条管线最不可靠的环节。真实产出里有这样的句子：

> Bash/Shell 则从 27.4% 下降至 30.9% 后趋于平稳。

从 27.4% "下降"到 30.9%，方向自相矛盾。同一份报告的 `python_usage` 一节里，`ide.python_version` 下挂着的选项是 `Yes` 与 `No, I use Python as a secondary language`——题目组名和选项含义对不上，正是 10.5 节那次误映射在下游留下的痕迹。这些错误没有被护栏拦住，因为叙述文本没有可机器校验的约束，`validate_narrative()` 只能检查非空与长度。

处理方式写在报告和 README 里：**数值以 CSV 为准，文字仅作参考。** 若要把 LLM 解读用于交付，必须人工逐句核对每个数字的来源，等同于重写。更稳的做法是只把模型解读当草稿提示，最终文字按第 9 章的纪律自己写。

## 10.8 缓存、断点续跑与人工修订

230 个决策文件不是日志，是**唯一事实来源**。缓存键把"这次请求"完整编码：

```30:36:llm/llm_survey/cache.py
def build_key(stage: str, payload: Any, digest: str, prompt_version: str) -> str:
    blob = json.dumps(
        {"stage": stage, "payload": payload, "digest": digest, "pv": prompt_version},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]
```

四个顶层输入任一变化就换键：阶段名、payload（列名清单/批量文本）、模型 digest、提示词版本。payload 是结构化对象，列顺序不同同样会换键——自检里专门断言了这一点，因为 `[a, b]` 与 `[b, a]` 是两次不同的提问。

每条记录包含 `response`（模型原始 JSON）、`duration_s`、`output_tokens`、`fallback`、`error`、`manual_edit`、`reviewed`、`payload_summary`、`prompt_version`。`save()` 用"临时文件 + `replace`"原子落盘，并保护人工修订：`manual_edit: true` 的记录默认不被覆盖。写入前要过一道"旧记录是否人工编辑"的检查，这是"缓存优先"与"人工优先"的优先级声明。

四种运维动作：

| 场景 | 做法 |
|---|---|
| 阶段中断 | 重跑同一命令，已完成批次全部命中 |
| 修正模型决策 | 编辑 `decisions/<stage>/<hash>.json` 的 `response`，置 `manual_edit` / `reviewed` 为 true，再跑该阶段 |
| 提示词升级 | 改 `config.PROMPT_VERSION` 里对应阶段的版本号（如 `clean_semantics`），让该阶段缓存整体失效 |
| 高危删列 | 看报告里的"待确认"列表，把确认的列写进 `llm/decisions/review_approved.json`，`--apply-review` 重跑 clean |

`--refresh` 是"重新问一遍"，`manual_edit` 是"以我的答案为准"，两者会互相干扰：`--refresh` 让 `load()` 跳过缓存、重新调模型，本次运行用的是新响应；但 `save()` 不会覆盖 `manual_edit` 记录，磁盘上的人工答案仍在。于是同一次运行的结果与落盘内容可能不一致。想让某几批重算又保持其余缓存，删对应缓存文件比全局 `--refresh` 更精确。

## 10.9 一致性核对：两条管线到底谁对

`parity.py` 做三件确定性比对，只在最后请模型写一段分歧解读。

| 指标 | 规则管线 | LLM 管线 |
|---|---|---|
| 总表列数（不含 year） | 153 | 40 |
| 归一后匹配列 | — | 36（Jaccard 22.9%） |

- **行数**：2019/2020/2023/2024 完全一致；2021 差 23 行（23,201 vs 23,178），2022 差 23 行（23,009 vs 22,986）。来源是 10.4 节的去重口径：LLM 管线 2021 删 438 行、2022 删 302 行，规则管线分别删 415、279。
- **非空率**：36 个同名匹配列，差异 ≥1pp 的为 **0 条**。这条最有价值——说明"同一列名下的执行结果完全一致"，两边对"非空即选中"的理解没有分歧。
- **同主题占比**：按 LLM 统计表的主题口径在规则总表上复算，12 条对比中只有 2 条不同，且都是 `other.lang.C/C++` 的 **0.1pp**（28.1% vs 28.2%）。最可能来自分母口径：规则管线用作答人数，LLM 用当年总样本。

结论应该这样表述：**重叠部分的执行质量一致；差异集中在"哪些列算同一题"，而不是"同一题算得对不对"。** Jaccard 22.9% 低，不是因为 LLM 算错，而是因为它只统一了 21 个组路径，规则管线的手工同义词表覆盖到 153 列；同时它把 `is.python.main` 误并进 `ide.python_version`，又制造了 16 个 `__dup`。

模型的 parity 解读则给了一个反面示范：

> 综合来看，LLM 管线因能捕捉更多业务上下文且核心指标一致，其结果在统计推断上更为可信。

这句话在两个层面越界。事实层面：LLM 管线只有 40 列，少的正是 CI、云平台、大数据等主题（规则管线独有列里可见 `bigdata.*`、`ci.*`），"捕捉更多业务上下文"与列清单相反。方法层面：40 列 vs 153 列、Jaccard 22.9% 的比对，不足以给两条管线排"谁更可信"；能支持的结论只有"重叠列一致、覆盖范围不同"。这就是 9.3 节讲的"从数字到解释的鸿沟"，只不过这次跨越鸿沟的是模型。

对账的正确用法是**定位差异**，不是让模型打分：

- 只看同名匹配列 → 验证执行层；
- 看仅规则有 / 仅 LLM 有的列 → 暴露同义词表覆盖与误映射；
- 看行数与分母 → 暴露清洗口径差异；
- 模型那段解读只当"待核对的假设清单"读。

## 10.10 什么时候用哪条管线

这不是"新技术替代旧技术"的故事，而是两种成本结构的取舍：

| 你的目标 | 选择 |
|---|---|
| 交付一份可引用的分析报告 | 规则管线（确定、覆盖全、可审计） |
| 新一年数据到手，想快速知道有哪些新题、该怎么归组 | LLM 管线先出候选，人工确认后写进规则管线映射表 |
| 怀疑规则管线的同义词表漏了组 | 看 `group_merges` 与 parity 的"仅 LLM 有"列 |
| 需要给非技术同事解释"为什么这样对齐" | 决策 JSON 里的 `reason` 字段比代码可读 |
| 没有 GPU / 不能装 Ollama | 规则管线；LLM 管线只能在已有清洗产物上用 `--dry-run` 看对齐/统计的默认分支，不是完整替代 |

本次运行的六条已知局限，也是这套方法的边界：

1. **选项级归并过于保守**：4B 的整组塌缩建议被全部拒绝，`value_mapping.csv` 为空。宁可不合并，也不误合并。
2. **组路径覆盖有限**：21 个高置信映射 vs 规则管线 46 条手工同义词，跨年共有列只有 40。
3. **2019 结构差异**：整句表头 + 网格题，组名与 2020+ 难以完全对齐，进一步压缩交集。
4. **叙述不稳定**：方向矛盾、题目组名与选项含义错位；数值以 CSV 为准。
5. **统计计划有冗余**：两个主题指向同一组，报告重复章节，未做人工去重。
6. **只做元数据级决策**：不逐行看数据，发现不了行级异常值。

如果要把这套方法推进一步，优先级不是换更大的模型，而是补三样工程件：**选项层面的证据（如选项在问卷中的原始顺序）、跨年同题的强约束（如题干文本相似度）、以及人工确认队列的闭环**。模型能力提升会改善提议质量，但"提议—校验—执行—对账"的骨架不该变。

## 练习题

**练习 10.1**（画像判读）某列画像为 `non_empty_pct=55.3, n_unique=1, top=["requirements.txt"], flags=["multi_like"]`。a) 它应该被标成哪种 `kind`？b) `non_empty_pct=55.3` 在这类列上含义是什么？c) 如果模型把它标成 `single_choice`，管线最终会得到什么 kind，理由字段会多出什么？

**练习 10.2**（护栏计算）某多选题组有 18 个选项，模型给出以下四个簇：A 含 2 项、B 含 4 项、C 含 5 项、D 含 17 项。a) 按 `MAX_CLUSTER_SIZE=4`、`MAX_CLUSTER_SHARE=0.5` 与塌缩判定，逐簇判断是否被接受；b) 该组的 `value_mapping.csv` 会记录几条；c) 如果这是一道单选题且 A、B 的写法满足文本相关，又会记录几条？

**练习 10.3**（缓存行为）下列操作后，对应阶段是命中缓存还是重新请求模型？a) 同一批列 `[a, b]` 重跑；b) 同一批列以 `[b, a]` 顺序重跑；c) 只改 `prompts.py` 里模板文字、不改 `PROMPT_VERSION`；d) 手工把某条决策的 `response` 改对并置 `manual_edit: true`，然后重跑该阶段；e) 执行 `--refresh`。

**练习 10.4**（对账解读）根据 10.9 节的三个数字（Jaccard 22.9%、非空率差异 0 条、同主题最大差 0.1pp），写一段 3 句以内的结论，要求不出现"更可信"这类比较级，并指出至少一个不能从这些数字推出的判断。

**练习 10.5**（迁移设计）假设你要用同样的思路处理"电商五年订单数据"：字段逐年改名、状态枚举逐年新增、口径（GMV 定义）变过一次。列出哪些决策可以交给模型、哪些必须确定性执行、以及你会加哪两条护栏。

### 参考答案

**10.1** a) `multi_option`：取值恒等于列名末段，是典型的"非空即选中"勾选列。b) 该列 55.3% 的行为非空，即选中了 `requirements.txt`；不能读成"44.7% 缺失"——多选题的空串里混着"未选中"与"未作答"，这也是第 7 章强调分母口径的原因。c) `_align_kind_with_evidence()` 会依据 `multi_like` 把它纠正为 `multi_option`，并在 `reason` 末尾追加"（画像显示为勾选标记列，按多选题选项列纠正）"；原始判断仍保留在缓存 `response` 里，可审计。

**10.2** a) A（2 项，11.1%）接受；B（4 项，22.2%）接受，恰好等于 `MAX_CLUSTER_SIZE`；C（5 项）被 `MAX_CLUSTER_SIZE` 拒（5/18=27.8% 未超份额，但 size 已超）；D（17 项）被 `MAX_CLUSTER_SIZE` 拒（`17 < 18` 不触发塌缩判定，但 17 > 4）。b) 0 条——`align_stage.py` 在收集取值单元时只取 `kind == "single_choice"` 的列，多选题的选项归并走的是组路径/列名层，不写 `value_mapping.csv`。c) 若为单选且 A、B 满足文本相关，则记录 6 条（2+4）；若写法不满足子串关系，仍会被 `_related()` 丢掉。

**10.3** a) 命中；b) 未命中——payload 顺序不同，`sort_keys=True` 只排序字典键，不排序列表元素；c) 命中旧缓存，模板改动不生效，这是最隐蔽的坑，必须同步升 `PROMPT_VERSION`；d) 命中，`load()` 直接返回人工修改后的记录（不调用模型，也不走 `save()`，`manual_kept` 不增加）；e) 全部重新请求；但 `save()` 默认 `force=False`，已标记 `manual_edit` 的记录不会被覆盖——磁盘保留人工版本，本次运行却用了新响应，两者不一致。想精确重算某几批，删对应缓存文件即可。

**10.4** 示例："两条管线在 36 个同名匹配列上的非空率完全一致（差异 ≥1pp 的 0 条），同主题占比最大差 0.1pp，说明重叠部分的执行口径一致；总表列数 153 vs 40、Jaccard 22.9%，说明差异主要在题目组覆盖范围而非计算质量。"不能推出的判断：哪条管线"更可信"、LLM 管线的结论"更接近真实"、未匹配的 117 列"都是规则管线多余的"——这些都需要逐列核对语义，Jaccard 只描述集合重叠，不描述正确性。

**10.5** 可交给模型：字段改名的候选映射、状态枚举的同义归并建议、主题分组与图表选型、分节文字草稿。必须确定性执行：金额/税率/退款的计算、去重与主键约束、GMV 口径切换的时间点与分母、任何写库操作。两条护栏示例：① **口径变更白名单**——2022 年前后 GMV 定义不同，跨年比较必须显式声明断点，模型无权把两种口径的字段直接并成一列（类比 `MAX_CLUSTER_SHARE` 的"不许整组合并"）；② **金额守恒校验**——订单明细汇总必须等于订单头金额、退款后净额不得为负，任何模型建议的清洗算子执行后都要过这道等式（类比 `validate_global_plan` 的证据反向约束）。核心迁移的是骨架：模型只提议、证据优先、护栏验收、产物对账。


