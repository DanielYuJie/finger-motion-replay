# 在 PCL2 中搜索并保存一个 Mod
param(
  [Parameter(Mandatory=$true)][string]$Keyword,
  [string]$PickTitle = "",
  [string]$VerFilter = "1.20.1",
  [int]$MaxTry = 3
)

. "$PSScriptRoot\pcl-helper.ps1"

function Set-Text {
  param([int]$X, [int]$Y, [string]$Text)
  [Win]::Click($X, $Y)
  Start-Sleep -Milliseconds 600
  # 清空
  [System.Windows.Forms.SendKeys]::SendWait("^a")
  Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait("{DEL}")
  Start-Sleep -Milliseconds 250
  Set-Clipboard -Value $Text
  Start-Sleep -Milliseconds 250
  [System.Windows.Forms.SendKeys]::SendWait("^v")
  Start-Sleep -Milliseconds 600
}

Write-Host "== 打开 Mod 下载页 =="
Click-Pcl -Name "下载" -Exact | Out-Null
Start-Sleep -Seconds 2
Click-Pcl -Name "Mod" -Exact | Out-Null
Start-Sleep -Seconds 3

# 名称框 (1077,552) 351x28 ；版本框 (1079,589) 327x28
Write-Host "== 填写条件: $Keyword / $VerFilter =="
Set-Text -X 1253 -Y 566 -Text $Keyword
Set-Text -X 1240 -Y 603 -Text $VerFilter

Click-Pcl -Name "搜索" -Exact | Out-Null
Start-Sleep -Seconds 6
Save-PclShot -Path (Join-Path $PSScriptRoot "s-last.png")

# 找目标
$target = $PickTitle
if (-not $target) { $target = $Keyword }

$root = Get-PclRoot
$cond = [System.Windows.Automation.Condition]::TrueCondition
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)

$hit = $null
foreach ($e in $all) {
  if ($e.Current.AutomationId -eq "LabTitle" -or $e.Current.AutomationId -eq "LabTitleRaw") {
    $n = $e.Current.Name
    if ($n -and $n.ToLower().Contains($target.ToLower())) {
      $r = $e.Current.BoundingRectangle
      if ($r.Width -gt 0 -and -not [double]::IsInfinity($r.Y)) {
        $hit = $e; break
      }
    }
  }
}

if (-not $hit) {
  Write-Host "未找到结果: $target"
  Get-PclTree -Max 60
  exit 1
}

$r = $hit.Current.BoundingRectangle
$cx = [int]($r.X + $r.Width/2); $cy = [int]($r.Y + $r.Height/2)
Write-Host "点击结果 '$($hit.Current.Name)' @ ($cx,$cy)"
[Win]::Click($cx, $cy)
Start-Sleep -Seconds 5
Save-PclShot -Path (Join-Path $PSScriptRoot "p-last.png")

# 版本列表中选 1.20.1 的第一条
$root = Get-PclRoot
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
$verHit = $null
foreach ($e in $all) {
  if ($e.Current.AutomationId -eq "LabTitle") {
    $n = $e.Current.Name
    if ($n -and $n -match "1\.20\.1" -and $n -notmatch "NeoForge|Forge 1") {
      $r2 = $e.Current.BoundingRectangle
      if ($r2.Width -gt 0 -and $r2.Y -gt 700) { $verHit = $e; break }
    }
  }
}

if (-not $verHit) {
  Write-Host "未找到 1.20.1 的版本条目"
  Get-PclTree -Max 60
  exit 1
}

$r2 = $verHit.Current.BoundingRectangle
$vx = [int]($r2.X + $r2.Width/2); $vy = [int]($r2.Y + $r2.Height/2)
Write-Host "点击版本 '$($verHit.Current.Name)' @ ($vx,$vy)"
[Win]::Click($vx, $vy)
Start-Sleep -Seconds 5
Save-PclShot -Path (Join-Path $PSScriptRoot "d-last.png")

# 保存对话框：点「保存(S)」
$root = Get-PclRoot
$all = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
foreach ($e in $all) {
  $n = $e.Current.Name
  if ($n -eq "保存(S)" -or $n -eq "保存") {
    $r3 = $e.Current.BoundingRectangle
    if ($r3.Width -gt 0) {
      [Win]::Click([int]($r3.X + $r3.Width/2), [int]($r3.Y + $r3.Height/2))
      Write-Host "已点击保存"
      Start-Sleep -Seconds 5
      break
    }
  }
}
Write-Host "== 完成: $Keyword =="
