#!/bin/bash
# patch_dockerignore_template.sh
#
# Purpose: Patch bedrock_agentcore_starter_toolkit's dockerignore.template
#          to include src/prompts/*.md files in Docker builds
#
# Usage:
#   cd setup/
#   ./patch_dockerignore_template.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE_FILE="$SCRIPT_DIR/.venv/lib/python3.12/site-packages/bedrock_agentcore_starter_toolkit/utils/runtime/templates/dockerignore.template"

echo "🔧 Patching dockerignore.template to include src/prompts/*.md files..."

# Check if template file exists
if [ ! -f "$TEMPLATE_FILE" ]; then
    echo "❌ Error: Template file not found at: $TEMPLATE_FILE"
    echo "   Make sure you've run 'uv sync' first!"
    exit 1
fi

# Check if already patched (use literal string match)
if grep -qF "!src/prompts/*.md" "$TEMPLATE_FILE"; then
    echo "✅ Template already patched!"
    exit 0
fi

# Create backup
cp "$TEMPLATE_FILE" "$TEMPLATE_FILE.backup"
echo "📄 Backup created: $TEMPLATE_FILE.backup"

# Apply patch - try multiple strategies
echo "🔍 Analyzing template structure..."

if grep -qF "!README.md" "$TEMPLATE_FILE"; then
    # Strategy 1: Anchor exists - add after !README.md
    echo "   Found !README.md anchor, adding after it..."
    sed -i '/!README\.md/a !src/prompts/*.md' "$TEMPLATE_FILE"
elif grep -q "^\*\.md$" "$TEMPLATE_FILE"; then
    # Strategy 2: No anchor, but *.md exists - add after it
    echo "   No anchor found, adding after *.md exclusion..."
    sed -i '/^\*\.md$/a !src/prompts/*.md' "$TEMPLATE_FILE"
elif grep -q "^# Documentation" "$TEMPLATE_FILE"; then
    # Strategy 3: Add after Documentation section header
    echo "   Adding in Documentation section..."
    sed -i '/^# Documentation/a *.md\n!src/prompts/*.md' "$TEMPLATE_FILE"
else
    # Strategy 4: Append at end of file
    echo "   Adding at end of file..."
    echo -e "\n# Include prompt templates\n!src/prompts/*.md" >> "$TEMPLATE_FILE"
fi

# Verify patch (use literal asterisk match)
if grep -qF "!src/prompts/*.md" "$TEMPLATE_FILE"; then
    echo "✅ Patch applied successfully!"
    echo ""
    echo "Modified section:"
    grep -B 1 -A 1 "!src/prompts" "$TEMPLATE_FILE"
    echo ""
else
    echo "❌ Patch failed!"
    echo ""
    echo "   Expected to find: !src/prompts/*.md"
    echo "   Template structure:"
    grep -n "Documentation\|\.md\|README" "$TEMPLATE_FILE" || echo "   (no relevant patterns found)"
    echo ""
    # Restore backup
    mv "$TEMPLATE_FILE.backup" "$TEMPLATE_FILE"
    exit 1
fi

echo ""
echo "🎉 Done! The toolkit will now include prompt template files in Docker builds."
