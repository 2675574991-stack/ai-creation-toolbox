# 打包 AssetNest 为单文件 exe
# 依赖：Python 3.10+（建议 3.12）、pip 可安装 pyinstaller 与 pillow
# 用法：.\build.ps1  或  .\build.ps1 -Python C:\Python312\python.exe
param(
  [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = $Python
try {
  & $py --version | Out-Null
} catch {
  throw "找不到 Python：$py。请安装 Python 3.10+ 并加入 PATH，或用 -Python 指定 python.exe。"
}

& $py -m pip install --disable-pip-version-check -q pyinstaller pillow
& $py -m PyInstaller --noconfirm --clean --onefile --windowed `
  --name AssetNest `
  --icon 'assets\assetnest.ico' `
  --add-data 'web;web' `
  --add-data 'assets;assets' `
  app.py

if (Test-Path 'dist\AssetNest.exe') {
  Write-Host '构建完成：dist\AssetNest.exe' -ForegroundColor Green
  (Get-Item 'dist\AssetNest.exe').Length / 1MB
} else {
  throw '构建失败，请检查上面的日志。'
}
