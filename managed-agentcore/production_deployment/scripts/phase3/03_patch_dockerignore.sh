#!/bin/bash
# 03_patch_dockerignore.sh
#
# Purpose: Patch bedrock_agentcore_starter_toolkit's dockerignore.template so the
#          runtime image gets the files it needs and none of the ones it doesn't:
#
#            1. Include src/prompts/*.md -- the template's blanket *.md rule would
#               otherwise drop every agent prompt and the runtime fails at startup.
#            2. Exclude artifacts/ -- local analysis output from previous runs.
#               It is dead weight in the image, and because CodeBuild copies it in
#               as root the runtime (a non-root user) cannot clean it up, which
#               surfaces as a "Permission denied" error on every first execution.
#
#          Both patches have to live here rather than in the repository's own
#          .dockerignore: the toolkit filters the CodeBuild source zip with this
#          template unconditionally (see services/codebuild.py, "Always uses the
#          dockerignore.template"), so .dockerignore never reaches the build.
#
#          Run after 02_create_uv_env.sh -- the template only exists once the
#          virtual environment has installed the toolkit.
#
# Usage:
#   cd production_deployment/scripts/phase3/
#   ./03_patch_dockerignore.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/.venv/lib/python3.12/site-packages/bedrock_agentcore_starter_toolkit/utils/runtime/templates/dockerignore.template"

echo "🔧 Patching dockerignore.template..."

# Check if template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "❌ Error: Template file not found at: $TEMPLATE_FILE"
    echo "   Make sure you've run 02_create_uv_env.sh first!"
    exit 1
fi

# Back up once, before the first modification of this run
BACKUP_MADE=false
ensure_backup() {
    if [ "$BACKUP_MADE" = false ]; then
        cp "$TEMPLATE_FILE" "$TEMPLATE_FILE.backup"
        echo "📄 Backup created: $TEMPLATE_FILE.backup"
        BACKUP_MADE=true
    fi
}

restore_and_fail() {
    echo "❌ Patch failed: $1"
    echo ""
    echo "   Template structure:"
    grep -n "Documentation\|\.md\|README\|artifacts" "$TEMPLATE_FILE" || echo "   (no relevant patterns found)"
    echo ""
    if [ "$BACKUP_MADE" = true ]; then
        mv "$TEMPLATE_FILE.backup" "$TEMPLATE_FILE"
        echo "   Template restored from backup."
    fi
    exit 1
}

# ---------------------------------------------------------------------------
# Patch 1: include agent prompts (must come after the template's *.md exclusion)
# ---------------------------------------------------------------------------
if grep -qF "!src/prompts/*.md" "$TEMPLATE_FILE"; then
    echo "✅ [1/2] Prompts already included."
else
    ensure_backup
    echo "🔍 [1/2] Including src/prompts/*.md..."

    if grep -qF "!README.md" "$TEMPLATE_FILE"; then
        echo "   Found !README.md anchor, adding after it..."
        sed -i '/!README\.md/a !src/prompts/*.md' "$TEMPLATE_FILE"
    elif grep -q "^\*\.md$" "$TEMPLATE_FILE"; then
        echo "   No anchor found, adding after *.md exclusion..."
        sed -i '/^\*\.md$/a !src/prompts/*.md' "$TEMPLATE_FILE"
    elif grep -q "^# Documentation" "$TEMPLATE_FILE"; then
        echo "   Adding in Documentation section..."
        sed -i '/^# Documentation/a *.md\n!src/prompts/*.md' "$TEMPLATE_FILE"
    else
        echo "   Adding at end of file..."
        printf '\n# Include prompt templates\n!src/prompts/*.md\n' >> "$TEMPLATE_FILE"
    fi

    grep -qF "!src/prompts/*.md" "$TEMPLATE_FILE" \
        || restore_and_fail "expected to find !src/prompts/*.md"
    echo "   ✅ Applied."
fi

# ---------------------------------------------------------------------------
# Patch 2: exclude previous runs' analysis output
# ---------------------------------------------------------------------------
if grep -qE "^artifacts/$" "$TEMPLATE_FILE"; then
    echo "✅ [2/2] artifacts/ already excluded."
else
    ensure_backup
    echo "🔍 [2/2] Excluding artifacts/..."
    # Appended rather than inserted: this is a plain exclusion with no matching
    # negation, so its position relative to the other rules does not matter.
    printf '\n# Analysis output from local runs; never belongs in the image\nartifacts/\n' >> "$TEMPLATE_FILE"

    grep -qE "^artifacts/$" "$TEMPLATE_FILE" \
        || restore_and_fail "expected to find artifacts/"
    echo "   ✅ Applied."
fi

echo ""
echo "Effective rules:"
grep -nE "^\*\.md$|^!src/prompts|^artifacts/$" "$TEMPLATE_FILE" | sed 's/^/  /'
echo ""
echo "🎉 Done! The toolkit will ship the prompts and skip stale analysis output."
