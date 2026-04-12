# Auto-Generate Column Definitions (JSON Generation)

Automatically generates `column_definitions.json` from uploaded CSV files using Amazon Bedrock (Claude), so users no longer need to manually create column definition files.

## Overview

Column definitions help the analysis agents understand domain-specific column meanings (e.g., "sales" = net vs gross) and formulas. Previously, users had to manually author a JSON file — a barrier for non-technical users.

This feature reads the CSV header and sample rows, sends them to Claude Haiku via Bedrock, and returns a structured `column_definitions.json` for user review before upload.

## Workflow

```
User uploads CSV
       ↓
[🤖 Auto-generate] button appears as primary action
       ↓
Backend reads CSV header + 5 sample rows
       ↓
Bedrock Claude Haiku generates column definitions
       ↓
Review panel with Table / JSON toggle
       ↓
User: Confirm | Regenerate | Edit manually
       ↓
Confirmed JSON attached to upload as column_definitions.json
```

## Changes

### Backend (`deep-insight-web/app.py`)

- **New endpoint**: `POST /generate-column-definitions`
  - Accepts: `data_file` (CSV upload), `lang` (form field: `ko` or `en`)
  - Parses CSV header + first 5 sample rows using Python `csv` module
  - Calls `us.anthropic.claude-haiku-4-5-20251001-v1:0` via `bedrock-runtime` `invoke_model`
  - Strips markdown code fences from LLM response if present
  - Validates and returns parsed JSON array
  - Returns `{ success: true, column_definitions: [...] }`

### Frontend (`deep-insight-web/static/`)

#### `index.html`
- Restructured column definitions section for improved UX:
  - **Auto-generate button placed above** the manual upload drop zone as the primary action
  - "or" divider separates auto-generate (primary) from manual JSON upload (secondary)
  - `selected-coldef` display moved above both options for visibility when a file is confirmed
- Added review panel with:
  - Table/JSON view toggle button
  - Regenerate and Edit buttons
  - JSON editor (textarea) for manual edits
  - Table view (`<table>`) for readable column preview
  - Confirm and Cancel action buttons

#### `js/upload.js`
- `updateAutogenVisibility()` — Shows/hides auto-generate button and "or" divider together when a data file is selected but no column definition JSON is provided
- `hideAutogenArea()` — Hides auto-generate area, divider, review panel, and resets state
- `generateColdef()` — Calls `/generate-column-definitions` endpoint, hides divider on success
- `showColdefReview()` / `renderColdefTable()` — Renders generated definitions in both table and JSON views
- `toggleColdefView()` — Switches between table and JSON display modes
- `toggleColdefEdit()` — Toggles inline JSON editor with validation on exit
- `confirmColdef()` — Converts generated JSON to a `Blob`, attaches to upload `FormData`, hides divider
- `cancelColdef()` — Dismisses the review panel and resets state
- `refreshSelectedFileDisplays()` — Re-renders dynamically created file selection badges on language change (data file, coldef file, auto-generated coldef badge, review table headers)
- Modified upload form submission to include auto-generated column definitions when no manual file is provided

#### `js/i18n.js`
- Added Korean and English translations for all new UI elements:
  - Auto-generate button, description hint (`coldef_autogen_desc`), loading state, error messages
  - Review panel title, action buttons
  - Table/JSON toggle labels
  - Table column headers ("Column" / "Description")
- `applyLanguage()` now calls `refreshSelectedFileDisplays()` to update dynamically rendered text (e.g., "Selected:" / "선택됨:") on language toggle

#### `css/styles.css`
- `.btn-autogen-primary` — Prominent CTA button with gradient background, white text, `✨` icon, hover lift effect, and active press feedback
- `.coldef-autogen-desc` — Centered description text below the auto-generate button
- `.drop-zone-secondary` — Reduced-prominence drop zone for manual JSON upload (smaller padding, lower opacity)
- `.autogen-divider` — "or" divider with horizontal lines between primary and secondary options
- `.coldef-review-panel` — Review panel container with green accent border
- `.coldef-table` — Styled table with sticky header, hover rows, monospace column names
- `.btn-view-active` — Active state for view toggle button with accent shadow
- `.btn-sm` — Small button variant with slightly increased padding
- `.btn-outline` — Outline button with elevated background, box-shadow, hover lift/glow effect, and active press feedback

## User Experience

The auto-generate option is presented as the **primary** action for column definitions, with manual JSON upload as a secondary "or" alternative below it. This reduces friction for non-technical users who don't have a pre-authored JSON file.

```
Column Definitions (Recommended)
┌─────────────────────────────────────┐
│  🤖 Auto-generate Column Defs   ✨  │  ← Primary (gradient bg, prominent)
│  AI generates definitions from      │
│  your uploaded data file            │
└─────────────────────────────────────┘
              ── or ──
┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐
   📄 Drop JSON file here              ← Secondary (smaller, dashed)
└ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘
```

| User Type | Flow |
|-----------|------|
| No JSON file | Upload data file → Click "Auto-generate" (primary) → Review table → Confirm → Upload |
| Wants to customize | Auto-generate → Click "Edit" → Modify JSON → Confirm → Upload |
| Has JSON file | Upload data file → Scroll past auto-generate → Drop JSON (secondary) → Upload |

### Language Behavior

- Column descriptions are generated in the **language active at generation time** (Korean or English)
- Column names always match the original CSV headers regardless of language
- Switching language after generation does **not** auto-translate descriptions — user should click "Regenerate" to get descriptions in the new language
- All UI labels (buttons, table headers, file badges) update dynamically on language toggle

## Model Configuration

- **Model**: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (cross-region inference profile)
- **Max tokens**: 2048
- **Language**: Determined by the UI language toggle (Korean / English) at generation time
