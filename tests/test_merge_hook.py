import json
import os
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(home):
    env = dict(os.environ, HOME=str(home))
    return subprocess.run(
        [sys.executable, os.path.join(REPO, "merge_hook.py")],
        capture_output=True, text=True, env=env, timeout=30,
    )


def test_merge_hook_idempotent(tmp_path):
    first = _run(tmp_path)
    assert first.returncode == 0
    second = _run(tmp_path)
    assert second.returncode == 0
    assert "already present" in second.stdout
    settings = json.load(open(os.path.join(str(tmp_path), ".claude", "settings.json")))
    entries = [h for g in settings["hooks"]["Stop"] for h in g["hooks"]
               if "speak.py" in h["command"]]
    assert len(entries) == 1
    assert '"' in entries[0]["command"]  # quoted path


def test_merge_hook_recognizes_old_unquoted_entry(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    old = {"hooks": {"Stop": [{"hooks": [{"type": "command",
           "command": "python3 %s hook" % os.path.join(str(tmp_path), ".claude", "tools", "speak.py")}]}]}}
    (claude / "settings.json").write_text(json.dumps(old))
    result = _run(tmp_path)
    assert result.returncode == 0
    assert "already present" in result.stdout


def test_merge_hook_preserves_other_settings_and_backs_up(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text(json.dumps({"model": "opus", "hooks": {"PostToolUse": []}}))
    result = _run(tmp_path)
    assert result.returncode == 0
    settings = json.load(open(claude / "settings.json"))
    assert settings["model"] == "opus"
    assert settings["hooks"]["PostToolUse"] == []
    assert len(settings["hooks"]["Stop"]) == 1
    assert (claude / "settings.json.bak").exists()


def test_merge_hook_aborts_on_invalid_json(tmp_path):
    claude = tmp_path / ".claude"
    claude.mkdir()
    (claude / "settings.json").write_text("{broken")
    result = _run(tmp_path)
    assert result.returncode == 1
    assert (claude / "settings.json").read_text() == "{broken"
