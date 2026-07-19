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

MARKER_RE = re.compile(r"<!--\s*TTS_SUMMARY\s*(.*?)\s*TTS_SUMMARY\s*-->", re.DOTALL)


def log(msg):
    """Append a debug line to log_path(), only when the debug flag file exists."""
    if not os.path.exists(debug_flag()):
        return
    try:
        import datetime
        os.makedirs(os.path.dirname(log_path()), exist_ok=True)
        with open(log_path(), "a", encoding="utf-8") as f:
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
