"""盘古 openPangu-Embedded 驱动管线入口。

与 llm/run_llm_pipeline.py 共用全部阶段逻辑、提示词、护栏与词表，差别只有两点：
  1. 产物根目录指向 pangu/（决策缓存、清洗表、对齐表、报告互不污染）；
  2. 默认模型为盘古 GGUF。

用法：
  python pangu/run_pangu.py --stage ping
  python pangu/run_pangu.py --stage selftest
  python pangu/run_pangu.py --stage clean --years 2019 2020
  python pangu/run_pangu.py --stage all

切换模型（1B/7B 对照）：
  $env:LLM_SURVEY_MODEL="pangu-emb-1b"; python pangu/run_pangu.py --stage ping

环境变量必须在这里、导入 llm_survey 之前设置：config 在模块导入时即求值。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LLM_DIR = HERE.parent / "llm"

# setdefault：允许调用方用环境变量覆盖，不硬性锁死。
os.environ.setdefault("LLM_SURVEY_OUT_ROOT", str(HERE))
os.environ.setdefault("LLM_SURVEY_MODEL", "pangu-emb-7b")

if str(LLM_DIR) not in sys.path:
    sys.path.insert(0, str(LLM_DIR))

from run_llm_pipeline import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
