from __future__ import annotations

import pytest

from app.laya_client import Choice, LocalLayaClient


class Response:
    def __init__(self, questions):
        self.questions = questions

    def raise_for_status(self):
        return None

    def json(self):
        return {
            "model": "convaiinnovations/laya-multilingual",
            "answers": {key: {
                "choice": next(iter(question["criteria"])),
                "probabilities": {
                    option: (.8 if index == 0 else .2 / (len(question["criteria"]) - 1))
                    for index, option in enumerate(question["criteria"])
                },
            } for key, question in self.questions.items()},
            "usage": {"truncated": False},
        }


def test_local_laya_client_serializes_choices_and_maps_confidence(monkeypatch):
    captured = []

    def post(url, **kwargs):
        captured.append({"url": url, **kwargs})
        return Response(kwargs["json"]["questions"])

    monkeypatch.setattr("app.laya_client.requests.post", post)
    with LocalLayaClient(
        endpoint="http://127.0.0.1:8791/predict",
        model="convaiinnovations/laya-multilingual",
        timeout=90,
    ) as client:
        response = client.system_one(
            state={"request": "trend"},
            questions={
                "chart": Choice(instructions="choose", criteria={"line": "trend", "bar": "rank"}),
                "support": Choice(instructions="choose", criteria={"yes": "yes", "no": "no"}),
                "mark": Choice(instructions="choose", criteria={"keep": "keep", "omit": "omit"}),
            },
        )

    assert len(captured) == 2
    assert all(len(call["json"]["questions"]) <= 2 for call in captured)
    assert captured[0]["url"] == "http://127.0.0.1:8791/predict"
    assert captured[0]["allow_redirects"] is False
    assert captured[0]["json"]["questions"]["chart"]["type"] == "choice"
    assert response.model == "convaiinnovations/laya-multilingual"
    assert response.answers["chart"].choice == "line"
    assert response.answers["chart"].confidence == pytest.approx(.6)
    assert set(response.answers) == {"chart", "support", "mark"}
