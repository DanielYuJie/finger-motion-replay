# Start the local ORCA stack: bridge (ingest) + sim (MuJoCo) + a data driver.
#
# Why this file exists: every path under this repo contains a space
# ("Personal Portfolio Area"), and Start-Process does NOT quote arguments for you.
# Passing an unquoted script path silently fails with:
#     python.exe: can't open file 'D:\\Personal': [Errno 2] No such file or directory
# Centralising the quoting here removes that whole class of mistake.
#
# ASCII-only on purpose: Windows PowerShell reads BOM-less .ps1 as ANSI, so
# non-ASCII characters break the parser. See orca-link/README.md for the notes.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File run_stack.ps1
#   ... -Driver gestures        # synthetic wave instead of the webcam
#   ... -Driver none            # bridge + sim only
#   ... -NoSim                  # no MuJoCo window (e.g. headless check)
#   ... -Restart                # kill previously started instances first

param(
    [string]$Python = 'C:\Users\q2669\.conda\envs\orca-teleop\python.exe',
    [ValidateSet('webcam', 'gestures', 'none')][string]$Driver = 'webcam',
    [switch]$NoSim,
    [switch]$Restart,
    [double]$SimFps = 30,
    [double]$CamFps = 15
)

$ErrorActionPreference = 'Continue'
$Here = $PSScriptRoot
$LogDir = Join-Path $Here 'logs'
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Start-Py {
    # NOTE: the parameter must NOT be named $Args. PowerShell treats $Args as an
    # automatic variable (the unbound parameter list of a function), so a
    # parameter of that name silently fails to bind: $Args stays empty and every
    # argument is dropped. Symptom seen in practice -- the processes started, but
    # the real command lines were missing everything:
    #     python.exe -u "...\orca_bridge.py"          (no --host 0.0.0.0, no --port)
    #     python.exe -u "...\webcam_drive.py"         (no --show)
    # Which meant the bridge fell back to 127.0.0.1-only and the preview window
    # never opened. Same class of trap as $pid / $R / $HOME in PowerShell.
    param([string]$Script, [string[]]$PyArgs, [string]$Name)
    $log = Join-Path $LogDir "$Name.log"
    Remove-Item -LiteralPath $log, "$log.err" -ErrorAction SilentlyContinue
    # The script path is wrapped in explicit quotes: it contains spaces.
    $argv = @('-u', "`"$Script`"") + $PyArgs
    $p = Start-Process -FilePath $Python -ArgumentList $argv -WorkingDirectory $Here `
        -PassThru -RedirectStandardOutput $log -RedirectStandardError "$log.err" -WindowStyle Hidden
    Write-Host ("    {0,-10} pid={1,-7} log={2}" -f $Name, $p.Id, $log)
    return $p
}

if ($Restart) {
    Write-Host "==> stopping previously started instances"
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'orca_bridge\.py|sim_drive\.py|webcam_drive\.py|drive_gestures\.py' } |
        ForEach-Object {
            Write-Host ("    kill pid {0}" -f $_.ProcessId)
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
    Start-Sleep -Seconds 2
}

if (-not (Test-Path $Python)) { Write-Host "python not found: $Python"; exit 1 }

Write-Host "==> bridge: orca_bridge.py --sink print --host 0.0.0.0 --port 8766"
$bridge = Start-Py -Script (Join-Path $Here 'orca_bridge.py') -Name 'bridge' -PyArgs @('--sink', 'print', '--host', '0.0.0.0', '--port', '8766')
Start-Sleep -Seconds 3
try {
    $h = Invoke-RestMethod 'http://127.0.0.1:8766/health' -TimeoutSec 5
    Write-Host ("    health ok: joints={0}" -f $h.joint_count)
}
catch { Write-Host "    health FAILED: $($_.Exception.Message)" }

$sim = $null
if (-not $NoSim) {
    Write-Host "==> sim: sim_drive.py --render human (a MuJoCo window will open)"
    $sim = Start-Py -Script (Join-Path $Here 'sim_drive.py') -Name 'sim' `
        -PyArgs @('--render', 'human', '--fps', "$SimFps", '--seconds', '0', '--print-every', '3')
    Start-Sleep -Seconds 10
    $sp = Get-Process -Id $sim.Id -ErrorAction SilentlyContinue
    if ($sp) { Write-Host ("    alive; window='{0}'" -f $sp.MainWindowTitle) }
    else { Write-Host "    exited early - check logs\sim.log.err" }
}

if ($Driver -eq 'webcam') {
    Write-Host "==> driver: webcam_drive.py --show (live camera -> joints -> bridge -> sim)"
    $drv = Start-Py -Script (Join-Path $Here 'webcam_drive.py') -Name 'webcam' `
        -PyArgs @('--show', '--fps', "$CamFps", '--print-every', '3')
    Write-Host "    note: mediapipe import + model load takes ~8-10s before the first POST"
}
elseif ($Driver -eq 'gestures') {
    Write-Host "==> driver: drive_gestures.py --pattern wave (synthetic)"
    $drv = Start-Py -Script (Join-Path $Here 'drive_gestures.py') -Name 'gestures' `
        -PyArgs @('--pattern', 'wave', '--seconds', '0', '--hz', '30')
}
else {
    Write-Host "==> driver: none (bridge + sim only; POST to 8766/update yourself)"
}

Write-Host ""
Write-Host "==> running"
Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'orca_bridge\.py|sim_drive\.py|webcam_drive\.py|drive_gestures\.py' } |
    ForEach-Object {
        $proc = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
        Write-Host ("    pid {0,-7} {1,6} MB  {2}" -f $proc.Id, [math]::Round($proc.WorkingSet64 / 1MB, 0), $proc.MainWindowTitle)
    }
Write-Host ""
Write-Host "    stop all:  powershell -File run_stack.ps1 -Restart -Driver none -NoSim"
Write-Host "    or:        Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { `$_.CommandLine -match 'orca_bridge|sim_drive|webcam_drive|drive_gestures' } | ForEach-Object { Stop-Process -Id `$_.ProcessId -Force }"
Write-Host "    logs:      $LogDir"
