"""统一的 LLM 调用客户端。

通过环境变量选择模型提供商：

- ``LLM_PROVIDER``: deepseek（默认）| qwen | openai
- ``DEEPSEEK_API_KEY``: DeepSeek 的 API Key
- ``DASHSCOPE_API_KEY``: 阿里云百炼（Qwen）的 API Key
- ``OPENAI_API_KEY``: OpenAI 的 API Key

本模块使用 httpx 直接调用 OpenAI 兼容的 /chat/completions 接口，
不依赖 openai SDK。所有提供商（DeepSeek / Qwen / OpenAI）均返回
统一的 :class:`LLMResponse` 结构。

配置优先级：进程环境变量 ``>`` 项目根目录下的 ``.env`` 文件。
后者以内置的 :func:`load_dotenv` 加载，无需安装 python-dotenv。

用法示例::

    from pipeline.model_client import quick_chat

    reply = quick_chat("用一句话介绍你自己。")
"""

import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "deepseek"
DEFAULT_TIMEOUT = 60.0
MAX_RETRIES = 3
BASE_RETRY_DELAY = 1.0
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

# 各提供商的配置：base_url、默认模型、API Key 环境变量名。
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
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
}

# 各模型价格（USD / 1M tokens），取值 (输入价, 输出价)。
# 数据为 2026-07 官方公布价格，使用前请核对官方最新价目。
MODEL_PRICES_USD = {
    "deepseek-v4-flash": (0.14, 0.28),
    "deepseek-v4-pro": (0.435, 0.87),
    "qwen-plus": (0.40, 1.20),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}

# 国产模型价格表（RMB / 1M tokens），按提供商计，取值 (输入价, 输出价)。
# 供 CostTracker 估算成本，使用前请核对各厂商最新价目。
PROVIDER_PRICES_CNY = {
    "deepseek": (1.0, 2.0),
    "qwen": (4.0, 12.0),
    "openai": (150.0, 600.0),  # gpt-4o-mini
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


class CostTracker:
    """追踪 LLM 调用的 token 消耗与估算成本（RMB）。

    每次 API 调用成功后由 :meth:`OpenAICompatibleProvider.chat` 自动记录，
    Pipeline 结束时可通过 :meth:`report` 输出成本报告。

    Attributes:
        _records: 各提供商累计的 token 用量，key 为提供商名称
            （deepseek / qwen / openai）。
        _calls: 各提供商的调用次数。
    """

    def __init__(self) -> None:
        self._records: dict[str, Usage] = {}
        self._calls: dict[str, int] = {}

    def record(self, usage: Usage, provider: str) -> None:
        """记录一次 API 调用的 token 用量。

        Args:
            usage: 本次调用的 token 用量统计。
            provider: 提供商名称（deepseek / qwen / openai）。
        """
        record = self._records.setdefault(
            provider, Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0)
        )
        record.prompt_tokens += usage.prompt_tokens
        record.completion_tokens += usage.completion_tokens
        record.total_tokens += usage.total_tokens
        self._calls[provider] = self._calls.get(provider, 0) + 1

    def estimated_cost(self, provider: str) -> float:
        """估算某提供商累计调用的成本。

        按 :data:`PROVIDER_PRICES_CNY` 的价格（RMB / 1M tokens）计算，
        未记录过调用的提供商返回 0。

        Args:
            provider: 提供商名称。

        Returns:
            估算成本（元）。

        Raises:
            ValueError: 提供商不在价格表中。
        """
        price = PROVIDER_PRICES_CNY.get(provider)
        if price is None:
            raise ValueError(
                f"提供商 '{provider}' 不在成本价格表中，"
                f"可选: {', '.join(PROVIDER_PRICES_CNY)}"
            )
        record = self._records.get(provider)
        if record is None:
            return 0.0
        input_price, output_price = price
        return (
            record.prompt_tokens / 1_000_000 * input_price
            + record.completion_tokens / 1_000_000 * output_price
        )

    def report(self, provider: Optional[str] = None) -> None:
        """打印成本报告。

        Args:
            provider: 仅报告该提供商；缺省报告所有记录过的提供商。
        """
        logger.info("===== LLM 成本报告 =====")
        providers = [provider] if provider else sorted(self._records)
        if not providers:
            logger.info("（无任何已记录的调用）")
            return
        for name in providers:
            record = self._records.get(name)
            if record is None:
                continue
            logger.info(
                "[%s] 调用 %d 次: 输入 %d tokens, 输出 %d tokens, 估算成本 %.4f 元",
                name,
                self._calls.get(name, 0),
                record.prompt_tokens,
                record.completion_tokens,
                self.estimated_cost(name),
            )
        logger.info("========================")


tracker = CostTracker()


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


class LLMProvider(ABC):
    """LLM 提供商抽象基类。

    子类需实现 :meth:`chat`，向各自后端发起对话请求并返回
    统一的 :class:`LLMResponse`。
    """

    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        """初始化提供商实例。

        Args:
            api_key: 提供商 API Key。
            base_url: OpenAI 兼容接口的基础地址。
            model: 使用的模型名称。
        """
        self._api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    @abstractmethod
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


class OpenAICompatibleProvider(LLMProvider):
    """基于 OpenAI 兼容 /chat/completions 接口的实现。

    适用于 DeepSeek、Qwen（百炼）、OpenAI 等提供兼容接口的服务。
    每次调用成功后自动将 token 用量记录到全局 :data:`tracker`。
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
            provider_name: 提供商名称（deepseek / qwen / openai），
                用于成本追踪；为 None 时不记录。
        """
        super().__init__(api_key, base_url, model)
        self.provider_name = provider_name

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        """发起一次对话请求，见 :meth:`LLMProvider.chat`。"""
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
        if self.provider_name:
            tracker.record(usage, self.provider_name)
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

    Args:
        name: 提供商名称（deepseek/qwen/openai），默认读取
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

    return OpenAICompatibleProvider(
        api_key=api_key,
        base_url=base_url or config["base_url"],
        model=model or config["model"],
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
    while True:
        try:
            return provider.chat(messages, temperature=temperature, max_tokens=max_tokens)
        except httpx.HTTPStatusError as exc:
            retryable = exc.response.status_code in RETRYABLE_STATUS_CODES
            last_attempt = attempt >= max_retries - 1
            if not retryable or last_attempt:
                raise
            delay = BASE_RETRY_DELAY * (2**attempt)
        except httpx.RequestError as exc:
            if attempt >= max_retries - 1:
                raise
            delay = BASE_RETRY_DELAY * (2**attempt)

        attempt += 1
        logger.warning(
            "LLM 调用失败（第 %d 次），%.1fs 后重试: %s",
            attempt, delay, exc,
        )
        time.sleep(delay)


def estimate_tokens(text: str) -> int:
    """估算文本的 token 数量。

    CJK 字符（中文、日文、韩文）按 1 token 计，其余字符按 0.25 token 计，
    适用于大部分 LLM 的通用 tokenizer。

    Args:
        text: 待估算的文本。

    Returns:
        估算的 token 数。
    """
    if not text:
        return 0
    total = 0.0
    for ch in text:
        total += 1.0 if ord(ch) >= 0x2E80 else 0.25
    return int(total)


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


def response_cost(model: str, response: LLMResponse) -> float:
    """根据响应中的用量统计计算费用（USD）。

    Args:
        model: 模型名称。
        response: LLM 响应。

    Returns:
        费用（美元）。
    """
    return calculate_cost(model, response.usage.prompt_tokens, response.usage.completion_tokens)


def quick_chat(
    prompt: str,
    system: Optional[str] = None,
    provider: Optional[LLMProvider] = None,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
) -> str:
    """一句话调用 LLM，返回文本内容。

    Args:
        prompt: 用户输入。
        system: 可选的系统提示词。
        provider: 提供商实例，默认按环境变量创建。
        temperature: 采样温度。
        max_tokens: 输出最大 token 数。

    Returns:
        模型返回的文本内容。
    """
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    target = provider or create_provider()
    response = chat_with_retry(
        target, messages, temperature=temperature, max_tokens=max_tokens
    )
    return response.content


def main() -> None:
    """模块自测：验证工具函数，并在配置了 API Key 时做真实调用。"""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    sample = "中文文本估算示例，用于验证 token 估算。Hello world, this is an English sentence."
    logger.info("估算 token 数: %d (原文 %d 字符)", estimate_tokens(sample), len(sample))

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
    logger.info(
        "本次调用: %d in / %d out tokens, 成本 $%.6f",
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        response_cost(provider.model, response),
    )
    logger.info("回复: %s", response.content)


if __name__ == "__main__":
    main()
