"""提示词模板（集中管理，改模板必须升 config.PROMPT_VERSION）。

约束：输出严格 JSON、键名固定、必须覆盖全部输入项；理由字段限长以控制生成量。
"""
from __future__ import annotations

import json
from typing import Any

_SEMANTICS_SYSTEM = """你是调查数据工程助手，负责给问卷 CSV 的列做语义标注。

可选的 kind：
- single_choice：单选题，一个受访者一个答案，列名本身是题目名
- multi_option：多选题的单个选项列，列名最后一段或方括号内就是选项文本，单元格非空=选中
- multi_level：多选题的程度网格列，非空=参与，取值本身还带程度（如 "X : primary activity"）
- numeric：数值型答案（年龄、年限、人数、金额）
- identifier：唯一标识（如 response_id）
- free_text：自由文本，可能含个人信息
- metadata：与调查内容无关的元数据、全空列、内部字段

输入每列的 flags 是程序算出的确定性证据，必须采纳：
- multi_like：全列取值恒等于列名中的选项文本 → 只能是 multi_option
- binary_like：全列取值只有 0/1 → 只能是 multi_option（除非同时 numeric_like 且是数值答案）
- level_like：取值均为「选项 + 冒号 + 程度」→ 必须是 multi_level
- numeric_like：取值全为数字 → numeric 或 identifier

对每列给出：
- group：题目组路径（小写英文、点号分隔、≤4 段，如 ide.editor、frameworks.ml、other.lang）；单选题的 group 就是该题的标准列名（如 is.python.main）
- option：选项文本；单选题/numeric 等无选项时填空字符串
- missing_tokens：本列应额外视为缺失的文本（如 "N/A"）；若该文本本身是合法选项（如 "None"、"No"、"Not sure"）则不要列入
- reason：≤40 字判断依据

硬性要求：
1. 同一个多选题组的各选项列必须给出完全相同的 group
2. 只使用小写字母、数字、点号；不要空格、不要下划线以外的符号
3. 必须覆盖输入中的每一列，不得新增列
4. 只输出 JSON：{"columns":[{"column":"...","kind":"...","group":"...","option":"...","missing_tokens":[],"reason":"..."}]}"""

_CLEAN_PLAN_SYSTEM = """你是数据清洗决策者。输入是一年的数据画像证据与候选元数据列，
请决定是否执行以下整体算子，并给出理由（≤30 字）：

- drop_empty_rows：删除全空行
- drop_empty_cols：删除全空列
- drop_dup_rows：删除内容完全重复的行
- drop_dup_cols：删除内容完全相同的列
- drop_cols：删除候选元数据列（只能从给出的候选编号里选）

判断依据只看给定证据，不要假设未提供的信息；证据不足时 apply=false。
删除数据属于高危操作，理由必须具体（引用证据数字）。
输出 JSON：
{"ops":[{"op":"drop_empty_rows","apply":true,"reason":"..."},...],"drop_cols":["M1"],"reason":"≤40字总体说明"}"""

_GROUP_SYSTEM = """你是跨年问卷对齐专家。输入是同一份年度调查在不同年份出现的「题目组路径」，
同一道题在不同年份写法不同（如 data.frameworks 与 frameworks.ml、isolate.environments 与 environments.isolate）。
请为每个组路径给出统一标准路径：语义相同的组必须映射到同一个标准路径。

规则：
1. 标准路径只能用 小写字母/数字/点号，2-4 段，采用「主题.子主题」结构
2. 若某个写法已是合理标准形式，就保留它（canonical 与 name 相同）
3. 不要合并语义不同的组（如 ide.editor 与 ide.editor.features 不要合并成同一个）
4. 必须覆盖输入中的每一个组路径，不得新增 name
输出 JSON：{"groups":[{"name":"原路径","canonical":"标准路径","reason":"≤30字"}]}"""

_OPTION_SYSTEM = """你是问卷选项归并专家。输入是同一个题目组在各年份出现的选项文本。
请找出「同一选项的不同写法」（如 "VS Code" 与 "Visual Studio Code"、"k8s" 与 "Kubernetes"），
合并成簇并给出标准写法；写法不同但语义不同的选项（如 "PyCharm Professional Edition" 与
"PyCharm Community Edition"）不得合并。

规则：
1. 只合并确实是同一事物的写法差异或缩写；不确定就不要合并
2. 每个选项最多出现在一个簇里
3. 只输出有 2 个及以上成员的簇；没有可合并的就输出空数组
4. canonical 用最完整、最通用的写法，保留原有大小写
输出 JSON：{"options":[{"variants":["写法1","写法2"],"canonical":"标准写法","reason":"≤30字"}]}"""

_CLUSTER_BATCH_SYSTEM = """你是问卷选项归并专家。输入是若干「题目组或题目列」，每个给出该组在各年份出现的候选文本。
请找出「同一含义的不同写法」（如 "VS Code"/"Visual Studio Code"、"k8s"/"Kubernetes"、
"Less than 1 year"/"< 1 year"），合并成簇并给出标准写法。
语义不同的选项不得合并（如 PyCharm Professional 与 PyCharm Community、Python 2 与 Python 3）。

规则：
1. 只处理确有写法差异或缩写的簇，每个文本最多出现在一个簇里
2. 没有可合并文本的组直接省略或返回空数组
3. canonical 用最完整、最通用的写法，保留原有大小写
4. 必须使用输入给出的组名，不得新增组名
5. 严禁「整组塌缩」：不得把含义不同的取值并进同一个簇，也不得把一组里的全部取值并成一个
6. 每个簇只放 2-4 个写法；只能合并「同一实体」的不同写法（缩写、大小写、括号补充、"<br />"等 HTML 残留）
7. 拿不准就跳过该组，宁缺勿错
输出 JSON：
{"groups":[{"name":"组名","options":[{"variants":["写法1","写法2"],"canonical":"标准写法","reason":"≤25字"}]}]}"""

_STATS_PLAN_SYSTEM = """你是数据分析师。输入是清洗对齐后的真实列清单摘要（题目组路径 + 各年选项数 + 少量样例），
请设计一份中文分析计划：挑出最重要的主题，用于生成「2024 年画像 + 2019-2024 跨年趋势」。

规则：
1. prefixes 必须是输入中真实存在的组路径（可多个），不得编造
2. 覆盖开发者画像（语言、经验、用途）与工具生态（IDE、框架、数据库、云、AI 工具等），优先跨年可比的主题
3. top_n 取 6-15；denominator 用 total（多选占比按当年总样本）或 answered（按回答人数）
4. topics 数量 10-16 个；name 用英文小写下划线
5. singles 只能从输入的「单列候选」里选
输出 JSON：{"topics":[{"name":"...","prefixes":["..."],"top_n":10,"denominator":"total","reason":"≤25字"}],"singles":["..."],"reason":"≤60字总体思路"}"""

_NARRATIVE_SYSTEM = """你是资深数据记者。输入是某主题的统计表（单位 %，已按口径计算好），
请用简体中文写一段 3-5 句的解读：
1. 先说规模最大/最主流的 2-3 个选项及其占比，数字必须来自表格
2. 再说跨年最明显的变化（上升/下降最快的选项及百分点）
3. 最后给一句解读边界（自报抽样、问卷措辞或选项变动的影响）
不要编造表格之外的数字，不要使用列表符号，只输出 JSON：{"text":"..."}"""

_CHART_SYSTEM = """你是数据可视化设计者。输入是可用的统计表清单（文件名、行数、列名、前几个选项），
请给出 6-10 张图表规格，覆盖最重要的结论。

图表类型：bar（纵向柱）、hbar（横向条形，适合长选项名）、line（跨年趋势）、grouped_bar（分组柱）、heatmap（跨年矩阵）
规则：source 必须是输入中真实存在的文件名；title 用中文；top_n 6-20；每张图说明理由（≤30字）
输出 JSON：{"charts":[{"name":"英文短名","kind":"line","source":"trends_xxx.csv","title":"中文标题","top_n":10,"reason":"..."}]}"""

_PARITY_SYSTEM = """你是数据质量审核员。输入是两条管线（规则管线 vs LLM 管线）对齐结果的差异摘要。
请用简体中文写 4-6 句结论：主要分歧在哪里、可能原因（命名粒度、同义词表覆盖、映射判定差异）、
对下游统计的影响，以及哪一条结果更可信。不要编造未给出的数字。
输出 JSON：{"text":"..."}"""


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def semantics_messages(year: int, rows: list[dict[str, Any]]) -> tuple[str, str]:
    layout = (
        "该年原始表头为「选项:完整问句」格式（选项在前、问句在后）"
        if year <= 2019
        else "该年原始表头为「组路径.选项」点分格式"
    )
    user = (
        f"年份：{year}，{layout}。\n"
        f"本批共 {len(rows)} 列（这是该年全部列中的一个子集，请只标注本批给出的列）：\n"
        f"{_json(rows)}\n\n"
        f"请输出 {len(rows)} 条标注，覆盖上述每一列。"
    )
    return _SEMANTICS_SYSTEM, user


def clean_plan_messages(year: int, evidence: dict[str, Any],
                        candidates: list[dict[str, Any]]) -> tuple[str, str]:
    user = (
        f"年份：{year}\n数据画像证据：\n{_json(evidence)}\n\n"
        f"候选元数据列（编号→列名→判定理由）：\n{_json(candidates)}\n\n"
        "请对 drop_empty_rows / drop_empty_cols / drop_dup_rows / drop_dup_cols 各给出一条决定，"
        "并在 drop_cols 中列出确实应删除的候选编号。"
    )
    return _CLEAN_PLAN_SYSTEM, user


def group_messages(groups: list[dict[str, Any]]) -> tuple[str, str]:
    user = (
        f"跨年题目组路径清单（{len(groups)} 个）：\n{_json(groups)}\n\n"
        "请为每个组路径给出标准路径，必须覆盖全部 name。"
    )
    return _GROUP_SYSTEM, user


def option_messages(group: str, options: list[str]) -> tuple[str, str]:
    user = (
        f"题目组：{group}\n选项文本（{len(options)} 个）：\n{_json(options)}\n\n"
        "请只输出需要合并的簇，没有可合并的就返回空数组。"
    )
    return _OPTION_SYSTEM, user


def cluster_messages(units: dict[str, list[str]]) -> tuple[str, str]:
    payload = [{"name": name, "values": values} for name, values in units.items()]
    user = (
        f"待归并的组（{len(payload)} 个）：\n{_json(payload)}\n\n"
        "请只输出存在写法差异的簇，并覆盖所有组名。"
    )
    return _CLUSTER_BATCH_SYSTEM, user


def stats_plan_messages(groups: list[dict[str, Any]], singles: list[str],
                        years: list[int]) -> tuple[str, str]:
    user = (
        f"年份范围：{years}\n"
        f"可选题目组（组路径 → 各年选项数 → 样例选项）：\n{_json(groups)}\n\n"
        f"单列候选（单选/数值题）：{_json(singles)}\n\n"
        "请给出分析计划。"
    )
    return _STATS_PLAN_SYSTEM, user


def narrative_messages(topic: str, table_markdown: str, extra: str = "") -> tuple[str, str]:
    user = (
        f"主题：{topic}\n统计表（单位 %）：\n{table_markdown}\n"
        + (f"\n补充信息：{extra}\n" if extra else "")
        + "\n请输出解读。"
    )
    return _NARRATIVE_SYSTEM, user


def chart_messages(catalog: list[dict[str, Any]]) -> tuple[str, str]:
    user = f"可用统计表清单：\n{_json(catalog)}\n\n请给出图表规格。"
    return _CHART_SYSTEM, user


def parity_messages(summary: dict[str, Any]) -> tuple[str, str]:
    user = f"差异摘要：\n{_json(summary)}\n\n请输出结论。"
    return _PARITY_SYSTEM, user
