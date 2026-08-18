"""统一的 LLM 调用客户端（全项目唯一入口）。

本模块是 LLM 调用的统一入口，全项目（pipeline / patterns / workflows / 其他）
均从此导入。``pipeline/model_client.py`` 仅为向后兼容的 re-export 层，
新代码一律直接依赖本模块。

通过环境变量选择模型提供商：

- ``LLM_PROVIDER``: deepseek（默认）| qwen | openai | glm
- ``DEEPSEEK_API_KEY``: DeepSeek 的 API Key
- ``DASHSCOPE_API_KEY``: 阿里云百炼（Qwen）的 API Key
- ``OPENAI_API_KEY``: OpenAI 的 API Key
- ``GLM_API_KEY``: 智谱 GLM（或第三方兼容服务）的 API Key
- ``QWEN_BASE_URL`` / ``QWEN_MODEL``: 可选，覆盖 qwen 的 base_url / 模型名
  （用于百炼专属网关等自定义 OpenAI 兼容地址）
- ``GLM_BASE_URL`` / ``GLM_MODEL``: 可选，覆盖 glm 的 base_url / 模型名
  （用于商汤 SenseNova https://token.sensenova.cn/v1 等第三方兼容服务）

本模块使用 httpx 直接调用 OpenAI 兼容的 /chat/completions 接口，
不依赖 openai SDK。所有提供商均返回统一的结构。

配置优先级：进程环境变量 ``>`` 项目根目录下的 ``.env`` 文件。
后者以内置的 :func:`load_dotenv` 加载，无需安装 python-dotenv。

成本追踪：调用方通过 :func:`accumulate_usage` 把每次调用的 :class:`Usage`
累加进状态中的成本汇总 dict（如 ``state["cost_tracker"]``）。

用法示例::

    from workflows.model_client import chat_json

    parsed, usage = chat_json("用一句话介绍你自己，输出 JSON。")
"""

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "deepseek"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
# 429（限流）时退避时间乘数：部分服务（如商汤 SenseNova）无 Retry-After 头，
# 且对突发速率敏感，需比 5xx 更长的冷却等待。
RATE_LIMIT_BACKOFF_MULTIPLIER = 5.0

# 各提供商的配置：base_url、默认模型、API Key 环境变量名，
# 以及可选的 base_url / 模型名覆盖环境变量（如商汤 SenseNova 等第三方接入）。
PROVIDER_CONFIGS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url_env": "QWEN_BASE_URL",
        "model_env": "QWEN_MODEL",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "glm": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.2",
        "api_key_env": "GLM_API_KEY",
        "base_url_env": "GLM_BASE_URL",
        "model_env": "GLM_MODEL",
    },
}

# 各模型价格（USD / 1M tokens），取值 (输入价, 输出价)。
# 数据为 2026-07 官方公布价格，使用前请核对官方最新价目。
# glm-5.2 价格为第三方资料参考值（约 $1.40/$4.40），待核对官方价目。
MODEL_PRICES_USD = {
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.435, 0.87),
    "qwen-plus": (0.40, 1.20),
    "qwen3.7-plus": (0.28, 1.11),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "glm-5.2": (1.40, 4.40),
}


@dataclass
class Usage:
    """Token 用量统计。

    Attributes:
        prompt_tokens: 输入（提示词）token 数。
        completion_tokens: 输出（补全）token 数。
        total_tokens: 总 token 数。
    """

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """统一的 LLM 响应。

    Attributes:
        content: 模型返回的文本内容。
        usage: Token 用量统计。
        model: 实际使用的模型名称。
        finish_reason: 结束原因（如 stop、length）。
    """

    content: str
    usage: Usage
    model: str
    finish_reason: Optional[str] = None


class LLMProvider:
    """基于 OpenAI 兼容 /chat/completions 接口的 LLM 提供商实现。

    适用于 DeepSeek、Qwen（百炼）、OpenAI、GLM 等提供兼容接口的服务。
    通过 :func:`create_provider` 统一创建。
    """

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        provider_name: Optional[str] = None,
    ) -> None:
        """初始化提供商实例。

        Args:
            api_key: 提供商 API Key。
            base_url: OpenAI 兼容接口的基础地址。
            model: 使用的模型名称。
            provider_name: 提供商名称（deepseek / qwen / openai / glm），
                用于成本追踪与成本键生成（见 :func:`accumulate_usage`）。
        """
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.provider_name = provider_name

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """发起一次对话请求。

        Args:
            messages: OpenAI 格式的对话消息列表，如
                [{"role": "user", "content": "你好"}]。
            temperature: 采样温度，0-2 之间，默认 0.7。
            max_tokens: 输出最大 token 数，不传由服务端决定。

        Returns:
            统一的 LLMResponse 对象。

        Raises:
            httpx.HTTPStatusError: 服务端返回非 2xx 状态码。
            httpx.RequestError: 网络请求失败或超时。
        """
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/chat/completions"

        with httpx.Client(timeout=DEFAULT_TIMEOUT) as client:
            response = client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        content = data["choices"][0]["message"]["content"]
        usage_data = data.get("usage") or {}
        usage = Usage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )
        logger.info(
            "LLM 调用完成: model=%s, prompt=%d, completion=%d, finish=%s",
            self.model,
            usage.prompt_tokens,
            usage.completion_tokens,
            data["choices"][0].get("finish_reason"),
        )

        return LLMResponse(
            content=content,
            usage=usage,
            model=self.model,
            finish_reason=data["choices"][0].get("finish_reason"),
        )


def load_dotenv(dotenv_path: Optional[Path] = None) -> None:
    """加载 .env 文件中的配置到环境变量。

    仅对尚未设置的变量生效（已存在的进程环境变量优先），
    因此重复调用是幂等的。文件不存在时静默返回。

    Args:
        dotenv_path: .env 文件路径，默认为项目根目录下的 .env。
    """
    path = dotenv_path or (Path(__file__).resolve().parent.parent / ".env")
    try:
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                if key:
                    os.environ.setdefault(key, value.strip().strip("\"'"))
    except OSError:
        return


def create_provider(
    name: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> LLMProvider:
    """根据环境变量创建默认提供商实例。

    base_url / model 优先级：显式参数 > 提供商专属覆盖环境变量
    （如 ``QWEN_BASE_URL``、``GLM_MODEL``，用于百炼专属网关、商汤 SenseNova
    等第三方 OpenAI 兼容服务）> 默认配置。

    Args:
        name: 提供商名称（deepseek/qwen/openai/glm），默认读取
            环境变量 ``LLM_PROVIDER``，再缺省为 deepseek。
        model: 覆盖默认模型。
        base_url: 覆盖默认接口地址。

    Returns:
        配置好的 LLMProvider 实例。

    Raises:
        ValueError: 提供商名称不支持。
        RuntimeError: 未设置对应的 API Key 环境变量。
    """
    load_dotenv()
    provider_name = (name or os.getenv("LLM_PROVIDER", DEFAULT_PROVIDER)).lower()
    if provider_name not in PROVIDER_CONFIGS:
        raise ValueError(
            f"不支持的提供商 '{provider_name}'，"
            f"可选: {', '.join(PROVIDER_CONFIGS)}"
        )

    config = PROVIDER_CONFIGS[provider_name]
    api_key = os.getenv(config["api_key_env"])
    if not api_key:
        raise RuntimeError(
            f"未设置环境变量 {config['api_key_env']}，"
            f"无法创建 {provider_name} 提供商"
        )

    base_url = (
        base_url
        or os.getenv(config.get("base_url_env") or "")
        or config["base_url"]
    )
    model = (
        model
        or os.getenv(config.get("model_env") or "")
        or config["model"]
    )

    return LLMProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        provider_name=provider_name,
    )


def chat_with_retry(
    provider: LLMProvider,
    messages: list[dict[str, str]],
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    max_retries: int = MAX_RETRIES,
) -> LLMResponse:
    """带重试与指数退避的对话调用。

    对网络错误（含超时）和可重试的服务端状态码（429/5xx）进行重试，
    最多重试 ``max_retries - 1`` 次，每次等待 ``2^attempt`` 秒。

    Args:
        provider: LLM 提供商实例。
        messages: OpenAI 格式的对话消息列表。
        temperature: 采样温度。
        max_tokens: 输出最大 token 数。
        max_retries: 总尝试次数，默认 3。

    Returns:
        统一的 LLMResponse 对象。

    Raises:
        httpx.HTTPStatusError: 最后一次失败为不可重试的状态码，
            或重试次数已用尽。
        httpx.RequestError: 重试次数已用尽仍网络失败。
    """
    attempt = 0
    last_error = ""
    while True:
        try:
            return provider.chat(messages, temperature=temperature, max_tokens=max_tokens)
        except httpx.HTTPStatusError as exc:
            last_error = f"HTTP {exc.response.status_code}: {exc}"
            retryable = exc.response.status_code in RETRYABLE_STATUS_CODES
            last_attempt = attempt >= max_retries - 1
            if not retryable or last_attempt:
                raise
            delay = BASE_RETRY_DELAY * (2**attempt)
            if exc.response.status_code == 429:
                delay *= RATE_LIMIT_BACKOFF_MULTIPLIER
        except httpx.RequestError as exc:
            last_error = str(exc)
            if attempt >= max_retries - 1:
                raise
            delay = BASE_RETRY_DELAY * (2**attempt)

        attempt += 1
        logger.warning(
            "LLM 调用失败（第 %d 次），%.1fs 后重试: %s",
            attempt, delay, last_error,
        )
        time.sleep(delay)


def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """按 USD 计算一次调用的费用。

    Args:
        model: 模型名称，须在 MODEL_PRICES_USD 中登记。
        prompt_tokens: 输入 token 数。
        completion_tokens: 输出 token 数。

    Returns:
        费用（美元）。

    Raises:
        ValueError: 模型不在价格表中。
    """
    price = MODEL_PRICES_USD.get(model)
    if price is None:
        raise ValueError(
            f"模型 '{model}' 不在价格表中，可调用 "
            f"MODEL_PRICES_USD[{model}] = (输入价, 输出价) 补充"
        )
    input_price, output_price = price
    return prompt_tokens / 1_000_000 * input_price + completion_tokens / 1_000_000 * output_price


def _parse_json_text(text: str) -> tuple[Any, Optional[str]]:
    """解析模型输出中的 JSON，容忍代码块标记与前后噪声，返回 (对象, 错误信息)。"""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        return json.loads(text), None
    except json.JSONDecodeError:
        pass
    start, end = text.find("{"), text.rfind("}")
    if -1 < start < end:
        try:
            return json.loads(text[start : end + 1]), None
        except json.JSONDecodeError as exc:
            return None, str(exc)
    return None, "未找到 JSON 对象"


def chat_json(
    prompt: str,
    system: Optional[str] = None,
    temperature: float = 0.7,
    provider: Optional[LLMProvider] = None,
    max_retries: int = MAX_RETRIES,
) -> tuple[Any, Usage]:
    """调用 LLM 并解析 JSON，返回 (解析后的对象, 本次用量)。

    Args:
        prompt: 用户输入。
        system: 可选的系统提示词。
        temperature: 采样温度。
        provider: 提供商实例，默认按环境变量创建。
        max_retries: 总尝试次数。

    Returns:
        (解析后的 JSON 对象, Usage)。

    Raises:
        ValueError: 模型未输出合法 JSON 对象。
        httpx.HTTPStatusError: 服务端返回不可重试的状态码，或重试次数已用尽。
        httpx.RequestError: 重试次数已用尽仍网络失败。
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    target = provider or create_provider()
    response = chat_with_retry(
        target, messages, temperature=temperature, max_retries=max_retries
    )
    parsed, err = _parse_json_text(response.content)
    if isinstance(parsed, (dict, list)):
        return parsed, response.usage
    raise ValueError(f"LLM 未输出合法 JSON: {err or '非对象'}")


def accumulate_usage(cost_tracker: dict, usage: Usage, provider: LLMProvider) -> dict:
    """把一次调用的 token 用量并入成本汇总 dict，返回并入后的新 dict。

    以 ``{provider_name}/{model}`` 为键累计（provider_name 为空时退化为模型名），
    值为 ``{"prompt_tokens", "completion_tokens", "total_tokens", "calls", "cost_usd"}``。
    模型不在价格表中时 cost_usd 按 0 计（不抛错）。

    Args:
        cost_tracker: state 中的成本汇总 dict（或 {}）。
        usage: 本次调用的用量。
        provider: 提供商实例，用于生成键与价格查找。

    Returns:
        并入本次用量后的新 dict。
    """
    name = provider.provider_name or ""
    model = provider.model
    key = f"{name}/{model}" if name else model
    merged = {k: dict(v) for k, v in (cost_tracker or {}).items()}
    entry = merged.setdefault(
        key,
        {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
            "cost_usd": 0.0,
        },
    )
    entry["prompt_tokens"] += usage.prompt_tokens
    entry["completion_tokens"] += usage.completion_tokens
    entry["total_tokens"] += usage.total_tokens
    entry["calls"] += 1
    try:
        entry["cost_usd"] += calculate_cost(
            model, usage.prompt_tokens, usage.completion_tokens
        )
    except ValueError:
        logger.warning("模型 %s 未登记价格，本次成本按 0 计", model)
    return merged


def main() -> None:
    """模块自测：验证成本计算，并在配置了 API Key 时做真实调用。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    usage = Usage(prompt_tokens=1000, completion_tokens=200, total_tokens=1200)
    for model in MODEL_PRICES_USD:
        logger.info("模型 %-18s 1000 in / 200 out 成本: $%.6f", model,
                    calculate_cost(model, usage.prompt_tokens, usage.completion_tokens))

    try:
        provider = create_provider()
    except RuntimeError as exc:
        logger.info("未配置 API Key，跳过真实调用: %s", exc)
        return

    logger.info("提供商: %s, 模型: %s", provider.base_url, provider.model)
    messages = [{"role": "user", "content": "请用一句话介绍你自己。"}]
    response = chat_with_retry(provider, messages)
    cost = calculate_cost(
        response.model, response.usage.prompt_tokens, response.usage.completion_tokens
    )
    logger.info(
        "本次调用: %d in / %d out tokens, 成本 $%.6f",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        cost,
    )
    logger.info("回复: %s", response.content)


if __name__ == "__main__":
    main()