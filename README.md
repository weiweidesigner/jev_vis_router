# Local Laya Visualization Router

可视化路由模块。通过本地开源 Laya，从调用方提供的组件候选中选择主图、可选辅助图，并返回分析角度、视觉编码、证据策略与标记策略。

## 安装

建议 Python 3.11+，在仓库根目录执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## 调用

在仓库根目录运行 Python，或将仓库根目录加入模块搜索路径：

```python
from dataclasses import asdict
from app.jev_visualization_router import JevVisualizationRouter

router = JevVisualizationRouter()  # 从进程环境读取凭据
result = router.route(
    question="展示每月营收趋势",
    candidates=[
        {"script": "line_chart.py", "family": "generic-chart", "label": "折线图", "description": "展示时间趋势"},
        {"script": "pie.py", "family": "generic-chart", "label": "饼图", "description": "展示构成比例"},
    ],
)
print(asdict(result))
```

真实请求由本地 Laya 服务提供，不需要 API Key。环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `LAYA_DECISION_URL` | `http://127.0.0.1:8791/predict` | 本地 Laya 决策接口 |
| `LAYA_VISUAL_MODEL` | `convaiinnovations/laya-multilingual` | 开源模型标识 |
| `LAYA_VISUAL_TIMEOUT_SECONDS` | `90` | 本地推理超时 |
| `LAYA_VISUAL_PRIMARY_MIN_CONFIDENCE` | `0.35` | 主图置信度阈值 |
| `LAYA_VISUAL_SUPPORTING_MIN_CONFIDENCE` | `0.55` | 辅助图置信度阈值 |

候选组件必须由调用方提供，建议描述包含组件 Schema 的相关语义。路由仅提供决策；数据获取、Schema 验证、图表渲染与最终解释由宿主执行。

返回值 `JevVisualizationDecision` 包含选中脚本、主/辅助图、置信度、分析角度、视觉编码、证据与标记策略等。允许 `no-visual`；辅助图重复或置信度不足时被省略。主图置信度不足、凭据缺失、网络失败、候选无效时抛出 `JevVisualizationRouterError`，由调用方处理回退。

## 验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试使用模拟本地客户端，无需启动模型或外部请求。只包含可视化路由，不包含模型路由、工具活动路由或宿主应用。

## K线标记规划与统一策略

`router.plan_kline_annotations(question=..., symbol=..., period=..., ohlcv=..., proposals=..., ma_periods=[20,50,200])` 返回 `JevKlineAnnotationPlan`。数据必须由调用方先取得；本仓库不取行情、不绘图。本地 Laya 只能选择已经通过标的、周期、日期、价格范围校验的候选坐标，低置信度及 `no-mark` 返回空标记。候选可来自已有分析结果；未传候选时只从已提供行情计算区间高低点、近20根支撑压力、最新收盘及有足够样本的均线。不能生成未来价格、未知事件或缺失数据的均线。

返回原生 `annotations`：支持水平/垂直线、双点线段/射线、买卖点、文字与气泡。统一进行去重、周期绑定、语义配色与 MA 色一致性；显式十六进制颜色优先。买卖点按调用方市场采用相同涨跌色约定。渲染器负责像素坐标、标签避碰、图例、移动端交互。

独立 CLI：

```bash
python app/jev_kline_annotations.py --payload verified-kline.json --question "标记支撑压力" --output marked-kline.json
```

输出保留原行情，增加 `annotations` 和 `jevAnnotationPlan` 规划来源。`--normalize-only` 只校验和配色已有标记，明确记录 `modelSelected:false`，适用于已验证的缓存案例；不会伪造一次 Laya 模型推理。

### Native drawings v2

`python app/jev_kline_annotations.py --catalog` prints the native renderer's mirrored public capability contract (43 types, anchor counts, style whitelist, formula semantics, explicit unsupported families). This metadata is also passed to Laya with validated candidates. The router remains independent: it never imports component code, fetches prices or draws pixels.

Supported families include lines, channels/OLS regression, pitchfork variants, Fibonacci retracement/three-point extension/channel/timezone/fan, geometric paths/shapes, measurements, long/short **scenarios**, notes and emoji. Exact candle times and prices in the verified range are mandatory. Requested fib retracement and regression candidates can be derived from actual OHLCV; confirmed pivots are required for trend lines, pitchforks and fib extensions. Arbitrary geometry and position scenarios require explicit evidence-bound proposals. Missing evidence yields no mark, not substituted geometry.

Styles survive validation: line width/dash/opacity, fill/color/opacity, font size/text color, level ratios/colors, label visibility and supported extensions. Unsupported CSS/HTML and order fields are never forwarded. `--selection-mode user-specified|all` preserves every validated supplied mark; automatic mode defaults to three, or `--max-marks N`. Rejected inputs are reported in `jevAnnotationPlan.rejected`.

Gann, synthetic future candles, external media/posts and the remaining advanced Fibonacci tools are explicitly **not implemented**. Volume-at-price must use the actual volume-profile component/data source, not an invented OHLCV allocation. See the catalog's `unsupportedTypes` rather than assuming parity with the full TradingView drawing suite.
