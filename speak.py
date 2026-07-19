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
