# 安全说明

## 支持范围

当前维护最新 Release（v1.2.x）。

## 本地服务

- 素材巢会在 `127.0.0.1` 上启动一个本地 HTTP 服务，端口随机。
- 服务没有登录/鉴权，**不要把它暴露到公网**，也不要做端口转发。
- 工具箱关闭时会结束素材巢进程；如异常残留，可在任务管理器结束 `AssetNest.exe`。

## 数据

- 应用不联网、无遥测、无账号。
- 数据保存在 `%LOCALAPPDATA%\AICreationBox-OSS` 与 `%LOCALAPPDATA%\AssetNest`。
- 不要在不信任的目录中运行素材巢，或把项目指向不可信的网络共享。

## 报告漏洞

请通过 GitHub Security Advisories 私密报告，不要先开公开 Issue。

请附上：

- 版本号 / commit
- Windows 版本
- 复现步骤
- 影响范围

## 第三方

WebView2、Python、PyInstaller、Pillow、Tcl/Tk 的安全问题请同时参考对应上游项目的公告。
