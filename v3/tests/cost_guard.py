"""多 Agent LLM 调用的人民币预算守卫。"""

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class BudgetExceededError(RuntimeError):
    """累计 LLM 成本超过预算时抛出。"""


@dataclass
class CostRecord:
    """单次 LLM 调用的成本记录。"""

    timestamp: str
    node_name: str
    prompt_tokens: int
    completion_tokens: int
    cost_yuan: float
    model: str


class CostGuard:
    """记录多 Agent 调用成本，并在预算临界或超限时给出保护。"""

    def __init__(
        self,
        budget_yuan: float = 1.0,
        alert_threshold: float = 0.8,
        input_price_per_million: float = 1.0,
        output_price_per_million: float = 2.0,
    ) -> None:
        if budget_yuan <= 0:
            raise ValueError("budget_yuan 必须大于 0")
        if not 0 <= alert_threshold <= 1:
            raise ValueError("alert_threshold 必须在 0 到 1 之间")
        if input_price_per_million < 0 or output_price_per_million < 0:
            raise ValueError("token 单价不能为负数")

        self.budget_yuan = budget_yuan
        self.alert_threshold = alert_threshold
        self.input_price_per_million = input_price_per_million
        self.output_price_per_million = output_price_per_million
        self.records: list[CostRecord] = []

    @property
    def total_prompt_tokens(self) -> int:
        return sum(record.prompt_tokens for record in self.records)

    @property
    def total_completion_tokens(self) -> int:
        return sum(record.completion_tokens for record in self.records)

    @property
    def total_cost_yuan(self) -> float:
        return sum(record.cost_yuan for record in self.records)

    def record(
        self, node_name: str, usage: dict[str, int], model: str = ""
    ) -> CostRecord:
        """记录一次 LLM 调用，并按构造函数中的单价计算人民币成本。"""
        try:
            prompt_tokens = usage["prompt_tokens"]
            completion_tokens = usage["completion_tokens"]
        except KeyError as exc:
            raise ValueError(f"usage 缺少字段: {exc.args[0]}") from exc

        if (
            not isinstance(prompt_tokens, int)
            or not isinstance(completion_tokens, int)
            or prompt_tokens < 0
            or completion_tokens < 0
        ):
            raise ValueError("usage 的 token 数必须是非负整数")

        cost_yuan = (
            prompt_tokens * self.input_price_per_million
            + completion_tokens * self.output_price_per_million
        ) / 1_000_000
        cost_record = CostRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            node_name=node_name,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_yuan=cost_yuan,
            model=model,
        )
        self.records.append(cost_record)
        return cost_record

    def check(self) -> dict[str, Any]:
        """检查当前累计成本；超限时抛出 :class:`BudgetExceededError`。"""
        total_cost = self.total_cost_yuan
        usage_ratio = total_cost / self.budget_yuan
        result = {
            "status": "ok",
            "total_cost": total_cost,
            "budget": self.budget_yuan,
            "usage_ratio": usage_ratio,
            "message": "预算充足。",
        }
        if usage_ratio > 1:
            result.update(
                status="exceeded",
                message=(
                    f"预算超限：已使用 {total_cost:.6f} 元，"
                    f"预算为 {self.budget_yuan:.6f} 元。"
                ),
            )
            raise BudgetExceededError(result["message"])
        if usage_ratio >= self.alert_threshold:
            result.update(
                status="warning",
                message=(
                    f"接近预算：已使用 {usage_ratio:.1%}，"
                    f"预警阈值为 {self.alert_threshold:.1%}。"
                ),
            )
        return result

    def get_report(self) -> dict[str, Any]:
        """生成总体与按节点分组的成本报告。"""
        nodes: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "calls": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_cost_yuan": 0.0,
                "models": [],
            }
        )
        for record in self.records:
            node = nodes[record.node_name]
            node["calls"] += 1
            node["prompt_tokens"] += record.prompt_tokens
            node["completion_tokens"] += record.completion_tokens
            node["total_cost_yuan"] += record.cost_yuan
            if record.model and record.model not in node["models"]:
                node["models"].append(record.model)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "budget_yuan": self.budget_yuan,
            "alert_threshold": self.alert_threshold,
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cost_yuan": self.total_cost_yuan,
            "records": [asdict(record) for record in self.records],
            "nodes": dict(nodes),
        }

    def save_report(self, path: str | Path | None = None) -> Path:
        """将成本报告保存为 JSON；默认保存为当前目录的 ``cost_report.json``。"""
        report_path = Path(path) if path is not None else Path("cost_report.json")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(self.get_report(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return report_path


def _test_cost_tracking() -> None:
    guard = CostGuard()
    guard.record("analyze", {"prompt_tokens": 500_000, "completion_tokens": 250_000})
    assert guard.total_prompt_tokens == 500_000
    assert guard.total_cost_yuan == 1.0


def _test_budget_exceeded() -> None:
    guard = CostGuard(budget_yuan=0.1)
    guard.record("review", {"prompt_tokens": 100_000, "completion_tokens": 100_000})
    try:
        guard.check()
    except BudgetExceededError:
        return
    raise AssertionError("check() 应在预算超限时抛出 BudgetExceededError")


def _test_alert_threshold() -> None:
    guard = CostGuard(budget_yuan=1.0, alert_threshold=0.8)
    guard.record("analyze", {"prompt_tokens": 800_000, "completion_tokens": 0})
    assert guard.check()["status"] == "warning"


if __name__ == "__main__":
    _test_cost_tracking()
    _test_budget_exceeded()
    _test_alert_threshold()
    print("CostGuard self-tests passed")
