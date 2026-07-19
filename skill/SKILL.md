---
name: speak
description: Toggle voice output (TTS summaries) for the current project, or change the voice
---

# Speech Control (Per-Project)

Controls the claude-speak v2 Stop-hook TTS. Only the `<!-- TTS_SUMMARY ... -->`
block of each response is ever spoken; no marker means silence.

## Usage
```
/speak              # Toggle speech on/off for this project
/speak on           # Enable speech
/speak off          # Disable speech
/speak status       # Show current state and voice
/speak voices       # List recommended voices
/speak voice <name> # Set voice for this project
/speak voice reset  # Reset to default voice
```

## How It Works

Per-project flag files in `~/.claude/projects/<ENCODED>/`:
- `speech-paused` — present = speech paused for this project
- `speech-voice`  — voice name override for this project

Global fallbacks: `~/.claude/speech-paused`, `~/.claude/speech-voice`.
Default voice: `fr-FR-RemyMultilingualNeural`.

`<ENCODED>` = CWD with `:` `\` `/` replaced by `-`.
Example: `/home/user/myapp` → `-home-user-myapp`
Example: `C:\Projects\MyApp` → `C--Projects-MyApp`

Changes take effect on the next response (the hook re-reads config each time).

## Instructions

Determine `<ENCODED>` from the current CWD, then run the matching command.
Use Bash on Linux/macOS, PowerShell on Windows.

### `/speak` (toggle)

Bash:
```bash
F="$HOME/.claude/projects/<ENCODED>/speech-paused"; if [ -f "$F" ]; then rm "$F"; echo ON; else mkdir -p "$(dirname "$F")" && touch "$F"; echo OFF; fi
```

PowerShell:
```powershell
$f="$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused"; if (Test-Path $f) { Remove-Item $f -Force; "ON" } else { New-Item $f -ItemType File -Force | Out-Null; "OFF" }
```

### `/speak on`

Bash: `rm -f "$HOME/.claude/projects/<ENCODED>/speech-paused"`
PowerShell: `Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused" -Force -ErrorAction SilentlyContinue`

### `/speak off`

Bash: `mkdir -p "$HOME/.claude/projects/<ENCODED>" && touch "$HOME/.claude/projects/<ENCODED>/speech-paused"`
PowerShell: `New-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused" -ItemType File -Force | Out-Null`

### `/speak status`

Report Speech ON/OFF (`speech-paused` present = OFF) and the voice
(`speech-voice` project file, else global file, else
`default (fr-FR-RemyMultilingualNeural)`).

### `/speak voices`

Show this table; mention `python3 -m edge_tts --list-voices` for the full list.

| Voice | Language | ID |
|-------|----------|----|
| Rémy (défaut) | FR (multilingue) | `fr-FR-RemyMultilingualNeural` |
| Vivienne | FR (multilingue) | `fr-FR-VivienneMultilingualNeural` |
| Denise | FR | `fr-FR-DeniseNeural` |
| Henri | FR | `fr-FR-HenriNeural` |
| Andrew | EN-US (multilingue) | `en-US-AndrewMultilingualNeural` |
| Ava | EN-US (multilingue) | `en-US-AvaMultilingualNeural` |
| Ryan | EN-GB | `en-GB-RyanNeural` |
| Sonia | EN-GB | `en-GB-SoniaNeural` |

### `/speak voice <name>`

Bash: `mkdir -p "$HOME/.claude/projects/<ENCODED>" && printf '%s' "<VOICE_NAME>" > "$HOME/.claude/projects/<ENCODED>/speech-voice"`
PowerShell: `Set-Content "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-voice" "<VOICE_NAME>" -NoNewline`

### `/speak voice reset`

Bash: `rm -f "$HOME/.claude/projects/<ENCODED>/speech-voice"`
PowerShell: `Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-voice" -Force -ErrorAction SilentlyContinue`

### Response format

Concise, e.g. "Speech for MyApp: ON", "Voice for MyApp set to: fr-FR-DeniseNeural".
