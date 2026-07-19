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


# ─── cmd_say lock/cleanup behavior ────────────────────────────────────────────

import tempfile


def _mp3_path():
    return os.path.join(tempfile.gettempdir(), "claude_speak_%d.mp3" % os.getpid())


def test_cmd_say_skips_playback_without_lock(fake_home, tmp_path, monkeypatch):
    played = []

    def fake_synth(text, voice, rate, path):
        with open(path, "wb") as f:
            f.write(b"mp3")
        return True

    monkeypatch.setattr(speak, "synthesize", fake_synth)
    monkeypatch.setattr(speak, "play", lambda p: played.append(p) or True)
    monkeypatch.setattr(speak, "acquire_play_lock", lambda timeout_sec=90: False)
    tf = tmp_path / "t.txt"
    tf.write_text("hello world")
    speak.cmd_say(str(tf), "some-voice")
    assert played == []
    assert not os.path.exists(_mp3_path())


def test_cmd_say_removes_partial_mp3_on_synth_failure(fake_home, tmp_path, monkeypatch):
    def fake_synth_fail(text, voice, rate, path):
        with open(path, "wb") as f:
            f.write(b"partial")
        return False

    monkeypatch.setattr(speak, "synthesize", fake_synth_fail)
    tf = tmp_path / "t.txt"
    tf.write_text("hello world")
    speak.cmd_say(str(tf), "some-voice")
    assert not os.path.exists(_mp3_path())


def test_cmd_say_plays_and_cleans_up_with_lock(fake_home, tmp_path, monkeypatch):
    played = []

    def fake_synth(text, voice, rate, path):
        with open(path, "wb") as f:
            f.write(b"mp3")
        return True

    monkeypatch.setattr(speak, "synthesize", fake_synth)
    monkeypatch.setattr(speak, "play", lambda p: played.append(p) or True)
    tf = tmp_path / "t.txt"
    tf.write_text("hello world")
    speak.cmd_say(str(tf), "some-voice")
    assert played == [_mp3_path()]
    assert not os.path.exists(_mp3_path())
    assert not os.path.exists(speak.lock_path())


# ─── CLI invariant: hook is always silent, always exit 0 ─────────────────────

import subprocess


def test_cli_hook_garbage_input_silent_exit_zero(tmp_path):
    env = dict(os.environ, CC_SPEAK_HOME=str(tmp_path))
    proc = subprocess.run(
        [sys.executable, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "speak.py"), "hook"],
        input=b"not json at all",
        capture_output=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout == b""
    assert proc.stderr == b""
