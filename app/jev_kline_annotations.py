"""Evidence-only native K-line marks. No provider, renderer, or host imports."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .laya_client import Choice

MA_COLORS = ('#fbbf24', '#8b5cf6', '#38bdf8', '#f97316')
REFERENCE_COLORS = ('#fb923c', '#38bdf8', '#fbbf24', '#8b5cf6', '#f472b6', '#60a5fa')
ALIASES = {'horizontal': 'horizontal-line', 'vertical': 'vertical-line', 'straightLine': 'straight-line', 'rayLine': 'ray-line', 'arrowSegment': 'arrow-segment', 'pure-text': 'text'}
TYPES = {'horizontal-line', 'vertical-line', 'straight-line', 'ray-line', 'segment', 'arrow-segment', 'buy', 'sell', 'text', 'callout'}
TWO_POINTS = {'straight-line', 'ray-line', 'segment', 'arrow-segment'}


def timestamp(value: Any) -> int | None:
    try:
        number = float(value)
        if math.isfinite(number):
            return round(number * 1000 if abs(number) < 1e12 else number)
    except (ValueError, TypeError, OverflowError):
        pass
    try:
        date = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return round(date.timestamp() * 1000)
    except (ValueError, TypeError, OverflowError):
        return None


def evidence_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        time = row.get('time') or row.get('timestamp')
        stamp = timestamp(time)
        try:
            low, high, close = (float(row[key]) for key in ('low', 'high', 'close'))
        except (ValueError, TypeError, KeyError):
            continue
        if stamp is None or not all(math.isfinite(v) and v > 0 for v in (low, high, close)) or not low <= close <= high:
            continue
        valid.append({**row, 'time': time, '_timestamp': stamp, 'low': low, 'high': high, 'close': close})
    return sorted(valid, key=lambda row: row['_timestamp'])


def kline_annotation_style(annotation: dict[str, Any], *, ma_periods: list[int] | None = None, market: str = 'US', index: int = 0) -> tuple[str, str]:
    """Explicit colors win; semantic roles and MA identity share one policy."""
    text = str(annotation.get('text') or '')
    role = str(annotation.get('role') or '').lower()
    color = str(annotation.get('color') or '')
    if re.fullmatch(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})', color):
        return color, text
    ma = re.search(r'\bMA\s*(\d+)', text, re.I)
    periods = ma_periods if ma_periods is not None else [5, 10, 20, 60]
    if ma and int(ma[1]) in periods:
        at = periods.index(int(ma[1]))
        if at < len(MA_COLORS):
            return MA_COLORS[at], text
    red_up = str(market).upper() in {'CN', 'HK'}
    if annotation.get('type') == 'buy' or role == 'buy':
        return ('#ff2f57' if red_up else '#00b899'), text or '买入参考点'
    if annotation.get('type') == 'sell' or role == 'sell':
        return ('#00b899' if red_up else '#ff2f57'), text or '卖出参考点'
    if role in {'support', 'low', 'stop-loss'} or re.search(r'支撑|支撐|支持|低点|低點|support|\blow\b|stop.loss', text, re.I):
        return '#fb923c', text or '支撑参考位'
    if role == 'high' or re.search(r'高点|高點|高位|\bhigh\b', text, re.I):
        return '#f472b6', text or '区间高点'
    if role == 'resistance' or re.search(r'压力|壓力|阻力|resistance', text, re.I):
        return '#60a5fa', text or '压力参考位'
    if annotation.get('type') in {'text', 'callout'}:
        return '#8b5cf6', text or '技术参考点'
    return REFERENCE_COLORS[index % len(REFERENCE_COLORS)], text or '技术参考位'


def normalize_kline_annotations(proposals: Any, *, symbol: str, period: str, ohlcv: list[dict[str, Any]], ma_periods: list[int] | None = None, market: str = 'US', requested_type: str = '', max_marks: int = 8) -> tuple[dict[str, Any], ...]:
    """Validate native/legacy proposals against one symbol, period, and candle set."""
    rows = evidence_rows(ohlcv)
    if not symbol.strip() or not period.strip() or not rows or not isinstance(proposals, (list, tuple)):
        return ()
    time_to_row = {row['_timestamp']: row for row in rows}
    low, high = min(r['low'] for r in rows), max(r['high'] for r in rows)
    symbol = symbol.strip().upper()
    result, seen = [], set()
    for proposal in proposals[:64]:
        if not isinstance(proposal, dict) or str(proposal.get('symbol') or symbol).upper() != symbol or str(proposal.get('period') or period) != period:
            continue
        kind = requested_type or str(proposal.get('type') or 'horizontal-line')
        kind = ALIASES.get(kind, kind)
        if kind not in TYPES:
            continue
        points = proposal.get('points') or [{'time': proposal.get('time') or rows[-1]['time'], 'price': proposal.get('price')}]
        if not isinstance(points, list) or len(points) != (2 if kind in TWO_POINTS else 1):
            continue
        normalized_points = []
        for point in points:
            if not isinstance(point, dict):
                break
            stamp = timestamp(point.get('time'))
            try:
                price = float(point.get('price'))
            except (ValueError, TypeError):
                break
            if stamp not in time_to_row or not math.isfinite(price) or not low <= price <= high:
                break
            normalized_points.append({'time': time_to_row[stamp]['time'], 'price': price})
        if len(normalized_points) != len(points):
            continue
        text = re.sub(r'[\x00-\x1f<>]', '', str(proposal.get('text') or '')).strip()[:80]
        key = (kind, tuple((timestamp(p['time']), p['price']) for p in normalized_points), text)
        if key in seen:
            continue
        seen.add(key)
        color, label = kline_annotation_style({**proposal, 'type': kind, 'text': text}, ma_periods=ma_periods, market=market, index=len(result))
        mark = {'symbol': symbol, 'type': kind, 'period': period, 'points': normalized_points, 'text': label, 'color': color, 'source': 'jev-kline-policy'}
        if proposal.get('role'):
            mark['role'] = str(proposal['role'])[:30]
        for field in ('offsetX', 'offsetY'):
            if isinstance(proposal.get(field), (int, float)) and math.isfinite(proposal[field]):
                mark[field] = proposal[field]
        result.append(mark)
        if len(result) >= max_marks:
            break
    return tuple(result)


def build_kline_candidates(*, symbol: str, period: str, ohlcv: list[dict[str, Any]], ma_periods: list[int] | None = None, language: str = 'zh-CN', requested_type: str = '') -> tuple[dict[str, Any], ...]:
    rows = evidence_rows(ohlcv)
    if not rows:
        return ()
    latest = rows[-1]
    english = language.lower().startswith('en')
    candidates = []
    def add(row: dict[str, Any], price: float, role: str, text: str, kind: str = 'horizontal-line') -> None:
        anchor = latest if requested_type in {'text', 'callout'} and role in {'support', 'resistance'} else row
        candidates.append({'symbol': symbol, 'period': period, 'type': requested_type or kind, 'time': anchor['time'], 'price': price, 'role': role, 'text': text})
    recent = rows[-20:]
    low_row = min(recent, key=lambda r: r['low'])
    high_row = max(recent, key=lambda r: r['high'])
    add(low_row, low_row['low'], 'support', 'Recent support' if english else '近期支撑')
    add(high_row, high_row['high'], 'resistance', 'Recent resistance' if english else '近期压力')
    high_row = max(rows, key=lambda r: r['high'])
    low_row = min(rows, key=lambda r: r['low'])
    add(high_row, high_row['high'], 'high', 'Range high' if english else '区间高点', 'callout')
    add(low_row, low_row['low'], 'low', 'Range low' if english else '区间低点', 'callout')
    add(latest, latest['close'], 'latest', 'Latest close' if english else '最新收盘', 'callout')
    for n in ma_periods or [20, 50, 200]:
        if isinstance(n, int) and 1 < n <= len(rows):
            add(latest, sum(row['close'] for row in rows[-n:]) / n, 'ma', f'MA{n}')
    return tuple(candidates)


@dataclass(frozen=True)
class JevKlineAnnotationPlan:
    annotations: tuple[dict[str, Any], ...]
    mark_strategy: str
    confidence: float
    provider_model: str


def plan_kline_annotations(router: Any, *, question: str, symbol: str, period: str, ohlcv: list[dict[str, Any]], proposals: Any = None, ma_periods: list[int] | None = None, market: str = 'US', language: str = 'zh-CN', requested_type: str = '', min_confidence: float = .55) -> JevKlineAnnotationPlan:
    if not router.configured:
        raise ValueError('未配置 LAYA_DECISION_URL')
    raw = proposals if proposals else build_kline_candidates(symbol=symbol, period=period, ohlcv=ohlcv, ma_periods=ma_periods, language=language, requested_type=requested_type)
    candidates = normalize_kline_annotations(raw, symbol=symbol, period=period, ohlcv=ohlcv, ma_periods=ma_periods, market=market, requested_type=requested_type)
    if not candidates:
        return JevKlineAnnotationPlan((), 'no-mark', 0, '')
    mapping = {f'mark-{i + 1}': mark for i, mark in enumerate(candidates)}
    state = {'request': str(question)[:6000], 'symbol': symbol, 'period': period, 'candidates': mapping, 'constraint': 'Evaluate each validated candidate independently. Do not invent coordinates. Buy/sell marks are references, not execution or guaranteed signals.'}
    with router.client_factory(endpoint=router.endpoint, model=router.model, timeout=router.timeout) as client:
        response = client.system_one(state=state, questions={
            'mark_strategy': Choice(instructions='按用户请求选择标记用途；用户明确要求支撑、压力、事件或拐点标记时，不得选 no-mark。', criteria={k: router.MARK_STRATEGIES[k] for k in ('no-mark', 'threshold-reference', 'turning-points', 'event-callouts', 'risk-outliers')}),
            **{key: Choice(instructions=f'根据用户请求独立评估已验证候选 {key}；明确要求且直接匹配时选 include。', criteria={
                'include': f'This validated candidate directly supports the requested analysis: {mark["text"]}, {mark["type"]}, {mark["points"]}.',
                'omit': 'This candidate is unnecessary, irrelevant, or insufficiently supported for the request.',
            }) for key, mark in mapping.items()},
        })
    answers = response.answers
    strategy = answers.get('mark_strategy')
    confidence = router._confidence(strategy)
    strategy_name = str(getattr(strategy, 'choice', 'no-mark'))
    request_text = str(question or '').lower()
    explicit_strategy = (
        'event-callouts' if any(term in request_text for term in ('事件', '催化', 'event')) else
        'turning-points' if any(term in request_text for term in ('拐点', '高点', '低点', 'turning point')) else
        'risk-outliers' if any(term in request_text for term in ('风险', '异常', '离群', 'outlier', 'risk')) else
        'threshold-reference' if any(term in request_text for term in ('支撑', '压力', '阻力', '阈值', '水平线', '参考线', 'support', 'resistance', 'threshold')) else ''
    )
    if explicit_strategy:
        strategy_name = explicit_strategy
        confidence = max(confidence, 1.0)
    if strategy_name not in {'threshold-reference', 'turning-points', 'event-callouts', 'risk-outliers'} or confidence < min_confidence:
        return JevKlineAnnotationPlan((), 'no-mark', confidence, str(getattr(response, 'model', '')))
    ranked = []
    for key, mark in mapping.items():
        answer = answers.get(key)
        score = router._confidence(answer)
        if (getattr(answer, 'choice', '') == 'include' and score >= min_confidence) or (explicit_strategy and proposals):
            ranked.append((score, mark))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = [{**mark, 'source': 'jev-kline-plan'} for _, mark in ranked[:3]]
    return JevKlineAnnotationPlan(tuple(selected), strategy_name, confidence, str(getattr(response, 'model', '')))


def main() -> int:
    """Plan an existing native payload without fetching or rendering its data."""
    import argparse
    import copy
    import json
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.jev_visualization_router import JevVisualizationRouter
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', required=True)
    parser.add_argument('--question', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--normalize-only', action='store_true', help='Validate and style existing marks; never claim a model selection.')
    args = parser.parse_args()
    payload = json.loads(Path(args.payload).read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        parser.error('payload must be an object')
    output = copy.deepcopy(payload)
    component = output.get('component') if isinstance(output.get('component'), dict) else output
    props = component.get('props') if isinstance(component.get('props'), dict) else component
    symbol = str(props.get('code') or props.get('symbol') or output.get('symbol') or output.get('code') or '').upper()
    period = str(props.get('dataType') or props.get('period') or output.get('period') or '1d')
    rows = component.get('data') if isinstance(component.get('data'), list) else output.get('data', [])
    if not symbol or not evidence_rows(rows):
        parser.error('symbol and verified OHLCV evidence are required')
    options = dict(symbol=symbol, period=period, ohlcv=rows, ma_periods=props.get('ma'), market=str(props.get('financialMarket') or ('CN' if re.search(r'\.(SH|SZ|SS|BJ)$', symbol) else 'HK' if symbol.endswith('.HK') else 'US')))
    if args.normalize_only:
        marks = normalize_kline_annotations(props.get('annotations', []), **options)
        receipt = {'policy': 'jev_vis_router', 'selection': 'verified-proposals', 'modelSelected': False}
    else:
        plan = JevVisualizationRouter().plan_kline_annotations(question=args.question, proposals=props.get('annotations'), language=str(props.get('language') or 'zh-CN'), **options)
        marks = plan.annotations
        receipt = {'policy': 'jev_vis_router', 'provider': 'local-laya', 'selection': 'laya', 'modelSelected': True, 'strategy': plan.mark_strategy, 'confidence': plan.confidence, 'model': plan.provider_model}
    other_periods = [mark for mark in props.get('annotations', []) if isinstance(mark, dict) and mark.get('period') and str(mark['period']) != period]
    props['annotations'] = [*other_periods, *marks]
    receipt['period'] = period
    output['jevAnnotationPlan'] = receipt
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'output': str(destination.resolve()), 'markCount': len(marks), **receipt}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
