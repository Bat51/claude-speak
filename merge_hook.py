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
