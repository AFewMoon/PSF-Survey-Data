"""集中配置：路径、年份、模型参数、提示词版本与安全阈值。

所有可调参数只在本文件，各阶段脚本只读不改。
"""
from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------- 路径
LLM_DIR = Path(__file__).resolve().parents[1]
ROOT = LLM_DIR.parent

YEARS: list[int] = [2019, 2020, 2021, 2022, 2023, 2024]
LATEST: int = 2024

RAW_FILES: dict[int, str] = {
    2019: "2019_python_psf_external_19.csv",
    2020: "2020_2020_sharing_data_outside.csv",
    2021: "2021_2021_sharing_data_outside.csv",
    2022: "2022_2022_sharing_data_outside.csv",
    2023: "2023_2023_sharing_data_outside.csv",
    2024: "2024_2024_sharing_data_outside.csv",
}

RAW_ENC = "utf-8-sig"

DECISIONS_DIR = LLM_DIR / "decisions"
PROFILE_DIR = DECISIONS_DIR / "profile"
CLEAN_DECISIONS_DIR = DECISIONS_DIR / "clean"
ALIGN_DECISIONS_DIR = DECISIONS_DIR / "align"
STATS_DECISIONS_DIR = DECISIONS_DIR / "stats"
CHART_DECISIONS_DIR = DECISIONS_DIR / "chart"
PARITY_DECISIONS_DIR = DECISIONS_DIR / "parity"
REVIEW_FILE = DECISIONS_DIR / "review_approved.json"

CLEANED_DIR = LLM_DIR / "cleaned"
ALIGNED_DIR = LLM_DIR / "aligned"
STATS_DIR = LLM_DIR / "stats"
CHARTS_DIR = LLM_DIR / "charts"
REPORTS_DIR = LLM_DIR / "reports"

# 规则管线产物（只读，用于一致性核对）
RULE_ALIGNED_DIR = ROOT / "aligned"
RULE_CLEANED_DIR = ROOT / "cleaned"

# ---------------------------------------------------------------- 模型
MODEL = os.environ.get("LLM_SURVEY_MODEL", "qwen3.5:4b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
TEMPERATURE = 0.0
SEED = 42
NUM_CTX = 8192
NUM_PREDICT_MIN = 512
NUM_PREDICT_PER_COL = 90
KEEP_ALIVE = "30m"
# qwen3.5 默认 thinking=true 时单次调用可达 80s+，管线必须关闭思考链
THINK = False
TIMEOUT_S = 300
MAX_RETRIES = 3
RETRY_BACKOFF_S = (1.0, 2.0, 4.0)
CONNECT_TIMEOUT_S = 10

# ---------------------------------------------------------------- 批大小
BATCH_COLS = int(os.environ.get("LLM_SURVEY_BATCH", "18"))
BATCH_COLS_MIN = 4
BATCH_CHAR_BUDGET = 6000  # 单请求「列名+样本」字符预算，超预算自动拆批

# ---------------------------------------------------------------- 画像
PROFILE_VERSION = 4  # 画像结构变更时自增，旧缓存画像自动重建
PROMPT_SAMPLE_VALUES = 6
PROMPT_VALUE_MAXLEN = 48
PROFILE_FREE_TEXT_UNIQUE = 200

# ---------------------------------------------------------------- 清洗安全阈值
MISSING_TOKENS = frozenset({"", "na", "n/a", "nan", "null", "none.", "unknown"})
# 这些文本即使模型判为缺失也不改写（本身可能是合法选项）
PROTECTED_TOKENS = frozenset({"none", "no", "not sure", "0", "1"})
MAX_EXTRA_MISSING_SHARE = 0.05  # 模型新增缺失标记最多覆盖该列非空值的 5%
MAX_DROP_COL_SHARE = 0.20  # 单年 drop_col 不得超过列数的 20%
MAX_DROP_ROW_SHARE = 0.60  # 删行不得超过 60%（防误删）
MAX_CLUSTER_SIZE = 4  # 一次归并最多合并 4 种写法（超过多为误并）
MAX_CLUSTER_SHARE = 0.50  # 一次归并不得吞并同组一半以上选项

# ---------------------------------------------------------------- Few-shot 与封闭集
# 留出年份：这些年份的人工映射不进提示词，只用于最终对账（公平比较）
HOLDOUT_YEARS: set[int] = {
    int(y) for y in os.environ.get("LLM_SURVEY_HOLDOUT", "2023,2024").replace(" ", "").split(",")
    if y
}
FEWSHOT_PATH_EXAMPLES = 8     # 组路径映射范例条数（too many 会挤占 8k 上下文）
FEWSHOT_VALUE_EXAMPLES = 6    # 取值写法范例条数
PATH_CANDIDATE_MAX = 200      # 单批送入的封闭候选路径上限（超出按相似度剪枝）
PAIR_SIM_THRESHOLD = 0.70     # difflib 相似度阈值：达到才生成候选对
PAIR_BATCH_SIZE = 24          # 单次请求的候选对数量
PAIR_TOKEN_MIN_SHARE = 0.50   # token 交集占短文本比例下限（防仅字符偶然相似）
GROUP_SNAP_STRONG = 0.60      # 选项重合度 ≥ 该值：确定性对齐到人工标准路径
GROUP_SNAP_WEAK = 0.40        # 介于强弱阈值之间：交给模型判定是否同题
GROUP_SNAP_MARGIN = 0.10      # 第一与第二候选的差距低于该值即视为有歧义，交模型判定
GROUP_NAME_SIM = 0.90         # 单选题按归一后名称相似度对齐的阈值
GROUP_FP_JACCARD_MIN = 0.20   # 组映射前后取值指纹 Jaccard 下限，低于则拒绝合并
GROUP_FP_MIN_ITEMS = 3        # 指纹条目少于此数时不据此否决（证据不足）
YES_NO_SHARE_MAX = 0.60       # 源组取值 Yes/No 占比超过该值时，禁止映射到「版本」类路径

# ---------------------------------------------------------------- 提示词版本
# 修改任一提示词模板时必须同步升版本，否则缓存会复用旧决策
PROMPT_VERSION: dict[str, str] = {
    "clean_semantics": "clean-semantics-v2",
    "clean_plan": "clean-plan-v1",
    "group_path": "group-path-v3",
    "group_pair": "group-pair-v1",
    "option_alias": "option-alias-v2",
    "pair_judge": "pair-judge-v1",
    "stats_plan": "stats-plan-v1",
    "stats_narrative": "stats-narrative-v1",
    "chart_spec": "chart-spec-v1",
    "parity_note": "parity-note-v1",
}

# ---------------------------------------------------------------- 语义枚举
KINDS = (
    "single_choice",   # 单选题：一个受访者一个答案
    "multi_option",    # 多选题的某个选项列：非空即选中
    "multi_level",     # 多选程度网格：非空=参与，取值表示程度（如 "X : primary activity"）
    "numeric",         # 数值（年龄、年限、人数）
    "identifier",      # 样本 ID
    "free_text",       # 自由文本（可能含个人信息）
    "metadata",        # 与调查内容无关的元数据/空列
)

CLEAN_OPS = (
    "keep",            # 显式保留（唯一必须逐列覆盖的算子）
    "rename",          # 重命名
    "binarize",        # 非空->1，空->0
    "to_numeric",      # 转数值
    "drop_col",        # 删列（高危，需人工确认）
    "drop_empty_rows",  # 删全空行
    "drop_empty_cols",  # 删全空列
    "drop_dup_rows",   # 删完全重复行
    "drop_dup_cols",   # 删内容完全相同的列
)

REVIEW_OPS = frozenset({"drop_col"})
