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
    try:
        if not synthesize(text, voice, DEFAULT_RATE, mp3):
            return
        if not acquire_play_lock():
            log("say: could not acquire playback lock, skipping")
            return
        try:
            play(mp3)
        finally:
            release_play_lock()
    finally:
        try:
            os.remove(mp3)
        except OSError:
            pass


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
