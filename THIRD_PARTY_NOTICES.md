# 第三方组件与商标说明

本项目采用 MIT License，但下列第三方组件/内容遵循它们自己的许可证。

## Microsoft Edge WebView2

- 组件：Microsoft.Web.WebView2 SDK 1.0.4258.31、WebView2 Runtime
- 用途：桌面宿主的内嵌浏览器
- 版权：Microsoft Corporation
- 许可：Microsoft 软件许可条款（允许随应用分发）
- 获取：https://www.nuget.org/packages/Microsoft.Web.WebView2
- 运行时：https://developer.microsoft.com/microsoft-edge/webview2/

构建时通过 `scripts/fetch-webview2.ps1` 从 NuGet 还原，仓库本身不提交这些 DLL。

## Python 运行时与打包工具（仅素材巢二进制涉及）

素材巢通过 PyInstaller 打包为单文件 exe 时，会包含：

- Python 3.12 — PSF License
- PyInstaller — GPL-2.0-or-later，附 bootloader exception
- Pillow — HPND License
- Tcl/Tk — BSD-style License

对应版权与许可证随各项目发布。若只使用源码运行（`python app.py`），则不需要分发这些二进制。

## H3 提示词医生 / 提示词框架工作台

- **本项目不包含、不分发**这两个模块的代码、文案或安装包。
- 它们是第三方内容，版权归各自作者所有。
- 本项目不提供、不授权它们；如需使用，请自行取得授权。
- “H3”“MiniMax”等名称/商标归各自权利人所有，本项目与它们无隶属关系。

## 素材巢（AssetNest）

- 产品构想、需求与项目方向由本项目作者提出。
- 代码在作者需求下使用 AI 辅助编写。
- 以 MIT License 随本项目发布（见根目录 LICENSE）。

## 图标

- `assets/app.ico` 为本项目生成。
- `modules/assetnest/assets/assetnest.ico` 为素材巢模块图标。
