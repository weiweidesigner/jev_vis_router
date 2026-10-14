from types import SimpleNamespace
from copy import deepcopy
import pytest
from app.jev_kline_annotations import normalize_kline_annotations, build_kline_candidates, kline_annotation_style
from app.jev_visualization_router import JevVisualizationRouter, JevVisualizationRouterError

ROWS = [{'time': 1780000000 + i * 86400, 'open': 100+i, 'low': 99+i, 'high': 102+i, 'close': 101+i, 'volume': 1000} for i in range(30)]
CTX = dict(symbol='JPM', period='1d', ohlcv=ROWS, ma_periods=[20, 50, 200])

def proposal(**changes):
    return {'symbol':'JPM','type':'horizontal','time':ROWS[-1]['time'],'price':120,'text':'支撑',**changes}

@pytest.mark.parametrize('changes', [dict(symbol='AMD'),dict(period='1w'),dict(time=1),dict(price=float('nan')),dict(price=1000),dict(price=-1),dict(type='unknown')])
def test_rejects_unsupported_coordinates_or_identity(changes):
    assert normalize_kline_annotations([proposal(**changes)], **CTX)==()

def test_supports_native_lines_periods_deduplication_and_does_not_mutate():
    raw=[proposal(type='segment',points=[{'time':ROWS[2]['time'],'price':101},{'time':ROWS[-1]['time'],'price':120}])]
    original=deepcopy(raw)
    result=normalize_kline_annotations(raw*2,**CTX)
    assert len(result)==1 and result[0]['period']=='1d' and len(result[0]['points'])==2
    assert raw==original

def test_semantic_colors_match_ma_identity_and_market_direction():
    colors=[kline_annotation_style({'type':'horizontal-line','text':text},ma_periods=[20,50,200])[0] for text in ['支撑','MA200','压力 MA20','压力 MA50','52周高点']]
    assert colors==['#fb923c','#38bdf8','#fbbf24','#8b5cf6','#f472b6']
    assert kline_annotation_style({'type':'buy'},market='CN')[0]=='#ff2f57'
    assert kline_annotation_style({'type':'buy'},market='US')[0]=='#00b899'
    assert kline_annotation_style({'text':'MA20','color':'#123456'},ma_periods=[20])[0]=='#123456'

def test_candidates_are_computed_from_real_candles_and_available_ma_windows():
    raw=build_kline_candidates(**{k:v for k,v in CTX.items() if k!='market'})
    assert any(m['text']=='MA20' and m['price']==pytest.approx(sum(r['close'] for r in ROWS[-20:])/20) for m in raw)
    assert not any(m['text']=='MA200' for m in raw)
    assert min(m['price'] for m in raw)>=min(r['low'] for r in ROWS)

class Client:
    strategy='threshold-reference'
    confidence=.9
    def __init__(self,**kw): pass
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def system_one(self,**kwargs):
        type(self).state=kwargs['state']
        return SimpleNamespace(model='test-jev',answers={
            'mark_strategy':SimpleNamespace(choice=self.strategy,confidence=self.confidence),
            'mark_1':SimpleNamespace(choice='mark-1',confidence=.9),
            'mark_2':SimpleNamespace(choice='mark-1',confidence=.9),
            'mark_3':SimpleNamespace(choice='invented-mark',confidence=.9)})

def test_jev_selects_only_validated_candidate_ids_and_keeps_receipt():
    result=JevVisualizationRouter(api_key='test',client_factory=Client).plan_kline_annotations(question='标记支撑位',proposals=[proposal(),proposal(price=1000)],**CTX)
    assert len(result.annotations)==1 and result.annotations[0]['source']=='jev-kline-plan'
    assert result.annotations[0]['points'][0]['price']==120 and result.provider_model=='test-jev'
    assert len(Client.state['candidates'])==1

@pytest.mark.parametrize('strategy,confidence',[('no-mark',.9),('threshold-reference',.2)])
def test_no_mark_and_low_confidence_do_not_force_annotations(strategy,confidence):
    class Abstain(Client): pass
    Abstain.strategy=strategy;Abstain.confidence=confidence
    assert JevVisualizationRouter(api_key='test',client_factory=Abstain).plan_kline_annotations(question='标记',proposals=[proposal()],**CTX).annotations==()

def test_missing_credentials_fail_explicitly():
    with pytest.raises(JevVisualizationRouterError):
        JevVisualizationRouter(api_key='').plan_kline_annotations(question='标记',**CTX)
