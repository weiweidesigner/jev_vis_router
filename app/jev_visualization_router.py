from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable

from .laya_client import Choice, LocalLayaClient

from .jev_kline_annotations import JevKlineAnnotationPlan, plan_kline_annotations


class JevVisualizationRouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class JevVisualizationDecision:
    selected_scripts: tuple[str, ...]
    primary_script: str | None
    supporting_script: str | None
    primary_confidence: float
    supporting_confidence: float
    provider_model: str
    candidate_count: int
    semantic_lens: str = "evidence-led"
    semantic_lens_confidence: float = 0.0
    primary_purpose: str = ""
    supporting_purpose: str = ""
    visual_encoding: str = "latest-vs-history"
    visual_encoding_confidence: float = 0.0
    evidence_strategy: str = "structured-data-first"
    evidence_strategy_confidence: float = 0.0
    mark_strategy: str = "no-mark"
    mark_strategy_confidence: float = 0.0
    mobile_columns: int = 2


class JevVisualizationRouter:
    """Choose concrete Aime Chart renderers before generative CLI planning."""

    NO_VISUAL = "no-visual"
    SEMANTIC_LENSES = {
        "trend-and-inflection": "Emphasize change over time, acceleration/deceleration, and meaningful turning points.",
        "comparison-and-ranking": "Emphasize comparable differences, relative performance, leaders/laggards, and scale.",
        "composition-and-drivers": "Emphasize mix, contribution, concentration, and the drivers behind the total.",
        "distribution-and-risk": "Emphasize spread, outliers, concentration, downside, and uncertainty rather than averages alone.",
        "technical-confirmation": "Emphasize price/volume structure, trend confirmation, momentum, support/resistance, and conflicting signals.",
        "events-and-causality": "Emphasize chronology, dependencies, catalysts, and the difference between correlation and causal evidence.",
        "relationship-and-flow": "Emphasize connections, flows, source-to-destination structure, and network or process bottlenecks.",
        "forecast-and-scenarios": "Emphasize expectations, ranges, consensus dispersion, scenario differences, and forecast risk.",
        "evidence-led": "Use the strongest available evidence and explain the chart's decision-relevant takeaway without forcing a preset angle.",
    }
    VISUAL_ENCODINGS = {
        "latest-vs-history": "Anchor on the latest value, then compare it with the immediately prior period and the most relevant historical benchmark.",
        "trend-and-inflection": "Encode time on the horizontal axis and emphasize slope, acceleration, reversal, peaks, troughs, and turning points.",
        "growth-and-rate": "Emphasize period-over-period growth, cumulative change, normalized returns, or rate-of-change instead of raw levels alone.",
        "cross-sectional-comparison": "Use aligned scales to compare multiple securities, categories, periods, or benchmarks and surface leaders, laggards, and dispersion.",
        "composition-and-contribution": "Show part-to-whole mix, contribution to change, concentration, and which categories drive the aggregate.",
        "driver-outcome-dual-axis": "Relate two differently scaled but meaningfully connected measures, clearly separating driver and outcome without implying causality.",
        "event-overlay": "Align verified events or catalysts with a time series so the answer can compare before/after behavior and avoid unsupported causal claims.",
        "distribution-and-outliers": "Show spread, density, ranges, clusters, skew, and outliers rather than reducing the evidence to an average.",
        "flow-and-relationship": "Show source-to-destination flow, dependencies, hierarchy, process stages, or relationship strength.",
        "scenario-and-uncertainty": "Show forecast ranges, consensus dispersion, scenarios, confidence bands, and the conditions that would invalidate a view.",
        "technical-price-volume": "Combine price structure with volume/liquidity and technical confirmation; highlight support, resistance, momentum, and divergence.",
    }
    EVIDENCE_STRATEGIES = {
        "us-business-native": "For a US equity or US-listed security, use the matching native business chart as primary structured evidence and preserve its built-in data and display logic; do not add search unless the question needs current narrative evidence.",
        "us-business-plus-internal": "For a US equity or US-listed security, combine native business-chart evidence with AInvest in-app text/news search for catalysts, disclosures, market reaction, or recent context.",
        "us-business-plus-internal-video": "For a US equity or US-listed security, combine native business charts with AInvest in-app text search and video search; videos are supplemental viewpoint/catalyst evidence, not a substitute for structured fundamentals or price data.",
        "us-structured-plus-internal": "For a US-listed comparison or custom analysis rendered with a generic chart, use structured financial/market data as primary evidence and add AInvest in-app text/news for recent catalysts or narrative context.",
        "us-structured-plus-internal-video": "For a US-listed comparison or custom analysis rendered with a generic chart, use structured data as primary evidence and add AInvest in-app text plus video search as distinct context layers.",
        "us-internal-media": "The request is primarily about US-listed news, articles, videos, interviews, Shorts, or market narratives, so use AInvest in-app text/video evidence and add structured charts only when they materially test the narrative.",
        "structured-data-first": "Use the best structured financial/market source first and select a generic visualization only when its visual encoding better answers the question than a native business component.",
        "external-evidence": "Use external search because the asset is not US-listed or the required facts are outside AInvest's native business/news/video scope; connect verified facts to a schema-valid visualization when useful.",
        "user-data-only": "Use only user-provided or upstream structured data; do not fetch news or media unless the user explicitly requests it.",
    }
    MARK_STRATEGIES = {
        "missing-value-placeholder": "When the user explicitly requests a hatched missing/unreported bar, preserve null source values and use native grouped_bar.py barPlaceholders (chart-markup bar-placeholder). Resolve the exact target and distinct same-row referenceSeries from verified data; hatch height follows that reference, while tooltip/legend show a localized missing status. Do not fabricate actual values or route to custom HTML for this native capability.",
        "no-mark": "Keep the renderer defaults. Do not add decorative emphasis when no evidence-backed focal point is needed.",
        "turning-points": "Emphasize verified peaks, troughs, reversals, or slope changes with a small number of point or range marks.",
        "event-callouts": "Attach verified event time and title callouts to matching points on a time series; never infer an event date.",
        "threshold-reference": "Use a labeled reference line or threshold mark when a numeric benchmark, target, support, resistance, or boundary is explicit.",
        "leaders-laggards": "Recolor or emphasize the strongest and weakest comparable categories or series after ranking from structured data.",
        "contribution-focus": "Emphasize the categories or steps that explain the largest evidence-backed contribution to a total or change.",
        "risk-outliers": "Emphasize verified downside, outliers, concentration, or exceptional observations without hiding the surrounding distribution.",
        "signed-direction": "For a single-series bar encoding signed change, return, growth, delta, or profit/loss, mark positive, negative, and zero values semantically. Do not hardcode red or green: the renderer maps price-up and price-down colors from financialMarket (CN/HK red-up green-down; US green-up red-down). Do not use value colors on a multi-series grouped bar because color must remain available for series identity.",
        "distribution-polarity": "For a signed histogram, derive polarity from x-axis bins rather than bar height. A single-series histogram may use red/green/neutral bars. A multi-series grouped distribution must preserve series colors and express polarity with the zero boundary or subtle plot regions.",
    }

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        min_primary_confidence: float | None = None,
        min_supporting_confidence: float | None = None,
        client_factory: Callable[..., Any] = LocalLayaClient,
    ) -> None:
        # api_key remains accepted so existing callers fail neither at import nor construction.
        # Local Laya does not use it.
        self.api_key = str(api_key or "")
        self.endpoint = (
            endpoint if endpoint is not None else os.getenv("LAYA_DECISION_URL", "http://127.0.0.1:8791/predict")
        ).strip()
        self.model = (
            model if model is not None else os.getenv("LAYA_VISUAL_MODEL", "convaiinnovations/laya-multilingual")
        ).strip() or "convaiinnovations/laya-multilingual"
        self.timeout = timeout if timeout is not None else float(os.getenv("LAYA_VISUAL_TIMEOUT_SECONDS", "90"))
        self.min_primary_confidence = (
            min_primary_confidence
            if min_primary_confidence is not None
            else float(os.getenv("LAYA_VISUAL_PRIMARY_MIN_CONFIDENCE", "0.35"))
        )
        self.min_supporting_confidence = (
            min_supporting_confidence
            if min_supporting_confidence is not None
            else float(os.getenv("LAYA_VISUAL_SUPPORTING_MIN_CONFIDENCE", "0.55"))
        )
        self.client_factory = client_factory

    @property
    def configured(self) -> bool:
        return bool(self.endpoint)

    def plan_kline_annotations(self, **kwargs: Any) -> JevKlineAnnotationPlan:
        """Select native K-line marks from validated, already fetched evidence."""
        try:
            return plan_kline_annotations(self, **kwargs)
        except Exception as exc:
            raise JevVisualizationRouterError(f"Laya K线标记规划失败：{exc}") from exc

    def plan_card_layout(self, *, card_count: int, question: str = "", max_columns: int = 4, mobile_columns: int = 1) -> dict[str, Any]:
        """Choose per-row counts only after the caller knows the actual card count."""
        if type(card_count) is not int or not 1 <= card_count <= 8:
            raise ValueError("card_count must be 1..8")
        if type(max_columns) is not int or not 1 <= max_columns <= 4 or type(mobile_columns) is not int or not 1 <= mobile_columns <= 4:
            raise ValueError("column bounds must be 1..4")
        plans = {}
        for cap in range(1, min(card_count,max_columns)+1):
            rows = (card_count+cap-1)//cap
            base, extra = divmod(card_count,rows)
            counts = [base+(i<extra) for i in range(rows)]
            if min(counts)==1 and max(counts)>1:
                continue  # Avoid an orphan card when a balanced alternative exists.
            key = "+".join(map(str,counts))
            plans[key] = counts
        if len(plans) == 1:
            counts = next(iter(plans.values()))
            return {"source":"constraints","modelSelected":False,"reason":"only-feasible-layout",
                    "cardCount":card_count,"rowCounts":counts,"columns":max(counts),
                    "mobileColumns":mobile_columns}
        criteria = {key: f"{len(counts)} rows, cards per row {counts}; each row fills width; " + ("detailed single-column reading" if max(counts)==1 else "simultaneous comparison") for key,counts in plans.items()}
        try:
            with self.client_factory(endpoint=self.endpoint,model=self.model,timeout=self.timeout) as client:
                response=client.system_one(state={"cardCount":card_count,"request":question[:600],"goal":"Balanced intraday comparison; use 2–3 cards per row for normal desktop comparisons, avoid unnecessarily tall single-column stacks, keep readable charts."},questions={"card_layout":Choice(instructions="Choose balanced desktop rows for the actual card count. Honor explicit width constraints. Prefer a compact comparison with 2–3 charts per row, all cards visible without horizontal scrolling. Choose single column only for detailed reading or a single card.",criteria=criteria)})
            answer=response.answers["card_layout"]
            if answer.choice not in plans:
                raise ValueError("unknown card layout")
            return {"source":"jev","providerModel":response.model,"cardCount":card_count,"rowCounts":plans[answer.choice],"columns":max(plans[answer.choice]),"mobileColumns":mobile_columns,"confidence":self._confidence(answer)}
        except Exception as exc:
            raise JevVisualizationRouterError(f"Laya card layout planning failed: {exc}") from exc

    def route(
        self,
        *,
        question: str,
        candidates: list[dict[str, str]],
    ) -> JevVisualizationDecision:
        if not self.endpoint:
            raise JevVisualizationRouterError("未配置 LAYA_DECISION_URL")
        normalized = self._normalize_candidates(candidates)
        if not normalized:
            raise JevVisualizationRouterError("没有可供 Laya 选择的可视化组件")

        key_to_script: dict[str, str | None] = {self.NO_VISUAL: None}
        criteria: dict[str, str] = {
            self.NO_VISUAL: (
                "仅当用户未要求图表，且问题只是简单状态/单一数值、缺乏可信数据或图表无助于回答时，才不生成可视化。"
            )
        }
        available: list[dict[str, str]] = []
        for index, item in enumerate(normalized, start=1):
            key = f"visual-{index}"
            key_to_script[key] = item["script"]
            criteria[key] = (
                f"script={item['script']}; family={item['family']}; label={item['label']}; "
                f"capability={item['description']}"
            )
            available.append({"key": key, **item})

        state = {
            "request": str(question or "").strip()[:6000],
            "available_visualizations": available,
            "selection_goal": (
                "Choose the most semantically accurate concrete renderer. A supporting renderer is optional and must add "
                "a distinct analytical dimension rather than duplicate the primary view."
            ),
        }
        try:
            with self.client_factory(endpoint=self.endpoint, model=self.model, timeout=self.timeout) as client:
                response = client.system_one(
                    state=state,
                    questions={
                        "primary_visual": Choice(
                            instructions=(
                                "从真实候选组件中选择最符合用户请求的一个主图。用户明确指定的图表形式是硬约束，必须选择匹配组件。内置金融语义直接匹配时优先业务图；用户数据、跨资产比较或自定义编码优先通用图。只有图表确实无用时才选 no-visual。"
                            ),
                            criteria=criteria,
                        ),
                        "supporting_visual": Choice(
                            instructions=(
                                "只有候选图能回答第二个重要分析维度时，才选一张辅助图；不得与主图重复。普通单视图请求选 no-visual。"
                            ),
                            criteria=criteria,
                        ),
                        "semantic_lens": Choice(
                            instructions=(
                                "Choose the analytical lens that best turns the selected visualization into a useful answer. "
                                "The lens controls what the narrative should explain; it must not invent data or override the "
                                "selected renderer's schema."
                            ),
                            criteria=self.SEMANTIC_LENSES,
                        ),
                        "visual_encoding": Choice(
                            instructions=(
                                "Choose the visualization logic that best exposes the requested analytical relationship. "
                                "Treat an explicitly requested chart form as a hard constraint. The generative planner will "
                                "still validate the chosen renderer's semanticChannels and payload schema."
                            ),
                            criteria=self.VISUAL_ENCODINGS,
                        ),
                        "evidence_strategy": Choice(
                            instructions=(
                                "Choose the evidence composition for the request. For clearly identified US equities or "
                                "US-listed securities, preserve the native business-chart data/display logic and use AInvest "
                                "in-app text/video search when recent catalysts or media context materially improve the answer. "
                                "Never route explicitly non-US securities to the US-only internal search or video capabilities."
                            ),
                            criteria=self.EVIDENCE_STRATEGIES,
                        ),
                        "mobile_columns": Choice(
                            instructions="Choose the mobile comparison grid column count for multi_intraday.py or multi_kline.py. Honor explicit user requests. Prefer 1 for candlesticks/indicators/volume detail; 2 for ordinary intraday comparisons; 3 or 4 only for dense overviews/watchlists.",
                            criteria={"1": "One chart per row, detailed", "2": "Two charts per row, balanced comparison", "3": "Three charts per row, dense overview", "4": "Four charts per row, compact watchlist"},
                        ),
                        "mark_strategy": Choice(
                            instructions=(
                                "Choose whether the chart needs an evidence-backed annotation layer. Marks must clarify a "
                                "decision-relevant point, not decorate the chart. Prefer a concrete mark strategy whenever the "
                                "selected chart naturally exposes a decision-relevant turning point, event, threshold, leader/laggard, "
                                "contribution driver, signed direction, missing-value placeholder, or risk outlier. Choose no-mark only when neither the request "
                                "nor the selected visual semantics can identify one of those evidence-resolvable relationships. "
                                "For a single-series bar or bar-line view whose bars represent signed change, return, growth, "
                                "delta, P&L, or rise/fall, choose signed-direction even when the user did not explicitly request "
                                "colors. Do not choose signed-direction for a multi-series grouped bar: preserve color for the legend "
                                "and series identity, while position relative to zero communicates sign. "
                                "For a signed return/change distribution or histogram, choose distribution-polarity instead: "
                                "the bar height is frequency and polarity must be derived from the x-axis bin; grouped distributions "
                                "must preserve series colors and use the zero boundary rather than recoloring every bar. "
                                "This choice is semantic only; the planner must later resolve every target against real data."
                            ),
                            criteria=self.MARK_STRATEGIES,
                        ),
                    },
                )
        except Exception as exc:
            raise JevVisualizationRouterError(f"Laya 可视化路由请求失败：{exc}") from exc

        primary_answer = response.answers.get("primary_visual")
        supporting_answer = response.answers.get("supporting_visual")
        lens_answer = response.answers.get("semantic_lens")
        encoding_answer = response.answers.get("visual_encoding")
        evidence_answer = response.answers.get("evidence_strategy")
        mark_answer = response.answers.get("mark_strategy")
        primary_key = str(getattr(primary_answer, "choice", "") or "")
        supporting_key = str(getattr(supporting_answer, "choice", "") or "")
        if primary_key not in key_to_script or supporting_key not in key_to_script:
            raise JevVisualizationRouterError("Laya 返回了候选集合之外的可视化组件")
        primary_confidence = self._confidence(primary_answer)
        supporting_confidence = self._confidence(supporting_answer)
        semantic_lens = str(getattr(lens_answer, "choice", "") or "")
        if semantic_lens not in self.SEMANTIC_LENSES:
            semantic_lens = "evidence-led"
        semantic_lens_confidence = self._confidence(lens_answer)
        visual_encoding = str(getattr(encoding_answer, "choice", "") or "")
        if visual_encoding not in self.VISUAL_ENCODINGS:
            visual_encoding = "latest-vs-history"
        evidence_strategy = str(getattr(evidence_answer, "choice", "") or "")
        if evidence_strategy not in self.EVIDENCE_STRATEGIES:
            evidence_strategy = "structured-data-first"
        mark_strategy = str(getattr(mark_answer, "choice", "") or "")
        if mark_strategy not in self.MARK_STRATEGIES:
            mark_strategy = "no-mark"
        explicit_primary = self._explicit_requested_script(question, normalized)
        if primary_confidence < self.min_primary_confidence and not explicit_primary:
            raise JevVisualizationRouterError(
                f"Laya 主可视化置信度 {primary_confidence:.0%} 低于阈值 {self.min_primary_confidence:.0%}"
            )

        primary = key_to_script[primary_key]
        supporting = key_to_script[supporting_key]
        if explicit_primary:
            primary = explicit_primary
            primary_confidence = 1.0
        if primary is None or supporting == primary or supporting_confidence < self.min_supporting_confidence:
            supporting = None
        selected = tuple(script for script in (primary, supporting) if script)
        by_script = {item["script"]: item for item in normalized}
        primary_family = str(by_script.get(primary or "", {}).get("family") or "")
        if primary_family == "generic-chart" and evidence_strategy.startswith("us-business"):
            if evidence_strategy.endswith("internal-video"):
                evidence_strategy = "us-structured-plus-internal-video"
            elif evidence_strategy.endswith("plus-internal"):
                evidence_strategy = "us-structured-plus-internal"
            else:
                evidence_strategy = "structured-data-first"
        return JevVisualizationDecision(
            selected_scripts=selected,
            primary_script=primary,
            supporting_script=supporting,
            primary_confidence=primary_confidence,
            supporting_confidence=supporting_confidence,
            provider_model=str(getattr(response, "model", "") or self.model),
            candidate_count=len(normalized),
            semantic_lens=semantic_lens,
            semantic_lens_confidence=semantic_lens_confidence,
            primary_purpose=str(by_script.get(primary or "", {}).get("description") or ""),
            supporting_purpose=str(by_script.get(supporting or "", {}).get("description") or ""),
            visual_encoding=visual_encoding,
            visual_encoding_confidence=self._confidence(encoding_answer),
            evidence_strategy=evidence_strategy,
            evidence_strategy_confidence=self._confidence(evidence_answer),
            mark_strategy=mark_strategy,
            mark_strategy_confidence=self._confidence(mark_answer),
            mobile_columns=int(getattr(response.answers.get("mobile_columns"), "choice", "2")) if str(getattr(response.answers.get("mobile_columns"), "choice", "2")) in {"1", "2", "3", "4"} else 2,
        )

    @staticmethod
    def _explicit_requested_script(question: str, candidates: list[dict[str, str]]) -> str | None:
        text = str(question or "").lower()
        terms = {
            "multi_kline.py": ("多k线", "多k線", "多周期k线", "多股k线", "multiple candlestick", "multi kline"),
            "kline.py": ("k线", "蜡烛", "candlestick"),
            "line_chart.py": ("折线图", "line chart"),
            "group_line.py": ("分组折线", "多折线", "group line"),
            "bar_chart.py": ("柱状图", "bar chart"),
            "grouped_bar.py": ("分组柱状", "grouped bar"),
            "pie.py": ("饼图", "饼状图", "pie chart"),
            "treemap.py": ("矩形树图", "treemap"),
            "timeline.py": ("时间线", "timeline"),
            "flowchart.py": ("流程图", "flowchart"),
            "mind_map.py": ("思维导图", "mind map"),
            "table.py": ("表格", "table"),
        }
        by_name = {str(item.get("script") or "").rsplit("/", 1)[-1]: str(item.get("script") or "") for item in candidates}
        for filename, aliases in terms.items():
            if filename in by_name and any(alias in text for alias in aliases):
                return by_name[filename]
        if len(candidates) == 1 and any(term in text for term in ("图表", "可视化", "chart", "plot")):
            return str(candidates[0].get("script") or "") or None
        return None

    @staticmethod
    def _normalize_candidates(candidates: list[dict[str, str]]) -> list[dict[str, str]]:
        normalized: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in candidates:
            script = str(item.get("script") or "").strip()
            if not script or script in seen:
                continue
            seen.add(script)
            normalized.append(
                {
                    "script": script,
                    "family": str(item.get("family") or "chart").strip()[:80],
                    "label": str(item.get("label") or script).strip()[:160],
                    "description": str(item.get("description") or "").strip()[:1200],
                }
            )
        return normalized

    @staticmethod
    def _confidence(answer: Any) -> float:
        try:
            value = float(getattr(answer, "confidence", 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        return max(0.0, min(value, 1.0))
