"""Evidence-only native K-line marks. No provider, renderer, or host imports."""
from __future__ import annotations

import math
import re
import json
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

if __package__:
    from .laya_client import Choice
else:
    import sys
    sys.path.insert(0, str(Path(__file__).absolute().parents[1]))
    from app.laya_client import Choice

MA_COLORS = ('#fbbf24', '#8b5cf6', '#38bdf8', '#f97316')
REFERENCE_COLORS = ('#fb923c', '#38bdf8', '#fbbf24', '#8b5cf6', '#f472b6', '#60a5fa')
ALIASES = {'horizontal': 'horizontal-line', 'vertical': 'vertical-line', 'straightLine': 'straight-line', 'rayLine': 'ray-line', 'arrowSegment': 'arrow-segment', 'pure-text': 'text'}
CATALOG = json.loads(Path(__file__).resolve().with_name('kline_annotation_catalog.json').read_text(encoding='utf-8'))
ALIASES.update(CATALOG['aliases'])
TYPES = set(CATALOG['supportedTypes'])
TWO_POINTS = {'straight-line', 'ray-line', 'segment', 'arrow-segment'}


def requested_annotation_type(question: str) -> str:
    """Only explicit drawing requests select a shape, never incidental discussion."""
    request = str(question or '').lower()
    if not re.search(r'画|标记|标注|绘|加上|添加|使用|用|draw|plot|add', request):
        return ''
    names = {**{v['label']: k for k, v in CATALOG['typeDefinitions'].items()},
             '箭头标注':'callout', '引线标注':'callout', '文字':'text', '气泡':'callout',
             '多头仓位': 'long-position', '空头仓位': 'short-position',
             '斐波那契扩展': 'fib-extension', '斐波那契回调': 'fib-retracement',
             '回归趋势': 'regression-channel', '趋势通道': 'regression-channel'}
    for name in sorted(names, key=len, reverse=True):
        if name.lower() in request:
            return names[name]
    for name in sorted([*TYPES, *ALIASES], key=len, reverse=True):
        if re.search(r'(?<![a-z-])' + re.escape(name.lower()) + r'(?![a-z-])', request):
            return ALIASES.get(name, name)
    return ''


def unsupported_annotation_request(question: str) -> bool:
    return bool(re.search(r'江恩|\bgann\b|趋势角度|平顶.?平底|弧形|双曲线|分价成交|成交量分布|volume.?profile|模拟.?[kK]线|模擬.?[kK]線|forecast.candle|斐波那契(?:圈|弧|楔|速度|趋势时间)|fib[ -](?:circle|arc|wedge|speed|trend.time)',str(question),re.I))


def drawing_style(proposal: dict[str, Any]) -> dict[str, Any]:
    """Whitelist style values; never forward arbitrary CSS, HTML, or execution data."""
    result = {}
    for key, lo, hi in [('lineWidth',1,8),('opacity',.1,1),('fillOpacity',0,.5),('fontSize',10,24),('deviation',.1,5),('offsetX',-2000,2000),('offsetY',-2000,2000)]:
        value = proposal.get(key)
        if isinstance(value, (int,float)) and not isinstance(value,bool) and math.isfinite(value):
            result[key] = min(hi,max(lo,value))
    for key in ('fillColor','textColor'):
        if re.fullmatch(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})',str(proposal.get(key) or '')):
            result[key]=proposal[key]
    if proposal.get('lineStyle') in {'solid','dashed','dotted'}:
        result['lineStyle']=proposal['lineStyle']
    for key in ('showLabels','extendLeft','extendRight'):
        if isinstance(proposal.get(key),bool):
            result[key]=proposal[key]
    levels=proposal.get('levels')
    if isinstance(levels,list):
        bound=144 if proposal.get('type')=='fib-timezone' else 10
        valid=list(dict.fromkeys(v for v in levels if isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) and abs(v)<=bound))[:16]
        if valid:
            result['levels']=valid
    if isinstance(proposal.get('levelColors'),list):
        colors=[v for v in proposal['levelColors'][:16] if isinstance(v,str) and re.fullmatch(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})',v)]
        if colors:
            result['levelColors']=colors
    if proposal.get('emoji'):
        result['emoji']=re.sub(r'[\x00-\x1f<>]', '',str(proposal['emoji']))[:16]
    return result


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


def normalize_kline_annotations(proposals: Any, *, symbol: str, period: str, ohlcv: list[dict[str, Any]], ma_periods: list[int] | None = None, market: str = 'US', requested_type: str = '', max_marks: int | None = 8) -> tuple[dict[str, Any], ...]:
    """Validate native/legacy proposals against one symbol, period, and candle set."""
    rows = evidence_rows(ohlcv)
    if not symbol.strip() or not period.strip() or not rows or not isinstance(proposals, (list, tuple)):
        return ()
    time_to_row = {row['_timestamp']: row for row in rows}
    low, high = min(r['low'] for r in rows), max(r['high'] for r in rows)
    symbol = symbol.strip().upper()
    result, seen = [], set()
    for proposal in proposals:
        if not isinstance(proposal, dict) or str(proposal.get('symbol') or symbol).upper() != symbol or str(proposal.get('period') or period) != period:
            continue
        kind = requested_type or str(proposal.get('type') or 'horizontal-line')
        kind = ALIASES.get(kind, kind)
        if kind not in TYPES:
            continue
        points = proposal.get('points') or [{'time': proposal.get('time') or rows[-1]['time'], 'price': proposal.get('price')}]
        definition = CATALOG['typeDefinitions'][kind]
        if not isinstance(points, list) or not definition['minPoints'] <= len(points) <= definition['maxPoints']:
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
        if len(normalized_points) != len(points) or (len(points)>1 and len({(timestamp(p['time']),p['price']) for p in normalized_points})<2):
            continue
        stamps=[timestamp(p['time']) for p in normalized_points]
        if kind in {'parallel-channel','fib-channel','regression-channel','fib-timezone','fib-fan'} and stamps[0]==stamps[1]:
            continue
        if kind=='disjoint-channel' and (stamps[0]!=stamps[2] or stamps[1]!=stamps[3] or stamps[0]==stamps[1]):
            continue
        if kind in {'long-position','short-position'}:
            entry,stop,target=(p['price'] for p in normalized_points)
            if stamps[2]<=stamps[0] or not (stop<entry<target if kind=='long-position' else target<entry<stop):
                continue
        text = re.sub(r'[\x00-\x1f<>]', '', str(proposal.get('text') or '')).strip()[:80]
        style=drawing_style(proposal)
        key = (kind, tuple((timestamp(p['time']), p['price']) for p in normalized_points), text, str(proposal.get('color') or ''), json.dumps(style,sort_keys=True))
        if key in seen:
            continue
        seen.add(key)
        color, label = kline_annotation_style({**proposal, 'type': kind, 'text': text}, ma_periods=ma_periods, market=market, index=len(result))
        mark = {'symbol': symbol, 'type': kind, 'period': period, 'points': normalized_points, 'text': label, 'color': color, 'source': 'jev-kline-policy'}
        if kind.startswith('fib-') and not re.fullmatch(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})',str(proposal.get('color') or '')):
            mark.pop('color')  # Native ratio palette, unless user explicitly supplies a common color.
        mark.update(style)
        if proposal.get('role'):
            mark['role'] = str(proposal['role'])[:30]
        if proposal.get('basis'):
            mark['basis'] = re.sub(r'[\x00-\x1f<>]', '', str(proposal['basis']))[:240]
        result.append(mark)
        if max_marks is not None and len(result) >= max_marks:
            break
    return tuple(result)


def build_kline_candidates(*, symbol: str, period: str, ohlcv: list[dict[str, Any]], ma_periods: list[int] | None = None, language: str = 'zh-CN', requested_type: str = '') -> tuple[dict[str, Any], ...]:
    rows = evidence_rows(ohlcv)
    if not rows:
        return ()
    latest = rows[-1]
    english = language.lower().startswith('en')
    requested_type=ALIASES.get(requested_type,requested_type)
    if requested_type and requested_type not in TYPES:
        return ()
    if requested_type and CATALOG['typeDefinitions'][requested_type]['minPoints']>1:
        recent=rows[-60:]
        if len(recent)<2:
            return ()
        def point(row,field='close'):
            return {'time':row['time'],'price':row[field]}
        def candidate(points,text):
            return ({'symbol':symbol,'period':period,'type':requested_type,'points':points,'text':text,'extendRight':requested_type in {'fib-retracement','fib-extension','parallel-channel','regression-channel'}},)
        if requested_type=='regression-channel':
            n=len(recent);mean=sum(row['close'] for row in recent)/n;mid=(n-1)/2
            variance=sum((row['close']-mean)**2 for row in recent)
            slope=sum((i-mid)*(row['close']-mean) for i,row in enumerate(recent))/sum((i-mid)**2 for i in range(n))
            residual=sum((row['close']-(mean+slope*(i-mid)))**2 for i,row in enumerate(recent))
            r2=1-residual/variance if variance else 0
            return tuple({**mark,'basis':f'{n} observed closes; slope {slope:+.4g}/bar, R²={r2:.3f}. Bands use +/-2 residual standard deviations, not price predictions.'} for mark in candidate([point(recent[0]),point(recent[-1])],'Close regression ±2σ' if english else '收盘价回归 ±2σ'))
        if requested_type in {'fib-retracement','rectangle','price-range','date-range','date-price-range'}:
            low_row=min(recent,key=lambda r:r['low']); high_row=max(recent,key=lambda r:r['high'])
            extremes=sorted([(low_row,'low'),(high_row,'high')],key=lambda pair:pair[0]['_timestamp'])
            if extremes[0][0]['_timestamp']==extremes[1][0]['_timestamp']:
                return ()
            return candidate([point(row,key) for row,key in extremes],'Observed range' if english else '实际区间高低点')
        # Confirmed local pivots only; neither latest unfinished pivot nor invented price.
        lows=[r for i,r in enumerate(recent) if 2<=i<len(recent)-2 and all(r['low']<recent[j]['low'] for j in (i-2,i-1,i+1,i+2))]
        highs=[r for i,r in enumerate(recent) if 2<=i<len(recent)-2 and all(r['high']>recent[j]['high'] for j in (i-2,i-1,i+1,i+2))]
        if requested_type in {'segment','straight-line','ray-line','arrow-segment','info-line'}:
            result=[]
            for pivots,field,text in ((lows,'low','Swing lows' if english else '局部低点连线'),(highs,'high','Swing highs' if english else '局部高点连线')):
                if len(pivots)>=2:
                    result.extend(candidate([point(row,field) for row in pivots[-2:]],text))
            return tuple(result)
        if requested_type=='parallel-channel':
            result=[]
            by_time={row['_timestamp']:i for i,row in enumerate(recent)}
            for pivots,field,opposite in ((lows,'low','high'),(highs,'high','low')):
                if len(pivots)<2:
                    continue
                first,last=pivots[-2:]
                start,end=by_time[first['_timestamp']],by_time[last['_timestamp']]
                if end<=start:
                    continue
                slope=(last[field]-first[field])/(end-start)
                baseline=lambda i:first[field]+slope*(i-start)
                interval=list(enumerate(recent[start:end+1],start))
                at,third=max(interval,key=lambda pair:(pair[1][opposite]-baseline(pair[0]))*(1 if field=='low' else -1))
                offset=third[opposite]-baseline(at)
                if offset==0 or (offset>0)!=(field=='low'):
                    continue
                coverage=sum(min(baseline(i),baseline(i)+offset)<=row['close']<=max(baseline(i),baseline(i)+offset) for i,row in interval)/len(interval)
                if coverage<.65:
                    continue
                marks=candidate([point(first,field),point(last,field),point(third,opposite)],'Observed pivot channel' if english else '实际拐点平行通道')
                result.extend({**mark,'basis':f'Two confirmed {field} pivots; opposite {opposite} anchor from observed bars; {coverage:.1%} close coverage within the anchor interval.'} for mark in marks)
            return tuple(result)
        if requested_type in {'fib-extension','pitchfork','schiff-pitchfork','modified-schiff-pitchfork'}:
            pivots=sorted([(r,'low') for r in lows]+[(r,'high') for r in highs],key=lambda pair:pair[0]['_timestamp'])
            alternating=[]
            for row,field in pivots:
                if alternating and alternating[-1][1]==field:
                    previous=alternating[-1][0]
                    if (row[field]<previous[field] if field=='low' else row[field]>previous[field]):
                        alternating[-1]=(row,field)
                else:
                    alternating.append((row,field))
            if len(alternating)>=3:
                return candidate([point(row,field) for row,field in alternating[-3:]],'Observed pivots · reference' if english else '实际拐点 · 技术参考')
        # Arbitrary decoration and risk scenarios still require explicit evidence-bound anchors.
        return ()
    if not requested_type:
        # The native v2 pool replaces the legacy horizontal/callout/MA default.
        # Every family is independently eligible; JEV may omit all of them.
        if len(rows)<5 or max(row['high'] for row in rows)==min(row['low'] for row in rows):
            return ()
        kinds=[
            ('segment',rows,'Two confirmed local extrema of the same kind; no unconfirmed endpoint or future candle.'),
            ('regression-channel',rows,'OLS of actual closes in the latest observed window; bands use residual standard deviation, not predicted prices.'),
            ('parallel-channel',rows,'Two confirmed same-side pivots and an actual opposite extreme; no guessed boundary.'),
            ('fib-retracement',rows,'Observed window low and high, ordered by time. Ratio levels are technical references, not future prices.'),
            ('rectangle',rows[-20:],'Observed low/high anchors from the latest 20 bars; the box spans their timestamps, not a confirmed consolidation claim.'),
            ('date-price-range',rows,'Time and price change between actual observed extremes; bar intervals and elapsed days remain separate.'),
            ('fib-extension',rows,'Three alternating confirmed pivots. Extension ratios are scenarios, never observed future prices.'),
            ('pitchfork',rows,'Three alternating confirmed pivots; median and parallel rays are technical references, not a forecast.'),
        ]
        result=[]
        for kind,sample,basis in kinds:
            if kind=='regression-channel' and (len(sample)<20 or len({row['close'] for row in sample})<2):
                continue
            marks=build_kline_candidates(symbol=symbol,period=period,ohlcv=sample,ma_periods=ma_periods,language=language,requested_type=kind)
            result.extend({**mark,'basis':mark.get('basis') or basis,'candidatePolicy':'native-v2-auto'} for mark in marks)
        return tuple(result)
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
    candidate_types: tuple[str, ...] = ()
    candidate_count: int = 0
    candidate_policy: str = 'native-v2-auto'


def plan_kline_annotations(router: Any, *, question: str, symbol: str, period: str, ohlcv: list[dict[str, Any]], proposals: Any = None, ma_periods: list[int] | None = None, market: str = 'US', language: str = 'zh-CN', requested_type: str = '', min_confidence: float = .55, selection_mode: str = 'auto', max_marks: int | None = None) -> JevKlineAnnotationPlan:
    if not router.configured:
        raise ValueError('未配置 LAYA_DECISION_URL')
    if selection_mode not in {'auto','user-specified','all'}:
        raise ValueError('selection_mode must be auto, user-specified or all')
    requested_type=ALIASES.get(requested_type,requested_type) or requested_annotation_type(question)
    if not requested_type and unsupported_annotation_request(question):
        raise ValueError('Requested drawing is outside the native catalog; see unsupportedTypes. No substitute marks were generated.')
    supplied=list(proposals) if isinstance(proposals,(list,tuple)) else []
    if selection_mode!='auto' and supplied:
        raw=supplied  # Explicit user scope is never expanded behind their back.
    else:
        generated=build_kline_candidates(symbol=symbol, period=period, ohlcv=ohlcv, ma_periods=ma_periods, language=language, requested_type=requested_type)
        raw=[*supplied,*generated] if requested_type else [*generated,*supplied]
        if requested_type:
            raw=[mark for mark in raw if isinstance(mark,dict) and ALIASES.get(str(mark.get('type')),str(mark.get('type')))==requested_type]
    candidates = normalize_kline_annotations(raw, symbol=symbol, period=period, ohlcv=ohlcv, ma_periods=ma_periods, market=market, max_marks=None)
    policy='native-v2-auto' if selection_mode=='auto' and not requested_type else 'native-v2-requested-type' if requested_type else 'native-v2-user-set'
    if not candidates:
        return JevKlineAnnotationPlan((), 'no-mark', 0, '',candidate_policy=policy)
    mapping = {f'mark-{i + 1}': mark for i, mark in enumerate(candidates)}
    candidate_types=tuple(dict.fromkeys(mark['type'] for mark in candidates))
    observed=evidence_rows(ohlcv)[-60:]
    observed_low=min(row['low'] for row in observed);observed_high=max(row['high'] for row in observed)
    evidence_summary={'bars':len(observed),'lastClose':round(observed[-1]['close'],6),
                      'windowChangePct':round((observed[-1]['close']/observed[0]['close']-1)*100,3),
                      'windowLow':round(observed_low,6),'windowHigh':round(observed_high,6)}
    state = {'request': str(question)[:6000], 'symbol': symbol, 'period': period, 'candidates': mapping,
             # Full definitions remain in the validator/catalog CLI. The CPU
             # sidecar has a 2,000-token state budget; don't resend all formulas.
             'drawingCapabilities': {'version':CATALOG['version'], 'supportedTypes':CATALOG['supportedTypes'],
                                     'activeTypes':sorted({mark['type'] for mark in candidates}),
                                     'styleFields':['lineWidth','lineStyle','opacity','fillColor','fillOpacity','fontSize','textColor','showLabels','extendLeft','extendRight','levels','levelColors']},
             'selectionMode':selection_mode,
             'candidateSummary':list(dict.fromkeys((mark['type'],mark['text']) for mark in candidates)),
             'observedEvidence':evidence_summary,
             'constraint': 'Evaluate each validated candidate independently. Use only the native catalog types/style. Never invent coordinates or claim projections are observed prices. Buy/sell and long/short positions are technical scenarios, never execution or guaranteed signals.'}
    with router.client_factory(endpoint=router.endpoint, model=router.model, timeout=router.timeout) as client:
        response = client.system_one(state=state, questions={
            'mark_strategy': Choice(instructions='依据问题和原生候选选择用途；普通技术分析也要评估趋势、通道、回撤、区间，不要求用户点名。无关或证据不足允许 no-mark。', criteria={k: router.MARK_STRATEGIES[k] for k in ('no-mark', 'threshold-reference', 'turning-points', 'event-callouts', 'risk-outliers')}),
            **{key: Choice(instructions=f'根据用户请求独立评估已验证候选 {key}；明确要求且直接匹配时选 include。', criteria={
                'include': f'{mark["type"]}: {mark["text"]}. Evidence: {mark.get("basis") or "Exact verified anchors"}. Directly explains the requested analysis.',
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
        'threshold-reference' if requested_type or selection_mode!='auto' or any(term in request_text for term in ('支撑', '压力', '阻力', '阈值', '水平线', '参考线', '斐波那契', '通道', 'support', 'resistance', 'threshold')) else ''
    )
    explicit_drawing_intent=bool(requested_type or selection_mode!='auto' or re.search(r'画|标记|标注|绘|可视化|\bdraw\b|\bannotate\b|\bmark\b',request_text))
    if explicit_strategy and explicit_drawing_intent:
        strategy_name = explicit_strategy
        confidence = max(confidence, 1.0)
    if strategy_name not in {'threshold-reference', 'turning-points', 'event-callouts', 'risk-outliers'} or confidence < min_confidence:
        return JevKlineAnnotationPlan((), 'no-mark', confidence, str(getattr(response, 'model', '')),candidate_types,len(candidates),policy)
    ranked = []
    for key, mark in mapping.items():
        answer = answers.get(key)
        score = router._confidence(answer)
        if (getattr(answer, 'choice', '') == 'include' and score >= min_confidence) or selection_mode!='auto' or requested_type:
            ranked.append((score, mark))
    ranked.sort(key=lambda item: item[0], reverse=True)
    limit=None if selection_mode in {'all','user-specified'} else (max_marks if max_marks is not None and max_marks>0 else 3)
    if selection_mode=='auto' and max_marks is None:
        families,diverse=set(),[]
        for score,mark in ranked:
            family=('trend' if mark['type'] in {'segment','straight-line','ray-line','parallel-channel','regression-channel','pitchfork'} else
                    'retracement' if mark['type'] in {'fib-retracement','fib-extension','fib-channel'} else
                    'range' if mark['type'] in {'rectangle','date-price-range','price-range','date-range'} else
                    'reference' if mark['type'] in {'horizontal-line','horizontal-ray','text','callout','price-label'} else mark['type'])
            if family not in families:
                families.add(family);diverse.append((score,mark))
        ranked=diverse
    selected = [{**mark, 'source': 'jev-kline-plan'} for _, mark in (ranked if limit is None else ranked[:limit])]
    return JevKlineAnnotationPlan(tuple(selected), strategy_name, confidence, str(getattr(response, 'model', '')),candidate_types,len(candidates),policy)


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
    parser.add_argument('--catalog', action='store_true', help='Print supported native types, anchors, styles, semantics and explicit limitations.')
    parser.add_argument('--payload')
    parser.add_argument('--question')
    parser.add_argument('--output')
    parser.add_argument('--selection-mode', choices=['auto','user-specified','all'], default='auto')
    parser.add_argument('--max-marks', type=int, help='Explicit automatic candidate limit; user-specified/all never truncate validated proposals.')
    parser.add_argument('--normalize-only', action='store_true', help='Validate and style existing marks; never claim a model selection.')
    args = parser.parse_args()
    if args.catalog:
        print(json.dumps(CATALOG,ensure_ascii=False,indent=2))
        return 0
    if not all((args.payload,args.question,args.output)):
        parser.error('--payload, --question and --output are required unless --catalog is used')
    payload = json.loads(Path(args.payload).read_text(encoding='utf-8'))
    if not isinstance(payload, dict):
        parser.error('payload must be an object')
    output = copy.deepcopy(payload)
    component = output.get('component') if isinstance(output.get('component'), dict) else output
    props = component.get('props') if isinstance(component.get('props'), dict) else component
    symbol = str(props.get('code') or props.get('symbol') or output.get('symbol') or output.get('code') or '').upper()
    period = str(props.get('dataType') or props.get('period') or output.get('period') or '1d')
    rows = component.get('data') if isinstance(component.get('data'), list) else output.get('data', [])
    period_data=component.get('dataByPeriod') or output.get('dataByPeriod') or props.get('dataByPeriod')
    if isinstance(period_data,dict) and isinstance(period_data.get(period),list):
        rows=period_data[period]
    if not symbol or not evidence_rows(rows):
        parser.error('symbol and verified OHLCV evidence are required')
    options = dict(symbol=symbol, period=period, ohlcv=rows, ma_periods=props.get('ma'), market=str(props.get('financialMarket') or ('CN' if re.search(r'\.(SH|SZ|SS|BJ)$', symbol) else 'HK' if symbol.endswith('.HK') else 'US')))
    if args.normalize_only:
        marks = normalize_kline_annotations(props.get('annotations', []), max_marks=None, **options)
        receipt = {'policy': 'jev_vis_router', 'selection': 'verified-proposals', 'modelSelected': False}
    else:
        plan = JevVisualizationRouter().plan_kline_annotations(question=args.question, proposals=props.get('annotations'), language=str(props.get('language') or 'zh-CN'), selection_mode=args.selection_mode, max_marks=args.max_marks, **options)
        marks = plan.annotations
        receipt = {'policy': 'jev_vis_router', 'provider': 'local-laya', 'selection': 'laya' if plan.provider_model else 'no-eligible-candidates', 'modelSelected': bool(plan.provider_model), 'strategy': plan.mark_strategy, 'confidence': plan.confidence, 'model': plan.provider_model}
        receipt.update(candidatePolicy=plan.candidate_policy,candidateTypes=list(plan.candidate_types),candidateCount=plan.candidate_count,selectedTypes=list(dict.fromkeys(mark['type'] for mark in marks)))
    other_periods = [mark for mark in props.get('annotations', []) if isinstance(mark, dict) and mark.get('period') and str(mark['period']) != period]
    diagnostics=[]
    for index,mark in enumerate(props.get('annotations',[])):
        if mark in other_periods:
            continue
        if not normalize_kline_annotations([mark],max_marks=None,**options):
            diagnostics.append({'index':index,'type':str(mark.get('type','')) if isinstance(mark,dict) else '', 'reason':'Unsupported type, wrong identity/period, anchor count, price or exact candle time; not approximated.'})
    if diagnostics:
        receipt['rejected']=diagnostics
    if not marks:
        receipt['warning']='No verified drawing candidates; provide supported types with exact evidence-bound anchors. No substituted geometry.'
    receipt['catalogVersion']=CATALOG['version']
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
