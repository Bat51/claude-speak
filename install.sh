#!/usr/bin/env bash
# claude-speak v2 installer (Linux/macOS)
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
TOOLS="$HOME/.claude/tools"
SKILLS="$HOME/.claude/skills/speak"

command -v python3 >/dev/null || { echo "ERROR: python3 not found"; exit 1; }

python3 -c "import edge_tts" 2>/dev/null || {
  echo "Installing edge-tts..."
  python3 -m pip install --user edge-tts 2>/dev/null || python3 -m pip install --user --break-system-packages edge-tts || { echo "ERROR: could not install edge-tts. Try: pipx install edge-tts"; exit 1; }
}

if [[ "$(uname)" == "Linux" ]] && ! command -v ffplay >/dev/null; then
  echo "WARNING: ffplay not found - audio will not play. Install with: sudo apt install ffmpeg"
fi

mkdir -p "$TOOLS" "$SKILLS"

# Remove stale v1 links and any existing targets (a prior install may have
# symlinked these back into the repo, which would make cp fail)
rm -f "$TOOLS/cc-speak.py" "$TOOLS/claude-speak.py"
rm -f "$TOOLS/speak.py" "$TOOLS/configure.py" "$TOOLS/settings.html" "$SKILLS/SKILL.md"

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
