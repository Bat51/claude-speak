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
