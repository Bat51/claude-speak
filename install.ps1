# claude-speak v2 installer (Windows)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tools = "$env:USERPROFILE\.claude\tools"
$Skills = "$env:USERPROFILE\.claude\skills\speak"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found in PATH"
}

$prevEAP = $ErrorActionPreference
$ErrorActionPreference = "Continue"
python -c "import edge_tts" 2>$null
$edgeTtsMissing = ($LASTEXITCODE -ne 0)
$ErrorActionPreference = $prevEAP
if ($edgeTtsMissing) {
    Write-Host "Installing edge-tts..."
    python -m pip install --user edge-tts
}

New-Item -ItemType Directory -Force -Path $Tools, $Skills | Out-Null

# Remove stale v1 links and any existing targets
Remove-Item "$Tools\cc-speak.py", "$Tools\claude-speak.py", "$Tools\speak.py", "$Tools\configure.py", "$Tools\settings.html", "$Skills\SKILL.md" -Force -ErrorAction SilentlyContinue

Copy-Item "$Here\speak.py", "$Here\configure.py", "$Here\settings.html" $Tools -Force
Copy-Item "$Here\skill\SKILL.md" "$Skills\SKILL.md" -Force

python "$Here\merge_hook.py"

Write-Host ""
Write-Host "claude-speak v2 installed."
Write-Host " - Hook: speaks only the <!-- TTS_SUMMARY ... --> block of each response."
Write-Host " - Make sure your global CLAUDE.md contains the TTS summary instructions (see README.md)."
Write-Host " - Settings UI: python $Tools\configure.py"
Write-Host " - In Claude Code: /speak on|off|status|voice <name>"
