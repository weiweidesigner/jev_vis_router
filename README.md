# JEV Visualization Router

Aime Chart 的独立可视化路由模块。通过 TypeSafe JEV，从调用方提供的组件候选中选择主图、可选辅助图，并返回分析角度、视觉编码、证据策略与标记策略。

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

真实请求需配置 `TYPESAFE_API_KEY`。其他环境变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `TYPESAFE_MODEL` | `jev-latest` | JEV 模型 |
| `TYPESAFE_TIMEOUT_SECONDS` | `20` | 请求超时 |
| `TYPESAFE_VISUAL_PRIMARY_MIN_CONFIDENCE` | `0.35` | 主图置信度阈值 |
| `TYPESAFE_VISUAL_SUPPORTING_MIN_CONFIDENCE` | `0.55` | 辅助图置信度阈值 |

候选组件必须由调用方提供，建议描述包含组件 Schema 的相关语义。路由仅提供决策；数据获取、Schema 验证、图表渲染与最终解释由宿主执行。

返回值 `JevVisualizationDecision` 包含选中脚本、主/辅助图、置信度、分析角度、视觉编码、证据与标记策略等。允许 `no-visual`；辅助图重复或置信度不足时被省略。主图置信度不足、凭据缺失、网络失败、候选无效时抛出 `JevVisualizationRouterError`，由调用方处理回退。

## 验证

```bash
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试使用模拟 SDK 客户端，无需 API 密钥或外部请求。只包含可视化路由，不包含模型路由、工具活动路由或宿主应用。
