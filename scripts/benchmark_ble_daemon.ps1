param(
  [string]$Action = "off",
  [int]$Parallel = 6,
  [int]$DirectIterations = 2,
  [int]$WarmIterations = 3,
  [switch]$VerboseLogs
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Wrapper = "C:\Users\neisan\.local\bin\switchbot-tools.ps1"
$PythonBin = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$DaemonCli = Join-Path $RepoRoot "scripts\switchbot_ble_daemon.py"
$Timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$OutputDir = Join-Path $RepoRoot "benchmark-logs\daemon-$Timestamp"
$LogDir = Join-Path $OutputDir "logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Invoke-Step {
  param(
    [string]$Label,
    [string[]]$Command
  )

  $stdoutPath = Join-Path $LogDir "$Label.stdout.txt"
  $stderrPath = Join-Path $LogDir "$Label.stderr.txt"
  $sw = [System.Diagnostics.Stopwatch]::StartNew()
  $process = Start-Process -FilePath $Command[0] -ArgumentList $Command[1..($Command.Length - 1)] -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -NoNewWindow -PassThru -Wait
  $exitCode = $process.ExitCode
  $sw.Stop()
  [pscustomobject]@{
    label = $Label
    exit_code = $exitCode
    wall_ms = [math]::Round($sw.Elapsed.TotalMilliseconds, 1)
    stdout = $stdoutPath
    stderr = $stderrPath
  }
}

function Stop-DaemonBestEffort {
  try {
    & $PythonBin $DaemonCli stop 1> $null 2> $null
  } catch {
  }
}

$jsonlPath = Join-Path $LogDir "ble.jsonl"
$results = New-Object System.Collections.Generic.List[object]

Stop-DaemonBestEffort

for ($i = 1; $i -le $DirectIterations; $i++) {
  $cmd = @(
    "powershell.exe",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $Wrapper,
    "lights", "--ble", $Action,
    "--parallel", "$Parallel",
    "--no-daemon",
    "--jsonl-path", $jsonlPath
  )
  if ($VerboseLogs) {
    $cmd += "--verbose"
  }
  $results.Add((Invoke-Step -Label "direct-$i" -Command $cmd))
}

Stop-DaemonBestEffort

$coldCmd = @(
  "powershell.exe",
  "-NoProfile",
  "-ExecutionPolicy", "Bypass",
  "-File", $Wrapper,
  "lights", "--ble", $Action,
  "--parallel", "$Parallel",
  "--jsonl-path", $jsonlPath
)
if ($VerboseLogs) {
  $coldCmd += "--verbose"
}
$results.Add((Invoke-Step -Label "daemon-cold" -Command $coldCmd))

for ($i = 1; $i -le $WarmIterations; $i++) {
  $warmCmd = @(
    "powershell.exe",
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", $Wrapper,
    "lights", "--ble", $Action,
    "--parallel", "$Parallel",
    "--jsonl-path", $jsonlPath
  )
  if ($VerboseLogs) {
    $warmCmd += "--verbose"
  }
  $results.Add((Invoke-Step -Label "daemon-warm-$i" -Command $warmCmd))
}

$statusCmd = @($PythonBin, $DaemonCli, "status")
$results.Add((Invoke-Step -Label "daemon-status" -Command $statusCmd))
Stop-DaemonBestEffort

$summary = [pscustomobject]@{
  action = $Action
  parallel = $Parallel
  direct_iterations = $DirectIterations
  warm_iterations = $WarmIterations
  created_at = (Get-Date).ToString("o")
  jsonl_path = $jsonlPath
  results = $results
}

$summaryPath = Join-Path $OutputDir "summary.json"
$summary | ConvertTo-Json -Depth 6 | Set-Content -Path $summaryPath -Encoding UTF8
$summary | ConvertTo-Json -Depth 6
