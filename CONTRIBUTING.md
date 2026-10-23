# 贡献指南

感谢参与。提交前请先确认：**不要引入无权分发的第三方代码、文案、图片或安装包。**

## 开发环境

- Windows 10/11 x64
- .NET Framework 4.8（系统自带 `csc.exe`）
- Python 3.10+（建议 3.12）
- Microsoft Edge WebView2 Runtime

## 构建

```powershell
powershell -ExecutionPolicy Bypass -File scripts\fetch-webview2.ps1
python -m pip install pyinstaller pillow
powershell -ExecutionPolicy Bypass -File scripts\build-assetnest.ps1
powershell -ExecutionPolicy Bypass -File build.ps1 -SkipAssetNest
```

产物在 `dist\AI创作工具箱`。

## 代码风格

- C#：.NET Framework 4.8 兼容，避免使用 C# 6+ 语法（`csc.exe` 版本限制）
- 前端：原生 HTML/CSS/JS，不引入构建步骤
- Python：PEP 8，标准库优先
- 提交信息用中文或英文均可，描述清楚动机

## Pull Request

1. Fork 并新建分支
2. 保持改动聚焦
3. 说明测试方式（Windows 版本、操作路径、截图）
4. 确认没有提交 `dist/`、`lib/`、`vendor/`、`*.exe`、`*.dll`

## 不要提交

- H3 / 提示词框架工作台的代码或文案
- 任何第三方安装包、字体、素材
- 个人路径、密钥、账号信息
- 构建产物和压缩包

## 许可证

贡献的代码默认按本项目 MIT License 授权。
