# PCL2 界面自动化辅助脚本
Add-Type -AssemblyName UIAutomationClient,UIAutomationTypes,System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  public struct RECT { public int L,T,R,B; }
  public const uint LEFTDOWN = 0x0002, LEFTUP = 0x0004;
  public static void Click(int x, int y) {
    SetCursorPos(x, y);
    System.Threading.Thread.Sleep(90);
    mouse_event(LEFTDOWN, 0, 0, 0, IntPtr.Zero);
    System.Threading.Thread.Sleep(60);
    mouse_event(LEFTUP, 0, 0, 0, IntPtr.Zero);
  }
}
"@

function Get-PclProcess {
  Get-Process -Name "Plain Craft Launcher 2" -ErrorAction SilentlyContinue | Select-Object -First 1
}

function Get-PclRoot {
  $p = Get-PclProcess
  if (-not $p) { return $null }
  [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
}

function Focus-Pcl {
  $p = Get-PclProcess
  if (-not $p) { return $false }
  [Win]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [Win]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 400
  $true
}

function Get-PclTree {
  param([int]$Max = 60)
  $root = Get-PclRoot
  if (-not $root) { Write-Host "PCL 未运行"; return }
  $cond = [System.Windows.Automation.Condition]::TrueCondition
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
  $i = 0
  foreach ($e in $all) {
    $n = $e.Current.Name
    if ($n -and $n.Trim().Length -gt 0) {
      if ($i -ge $Max) { break }
      $r = $e.Current.BoundingRectangle
      "{0,3} [{1}] '{2}'  autoId={3}  @({4},{5}) {6}x{7}" -f `
        $i, $e.Current.ControlType.ProgrammaticName.Replace('ControlType.',''), $n, `
        $e.Current.AutomationId, [int]$r.X, [int]$r.Y, [int]$r.Width, [int]$r.Height
      $i++
    }
  }
  "total named descendants: $($all.Count)"
}

function Find-PclElement {
  param([string]$Name, [switch]$Exact)
  $root = Get-PclRoot
  if (-not $root) { return $null }
  $cond = [System.Windows.Automation.Condition]::TrueCondition
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
  foreach ($e in $all) {
    $n = $e.Current.Name
    if (-not $n) { continue }
    if ($Exact) { if ($n -eq $Name) { return $e } }
    else { if ($n -like "*$Name*") { return $e } }
  }
  $null
}

function Click-Pcl {
  param([string]$Name, [switch]$Exact, [int]$Index = 0)
  if (-not (Focus-Pcl)) { Write-Host "PCL 未运行"; return $false }

  $root = Get-PclRoot
  $cond = [System.Windows.Automation.Condition]::TrueCondition
  $all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)

  $hits = @()
  foreach ($e in $all) {
    $n = $e.Current.Name
    if (-not $n) { continue }
    if ($Exact) { if ($n -eq $Name) { $hits += $e } }
    else { if ($n -like "*$Name*") { $hits += $e } }
  }

  if ($hits.Count -eq 0) { Write-Host "未找到元素: $Name"; return $false }
  if ($Index -ge $hits.Count) { Write-Host "索引越界: $Name ($Index/$($hits.Count))"; return $false }

  $e = $hits[$Index]
  $r = $e.Current.BoundingRectangle
  if ($r.Width -le 0 -or $r.Height -le 0) { Write-Host "元素不可见: $Name"; return $false }

  $x = [int]($r.X + $r.Width / 2)
  $y = [int]($r.Y + $r.Height / 2)
  Write-Host "点击 '$($e.Current.Name)' @ ($x,$y)  命中数=$($hits.Count)"
  [Win]::Click($x, $y)
  Start-Sleep -Milliseconds 700
  $true
}

function Type-Pcl {
  param([string]$Text)
  Focus-Pcl | Out-Null
  [System.Windows.Forms.SendKeys]::SendWait($Text)
  Start-Sleep -Milliseconds 400
}

function Press-Pcl {
  param([string]$Key)
  Focus-Pcl | Out-Null
  [System.Windows.Forms.SendKeys]::SendWait($Key)
  Start-Sleep -Milliseconds 400
}

function Save-PclShot {
  param([string]$Path = "pcl-window.png")
  $p = Get-PclProcess
  if (-not $p) { return }
  $r = New-Object Win+RECT
  [Win]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
  $w = $r.R - $r.L; $h = $r.B - $r.T
  if ($w -le 0 -or $h -le 0) { return }
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
  $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "screenshot -> $Path"
}
