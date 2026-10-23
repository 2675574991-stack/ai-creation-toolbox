# 从 NuGet 还原 WebView2 SDK（构建宿主需要）
param(
  [string]$Version = '1.0.4258.31'
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$lib = Join-Path $root 'lib'
$core = Join-Path $lib 'Microsoft.Web.WebView2.Core.dll'

if (Test-Path $core) {
  Write-Host "WebView2 SDK 已存在：$lib" -ForegroundColor Green
  return
}

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$tmp = Join-Path $env:TEMP ('wv2_' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$nupkg = Join-Path $tmp 'webview2.nupkg'
$url = "https://api.nuget.org/v3-flatcontainer/microsoft.web.webview2/$($Version.ToLower())/microsoft.web.webview2.$Version.nupkg"

Write-Host "下载 WebView2 SDK $Version ..."
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $nupkg -TimeoutSec 120

Add-Type -AssemblyName System.IO.Compression.FileSystem
$extract = Join-Path $tmp 'pkg'
[System.IO.Compression.ZipFile]::ExtractToDirectory($nupkg, $extract)

if (-not (Test-Path $lib)) { New-Item -ItemType Directory -Path $lib | Out-Null }
Copy-Item (Join-Path $extract 'lib\net462\Microsoft.Web.WebView2.Core.dll') $lib -Force
Copy-Item (Join-Path $extract 'lib\net462\Microsoft.Web.WebView2.WinForms.dll') $lib -Force
Copy-Item (Join-Path $extract 'runtimes\win-x64\native\WebView2Loader.dll') $lib -Force

Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "WebView2 SDK 已还原到：$lib" -ForegroundColor Green
