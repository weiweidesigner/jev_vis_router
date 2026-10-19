from __future__ import annotations

import pytest

from app.laya_client import Choice, LocalLayaClient


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "model": "convaiinnovations/laya-multilingual",
            "answers": {
                "chart": {
                    "choice": "line",
                    "probabilities": {"line": .8, "bar": .2},
                }
            },
            "usage": {"truncated": False},
        }


def test_local_laya_client_serializes_choices_and_maps_confidence(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return Response()

    monkeypatch.setattr("app.laya_client.requests.post", post)
    with LocalLayaClient(
        endpoint="http://127.0.0.1:8791/predict",
        model="convaiinnovations/laya-multilingual",
        timeout=90,
    ) as client:
        response = client.system_one(
            state={"request": "trend"},
            questions={"chart": Choice(instructions="choose", criteria={"line": "trend", "bar": "rank"})},
        )

    assert captured["url"] == "http://127.0.0.1:8791/predict"
    assert captured["allow_redirects"] is False
    assert captured["json"]["questions"]["chart"]["type"] == "choice"
    assert response.model == "convaiinnovations/laya-multilingual"
    assert response.answers["chart"].choice == "line"
    assert response.answers["chart"].confidence == pytest.approx(.6)
