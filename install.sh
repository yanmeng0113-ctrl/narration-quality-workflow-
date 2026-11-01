#!/bin/sh
# Install this skill as <skills-dir>/eddyy-skill-narration-quality.
# An existing install is renamed into <skills-dir>/.backups/, never deleted.
set -eu

SKILL_ID="eddyy-skill-narration-quality"
LEGACY_ID="narration-quality-workflow"
SRC_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
TARGET_ROOT="${SKILLS_DIR:-${CODEX_HOME:-$HOME/.codex}/skills}"
DRY_RUN=0

usage() {
  echo "Usage: $0 [--target SKILLS_DIR] [--dry-run]"
  echo "Default target: \$SKILLS_DIR, else \${CODEX_HOME:-\$HOME/.codex}/skills"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --target)
      [ $# -ge 2 ] || { usage >&2; exit 2; }
      TARGET_ROOT="$2"; shift 2 ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
done

if ! grep -q "^name: $SKILL_ID\$" "$SRC_DIR/SKILL.md"; then
  echo "error: SKILL.md name is not $SKILL_ID; run from the skill checkout" >&2
  exit 1
fi

DEST="$TARGET_ROOT/$SKILL_ID"
STAMP=$(date +%Y%m%d%H%M%S)
BACKUP="$TARGET_ROOT/.backups/$SKILL_ID.bak-$STAMP-$$"

echo "source: $SRC_DIR"
echo "target: $DEST"
[ -e "$DEST" ] && echo "existing install will be moved to: $BACKUP"
[ -e "$TARGET_ROOT/$LEGACY_ID" ] && echo "warning: legacy $TARGET_ROOT/$LEGACY_ID exists and is left untouched; remove or back it up yourself to avoid loading two copies" >&2
[ "$DRY_RUN" -eq 1 ] && { echo "dry run: nothing changed"; exit 0; }

mkdir -p "$TARGET_ROOT"
STAGE=$(mktemp -d "$TARGET_ROOT/.install-$SKILL_ID.XXXXXX")
trap 'rm -rf "$STAGE"' EXIT

for item in SKILL.md README.md CHANGELOG.md LICENSE references examples scripts; do
  cp -R "$SRC_DIR/$item" "$STAGE/"
done
find "$STAGE" \( -name __pycache__ -o -name '*.pyc' -o -name workdir \) -prune -exec rm -rf {} +

if [ -e "$DEST" ]; then
  mkdir -p "$TARGET_ROOT/.backups"
  mv "$DEST" "$BACKUP"
fi
mv "$STAGE" "$DEST"
chmod 755 "$DEST"
trap - EXIT

echo "installed: $DEST"
echo "verify: python3 -m unittest discover -s \"$DEST/scripts\" -p 'test_*.py'"
