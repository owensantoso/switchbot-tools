param(
  [string]$Action = "warm-white",
  [int]$Brightness = 60,
  [int]$Parallel = 4,
  [int]$ScanTimeout = 5,
  [int]$CachedIterations = 3,
  [int]$DiscoverIterations = 1,
  [string]$OutputDir = "",
  [switch]$SkipScan
)

$ErrorActionPreference = "Stop"

if (-not $OutputDir) {
  $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
  $OutputDir = Join-Path (Join-Path $PSScriptRoot "..") "benchmark-logs\$stamp"
}

$OutputDir = [System.IO.Path]::GetFullPath($OutputDir)
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$RepoRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$PythonBin = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$BleCli = Join-Path $RepoRoot "scripts\switchbot_ble.py"
if (-not (Test-Path -LiteralPath $PythonBin)) {
  throw "Python environment not found at $PythonBin"
}
if (-not (Test-Path -LiteralPath $BleCli)) {
  throw "BLE CLI not found at $BleCli"
}

function Get-ActionArgs {
  param(
    [string]$RequestedAction,
    [int]$RequestedBrightness,
    [int]$RequestedParallel
  )

  switch ($RequestedAction) {
    "warm-white" { return @("all", "temp", "--value", "2700", "--brightness", "$RequestedBrightness", "--parallel", "$RequestedParallel") }
    "cool-white" { return @("all", "temp", "--value", "5500", "--brightness", "$RequestedBrightness", "--parallel", "$RequestedParallel") }
    "daylight" { return @("all", "temp", "--value", "6500", "--brightness", "$RequestedBrightness", "--parallel", "$RequestedParallel") }
    "gold" { return @("all", "color", "--r", "255", "--g", "190", "--b", "0", "--brightness", "$RequestedBrightness", "--parallel", "$RequestedParallel") }
    "purple" { return @("all", "color", "--r", "128", "--g", "0", "--b", "128", "--brightness", "$RequestedBrightness", "--parallel", "$RequestedParallel") }
    "on" { return @("all", "on", "--parallel", "$RequestedParallel") }
    "off" { return @("all", "off", "--parallel", "$RequestedParallel") }
    default { throw "Unsupported benchmark action '$RequestedAction'" }
  }
}

function Invoke-BenchmarkCase {
  param(
    [string]$Name,
    [string[]]$CommandArgs
  )

  $logPath = Join-Path $OutputDir "$Name.jsonl"
  if (Test-Path -LiteralPath $logPath) {
    Remove-Item -LiteralPath $logPath -Force
  }

  $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
  & $PythonBin $BleCli @CommandArgs --verbose --jsonl-path $logPath
  $exitCode = $LASTEXITCODE
  $stopwatch.Stop()

  for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if (Test-Path -LiteralPath $logPath) {
      break
    }
    Start-Sleep -Milliseconds 100
  }

  [pscustomobject]@{
    Name = $Name
    ExitCode = $exitCode
    WallMs = [math]::Round($stopwatch.Elapsed.TotalMilliseconds, 1)
    LogPath = $logPath
    Args = @($CommandArgs)
  }
}

function Get-ElapsedDelta {
  param(
    [object[]]$Events,
    [string]$StartEvent,
    [string]$FinishEvent
  )

  $start = $Events | Where-Object { $_.event -eq $StartEvent } | Select-Object -First 1
  $finish = $Events | Where-Object { $_.event -eq $FinishEvent } | Select-Object -Last 1
  if ($null -eq $start -or $null -eq $finish) {
    return $null
  }
  return [math]::Round(([double]$finish.elapsed_ms - [double]$start.elapsed_ms), 1)
}

function Summarize-Run {
  param(
    [object]$Run
  )

  $events = Get-Content -LiteralPath $Run.LogPath | ForEach-Object { $_ | ConvertFrom-Json }
  $final = $events | Where-Object { $_.event -in @("all_lights_finished", "control_finished", "scan_finished", "all_lights_failed", "control_failed", "scan_failed") } | Select-Object -Last 1

  $deviceActionDurations = New-Object System.Collections.Generic.List[double]
  $deviceStartLookup = @{}
  foreach ($event in $events) {
    if ($event.event -eq "device_action_started") {
      $key = "$($event.device_name)|$($event.address)|$($event.action)"
      $deviceStartLookup[$key] = [double]$event.elapsed_ms
      continue
    }
    if ($event.event -eq "device_action_finished") {
      $key = "$($event.device_name)|$($event.address)|$($event.action)"
      if ($deviceStartLookup.ContainsKey($key)) {
        $deviceActionDurations.Add([math]::Round(([double]$event.elapsed_ms - [double]$deviceStartLookup[$key]), 1))
      }
    }
  }

  $taskDurations = @(
    $events |
      Where-Object { $_.event -eq "device_task_finished" -and $_.PSObject.Properties.Name -contains "duration_ms" } |
      ForEach-Object { [double]$_.duration_ms }
  )

  $waitDurations = @(
    $events |
      Where-Object { $_.event -eq "device_task_acquired" -and $_.PSObject.Properties.Name -contains "waited_ms" } |
      ForEach-Object { [double]$_.waited_ms }
  )

  [pscustomobject]@{
    name = $Run.Name
    exit_code = $Run.ExitCode
    wall_ms = $Run.WallMs
    total_elapsed_ms = if ($final) { [double]$final.elapsed_ms } else { $null }
    parallel = (($events | Where-Object { $_.event -eq "all_lights_started" } | Select-Object -First 1).parallel)
    discover_ms = Get-ElapsedDelta -Events $events -StartEvent "discover_started" -FinishEvent "discover_finished"
    cache_load_ms = Get-ElapsedDelta -Events $events -StartEvent "cache_load_started" -FinishEvent "cache_load_finished"
    cache_save_ms = Get-ElapsedDelta -Events $events -StartEvent "cache_save_started" -FinishEvent "cache_save_finished"
    scan_discover_ms = Get-ElapsedDelta -Events $events -StartEvent "scan_discover_started" -FinishEvent "scan_discover_finished"
    avg_device_action_ms = if ($deviceActionDurations.Count) { [math]::Round((($deviceActionDurations | Measure-Object -Average).Average), 1) } else { $null }
    max_device_action_ms = if ($deviceActionDurations.Count) { [math]::Round((($deviceActionDurations | Measure-Object -Maximum).Maximum), 1) } else { $null }
    avg_device_task_ms = if ($taskDurations.Count) { [math]::Round((($taskDurations | Measure-Object -Average).Average), 1) } else { $null }
    max_device_task_ms = if ($taskDurations.Count) { [math]::Round((($taskDurations | Measure-Object -Maximum).Maximum), 1) } else { $null }
    avg_wait_ms = if ($waitDurations.Count) { [math]::Round((($waitDurations | Measure-Object -Average).Average), 1) } else { $null }
    max_wait_ms = if ($waitDurations.Count) { [math]::Round((($waitDurations | Measure-Object -Maximum).Maximum), 1) } else { $null }
    failures = if ($final -and $final.PSObject.Properties.Name -contains "failures") { [int]$final.failures } else { 0 }
    log_path = $Run.LogPath
  }
}

$runs = New-Object System.Collections.Generic.List[object]

if (-not $SkipScan) {
  $runs.Add((Invoke-BenchmarkCase -Name "scan" -CommandArgs @("scan", "--timeout", "$ScanTimeout")))
}

$actionArgs = Get-ActionArgs -RequestedAction $Action -RequestedBrightness $Brightness -RequestedParallel $Parallel

for ($i = 1; $i -le $DiscoverIterations; $i++) {
  $runs.Add((Invoke-BenchmarkCase -Name ("discover-{0:d2}" -f $i) -CommandArgs @($actionArgs + @("--discover"))))
}

for ($i = 1; $i -le $CachedIterations; $i++) {
  $runs.Add((Invoke-BenchmarkCase -Name ("cached-{0:d2}" -f $i) -CommandArgs @($actionArgs)))
}

$summary = @($runs | ForEach-Object { Summarize-Run -Run $_ })
$summaryPath = Join-Path $OutputDir "summary.json"
$summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $summaryPath -Encoding utf8

Write-Host ""
Write-Host "BLE benchmark summary"
Write-Host "Output directory: $OutputDir"
Write-Host ""
$summary | Format-Table name, exit_code, parallel, wall_ms, total_elapsed_ms, discover_ms, cache_load_ms, avg_device_action_ms, avg_device_task_ms, avg_wait_ms, failures -AutoSize
Write-Host ""
Write-Host "Summary JSON: $summaryPath"
