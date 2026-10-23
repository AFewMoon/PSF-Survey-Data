# 第 10 章 LLM 驱动管线：模型做语义判断，代码做执行

> 目标：读懂 `llm/` 这套与规则管线并行的第二条实现。它用本地 `qwen3.5:4b` 完成列语义标注、跨年组路径统一、统计口径设计、图表选型与文字解读，用 Python 完成校验、执行与报告。本章重点不是"怎么调模型"，而是**怎样把不确定的模型输出接进一条必须可复现的数据管线**。

## 10.1 为什么还要一条管线

前九章的规则管线是完全确定的：算子、`GROUP_REMAP_2019`、`GROUP_PATH_CANON`、`OPTION_ALIASES`，每一条都是人工看过列名后写下的。代价也很清楚：

- 对齐后的总表有 153 列，背后是 382 条列名映射、109,745 条取值统一记录；
- 每新增一年（比如 2024 的 `ai` / `bi` / `region` / `trusted` 前缀），都要人工把新列翻一遍；
- 同义判断（`data.frameworks` 与 `frameworks.ml`、`isolate.environments` 与 `environments.isolate`）靠人肉维护同义词表，覆盖不全就丢列。

LLM 管线要验证的是一个工程问题：**这些语义决策能不能由模型从"列名 + 聚合画像"里提出来，再被确定性护栏约束到可接受的质量**。答案是"能，但模型只该做判断，不该做生成"——第 10.5 节会展开这句话。它有三条不可让步的原则：

1. **不替代规则管线**。两者产物各自独立，规则管线的 `cleaned/`、`aligned/`、`analysis/` 不被读写，最后用 `parity` 阶段对账。
2. **模型不接触数据本体**。模型只看到"列名 + 非空率 + 基数 + 至多 6 个截断样本值"，永远不逐行处理 18.5 万行，也不看自由文本原文。
3. **决策全部落盘、可校验、可重放**。模型输出只是候选 JSON，先过 `decision_schema.py`，再由纯函数执行；每次调用的响应、耗时、降级标记都写进 `decisions/`。

一句话概括分工：**模型是提建议的实习生，护栏是签字的主管，缓存是会议纪要。**

| 维度 | 规则管线 | LLM 管线 |
|---|---|---|
| 决策来源 | 人工映射表 + 固定逻辑 | 模型建议 + 证据纠错 + 护栏 |
| 可复现性 | 天然确定 | 靠 temperature=0 + seed + 决策缓存 |
| 扩展新一年 | 人工读列名、补映射 | 重跑，模型给候选，人只审高危项 |
| 语义覆盖面 | 153 列（手工同义词表较全） | 110 列（20 个组路径被改写、31 个选项簇、5,217 条取值统一） |
| 出错方式 | 漏映射（列丢失） | 误映射（列并错），需要 parity 兜底 |
| 适合场景 | 交付、长期维护 | 探索、辅助人工扩表、交叉验证 |

## 10.2 一次运行的全貌

```powershell
ollama serve                                      # 前置：本地 Ollama，模型已拉取
python llm/run_llm_pipeline.py --stage ping       # 健康检查，打印模型名与 digest
python llm/run_llm_pipeline.py --stage selftest   # 离线自检（17 项不变量检查，不调模型）
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
| `--holdout-years` | 留出年份（默认 `2023 2024`），这些年的人工映射不进提示词，只用于对账 |

阶段依赖固定：`profile → clean → align → stats → charts → parity`（画像、清洗、对齐、统计、图表、对账）。

`--dry-run` 有一个容易误解的地方：`clean_stage.clean_year()` 在 `client is None` 时直接返回，**不产出清洗文件**；只有 align/stats/charts 有离线分支。所以它适合"已有清洗产物、只想看默认对齐/统计"的场景，不能当首次运行的预览。首次请先 `--stage selftest`，再小范围 `--stage clean --years 2024`。

本机实测规模（RTX 5070 Laptop 8 GB）：

| 项 | 值 |
|---|---|
| 决策文件 | 304 个（clean 149 / align 130 / stats 14 / profile 6 / parity 4 / chart 1） |
| 首次全量 | 约 30 分钟 |
| 命中缓存全量 | 2.7 分钟（模型调用 0 次） |
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

## 10.5 对齐阶段：证据先定，模型只判定，词表只管写法

`align_stage.run()` 仍是四步流水线（组路径 → 列名 → 取值 → 交集），每步的输入都是上一步的产物。变的是每一步"谁说了算"：改造前，模型既是发现者又是命名者，它直接给出标准路径和同义簇；改造后，**证据负责发现、模型负责边界判断、人工词表负责命名**。

### 第一步：组路径的三段式

从清洗阶段留下的 `columns` 元数据收集 164 个题目组，要落到人工那套命名上。人工路线靠维护同义词表，这里靠三样东西分工：

| 段落 | 谁做 | 判据 |
|---|---|---|
| 快对齐 | 代码，不问模型 | 名称归一后命中人工词表；或多选选项 Jaccard ≥0.60 且领先第二候选 ≥0.10 |
| 逐对判断 | 模型，只答 a/b | 证据落在 [0.40, 0.60) 或前两名接近，且两条路径有共同实义词元 |
| 闭集命名 | 模型，只能选候选 | 候选来自人工词表的 84 条路径，缺省 `keep` |

**快对齐**的判据写在 `fewshot.match_groups()` 里，两种证据任一成立就定案：

```375:400:llm/llm_survey/fewshot.py
        if len(options) >= 2:
            scored: list[tuple[float, str]] = []
            for path, vocab_options in vocab_sets.items():
                if len(vocab_options) < 2:
                    continue
                if not compatible_target(name, options_tuple, path):
                    continue
                union = len(options | vocab_options)
                if not union:
                    continue
                scored.append((len(options & vocab_options) / union, path))
            scored.sort(key=lambda item: (-item[0], item[1]))
            best_score, best_path = scored[0] if scored else (0.0, "")
            second = scored[1][0] if len(scored) > 1 else 0.0
            # 选项文本在不同题目间可能重复（如「用 Python 做什么」与「参与哪些活动」共享同一份
            # 活动清单），所以第一候选必须明显领先才算证据充分，否则降级交模型判定。
            clear = best_score - second >= config.GROUP_SNAP_MARGIN
            if best_path and best_score >= config.GROUP_SNAP_STRONG and clear:
                snapped[name] = best_path
            elif (best_path and best_score >= config.GROUP_SNAP_WEAK
                  and _name_support(name, best_path)):
                # 证据不足时还要求名称有共同词元：否则「选项清单相同、题目完全不同」的
                # 假候选（how.involved 与 other.purposes）会被模型顺手判成同题。
                ambiguous.append((name, best_path))
            else:
                snapped[name] = name
            continue
```

数据给出的证据相当硬：`frameworks.data → frameworks` 选项重合 0.93，`isolate.environments → environments.isolate` 0.78，`ide.os → devenv.os` 0.67，`cloud.platforms → cloud.platform` 0.65。这几条不需要模型参与，代码自己就定了。

「领先第二候选」这一条看着像洁癖，其实是踩过坑的：选项清单在"用途/活动"类题目之间会整份重复（`how.involved` 与 `other.purposes` 都在问"参与哪些活动"），只看重合度会把两道不同的题并成一道。

**逐对判断**处理证据不够硬的组对。模型只回答"这两个路径是不是同一道题"，答案只能是 `a` 或 `b`，没有第三种写法：

```132:168:llm/llm_survey/align_stage.py
    for batch in _chunk_pairs(ambiguous, config.BATCH_CHAR_BUDGET, config.PAIR_BATCH_SIZE):
        payload = [
            {
                "id": f"p{i + 1}",
                "a": name,
                "b": target,
                "a_years": sorted(inventory[name]["years"]),
                "b_years": sorted(snap_years.get(target, set())),
                "a_sample": inventory[name]["sample"][:5],
                "b_sample": list(bundle.vocab_options.get(target, ()))[:5],
            }
            for i, (name, target) in enumerate(batch)
        ]
        system, user = prompts.group_pair_messages(payload)
        key = cache_pair.key(
            {"pairs": [list(p) for p in batch], "holdout": sorted(bundle.holdout_years)},
            config.PROMPT_VERSION["group_pair"],
        )
        judges += len(batch)

        def call(sys_msg=system, usr_msg=user,
                 n=len(batch)) -> tuple[dict[str, Any], ChatMeta]:
            return client.chat_json(sys_msg, usr_msg, num_predict=max(500, n * 70),
                                    tag="group-pair")

        response, _, _ = cache_pair.get_or_call(
            key, config.PROMPT_VERSION["group_pair"], {"n_pairs": len(batch)}, call,
            fallback=lambda: {"pairs": []},
        )
        ok, chunk_problems = decision_schema.validate_group_pairs(response, payload)
        problems += chunk_problems
        accepted += ok

    cluster_map, cluster_problems = decision_schema.clusters_from_pairs(
        accepted, names + [target for _name, target in ambiguous], "groups")
    problems += cluster_problems
    merged = {name: cluster_map.get(norm_key(name), snapped.get(name, name)) for name in names}
```

注意 `clusters_from_pairs()`：逐对判断的结论不能直接当映射用，要先用并查集拼成簇——否则 A 判"与 B 同题"、B 判"与 C 不同题"这种互相矛盾的答案会同时生效。

**闭集命名**兜最后一段：快对齐和逐对判断都没定案的组，去候选词表里挑一个写法，挑不出来就 `keep`。校验只认候选集和 `keep`，其他一律回退原名：

```262:268:llm/llm_survey/decision_schema.py
        if not dst or dst == "keep":
            mapping[src] = src
            continue
        if dst not in allowed_dst:
            problems.append(f"{src}: canonical 不在候选集（{dst!r}），已保留原名")
            mapping[src] = src
            continue
```

还有一道结构护栏，专治"改完名反而更糟"：

```311:328:llm/llm_survey/fewshot.py
def compatible_target(name: str, options: tuple[str, ...] | list[str], target: str) -> bool:
    """结构兼容性：组路径重命名后不得与自身选项重复拼接。

    多选题的列名是 `组 + "." + 选项`，若把组 `python.version`（选项 `most`）改名成
    `python.version.most`，列会变成 `python.version.most.most`；单选题把整列名当组名
    同理。判据：目标路径是原组名的延伸，或以本组某个选项结尾，都视为结构冲突。
    """
    key = norm_key(name)
    tkey = norm_key(target)
    if not key or not tkey or key == tkey:
        return True
    if tkey.startswith(key) and len(tkey) > len(key):
        return False
    for option in options:
        ok = norm_key(option)
        if ok and len(ok) >= 2 and tkey != ok and tkey.endswith(ok):
            return False
    return True
```

三道工序跑完，本次有 20 个组路径被改写，其中真正需要模型判断的是少数：

| 原路径 | 标准路径 | 涉及年份 |
|---|---|---|
| `data.frameworks` | `frameworks` | 2020–2022 |
| `isolate.environments` | `environments.isolate` | 2020–2022 |
| `ide.isolate` | `environments.isolate` | 2019 |
| `frameworks.web` | `web.frameworks` | 2019 |
| `ide.upgrade` | `python.version.upgrade` | 2019 |
| `ide.tools.ci` | `ci` | 2019 |
| `job` | `employment.status` | 2021–2024 |
| `role.architect` | `job.role` | 2019 |

改写前后都要过同一道兜底：`guard_group_mapping()` 把最终整条映射再按取值指纹查一遍，防止某条路径从快对齐或闭集命名绕开语义检查（细节见 10.6）。

### 第二步：重命名与撞名回退

按 `组路径.选项` 拼新列名。如果归并导致同年撞名（两个不同原始列拼成同一个新名），不硬加 `__dup` 掩盖，而是整年回退到确定性归一（`norm_text`）：

```530:541:llm/llm_survey/align_stage.py
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

回退后仍重名的列由 `dedup_names()` 加 `__dup1`、`__dup2` 后缀。这些列内容不同，不能合并——它们往往是"两道题被并成一组"的痕迹，本次共 15 列。

### 第三步：选项与取值，两段式

这一层是全章改动最大的地方。旧做法是让模型对着一个组的 24 个选项输出"同义簇"，模型就会给出"把 24 个并成 1 个"这种整组塌缩。现在拆成两段：

1. **确定性合并先行**：`norm_key` 相同（大小写、标点、空白、全半角差异）直接合并，不问模型；
2. **候选对 + 逐对判断**：剩下的写法用 `difflib` 相似度、缩写（`VS Code` ↔ `Visual Studio Code`）、词元包含三种方式召回候选对，模型只回答"这两个写法是不是同一样东西"，答案的 canonical 必须取自这一对；
3. **并查集聚簇**：逐对结论拼成簇，同时继承塌缩护栏（≤4 项、不吞并半数组）；
4. **按人工词表统一写法**：模型只判同义，写哪个词由人工词表决定（`VS Code` 统一成 `Visual Studio Code`），本次 78 处。

```283:291:llm/llm_survey/align_stage.py
def _judge_units(
    units: dict[str, list[str]], client: OllamaClient, refresh: bool, kind: str,
    counts: dict[tuple[str, str], int] | None = None,
) -> tuple[dict[str, dict[str, str]], int, int, int, list[str], str]:
    """两段式归并：确定性 norm_key 合并 → 候选对逐对判断 → 并查集聚簇。

    返回 ({单元: {norm_key: 标准文本}}, 簇数, 判定对数, 接受对数, problems, 缓存行)。
    逐对判断替代整组开放聚类：4B 只会整列塌缩，但判断「两个文本是否同义」是可靠分类任务。
    """
```

最后一步的写法对齐在 `snap_option_names()` 里，用的是人工词表当字典：

```466:494:llm/llm_survey/fewshot.py
    vocab = bundle.vocab_options.get(group)
    if not vocab:
        return dict(clusters or {})
    vocab_by_key = {norm_key(v): v for v in vocab if norm_key(v)}
    merged = dict(clusters or {})
    members: dict[str, set[str]] = {}
    for value in values:
        canon = merged.get(norm_key(value), norm_text(value))
        members.setdefault(canon, set()).add(value)
    for canon, texts in members.items():
        target = vocab_by_key.get(norm_key(canon))
        if target is None:
            for text in sorted(texts):
                if norm_key(text) in vocab_by_key:
                    target = vocab_by_key[norm_key(text)]
                    break
        if target is None:
            near = {
                vocab_by_key[key]
                for key in vocab_by_key
                if SequenceMatcher(None, norm_key(canon), key).ratio() >= config.GROUP_NAME_SIM
            }
            target = near.pop() if len(near) == 1 else None
        if target is None:
            continue
        for text in texts:
            merged[norm_key(text)] = target
        merged[norm_key(canon)] = target
    return merged
```

本次落地的规模：31 个同义簇、162 对判定（接受 34 对）、**5,217 条取值统一记录**。这个口径和规则管线的 109,745 条一致，数的是"受影响的单元格"，不是"映射条目"——去重之后只有 25 条不同映射（`value_mapping.csv` 去掉重复行就是这 25 行），其中 21 条是版本号字形归一（`Python 2.3` → `Python 2_3`），真正的词义归并是 `use.python.most` 的长句截短和 `Eclipse with PyDev → Eclipse + Pydev` 这类。改造前这个数字是 0：不是没有变体，是模型的归并建议全被护栏拒了。

### 第四步：取交集合并

六年列名取交集得 **110 列**，纵向拼成 185,586 行。110 列的主题分布：

| 主题 | 列数 |
|---|---|
| `other.lang.*` | 23 |
| `database.*` | 15 |
| `ide.editor.*` | 13 |
| `cloud.platform.*` | 11 |
| `python.version.upgrade.*` | 10 |
| `web.frameworks.*` | 10 |
| `ci.*` | 9 |
| 其余（`configuration.management`、`devenv.os`、`environments.isolate`、`bigdata` 等） | 19 |

### 为什么把"生成"换成"分类"

改造前的三条失败模式，恰好都落在"让模型生成"的环节：

1. **自由生成路径**。让模型对着 164 个组输出"标准路径"，它六年只改了 1 处——4B 在开放式命名上没有主见，`keep` 是它的默认答案；一旦它真给出新名字，又常常是自造的、词表里根本没有的路径，下游无法与人工产物对齐。
2. **整组塌缩**。让模型对一个组输出同义簇，它会把 24 个选项并成 `In Docker containers` 一个文本，执行下去这一列就从分布变成常数。塌缩护栏当时全部拦下，代价是 `value_mapping.csv` 为空。
3. **语义改道**。`is.python.main`（是否以 Python 为主）被映射到 `ide.python_version`（版本题）。这条映射在结构上完全合法：路径非空、无空格、小写点分，格式护栏没有理由拒绝，模型还六年一致地给出同一个答案。后果是 2019 年 5 个来源列被并成一组，四个真正的版本列降级为 `__dup1..4`，跨年总表的 `ide.python_version` 里装的其实是"Yes/No"，下游解读把普及度当成版本趋势写。**格式合法保证不了语义正确。**

三条失败有一个共同点：模型的语义理解没错，错的是任务形式。判断"这两条路径是不是同一道题"、"这两个写法是不是同一样东西"是分类任务，4B 稳定；"请给出标准路径"、"请把这 24 个选项聚类"是生成任务，4B 不稳定。所以改造的方向不是换更大的模型，而是**把生成任务改写成分类任务**：候选由人工词表和数据证据给出，模型只在少数边界上做二元判断，确定性可判的部分（归一后相等、选项重合 0.93）根本不问模型。

### 评测口径：留出年份

词表和 few-shot 范例只从 2019–2022 的人工映射里取，2023/2024 的人工结果不进提示词（`config.HOLDOUT_YEARS`，可用 `--holdout-years` 覆盖）。这三年份的映射只在一件事上使用：parity 对账。

道理很直白：如果把 2023/2024 的 canonical 也放进候选词表，模型等于开卷考试，10.9 节的 105 个匹配列就不再是"它自己对齐出来的"。代价是留出年份独有的写法可能与人工产物不一致，这是应该保留的差距，不是缺陷。

## 10.6 护栏：用数据本身否决语义

组路径的三段式里，模型已经不能自造路径了，但"结构合法、语义错误"的映射仍然可能出现——`is.python.main → ide.python_version` 就是模板：路径合法、年份稳定、模型六年一致。这类错误用格式校验拦不住，只能用**数据本身**拦。

`_fingerprint_reject()` 拿每列的取值指纹去核对映射，三条判据各管一类错误：

```194:231:llm/llm_survey/decision_schema.py
    if fsrc.get("yesno_share", 0.0) >= config.YES_NO_SHARE_MAX and any(
        marker in segment
        for segment in dst.split(".")
        for marker in ("version", "release")
    ):
        return (
            f"{src}: 取值以 Yes/No 为主（{fsrc['yesno_share']:.0%}），"
            f"不能映射到版本类路径 {dst}，已保留原名"
        )
    fdst = fingerprints.get(dst)
    if not fdst:
        return ""
    kinds_src = set(fsrc.get("kinds", ()))
    kinds_dst = set(fdst.get("kinds", ()))
    if (kinds_src == {"multi_level"} and kinds_dst == {"multi_option"}) or (
        kinds_src == {"multi_option"} and kinds_dst == {"multi_level"}
    ):
        # 同一份选项清单可能来自不同题型：multi_level 是「程度网格」（primary/secondary/hobby），
        # multi_option 是「勾选集合」。两者题目不同，选项重合再高也不能合并。
        return (
            f"{src} → {dst}: 题型冲突（{next(iter(kinds_src))} vs {next(iter(kinds_dst))}），"
            "已保留原名"
        )
    if "multi_option" not in kinds_src and "multi_level" not in kinds_src:
        # 单选取值随年份变化是常态（版本号、年限区间），集合不重合不代表题目不同；
        # 只有多选题的选项文本才是稳定的「同题指纹」。
        return ""
    left = set(fsrc.get("values", []))
    right = set(fdst.get("values", []))
    if len(left) >= config.GROUP_FP_MIN_ITEMS and len(right) >= config.GROUP_FP_MIN_ITEMS:
        union = left | right
        jaccard = len(left & right) / len(union) if union else 0.0
        if jaccard < config.GROUP_FP_JACCARD_MIN:
            return (
                f"{src} → {dst}: 取值指纹 Jaccard {jaccard:.2f} 低于 "
                f"{config.GROUP_FP_JACCARD_MIN}，已保留原名"
            )
    return ""
```

四条阈值，各拦一类错误：

| 护栏 | 判据 | 拦的是什么 |
|---|---|---|
| Yes/No 改道 | 源组 Yes/No 占比 ≥0.60，且目标路径某一段含 `version` / `release` | `is.python.main → ide.python_version` |
| 题型冲突 | `multi_level` 与 `multi_option` 互斥，重合再高也不合 | 2019 的程度网格并入 2020 的勾选集合 |
| 选项指纹 | 两边都是多选、各 ≥3 项时，取值 Jaccard <0.20 拒合 | 名字相近但选项完全不同的两组 |
| 结构兼容 | 目标路径是本组名延伸，或以本组某个选项结尾 | `python.version.most.most`、`company.develop.for.for` |

单选题为什么直接放行？单选取值逐年变化是常态——版本号从 `3.7` 走到 `3.12`、年限区间从 `2 年` 走到 `5 年`，集合不重合不能说明题目不同。只有多选题的选项文本才是稳定的"同题指纹"，这一条是实测调出来的：早期版本对单选也查 Jaccard，误拒了版本题。

组路径之外，选项归并仍保留塌缩护栏。`clusters_from_pairs()` 用并查集拼簇，同时检查三条上限：

| 阈值 | 值 | 含义 |
|---|---|---|
| `MAX_CLUSTER_SIZE` | 4 | 一个簇最多 4 种写法，超过多半是误并 |
| `MAX_CLUSTER_SHARE` | 0.50 | 簇大小 ≥3 时，不得吞并同组一半以上选项 |
| 塌缩判定 | `len(keys) >= total` | 簇覆盖全组，直接拒绝 |

算几个例子：24 个选项的组，2 项合并（8.3%）通过；4 项合并（16.7%）通过；5 项合并被 `MAX_CLUSTER_SIZE` 拒；5 个选项的组里合并 3 项（60% > 50%）被份额拒；合并全部 5 项被塌缩判定拒。被拒建议不静默丢弃，全部写进 `alignment_report.md` 的"校验提示"，供人判断是模型错了还是阈值太紧。

改造后这些护栏不再"全拒"：`VS Code` 与 `Visual Studio Code` 这种缩写对，旧规则因为"一个 `norm_key` 不是另一个的子串"而拒；现在由缩写召回生成候选对、模型判定、词表给写法，5,217 条取值统一才落得下来。

六类校验函数放在一张表里：

| 校验函数 | 管什么 | 失败后的动作 |
|---|---|---|
| `validate_semantics` | 列必须在本批、kind 合法、不得重复标注 | 丢弃非法条目，缺列补默认 |
| `validate_global_plan` | 算子白名单、证据非零、删行≤60%、删列≤20% | 改判不执行，删列进人工队列 |
| `validate_group_map_closed` | canonical 必须来自候选词表或 `keep`，再过取值指纹 | 回退原名，记 problem |
| `validate_pair_judgments` | 判定必须落在本次提问的对上，canonical 取自该对 | 丢弃非法判定 |
| `guard_group_mapping` | 最终整条映射按取值指纹兜底 | 回退原名，记 problem |
| `validate_stats_plan` / `validate_chart_specs` | 前缀命中真实列、top_n 夹到 2–30、图型在白名单 | 丢弃主题/该图，空则报错或用默认 |

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

从 27.4% "下降"到 30.9%，方向自相矛盾。同一份报告里还有"从 35.8% 上升至 30.9%，虽呈下降趋势"这种把两句话缝在一起的写法。这类错误没有被护栏拦住，因为叙述文本没有可机器校验的约束，`validate_narrative()` 只能检查非空与长度。

另有一类错误是上游留下的：改造前的对齐把 `is.python.main` 误映射到 `ide.python_version`（见 10.5 节末尾），下游解读就正儿八经地拿"Yes/No"讲版本趋势。这类问题现在由 10.6 节的取值指纹护栏挡在对齐环节，但已产出的报告不会自动修正——**统计与图表跑在对齐产物之上，重跑 `align` 之后必须跟着重跑这两阶段**，本节引用的 8 个主题、17 个统计 CSV 来自最近一次全量运行。

处理方式写在报告和 README 里：**数值以 CSV 为准，文字仅作参考。** 若要把 LLM 解读用于交付，必须人工逐句核对每个数字的来源，等同于重写。更稳的做法是只把模型解读当草稿提示，最终文字按第 9 章的纪律自己写。

## 10.8 缓存、断点续跑与人工修订

304 个决策文件不是日志，是**唯一事实来源**。缓存键把"这次请求"完整编码：

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
| 提示词升级 | 改 `config.PROMPT_VERSION` 里对应阶段的版本号（如 `clean_semantics`、`group_path`、`pair_judge`），让该阶段缓存整体失效 |
| 高危删列 | 看报告里的"待确认"列表，把确认的列写进 `llm/decisions/review_approved.json`，`--apply-review` 重跑 clean |

`--refresh` 是"重新问一遍"，`manual_edit` 是"以我的答案为准"，两者会互相干扰：`--refresh` 让 `load()` 跳过缓存、重新调模型，本次运行用的是新响应；但 `save()` 不会覆盖 `manual_edit` 记录，磁盘上的人工答案仍在。于是同一次运行的结果与落盘内容可能不一致。想让某几批重算又保持其余缓存，删对应缓存文件比全局 `--refresh` 更精确。

## 10.9 一致性核对：两条管线到底谁对

`parity.py` 做三件确定性比对，只在最后请模型写一段分歧解读。

| 指标 | 规则管线 | LLM 管线 |
|---|---|---|
| 总表列数（不含 year） | 153 | 110 |
| 归一后匹配列 | — | 105（Jaccard 66.5%） |

- **行数**：2019/2020/2023/2024 完全一致；2021 差 23 行（23,201 vs 23,178），2022 差 23 行（23,009 vs 22,986）。来源是 10.4 节的去重口径：LLM 管线 2021 删 438 行、2022 删 302 行，规则管线分别删 415、279。
- **非空率**：105 个同名匹配列，差异 ≥1pp 的为 **0 条**。这条最有价值——说明"同一列名下的执行结果完全一致"，两边对"非空即选中"的理解没有分歧。
- **同主题占比**：按 LLM 统计表的主题口径在规则总表上复算，12 条对比中只有 2 条不同，且都是 `other.lang.C/C++` 的 **0.1pp**（28.1% vs 28.2%）。最可能来自分母口径：规则管线用作答人数，LLM 用当年总样本。

口径必须交代清楚：`2023`、`2024` 两年的人工映射只用于对账，没有进入候选词表和 few-shot 范例（10.5 节末尾）。所以 105 这个数字是留出测试成绩，不是"照着答案抄出来的"。

剩下的 48 列差距集中在三块，没有一块是"算错了"：

1. **跨年改名的题**：`develop.for.cloud.*`（6 列）在 2019 叫 `run.in.cloud`，`orm.*`（7 列）在 2019 叫 `ide.databases`，`unittesting.*`（8 列）在部分年份换了位置。这类组当前判了 `keep`：证据带内要求名称有共同词元才交模型判定，否则 `how.involved` 与 `other.purposes` 那种"共享整份活动清单"的假候选会被顺手并掉。
2. **整句题名没归位**：人工把 2019 的 `most.of.the.time.do.you` 归到 `other.purposes`，模型给了别的名字且各年不一致，交集里于是没有这一族 17 列。
3. **选项写法**：`ide.editor.Visual Studio Code`、`frameworks.ml.None`、`environments.isolate.virtualenv`、`main.purposes`、`python.years`、`years.of.coding`、`use.python.most`、`python.version.upgrade.Python_org` 八列，语义都对应上了，写法与人工作物不同。

反向只有 5 列是 LLM 独有：`company.size`、`employment.status`、`python2.version.most`、`python3.version.most`、`team.size`——语义上没错，只是命名与人工产物不一致，交集因此少了 5 列。

结论应该这样表述：**重叠部分的执行质量一致；差异集中在"哪些列算同一题"，而不是"同一题算得对不对"。** Jaccard 66.5% 而不是更高，不是因为 LLM 算错，而是因为 20 个组路径的改写还不足以覆盖人工那 46 条同义词，且证据带内要求"名称有共同词元"才交模型判定，跨年改名的题因此宁可漏并。

模型的 parity 解读则给了一个反面示范：

> 鉴于规则管线在开发环境等具体场景下保留了更多原始分类信息，且核心统计指标一致，规则管线结果在细节覆盖上更可信。

这句话在两个层面越界。事实层面：LLM 管线有 110 列，缺的是改名题与选项写法（`develop.for.cloud.*`、`orm.*`、`other.purposes.*`），并不是"开发环境类信息"少——`environments.isolate` 三个选项里有 2 列就在 110 列中，只少 `virtualenv` 一个写法。方法层面：110 列 vs 153 列、Jaccard 66.5% 的比对，不足以给两条管线排"谁更可信"；能支持的结论只有"重叠列一致、覆盖范围不同"。这就是 9.3 节讲的"从数字到解释的鸿沟"，只不过这次跨越鸿沟的是模型。

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

本次运行的七条已知局限，也是这套方法的边界：

1. **跨年改名的题仍然漏并**：`develop.for.cloud.*`、`orm.*`、`unittesting.*` 等组的名字与人工产物没有共同词元，判据不敢放行，48 列差距主要来自这里。
2. **词表覆盖决定上限**：候选路径 84 条、选项写法来自非留出年份的人工产物；留出年份独有的写法（如 `environments.isolate.virtualenv`）对不上是正常的。
3. **2019 结构差异**：整句表头 + 网格题，题型由 `multi_level` 变 `multi_option`，题型冲突护栏会直接拒绝合并。
4. **取值映射的去重口径**：`value_mapping.csv` 按单元格记录，5,217 行去重后只有 25 条不同映射；把这 5,217 当作"映射条目"会高估工作量。
5. **叙述不稳定**：方向矛盾、把两句话缝在一起；数值以 CSV 为准。
6. **统计计划有冗余**：两个主题指向同一组，报告重复章节，未做人工去重。
7. **只做元数据级决策**：不逐行看数据，发现不了行级异常值。

下一步的优先级不是换更大的模型，而是三件事：**给跨年改名题补名称证据**（题干文本相似度，或"同年同题型 + 选项高度重合"的弱信号组合）、**把人工确认做成闭环**（被拒映射进队列，确认后直接写进规则管线映射表）、**让统计与图表跟着对齐产物自动重跑**（当前重跑 `align` 之后要手动跟跑后两阶段）。模型能力提升会改善判断质量，但"证据—判断—护栏—对账"的骨架不该变。

## 练习题

**练习 10.1**（画像判读）某列画像为 `non_empty_pct=55.3, n_unique=1, top=["requirements.txt"], flags=["multi_like"]`。a) 它应该被标成哪种 `kind`？b) `non_empty_pct=55.3` 在这类列上含义是什么？c) 如果模型把它标成 `single_choice`，管线最终会得到什么 kind，理由字段会多出什么？

**练习 10.2**（护栏计算）某多选题组有 18 个选项，逐对判断后并查集给出四个簇：A 含 2 项、B 含 4 项、C 含 5 项、D 含 17 项。a) 按 `MAX_CLUSTER_SIZE=4`、`MAX_CLUSTER_SHARE=0.5` 与塌缩判定，逐簇判断是否被接受；b) 被接受的簇体现在总表的哪一层，会不会写进 `value_mapping.csv`；c) 若同一份选项属于单选题，A、B 经逐对判断确认为同义，`value_mapping.csv` 记几条？

**练习 10.3**（缓存行为）下列操作后，对应阶段是命中缓存还是重新请求模型？a) 同一批列 `[a, b]` 重跑；b) 同一批列以 `[b, a]` 顺序重跑；c) 只改 `prompts.py` 里模板文字、不改 `PROMPT_VERSION`；d) 手工把某条决策的 `response` 改对并置 `manual_edit: true`，然后重跑该阶段；e) 执行 `--refresh`。

**练习 10.4**（对账解读）根据 10.9 节的三个数字（Jaccard 66.5%、非空率差异 0 条、同主题最大差 0.1pp），写一段 3 句以内的结论，要求不出现"更可信"这类比较级，并指出至少一个不能从这些数字推出的判断。

**练习 10.5**（迁移设计）假设你要用同样的思路处理"电商五年订单数据"：字段逐年改名、状态枚举逐年新增、口径（GMV 定义）变过一次。列出哪些决策可以交给模型、哪些必须确定性执行、以及你会加哪两条护栏。

**练习 10.6**（判据选择）两个组对：① 选项 Jaccard 0.78，第二名候选 0.76；② 选项 Jaccard 0.55，两条路径分别叫 `ide.lang.favorite` 与 `language.main`。它们分别走三段式里的哪一段，为什么？如果 ① 的两条路径分别是 `how.involved` 与 `other.purposes`，结局会怎样？

### 参考答案

**10.1** a) `multi_option`：取值恒等于列名末段，是典型的"非空即选中"勾选列。b) 该列 55.3% 的行为非空，即选中了 `requirements.txt`；不能读成"44.7% 缺失"——多选题的空串里混着"未选中"与"未作答"，这也是第 7 章强调分母口径的原因。c) `_align_kind_with_evidence()` 会依据 `multi_like` 把它纠正为 `multi_option`，并在 `reason` 末尾追加"（画像显示为勾选标记列，按多选题选项列纠正）"；原始判断仍保留在缓存 `response` 里，可审计。

**10.2** a) A（2 项，11.1%）接受；B（4 项，22.2%）接受，恰好等于 `MAX_CLUSTER_SIZE`；C（5 项）被 `MAX_CLUSTER_SIZE` 拒（5/18=27.8% 未超份额，但 size 已超）；D（17 项）被 `MAX_CLUSTER_SIZE` 拒（`17 < 18` 不触发塌缩判定，但 17 > 4）。b) 体现在**列名层**：同一簇里的选项拼成同一个 `组.选项` 列名，因此不写 `value_mapping.csv`——取值单元只收 `kind == "single_choice"` 的列。c) 按**单元格**记，不是按映射条目记：A、B 覆盖到的每个原始单元格各记一条，同一年同一列的同一写法会重复出现（本次 5,217 行去重后只有 25 条），因此答"6 条"是错的口径，准确说法是"A、B 共 6 种写法，记录行数等于这些写法在数据里出现的次数"。

**10.3** a) 命中；b) 未命中——payload 顺序不同，`sort_keys=True` 只排序字典键，不排序列表元素；c) 命中旧缓存，模板改动不生效，这是最隐蔽的坑，必须同步升 `PROMPT_VERSION`；d) 命中，`load()` 直接返回人工修改后的记录（不调用模型，也不走 `save()`，`manual_kept` 不增加）；e) 全部重新请求；但 `save()` 默认 `force=False`，已标记 `manual_edit` 的记录不会被覆盖——磁盘保留人工版本，本次运行却用了新响应，两者不一致。想精确重算某几批，删对应缓存文件即可。

**10.4** 示例："两条管线在 105 个同名匹配列上的非空率完全一致（差异 ≥1pp 的 0 条），同主题占比最大差 0.1pp，说明重叠部分的执行口径一致；总表列数 153 vs 110、Jaccard 66.5%，说明差异主要在题目组覆盖范围而非计算质量。"不能推出的判断：哪条管线"更可信"、LLM 管线的结论"更接近真实"、未匹配的 48 列"都是规则管线多余的"——这些都需要逐列核对语义，Jaccard 只描述集合重叠，不描述正确性。

**10.6** ① 走不了快对齐：0.78 虽然过 `GROUP_SNAP_STRONG`，但领先第二名只有 0.02，低于 `GROUP_SNAP_MARGIN=0.10`，说明"两份选项清单大量重复"这件事本身不构成证据；它降级到判定带，名称有共同词元就逐对判，没有就 `keep`。② 0.55 落在 [0.40, 0.60)，`ide.lang.favorite` 与 `language.main` 共享 `lang`/`language` 词元，正好交模型逐对判断。① 若换成 `how.involved` 与 `other.purposes`，两条路径没有共同词元，`_name_support` 直接否决，不进判定；这就是"宁可漏并"的那条线——2019 的活动清单在两道题里整份重复，只靠重合度必然误并。

**10.5** 可交给模型：字段改名的候选映射、状态枚举的同义归并建议、主题分组与图表选型、分节文字草稿。必须确定性执行：金额/税率/退款的计算、去重与主键约束、GMV 口径切换的时间点与分母、任何写库操作。两条护栏示例：① **口径变更白名单**——2022 年前后 GMV 定义不同，跨年比较必须显式声明断点，模型无权把两种口径的字段直接并成一列（类比 `MAX_CLUSTER_SHARE` 的"不许整组合并"）；② **金额守恒校验**——订单明细汇总必须等于订单头金额、退款后净额不得为负，任何模型建议的清洗算子执行后都要过这道等式（类比 `validate_global_plan` 的证据反向约束）。核心迁移的是骨架：模型只提议、证据优先、护栏验收、产物对账。


