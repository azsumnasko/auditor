# Generate Jira dashboard HTML (uses same Python path as run_jira_analytics.ps1)
$py = "C:\Users\Nasko\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Python not found at $py. Install Python 3.12 or update the path in this script."
    exit 1
}
Set-Location $PSScriptRoot
# Optional: pass a JSON path, e.g. .\run_generate_dashboard.ps1 jira_analytics_2026-02-18T15-57-07Z.json
$jsonPath = $args[0]
if ($jsonPath) { & $py generate_dashboard.py $jsonPath } else { & $py generate_dashboard.py }
Write-Host "Open jira_dashboard.html in your browser."
