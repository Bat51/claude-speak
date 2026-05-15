---
name: speak
description: Toggle voice output (text-to-speech) on or off for the current project, list voices, or change voice
---

# Speech Control (Per-Project)

Control the background text-to-speech voice output for the current project.

## Usage
```
/speak              # Toggle speech on/off for this project
/speak on           # Enable speech
/speak off          # Disable speech
/speak status       # Check current status, voice, and intro mode
/speak voices       # List available voices
/speak voice <name> # Set voice for this project
/speak voice reset  # Reset to default voice
/speak snippet on   # Also read the first sentence before the TTS summary
/speak snippet off  # Stop reading the first sentence
/speak preamble on  # Also read the entire first paragraph before the TTS summary
/speak preamble off # Stop reading the first paragraph
```

`snippet` and `preamble` are mutually exclusive: turning one on automatically
turns the other off. Both are disabled by default — only the TTS summary block
is spoken. These options have no effect on responses without a TTS summary
marker (those are spoken in full as before).

## How It Works

The speech system uses per-project files in `~/.claude/projects/<project-dir>/`:
- `speech-paused`   — when this file exists, speech is paused for this project
- `speech-voice`    — contains the voice name override for this project
- `speech-snippet`  — when present, the first sentence is spoken before the summary
- `speech-preamble` — when present, the entire first paragraph is spoken before the summary

The project directory name is derived from the CWD by replacing `:` `\` `/` with `-`.
Example: `C:\Projects\MyApp` → `C--Projects-MyApp`
Example: `/home/user/myapp` → `-home-user-myapp`

## Available Voices (Top Picks)

| Voice | Gender | Accent | ID |
|-------|--------|--------|----|
| Guy | Male | US | `en-US-GuyNeural` |
| Andrew | Male | US | `en-US-AndrewMultilingualNeural` |
| Ryan | Male | UK | `en-GB-RyanNeural` |
| Aria | Female | US | `en-US-AriaNeural` |
| Jenny | Female | US | `en-US-JennyNeural` |
| Sonia | Female | UK | `en-GB-SoniaNeural` |

For the full list, run: `python3 -m edge_tts --list-voices`

## Instructions

When this skill is invoked, determine the current project directory and encoded name:
- CWD example: `C:\Projects\MyApp` → Encoded: `C--Projects-MyApp`
- CWD example: `/home/user/myapp` → Encoded: `-home-user-myapp`
- Config dir: `~/.claude/projects/<ENCODED>/`

### `/speak` (no args) — Toggle

**Windows (PowerShell):**
```powershell
$flagFile = "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused"
if (Test-Path $flagFile) {
    Remove-Item $flagFile -Force
    # Speech is now ON
} else {
    New-Item $flagFile -ItemType File -Force | Out-Null
    # Speech is now OFF
}
```

**Linux/macOS (Bash):**
```bash
FLAG_FILE="$HOME/.claude/projects/<ENCODED>/speech-paused"
if [ -f "$FLAG_FILE" ]; then
    rm "$FLAG_FILE"
    # Speech is now ON
else
    touch "$FLAG_FILE"
    # Speech is now OFF
fi
```

### `/speak on`

**Windows (PowerShell):**
```powershell
Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused" -Force -ErrorAction SilentlyContinue
```

**Linux/macOS (Bash):**
```bash
rm -f "$HOME/.claude/projects/<ENCODED>/speech-paused"
```

### `/speak off`

**Windows (PowerShell):**
```powershell
New-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-paused" -ItemType File -Force | Out-Null
```

**Linux/macOS (Bash):**
```bash
mkdir -p "$HOME/.claude/projects/<ENCODED>"
touch "$HOME/.claude/projects/<ENCODED>/speech-paused"
```

### `/speak status`
Check `speech-paused`, `speech-voice`, `speech-snippet`, and `speech-preamble`
files. Report:
- Speech: ON/OFF
- Voice: <current voice or "default (en-US-GuyNeural)">
- Intro: <"preamble" | "snippet" | "none">

**Windows (PowerShell):**
```powershell
$configDir = "$env:USERPROFILE\.claude\projects\<ENCODED>"
$paused = Test-Path "$configDir\speech-paused"
$voice = if (Test-Path "$configDir\speech-voice") { Get-Content "$configDir\speech-voice" } else { "default (en-US-GuyNeural)" }
$intro = if (Test-Path "$configDir\speech-preamble") { "preamble" } elseif (Test-Path "$configDir\speech-snippet") { "snippet" } else { "none" }
```

**Linux/macOS (Bash):**
```bash
CONFIG_DIR="$HOME/.claude/projects/<ENCODED>"
PAUSED=$([ -f "$CONFIG_DIR/speech-paused" ] && echo "OFF" || echo "ON")
VOICE=$(cat "$CONFIG_DIR/speech-voice" 2>/dev/null || echo "default (en-US-GuyNeural)")
if [ -f "$CONFIG_DIR/speech-preamble" ]; then INTRO=preamble
elif [ -f "$CONFIG_DIR/speech-snippet" ]; then INTRO=snippet
else INTRO=none
fi
```

### `/speak voices`
Show the voice table above. Mention that `python3 -m edge_tts --list-voices` shows all available voices.

### `/speak voice <name>`
Write the voice name to the config file:

**Windows (PowerShell):**
```powershell
Set-Content "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-voice" "<VOICE_NAME>" -NoNewline
```

**Linux/macOS (Bash):**
```bash
mkdir -p "$HOME/.claude/projects/<ENCODED>"
printf '%s' "<VOICE_NAME>" > "$HOME/.claude/projects/<ENCODED>/speech-voice"
```

The change takes effect on the next spoken message (no restart needed).

### `/speak voice reset`

**Windows (PowerShell):**
```powershell
Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-voice" -Force -ErrorAction SilentlyContinue
```

**Linux/macOS (Bash):**
```bash
rm -f "$HOME/.claude/projects/<ENCODED>/speech-voice"
```

### `/speak snippet on`
Enable reading the first sentence before the TTS summary, and disable preamble
(mutually exclusive).

**Windows (PowerShell):**
```powershell
$configDir = "$env:USERPROFILE\.claude\projects\<ENCODED>"
New-Item $configDir -ItemType Directory -Force | Out-Null
Remove-Item "$configDir\speech-preamble" -Force -ErrorAction SilentlyContinue
New-Item "$configDir\speech-snippet" -ItemType File -Force | Out-Null
```

**Linux/macOS (Bash):**
```bash
CONFIG_DIR="$HOME/.claude/projects/<ENCODED>"
mkdir -p "$CONFIG_DIR"
rm -f "$CONFIG_DIR/speech-preamble"
touch "$CONFIG_DIR/speech-snippet"
```

### `/speak snippet off`

**Windows (PowerShell):**
```powershell
Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-snippet" -Force -ErrorAction SilentlyContinue
```

**Linux/macOS (Bash):**
```bash
rm -f "$HOME/.claude/projects/<ENCODED>/speech-snippet"
```

### `/speak preamble on`
Enable reading the entire first paragraph before the TTS summary, and disable
snippet (mutually exclusive).

**Windows (PowerShell):**
```powershell
$configDir = "$env:USERPROFILE\.claude\projects\<ENCODED>"
New-Item $configDir -ItemType Directory -Force | Out-Null
Remove-Item "$configDir\speech-snippet" -Force -ErrorAction SilentlyContinue
New-Item "$configDir\speech-preamble" -ItemType File -Force | Out-Null
```

**Linux/macOS (Bash):**
```bash
CONFIG_DIR="$HOME/.claude/projects/<ENCODED>"
mkdir -p "$CONFIG_DIR"
rm -f "$CONFIG_DIR/speech-snippet"
touch "$CONFIG_DIR/speech-preamble"
```

### `/speak preamble off`

**Windows (PowerShell):**
```powershell
Remove-Item "$env:USERPROFILE\.claude\projects\<ENCODED>\speech-preamble" -Force -ErrorAction SilentlyContinue
```

**Linux/macOS (Bash):**
```bash
rm -f "$HOME/.claude/projects/<ENCODED>/speech-preamble"
```

### Response format
Always be concise. Examples:
- "Speech for MyApp: ON"
- "Speech for MyApp: OFF"
- "Voice for MyApp set to: en-GB-RyanNeural"
- "Voice for MyApp reset to default (en-US-GuyNeural)"
- "Snippet for MyApp: ON (preamble OFF)"
- "Preamble for MyApp: ON (snippet OFF)"
- "Intro mode for MyApp: none"
