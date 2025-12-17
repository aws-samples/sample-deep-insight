# Claude Code-style Skill System for Strands Agents

A dynamic skill discovery and loading system that brings Claude Code's skill architecture to Strands Agent SDK, enabling agents to load specialized instructions on-demand.

## Overview

The Skill System allows agents to dynamically discover and load specialized skills (detailed instructions, code examples, best practices) without bloating the system prompt. Skills are loaded lazily—only when needed—reducing token usage and improving response quality.

**Key Benefits:**
- **Lazy Loading**: Skills loaded on-demand, not at startup
- **Dynamic Discovery**: Auto-detect skills from directory structure
- **Modular Design**: Add new skills without code changes
- **Token Efficient**: Only active skills consume context tokens

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Agent Startup                           │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │ SkillDiscovery  │ ← Scan ./skills/        │
│                    │ (metadata only) │   for SKILL.md files    │
│                    └────────┬────────┘                         │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │  System Prompt  │ ← Add <available_skills>│
│                    │   + skill list  │   section to prompt     │
│                    └────────┬────────┘                         │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │  Agent Ready    │                         │
│                    └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                      Runtime (On-Demand)                        │
│                              │                                  │
│                              ▼                                  │
│            User: "Help me process this PDF"                     │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │  Agent decides  │ ← Sees 'pdf' in         │
│                    │  to use skill   │   available_skills      │
│                    └────────┬────────┘                         │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │   skill_tool    │ ← Load full SKILL.md    │
│                    │ (skill_name=pdf)│   content (lazy load)   │
│                    └────────┬────────┘                         │
│                              │                                  │
│                              ▼                                  │
│                    ┌─────────────────┐                         │
│                    │ Agent follows   │ ← PDF processing        │
│                    │ skill guidance  │   instructions loaded   │
│                    └─────────────────┘                         │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Skill Discovery (`discovery.py`)

Scans skill directories and extracts metadata from SKILL.md files:

```python
from src.utils.skills.discovery import SkillDiscovery

discovery = SkillDiscovery(skill_dirs=["./skills"])
available_skills = discovery.discover()
# Returns: {'pdf': {'description': '...', 'path': '...', 'metadata': {...}}, ...}
```

**Features:**
- Recursive directory scanning (`rglob("SKILL.md")`)
- YAML frontmatter parsing for metadata
- Duplicate skill detection and warnings
- Graceful error handling

### 2. Skill Loader (`loader.py`)

Lazily loads full skill content when invoked:

```python
from src.utils.skills.loader import SkillLoader

loader = SkillLoader(available_skills)
content = loader.load("pdf")  # Returns full SKILL.md content
```

**Features:**
- No caching (always reads latest file content)
- Clear error messages for missing skills
- Minimal memory footprint

### 3. Skill Tool (`skill_tool.py`)

Strands SDK-compatible tool for agent skill invocation:

```python
from src.tools.skill_tool import skill_tool, setup_skill_tool

# Initialize (done by skill_utils.initialize_skills)
setup_skill_tool(loader, available_skills)

# Agent calls skill_tool with skill_name parameter
# Returns: <skill name='pdf'>...full content...</skill>
```

### 4. Skill Utils (`skill_utils.py`)

Orchestrates initialization and generates system prompt:

```python
from src.utils.skills.skill_utils import initialize_skills

available_skills, skill_prompt = initialize_skills(
    skill_dirs=["./skills"],
    verbose=True
)

# Append to your base prompt
system_prompt = base_prompt + skill_prompt
```

## SKILL.md Format

Each skill is defined by a `SKILL.md` file with YAML frontmatter:

```markdown
---
name: pdf
description: Comprehensive PDF manipulation toolkit for extracting text and tables, creating new PDFs, merging/splitting documents, and handling forms.
license: MIT
allowed-tools:
  - bash_tool
  - file_read
  - file_write
---

# PDF Processing Guide

## Overview
This guide covers essential PDF processing operations...

## Quick Start
```python
from pypdf import PdfReader, PdfWriter

reader = PdfReader("document.pdf")
print(f"Pages: {len(reader.pages)}")
```

## Common Tasks
...detailed instructions, code examples, best practices...
```

### Required Fields

| Field | Description |
|-------|-------------|
| `name` | Unique skill identifier (used in `skill_tool(skill_name="...")`) |
| `description` | Brief explanation shown in available skills list |

### Optional Fields

| Field | Description |
|-------|-------------|
| `license` | License information |
| `allowed-tools` | List of tools this skill may use |

## Directory Structure

```
skills/
├── pdf/
│   └── SKILL.md
├── document-skills/
│   ├── docx/
│   │   └── SKILL.md
│   ├── xlsx/
│   │   └── SKILL.md
│   └── pptx/
│       └── SKILL.md
├── mcp-builder/
│   └── SKILL.md
└── template-skill/
    └── SKILL.md
```

Nested directories are fully supported—the discovery process scans recursively.

## Usage Example

### main.py

```python
from src.tools import skill_tool, bash_tool
from strands_tools import file_read, file_write
from src.utils.skills.skill_utils import initialize_skills
from src.utils.strands_sdk_utils import strands_utils

# 1. Initialize skill system
_, skill_prompt = initialize_skills(
    skill_dirs=["./skills"],
    verbose=True
)

# 2. Build system prompt
base_prompt = """You are a helpful assistant..."""
system_prompt = base_prompt + skill_prompt

# 3. Create agent with skill_tool
agent = strands_utils.get_agent(
    agent_name="skill_agent",
    system_prompts=system_prompt,
    tools=[skill_tool, bash_tool, file_read, file_write],
    streaming=True
)

# 4. Agent can now invoke skills on-demand
# When user asks about PDF processing, agent will:
#   1. See 'pdf' in available_skills
#   2. Call skill_tool(skill_name="pdf")
#   3. Receive full PDF processing instructions
#   4. Follow those instructions to help user
```

## System Prompt Generation

The `initialize_skills()` function generates a prompt section like:

```markdown
## Skill System
<skill_instructions>
You have access to specialized skills that provide detailed guidance for specific tasks.
Use skill_tool to load relevant skill instructions when working on specialized tasks.

How to use skills:
- Invoke skills using skill_tool with the skill name
- The skill's prompt will expand and provide detailed instructions
- Follow the loaded skill instructions precisely to complete the task

Important:
- Only use skills listed in <available_skills> below
- Do not invoke a skill that is already loaded in the current conversation
- Skills provide code examples, best practices, and domain-specific guidance
</skill_instructions>

<available_skills>
  - pdf: Comprehensive PDF manipulation toolkit for extracting text...
  - docx: Microsoft Word document processing and generation...
  - xlsx: Excel spreadsheet analysis and manipulation...
</available_skills>
```

## Available Skills (Reference Implementation)

| Skill | Description |
|-------|-------------|
| `pdf` | PDF manipulation: extract text/tables, merge/split, forms |
| `docx` | Word document processing and generation |
| `xlsx` | Excel spreadsheet analysis |
| `pptx` | PowerPoint presentation creation |
| `mcp-builder` | Model Context Protocol server development |
| `tool-creator` | Custom tool development for agents |
| `skill-creator` | Creating new skills |
| `algorithmic-art` | Generative art creation |
| `canvas-design` | Visual design and canvas manipulation |
| `webapp-testing` | Web application testing |

## Creating New Skills

1. **Create directory**: `skills/my-skill/`

2. **Create SKILL.md**:
```markdown
---
name: my-skill
description: Brief description of what this skill does and when to use it.
---

# My Skill Guide

## Overview
Explain what this skill helps with...

## Quick Start
Show the simplest example...

## Detailed Instructions
Provide comprehensive guidance...
```

3. **Restart agent** - Skill is automatically discovered

## Best Practices

1. **Write clear descriptions** - Helps agent decide when to use the skill
2. **Include code examples** - Agents perform better with concrete examples
3. **Structure with headers** - Use `##` sections for easy navigation
4. **Keep skills focused** - One skill per domain/task type
5. **Test incrementally** - Verify skill loads correctly before adding content

## Key Files

| File | Purpose |
|------|---------|
| `src/utils/skills/discovery.py` | Skill directory scanning and metadata extraction |
| `src/utils/skills/loader.py` | Lazy loading of full skill content |
| `src/tools/skill_tool.py` | Strands SDK tool wrapper |
| `src/utils/skills/skill_utils.py` | Initialization orchestration |
| `skills/*/SKILL.md` | Individual skill definitions |

## Reference Implementation

A complete reference implementation is available at:
`/home/ubuntu/projects/strands-skill-system/`

This includes:
- Full skill system implementation
- 18 pre-built skills
- Interactive demo with streaming responses
- Bash and file operation tools integration

## Troubleshooting

### Skill not discovered

- Verify `SKILL.md` exists in skill directory
- Check YAML frontmatter has `name` and `description`
- Ensure no YAML syntax errors (validate with online parser)

### Skill not loading

- Check skill name matches exactly (case-sensitive)
- Verify file path is accessible
- Check logs for error messages

### Agent not using skills

- Verify `skill_tool` is in agent's tools list
- Check system prompt includes `<available_skills>` section
- Ensure skill description clearly indicates when to use it
