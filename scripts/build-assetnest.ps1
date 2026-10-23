# 构建 AssetNest 单文件程序，并放到工具箱的 vendor 目录
param(
  [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$module = Join-Path $root 'modules\assetnest'
$src = Join-Path $module 'dist\AssetNest.exe'
$dstDir = Join-Path $root 'vendor\AssetNest'
$dst = Join-Path $dstDir 'AssetNest.exe'

& (Join-Path $module 'build.ps1') -Python $Python

if (-not (Test-Path $src)) { throw "AssetNest 构建失败，找不到：$src" }
if (-not (Test-Path $dstDir)) { New-Item -ItemType Directory -Path $dstDir | Out-Null }
Copy-Item $src $dst -Force
Write-Host "已复制到：$dst" -ForegroundColor Green
