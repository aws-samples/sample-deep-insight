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
import threading
from pathlib import Path

import duckdb
import pandas as pd
import numpy as np

import boto3
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
LOCAL_UPLOAD_DIR = Path("/tmp/deep-insight-uploads")

EXEC_TIMEOUT = 30
TEXT_OUTPUT_LIMIT = 10_000
IMAGE_SIZE_LIMIT = 500_000

# Default DuckDB table name for the uploaded CSV
DEFAULT_TABLE = "data"


# ---------- Helpers: file discovery (S3 + local, shared with /upload) ----------


def _list_upload_files(upload_id: str) -> list[tuple[str, bytes]]:
    """Return list of (filename, bytes) for files uploaded under upload_id.

    Supports both S3 mode (if S3_BUCKET_NAME set) and local mode.
    """
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
        local_dir = LOCAL_UPLOAD_DIR / upload_id
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
        """Load CSV from upload storage into an in-memory DuckDB table."""
        if self.conn is not None:
            return

        csv_name, csv_bytes, coldef = _find_csv_and_coldef(self.upload_id)
        self.csv_filename = csv_name
        self.column_definitions = coldef

        # Write CSV to a tmp file DuckDB can read from (read_csv_auto needs a path).
        tmp_path = LOCAL_UPLOAD_DIR / self.upload_id / f"_chat_{csv_name}"
        tmp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(csv_bytes)

        self.conn = duckdb.connect(":memory:")
        # Register the CSV as a table named `data`. read_csv_auto infers types.
        self.run_query(
            f"CREATE TABLE {self.table_name} AS "
            f"SELECT * FROM read_csv_auto(?, header=True)",
            [str(tmp_path)],
        )
        self.row_count = self.run_query(
            f"SELECT COUNT(*) FROM {self.table_name}"
        ).fetchone()[0]

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

        self.ensure_data_loaded()
        tools = _create_tools(self, self.side_channel)

        # Prompt caching: the system prompt (Rules + per-dataset schema) and
        # tool specs are invariant across a session. Caching them drops repeat-
        # turn input cost to ~10% (Bedrock ephemeral cache, 5-minute TTL).
        # `cache_config=auto` also adds a cache point on the most recent user
        # message so conversation history benefits as it grows.
        bedrock_kwargs: dict = {
            "model_id": CHAT_MODEL_ID,
            "region_name": AWS_REGION,
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

    def close(self):
        if self.conn is not None:
            try:
                self.conn.close()
            except Exception:
                pass
            self.conn = None
        self.agent = None


# ---------- SessionManager ----------


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def get_or_create(self, upload_id: str) -> ChatSession:
        with self._lock:
            if upload_id not in self._sessions:
                self._sessions[upload_id] = ChatSession(upload_id)
            return self._sessions[upload_id]

    def remove(self, upload_id: str):
        with self._lock:
            session = self._sessions.pop(upload_id, None)
        if session:
            session.close()


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
- For trends over time → line chart. For category comparison → bar chart. For share/proportion → pie. For distribution → histogram / box plot.
- ALWAYS set a descriptive `plt.title(...)`, and axis labels when useful.
- Write labels in the same language as the user's question (Korean by default).
- Korean fonts and a clean light theme are pre-configured — do NOT set `rcParams`, `style.use`, or fonts inside `chart_code`.
- Do NOT call `plt.show()` or `plt.savefig()` — the tool handles saving.

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
    """Run matplotlib chart code in a restricted sandbox with a timeout."""
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
    return formatted.to_html(classes="chat-table", index=False, border=0)


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

        The result DataFrame of `sql` is available as `df` inside `chart_code`.
        `plt` is matplotlib.pyplot, `sns` is seaborn (if available).
        Do NOT call plt.show() or plt.savefig(). Do NOT set rcParams or fonts.
        Korean fonts and a light theme are pre-configured by the tool.

        Args:
            sql: The SQL query used to populate `df`.
            chart_code: Matplotlib code that creates the figure.

        Example:
            sql: "SELECT month, SUM(sales) AS total FROM data GROUP BY month ORDER BY month"
            chart_code: "plt.figure(figsize=(10,6))\\nplt.plot(df['month'], df['total'], marker='o')\\nplt.title('Monthly Sales')"
        """
        try:
            norm = _normalize_sql(sql)
            if norm not in _shown_sqls:
                side_channel.append(("sql", sql))
                _shown_sqls.add(norm)

            result_df = session.run_query(sql).df()
            if result_df.empty:
                return "Query returned no rows; cannot draw a chart."

            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm

            # Korean font: try common system fonts first, fallback to koreanize_matplotlib
            _korean_font_set = False
            for font_name in ["NanumGothic", "NanumBarunGothic", "Malgun Gothic", "AppleGothic"]:
                if any(font_name == f.name for f in fm.fontManager.ttflist):
                    plt.rcParams["font.family"] = font_name
                    _korean_font_set = True
                    break
            if not _korean_font_set:
                try:
                    import koreanize_matplotlib  # noqa: F401
                except ImportError:
                    pass
            plt.rcParams["axes.unicode_minus"] = False

            try:
                import seaborn as sns
            except ImportError:
                sns = None

            # Light theme with bold titles
            plt.rcParams.update({
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
            })

            exec_globals_chart = {
                "pd": pd, "np": np, "df": result_df,
                "plt": plt, "sns": sns,
            }

            exec_result = _safe_exec(chart_code, exec_globals_chart)
            if exec_result.get("error"):
                plt.close("all")
                return f"Chart error: {exec_result['error']}"

            buf = io.BytesIO()
            plt.savefig(buf, format="png", dpi=200, bbox_inches="tight",
                        facecolor="#ffffff", edgecolor="none")
            plt.close("all")
            buf.seek(0)
            image_bytes = buf.read()

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
            try:
                import matplotlib.pyplot as plt
                plt.close("all")
            except Exception:
                pass
            return f"Chart error: {type(e).__name__}: {e}"

    return [describe_schema, query_sql, create_chart]
