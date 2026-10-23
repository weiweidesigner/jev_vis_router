import json
import math
from types import SimpleNamespace

from app.jev_kline_annotations import build_kline_candidates, normalize_kline_annotations
from app.jev_visualization_router import JevVisualizationRouter

ROWS=[{'time':1780000000+i*86400,'open':100+i*.15+7*math.sin(i*.4)-.2,
       'close':100+i*.15+7*math.sin(i*.4),'low':99+i*.15+7*math.sin(i*.4),
       'high':101+i*.15+7*math.sin(i*.4),'volume':10000+i*10} for i in range(100)]
CTX=dict(symbol='FIXTURE',period='1d',ohlcv=ROWS)


class Select:
    state={}
    selected={'regression-channel','fib-retracement','rectangle'}
    strategy='threshold-reference'
    def __init__(self,**kwargs):pass
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def system_one(self,**kwargs):
        Select.state=kwargs['state']
        return SimpleNamespace(model='fixture-model',answers={
            'mark_strategy':SimpleNamespace(choice=self.strategy,confidence=.95),
            **{key:SimpleNamespace(choice='include' if mark['type'] in self.selected else 'omit',confidence=.95)
               for key,mark in Select.state['candidates'].items()}})


def test_latest_pool_offers_all_evidence_eligible_families_without_type_request():
    marks=build_kline_candidates(**CTX)
    types={mark['type'] for mark in marks}
    assert {'segment','parallel-channel','regression-channel','fib-retracement','rectangle','date-price-range','fib-extension','pitchfork'}<=types
    assert not types & {'horizontal-line','callout','buy','sell','emoji','long-position'}
    assert all(mark['basis'] and mark['candidatePolicy']=='native-v2-auto' for mark in marks)
    assert len(normalize_kline_annotations(marks,max_marks=None,**CTX))==len(marks)
    assert all(point['time'] in {row['time'] for row in ROWS} for mark in marks for point in mark['points'])


def test_old_upstream_marks_supplement_rather_than_block_latest_pool():
    old=[{'type':'horizontal-line','points':[{'time':ROWS[-1]['time'],'price':110}],'text':'Old support'}]
    result=JevVisualizationRouter(client_factory=Select).plan_kline_annotations(question='分析近期走势与风险',proposals=old,**CTX)
    assert {'regression-channel','fib-retracement','rectangle'}<={m['type'] for m in result.annotations}
    assert 'horizontal-line' in result.candidate_types
    assert {'parallel-channel','fib-retracement','regression-channel'}<=set(result.candidate_types)
    assert result.candidate_count==len(Select.state['candidates'])
    assert result.candidate_policy=='native-v2-auto'
    compact={key:value for key,value in Select.state.items() if key!='candidates'}
    assert len(json.dumps(compact,ensure_ascii=False))<4000


def test_normal_analysis_does_not_require_naming_a_drawing_tool():
    result=JevVisualizationRouter(client_factory=Select).plan_kline_annotations(question='分析近期走势',**CTX)
    assert {m['type'] for m in result.annotations}==Select.selected
    assert result.provider_model=='fixture-model'


def test_no_mark_remains_possible_for_default_analysis():
    class Abstain(Select):strategy='no-mark'
    assert not JevVisualizationRouter(client_factory=Abstain).plan_kline_annotations(question='分析近期走势',**CTX).annotations
    assert not JevVisualizationRouter(client_factory=Abstain).plan_kline_annotations(question='分析近期高低点与风险',**CTX).annotations


def test_automatic_upstream_proposals_are_not_forced_past_model_omission():
    class Omit(Select):selected=set()
    old=[{'type':'horizontal-line','points':[{'time':ROWS[-1]['time'],'price':110}],'text':'Old support'}]
    assert not JevVisualizationRouter(client_factory=Omit).plan_kline_annotations(question='分析支撑压力',proposals=old,**CTX).annotations


def test_explicit_user_set_is_not_automatically_expanded():
    old=[{'type':'horizontal-line','points':[{'time':ROWS[-1]['time'],'price':100+i}],'text':str(i)} for i in range(10)]
    for mode in ('all','user-specified'):
        result=JevVisualizationRouter(client_factory=Select).plan_kline_annotations(question='标注这些位置',selection_mode=mode,proposals=old,**CTX)
        assert len(result.annotations)==10 and result.candidate_types==('horizontal-line',)


def test_default_sparse_selection_does_not_stack_redundant_trend_drawings():
    class All(Select):selected={'segment','parallel-channel','regression-channel','pitchfork','fib-retracement','rectangle'}
    result=JevVisualizationRouter(client_factory=All).plan_kline_annotations(question='分析近期走势',**CTX)
    assert len(result.annotations)==3
    assert sum(m['type'] in {'segment','parallel-channel','regression-channel','pitchfork'} for m in result.annotations)==1


def test_insufficient_or_flat_evidence_does_not_invent_structural_candidates():
    assert not build_kline_candidates(**{**CTX,'ohlcv':ROWS[:1]})
    flat=[{**r,'close':100,'high':100,'low':100,'open':100} for r in ROWS]
    assert not build_kline_candidates(**{**CTX,'ohlcv':flat})
    monotonic=[{**r,'close':100+i,'high':101+i,'low':99+i} for i,r in enumerate(ROWS)]
    assert not {m['type'] for m in build_kline_candidates(**{**CTX,'ohlcv':monotonic})}&{'segment','parallel-channel','pitchfork','fib-extension'}
