$ErrorActionPreference = 'Stop'
$projectPath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw 'Environnement Python introuvable : configurez .venv avant de continuer.'
}
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument '-m unified_schedule.scheduled_sync' -WorkingDirectory $projectPath
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(1)) -RepetitionInterval (New-TimeSpan -Hours 1)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 50)
$userIdentity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $userIdentity -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'Unified Schedule - Hourly Sync' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Actualisation ADE et Workforce vers Google Calendar toutes les heures.' -Force | Out-Null
Write-Output 'Tâche installée : première exécution dans une minute, puis toutes les heures lorsque votre session Windows est ouverte.'
Write-Output "Journal : $projectPath\data\logs\sync.log"
