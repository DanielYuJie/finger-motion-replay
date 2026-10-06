# Minecraft 游戏窗口控制辅助
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class MC {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int c);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr h, ref POINT p);
  public struct RECT { public int L,T,R,B; }
  public struct POINT { public int X,Y; }
  public const uint LD=0x0002, LU=0x0004, WHEEL=0x0800, RD=0x0008, RU=0x0010;
  public static void Click(int x,int y){ SetCursorPos(x,y); System.Threading.Thread.Sleep(140);
    mouse_event(LD,0,0,0,IntPtr.Zero); System.Threading.Thread.Sleep(90); mouse_event(LU,0,0,0,IntPtr.Zero); }
  public static void RightClick(int x,int y){ SetCursorPos(x,y); System.Threading.Thread.Sleep(140);
    mouse_event(RD,0,0,0,IntPtr.Zero); System.Threading.Thread.Sleep(90); mouse_event(RU,0,0,0,IntPtr.Zero); }
  public static void Move(int x,int y){ SetCursorPos(x,y); }
  public static void Wheel(int dy){ mouse_event(WHEEL,0,0,(uint)dy,IntPtr.Zero); }
}
"@

function Get-McProcess {
  Get-Process -Name java -ErrorAction SilentlyContinue |
    Where-Object { $_.MainWindowTitle -match "Minecraft" } | Select-Object -First 1
}

function Focus-Mc {
  $p = Get-McProcess
  if (-not $p) { Write-Host "未找到 Minecraft 窗口"; return $false }
  [MC]::ShowWindow($p.MainWindowHandle, 9) | Out-Null
  [MC]::SetForegroundWindow($p.MainWindowHandle) | Out-Null
  Start-Sleep -Milliseconds 500
  $true
}

function Get-McRect {
  $p = Get-McProcess
  if (-not $p) { return $null }
  $r = New-Object MC+RECT
  [MC]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
  $r
}

# 相对游戏窗口内的坐标点击（含标题栏偏移）
function Click-Mc {
  param([int]$X, [int]$Y)
  Focus-Mc | Out-Null
  $r = Get-McRect
  [MC]::Click($r.L + $X, $r.T + $Y)
  Start-Sleep -Milliseconds 600
}

function Save-McShot {
  param([string]$Path = "mc-shot.png")
  Focus-Mc | Out-Null
  Start-Sleep -Milliseconds 700
  $r = Get-McRect
  if (-not $r) { return }
  $w = $r.R - $r.L; $h = $r.B - $r.T
  if ($w -le 0 -or $h -le 0) { Write-Host "窗口尺寸异常"; return }
  $bmp = New-Object System.Drawing.Bitmap($w, $h)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($r.L, $r.T, 0, 0, $bmp.Size)
  $bmp.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose(); $bmp.Dispose()
  Write-Host "shot -> $Path  (${w}x${h} @ $($r.L),$($r.T))"
}

# 发送游戏内聊天命令（自动打开聊天框，输入，回车）
function Send-McCommand {
  param([string]$Command)
  Focus-Mc | Out-Null
  [System.Windows.Forms.SendKeys]::SendWait("t")
  Start-Sleep -Milliseconds 450
  Set-Clipboard -Value $Command
  Start-Sleep -Milliseconds 150
  [System.Windows.Forms.SendKeys]::SendWait("^v")
  Start-Sleep -Milliseconds 350
  [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
  Start-Sleep -Milliseconds 500
  Write-Host "cmd: $Command"
}

# 键盘操作游戏
function Key-Mc {
  param([string]$Key, [int]$Delay = 400)
  Focus-Mc | Out-Null
  [System.Windows.Forms.SendKeys]::SendWait($Key)
  Start-Sleep -Milliseconds $Delay
}

Add-Type -AssemblyName System.Windows.Forms
