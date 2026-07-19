# claude-speak

**Spoken summaries for Claude Code.** A Stop hook reads a short, marked
summary of each response aloud -- and stays silent otherwise.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/Python-3.8+-green.svg)](https://www.python.org)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)](#platform-support)

<!-- TODO: Add demo GIF here -->
<!-- ![claude-speak demo](demo.gif) -->

---

## Why claude-speak?

There are several TTS tools for Claude Code. Here's why claude-speak is different:

| | claude-speak | [VoiceMode](https://github.com/mbailey/voicemode) | [AgentVibes](https://github.com/paulpreibisch/AgentVibes) | [claude-code-tts](https://github.com/ybouhjira/claude-code-tts) |
|---|:---:|:---:|:---:|:---:|
| **Cost** | **Free** | Free or paid | Free or paid | ~$0.015/1K chars |
| **API key needed** | **No** | Yes (OpenAI) | Optional | Yes (OpenAI) |
| **Model download** | **No** | Yes (Kokoro) | Yes (Piper) | No |
| **Voices** | **400+** | ~20 | 50+ | 6 |
| **Integration** | Stop hook | MCP server | MCP server | MCP + hooks |
| **Setup steps** | **1 command** | 3-5 | 3-5 | 3-5 |
| **Works offline** | No | Yes (Kokoro) | Yes (Piper) | No |

claude-speak uses [edge-tts](https://github.com/rany2/edge-tts), which provides free access to Microsoft's Neural TTS voices (the same ones powering Edge's Read Aloud). No signup, no billing, no model files to download.

**Trade-off:** Requires internet. If you need offline TTS, check out VoiceMode (Kokoro) or AgentVibes (Piper).

## How It Works

```
Claude Code  --Stop hook-->  speak.py hook  --detached-->  speak.py say  --edge-tts-->  speakers
(response      reads the       extracts the      spawns a       synthesizes    (your
 finishes)     TTS_SUMMARY     marker, decides    background     the summary    speakers)
               marker          whether to speak   process
```

1. When a response finishes, Claude Code fires its `Stop` hook, which runs `speak.py hook` with the transcript path on stdin.
2. `speak.py hook` looks at the *last* assistant message for a strict `<!-- TTS_SUMMARY ... TTS_SUMMARY -->` HTML-comment marker.
3. **No marker, no speech.** claude-speak never reads a full response aloud -- silence is the default. Only the text inside the marker is ever spoken.
4. If a marker is found (and speech isn't paused for this project), `speak.py` spawns a detached `speak.py say` process so the hook returns instantly and never blocks Claude Code.
5. The detached process synthesizes the summary with edge-tts and plays it through your speakers, serialized behind a short-lived inter-session lock so overlapping sessions don't talk over each other.

Because the marker is an HTML comment, it never shows up in the rendered response -- only in the raw transcript that the hook reads.

## Quick Start

```bash
git clone https://github.com/silverdolphin863/claude-speak.git && cd claude-speak && ./install.sh
```

On Windows (PowerShell):

```powershell
git clone https://github.com/silverdolphin863/claude-speak.git; cd claude-speak; .\install.ps1
```

The installer:

- Installs `edge-tts` if it isn't already present
- Copies `speak.py`, `configure.py`, `settings.html` to `~/.claude/tools/`
- Installs the `/speak` skill to `~/.claude/skills/speak/`
- Merges a `Stop` hook entry into `~/.claude/settings.json` (idempotent, keeps a `.bak` backup, never overwrites your other hooks)

Then add the TTS summary snippet below to your **global** `CLAUDE.md` and restart Claude Code. Without it, Claude never wraps a summary in the marker, so claude-speak stays silent.

## TTS Summary Instructions

claude-speak only ever speaks what's inside a `<!-- TTS_SUMMARY ... TTS_SUMMARY -->` marker. Add this block to your global Claude Code instructions file so every response ends with one:

- Linux / macOS: `~/.claude/CLAUDE.md`
- Windows (PowerShell): `$env:USERPROFILE\.claude\CLAUDE.md`

````markdown
## TTS Summary Instructions

At the END of EVERY response, wrap a short TTS-friendly summary in this EXACT
marker block (verbatim — keep the English keyword `TTS_SUMMARY` even when the
surrounding conversation is in French or any other language):

<!-- TTS_SUMMARY
Brief, natural language summary of what you did. No URLs, no technical jargon, no code snippets.
Just explain in 1-2 sentences what was accomplished, like you're talking to someone.
TTS_SUMMARY -->

Hard rules for the marker block (these override the conversation language):

- Use this EXACT marker block on every response. Do NOT translate `TTS_SUMMARY`.
- Do NOT replace the block with a label such as `TTS Summary:`, `Résumé TTS:`,
  `Résumé vocal:`, `Voice Summary:`, etc. The HTML comment form is the only
  accepted format — it is what the speech monitor parses.
- The marker block must come AFTER the technical response, on its own paragraph,
  with a blank line above it.
- Put ONLY the spoken summary inside the block. Anything outside the block is
  treated as visual-only and will not be read aloud.

Keep the summary inside the block conversational and avoid:
- URLs (say "a link" instead)
- File paths (say "the configuration file" instead)
- Technical constants or variable names
- Code syntax
````

Unlike v1, claude-speak v2 recognizes **only** this exact HTML-comment marker -- there is no fallback to speaking the whole response and no tolerance for visible label variants. If the marker is missing or malformed, the response is simply not spoken.

Once added, the change takes effect the next time Claude Code fires the `Stop` hook -- no restart of any background process needed, because there isn't one until a response actually needs to be spoken.

## Using the `/speak` Skill

Once installed, control speech from within Claude Code:

```
/speak              Toggle speech on/off for this project
/speak on           Enable speech
/speak off          Disable speech
/speak status       Show current voice and state
/speak voices       List recommended voices
/speak voice <name> Set voice for this project
/speak voice reset  Reset to the default voice
```

## Settings UI

Browse voices, preview audio, and configure per-project settings:

```bash
python3 ~/.claude/tools/configure.py
# Opens http://localhost:8910
```

## Configuration

### Flag Files

Settings are plain flag files, checked project-first then falling back to the global copy:

| File | Location | Purpose |
|------|----------|---------|
| `speech-paused` | `~/.claude/projects/<enc>/` (project) or `~/.claude/` (global) | When present, speech is paused |
| `speech-voice` | `~/.claude/projects/<enc>/` (project) or `~/.claude/` (global) | Contains the voice name (e.g. `en-GB-RyanNeural`) |
| `speech-debug` | `~/.claude/` | When present, enables logging to `~/.claude/tools/speak.log` |
| `speech-playing.lock` | `~/.claude/` | Internal inter-session playback lock; self-clears after ~60s if stale |

`<enc>` is the CWD with `:`, `\`, `/` replaced by `-` (the same scheme Claude Code itself uses). Example: `C:\Projects\MyApp` becomes `C--Projects-MyApp`.

### Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `CC_SPEAK_RATE` | edge-tts speech rate | `+10%` |
| `CC_SPEAK_HOME` | Override `~/.claude` (used by the test suite) | - |

Default voice: `fr-FR-RemyMultilingualNeural` (multilingual -- reads French and English correctly).

### Debug Logging

No log file is written by default. To enable it, touch the debug flag:

```bash
touch ~/.claude/speech-debug
```

Then tail `~/.claude/tools/speak.log` while you use Claude Code.

## Platform Support

| Platform | Audio Playback | Status |
|----------|---------------|--------|
| Windows | MCI (built-in, windowless) | Full support |
| macOS | afplay (built-in) | Full support |
| Linux | ffplay (install ffmpeg) | Full support |

## Requirements

- Python 3.8+
- [edge-tts](https://github.com/rany2/edge-tts) (`pip install edge-tts`)
- Internet connection (for Microsoft Neural TTS)
- ffplay on Linux only (for audio playback): `sudo apt install ffmpeg`
- On recent Debian/Ubuntu (PEP 668 "externally-managed-environment"), the installers automatically retry with `--break-system-packages`; alternatively install edge-tts via `pipx install edge-tts`

## Troubleshooting

**No sound?**
- Check `/speak status` -- make sure speech isn't paused and the voice is set as expected
- Confirm the hook is registered: look for a `speak.py hook` command under `hooks.Stop` in `~/.claude/settings.json`
- Enable debug logging: `touch ~/.claude/speech-debug`, reproduce, then read `~/.claude/tools/speak.log`
- On Linux, install ffmpeg: `sudo apt install ffmpeg`
- Make sure your global `CLAUDE.md` has the TTS summary instructions above -- no marker means no speech

**Still hearing entire responses read aloud?**
- That's the v1 behavior. An old v1 monitor (`claude-speak.py`) is probably still running somewhere -- kill it: `pkill -f claude-speak.py`
- On Windows: `Get-CimInstance Win32_Process -Filter "Name like 'python%'" | Where-Object { $_.CommandLine -match 'claude-speak\.py' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }`

**edge-tts errors?**
- Check your internet connection (edge-tts requires Microsoft's servers)
- Update edge-tts: `pip install --upgrade edge-tts`

## v1 -> v2 Migration

v2 is a full rewrite around a Claude Code `Stop` hook instead of a background JSONL-tailing monitor:

- `claude-speak.py` (monitor) and `cc-speak.py` (TTS engine) are removed. If either is still running, stop it: `pkill -f claude-speak.py` / `pkill -f cc-speak.py`.
- There is no more background process to start -- the hook is invoked by Claude Code itself after every response.
- The default "speak the whole cleaned response" behavior, the visible label fallbacks (`TTS Summary:`, `Résumé TTS:`, ...), the `snippet`/`preamble` intro modes, and the OpenAI TTS backend are all dropped. Only the strict `<!-- TTS_SUMMARY ... TTS_SUMMARY -->` marker is recognized.
- Re-run `./install.sh` / `.\install.ps1` to register the new hook; your existing `speech-voice` / `speech-paused` flag files carry over unchanged.
- Leftover `speech-snippet` / `speech-preamble` flag files from v1 are inert in v2 (the snippet/preamble intro modes are gone) and may be deleted.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Roadmap

See [ROADMAP.md](ROADMAP.md) for planned features.

## License

MIT License. See [LICENSE](LICENSE) for details.
