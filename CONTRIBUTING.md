# 贡献指南

感谢参与 `nc_visual_cli`。提交改动前，请确保修改保持离线报告的数据可追溯性和应急研判语义。

## 开发环境

项目固定使用 CPython 3.12：

```powershell
uv sync --frozen --extra dev
uv run python -m pytest
```

## 提交要求

- 风速、吹向必须继续由 `U_wind/V_wind` 推导。
- 不得把缺测解释为无风，也不得补造不存在的时次。
- 低支持、质量缺失和理论平流限制必须持续可见。
- HTML 必须保持离线可用，不引入 CDN、远程字体、地图服务或 `fetch()`。
- 修复数据契约或 CLI 行为时，请增加对应回归测试。

提交 Pull Request 时，请说明行为变化、验证命令和可能影响的输入数据类型。
