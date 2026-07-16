# nc_visual_cli 

[![tests](https://github.com/maomao3334/nc_visual_cli/actions/workflows/tests.yml/badge.svg)](https://github.com/maomao3334/nc_visual_cli/actions/workflows/tests.yml)

`nc_visual_cli` 是面向消防应急研判的离线风场态势报告生成器。它扫描文件夹第一层的 NetCDF 文件，生成可直接双击打开的动态 HTML、稳定 manifest JSON 和批次清单。

核心约束：

- 风速和实际吹向始终由 `U_wind/V_wind` 推导。
- 缺测保持透明，不解释为无风，不补造中间时次。
- 低邻点支持和无逐格质量信息必须显式呈现。
- 风险扇区只表示理论平流方向与距离，不是扩散模型、撤离边界或安全区。
- HTML 不依赖 CDN、在线地图、`fetch()` 或任何网络服务。

## 获取

- Windows 便携版：[GitHub Releases](https://github.com/maomao3334/nc_visual_cli/releases/latest)
- 源码仓库：[maomao3334/nc_visual_cli](https://github.com/maomao3334/nc_visual_cli)
- Python 3.12 Windows x64 离线环境包：在同一 Release 下载 `*-offline-env.zip`

```powershell
git clone https://github.com/maomao3334/nc_visual_cli.git
cd nc_visual_cli
```

## 快速使用

便携版解压后：

```powershell
.\nc_visual_cli.exe G:\data\nc
```

完整示例：

```powershell
.\nc_visual_cli.exe G:\data\nc `
  --output G:\reports `
  --events G:\data\events.geojson `
  --assets G:\data\assets.csv `
  --boundary G:\data\task_boundary.geojson `
  --risk-horizon-min 20 `
  --time-window-min 60 `
  --json
```

源码开发：

```powershell
uv sync --frozen --extra dev
uv run python -m pytest
.\.venv\Scripts\nc_visual_cli.exe demo_data --output reports
```

`uv.lock` 固定源码开发和 CI 环境。离线环境 ZIP 包含项目 wheel、全部运行时 wheel、精确 requirements、逐文件哈希和离线安装脚本。便携 EXE ZIP 仍不要求目标电脑安装 Python。

## 命令契约

```text
nc_visual_cli <folder>
  [--output PATH]
  [--events PATH]
  [--assets PATH]
  [--boundary PATH]
  [--risk-horizon-min 20]
  [--time-window-min 60]
  [--max-event-wind-distance-km 10]
  [--timezone Asia/Shanghai]
  [--theme dark|light|auto]
  [--latest-only]
  [--json]
```

默认批量处理全部兼容 NC。`--latest-only` 仅处理变量和质量字段最完整、同条件下修改时间最新的一份。

`--json` 保证 stdout 只有一个 JSON 对象。日志写入 stderr。退出码固定为：

| 退出码 | 含义 |
|---:|---|
| 0 | 全部成功 |
| 1 | 未预期内部错误 |
| 2 | 参数、路径或侧车文件错误 |
| 3 | NetCDF 数据契约不兼容或全部处理失败 |
| 4 | 批处理中部分文件失败 |

## 输入要求

NetCDF 至少需要一维 `lat/lon` 坐标和包含这两个维度的 `U_wind/V_wind`。支持变量维度顺序变化，并识别常见的 `latitude/longitude/u_wind/v_wind` 别名。

推荐提供：

- `time`、`height`
- `wind_interpolation_quality`
- `wind_effective_neighbor_count`
- `wind_nearest_observation_distance_deg`
- `observation_count`
- `source_mix`、`coord_status_mix`

无 `time` 时生成单帧静态报告；无 `height` 时显示“高度基准未知”；无质量字段时显示“无逐格质量信息”。

事件文件必填字段：`id,name,type,lon,lat,start_time`。设备文件必填字段：`id,name,type,lon,lat`。GeoJSON 必须使用 Point geometry；CSV 使用 UTF-8 或 UTF-8 BOM。任一记录非法都会返回具体行号，不静默跳过。

## 输出

```text
reports/
  <stem>_report.html
  <stem>_manifest.json
  batch_manifest.json
```

当稀疏风场载荷超过 20 MB 时自动输出：

```text
reports/
  <stem>_report/
    index.html
    chunks/data_001.js
  <stem>_manifest.json
  batch_manifest.json
```

分块模式通过本地 `<script>` 注册数据，可在 `file://` 下工作，不调用 `fetch()`。

## 报告操作

- 上一时次、播放/暂停、下一时次和 1x/2x/5x 速度控制真实存在的时次。
- 地图、剖面、覆盖图、风玫瑰和短报文共享时间与高度状态。
- 地图箭头表示风实际吹向，即烟羽可能的平流方向。
- 点击地图格点查看 U/V、风速、吹向、质量、邻点和最近观测距离。
- 点击剖面或覆盖图可直接选择时间高度位置。
- 地图支持滚轮、按钮和双指缩放；地图聚焦时上下键切换有效格点，左右键切换时次，空格播放。
- URL hash 保存时次、高度、主题、方向口径和选中格点。
- 浅色主题与打印样式适用于截图和纸面研判。

## 验证

```powershell
python -m pytest
python scripts\build_release.py
python scripts\build_offline_environment.py
```

发行脚本分别构建便携 EXE ZIP 和 CPython 3.12/Windows x64 离线环境 ZIP，并为两者生成 `.sha256` 文件。

## 许可

源码使用 MIT License。内置边界来自 Natural Earth 公共领域数据，详见 `THIRD_PARTY_NOTICES.md`。

参与开发请阅读 [CONTRIBUTING.md](CONTRIBUTING.md)。
