# Release Management

## Versioning Strategy

This project uses **Semantic Versioning** (SemVer) with **git tags** and **GitHub Releases**.

- **MAJOR** (v2.0.0): Breaking changes to architecture or APIs
- **MINOR** (v1.1.0): New features or deployment modes (backwards-compatible)
- **PATCH** (v1.0.1): Bug fixes, documentation updates

Each version adds new directories to the repo. Existing directories are not modified after release (archived).

---

## Directory-per-Version Structure

Each deployment mode is a self-contained directory with its own `src/`, `data/`, `setup/`, and entry point. No cross-directory imports.

```
sample-deep-insight/
├── README.md                    ← repo-level (describes all versions)
├── CONTRIBUTING.md              ← repo-level
├── docs/                        ← repo-level shared docs
│
├── self-hosted/                 ← v1.0 — local execution
│   ├── src/                     ← agent logic (self-hosted version)
│   ├── main.py                  ← entry point
│   └── ...
│
├── managed-agentcore/           ← v1.0 — AgentCore deployment (CLI client)
│   ├── src/                     ← agent logic (managed version)
│   ├── agentcore_runtime.py     ← entry point
│   └── ...
│
├── deep-insight-web/            ← v1.1 — Web UI (FastAPI + HTML/JS)
│   ├── app.py                   ← FastAPI server
│   ├── static/                  ← Single-page UI (HTML/JS)
│   ├── deploy.sh                ← Automated deployment script
│   └── ...
│
└── (future versions added here)
```

When a version is released:
1. Code is promoted from `under-development/` to root level
2. `under-development/` is removed
3. README.md is updated
4. Git tag is created

---

## Release History

### v1.0.0 (2025-12)

**CLI-only release** — Deep Insight multi-agent data analysis system.

| Directory | Description |
|---|---|
| `self-hosted/` | Local execution on EC2/laptop |
| `managed-agentcore/` | Production deployment via Bedrock AgentCore + Fargate |

Features:
- Three-tier agent hierarchy (Coordinator → Planner → Supervisor → Tool Agents)
- Human-in-the-Loop (HITL) plan review via S3 polling
- DOCX report generation
- Skill system (Claude Code-style)
- Token tracking and observability

### v1.1.0 (2026-02)

**Web UI release** — adds browser-based interface for non-technical users.

| Directory | Description |
|---|---|
| `self-hosted/` | Unchanged from v1.0 |
| `managed-agentcore/` | Updated: S3 data_directory support, session_id in workflow_complete event |
| `deep-insight-web/` | Web server — FastAPI + plain HTML/JS, calls AgentCore via boto3 |

New features:
- Single-page web UI with dark theme and i18n (Korean/English)
- File upload (CSV/Excel/TSV/TXT/JSON) + column definitions to S3
- AgentCore Native Protocol (boto3) for web server ↔ AgentCore communication
- SSE streaming from AgentCore → web server → Browser (20min+ sessions)
- HITL plan review modal with approve/revise workflow
- Report download with artifact retry (S3 upload delay handling)
- Bundled sample data and sample reports for first-time users
- Internet-facing ALB with VPN CIDR restriction
- Automated deployment via `deploy.sh` (ECR, ALB, ECS Fargate, IAM)

---

## How to Create a Release

### 1. Tag

```bash
git tag -a v1.1.0 -m "v1.1.0: Web UI"
git push origin v1.1.0
```

### 2. GitHub Release

- Go to **Releases** → **Draft a new release**
- Select the tag
- Title: `v1.1.0: Web UI`
- Body: copy the release notes from this document
- Publish

### 3. Users access a specific version

```bash
# Latest
git clone https://github.com/aws-samples/sample-deep-insight.git

# Specific version
git clone --branch v1.0.0 https://github.com/aws-samples/sample-deep-insight.git
```

---

## Rules

1. **Never modify archived directories** — once tagged, `self-hosted/` and `managed-agentcore/` are frozen for that version
2. **Each directory is self-contained** — own `src/`, `data/`, `requirements.txt`, no cross-directory imports
3. **`under-development/` is temporary** — exists only during development, removed on release
4. **Root-level files evolve** — `README.md`, `CONTRIBUTING.md`, `docs/` are updated with each release
5. **One branch (`main`)** — no release branches needed for a sample repo; use git tags
