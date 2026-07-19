# claude-speak v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fragile JSONL-monitor TTS with a Claude Code `Stop` hook that speaks ONLY a strictly-marked summary, and stays silent otherwise.

**Architecture:** A single `speak.py` with two CLI modes: `hook` (called by Claude Code's Stop hook; extracts the summary from the transcript and spawns a detached player) and `say` (edge-tts synthesis + cross-platform playback behind an inter-session file lock). The existing web UI (`configure.py` + `settings.html`) is kept but stripped of monitor controls. Old monitor/engine files are deleted.

**Tech Stack:** Python 3.8+ stdlib, `edge-tts` (only external dep), pytest for tests. Playback: Windows MCI (ctypes), macOS `afplay`, Linux `ffplay`.

**Spec:** `docs/superpowers/specs/2026-07-19-claude-speak-v2-design.md`

## Global Constraints

- Python floor: 3.8. No dependency other than `edge-tts` (pytest is dev-only).
- The hook mode NEVER exits non-zero and NEVER prints to stdout/stderr in normal operation (it must not break or slow Claude Code).
- Strict marker only: `<!--\s*TTS_SUMMARY\s*(.*?)\s*TTS_SUMMARY\s*-->` (DOTALL). Label variants ("Résumé TTS:", "TTS Summary:", etc.) must NOT match. Multiple markers: the LAST non-empty one wins.
- No marker (or empty marker) → total silence.
- Default voice: `fr-FR-RemyMultilingualNeural`. Default rate: `+10%`, overridable via env `CC_SPEAK_RATE`.
- Config flag files (unchanged from v1): `~/.claude/speech-paused`, `~/.claude/projects/<enc>/speech-paused`, `~/.claude/speech-voice`, `~/.claude/projects/<enc>/speech-voice`. `<enc>` = normalized cwd with `:`, `\`, `/` replaced by `-`.
- Summary text passes hook→say via temp file, never argv.
- Playback serialized across sessions by lock file `~/.claude/speech-playing.lock`; stale after 60 s.
- Debug logging ONLY when flag file `~/.claude/speech-debug` exists; log to `~/.claude/tools/speak.log`.
- Deleted features must not survive anywhere: snippet/preamble intro modes, OpenAI backend, JSONL monitor, PID files, debounce.
- Repo files are the source of truth; installers copy `speak.py`, `configure.py`, `settings.html` to `~/.claude/tools/` and the skill to `~/.claude/skills/speak/`.

---

### Task 1: `speak.py` core — cwd encoding, marker extraction, transcript parsing

**Files:**
- Create: `speak.py`
- Create: `tests/test_speak.py`

**Interfaces:**
- Produces: `encode_cwd(cwd: str) -> str`; `extract_summary(text: str) -> str | None`; `last_assistant_text(transcript_path: str) -> str` (returns `""` when none). Module constants `MARKER_RE`, `CLAUDE_DIR`, `PROJECTS_DIR`, `DEFAULT_VOICE`, `DEFAULT_RATE`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_speak.py`:

```python
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import speak


# ─── encode_cwd ───────────────────────────────────────────────────────────────

def test_encode_cwd_unix():
    assert speak.encode_cwd("/home/user/myapp") == "-home-user-myapp"


def test_encode_cwd_windows_style():
    # Backslashes and colon are replaced even on POSIX (string-level operation)
    assert speak.encode_cwd("C:\\Projects\\MyApp") == "C--Projects-MyApp"


# ─── extract_summary ──────────────────────────────────────────────────────────

def test_marker_basic():
    text = "Body text.\n\n<!-- TTS_SUMMARY\nAll done here.\nTTS_SUMMARY -->"
    assert speak.extract_summary(text) == "All done here."


def test_marker_multiline_content():
    text = "<!-- TTS_SUMMARY\nLine one.\nLine two.\nTTS_SUMMARY -->"
    assert speak.extract_summary(text) == "Line one.\nLine two."


def test_marker_tight_whitespace():
    text = "<!--TTS_SUMMARY Hello there. TTS_SUMMARY-->"
    assert speak.extract_summary(text) == "Hello there."


def test_no_marker_returns_none():
    assert speak.extract_summary("Just a plain response with no marker.") is None


def test_empty_marker_returns_none():
    assert speak.extract_summary("<!-- TTS_SUMMARY\n   \nTTS_SUMMARY -->") is None


def test_v1_label_variants_do_not_match():
    for label in ["TTS Summary: hello", "Résumé TTS : bonjour",
                  "Résumé vocal: bonjour", "**Voice Summary:** hi",
                  "Spoken Summary: hi"]:
        assert speak.extract_summary("Body.\n\n" + label) is None


def test_multiple_markers_last_wins():
    text = ("<!-- TTS_SUMMARY First. TTS_SUMMARY -->\n"
            "middle\n"
            "<!-- TTS_SUMMARY Second. TTS_SUMMARY -->")
    assert speak.extract_summary(text) == "Second."


def test_multiple_markers_last_empty_falls_back_to_previous():
    text = ("<!-- TTS_SUMMARY First. TTS_SUMMARY -->\n"
            "<!-- TTS_SUMMARY   TTS_SUMMARY -->")
    assert speak.extract_summary(text) == "First."


# ─── last_assistant_text ──────────────────────────────────────────────────────

def _write_transcript(tmp_path, lines):
    p = tmp_path / "transcript.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines), encoding="utf-8")
    return str(p)


def _assistant_line(msg_id, text=None, tool_use=False):
    content = []
    if text is not None:
        content.append({"type": "text", "text": text})
    if tool_use:
        content.append({"type": "tool_use", "id": "tu1", "name": "Bash", "input": {}})
    return {"type": "assistant", "uuid": "u-" + msg_id,
            "message": {"id": msg_id, "content": content}}


def test_last_assistant_single_message(tmp_path):
    path = _write_transcript(tmp_path, [
        {"type": "user", "message": {"content": "hi"}},
        _assistant_line("m1", "Hello world."),
    ])
    assert speak.last_assistant_text(path) == "Hello world."


def test_last_assistant_takes_last_message_only(tmp_path):
    path = _write_transcript(tmp_path, [
        _assistant_line("m1", "Old reply."),
        {"type": "user", "message": {"content": "again"}},
        _assistant_line("m2", "New reply."),
    ])
    assert speak.last_assistant_text(path) == "New reply."


def test_last_assistant_joins_split_lines_same_id(tmp_path):
    # One API response split across JSONL lines sharing message.id
    path = _write_transcript(tmp_path, [
        _assistant_line("m2", "Part one."),
        _assistant_line("m2", None, tool_use=True),
        _assistant_line("m2", "Part two."),
    ])
    assert speak.last_assistant_text(path) == "Part one.\nPart two."


def test_last_assistant_ignores_tool_only_lines(tmp_path):
    path = _write_transcript(tmp_path, [
        _assistant_line("m1", "Real text."),
        _assistant_line("m2", None, tool_use=True),
    ])
    # m2 has no text at all: the last message WITH text is still m1,
    # but m2 is the last assistant message → result is "" (silence).
    assert speak.last_assistant_text(path) == ""


def test_last_assistant_skips_malformed_lines(tmp_path):
    p = tmp_path / "transcript.jsonl"
    p.write_text('not json at all\n'
                 + json.dumps(_assistant_line("m1", "Fine.")) + "\n"
                 + '{"broken": ', encoding="utf-8")
    assert speak.last_assistant_text(str(p)) == "Fine."


def test_last_assistant_missing_file_returns_empty():
    assert speak.last_assistant_text("/nonexistent/nowhere.jsonl") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: FAIL / ERROR with `ModuleNotFoundError: No module named 'speak'`

- [ ] **Step 3: Write the implementation**

Create `speak.py`:

```python
#!/usr/bin/env python3
"""claude-speak v2: speak the TTS summary of a finished Claude Code response.

Registered as a Claude Code Stop hook ("hook" mode). When the last assistant
message contains a strict <!-- TTS_SUMMARY ... TTS_SUMMARY --> marker, the
summary is synthesized with edge-tts and played ("say" mode, run detached).
No marker means silence — nothing else is ever spoken.

Usage:
    python speak.py hook          # called by Claude Code (hook JSON on stdin)
    python speak.py say FILE VOICE  # internal: speak text from FILE, delete it
"""

import json
import os
import re
import sys

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
PROJECTS_DIR = os.path.join(CLAUDE_DIR, "projects")
DEFAULT_VOICE = "fr-FR-RemyMultilingualNeural"
DEFAULT_RATE = os.environ.get("CC_SPEAK_RATE", "+10%")
LOCK_PATH = os.path.join(CLAUDE_DIR, "speech-playing.lock")
LOCK_STALE_SEC = 60
DEBUG_FLAG = os.path.join(CLAUDE_DIR, "speech-debug")
LOG_PATH = os.path.join(CLAUDE_DIR, "tools", "speak.log")

MARKER_RE = re.compile(r"<!--\s*TTS_SUMMARY\s*(.*?)\s*TTS_SUMMARY\s*-->", re.DOTALL)


def log(msg):
    """Append a debug line to LOG_PATH, only when the debug flag file exists."""
    if not os.path.exists(DEBUG_FLAG):
        return
    try:
        import datetime
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (datetime.datetime.now().isoformat(timespec="seconds"), msg))
    except OSError:
        pass


def encode_cwd(cwd):
    """Encode a working directory to Claude's project directory name."""
    path = os.path.normpath(cwd)
    return path.replace(":", "-").replace("\\", "-").replace("/", "-")


def extract_summary(text):
    """Return the last non-empty strict-marker summary, or None."""
    if not text:
        return None
    for match in reversed(MARKER_RE.findall(text)):
        if match.strip():
            return match.strip()
    return None


def last_assistant_text(transcript_path):
    """Concatenated text blocks of the LAST assistant message in the transcript.

    A single API response can span several JSONL lines sharing message.id;
    all their text blocks are joined. Returns "" on any problem.
    """
    last_id = None
    texts = []
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                if data.get("type") != "assistant":
                    continue
                message = data.get("message") or {}
                msg_id = message.get("id") or data.get("uuid")
                if msg_id != last_id:
                    last_id = msg_id
                    texts = []
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text", "")
                        if t.strip():
                            texts.append(t)
    except OSError:
        return ""
    return "\n".join(texts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add speak.py tests/test_speak.py
git commit -m "feat(v2): speak.py core - strict marker extraction and transcript parsing"
```

---

### Task 2: config resolution (pause + voice) and summary cleaning

**Files:**
- Modify: `speak.py` (append functions)
- Modify: `tests/test_speak.py` (append tests)

**Interfaces:**
- Consumes: `encode_cwd`, `CLAUDE_DIR`, `PROJECTS_DIR`, `DEFAULT_VOICE` from Task 1.
- Produces: `is_paused(cwd: str | None) -> bool`; `get_voice(cwd: str | None) -> str`; `clean_summary(text: str) -> str`. All three honor an env override `CC_SPEAK_HOME` used ONLY by tests to relocate `~/.claude`.

To make the config functions testable without touching the real home directory, Task 1's module-level constants move behind small helpers that re-read `CC_SPEAK_HOME`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_speak.py`:

```python
# ─── config resolution ────────────────────────────────────────────────────────

import pytest


@pytest.fixture
def fake_home(tmp_path, monkeypatch):
    monkeypatch.setenv("CC_SPEAK_HOME", str(tmp_path))
    (tmp_path / "projects").mkdir()
    return tmp_path


def _project_dir(fake_home, cwd):
    d = fake_home / "projects" / speak.encode_cwd(cwd)
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_not_paused_by_default(fake_home):
    assert speak.is_paused("/home/user/app") is False


def test_project_pause_flag(fake_home):
    (_project_dir(fake_home, "/home/user/app") / "speech-paused").touch()
    assert speak.is_paused("/home/user/app") is True
    assert speak.is_paused("/home/user/other") is False


def test_global_pause_flag(fake_home):
    (fake_home / "speech-paused").touch()
    assert speak.is_paused("/home/user/app") is True
    assert speak.is_paused(None) is True


def test_voice_default(fake_home):
    assert speak.get_voice("/home/user/app") == speak.DEFAULT_VOICE


def test_voice_project_overrides_global(fake_home):
    (fake_home / "speech-voice").write_text("en-GB-RyanNeural")
    d = _project_dir(fake_home, "/home/user/app")
    (d / "speech-voice").write_text("fr-FR-DeniseNeural\n")
    assert speak.get_voice("/home/user/app") == "fr-FR-DeniseNeural"
    assert speak.get_voice("/home/user/other") == "en-GB-RyanNeural"


def test_voice_empty_file_falls_through(fake_home):
    d = _project_dir(fake_home, "/home/user/app")
    (d / "speech-voice").write_text("   ")
    assert speak.get_voice("/home/user/app") == speak.DEFAULT_VOICE


# ─── clean_summary ────────────────────────────────────────────────────────────

def test_clean_summary_strips_markdown_decoration():
    assert speak.clean_summary("**Done** with `speak.py` _now_.") == "Done with speak.py now."


def test_clean_summary_collapses_whitespace():
    assert speak.clean_summary("One.\n\nTwo.\t Three.") == "One. Two. Three."
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: Task 1 tests PASS; new tests FAIL with `AttributeError: module 'speak' has no attribute 'is_paused'`

- [ ] **Step 3: Implement**

In `speak.py`, replace the two constants `CLAUDE_DIR` / `PROJECTS_DIR` block with home helpers, and update the other constants that derive from them:

```python
def claude_dir():
    """~/.claude, overridable via CC_SPEAK_HOME (used by tests)."""
    return os.environ.get("CC_SPEAK_HOME") or os.path.join(os.path.expanduser("~"), ".claude")


def projects_dir():
    return os.path.join(claude_dir(), "projects")


DEFAULT_VOICE = "fr-FR-RemyMultilingualNeural"
DEFAULT_RATE = os.environ.get("CC_SPEAK_RATE", "+10%")
LOCK_STALE_SEC = 60


def lock_path():
    return os.path.join(claude_dir(), "speech-playing.lock")


def debug_flag():
    return os.path.join(claude_dir(), "speech-debug")


def log_path():
    return os.path.join(claude_dir(), "tools", "speak.log")
```

Update `log()` to call `debug_flag()` / `log_path()` instead of the old constants (same body otherwise). Then append:

```python
def _flag_exists(cwd, name):
    if cwd:
        if os.path.exists(os.path.join(projects_dir(), encode_cwd(cwd), name)):
            return True
    return os.path.exists(os.path.join(claude_dir(), name))


def _read_config(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            value = f.read().strip()
            return value or None
    except OSError:
        return None


def is_paused(cwd):
    """Project pause flag wins, then the global one."""
    return _flag_exists(cwd, "speech-paused")


def get_voice(cwd):
    """Voice resolution: project > global > DEFAULT_VOICE."""
    if cwd:
        v = _read_config(os.path.join(projects_dir(), encode_cwd(cwd), "speech-voice"))
        if v:
            return v
    v = _read_config(os.path.join(claude_dir(), "speech-voice"))
    return v or DEFAULT_VOICE


def clean_summary(text):
    """Minimal cleanup: markdown decoration off, whitespace collapsed."""
    text = re.sub(r"[*_`#]+", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()
```

(`CLAUDE_DIR`, `PROJECTS_DIR`, `LOCK_PATH`, `DEBUG_FLAG`, `LOG_PATH` constants are removed; nothing else references them yet.)

- [ ] **Step 4: Run all tests**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add speak.py tests/test_speak.py
git commit -m "feat(v2): pause/voice resolution and minimal summary cleaning"
```

---

### Task 3: hook mode — decide what to speak, spawn detached player

**Files:**
- Modify: `speak.py` (append)
- Modify: `tests/test_speak.py` (append)

**Interfaces:**
- Consumes: `last_assistant_text`, `extract_summary`, `is_paused`, `get_voice`, `clean_summary`, `log`.
- Produces: `run_hook(hook_input: dict) -> tuple[str, str] | None` — pure decision function returning `(summary_text, voice)` or `None` (silence); `spawn_say(text: str, voice: str) -> None` — writes temp file, spawns detached `speak.py say FILE VOICE`; `main()` CLI entry. Task 4 implements `cmd_say`; here it only gets a stub that exits 0.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_speak.py`:

```python
# ─── run_hook ─────────────────────────────────────────────────────────────────

MARKED = "Work done.\n\n<!-- TTS_SUMMARY\nEverything is finished.\nTTS_SUMMARY -->"


def _hook_input(tmp_path, response_text, cwd="/home/user/app"):
    lines = [_assistant_line("m1", response_text)]
    return {"transcript_path": _write_transcript(tmp_path, lines), "cwd": cwd}


def test_run_hook_returns_summary_and_voice(fake_home, tmp_path):
    result = speak.run_hook(_hook_input(tmp_path, MARKED))
    assert result == ("Everything is finished.", speak.DEFAULT_VOICE)


def test_run_hook_no_marker_is_silent(fake_home, tmp_path):
    assert speak.run_hook(_hook_input(tmp_path, "Plain response.")) is None


def test_run_hook_paused_is_silent(fake_home, tmp_path):
    (_project_dir(fake_home, "/home/user/app") / "speech-paused").touch()
    assert speak.run_hook(_hook_input(tmp_path, MARKED)) is None


def test_run_hook_uses_project_voice(fake_home, tmp_path):
    d = _project_dir(fake_home, "/home/user/app")
    (d / "speech-voice").write_text("en-GB-RyanNeural")
    result = speak.run_hook(_hook_input(tmp_path, MARKED))
    assert result == ("Everything is finished.", "en-GB-RyanNeural")


def test_run_hook_missing_transcript_is_silent(fake_home):
    assert speak.run_hook({"transcript_path": "/nope.jsonl", "cwd": "/x"}) is None


def test_run_hook_cleans_summary(fake_home, tmp_path):
    text = "X\n\n<!-- TTS_SUMMARY\n**Done** with   spaces.\nTTS_SUMMARY -->"
    result = speak.run_hook(_hook_input(tmp_path, text))
    assert result[0] == "Done with spaces."
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'run_hook'`

- [ ] **Step 3: Implement**

Append to `speak.py`:

```python
def run_hook(hook_input):
    """Decide what to speak for a finished response.

    Returns (cleaned_summary, voice) or None for silence.
    """
    cwd = hook_input.get("cwd")
    if is_paused(cwd):
        log("hook: paused, skipping")
        return None
    transcript = hook_input.get("transcript_path")
    if not transcript:
        return None
    text = last_assistant_text(transcript)
    summary = extract_summary(text)
    if not summary:
        log("hook: no marker in last assistant message")
        return None
    cleaned = clean_summary(summary)
    if not cleaned:
        return None
    return cleaned, get_voice(cwd)


def spawn_say(text, voice):
    """Write text to a temp file and launch a detached `say` process."""
    import subprocess
    import tempfile

    fd, path = tempfile.mkstemp(prefix="claude_speak_", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)

    cmd = [sys.executable, os.path.abspath(__file__), "say", path, voice]
    kwargs = {"stdin": subprocess.DEVNULL,
              "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL,
              "close_fds": True}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NO_WINDOW
        kwargs["creationflags"] = 0x00000008 | 0x08000000
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)
    log("hook: spawned say for %d chars, voice=%s" % (len(text), voice))


def cmd_hook():
    """Stop-hook entry: read hook JSON from stdin, never fail, never block."""
    try:
        hook_input = json.load(sys.stdin)
    except ValueError:
        return
    result = run_hook(hook_input)
    if result:
        spawn_say(result[0], result[1])


def cmd_say(text_file, voice):
    """Implemented in Task 4."""


def main():
    try:
        mode = sys.argv[1] if len(sys.argv) > 1 else ""
        if mode == "hook":
            cmd_hook()
        elif mode == "say" and len(sys.argv) >= 4:
            cmd_say(sys.argv[2], sys.argv[3])
    except Exception:
        try:
            import traceback
            log("fatal: " + traceback.format_exc())
        except Exception:
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run all tests**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: all PASS

- [ ] **Step 5: Smoke-test the CLI silently exits 0 on garbage**

Run: `echo 'not json' | python3 speak.py hook; echo "exit=$?"`
Expected output: `exit=0`, nothing else printed.

- [ ] **Step 6: Commit**

```bash
git add speak.py tests/test_speak.py
git commit -m "feat(v2): hook mode - summary decision and detached say spawn"
```

---

### Task 4: say mode — synthesis, playback lock, cross-platform playback

**Files:**
- Modify: `speak.py` (append + fill `cmd_say`)
- Modify: `tests/test_speak.py` (append lock tests)

**Interfaces:**
- Consumes: `lock_path()`, `LOCK_STALE_SEC`, `DEFAULT_RATE`, `log`.
- Produces: `synthesize(text, voice, rate, output_path) -> bool`; `play(path) -> bool`; `acquire_play_lock(timeout_sec=90) -> bool`; `release_play_lock() -> None`. `synthesize` and `play` are also imported by `configure.py` (Task 5).

- [ ] **Step 1: Write the failing lock tests**

Append to `tests/test_speak.py` (network/audio functions are NOT unit-tested; the lock is):

```python
# ─── playback lock ────────────────────────────────────────────────────────────

import time


def test_lock_acquire_and_release(fake_home):
    assert speak.acquire_play_lock(timeout_sec=1) is True
    assert os.path.exists(speak.lock_path())
    speak.release_play_lock()
    assert not os.path.exists(speak.lock_path())


def test_lock_blocks_then_times_out(fake_home):
    # A fresh lock held by "another process" (age < LOCK_STALE_SEC)
    with open(speak.lock_path(), "w") as f:
        f.write("99999999")
    start = time.time()
    assert speak.acquire_play_lock(timeout_sec=1) is False
    assert time.time() - start >= 0.9
    os.remove(speak.lock_path())


def test_lock_stale_is_reclaimed(fake_home):
    with open(speak.lock_path(), "w") as f:
        f.write("99999999")
    old = time.time() - (speak.LOCK_STALE_SEC + 5)
    os.utime(speak.lock_path(), (old, old))
    assert speak.acquire_play_lock(timeout_sec=5) is True
    speak.release_play_lock()
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: new tests FAIL with `AttributeError: ... no attribute 'acquire_play_lock'`

- [ ] **Step 3: Implement**

Append to `speak.py`, and replace the Task 3 stub of `cmd_say`:

```python
def synthesize(text, voice, rate, output_path):
    """edge-tts synthesis to an mp3 file. Returns True on success."""
    import asyncio
    try:
        import edge_tts
    except ImportError:
        log("say: edge-tts not installed")
        return False

    async def _run():
        communicate = edge_tts.Communicate(text, voice, rate=rate)
        await communicate.save(output_path)

    try:
        asyncio.run(_run())
    except Exception as e:
        log("say: edge-tts failed: %r" % (e,))
        return False
    return os.path.isfile(output_path) and os.path.getsize(output_path) > 0


def _play_mci(path):
    """Windows: windowless playback via MCI. Blocking."""
    import ctypes
    winmm = ctypes.windll.winmm
    buf = ctypes.create_unicode_buffer(256)
    alias = "claude_speak_%d" % os.getpid()
    abs_path = os.path.abspath(path)
    if winmm.mciSendStringW('open "%s" type mpegvideo alias %s' % (abs_path, alias), buf, 256, 0) != 0:
        return False
    winmm.mciSendStringW("play %s wait" % alias, buf, 256, 0)
    winmm.mciSendStringW("close %s" % alias, buf, 256, 0)
    return True


def play(path):
    """Blocking cross-platform playback: MCI / afplay / ffplay."""
    import shutil
    import subprocess
    if os.name == "nt":
        return _play_mci(path)
    for cmd in (["afplay", path],
                ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", path]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, check=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True
            except subprocess.CalledProcessError:
                continue
    log("say: no audio player found (install ffmpeg?)")
    return False


def acquire_play_lock(timeout_sec=90):
    """Serialize playback across sessions. Stale locks (>LOCK_STALE_SEC) are reclaimed."""
    import time
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            fd = os.open(lock_path(), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - os.path.getmtime(lock_path())
                if age > LOCK_STALE_SEC:
                    os.remove(lock_path())
                    continue
            except OSError:
                continue
            time.sleep(0.5)
        except OSError:
            return False
    return False


def release_play_lock():
    try:
        os.remove(lock_path())
    except OSError:
        pass


def cmd_say(text_file, voice):
    """Speak the text stored in text_file (then delete it)."""
    import tempfile
    try:
        with open(text_file, "r", encoding="utf-8") as f:
            text = f.read().strip()
    except OSError:
        return
    try:
        os.remove(text_file)
    except OSError:
        pass
    if not text:
        return

    mp3 = os.path.join(tempfile.gettempdir(), "claude_speak_%d.mp3" % os.getpid())
    if not synthesize(text, voice, DEFAULT_RATE, mp3):
        return
    got_lock = acquire_play_lock()
    try:
        play(mp3)
    finally:
        if got_lock:
            release_play_lock()
        try:
            os.remove(mp3)
        except OSError:
            pass
```

(Also delete the Task 3 placeholder `def cmd_say(text_file, voice): ...` stub.)

- [ ] **Step 4: Run all tests**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/test_speak.py -v`
Expected: all PASS

- [ ] **Step 5: Manual audio smoke test (requires network + speakers)**

```bash
python3 -c "import tempfile,os; p=os.path.join(tempfile.gettempdir(),'s.txt'); open(p,'w').write('Bonjour, ceci est un test de la version deux.'); print(p)"
python3 speak.py say /tmp/s.txt fr-FR-RemyMultilingualNeural
```

Expected: the sentence is spoken; temp file removed. (Adjust the printed path if tempdir differs.)

- [ ] **Step 6: Commit**

```bash
git add speak.py tests/test_speak.py
git commit -m "feat(v2): say mode - edge-tts synthesis, playback lock, cross-platform audio"
```

---

### Task 5: adapt the web UI (`configure.py` + `settings.html`)

**Files:**
- Modify: `configure.py`
- Modify: `settings.html`

**Interfaces:**
- Consumes: `speak.synthesize(text, voice, rate, output_path)` from Task 4.
- Produces: web UI without monitor controls; preview endpoint backed by `speak.py`.

- [ ] **Step 1: Swap the engine import in `configure.py`**

Replace the `cc-speak.py` file-path import block (lines 33-40, the block starting `# Import cc-speak's TTS functionality` through `spec.loader.exec_module(cc_speak)`) with:

```python
# Import the v2 engine (speak.py lives next to this file)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import speak
```

Replace the single call site `cc_speak.tts_edge(text, voice, rate, output_path)` (in `_api_preview`) with:

```python
speak.synthesize(text, voice, rate, output_path)
```

and adapt the surrounding error handling: `synthesize` returns `False` instead of raising, so:

```python
        if not os.path.exists(output_path):
            if not speak.synthesize(text, voice, rate, output_path):
                self._json_response({'error': 'TTS generation failed'}, 500)
                return
```

- [ ] **Step 2: Remove monitor endpoints from `configure.py`**

- In `do_GET`: delete the `elif` branch routing to `self._api_get_status()` (path `/api/status`).
- In `do_POST`: delete the two `elif` branches for `/api/monitor/start` and `/api/monitor/stop`.
- Delete entire methods: `_api_get_status`, `_api_start_monitor`, `_api_stop_monitor`, `_cleanup_pid_files`, `_remove_pid_if_matches`, and the module-level `is_process_running` helper if nothing else uses it (verify with grep first).

- [ ] **Step 3: Remove monitor UI from `settings.html`**

- Delete the `.monitor-btn*` CSS rules (block around lines 123-157).
- In the header, replace the `statusBadges` div content (the `No monitors` badge, around lines 785-790) with a static badge:

```html
        <div class="status-badges">
            <span class="badge badge-running">
                <span class="badge-dot"></span>
                Hook mode
            </span>
        </div>
```

- Delete JS: `renderStatus`, `startMonitor`, `stopMonitor` functions, the `getStatus()` API wrapper (the function calling `/api/status`), and every call site of these (grep for `renderStatus(`, `getStatus(`, `loadStatus`).
- Grep the file for `snippet` and `preamble`; delete any UI/JS found (there should be none, verify).

- [ ] **Step 4: Verify the UI still works**

```bash
cd /home/bat/git/claude-speak && python3 configure.py --no-browser --port 8911
```

In another shell: `curl -s http://localhost:8911/api/projects | head -c 300` → JSON list, no 500.
Open `http://localhost:8911` in a browser: page renders, voice list loads, preview button plays audio, no JS console errors referencing removed functions. Stop the server (Ctrl-C).

- [ ] **Step 5: Commit**

```bash
git add configure.py settings.html
git commit -m "refactor(v2): web UI on speak.py engine, monitor controls removed"
```

---

### Task 6: simplified `/speak` skill

**Files:**
- Rewrite: `skill/SKILL.md`

**Interfaces:**
- Consumes: flag-file layout from Global Constraints.
- Produces: the skill installed later by installers to `~/.claude/skills/speak/SKILL.md`.

- [ ] **Step 1: Rewrite `skill/SKILL.md`** with exactly this content:

````markdown
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
````

- [ ] **Step 2: Commit**

```bash
git add skill/SKILL.md
git commit -m "feat(v2): simplified /speak skill (no snippet/preamble)"
```

---

### Task 7: installers with settings.json hook merge

**Files:**
- Rewrite: `install.sh`
- Rewrite: `install.ps1`
- Create: `merge_hook.py` (shared by both installers)

**Interfaces:**
- Consumes: repo files `speak.py`, `configure.py`, `settings.html`, `skill/SKILL.md`.
- Produces: installed tree under `~/.claude/` and a `Stop` hook entry in `~/.claude/settings.json`.

- [ ] **Step 1: Create `merge_hook.py`**

```python
#!/usr/bin/env python3
"""Merge the claude-speak Stop hook into ~/.claude/settings.json (idempotent)."""

import json
import os
import shutil
import sys


def main():
    settings_path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    python_cmd = "python" if os.name == "nt" else "python3"
    hook_cmd = "%s %s hook" % (
        python_cmd,
        os.path.join(os.path.expanduser("~"), ".claude", "tools", "speak.py"),
    )

    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except ValueError:
            print("ERROR: %s is not valid JSON; fix it first." % settings_path)
            sys.exit(1)

    stop_groups = settings.setdefault("hooks", {}).setdefault("Stop", [])
    for group in stop_groups:
        for h in group.get("hooks", []):
            if "speak.py hook" in h.get("command", ""):
                print("Stop hook already present, nothing to do.")
                return

    if os.path.exists(settings_path):
        shutil.copy2(settings_path, settings_path + ".bak")
    stop_groups.append({"hooks": [{"type": "command", "command": hook_cmd}]})
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    with open(settings_path, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    print("Stop hook added to %s (backup: settings.json.bak)" % settings_path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Rewrite `install.sh`**

```bash
#!/usr/bin/env bash
# claude-speak v2 installer (Linux/macOS)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HOME/.claude/tools"
SKILLS="$HOME/.claude/skills/speak"

command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 1; }

python3 -c "import edge_tts" 2>/dev/null || {
  echo "Installing edge-tts..."
  python3 -m pip install --user edge-tts
}

if [[ "$(uname)" == "Linux" ]] && ! command -v ffplay >/dev/null; then
  echo "WARNING: ffplay not found - audio will not play. Install with: sudo apt install ffmpeg"
fi

mkdir -p "$TOOLS" "$SKILLS"
cp "$HERE/speak.py" "$HERE/configure.py" "$HERE/settings.html" "$TOOLS/"
cp "$HERE/skill/SKILL.md" "$SKILLS/SKILL.md"

python3 "$HERE/merge_hook.py"

echo ""
echo "claude-speak v2 installed."
echo " - Hook: speaks only the <!-- TTS_SUMMARY ... --> block of each response."
echo " - Make sure your global CLAUDE.md contains the TTS summary instructions"
echo "   (see README.md, section 'TTS summary instructions')."
echo " - Settings UI: python3 $TOOLS/configure.py"
echo " - In Claude Code: /speak on|off|status|voice <name>"
```

- [ ] **Step 3: Rewrite `install.ps1`**

```powershell
# claude-speak v2 installer (Windows)
$ErrorActionPreference = "Stop"
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Tools = "$env:USERPROFILE\.claude\tools"
$Skills = "$env:USERPROFILE\.claude\skills\speak"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "python not found in PATH"
}

python -c "import edge_tts" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing edge-tts..."
    python -m pip install --user edge-tts
}

New-Item -ItemType Directory -Force -Path $Tools, $Skills | Out-Null
Copy-Item "$Here\speak.py", "$Here\configure.py", "$Here\settings.html" $Tools -Force
Copy-Item "$Here\skill\SKILL.md" "$Skills\SKILL.md" -Force

python "$Here\merge_hook.py"

Write-Host ""
Write-Host "claude-speak v2 installed."
Write-Host " - Hook: speaks only the <!-- TTS_SUMMARY ... --> block of each response."
Write-Host " - Make sure your global CLAUDE.md contains the TTS summary instructions (see README.md)."
Write-Host " - Settings UI: python $Tools\configure.py"
Write-Host " - In Claude Code: /speak on|off|status|voice <name>"
```

- [ ] **Step 4: Test the merge script idempotence (against a fake HOME)**

```bash
cd /home/bat/git/claude-speak && HOME=/tmp/claude-1000/-home-bat-git-claude-speak/e1d8276e-de57-4a40-ae3e-9e60ce892ba0/scratchpad/fakehome python3 merge_hook.py && HOME=/tmp/claude-1000/-home-bat-git-claude-speak/e1d8276e-de57-4a40-ae3e-9e60ce892ba0/scratchpad/fakehome python3 merge_hook.py && cat /tmp/claude-1000/-home-bat-git-claude-speak/e1d8276e-de57-4a40-ae3e-9e60ce892ba0/scratchpad/fakehome/.claude/settings.json
```

Expected: first run prints "Stop hook added", second prints "already present"; the JSON contains exactly ONE Stop entry with `speak.py hook`.

- [ ] **Step 5: Commit**

```bash
git add install.sh install.ps1 merge_hook.py
git commit -m "feat(v2): installers with idempotent settings.json hook merge"
```

---

### Task 8: delete v1, rewrite README

**Files:**
- Delete: `claude-speak.py`, `cc-speak.py`, `Start-ClaudeWithSpeech.ps1`, `__pycache__/`
- Modify: `.gitignore` (add `__pycache__/` if absent)
- Rewrite: `README.md`
- Modify: `ROADMAP.md` (drop items that are now obsolete or shipped)

- [ ] **Step 1: Delete v1 files**

```bash
git rm claude-speak.py cc-speak.py Start-ClaudeWithSpeech.ps1
git rm -r --cached __pycache__ 2>/dev/null || true
rm -rf __pycache__
grep -q '__pycache__' .gitignore || echo '__pycache__/' >> .gitignore
```

- [ ] **Step 2: Verify nothing still references the deleted modules**

Run: `grep -rn "cc_speak\|cc-speak\|claude-speak.py\|speech-monitor\|snippet\|preamble" --include="*.py" --include="*.sh" --include="*.ps1" --include="*.html" --include="*.md" . | grep -v docs/superpowers | grep -v README.md`
Expected: no hits (README rewritten next step; spec/plan under docs/ may mention them historically).

- [ ] **Step 3: Rewrite `README.md`**

Structure (write real prose, keep the tone of the current README):

- Title + one-liner: "Spoken summaries for Claude Code. A Stop hook reads a short, marked summary of each response aloud — and stays silent otherwise."
- **How it works**: diagram `Claude Code --Stop hook--> speak.py hook --detached--> speak.py say --edge-tts--> speakers`; explanation of the strict `<!-- TTS_SUMMARY ... TTS_SUMMARY -->` marker and the silence-by-default rule.
- **Quick start**: clone, `./install.sh` / `.\install.ps1`, add the CLAUDE.md snippet, restart Claude Code.
- **TTS summary instructions** section: the exact CLAUDE.md snippet (copy the marker block from the spec — it is the same one currently in the user's global CLAUDE.md).
- **/speak skill** reference (on/off/status/voice).
- **Settings UI**: `python3 ~/.claude/tools/configure.py`.
- **Configuration** table: the four flag files + `CC_SPEAK_RATE` env var + debug flag `~/.claude/speech-debug` and log location.
- **Platform support** table (MCI/afplay/ffplay) and requirements (Python 3.8+, edge-tts, internet, ffmpeg on Linux).
- **Troubleshooting**: no sound → check `/speak status`, check hook registered in `~/.claude/settings.json`, touch `~/.claude/speech-debug` and read `~/.claude/tools/speak.log`; still hearing full responses → an old v1 monitor is running, kill it (`pkill -f claude-speak.py`).
- **v1 → v2 migration** note: v1 monitor and cc-speak removed; stop any running monitor; snippet/preamble/OpenAI backend dropped.

- [ ] **Step 4: Trim `ROADMAP.md`**

Remove entries about the monitor/debounce/intro modes; keep/add only still-relevant ideas (e.g. offline TTS backend).

- [ ] **Step 5: Run full test suite one more time**

Run: `cd /home/bat/git/claude-speak && python3 -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(v2)!: remove v1 monitor and engine, rewrite README for hook architecture"
```

---

### Task 9: install locally and end-to-end verification

**Files:** none (deployment + manual verification)

- [ ] **Step 1: Kill any running v1 monitor and clean stale files**

```bash
pkill -f "claude-speak.py" 2>/dev/null || true
rm -f ~/.claude/speech-monitor.pid ~/.claude/projects/*/speech-monitor.pid
rm -f ~/.claude/projects/*/speech-snippet ~/.claude/projects/*/speech-preamble
```

- [ ] **Step 2: Run the installer for real**

```bash
cd /home/bat/git/claude-speak && ./install.sh
```

Expected: edge-tts already present, files copied, "Stop hook added" (or "already present" on re-run), no errors. Verify: `cat ~/.claude/settings.json` contains the Stop hook entry; `ls ~/.claude/tools/` shows `speak.py`, `configure.py`, `settings.html`.

- [ ] **Step 3: Simulate a hook call end-to-end (audio must play)**

```bash
T=$(mktemp --suffix=.jsonl); printf '%s\n' '{"type":"assistant","uuid":"u1","message":{"id":"m1","content":[{"type":"text","text":"Corps de la réponse.\n\n<!-- TTS_SUMMARY\nCeci est un test de bout en bout de la version deux.\nTTS_SUMMARY -->"}]}}' > "$T"; echo "{\"transcript_path\":\"$T\",\"cwd\":\"$PWD\"}" | python3 ~/.claude/tools/speak.py hook; echo "exit=$?"
```

Expected: `exit=0` immediately (hook returns before audio finishes); the summary sentence is heard within a few seconds. Note: `/speak off` is currently active for this project — run `/speak on` first or use a different `cwd` value in the JSON.

- [ ] **Step 4: Negative test — no marker means silence**

```bash
T=$(mktemp --suffix=.jsonl); printf '%s\n' '{"type":"assistant","uuid":"u1","message":{"id":"m1","content":[{"type":"text","text":"Réponse sans marqueur du tout."}]}}' > "$T"; echo "{\"transcript_path\":\"$T\",\"cwd\":\"$PWD\"}" | python3 ~/.claude/tools/speak.py hook; echo "exit=$?"
```

Expected: `exit=0`, no audio, no output.

- [ ] **Step 5: Live verification in a real Claude Code session**

Ask the user to open a new Claude Code session (the hook loads at session start), run `/speak on`, ask any question, and confirm: only the summary is spoken, once, at the end of the response. Also verify `/speak off` then a question → silence.

- [ ] **Step 6: Final commit if fixes were needed, then done**

```bash
git status --short
```

Expected: clean tree (or commit any fixes made during verification with a `fix(v2): ...` message).
