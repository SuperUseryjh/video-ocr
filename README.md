# 视频截取 + OCR 识别器

基于 PySide6 的桌面工具：预览本地视频、设置起止时间并导出片段、框选画面区域、按固定间隔执行 OCR，以及导出识别结果 CSV。

## 安装与启动

使用 Python 3.10 或更高版本：

```powershell
py -3.13 -m pip install -r requirements.txt
py -3.13 -m video_ocr
```

视频片段导出依赖 FFmpeg。OCR 首次运行会初始化 RapidOCR 模型。

## 内嵌 FFmpeg

支持将 FFmpeg 随项目或打包后的程序一同发布。下载与系统架构对应的 FFmpeg 发行版后，将可执行文件放入项目根目录的 `bin/`：

```text
bin/
└── ffmpeg.exe
```

程序优先使用 `bin/ffmpeg.exe`；如果不存在，再回退到系统 `PATH` 中的 `ffmpeg`。`bin/ffmpeg.exe` 已在 `.gitignore` 中排除，发布时请连同对应发行版的许可证文件一并分发。

## 自动发布与更新

推送与 [version.py](file:///d:/GitHub/tmp/video_ocr/version.py) 一致的标签（例如版本为 `0.1.0` 时推送 `v0.1.0`），会触发 GitHub Actions 构建 Windows x64 目录型应用包，并将 ZIP、校验文件及更新清单推送到 `SuperUseryjh/static` 的 `video-ocr/` 路径。对应下载与更新清单地址为 `https://static.yaoonion.fun/video-ocr/`。

在源仓库的 Actions Secrets 中配置 `STATIC_REPO_PAT`。该 PAT 只需对 `SuperUseryjh/static` 具有 Contents 读写权限；不要将 PAT 写入源码、工作流或客户端。客户端仅在打包后的 `.exe` 中自动检查更新，也可通过“检查更新”手动触发；下载包会进行 SHA-256 校验后再安装。

## 使用方式

1. 点击“打开视频”，选择视频文件。
2. 在时间轴定位画面，使用“设为起点/终点”确定需处理的片段。
3. 在预览画面拖拽，限定 OCR 区域；没有框选时识别整帧。
4. 设置采样间隔，点击“识别选定范围”，完成后可导出 CSV。
5. 点击“导出片段”生成 MP4 文件；此方式为无重编码截取，边界会对齐到附近关键帧。

## 项目结构

```text
video_ocr/
├── __main__.py    # 模块化启动入口
├── app.py         # Qt 应用创建
├── frame_view.py  # 视频画面预览与区域框选
├── models.py      # OCR 结果数据模型
├── utils.py       # 时间、图像和 CSV 工具函数
└── workers.py     # OCR 与 FFmpeg 后台任务
bin/               # 可选内嵌的 FFmpeg 可执行文件
main.py            # 主窗口与界面交互编排
```

## License

GNU GPL v3
