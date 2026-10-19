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
    # Visualization selection is non-transactional. Preserve the selected
    # option probability rather than applying the conservative trading gate's
    # normalized-margin transform.
    return max(values)


class LocalLayaClient:
    """Expose the local HTTP service through the former system_one interface."""

    def __init__(self, *, endpoint: str, model: str, timeout: float, max_options_per_question: int = 3) -> None:
        self.endpoint = endpoint
        self.model = model
        self.timeout = timeout
        self.max_options_per_question = max(2, min(3, int(max_options_per_question)))

    def __enter__(self) -> "LocalLayaClient":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    @staticmethod
    def _compact_state(state: Any) -> Any:
        if not isinstance(state, dict):
            return state
        # Candidate details are already present in each tournament question.
        # Removing the duplicated catalogs keeps the local sidecar below its
        # strict state-token ceiling without discarding the user request.
        return {key: value for key, value in state.items() if key not in {"available_visualizations", "candidates"}}

    def _ask(self, *, state: Any, key: str, instructions: str, criteria: Mapping[str, str]) -> tuple[LayaAnswer, str, Mapping[str, Any]]:
        bounded = {str(name): str(description)[:240] for name, description in criteria.items()}
        payload = {"type": "choice", "instructions": str(instructions)[:300], "criteria": bounded}
        response = requests.post(
            self.endpoint,
            json={"state": self._compact_state(state), "questions": {key: payload}},
            timeout=(5, self.timeout),
            allow_redirects=False,
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or not isinstance(body.get("answers"), dict):
            raise ValueError("Laya 未返回有效决策")
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
        if usage.get("truncated") or usage.get("options") or usage.get("truncated_questions"):
            raise ValueError("Laya 输入或选项发生截断")
        raw = body["answers"].get(key)
        if not isinstance(raw, dict) or not isinstance(raw.get("probabilities"), dict):
            raise ValueError(f"Laya 缺少决策 {key}")
        probabilities = {str(name): float(value) for name, value in raw["probabilities"].items()}
        if set(probabilities) != set(bounded):
            raise ValueError(f"Laya 决策 {key} 的选项集合不匹配")
        choice = str(raw.get("choice") or "")
        if choice not in probabilities or choice != max(probabilities, key=probabilities.get):
            raise ValueError(f"Laya 决策 {key} 与概率分布不一致")
        return LayaAnswer(choice=choice, confidence=_confidence(probabilities), probabilities=probabilities), str(body.get("model") or self.model), usage

    def system_one(self, *, state: Any, questions: Mapping[str, Choice]) -> LayaResponse:
        answers: dict[str, LayaAnswer] = {}
        aggregate_usage: dict[str, Any] = {}
        response_model = self.model
        for key, question in questions.items():
            remaining = dict(question.criteria)
            final_answer: LayaAnswer | None = None
            round_number = 0
            while len(remaining) > self.max_options_per_question:
                winners: dict[str, str] = {}
                entries = list(remaining.items())
                for start in range(0, len(entries), self.max_options_per_question):
                    group = dict(entries[start:start + self.max_options_per_question])
                    if len(group) == 1:
                        winners.update(group)
                        continue
                    answer, response_model, usage = self._ask(
                        state=state,
                        key=f"{key}_r{round_number}_{start // self.max_options_per_question}",
                        instructions=question.instructions,
                        criteria=group,
                    )
                    winners[answer.choice] = remaining[answer.choice]
                    for name, value in usage.items():
                        if isinstance(value, (int, float)) and not isinstance(value, bool):
                            aggregate_usage[name] = aggregate_usage.get(name, 0) + value
                remaining = winners
                round_number += 1
            final_answer, response_model, usage = self._ask(
                state=state,
                key=key,
                instructions=question.instructions,
                criteria=remaining,
            )
            for name, value in usage.items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    aggregate_usage[name] = aggregate_usage.get(name, 0) + value
            answers[key] = final_answer
        return LayaResponse(
            model=response_model,
            answers=answers,
            usage=aggregate_usage,
        )
