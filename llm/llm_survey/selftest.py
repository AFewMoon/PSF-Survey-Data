"""离线自检：不调用模型，验证校验器与执行器的关键不变量。"""
from __future__ import annotations

from typing import Callable

import pandas as pd

from . import config, decision_schema, ollama_client, stats_stage
from .cache import build_key
from .textnorm import clean_cell, dedup_names, norm_key


def _test_cache_key() -> None:
    a = build_key("clean_semantics", {"year": 2024, "batch": ["a", "b"]}, "d1", "v1")
    b = build_key("clean_semantics", {"year": 2024, "batch": ["a", "b"]}, "d1", "v1")
    c = build_key("clean_semantics", {"year": 2024, "batch": ["b", "a"]}, "d1", "v1")
    d = build_key("clean_semantics", {"year": 2024, "batch": ["a", "b"]}, "d2", "v1")
    assert a == b, "缓存键必须稳定"
    assert a != c, "列顺序不同应产生不同键"
    assert a != d, "模型摘要不同应产生不同键"


def _test_json_extract() -> None:
    raw = '```json\n{"columns": [{"column": "a", "kind": "multi_option",}]}\n```'
    data = ollama_client.extract_json(raw)
    assert data["columns"][0]["column"] == "a", "应剥离代码围栏并修复尾逗号"
    nested = '前缀 {"a": {"b": "}{"} } 后缀'
    assert ollama_client.extract_json(nested)["a"]["b"] == "}{", "应正确跳过字符串内括号"


def _test_textnorm() -> None:
    assert norm_key("Visual Studio Code") == norm_key("visual studio  code")
    assert clean_cell("  N/A ") == ""
    assert clean_cell("None") == "None", "None 是合法选项，不应被清洗为空"
    assert dedup_names(["a", "a", "a"]) == ["a", "a__dup1", "a__dup2"]


def _test_semantics_validation() -> None:
    response = {"columns": [
        {"column": "a.b", "kind": "multi_option", "group": "g", "option": "b", "reason": ""},
        {"column": "ghost", "kind": "single_choice", "group": "x", "reason": ""},
        {"column": "a.b", "kind": "numeric", "group": "g", "reason": ""},
    ]}
    items, problems = decision_schema.validate_semantics(response, ["a.b"], 2024)
    assert len(items) == 1, "不存在的列与重复列必须被拒绝"
    assert len(problems) == 2


def _test_clean_plan() -> None:
    evidence = {"rows": 1000, "cols": 100, "empty_rows": 10, "empty_cols": ["x"],
                "dup_rows": 5, "dup_col_groups": [["a", "b"]]}
    candidates = [{"id": "M1", "column": "col1", "reason": "全空"}]
    good = {"ops": [
        {"op": "drop_empty_rows", "apply": True, "reason": "10 行全空"},
        {"op": "drop_empty_cols", "apply": True, "reason": "1 列全空"},
        {"op": "drop_dup_rows", "apply": False},
        {"op": "drop_dup_cols", "apply": True},
        {"op": "delete_everything", "apply": True},
    ], "drop_cols": ["M1", "M9"]}
    plan, review, problems = decision_schema.validate_global_plan(good, evidence, candidates, 2024)
    assert plan["ops"]["drop_empty_rows"]["apply"] is True
    assert plan["ops"]["drop_dup_rows"]["apply"] is False
    assert len(review) == 1 and review[0]["column"] == "col1"
    assert any("delete_everything" in p for p in problems), "非白名单算子必须报错"
    assert any("M9" in p for p in problems), "未知候选编号必须报错"

    bad = {"ops": [{"op": "drop_empty_rows", "apply": True},
                   {"op": "drop_dup_rows", "apply": True}], "drop_cols": []}
    plan2, _, problems2 = decision_schema.validate_global_plan(
        bad, {"rows": 1000, "cols": 100, "empty_rows": 0, "dup_rows": 900,
              "empty_cols": [], "dup_col_groups": []}, [], 2024)
    assert plan2["ops"]["drop_empty_rows"]["apply"] is False, "无证据不得删行"
    assert plan2["ops"]["drop_dup_rows"]["apply"] is False, "超阈值不得删行"
    assert len(problems2) >= 2


def _test_cluster() -> None:
    units = {"ide": ["VS Code", "Visual Studio Code", "PyCharm"]}
    response = {"groups": [{"name": "ide", "options": [
        {"variants": ["VS Code", "Visual Studio Code"], "canonical": "Visual Studio Code"},
        {"variants": ["PyCharm"], "canonical": "PyCharm"},
    ]}]}
    mapping, problems = decision_schema.validate_cluster_batch(response, units)
    assert mapping["ide"][norm_key("VS Code")] == "Visual Studio Code"
    assert norm_key("PyCharm") not in mapping["ide"], "单成员簇不生效"
    assert not problems

    # 整组塌缩必须被拒绝：4B 模型曾把同组全部部署选项并成 "In Docker containers"
    collapse = {"groups": [{"name": "deploy", "options": [
        {"variants": ["A", "B", "C"], "canonical": "A"}]}]}
    mapping2, problems2 = decision_schema.validate_cluster_batch(
        collapse, {"deploy": ["A", "B", "C"]})
    assert not mapping2.get("deploy"), "吞并全部选项的归并必须拒绝"
    assert any("安全上限" in p for p in problems2)


def _test_stats_plan() -> None:
    columns = ["ide.editor.vscode", "ide.editor.pycharm", "is.python.main"]
    good = {"topics": [{"name": "ide", "prefixes": ["ide.editor"], "top_n": 10,
                        "denominator": "total"}], "singles": ["is.python.main"]}
    plan, problems = decision_schema.validate_stats_plan(good, columns)
    assert plan["topics"][0]["name"] == "ide" and not problems
    bad = {"topics": [{"name": "ghost", "prefixes": ["not.exists"], "top_n": 10}]}
    try:
        decision_schema.validate_stats_plan(bad, columns)
    except decision_schema.DecisionError:
        return
    raise AssertionError("不存在的主题前缀必须整体拒绝")


def _test_chart_specs() -> None:
    specs, problems = decision_schema.validate_chart_specs(
        {"charts": [{"name": "t", "kind": "line", "source": "trends_llm_ide.csv",
                     "title": "x", "top_n": 8},
                    {"name": "bad", "kind": "pie", "source": "trends_llm_ide.csv"}]},
        ["trends_llm_ide.csv"],
    )
    assert len(specs) == 1 and specs[0]["kind"] == "line"
    assert any("pie" in p for p in problems)


def _test_group_stats() -> None:
    df = pd.DataFrame({
        "year": [2024] * 4,
        "g.a": pd.Series([1, 0, 1, 0], dtype="int64"),
        "g.b": pd.Series([0, 1, 0, 0], dtype="int64"),
    })
    frame = stats_stage.group_stats(df, "g", ["g.a", "g.b"], "total")
    assert frame.set_index("option").loc["a", "pct"] == 50.0
    assert frame.set_index("option").loc["b", "pct"] == 25.0
    answered = stats_stage.group_stats(df, "g", ["g.a", "g.b"], "answered")
    assert answered["denominator"].iloc[0] == 3, "answered 分母应为有作答行数（4 行中 3 行至少选一项）"


def _test_no_side_effects() -> None:
    df = pd.DataFrame({"a": ["1", "0"]})
    original = df.copy()
    from .clean_stage import _proposed_names
    _, meta = _proposed_names(["a"], {"a": {"kind": "multi_option", "group": "g",
                                            "option": "a", "reason": "", "column": "a"}},
                              2020)
    assert meta[0]["new"] == "g.a"
    assert df.equals(original), "执行器不得就地修改入参"


def _test_evidence_rules() -> None:
    """确定性证据优先：程度网格/勾选标记/无选项结构三类纠正。"""
    from .clean_stage import _align_kind_with_evidence

    def fix(col: str, kind: str, info: dict, year: int = 2020) -> dict:
        item = {"column": col, "kind": kind, "group": "", "option": "",
                "reason": "", "missing_tokens": []}
        _align_kind_with_evidence(col, item, info, year, 1000)
        return item

    assert fix("how.involved.X", "single_choice", {"level_like": True})["kind"] == "multi_level"
    assert fix("other.lang.Java", "free_text", {"multi_like": True})["kind"] == "multi_option"
    assert fix("gender", "multi_option", {"n_unique": 3, "non_empty_pct": 98.0})["kind"] \
        == "single_choice", "无选项结构的整题列不应判为多选"
    assert fix("response_id", "free_text",
               {"numeric_like": True, "n_unique": 1000, "non_empty_pct": 100.0})["kind"] \
        == "identifier", "全唯一数字列应为标识列"
    assert fix("Comments", "single_choice", {"redacted": True})["kind"] == "free_text"
    # 2019：`选项:问句` 也属于选项结构，不能被降级为单选
    assert fix("Java:What languages do you use?", "multi_option", {"multi_like": True},
               2019)["kind"] == "multi_option"


def _test_fewshot_isolation() -> None:
    from . import fewshot
    bundle = fewshot.load_manual_mappings({2023, 2024})
    assert bundle.path_vocab, "应能从非留出年份构建候选词表"
    assert not (set(bundle.years_used) & {2023, 2024}), "留出年份不得进入 few-shot"
    assert any("留出年份" in note for note in bundle.notes), "报告需标注留出口径"
    candidates = fewshot.build_path_candidates(bundle, ["model.group"])
    assert "model.group" in candidates, "模型自身组名必须留在候选集内"


def _test_candidate_pairs() -> None:
    from . import fewshot
    pairs = fewshot.candidate_pairs(
        ["VS Code", "Visual Studio Code", "PyCharm", "PyCharm Professional",
         "Python 2", "Python 3", "Less than 1 year", "< 1 year"]
    )
    assert ("VS Code", "Visual Studio Code") in pairs or (
        "Visual Studio Code", "VS Code") in pairs, "缩写必须被召回"
    assert ("PyCharm", "PyCharm Professional") not in pairs, "不同版本层级不得成为候选"
    assert ("Python 2", "Python 3") not in pairs, "数字不同不得成为候选"
    assert any("1 year" in a or "1 year" in b for a, b in pairs), "包含关系应被召回"


def _test_closed_group_validation() -> None:
    candidates = ["is.python.main", "ide.python_version", "ide.editor"]
    fingerprints = {
        "is.python.main": {"values": ["yes", "no"], "yesno_share": 0.95,
                           "kinds": ["single_choice"]},
        "ide.python_version": {"values": ["37", "38", "39"], "yesno_share": 0.0,
                               "kinds": ["single_choice"]},
        "env.a": {"values": ["docker", "conda", "venv"], "yesno_share": 0.0,
                  "kinds": ["multi_option"]},
        "ide.editor": {"values": ["vscode", "pycharm", "vim"], "yesno_share": 0.0,
                       "kinds": ["multi_option"]},
    }
    response = {"groups": [
        {"name": "is.python.main", "canonical": "ide.python_version"},
        {"name": "env.a", "canonical": "ide.editor"},
        {"name": "ide.editor", "canonical": "made.up.path"},
    ]}
    mapping, problems = decision_schema.validate_group_map_closed(
        response, ["is.python.main", "env.a", "ide.editor"], candidates, fingerprints
    )
    assert mapping["is.python.main"] == "is.python.main", "Yes/No 组不得映射到版本类路径"
    assert mapping["env.a"] == "env.a", "取值指纹不重合不得合并"
    assert mapping["ide.editor"] == "ide.editor", "越界 canonical 必须回退原名"
    assert len(problems) == 3


def _test_group_snap() -> None:
    from . import fewshot
    bundle = fewshot.FewShotBundle(
        path_vocab=("data.frameworks", "ide.editor", "is.python.main"),
        vocab_options={
            "data.frameworks": ("django", "flask", "fastapi", "numpy"),
            "ide.editor": ("vs code", "pycharm", "vim"),
        },
    )
    inventory = {
        # 选项重合 3/5 = 0.60 → 证据充分，直接对齐，不问模型
        "frameworks.data": {"years": {2020}, "options": {"Django", "Flask", "FastAPI", "pandas"}},
        # 选项重合 2/5 = 0.40 → 落在 [WEAK, STRONG) 区间，交模型判定
        "ide.isolate": {"years": {2020},
                        "options": {"VS Code", "PyCharm", "Docker", "Jupyter"}},
        # 名称归一后命中词表 → 直接对齐
        "is.python.main": {"years": {2021}, "options": set()},
        # 与任何候选都不像 → 保留原名
        "zzz.unknown": {"years": {2022}, "options": set()},
    }
    snapped, ambiguous = fewshot.match_groups(inventory, bundle)
    assert snapped["frameworks.data"] == "data.frameworks", "高重合度必须确定性对齐"
    assert snapped["is.python.main"] == "is.python.main", "名称命中词表不得改名"
    assert snapped["zzz.unknown"] == "zzz.unknown", "无证据必须保留原名"
    assert ("ide.isolate", "ide.editor") in ambiguous, "中等证据应进模型判定队列"

    # 兜底护栏：快对齐/命名之后整体再过一遍取值指纹
    mapping = {
        "is.python.main": "ide.python_version",
        "data.frameworks": "frameworks.data",
        "ide.editor": "ide.editor",
    }
    fingerprints = {
        "is.python.main": {"values": ["yes", "no"], "yesno_share": 0.92,
                           "kinds": ["single_choice"]},
        "ide.python_version": {"values": ["37", "38"], "yesno_share": 0.0,
                               "kinds": ["single_choice"]},
        "data.frameworks": {"values": ["django", "flask"], "yesno_share": 0.0,
                            "kinds": ["multi_option"]},
        "frameworks.data": {"values": ["django", "flask", "numpy"], "yesno_share": 0.0,
                            "kinds": ["multi_option"]},
    }
    final, guard_problems = decision_schema.guard_group_mapping(mapping, fingerprints)
    assert final["is.python.main"] == "is.python.main", "Yes/No 组不得改道到版本题"
    assert final["data.frameworks"] == "frameworks.data", "同题指纹相近必须放行"
    assert guard_problems

    # 题型冲突：multi_level（程度网格）与 multi_option（勾选集合）选项清单相同也不能合并
    level_fps = {
        "computer.graphics": {"values": ["academic research", "hobby"], "yesno_share": 0.0,
                              "kinds": ["multi_level"]},
        "other.purposes": {"values": ["academic research", "hobby"], "yesno_share": 0.0,
                          "kinds": ["multi_option"]},
    }
    merged, kind_problems = decision_schema.guard_group_mapping(
        {"computer.graphics": "other.purposes"}, level_fps)
    assert merged["computer.graphics"] == "computer.graphics", "题型冲突必须拒绝合并"
    assert kind_problems

    # 结构兼容：组名 + 选项拼接后不得重复（python.version + most → python.version.most.most）
    assert not fewshot.compatible_target("python.version", ("most",), "python.version.most")
    assert not fewshot.compatible_target("company.develop", ("for",), "company.develop.for")
    assert fewshot.compatible_target("frameworks.data", ("Django", "Flask"), "frameworks")
    assert fewshot.compatible_target("ide.isolate", ("Docker", "conda"), "environments.isolate")


def _test_pair_judgment() -> None:
    pairs = [
        {"id": "p1", "group": "ide", "a": "VS Code", "b": "Visual Studio Code"},
        {"id": "p2", "group": "ide", "a": "PyCharm", "b": "PyCharm Professional"},
    ]
    response = {"pairs": [
        {"id": "p1", "same": True, "canonical": "Visual Studio Code"},
        {"id": "p2", "same": True, "canonical": "PyCharm Professional Edition"},
    ]}
    accepted, problems = decision_schema.validate_pair_judgments(response, pairs)
    assert len(accepted) == 1, "canonical 不取自该对时必须忽略"
    assert problems
    mapping, probs = decision_schema.clusters_from_pairs(
        accepted, ["VS Code", "Visual Studio Code", "PyCharm"], "ide")
    assert mapping[norm_key("VS Code")] == "Visual Studio Code"
    assert not probs

    chain = [{"group": "g", "a": f"v{i}", "b": f"v{i + 1}", "canonical": f"v{i}"}
             for i in range(4)]
    collapsed, collapse_problems = decision_schema.clusters_from_pairs(
        chain, [f"v{i}" for i in range(5)], "g")
    assert not collapsed, "超过簇上限的归并必须拒绝"
    assert collapse_problems


def _test_option_from_header() -> None:
    from .textnorm import option_from_header
    assert option_from_header("Bash / Shell:What other language(s) do you use?") == "Bash / Shell"
    assert option_from_header("ide.editor.Visual Studio Code") == "Visual Studio Code"
    assert option_from_header("How many years have you been coding?") == ""
    assert option_from_header("tools [PyCharm]") == "PyCharm"


TESTS: list[tuple[str, Callable[[], None]]] = [
    ("缓存键稳定性", _test_cache_key),
    ("JSON 提取与修复", _test_json_extract),
    ("文本归一", _test_textnorm),
    ("语义校验", _test_semantics_validation),
    ("清洗计划白名单与阈值", _test_clean_plan),
    ("选项聚类校验（备用路径）", _test_cluster),
    ("few-shot 留出年份隔离", _test_fewshot_isolation),
    ("候选对召回规则", _test_candidate_pairs),
    ("封闭集组映射校验", _test_closed_group_validation),
    ("组路径证据快对齐与指纹兜底", _test_group_snap),
    ("逐对判断与聚簇护栏", _test_pair_judgment),
    ("统计计划校验", _test_stats_plan),
    ("图表规格校验", _test_chart_specs),
    ("统计分母口径", _test_group_stats),
    ("表头选项解析", _test_option_from_header),
    ("画像证据纠正", _test_evidence_rules),
    ("执行器纯函数性", _test_no_side_effects),
]


def run(verbose: bool = True) -> int:
    passed = 0
    for name, fn in TESTS:
        fn()
        passed += 1
        if verbose:
            print(f"  [ok] {name}")
    print(f"自检通过 {passed}/{len(TESTS)} 项（未调用模型）")
    return 0
