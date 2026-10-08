#Requires -Version 5.1

param(
  [int]$Port = 8123,
  [switch]$NoBrowser,
  [switch]$Reinstall,
  [switch]$SkipInstall,
  [switch]$Setup,
  [switch]$Kill,
  [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Url = "http://127.0.0.1:$Port"
$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"

function Fail($msg) { Write-Host "[start-ui] $msg" -ForegroundColor Red; exit 1 }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
  ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
  Write-Host "[start-ui] 需要管理员权限 (建 tun 隧道必需), 正在提权重开..." -ForegroundColor Yellow
  $args = "-NoProfile -ExecutionPolicy Bypass -File `"$($MyInvocation.MyCommand.Path)`" -Port $Port"
  if ($NoBrowser) { $args += " -NoBrowser" }
  if ($Reinstall) { $args += " -Reinstall" }
  if ($SkipInstall) { $args += " -SkipInstall" }
  if ($Setup) { $args += " -Setup" }
  if ($Kill) { $args += " -Kill" }
  if ($Force) { $args += " -Force" }
  Start-Process powershell -ArgumentList $args -Verb RunAs
  exit 0
}
Write-Host "[start-ui] 已是管理员, 跳过提权."

if (-not (Test-Path $VenvPy)) {
  Write-Host "[start-ui] 建 .venv ..."
  try { py -3 -m venv .venv } catch { python -m venv .venv }
  if (-not (Test-Path $VenvPy)) { Fail "建 .venv 失败, 先装 Python 3.10+ (勾选 Add to PATH)." }
}

$needInstall = $false
if ($SkipInstall) {
  Write-Host "[start-ui] 跳过依赖安装 (-SkipInstall)"
} elseif ($Reinstall) {
  $needInstall = $true
} else {
  & $VenvPy -c "import pymobiledevice3, yaml, geopy, coloredlogs, qh3" 2>$null
  if ($LASTEXITCODE -ne 0) { $needInstall = $true }
}
if ($needInstall) {
  Write-Host "[start-ui] 装依赖 (pip install -r requirements.txt) ..."
  & (Join-Path $Root ".venv\Scripts\pip.exe") install -r requirements.txt
  if ($LASTEXITCODE -ne 0) { Fail "依赖安装失败. 先装 iTunes (Apple 官方版, 非微软商店版) 并打开过一次." }
} else {
  Write-Host "[start-ui] 依赖已就绪, 跳过安装 (-Reinstall 可强制重装)"
}
if ($Setup) {
  Write-Host "[start-ui] 依赖就绪 (venv: .venv). 启动: .\start-ui.ps1 (管理员 PowerShell)"
  exit 0
}

function Get-PortReport($p) {
  $raw = & $VenvPy -m util.ports check $p 2>$null
  return ($raw | ConvertFrom-Json)
}
function Kill-SameService($rep) {
  $pids = $rep.pids
  if (-not $pids -or $pids.Count -eq 0) { Write-Host "[start-ui] 找不到可杀的进程 (可能已退出)."; return $true }
  Write-Host "[start-ui] 一键 kill 同类服务: taskkill $($pids -join ' ') ..."
  $killRaw = & $VenvPy -m util.ports kill @pids 2>$null
  Write-Host $killRaw
  Start-Sleep -Seconds 1
  $again = Get-PortReport $Port
  if ($again.open) { Write-Host "[start-ui] kill 后端口 $Port 仍被占用, 手动查: netstat -ano | findstr $Port" -ForegroundColor Red; return $false }
  Write-Host "[start-ui] 端口 $Port 已释放."
  return $true
}
$rep = Get-PortReport $Port
if ($rep.open) {
  if ($rep.pids) { Write-Host "[start-ui] 端口 $Port 已被占用 (pid $($rep.pids -join ', '))." -ForegroundColor Yellow }
  else { Write-Host "[start-ui] 端口 $Port 已被占用." -ForegroundColor Yellow }
  foreach ($pid in $rep.pids) {
    $cmd = $rep.cmds."$pid"
    if ($cmd) { Write-Host "  pid $pid : $cmd" }
  }
  Write-Host "  判断: $($rep.detail)"
  $same = $rep.same
  if ($same) { Write-Host "  这是上次没退出的同类服务 (本项目 WebUI), 可以一键 kill." }
  else { Write-Host "  这不是本项目 WebUI, 不要 kill (可能是别的服务)." -ForegroundColor Yellow }
  if ($Kill) {
    if (-not $same) { Fail "非同类占用, 拒绝 kill. 换端口: .\start-ui.ps1 -Port $($Port + 1)" }
    if (-not (Kill-SameService $rep)) { exit 1 }
    exit 0
  }
  if ($Force) {
    if (-not $same) { Fail "非同类占用, 拒绝 -Force. 换端口: .\start-ui.ps1 -Port $($Port + 1)" }
    if (-not (Kill-SameService $rep)) { exit 1 }
  } else {
    if ($same) {
      Write-Host "  一键清理: .\start-ui.ps1 -Port $Port -Kill   (只杀同类)"
      Write-Host "  或覆盖重启: .\start-ui.ps1 -Port $Port -Force"
      $ans = Read-Host "  现在 kill 并继续启动? [y/N]"
      if ($ans -match '^(y|Y|yes)$') {
        if (-not (Kill-SameService $rep)) { exit 1 }
      } else {
        Write-Host "  已取消. 换端口: .\start-ui.ps1 -Port $($Port + 1)"
        exit 1
      }
    } else {
      Write-Host "  换端口: .\start-ui.ps1 -Port $($Port + 1)"
      Write-Host "  查谁占着: netstat -ano | findstr $Port"
      exit 1
    }
  }
} elseif ($Kill) {
  Write-Host "[start-ui] 端口 $Port 本来就空闲, 无需 kill."
  exit 0
}

Write-Host "[start-ui] WebUI 启动中 -> $Url (停止: 关此窗口前先点页面 ■ 停止, 否则定位不清)"
$proc = Start-Process -FilePath $VenvPy -ArgumentList "webui.py", "--port", "$Port" `
  -NoNewWindow -PassThru -WorkingDirectory $Root
$ok = $false
for ($i = 0; $i -lt 30; $i++) {
  try {
    Invoke-WebRequest -UseBasicParsing "$Url/api/run/state" -TimeoutSec 3 | Out-Null
    $ok = $true; break
  } catch {}
  if ($proc.HasExited) { break }
  Start-Sleep -Milliseconds 500
}
if (-not $ok) {
  Write-Host "[start-ui] WebUI 在 15s 内没起来 (端口 $Port)." -ForegroundColor Red
  if (-not $proc.HasExited) { Write-Host "  进程还在但健康检查不通, 看看是不是防火墙/代理." }
  exit 1
}
Write-Host "[start-ui] WebUI 就绪 -> $Url"
if (-not $NoBrowser) { Start-Process $Url }

try {
  $proc.WaitForExit()
} finally {
  if (-not $proc.HasExited) {
    Write-Host "[start-ui] 正在停止 WebUI (定位可能需重启手机恢复)..."
    $proc.Kill()
  }
}
