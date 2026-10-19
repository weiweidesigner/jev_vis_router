"""Small adapter for the locally hosted Laya typed-decision service."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

import requests


@dataclass(frozen=True)
class Choice:
    instructions: str
    criteria: Mapping[str, str]


@dataclass(frozen=True)
class LayaAnswer:
    choice: str
    confidence: float
    probabilities: Mapping[str, float]


@dataclass(frozen=True)
class LayaResponse:
    model: str
    answers: Mapping[str, LayaAnswer]
    usage: Mapping[str, Any]


def _confidence(probabilities: Mapping[str, Any]) -> float:
    values = [float(value) for value in probabilities.values()]
    if not values or any(not math.isfinite(value) or value < 0 or value > 1 for value in values):
        raise ValueError("Laya 概率分布无效")
    if abs(sum(values) - 1) > .002:
        raise ValueError("Laya 概率分布之和无效")
    if len(values) == 1:
        return 1.0
    maximum = max(values)
    return max(0.0, min(1.0, (maximum - 1 / len(values)) / (1 - 1 / len(values))))


class LocalLayaClient:
    """Expose the local HTTP service through the former system_one interface."""

    def __init__(self, *, endpoint: str, model: str, timeout: float, max_questions_per_request: int = 2) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.max_questions_per_request = max(1, int(max_questions_per_request))

    def __enter__(self) -> "LocalLayaClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def system_one(self, *, state: Any, questions: Mapping[str, Choice]) -> LayaResponse:
        items = list(questions.items())
        answers: dict[str, LayaAnswer] = {}
        aggregate_usage: dict[str, Any] = {}
        response_model = self.model
        for start in range(0, len(items), self.max_questions_per_request):
            batch = dict(items[start:start + self.max_questions_per_request])
            payload_questions = {
                key: {
                    "type": "choice",
                    "instructions": question.instructions,
                    "criteria": dict(question.criteria),
                }
                for key, question in batch.items()
            }
            response = requests.post(
                self.endpoint,
                json={"state": state, "questions": payload_questions},
                timeout=(5, self.timeout),
                allow_redirects=False,
            )
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
                raise ValueError("Laya 未返回有效决策")
            response_model = str(body.get("model") or response_model)
            usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
            if usage.get("truncated") or usage.get("options") or usage.get("truncated_questions"):
                raise ValueError("Laya 输入或选项发生截断")
            for name, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    aggregate_usage[name] = aggregate_usage.get(name, 0) + value
            for key, question in batch.items():
                raw = body["answers"].get(key)
                if not isinstance(raw, dict) or not isinstance(raw.get("probabilities"), dict):
                    raise ValueError(f"Laya 缺少决策 {key}")
                probabilities = {str(name): float(value) for name, value in raw["probabilities"].items()}
                if set(probabilities) != set(question.criteria):
                    raise ValueError(f"Laya 决策 {key} 的选项集合不匹配")
                choice = str(raw.get("choice") or "")
                if choice not in probabilities or choice != max(probabilities, key=probabilities.get):
                    raise ValueError(f"Laya 决策 {key} 与概率分布不一致")
                answers[key] = LayaAnswer(
                    choice=choice,
                    confidence=_confidence(probabilities),
                    probabilities=probabilities,
                )
        return LayaResponse(
            model=response_model,
            answers=answers,
            usage=aggregate_usage,
        )
