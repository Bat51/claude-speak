#!/usr/bin/env python3
"""Merge the claude-speak Stop hook into ~/.claude/settings.json (idempotent)."""

import json
import os
import shutil
import sys


def main():
    settings_path = os.path.join(os.path.expanduser("~"), ".claude", "settings.json")
    python_cmd = "python" if os.name == "nt" else "python3"
    script_path = os.path.join(os.path.expanduser("~"), ".claude", "tools", "speak.py")
    hook_cmd = '%s "%s" hook' % (python_cmd, script_path)

    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except ValueError:
            print("ERROR: %s is not valid JSON; fix it first." % settings_path)
            sys.exit(1)

    if not isinstance(settings.get("hooks"), dict):
        settings["hooks"] = {}
    if not isinstance(settings["hooks"].get("Stop"), list):
        settings["hooks"]["Stop"] = []
    stop_groups = settings["hooks"]["Stop"]
    for group in stop_groups:
        for h in group.get("hooks", []):
            command = h.get("command", "")
            if 'speak.py" hook' in command or "speak.py hook" in command:
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
