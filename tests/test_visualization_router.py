from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.jev_visualization_router import (
    JevVisualizationDecision,
    JevVisualizationRouter,
    JevVisualizationRouterError,
)


class FakeClient:
    primary_choice = "visual-2"
    primary_confidence = 0.91
    supporting_choice = "visual-3"
    supporting_confidence = 0.72
    semantic_lens = "composition-and-drivers"
    semantic_lens_confidence = 0.84
    visual_encoding = "composition-and-contribution"
    visual_encoding_confidence = 0.87
    evidence_strategy = "us-business-plus-internal-video"
    evidence_strategy_confidence = 0.81
    mark_strategy = "contribution-focus"
    mark_strategy_confidence = 0.79
    captured_state = None

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *args: object) -> None:
        pass

    def system_one(self, *, state: object, questions: object) -> object:
        type(self).captured_state = state
        return SimpleNamespace(
            model="jev-1.13.0",
            answers={
                "primary_visual": SimpleNamespace(
                    choice=self.primary_choice,
                    confidence=self.primary_confidence,
                ),
                "supporting_visual": SimpleNamespace(
                    choice=self.supporting_choice,
                    confidence=self.supporting_confidence,
                ),
                "semantic_lens": SimpleNamespace(
                    choice=self.semantic_lens,
                    confidence=self.semantic_lens_confidence,
                ),
                "visual_encoding": SimpleNamespace(
                    choice=self.visual_encoding,
                    confidence=self.visual_encoding_confidence,
                ),
                "evidence_strategy": SimpleNamespace(
                    choice=self.evidence_strategy,
                    confidence=self.evidence_strategy_confidence,
                ),
                "mark_strategy": SimpleNamespace(
                    choice=self.mark_strategy,
                    confidence=self.mark_strategy_confidence,
                ),
            },
        )


VISUAL_CANDIDATES = [
    {"script": "line_chart.py", "family": "generic-chart", "label": "Line", "description": "Single trend"},
    {"script": "income_statement.py", "family": "business-chart", "label": "Income", "description": "Revenue and profit"},
    {"script": "revenue_sources.py", "family": "business-chart", "label": "Revenue sources", "description": "Business mix"},
]


def test_jev_visualization_router_selects_primary_and_distinct_support() -> None:
    router = JevVisualizationRouter(api_key="test-key", client_factory=FakeClient)
    decision = router.route(question="分析收入、利润和业务收入构成", candidates=VISUAL_CANDIDATES)

    assert decision.selected_scripts == ("income_statement.py", "revenue_sources.py")
    assert decision.primary_confidence == 0.91
    assert decision.supporting_confidence == 0.72
    assert decision.provider_model == "jev-1.13.0"
    assert decision.candidate_count == 3
    assert decision.semantic_lens == "composition-and-drivers"
    assert decision.visual_encoding == "composition-and-contribution"
    assert decision.evidence_strategy == "us-business-plus-internal-video"
    assert decision.mark_strategy == "contribution-focus"
    assert decision.primary_purpose == "Revenue and profit"
    assert decision.supporting_purpose == "Business mix"
    assert len(FakeClient.captured_state["available_visualizations"]) == 3


def test_jev_visualization_router_omits_low_confidence_support() -> None:
    class LowSupportClient(FakeClient):
        supporting_confidence = 0.2

    router = JevVisualizationRouter(api_key="test-key", client_factory=LowSupportClient)
    decision = router.route(question="只看利润趋势", candidates=VISUAL_CANDIDATES)

    assert decision.selected_scripts == ("income_statement.py",)
    assert decision.supporting_script is None


def test_jev_visualization_router_does_not_force_a_chart() -> None:
    class NoVisualClient(FakeClient):
        primary_choice = "no-visual"
        primary_confidence = 0.89

    router = JevVisualizationRouter(api_key="test-key", client_factory=NoVisualClient)
    decision = router.route(question="账户操作是否成功", candidates=VISUAL_CANDIDATES)

    assert decision.selected_scripts == ()
    assert decision.primary_script is None
    assert decision.supporting_script is None


def test_generic_visual_normalizes_business_only_evidence_strategy() -> None:
    class GenericClient(FakeClient):
        primary_choice = "visual-1"
        supporting_choice = "no-visual"
        evidence_strategy = "us-business-native"

    router = JevVisualizationRouter(api_key="test-key", client_factory=GenericClient)
    decision = router.route(question="比较三只 ETF 的累计收益", candidates=VISUAL_CANDIDATES)

    assert decision.primary_script == "line_chart.py"
    assert decision.evidence_strategy == "structured-data-first"


def test_jev_visualization_router_falls_back_on_low_primary_confidence() -> None:
    class LowPrimaryClient(FakeClient):
        primary_confidence = 0.2

    router = JevVisualizationRouter(api_key="test-key", client_factory=LowPrimaryClient)
    with pytest.raises(JevVisualizationRouterError, match="主可视化置信度"):
        router.route(question="画图", candidates=VISUAL_CANDIDATES)



@pytest.mark.parametrize("columns", ["1", "2", "3", "4"])
def test_router_returns_mobile_intraday_columns(columns):
    class GridClient(FakeClient):
        primary_choice = "visual-1"
        supporting_choice = "no-visual"
        def system_one(self, *, state, questions):
            assert "mobile_columns" in questions
            result = super().system_one(state=state, questions=questions)
            result.answers["mobile_columns"] = SimpleNamespace(choice=columns, confidence=0.9)
            return result
    router = JevVisualizationRouter(api_key="test-key", client_factory=GridClient)
    decision = router.route(question="比较多只股票的分时", candidates=[{"script":"multi_intraday.py", "family":"business-chart", "label":"多分时", "description":"Intraday comparison"}])
    assert decision.mobile_columns == int(columns)
