# Contributing to claude-speak

Thanks for your interest in contributing.

## Reporting Bugs

Open an issue with:
- Your OS and Python version
- Steps to reproduce
- Expected vs actual behavior
- Any error output from stderr

## Suggesting Features

Open an issue describing:
- The problem you're trying to solve
- Your proposed solution
- Alternatives you've considered

## Pull Requests

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Make your changes
4. Test on your platform:
   - `python3 -m pytest tests/ -v` (unit tests)
   - `echo '{"cwd": "'"$PWD"'", "transcript_path": "/path/to/a/transcript.jsonl"}' | python3 speak.py hook` (drive the hook directly)
   - `python3 speak.py say some_text_file.txt en-US-GuyNeural` (audio playback for a given voice)
5. Commit with a clear message
6. Open a PR

## Code Style

- Python 3.8+ compatible (no walrus operator, no `match` statements)
- Use `argparse` for CLI arguments
- Keep dependencies minimal -- `edge-tts` is the only required dependency
- Cross-platform: test or guard platform-specific code (`sys.platform`)

## Architecture

```
speak.py         -- Stop-hook engine: extracts the TTS_SUMMARY marker (hook
                     mode) and does edge-tts synthesis + playback (say mode)
configure.py     -- Web-based settings UI
settings.html    -- Frontend for configure.py
merge_hook.py    -- Idempotent Stop-hook installer for settings.json
install.sh       -- Installer (Linux/macOS)
install.ps1      -- Installer (Windows)
skill/SKILL.md   -- Claude Code /speak skill definition
```

**Marker extraction and text cleaning** live in `speak.py` (`extract_summary` / `clean_summary`). Since only the `<!-- TTS_SUMMARY ... -->` block is ever spoken, there is no general Claude Code output to sanitize -- keep this minimal on purpose.

**Audio playback** is platform-specific: Windows uses MCI via ctypes, macOS uses afplay, Linux uses ffplay. New platforms need a new playback function in `speak.py`.

## What's Welcome

- New TTS backends (local engines like Kokoro, Piper, etc.)
- Better text cleaning patterns for Claude Code output
- Bug fixes and platform-specific fixes
- Documentation improvements
- Performance improvements

## What to Avoid

- Adding heavy dependencies
- Breaking changes to the flag-file config system
- Features that require Claude Code modifications
