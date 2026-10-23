from copy import deepcopy
from types import SimpleNamespace
import json
import subprocess
import sys
from pathlib import Path

import pytest
from app.jev_kline_annotations import CATALOG, normalize_kline_annotations, build_kline_candidates, requested_annotation_type
from app.jev_visualization_router import JevVisualizationRouter

ROWS=[{'time':1780000000+i*86400,'low':90,'high':140,'close':100+i*.2,'open':100,'volume':1000} for i in range(80)]
CTX=dict(symbol='TEST',period='1d',ohlcv=ROWS)


def mark(kind='rectangle', **extra):
    return {'type':kind,'period':'1d','symbol':'TEST','points':[{'time':ROWS[10]['time'],'price':110},{'time':ROWS[50]['time'],'price':130}],**extra}


@pytest.mark.parametrize('kind',CATALOG['supportedTypes'])
def test_complete_catalog_anchor_contract(kind):
    n=CATALOG['typeDefinitions'][kind]['minPoints']
    points=[{'time':ROWS[10+i*10]['time'],'price':100+i*5} for i in range(n)]
    if kind=='long-position':
        points=[{'time':ROWS[10]['time'],'price':110},{'time':ROWS[10]['time'],'price':100},{'time':ROWS[50]['time'],'price':130}]
    if kind=='short-position':
        points=[{'time':ROWS[10]['time'],'price':110},{'time':ROWS[10]['time'],'price':130},{'time':ROWS[50]['time'],'price':100}]
    if kind=='disjoint-channel':
        points=[{'time':ROWS[10]['time'],'price':100},{'time':ROWS[50]['time'],'price':110},{'time':ROWS[10]['time'],'price':120},{'time':ROWS[50]['time'],'price':130}]
    raw=[mark(kind,points=points,text='Verified range',lineStyle='dotted',lineWidth=3)]
    before=deepcopy(raw)
    result=normalize_kline_annotations(raw,**CTX)
    assert len(result)==1 and len(result[0]['points'])==n
    assert result[0]['lineStyle']=='dotted' and result[0]['lineWidth']==3
    assert raw==before


def test_style_whitelist_and_geometry_requirements():
    raw=mark(lineWidth=100,opacity=float('nan'),fillOpacity=.25,fillColor='#123456',textColor='url(bad)',lineStyle='dashed',levels=[0,.5,1,float('nan'),'bad'],levelColors=['#123456'],style='position:fixed',order={'submit':True})
    result=normalize_kline_annotations([raw],**CTX)[0]
    assert result['lineWidth']==8 and result['fillOpacity']==.25
    assert result['levels']==[0,.5,1] and result['levelColors']==['#123456']
    assert not {'opacity','textColor','style','order'} & result.keys()
    assert not normalize_kline_annotations([mark('long-position',points=[{'time':ROWS[5]['time'],'price':110},{'time':ROWS[5]['time'],'price':120},{'time':ROWS[10]['time'],'price':130}])],**CTX)
    assert not normalize_kline_annotations([mark('fib-retracement',points=[{'time':1,'price':110},{'time':ROWS[5]['time'],'price':120}])],**CTX)
    assert not normalize_kline_annotations([mark('regression-channel',points=[{'time':ROWS[5]['time'],'price':110},{'time':ROWS[5]['time'],'price':120}])],**CTX)


def test_requested_drawings_require_evidence_and_preserve_fib_native_palette():
    assert requested_annotation_type('请画斐波那契回撤')=='fib-retracement'
    assert requested_annotation_type('添加改良希夫干草叉')=='modified-schiff-pitchfork'
    assert requested_annotation_type('讨论一下回归通道')==''
    assert build_kline_candidates(**CTX,requested_type='regression-channel')[0]['points'][0]['time']==ROWS[-60]['time']
    assert not build_kline_candidates(**CTX,requested_type='long-position')
    assert not build_kline_candidates(**CTX,requested_type='segment')  # No confirmed pivots in a monotonic range.
    assert 'color' not in normalize_kline_annotations([mark('fib-retracement')],**CTX)[0]
    assert normalize_kline_annotations([mark('fib-retracement',color='#abcdef')],**CTX)[0]['color']=='#abcdef'


class Include:
    state=None
    def __init__(self,**kwargs): pass
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def system_one(self,**kwargs):
        Include.state=kwargs['state']
        return SimpleNamespace(model='test',answers={'mark_strategy':SimpleNamespace(choice='threshold-reference',confidence=.95),**{key:SimpleNamespace(choice='include',confidence=.95) for key in Include.state['candidates']}})


def test_jev_receives_catalog_and_does_not_truncate_explicit_set():
    proposals=[mark(text=f'Range {i}') for i in range(12)]
    router=JevVisualizationRouter(client_factory=Include)
    plan=router.plan_kline_annotations(question='请画全部区间',proposals=proposals,selection_mode='all',**CTX)
    assert len(plan.annotations)==12
    assert Include.state['drawingCapabilities']==CATALOG
    assert len(router.plan_kline_annotations(question='标记关键范围',proposals=proposals,**CTX).annotations)==3
    assert len(router.plan_kline_annotations(question='请画回归通道',**CTX).annotations)==1
    with pytest.raises(Exception,match='outside the native catalog'):
        router.plan_kline_annotations(question='画江恩箱',**CTX)


def test_cli_direct_invocation_keeps_styles_and_reports_rejections(tmp_path):
    script=Path(__file__).resolve().parents[1]/'app/jev_kline_annotations.py'
    result=subprocess.run([sys.executable,str(script),'--catalog'],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)==CATALOG
    payload={'type':'kline','props':{'code':'TEST','dataType':'1d','annotations':[mark(lineStyle='dashed'),mark('gann-box')]},'dataByPeriod':{'1d':ROWS}}
    source=tmp_path/'in.json';output=tmp_path/'out.json';source.write_text(json.dumps(payload))
    result=subprocess.run([sys.executable,str(script),'--payload',str(source),'--question','画矩形','--output',str(output),'--normalize-only'],text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    data=json.loads(output.read_text())
    assert len(data['props']['annotations'])==1 and data['props']['annotations'][0]['lineStyle']=='dashed'
    assert data['dataByPeriod']==payload['dataByPeriod']
    assert data['jevAnnotationPlan']['rejected'][0]['type']=='gann-box'
    assert data['jevAnnotationPlan']['modelSelected'] is False
