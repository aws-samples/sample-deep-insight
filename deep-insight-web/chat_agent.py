"""
Deep Insight Web — Data Q&A Chat Agent (DuckDB / SQL mode)

Strands Agent SDK chatbot that converts natural language to SQL,
executes on an in-memory DuckDB loaded from the user's uploaded CSV,
and visualizes results with matplotlib charts.

Compared to the pandas-exec variant, SQL mode gives the user:
  - Visible SQL the agent is running (audit / learn)
  - The ability to edit SQL and re-run without the LLM (see /sql/execute)
  - Narrower exec() surface (only the chart code runs in sandbox)
"""

import base64
import io
import json
import logging
import os
import re
import tempfile
import threading
import time
from pathlib import Path

import duckdb
import pandas as pd
import numpy as np

import boto3
from botocore.config import Config
from strands import Agent, tool
from strands.models.bedrock import BedrockModel
from strands.models.model import CacheConfig
from strands.agent.conversation_manager import SlidingWindowConversationManager

logger = logging.getLogger(__name__)

# ---------- Configuration ----------

AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
S3_BUCKET_NAME = os.environ.get("S3_BUCKET_NAME", "")
CHAT_MODEL_ID = os.environ.get(
    "CHAT_MODEL_ID", "global.anthropic.claude-sonnet-4-6"
)
# Prompt caching: on by default for Claude models. The system prompt (Rules +
# schema) and tool specs are static across a session, so caching them yields
# ~90% input-token savings on repeat turns. Set to "0" to disable for debugging.
ENABLE_PROMPT_CACHE = os.environ.get("ENABLE_PROMPT_CACHE", "1") != "0"
# Upload root defaults to a path under the system temp dir; override with
# UPLOAD_DIR when the container mounts a dedicated writable volume.
LOCAL_UPLOAD_DIR = Path(
    os.environ.get("UPLOAD_DIR", os.path.join(tempfile.gettempdir(), "deep-insight-uploads"))
)

# Strict allow-list for upload_id. CodeQL's path-injection taint analysis
# recognizes regex.fullmatch on `^[allowed-chars]+$` as a sanitizer barrier;
# the looser `Path.resolve().relative_to(root)` check we previously used does
# the same job at runtime but is not part of CodeQL's known sanitizer set,
# so the alert kept re-firing. Re-enforcing here at the chat_agent.py boundary
# is also defense in depth — app.py validates request bodies, but anything
# importing chat_agent.session_manager directly bypasses that layer.
_UPLOAD_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MAX_UPLOAD_ID_LEN = 64


def _check_upload_id(upload_id: str) -> str:
    """Return the upload_id only if it passes the strict allow-list.

    Raises ValueError otherwise. By design rejects "..", "/", "\\", and any
    character that could traverse out of LOCAL_UPLOAD_DIR.
    """
    if not isinstance(upload_id, str) or not upload_id \
            or len(upload_id) > _MAX_UPLOAD_ID_LEN \
            or not _UPLOAD_ID_RE.fullmatch(upload_id):
        raise ValueError("Invalid upload_id")
    return upload_id


def _safe_join_under_upload_dir(*parts: str) -> Path:
    """Join `parts` under LOCAL_UPLOAD_DIR and assert the result stays inside.

    Uses `os.path.realpath` + `os.path.commonpath`, which CodeQL recognizes
    as a path-traversal sanitizer barrier. Raises ValueError if the joined
    path escapes the upload root via "..", a symlink, or a literal "/".
    """
    root = os.path.realpath(str(LOCAL_UPLOAD_DIR))
    candidate = os.path.realpath(os.path.join(root, *parts))
    # commonpath raises if drives differ on Windows; Path objects on macOS/
    # Linux give a stable answer.
    try:
        if os.path.commonpath([root, candidate]) != root:
            raise ValueError("Path escapes upload root")
    except ValueError:
        raise ValueError("Path escapes upload root") from None
    return Path(candidate)


EXEC_TIMEOUT = 30
TEXT_OUTPUT_LIMIT = 10_000
IMAGE_SIZE_LIMIT = 500_000

# Default DuckDB table name for the uploaded CSV
DEFAULT_TABLE = "data"


# ---------- Helpers: file discovery (S3 + local, shared with /upload) ----------


def _list_upload_files(upload_id: str) -> list[tuple[str, bytes]]:
    """Return list of (filename, bytes) for files uploaded under upload_id.

    Supports both S3 mode (if S3_BUCKET_NAME set) and local mode.

    `upload_id` is re-validated here even though app.py also validates at
    each endpoint — this is the boundary CodeQL's path-injection analysis
    sees, and any future caller importing this module directly skips the
    HTTP-layer check.
    """
    upload_id = _check_upload_id(upload_id)
    files: list[tuple[str, bytes]] = []

    if S3_BUCKET_NAME:
        s3 = boto3.client("s3", region_name=AWS_REGION)
        prefix = f"uploads/{upload_id}/"
        response = s3.list_objects_v2(Bucket=S3_BUCKET_NAME, Prefix=prefix)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            filename = key.removeprefix(prefix)
            body = s3.get_object(Bucket=S3_BUCKET_NAME, Key=key)["Body"].read()
            files.append((filename, body))
    else:
        # _check_upload_id already rejected "..", "/", and "\". This realpath
        # + commonpath check below is defense-in-depth against symlink shenan-
        # igans inside LOCAL_UPLOAD_DIR.
        try:
            local_dir = _safe_join_under_upload_dir(upload_id)
        except ValueError:
            return files
        if local_dir.exists():
            for p in sorted(local_dir.iterdir()):
                if p.is_file():
                    files.append((p.name, p.read_bytes()))

    return files


def _find_csv_and_coldef(upload_id: str) -> tuple[str, bytes, dict | None]:
    """Locate the CSV file and (optional) column_definitions.json for an upload.

    Returns (csv_filename, csv_bytes, column_definitions_dict_or_None).
    """
    files = _list_upload_files(upload_id)
    csv_name, csv_bytes = None, None
    coldef: dict | list | None = None

    for name, data in files:
        if name == "column_definitions.json":
            try:
                coldef = json.loads(data)
            except Exception as e:
                logger.warning(f"Failed to parse column_definitions.json: {e}")
        elif name.lower().endswith(".csv"):
            csv_name, csv_bytes = name, data

    if not csv_bytes:
        raise FileNotFoundError(f"No CSV file found for upload_id={upload_id}")

    return csv_name, csv_bytes, coldef


# ---------- ChatSession ----------


class ChatSession:
    """Per-upload session: DuckDB connection, loaded table, and Strands Agent.

    Thread safety: DuckDB does not allow a single connection to be used from
    multiple threads concurrently. The agent runs in a background thread while
    /sql/execute or /chat/meta requests may hit the same session from the main
    async worker. We serialize all DB access behind `self.db_lock` and always
    go through `self.run_query(...)` (which uses a fresh cursor).
    """

    def __init__(self, upload_id: str):
        self.upload_id = upload_id
        self.agent: Agent | None = None
        self.conn: duckdb.DuckDBPyConnection | None = None
        self.db_lock = threading.Lock()
        self.table_name: str = DEFAULT_TABLE
        self.column_definitions: list | dict | None = None
        self.schema_summary: str = ""
        self.row_count: int = 0
        self.csv_filename: str = ""
        self.side_channel: list = []
        self._tmp_csv_path: Path | None = None
        # Serializes one-time setup (load + lockdown) against concurrent
        # callers. Without this, /chat/meta and /chat/suggestions firing on
        # page load can both pass the `if self.conn is not None` guard and
        # then race on `SET lock_configuration=true`, which only permits one
        # call per connection. RLock so ensure_agent_created can call
        # ensure_data_loaded under the same lock without deadlocking.
        self._init_lock = threading.RLock()
        # Time of last activity (chat / sql exec / meta) used by the session
        # manager for idle-eviction. Updated on every touch().
        self.last_active: float = time.time()

    # ---- Thread-safe DB helpers ----

    def run_query(self, sql: str, params=None):
        """Execute SQL under the session lock using a fresh cursor.

        Returns the cursor, from which callers can `.fetchall()`, `.fetchone()`,
        or `.df()`. Cursors are cheap and isolate each call from the shared
        connection state, which is the pattern DuckDB recommends for concurrent
        access on one connection.
        """
        assert self.conn is not None, "DB not loaded"
        with self.db_lock:
            cur = self.conn.cursor()
            if params is None:
                return cur.execute(sql)
            return cur.execute(sql, params)

    def ensure_data_loaded(self):
        """Load CSV from upload storage into an in-memory DuckDB table.

        Idempotent + thread-safe: page load fires /chat/meta and
        /chat/suggestions in parallel and both may hit a fresh session.
        Without the lock, both threads pass the `self.conn is None` check,
        race to load the CSV, and the second `SET lock_configuration=true`
        fails ("configuration has been locked").
        """
        # Fast path without taking the lock.
        if self.conn is not None:
            return
        with self._init_lock:
            # Re-check inside the lock — another thread may have just loaded.
            if self.conn is not None:
                return
            self._load_data_locked()

    def _load_data_locked(self) -> None:
        """Body of ensure_data_loaded; caller must hold self._init_lock."""
        # Re-check upload_id against the strict allow-list at the boundary
        # where it flows into a path. This is what CodeQL recognizes as the
        # path-injection sanitizer.
        upload_id = _check_upload_id(self.upload_id)

        csv_name, csv_bytes, coldef = _find_csv_and_coldef(upload_id)
        self.csv_filename = csv_name
        self.column_definitions = coldef

        # csv_name came back from S3 / disk listing — treat it as untrusted.
        # Take the basename and reject "."/".." or any path separator before
        # using it. _UPLOAD_ID_RE-style allow-list isn't appropriate here
        # because legitimate filenames include spaces / Korean / dots.
        safe_csv_name = os.path.basename(csv_name)
        if not safe_csv_name or safe_csv_name in (".", "..") \
                or "/" in safe_csv_name or "\\" in safe_csv_name \
                or "\x00" in safe_csv_name:
            raise ValueError(f"Unsafe CSV name in upload {upload_id}")

        # Write CSV to a tmp file DuckDB can read from (read_csv_auto needs
        # a path). Build via realpath/commonpath so CodeQL sees the sanitizer.
        tmp_path = _safe_join_under_upload_dir(upload_id, f"_chat_{safe_csv_name}")
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(csv_bytes)

        self.conn = duckdb.connect(":memory:")
        # Track tmp CSV for cleanup on session close.
        self._tmp_csv_path = tmp_path
        # Register the CSV as a table named `data`. read_csv_auto infers types.
        self.run_query(
            f"CREATE TABLE {self.table_name} AS "
            f"SELECT * FROM read_csv_auto(?, header=True)",
            [str(tmp_path)],
        )
        self.row_count = self.run_query(
            f"SELECT COUNT(*) FROM {self.table_name}"
        ).fetchone()[0]

        # Seal the session against external filesystem / network / extension
        # access. The user can edit SQL in the Q&A UI, so we must prevent
        # `COPY ... TO '/tmp/leak.csv'`, `INSTALL`/`LOAD`, `ATTACH 'http://...'`,
        # and similar escape paths. Must run AFTER the initial read_csv_auto
        # because that itself uses LocalFileSystem.
        self.run_query("SET enable_external_access=false")
        self.run_query(
            "SET disabled_filesystems="
            "'LocalFileSystem,HTTPFileSystem,S3FileSystem'"
        )
        self.run_query("SET lock_configuration=true")

        self._build_schema_summary()
        logger.info(
            f"ChatSession loaded: upload_id={self.upload_id}, "
            f"rows={self.row_count}, table={self.table_name}"
        )

    def _build_schema_summary(self) -> None:
        """Build a human-readable schema summary for the system prompt."""
        cols = self.run_query(
            f"DESCRIBE {self.table_name}"
        ).fetchall()  # (name, type, null, key, default, extra)

        lines = [f"Table: {self.table_name}  (rows: {self.row_count:,})", "Columns:"]

        # Build description lookup from column_definitions.json (optional)
        desc_by_name: dict[str, str] = {}
        if isinstance(self.column_definitions, list):
            for item in self.column_definitions:
                if not isinstance(item, dict):
                    continue
                name = item.get("column_name") or item.get("name")
                desc = item.get("column_desc") or item.get("description") or ""
                if name:
                    desc_by_name[str(name)] = str(desc)

        for row in cols:
            col_name, col_type = row[0], row[1]
            desc = desc_by_name.get(col_name, "")
            sample_vals = self._sample_distinct_values(col_name, col_type)
            parts = [f"  - {col_name} ({col_type})"]
            if desc:
                parts.append(f": {desc}")
            if sample_vals:
                parts.append(f"  [examples: {sample_vals}]")
            lines.append("".join(parts))

        self.schema_summary = "\n".join(lines)

    def _sample_distinct_values(self, col: str, col_type: str) -> str:
        """Return a short comma-joined string of up to 5 distinct values for hints."""
        try:
            # Skip huge blob-y types
            if "BLOB" in col_type.upper():
                return ""
            rows = self.run_query(
                f'SELECT DISTINCT "{col}" FROM {self.table_name} '
                f'WHERE "{col}" IS NOT NULL LIMIT 5'
            ).fetchall()
            vals = [str(r[0]) for r in rows if r[0] is not None]
            short = [v if len(v) <= 30 else v[:27] + "..." for v in vals]
            return ", ".join(short)
        except Exception:
            return ""

    def ensure_agent_created(self):
        """Create the Strands Agent with tools bound to this session's connection."""
        if self.agent is not None:
            return
        with self._init_lock:
            if self.agent is not None:
                return
            self._create_agent_locked()

    def _create_agent_locked(self) -> None:
        """Body of ensure_agent_created; caller must hold self._init_lock."""
        self.ensure_data_loaded()
        tools = _create_tools(self, self.side_channel)

        # Prompt caching: the system prompt (Rules + per-dataset schema) and
        # tool specs are invariant across a session. Caching them drops repeat-
        # turn input cost to ~10% (Bedrock ephemeral cache, 5-minute TTL).
        # `cache_config=auto` also adds a cache point on the most recent user
        # message so conversation history benefits as it grows.
        # Bound the Bedrock call: without read_timeout a hung response holds
        # both the background agent thread and the SSE connection indefinitely.
        # Values mirror managed-agentcore/src/utils/strands_sdk_utils.py but
        # are tighter (Q&A turns are short, not 15-min analysis).
        bedrock_kwargs: dict = {
            "model_id": CHAT_MODEL_ID,
            "region_name": AWS_REGION,
            "boto_client_config": Config(
                read_timeout=120,
                connect_timeout=10,
                retries=dict(max_attempts=3, mode="adaptive"),
            ),
        }
        # Build system prompt. When caching is on, attach a cachePoint block so
        # Bedrock caches the (large, invariant) system prompt across turns.
        # This is the SystemContentBlock form Strands recommends; it replaces
        # the deprecated `cache_prompt` kwarg on BedrockModel.
        system_prompt_text = _build_system_prompt(self.schema_summary, self.table_name)
        if ENABLE_PROMPT_CACHE:
            system_prompt_value: str | list = [
                {"text": system_prompt_text},
                {"cachePoint": {"type": "default"}},
            ]
            bedrock_kwargs["cache_tools"] = "default"
            bedrock_kwargs["cache_config"] = CacheConfig(strategy="auto")
            logger.info(
                f"Prompt caching ENABLED for upload_id={self.upload_id} "
                f"(system prompt block + tools + messages)"
            )
        else:
            system_prompt_value = system_prompt_text

        model = BedrockModel(**bedrock_kwargs)

        self.agent = Agent(
            model=model,
            system_prompt=system_prompt_value,
            tools=tools,
            conversation_manager=SlidingWindowConversationManager(window_size=30),
        )

    def touch(self) -> None:
        """Mark the session as recently active (used by LRU/idle eviction)."""
        self.last_active = time.time()

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        self.agent = None
        # Clean up the tmp CSV copy DuckDB read from. /tmp is ephemeral but
        # filling it under load is still bad — Fargate's writable layer is
        # small and shared across requests.
        if self._tmp_csv_path is not None:
            try:
                self._tmp_csv_path.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(
                    f"Failed to unlink tmp CSV {self._tmp_csv_path}: {e}"
                )
            self._tmp_csv_path = None


# ---------- SessionManager ----------


# Eviction tunables (overridable via env). Defaults are tuned for a 2 GB
# Fargate task with ~5 concurrent users and 50 MB CSVs (≈ 1.5 GB worst case).
SESSION_MAX = int(os.environ.get("CHAT_SESSION_MAX", "20"))
SESSION_IDLE_TTL_SEC = int(os.environ.get("CHAT_SESSION_IDLE_TTL_SEC", "1800"))


class SessionManager:
    """LRU + idle-TTL bounded session cache.

    Each ChatSession pins (DuckDB :memory: ≈ CSV size) + (pandas df ≈ CSV size)
    + (Strands agent history) + (a tmp CSV on disk). Without bounds, sessions
    accumulate for the lifetime of the container. We evict on every access:

      1. Drop sessions whose `last_active` is older than IDLE_TTL_SEC.
      2. If still over MAX, drop the least-recently-active sessions.

    Eviction calls `session.close()` which releases the DuckDB connection,
    drops the agent (and its conversation history), and unlinks the tmp CSV.
    """

    def __init__(self):
        # Insertion-order dict + last_active on each session is enough — we
        # don't need OrderedDict.move_to_end because eviction sorts by
        # last_active anyway.
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def get_or_create(self, upload_id: str) -> ChatSession:
        with self._lock:
            session = self._sessions.get(upload_id)
            if session is None:
                session = ChatSession(upload_id)
                self._sessions[upload_id] = session
            session.touch()
            # Evict AFTER insert+touch so the just-added session has the
            # newest last_active and won't be selected as the LRU victim.
            self._evict_locked()
            return session

    def remove(self, upload_id: str):
        with self._lock:
            session = self._sessions.pop(upload_id, None)
        if session:
            session.close()

    def _evict_locked(self) -> None:
        """Drop idle and over-cap sessions. Caller must hold self._lock."""
        now = time.time()
        # 1) Idle eviction.
        idle_keys = [
            k for k, s in self._sessions.items()
            if (now - s.last_active) > SESSION_IDLE_TTL_SEC
        ]
        for k in idle_keys:
            s = self._sessions.pop(k, None)
            if s:
                logger.info(
                    f"SessionManager: idle-evict upload_id={k} "
                    f"(idle={int(now - s.last_active)}s)"
                )
                try:
                    s.close()
                except Exception:
                    pass

        # 2) LRU eviction if still over cap.
        overflow = len(self._sessions) - SESSION_MAX
        if overflow > 0:
            ranked = sorted(
                self._sessions.items(), key=lambda kv: kv[1].last_active
            )
            for k, s in ranked[:overflow]:
                self._sessions.pop(k, None)
                logger.info(f"SessionManager: lru-evict upload_id={k}")
                try:
                    s.close()
                except Exception:
                    pass


session_manager = SessionManager()


# ---------- Suggestions (dynamic, based on schema) ----------


def generate_suggestions(upload_id: str) -> list[str]:
    """Generate 3 example questions based on the uploaded CSV's columns.

    Heuristic (no LLM call — fast path for the welcome screen):
      - If a datelike/연도/월/date column exists → propose a trend question
      - If a category-looking column exists → propose a TOP-N question
      - Fallback → basic summary
    """
    try:
        session = session_manager.get_or_create(upload_id)
        session.ensure_data_loaded()
        cols = session.run_query(
            f"DESCRIBE {session.table_name}"
        ).fetchall()
    except Exception as e:
        logger.warning(f"generate_suggestions failed: {e}")
        return _default_suggestions()

    col_names = [c[0] for c in cols]
    col_types = {c[0]: c[1].upper() for c in cols}

    date_like = next(
        (c for c in col_names
         if re.search(r"date|time|연도|년|월|일", c, re.IGNORECASE)
         or "TIMESTAMP" in col_types[c] or "DATE" in col_types[c]),
        None,
    )
    numeric_col = next(
        (c for c in col_names
         if any(t in col_types[c] for t in ["INT", "DOUBLE", "DECIMAL", "FLOAT", "BIGINT"])),
        None,
    )
    category_col = next(
        (c for c in col_names
         if "VARCHAR" in col_types[c] and c != date_like),
        None,
    )

    suggestions: list[str] = []
    if numeric_col:
        suggestions.append(f"{numeric_col}의 기본 통계를 보여줘")
    if category_col and numeric_col:
        suggestions.append(
            f"{category_col}별 {numeric_col} 합계 TOP 5를 차트로 보여줘"
        )
    if date_like and numeric_col:
        suggestions.append(
            f"{date_like}별 {numeric_col} 추이를 라인 차트로 보여줘"
        )

    if not suggestions:
        suggestions = _default_suggestions()
    return suggestions[:3]


def _default_suggestions() -> list[str]:
    return [
        "데이터의 기본 통계를 보여줘",
        "상위 5개 항목을 차트로 보여줘",
        "컬럼 간 관계를 시각화해줘",
    ]


# ---------- System Prompt ----------


def _build_system_prompt(schema_summary: str, table_name: str) -> str:
    return f"""You are a data analyst assistant. You help users explore an uploaded CSV dataset, stored in a DuckDB in-memory database, by converting natural-language questions into SQL.

## Dataset Schema
{schema_summary}

The table name is `{table_name}`. You MUST query this table via SQL — never guess values.

## CRITICAL RULES — Tool Usage
- You MUST use tools for ALL data questions. NEVER estimate, guess, or compute in your head.
- For ANY data question: use `query_sql` with a DuckDB SQL query.
- For ANY visualization request (chart/graph/plot/trend/distribution): use `create_chart` which takes BOTH the SQL and the matplotlib code.
- To re-inspect the schema: use `describe_schema`.
- The tools render tables/charts/SQL directly to the user. You do not need to paste them in your text.

## SQL Generation Rules
- Always use DuckDB SQL syntax.
- Always quote column names with double quotes if they contain non-ASCII, spaces, or punctuation: `"컬럼명"`.
- Use `NULLIF(x, 0)` for safe division.
- Use `ROUND(x, 2)` for percentages and ratios.
- Prefer aggregations (`GROUP BY`) over returning raw millions of rows.
- Sort outputs meaningfully: rankings by value DESC, time series by time ASC.

## Chart Rules
- `create_chart(sql, chart_code)` runs the SQL and binds the result DataFrame to `df` for the chart code.
- A pre-built matplotlib `fig` and `ax` are provided. Use the OO API: `ax.plot(...)`, `ax.bar(...)`, `ax.set_title(...)`, etc.
- ALWAYS set a descriptive title via `ax.set_title(...)`, and axis labels via `ax.set_xlabel(...)` / `ax.set_ylabel(...)` when useful.
- Write labels in the same language as the user's question (Korean by default).
- Korean fonts and a clean light theme are pre-configured — do NOT set `rcParams`, `style.use`, or fonts inside `chart_code`.
- A consistent brand color palette (orange-led: `#E68A1F`, blue, teal, purple, gray, pink) is pre-configured via `axes.prop_cycle`. Do NOT pass `color=`, `c=`, `palette=`, or `cmap=` arguments to `ax.bar`, `ax.barh`, `ax.plot`, `ax.scatter`, `sns.barplot`, etc. — let matplotlib pick from the cycle. Specifying a color manually overrides the brand palette and produces inconsistent visuals across the app.
- For heatmaps (`sns.heatmap`, `ax.imshow`), ALWAYS use `cmap='Blues'`. Do NOT pick other colormaps (예: `YlOrRd`, `viridis`, `RdYlGn`) to match the orange bar palette — heatmaps and bar charts intentionally use different color systems: bars encode *categories* via prop_cycle, heatmaps encode *value magnitude* via a sequential blue ramp.
- Do NOT import or call `plt` (matplotlib.pyplot) directly. Do NOT call `plt.show()`, `plt.savefig()`, `plt.close()`, or `plt.figure()` — the tool handles all of that.
- For multi-axis layouts use `fig.subplots(...)` to add more axes; do NOT call `plt.subplots`.

## Chart Type Selection (avoid antipatterns)
- Trends over time → `ax.plot` (with `marker='o'` if ≤ 20 points).
- Category comparison or share/proportion → horizontal bar (`ax.barh`), sorted by value descending. Pie charts are FORBIDDEN — they degrade fast as categories grow and Korean labels overlap.
- Distribution of one numeric variable → `ax.hist` (bins=20) or `ax.boxplot`.
- N >= 8 categories on a single chart: keep top 7, aggregate the rest into a single "기타" / "Other" row BEFORE plotting. Do NOT render every category.
- Korean category labels on a vertical bar overlap. Default to horizontal (`ax.barh`) whenever any label has > 4 Korean chars or there are > 6 categories.
- Two categorical axes (cross-tab pattern: `GROUP BY cat_A, cat_B` with one numeric aggregate) — DO NOT split into multiple bar charts side by side. Pick ONE single chart based on the shape:
    * `|cat_A| ≥ 4 AND |cat_B| ≥ 4` → heatmap (`sns.heatmap(..., annot=True, fmt='d')` or `ax.imshow` + `ax.text`).
    * One side is small (`min(|cat_A|, |cat_B|) ≤ 3`) → grouped horizontal bar with `hue=` set to the smaller side.
    * One axis is a time series (월/년/날짜) → small multiples line (per-series line chart, ≤ 5 series), NOT a heatmap.
    * Question asks for "TOP N" or ranking → sorted horizontal bar, optionally with `hue` if a secondary categorical exists.
  Signal phrases that imply this pattern even without literal "비교": "A별 B의 차이/선호도/분포/패턴".
- For horizontal bar with N items, set `fig.set_size_inches(10, max(4, 0.4 * N))` so labels never collide.
- When annotating bar values, ALWAYS use `ax.bar_label(container, padding=4, fmt=lambda v: f"{{v:,.0f}}")` (or with a unit suffix, e.g. `fmt=lambda v: f"{{v:,.0f}}만원"`). The `fmt` argument MUST be a callable — NEVER pass an old-style format string like `"%,.0f"`. Python's `%` formatter does not support thousands comma and will print the format spec verbatim onto the chart.
- NEVER hand-place value labels with `ax.text(...)` or a manual `for i, v in enumerate(...)` loop. Such loops desync from the bar order whenever the SQL result is sorted differently from the draw order, which produces labels attached to the wrong bars (a silent data-correctness bug). `bar_label` always tracks the container's actual draw order.
- ALWAYS hide top + right spines on bar/line/scatter charts: `ax.spines['top'].set_visible(False); ax.spines['right'].set_visible(False)`. Without this, value labels at the bar end visibly collide with the right spine.
- Extend the value-axis limit by ~25% so labels don't run off the figure edge: `ax.set_xlim(0, max(values) * 1.25)` for horizontal bars, `ax.set_ylim(0, max(values) * 1.20)` for vertical bars. Manual `ax.text` value labels MUST also leave a gap of ≥ 2% of the axis range.

## Time-Series Specific
- Plot at most 5 series on a single line chart. With > 5 series the chart becomes spaghetti.
- If the SQL returns > 5 categories over time, FILTER to the top 5 by total value in the SQL itself (e.g. `WHERE category IN (top 5 from a subquery)`) — do NOT plot all categories then "trust the legend".
- Sort the x-axis chronologically and rotate date labels: `ax.tick_params(axis='x', rotation=30)`.

## Axes Hygiene (prevent overlapping/empty axes)
- The provided `ax` is the ONLY axes you should use by default. Do NOT call `ax.twinx()`, `ax.twiny()`, or `fig.add_subplot(...)`. If a question truly needs two y-scales, draw two separate `create_chart` calls instead of overlaying.
- If a small-multiples layout is justified (e.g. comparing 2 groups side by side), you MAY replace the default axes ONCE: `fig.clear(); axes = fig.subplots(1, 2)` — this REMOVES the original `ax` so there is no leftover empty 0.0–1.0 axes underneath. Never call `fig.subplots(...)` without `fig.clear()` first.
- Place the legend OUTSIDE the axes when present: `ax.legend(bbox_to_anchor=(1.02, 1), loc='upper left', borderaxespad=0)`. Never let legend boxes cover the data.
- Always call `fig.tight_layout()` as the last line of `chart_code` to prevent label clipping.

## Korean Currency Formatting
- KRW values almost always exceed 6 digits, which makes raw 원 labels (예: `1,820,044원`) collide with axis ticks and bar ends. ALWAYS scale to a friendlier unit before plotting:
  - 1,000 ≤ value < 1,000,000 → divide by 1,000, label unit as "천원"
  - 1,000,000 ≤ value < 100,000,000 → divide by 10,000, label unit as "만원"
  - value ≥ 100,000,000 → divide by 100,000,000, label unit as "억원"
- Apply the scale to BOTH bar values AND axis tick labels. Use `FuncFormatter(lambda v, _: f"{{v/10000:,.0f}}")` (만원 case) so ticks read "150" not "1500000". Use f-string formatting only — do NOT use old-style `format(v, ',.0f')` or `"%,.0f"` strings.
- Reflect the scale in the axis label: `ax.set_xlabel('매출액 (만원)')`. Never leave the scientific notation tag (`1e6`) on the axis — it always means the unit is wrong.
- Bar value labels follow the same scale (예: `153만원 (17.9%)`), NOT raw 원 (예: `1,533,901원 (17.88%)`). To attach the unit, divide the values BEFORE plotting (`df["amount_만원"] = df["amount"] / 10000`) and pass `fmt=lambda v: f"{{v:,.0f}}만원"` to `bar_label`. Do NOT divide inside the lambda — the bar heights you pass to `ax.barh` must already be in the chosen unit so axis ticks and label values agree.
- ALWAYS use Python f-string formatting (`f"{{v:,.0f}}"`, `f"{{p:.1f}}%"`) — round percentages to 1 decimal place and currency to whole units. Never embed raw `float` directly in a label (Python prints `16.939999999999998` for what should be `16.9%`).

## Response Rules (Insight-first — do NOT produce empty "interpretation" filler)
- FIRST sentence must be a headline insight that includes a specific number from the result
  (예: "30대가 전체의 42%로 최대 구매층" / "A점이 전년 대비 +18% 성장으로 유일한 증가 지점").
- THEN 1–2 sentences explaining the driver, outlier, or imbalance, citing concrete values
  (절댓값, 비중 %, 격차, 순위 등). Read the numbers from the tool's returned data summary.
- If there is a clear business implication, state it in ONE short sentence
  (예: "시니어 간편식 라인업 확대 여지가 큼").
- Target length: 3–5 sentences. No chart/table description
  ("차트입니다" / "표입니다" 금지).
- Light markdown is OK for emphasis: use **bold** to highlight the headline number
  or a single key phrase (max 1–2 times per answer). Do NOT use headings (#), tables
  (|), bullet lists, or code blocks — those are reserved for the tool output.
- BANNED filler phrases — NEVER use these, they are meaningless:
    "특정 X에서 ~", "일부 ~", "경향이 있으며", "경향을 보입니다",
    "확인할 수 있습니다", "다양한 패턴이 보입니다", "전반적으로 ~한 모습".
- Always quantify. If you cannot name a number, do not make the point.
- Answer in the user's language (default Korean).

## NEVER show both a table and a chart for the same question — pick ONE:
  * Chart for trends / comparisons / distributions / visual patterns.
  * Table only when the user explicitly asks for exact numbers without a chart.
  * When in doubt → chart.

## Suggested Follow-up Questions
- At the END of every response, append 2–3 follow-up questions the user may want next.
- Base them on the schema + current conversation.
- Format exactly as: [SUGGESTIONS]q1|q2|q3[/SUGGESTIONS]
- Same language as the user.
"""


# ---------- Sandboxed Chart Execution ----------


def _safe_exec(code: str, extra_globals: dict, timeout: int = EXEC_TIMEOUT) -> dict:
    """Run matplotlib chart code in a restricted sandbox with a timeout.

    TRUST BOUNDARY — read this before adding caller paths.

    The only intended caller is `create_chart`, where `code` is produced by an
    LLM that has been given a constrained system prompt and a SQL-only data
    surface. We block the obvious escape hatches (`__import__`, `open`,
    `exec`, `eval`, `compile`, `breakpoint`, `exit`, `quit`, `input`) but the
    sandbox is NOT robust against an attacker with arbitrary code-injection
    capability. Specifically, the classic Python sandbox escape
    `().__class__.__base__.__subclasses__()` is reachable from here and gives
    access to file/process primitives.

    Implications:
      - Do NOT call `_safe_exec` with user-supplied code (e.g. from a chat
        message or HTTP body) without an additional trust layer.
      - If the LLM is ever exposed to direct prompt injection from the user's
        data file or chat message, this becomes a remote-code-execution path
        on the container. Any future change that broadens the input surface
        MUST tighten the sandbox first (AST allowlist + multiprocessing
        worker with rlimits is the recommended replacement).
    """
    safe_builtins = {
        k: v for k, v in __builtins__.items()
        if k not in (
            "__import__", "open", "exec", "eval", "compile",
            "breakpoint", "exit", "quit", "input",
        )
    } if isinstance(__builtins__, dict) else {
        k: getattr(__builtins__, k)
        for k in dir(__builtins__)
        if k not in (
            "__import__", "open", "exec", "eval", "compile",
            "breakpoint", "exit", "quit", "input",
        ) and not k.startswith("_")
    }

    exec_globals = {"__builtins__": safe_builtins, **extra_globals}
    result_container = {"result": None, "error": None}

    def _run():
        try:
            exec(code, exec_globals)
            result_container["result"] = exec_globals.get("result")
        except Exception as e:
            result_container["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=timeout)

    if thread.is_alive():
        return {"error": f"Execution timed out after {timeout} seconds"}

    return result_container


# ---------- Shared: format a result DataFrame as the chat HTML table ----------


def _format_df_html(df: pd.DataFrame) -> str:
    formatted = df.copy()
    for col in formatted.select_dtypes(include=["number"]).columns:
        formatted[col] = formatted[col].apply(
            lambda x: f"{x:,.0f}" if pd.notna(x) and abs(x) >= 1 and x == int(x)
            else (f"{x:,.2f}" if pd.notna(x) else "")
        )
    # escape=True is the pandas default but we set it explicitly: this HTML is
    # injected with innerHTML on the client (chat.js), so any future contributor
    # flipping escape would silently open an XSS hole via CSV cell content.
    return formatted.to_html(
        classes="chat-table", index=False, border=0, escape=True
    )


def _df_summary_for_llm(df: pd.DataFrame, top_n: int = 10) -> str:
    """Build a compact numeric summary the agent can cite in its response.

    Goal: give the LLM *actual numbers* it can quote — headline insights need
    concrete values. Without this, the agent is blind to the tool's output and
    falls back to filler like "경향이 있음을 확인할 수 있음".

    Returns a short text block with:
      - Total row count
      - Top N rows (as a table)
      - Numeric column stats: min / max / mean / sum
      - For single numeric-column aggregates, percent share of each row
    """
    if df is None or df.empty:
        return "(empty result)"

    lines: list[str] = [f"rows: {len(df):,}"]

    # Head rows
    head = df.head(top_n)
    lines.append("top_rows:\n" + head.to_string(index=False))

    # Numeric stats
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()
    if num_cols:
        stats_parts = []
        for c in num_cols:
            s = df[c]
            try:
                total = float(s.sum())
                stats_parts.append(
                    f"  {c}: min={s.min():,.4g} max={s.max():,.4g} "
                    f"mean={s.mean():,.4g} sum={total:,.4g}"
                )
            except Exception:
                pass
        if stats_parts:
            lines.append("stats:\n" + "\n".join(stats_parts))

    # Share-of-total hint: if exactly one numeric column and few rows, add %
    if len(num_cols) == 1 and len(df) <= 20:
        c = num_cols[0]
        try:
            total = float(df[c].sum())
            if total != 0:
                shares = (df[c] / total * 100).round(1)
                # Build "label: value (pct%)" lines if there is a label-like col
                label_cols = [col for col in df.columns if col != c]
                if label_cols:
                    lab = label_cols[0]
                    rows = []
                    for i, row in df.iterrows():
                        rows.append(f"  {row[lab]}: {row[c]:,.4g} ({shares[i]}%)")
                    lines.append("share_of_total:\n" + "\n".join(rows))
        except Exception:
            pass

    return "\n".join(lines)


# ---------- Chart rendering (matplotlib OO API, thread-safe) ----------


# Resolve the Korean font name once at import time. fontManager.ttflist scan is
# expensive and the result is process-stable.
_KOREAN_FONT_NAME: str | None = None


def _resolve_korean_font() -> str | None:
    global _KOREAN_FONT_NAME
    if _KOREAN_FONT_NAME is not None:
        return _KOREAN_FONT_NAME or None
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.font_manager as fm
        for name in ["NanumGothic", "NanumBarunGothic", "Malgun Gothic", "AppleGothic"]:
            if any(name == f.name for f in fm.fontManager.ttflist):
                _KOREAN_FONT_NAME = name
                return name
        # koreanize_matplotlib registers a fallback into the global font cache.
        # We still don't use plt.rcParams at runtime, but the registration is
        # one-time and safe.
        try:
            import koreanize_matplotlib  # noqa: F401
        except ImportError:
            pass
    except Exception as e:
        logger.warning(f"Korean font resolution failed: {e}")
    _KOREAN_FONT_NAME = ""  # cache the negative
    return None


# Per-figure style overrides applied via rcParams context. Mirrors the prior
# global plt.rcParams.update() but scoped to a single render call.
#
# axes.prop_cycle: starts with AWS-inspired orange so single-series charts get
# a consistent brand color, with neutral / blue / teal / muted-pink fillers
# that read well next to the chat UI's blue primary. Heatmaps are NOT affected
# (they read from `image.cmap` instead) — left at matplotlib's default `viridis`
# so dark-end contrast on the chat dark background stays readable.
from cycler import cycler
_CHART_PALETTE = ["#E68A1F", "#3A7BD5", "#2EB39C", "#7E57C2", "#5C6B7A", "#D86A6A"]

_CHART_STYLE = {
    "figure.facecolor": "#ffffff",
    "axes.facecolor": "#ffffff",
    "axes.edgecolor": "#999999",
    "axes.labelcolor": "#111111",
    "axes.labelsize": 13,
    "axes.titlesize": 15,
    "axes.titleweight": "bold",
    "text.color": "#111111",
    "xtick.color": "#333333",
    "ytick.color": "#333333",
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "grid.color": "#dddddd",
    "legend.fontsize": 11,
    "figure.dpi": 100,
    "axes.unicode_minus": False,
    "axes.prop_cycle": cycler(color=_CHART_PALETTE),
}


def _render_chart_oo(chart_code: str, result_df: pd.DataFrame):
    """Render `chart_code` on a fresh Figure using the OO API.

    Returns (fig, image_bytes) on success or (None, error_string) on failure.
    Uses matplotlib.figure.Figure directly (NOT pyplot) so concurrent calls do
    not share rcParams / global figure registry. The figure is held only for
    this call's lifetime and is garbage-collected when the function returns.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib as mpl
    from matplotlib.figure import Figure

    try:
        import seaborn as sns
    except ImportError:
        sns = None

    style = dict(_CHART_STYLE)
    font = _resolve_korean_font()
    if font:
        style["font.family"] = font

    # rc_context scopes rcParams changes to this block — even though we use the
    # OO API, some downstream calls (e.g. seaborn) still read rcParams at draw
    # time. Without the context, two concurrent renders could read each other's
    # style.
    with mpl.rc_context(style):
        fig = Figure(figsize=(10, 6))
        ax = fig.subplots()

        exec_globals_chart = {
            "pd": pd, "np": np, "df": result_df,
            "fig": fig, "ax": ax, "sns": sns,
        }

        exec_result = _safe_exec(chart_code, exec_globals_chart)
        if exec_result.get("error"):
            return None, f"Chart error: {exec_result['error']}"

        buf = io.BytesIO()
        fig.savefig(
            buf, format="png", dpi=200, bbox_inches="tight",
            facecolor="#ffffff", edgecolor="none",
        )
        buf.seek(0)
        return fig, buf.read()


# Public helper: re-run user-edited SQL from the /sql/execute endpoint.
def execute_sql_for_session(upload_id: str, sql: str, max_rows: int = 500) -> dict:
    """Execute a read-only SQL query against the session's DuckDB and return HTML.

    Used by the `/sql/execute` endpoint so users can edit + re-run SQL without
    going through the LLM. Does not modify session chat state.
    """
    sql = (sql or "").strip()
    if not sql:
        return {"success": False, "error": "SQL is empty"}

    try:
        session = session_manager.get_or_create(upload_id)
        session.ensure_data_loaded()
        result_df = session.run_query(sql).df()
    except Exception as e:
        # codeql[py/stack-trace-exposure] — intentional UX: this endpoint is
        # the SQL editor's "Run" button. The user typed the SQL, so showing
        # the DuckDB parse/runtime error back is the entire point — without
        # it, the editor is unusable. The DuckDB session is sealed against
        # filesystem / network access (see ensure_data_loaded), so the worst
        # an error can leak is column / table name hints from the user's own
        # uploaded CSV.
        return {"success": False, "error": f"{type(e).__name__}: {e}"}

    total = len(result_df)
    if total == 0:
        return {"success": True, "html": "<p class='chat-empty'>결과 없음</p>",
                "rows": 0, "total": 0, "truncated": False}

    truncated = total > max_rows
    if truncated:
        result_df = result_df.head(max_rows)

    return {
        "success": True,
        "html": _format_df_html(result_df),
        "rows": len(result_df),
        "total": total,
        "truncated": truncated,
    }


# ---------- Tool Definitions ----------


def _create_tools(
    session: "ChatSession",
    side_channel: list,
) -> list:
    """Bind tools to a specific ChatSession.

    All DB access goes through `session.run_query(...)` so the shared DuckDB
    connection is serialized with a lock and each call uses its own cursor.
    """

    table_name = session.table_name
    _shown_sqls: set[str] = set()

    def _normalize_sql(s: str) -> str:
        return re.sub(r"\s+", " ", s.strip().lower())

    @tool
    def describe_schema() -> str:
        """Describe the uploaded dataset: columns, types, row count, and sample rows.
        Use this when you need to recall the schema mid-conversation."""
        parts: list[str] = []
        row_count = session.run_query(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        parts.append(f"Table `{table_name}` — {row_count:,} rows")

        cols = session.run_query(f"DESCRIBE {table_name}").fetchall()
        parts.append("Columns:")
        for row in cols:
            parts.append(f"  - {row[0]} ({row[1]})")

        sample = session.run_query(
            f"SELECT * FROM {table_name} LIMIT 5"
        ).df()
        parts.append("\nSample rows:\n" + sample.to_string())
        return "\n".join(parts)

    @tool
    def query_sql(sql: str, display: bool = True) -> str:
        """Execute a DuckDB SQL query and return the results.

        The SQL text is shown to the user automatically. If `display=True`,
        the result is also rendered as a table in the chat UI.

        Args:
            sql: A valid DuckDB SQL query against the `data` table.
            display: True (default) to show results as a table. False for
                intermediate computations whose output the user should not see.
        """
        try:
            norm = _normalize_sql(sql)
            if norm not in _shown_sqls:
                side_channel.append(("sql", sql))
                _shown_sqls.add(norm)

            result_df = session.run_query(sql).df()

            if result_df.empty:
                return "쿼리 결과가 비었습니다. 조건을 확인해주세요."

            if display:
                side_channel.append(("table", _format_df_html(result_df)))
                summary = _df_summary_for_llm(result_df)
                return (
                    f"[SQL executed. {len(result_df)} rows displayed to user as a table. "
                    "Do NOT restate the table in text; instead use the numbers below "
                    "to write a concrete, numeric insight.]\n\n"
                    f"{summary}"
                )
            else:
                text = result_df.to_string()
                if len(text) > TEXT_OUTPUT_LIMIT:
                    text = text[:TEXT_OUTPUT_LIMIT] + "\n... (truncated)"
                return text

        except Exception as e:
            return f"SQL error: {type(e).__name__}: {e}"

    @tool
    def create_chart(sql: str, chart_code: str) -> str:
        """Execute SQL, then run matplotlib code to create a chart from the results.

        Inside `chart_code` you have:
          - `df`  : the result DataFrame of `sql`
          - `fig` : a fresh matplotlib Figure (already styled, light theme)
          - `ax`  : the default Axes (use `fig.subplots(...)` to add more)
          - `pd`, `np`, `sns` (seaborn if available)

        Use the matplotlib OO API on `ax` / `fig`. Do NOT import or call `plt`
        (matplotlib.pyplot) directly — pyplot mutates global state and is not
        safe under concurrent users. Do NOT call savefig / close — the tool
        handles output.

        Args:
            sql: The SQL query used to populate `df`.
            chart_code: Matplotlib code that draws on the provided `fig` / `ax`.

        Example:
            sql: "SELECT month, SUM(sales) AS total FROM data GROUP BY month ORDER BY month"
            chart_code: "ax.plot(df['month'], df['total'], marker='o')\\nax.set_title('Monthly Sales')"
        """
        try:
            norm = _normalize_sql(sql)
            if norm not in _shown_sqls:
                side_channel.append(("sql", sql))
                _shown_sqls.add(norm)

            result_df = session.run_query(sql).df()
            if result_df.empty:
                return "Query returned no rows; cannot draw a chart."

            # Build a Figure via the OO API. Avoids pyplot's global state
            # (plt.rcParams / plt.close('all')) which is shared across threads
            # — under concurrent users, one user's plt.close('all') can wipe
            # another's figure mid-render.
            fig, image_bytes = _render_chart_oo(chart_code, result_df)
            if isinstance(image_bytes, str):
                # error string returned from helper
                return image_bytes

            if len(image_bytes) > IMAGE_SIZE_LIMIT:
                return "Chart image exceeds size limit. Simplify the visualization."

            b64 = base64.b64encode(image_bytes).decode("utf-8")
            side_channel.append(("chart", b64))
            summary = _df_summary_for_llm(result_df)
            return (
                "[Chart created and displayed to the user. Do NOT describe the chart "
                "('차트입니다' 등 금지). Use the numbers below to write a concrete, "
                "numeric insight — headline with a specific value, then the driver "
                "or outlier, then a one-line implication.]\n\n"
                f"{summary}"
            )

        except Exception as e:
            return f"Chart error: {type(e).__name__}: {e}"

    return [describe_schema, query_sql, create_chart]
