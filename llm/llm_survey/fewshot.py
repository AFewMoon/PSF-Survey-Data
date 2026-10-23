"""人工映射范例与封闭候选词表（留出年份隔离）。

设计理由：
- 4B 模型「开放式生成」不可靠（自造组路径、整列塌缩），但「在有限集合里做分类」可靠。
  本模块把人工映射表（只读）变成**候选词表 + 少量范例**，让模型做选择题而不是填空题。
- 公平性：留出年份（默认 2023/2024）的人工映射一律不进提示词，只用于最终对账。
  范例与词表只取自非留出年份，等价于「人只有往年经验」。

全部函数为纯函数：入参只读，返回新对象。
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd

from . import config
from .textnorm import norm_key, norm_text

_TOKEN_RE = re.compile(r"[0-9a-z]+")
_NUM_RE = re.compile(r"\d+")
# 同一产品的不同版本/版本层级不是同义写法（人工对齐同样不合并）
_QUALIFIERS = frozenset({
    "professional", "community", "enterprise", "ultimate", "edition",
    "premium", "student", "personal", "team", "business",
})


@dataclass(frozen=True)
class FewShotBundle:
    """非留出年份的人工映射摘要。"""

    holdout_years: frozenset[int] = frozenset()
    years_used: tuple[int, ...] = ()
    path_vocab: tuple[str, ...] = ()
    vocab_options: dict[str, tuple[str, ...]] = field(default_factory=dict)
    path_examples: tuple[tuple[str, str], ...] = ()
    value_examples: tuple[tuple[str, str], ...] = ()
    source_files: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default=())

    @property
    def empty(self) -> bool:
        return not self.path_vocab


def _group_pair(year: int, original: str, canonical: str) -> tuple[str, str]:
    """从一行映射推导 (原组路径, 标准组路径)。

    2019 表头为「问句[选项]」：有方括号才是多选题，否则整句就是单选题目名。
    2020+ 表头为「组.选项」：最后一段恒为选项，两侧各去掉最后一段即得组路径。
    """
    orig = str(original).strip()
    canon = str(canonical).strip()
    if not canon:
        return "", ""
    if year <= 2019:
        if "[" in orig:
            return orig.split("[", 1)[0].strip(), canon.rsplit(".", 1)[0]
        return canon, canon
    orig_group = orig.rsplit(".", 1)[0] if "." in orig else orig
    return orig_group, canon.rsplit(".", 1)[0]


def _path_ok(path: str) -> bool:
    """候选路径形态约束：小写字母/数字/点号，1-4 段，无空格。"""
    if not path or " " in path or path.startswith(".") or path.endswith("."):
        return False
    if not re.fullmatch(r"[a-z0-9._]+", path):
        return False
    return 1 <= len(path.split(".")) <= 4


def _header_group_paths(path: Path) -> tuple[set[str], dict[str, set[str]]]:
    """从分年对齐表头推导人工组路径与各组的选项集合。

    同一前缀下 ≥2 列才视为多选题组；无同前缀兄弟列的按单选题处理（列名即组路径）。
    """
    if not path.exists():
        return set(), {}
    try:
        cols = list(pd.read_csv(path, nrows=0, encoding="utf-8-sig").columns)
    except Exception:  # 表头异常不应阻断对齐
        return set(), {}
    prefixes = Counter(col.rsplit(".", 1)[0] for col in cols if "." in col)
    groups: set[str] = set()
    options: dict[str, set[str]] = {}
    for col in cols:
        if "." in col:
            prefix, option = col.rsplit(".", 1)
            if prefixes[prefix] >= 2:
                groups.add(prefix)
                options.setdefault(prefix, set()).add(option)
            else:
                groups.add(col)  # 单选题
        else:
            groups.add(col)
    return {g for g in groups if _path_ok(g)}, options


def load_manual_mappings(
    holdout_years: set[int] | None = None, root: Path | None = None
) -> FewShotBundle:
    """读取人工映射表，剔除留出年份，返回词表与范例。

    缺文件时返回空 bundle（管线退化为「只用模型自身组名」的封闭集）。
    """
    holdout = frozenset(config.HOLDOUT_YEARS if holdout_years is None else holdout_years)
    base = Path(root) if root is not None else config.ROOT
    col_path = base / "aligned" / "column_mapping.csv"
    val_path = base / "aligned" / "value_mapping.csv"
    notes: list[str] = []
    sources: list[str] = []
    if not col_path.exists():
        notes.append(f"缺少人工列映射：{col_path}")
        return FewShotBundle(holdout_years=holdout, notes=tuple(notes))

    col = pd.read_csv(col_path, keep_default_na=False, encoding="utf-8-sig", dtype=str)
    sources.append("aligned/column_mapping.csv")
    col["year"] = col["year"].astype(int)
    kept = col[~col["year"].isin(holdout)]

    vocab: set[str] = set()
    pairs: dict[tuple[str, str], int] = {}
    for row in kept.itertuples(index=False):
        orig_group, canon_group = _group_pair(int(row.year), row.original, row.canonical)
        if not _path_ok(canon_group):
            continue
        vocab.add(canon_group)
        if orig_group and orig_group != canon_group and _path_ok_orig(orig_group):
            pairs[(orig_group, canon_group)] = pairs.get((orig_group, canon_group), 0) + 1

    # 范例按「标准路径去重」挑选，避免同一组重复占满上下文
    examples: list[tuple[str, str]] = []
    seen_canon: set[str] = set()
    for (orig_group, canon_group), _count in sorted(
        pairs.items(), key=lambda kv: (-len(kv[0]), kv[0][1])
    ):
        if canon_group in seen_canon:
            continue
        examples.append((orig_group, canon_group))
        seen_canon.add(canon_group)
        if len(examples) >= config.FEWSHOT_PATH_EXAMPLES:
            break

    # 分年对齐表头补全人工组路径词表（只取非留出年份，等价于「人只有往年表」）
    vocab_options: dict[str, set[str]] = {}
    for year in sorted(int(y) for y in config.YEARS if int(y) not in holdout):
        header_path = base / "aligned" / f"cleaned_aligned_{year}.csv"
        header_groups, header_options = _header_group_paths(header_path)
        if header_groups:
            vocab |= header_groups
            for path, options in header_options.items():
                vocab_options.setdefault(path, set()).update(options)
            sources.append(f"aligned/cleaned_aligned_{year}.csv（仅表头）")

    value_examples: list[tuple[str, str]] = []
    if val_path.exists():
        val = pd.read_csv(val_path, keep_default_na=False, encoding="utf-8-sig", dtype=str)
        sources.append("aligned/value_mapping.csv")
        val["year"] = val["year"].astype(int)
        val = val[~val["year"].isin(holdout)]
        seen: set[tuple[str, str]] = set()
        for row in val.itertuples(index=False):
            orig, canon = str(row.original).strip(), str(row.canonical).strip()
            if not orig or not canon or orig == canon:
                continue
            if norm_key(orig) == norm_key(canon):
                continue  # 仅标点/空白差异，确定性归一即可，不需要范例
            if sorted(_NUM_RE.findall(orig)) != sorted(_NUM_RE.findall(canon)):
                continue  # 数字不同意味着语义可能不同（如 Python 2 / Python 3），不作范例
            key = (orig, canon)
            if key in seen:
                continue
            seen.add(key)
            value_examples.append(key)
            if len(value_examples) >= config.FEWSHOT_VALUE_EXAMPLES:
                break
    else:
        notes.append(f"缺少人工取值映射：{val_path}")

    years_used = tuple(sorted({int(y) for y in kept["year"]}))
    notes.append(
        f"few-shot 来源年份：{years_used or '无'}；留出年份：{sorted(holdout)}（不参与提示词）"
    )
    return FewShotBundle(
        holdout_years=holdout,
        years_used=years_used,
        path_vocab=tuple(sorted(vocab)),
        vocab_options={path: tuple(sorted(opts)) for path, opts in vocab_options.items()},
        path_examples=tuple(examples),
        value_examples=tuple(value_examples),
        source_files=tuple(sources),
        notes=tuple(notes),
    )


def _path_ok_orig(path: str) -> bool:
    """原组路径只要求非空且不超过 4 段（2019 长问句也算合法输入）。"""
    text = str(path).strip()
    return bool(text) and len(text) <= 120 and len(text.split(".")) <= 4


def build_path_candidates(bundle: FewShotBundle, model_groups: list[str]) -> list[str]:
    """封闭候选词表 = 人工标准路径（非留出年份） ∪ 模型既有组名。"""
    merged = set(bundle.path_vocab)
    merged.update(str(g).strip() for g in model_groups if str(g).strip())
    return sorted(p for p in merged if p)


def path_shortlist(candidates: list[str], groups: list[str], limit: int | None = None) -> list[str]:
    """按与本批组名的相似度剪枝候选，保持排序稳定。"""
    cap = config.PATH_CANDIDATE_MAX if limit is None else limit
    if len(candidates) <= cap:
        return list(candidates)
    group_keys = [norm_key(g) for g in groups if norm_key(g)]
    scored: list[tuple[float, str]] = []
    for cand in candidates:
        ck = norm_key(cand)
        best = 0.0
        for gk in group_keys:
            if not ck or not gk:
                continue
            if ck in gk or gk in ck:
                best = 1.0
                break
            best = max(best, SequenceMatcher(None, ck, gk).ratio())
        scored.append((best, cand))
    scored.sort(key=lambda item: (-item[0], item[1]))
    kept = sorted(cand for _score, cand in scored[:cap])
    return kept


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall(str(text).lower()))


def _initials(text: str) -> str:
    """缩写展开：≤3 字符的词元按字母展开，其余取首字母（VS Code / Visual Studio Code → vsc）。"""
    out: list[str] = []
    for token in _TOKEN_RE.findall(str(text).lower()):
        out.append(token if len(token) <= 3 else token[0])
    return "".join(out)


def _similar(a: str, b: str, threshold: float) -> bool:
    """三条召回规则：字符相似度、缩写一致、词元包含；版本层级差异一律排除。"""
    ka, kb = norm_key(a), norm_key(b)
    if not ka or not kb or ka == kb:
        return False  # 完全相同：确定性归一已处理，无需模型
    if min(len(ka), len(kb)) < 2:
        return False
    if sorted(_NUM_RE.findall(ka)) != sorted(_NUM_RE.findall(kb)):
        return False  # 数字不同多为不同实体（Python 2 / Python 3、7.x / 8.x）
    if SequenceMatcher(None, ka, kb).ratio() >= threshold:
        return True
    ia, ib = _initials(a), _initials(b)
    if len(ia) >= 2 and ia == ib:
        return True
    ta, tb = _tokens(a), _tokens(b)
    shorter, longer = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    if shorter and shorter < longer:
        if longer - shorter & _QUALIFIERS:
            return False
        return True
    return False


def candidate_pairs(
    values: list[str], threshold: float | None = None, limit: int = 40
) -> list[tuple[str, str]]:
    """用 difflib 相似度筛出「可能同义」的候选对，按相似度降序取前 limit 个。

    4B 直接对全组做开放聚类会整列塌缩；只让它判断两个具体文本是否同义，
    任务从「生成」降级为「分类」。
    """
    thr = config.PAIR_SIM_THRESHOLD if threshold is None else threshold
    unique = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        key = norm_key(text)
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    scored: list[tuple[float, str, str]] = []
    for i, left in enumerate(unique):
        for right in unique[i + 1:]:
            if not _similar(left, right, thr):
                continue
            score = SequenceMatcher(None, norm_key(left), norm_key(right)).ratio()
            scored.append((score, left, right))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    return [(left, right) for _score, left, right in scored[:limit]]


def _name_support(a: str, b: str) -> bool:
    """两条组路径是否有共同的实义词元（purposes / isolate / frameworks 这类）。"""
    ta = {t for t in _tokens(a) if len(t) >= 3}
    tb = {t for t in _tokens(b) if len(t) >= 3}
    return bool(ta & tb)


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


def filter_candidates(
    candidates: list[str], groups: list[str], inventory: dict[str, dict]
) -> list[str]:
    """只保留与本批至少一个组结构兼容的候选（挡住 `xxx.for.for` 这类重复拼接）。"""
    kept: list[str] = []
    for cand in candidates:
        for name in groups:
            options = tuple(inventory.get(name, {}).get("options", ()))
            if compatible_target(name, options, cand):
                kept.append(cand)
                break
    return kept


def match_groups(
    inventory: dict[str, dict],
    bundle: FewShotBundle,
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """把每个模型组路径对齐到人工标准路径。

    返回 (snapped, ambiguous)：
    - 名称归一后已在词表中 → 直接对齐
    - 多选题选项重合度 ≥ GROUP_SNAP_STRONG 且明显领先第二候选 → 确定性对齐
    - 证据不足（[WEAK, STRONG) 或前两名接近），且名称有共同词元 → 交模型判定
    - 其余保留原名

    这是「像手搓那样」的关键：人工靠维护同义词表，这里用人工词表 + 选项证据替代，
    合并关系由数据决定，命名由词表决定。
    """
    vocab_sets = {
        path: {norm_key(opt) for opt in options if norm_key(opt)}
        for path, options in bundle.vocab_options.items()
    }
    vocab_by_key = {norm_key(path): path for path in bundle.path_vocab}
    single_vocab = [path for path in bundle.path_vocab if not vocab_sets.get(path)]
    snapped: dict[str, str] = {}
    ambiguous: list[tuple[str, str]] = []
    for name, entry in inventory.items():
        key = norm_key(name)
        if key in vocab_by_key:
            snapped[name] = vocab_by_key[key]
            continue
        options_tuple = tuple(str(opt) for opt in entry.get("options", ()))
        options = {norm_key(opt) for opt in options_tuple if norm_key(opt)}
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
        best_sim, best_single = 0.0, ""
        for path in single_vocab:
            if not compatible_target(name, options_tuple, path):
                continue
            ratio = SequenceMatcher(None, key, norm_key(path)).ratio()
            if ratio > best_sim:
                best_sim, best_single = ratio, path
        snapped[name] = (
            best_single if best_single and best_sim >= config.GROUP_NAME_SIM else name
        )
    return snapped, ambiguous


def group_candidate_pairs(
    inventory: dict[str, dict],
    fingerprints: dict[str, dict] | None = None,
    threshold: float = 0.50,
    min_shared: int = 3,
    limit: int = 80,
) -> list[tuple[str, str]]:
    """按选项重合度生成组对候选：同一道题在不同年份的写法，选项文本高度重合。

    只让多选题参与（选项是可靠证据）；单选题的 Yes/No 取值在组间普遍相同，会制造假候选。
    """
    option_sets: dict[str, set[str]] = {}
    for name, entry in inventory.items():
        keys = {norm_key(opt) for opt in entry.get("options", ()) if norm_key(opt)}
        if len(keys) >= 2:
            option_sets[name] = keys
    scored: list[tuple[float, int, str, str]] = []
    names = sorted(option_sets)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            a, b = option_sets[left], option_sets[right]
            shared = len(a & b)
            if shared < min_shared:
                continue
            union = len(a | b)
            jaccard = shared / union if union else 0.0
            if jaccard >= threshold:
                scored.append((jaccard, shared, left, right))
    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [(left, right) for _j, _s, left, right in scored[:limit]]


def prefer_canonical(left: str, right: str) -> str:
    """模型未给出合法 canonical 时的确定性兜底：取更长、更完整的写法。"""
    return max((left, right), key=lambda v: (len(v), v))


def snap_option_names(
    group: str,
    values: list[str],
    bundle: FewShotBundle,
    clusters: dict[str, str] | None = None,
) -> dict[str, str]:
    """把归并后的选项写法对齐到人工词表里该组已有的选项（闭集，不新造名字）。

    模型逐对判断只回答「是否同一事物」，写法常常落在较口语的一侧（`VS Code` 而不是
    `Visual Studio Code`），跨年列名因此对不上人工产物。这里用人工词表当字典：
    - 归一后完全命中 → 直接采用人工写法
    - 簇内成员任一命中 → 采用人工写法
    - 否则唯一模糊命中（≥0.90）→ 采用人工写法
    """
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


def pair_token(pair: tuple[str, str]) -> str:
    """候选对在提示词与缓存中的稳定标识。"""
    return f"{pair[0]} ⇒ {pair[1]}"
