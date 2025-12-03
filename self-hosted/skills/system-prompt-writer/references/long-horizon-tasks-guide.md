# Long-Horizon Tasks Guide

This guide provides patterns for agents that handle **long-running, complex tasks** spanning multiple context windows or extended sessions.

**Part of the system-prompt-writer skill** - See `SKILL.md` for core principles.

## When to Use This Guide

Use this guide **only** when your agent needs to:

- Execute tasks that span multiple context windows
- Maintain state across extended sessions
- Handle complex workflows with many steps
- Track progress on long-running operations

**Most agents don't need this.** Standard system prompts (covered in `SKILL.md`) are sufficient for typical use cases.

## Related Files

- **SKILL.md** - Core prompt writing principles (start here)
- **examples.md** - Standard agent examples
- **section-organization-guide.md** - Prompt structure guidance

---

## Multi-Context Window Workflows

Claude 4 models excel at **long-horizon reasoning** and **state tracking**. For tasks spanning multiple context windows, establish a framework in the first window.

### First Context Window: Framework Setup

In the first context window, establish:

1. **Test file** (`tests.json`) - Track what needs to be done and current status
2. **Setup script** (`init.sh`) - Initialize environment for each session
3. **Progress file** (`progress.txt`) - Human-readable progress notes

#### tests.json Pattern

Use JSON for structured state tracking:

```json
{
  "tests": [
    {"id": 1, "name": "authentication_flow", "status": "passing"},
    {"id": 2, "name": "user_management", "status": "failing"},
    {"id": 3, "name": "api_endpoints", "status": "not_started"}
  ],
  "total": 200,
  "passing": 150,
  "failing": 25,
  "not_started": 25
}
```

**Key principle:** Tests should be immutable once defined.

```
It is unacceptable to remove or edit tests without explicit approval.
```

#### init.sh Pattern

Create a setup script for consistent session initialization:

```bash
#!/bin/bash
# init.sh - Run at start of each session

# Start necessary services
./start_server.sh

# Run test suite to check current state
python -m pytest tests/ --tb=short

# Run linters
ruff check src/

# Show current progress
cat progress.txt
```

#### progress.txt Pattern

Use plain text for human-readable progress notes:

```
Session 3 progress:
- Fixed authentication token validation
- Updated user model to handle edge cases
- Next: investigate user_management test failures

Session 2 progress:
- Implemented basic user CRUD operations
- Added input validation
- Discovered edge case in token refresh

Session 1 progress:
- Set up project structure
- Created initial test suite (200 tests)
- Implemented database models
```

---

## State Management Strategy

| Purpose | Format | File | Example |
|---------|--------|------|---------|
| Structured task tracking | JSON | `tests.json`, `tasks.json` | Test status, task completion |
| Progress notes | Plain text | `progress.txt` | Session summaries, next steps |
| Version history | Git | Commits, logs | Code changes, decision history |
| Configuration | JSON/YAML | `config.json` | Environment settings |

### Why Multiple Formats?

- **JSON**: Machine-readable, easy to query and update programmatically
- **Plain text**: Human-readable, good for context and narrative
- **Git**: Provides history, rollback capability, and diff visibility

---

## Context Persistence Prompts

### Prompt: Save State Before Compaction

Include this pattern when context window may be compacted:

```xml
<context_persistence>
Your context window will be automatically compacted when it reaches capacity.
Before this happens:
1. Save current progress to progress.txt
2. Update tests.json with current status
3. Commit any code changes with descriptive message
4. Document next steps clearly

Always be as persistent and autonomous as possible and complete tasks fully.
</context_persistence>
```

### Prompt: Starting Fresh Context

When starting a new context window (not continuing from compaction):

```xml
<session_start>
At the start of each session:
1. Run `pwd` to confirm working directory
2. Review progress.txt for previous session notes
3. Check tests.json for current task status
4. Review recent git log for context
5. Run init.sh to verify environment state
6. Run fundamental integration tests before new work

You can only read/write files in the designated project directory.
</session_start>
```

---

## System Prompt Template: Long-Horizon Agent

Use this template for agents handling extended, multi-session tasks:

```markdown
## Role
<role>
You are a [specific role] handling complex, multi-step tasks that may span multiple sessions.
Your objective is to [clear goal] while maintaining consistent progress.
</role>

## State Management
<state_management>
Track your work using these files:
- tests.json: Structured task/test status (JSON)
- progress.txt: Session notes and next steps (text)
- Git: All code changes with descriptive commits

Update these files as you complete work. Never leave state only in memory.
</state_management>

## Session Protocol
<session_protocol>
At session start:
1. Review progress.txt and tests.json
2. Check git log for recent changes
3. Run verification tests
4. Continue from documented next steps

Before session end or context limit:
1. Update progress.txt with session summary
2. Update tests.json with current status
3. Commit all changes
4. Document clear next steps
</session_protocol>

## Instructions
<instructions>
- Focus on incremental progress - complete one task fully before starting next
- Verify each step before proceeding
- Document decisions and rationale
- Test changes before committing
- [Domain-specific instructions]
</instructions>

## Constraints
<constraints>
- Do not remove or modify existing tests without approval
- Always save state before context compaction
- Commit frequently with meaningful messages
- [Domain-specific constraints]
</constraints>
```

---

## Example: Multi-Session Refactoring Agent

```markdown
## Role
<role>
You are a code refactoring specialist handling a large-scale migration project.
Your objective is to migrate the codebase from Framework A to Framework B while maintaining all functionality.
</role>

## State Management
<state_management>
Track migration progress:
- migration_status.json: Component status (pending/in_progress/completed/verified)
- progress.txt: Session notes, blockers, decisions
- Git: All changes with "[MIGRATION]" prefix in commit messages

Update status immediately when completing each component.
</state_management>

## Session Protocol
<session_protocol>
Session start:
1. cat progress.txt | tail -50
2. python scripts/check_migration_status.py
3. git log --oneline -10
4. Run smoke tests: pytest tests/smoke/

Before ending:
1. Update migration_status.json
2. Add session summary to progress.txt
3. git add . && git commit -m "[MIGRATION] Session N: [summary]"
4. Note any blockers or questions for next session
</session_protocol>

## Migration Rules
<instructions>
- Migrate one component at a time
- Run component tests after each migration
- Preserve all existing behavior
- Document any API changes
- If stuck on a component, document blocker and move to next
</instructions>

## Constraints
<constraints>
- Never delete old implementation until new passes all tests
- Do not modify test assertions (only test setup if needed)
- Maximum 3 components per session to ensure quality
- Always leave codebase in working state
</constraints>
```

---

## Key Principles

1. **State lives outside context** - Never rely solely on context memory for important state
2. **Incremental progress** - Complete and verify small chunks rather than large changes
3. **Explicit handoff** - Document clearly what the next session should do
4. **Verify before proceed** - Run tests/checks after each significant change
5. **Immutable tests** - Tests define success criteria; don't modify them to pass

---

## When NOT to Use These Patterns

These patterns add overhead. Skip them when:

- Task completes in a single session
- State tracking isn't needed
- Simple, stateless query-response agent
- Agent doesn't modify persistent state

For standard agents, use the basic templates in `SKILL.md` instead.

---

**Return to main skill:** See `SKILL.md` for core prompt writing principles.
