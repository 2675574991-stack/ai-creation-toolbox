param(
  [switch]$SkipAssetNest
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$csc = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319\csc.exe'
$outDir = Join-Path $root 'dist\AI创作工具箱'
$exe = Join-Path $outDir 'AI创作工具箱.exe'
$assetExe = Join-Path $root 'vendor\AssetNest\AssetNest.exe'
$webViewDll = Join-Path $root 'lib\Microsoft.Web.WebView2.WinForms.dll'

if (-not (Test-Path $csc)) { throw "找不到 csc.exe：$csc（需要 .NET Framework 4.8）" }

if (-not (Test-Path $webViewDll)) {
  & (Join-Path $root 'scripts\fetch-webview2.ps1')
}

if (-not (Test-Path $assetExe)) {
  if ($SkipAssetNest) {
    throw "缺少 $assetExe。请先运行 scripts\build-assetnest.ps1，或去掉 -SkipAssetNest。"
  }
  & (Join-Path $root 'scripts\build-assetnest.ps1')
}

if (-not (Test-Path $outDir)) { New-Item -ItemType Directory -Path $outDir | Out-Null }

$cscArgs = @(
  '/nologo', '/target:winexe', '/platform:x64', '/codepage:65001', '/optimize+',
  ('/out:' + $exe),
  ('/win32icon:' + (Join-Path $root 'assets\app.ico')),
  ('/win32manifest:' + (Join-Path $root 'src\app.manifest')),
  '/reference:System.dll',
  '/reference:System.Core.dll',
  '/reference:System.Drawing.dll',
  '/reference:System.Windows.Forms.dll',
  '/reference:System.Web.Extensions.dll',
  ('/reference:' + (Join-Path $root 'lib\Microsoft.Web.WebView2.Core.dll')),
  ('/reference:' + (Join-Path $root 'lib\Microsoft.Web.WebView2.WinForms.dll')),
  (Join-Path $root 'src\AssemblyInfo.cs'),
  (Join-Path $root 'src\Host.cs')
)

& $csc $cscArgs
if ($LASTEXITCODE -ne 0) { throw "编译失败，exit=$LASTEXITCODE" }

Copy-Item (Join-Path $root 'lib\Microsoft.Web.WebView2.Core.dll') $outDir -Force
Copy-Item (Join-Path $root 'lib\Microsoft.Web.WebView2.WinForms.dll') $outDir -Force
Copy-Item (Join-Path $root 'lib\WebView2Loader.dll') $outDir -Force
Copy-Item (Join-Path $root 'assets\app.ico') $outDir -Force
Copy-Item (Join-Path $root '使用说明.txt') $outDir -Force

$vendorDest = Join-Path $outDir 'vendor'
if (Test-Path $vendorDest) { Remove-Item $vendorDest -Recurse -Force }
Copy-Item (Join-Path $root 'vendor') $vendorDest -Recurse -Force

$webDest = Join-Path $outDir 'web'
if (Test-Path $webDest) { Remove-Item $webDest -Recurse -Force }
Copy-Item (Join-Path $root 'web') $webDest -Recurse -Force

Write-Host "构建完成：$exe" -ForegroundColor Green
