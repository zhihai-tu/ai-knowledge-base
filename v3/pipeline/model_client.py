"""向后兼容的 re-export 层（Deprecated）。

LLM 调用统一入口已迁移至 :mod:`workflows.model_client`，本模块仅为
向后兼容保留，所有实现均在 ``workflows.model_client`` 中。新代码请
直接 ``from workflows.model_client import ...``。

注意：``pipeline.py`` 以 ``python pipeline.py`` 运行时 ``sys.path[0]``
指向 pipeline 目录，此处显式把项目根目录加入 ``sys.path``，保证两者
都能正确解析 ``workflows`` 包。
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from workflows.model_client import (  # noqa: E402,F401
    DEFAULT_PROVIDER,
    DEFAULT_TIMEOUT,
    MAX_RETRIES,
    BASE_RETRY_DELAY,
    RETRYABLE_STATUS_CODES,
    PROVIDER_CONFIGS,
    MODEL_PRICES_USD,
    Usage,
    LLMResponse,
    LLMProvider,
    load_dotenv,
    create_provider,
    chat_with_retry,
    calculate_cost,
    chat_json,
    accumulate_usage,
    main,
)

__all__ = [
    "DEFAULT_PROVIDER",
    "DEFAULT_TIMEOUT",
    "MAX_RETRIES",
    "BASE_RETRY_DELAY",
    "RETRYABLE_STATUS_CODES",
    "PROVIDER_CONFIGS",
    "MODEL_PRICES_USD",
    "Usage",
    "LLMResponse",
    "LLMProvider",
    "load_dotenv",
    "create_provider",
    "chat_with_retry",
    "calculate_cost",
    "chat_json",
    "accumulate_usage",
    "main",
]