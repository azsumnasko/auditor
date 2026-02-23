# Run Jira analytics using the installed Python (avoids PATH/Store alias issues)
$py = "C:\Users\Nasko\AppData\Local\Programs\Python\Python312\python.exe"
if (-not (Test-Path $py)) {
    Write-Error "Python not found at $py. Install Python 3.12 or update the path in this script."
    exit 1
}
Set-Location $PSScriptRoot
& $py -m pip install -q -r requirements.txt
& $py jira_analytics.py
