# Data Q&A (Inner Loop)

> Conversational, second-scale exploration over the uploaded CSV — the **inner
> loop** that complements the long-form analysis report (the **outer loop**).

Deep Insight runs two distinct workflows on the same uploaded data:

| | Outer loop — Analysis | Inner loop — Data Q&A |
|---|---|---|
| **Endpoint** | `POST /analyze` | `POST /chat` |
| **Engine** | Hierarchical multi-agent (Coordinator → Planner → Supervisor → tools) | Single Strands Agent + Text2SQL |
| **Latency** | 15–30 min, runs to completion | Seconds, iterative dialogue |
| **Path** | AgentCore Runtime | In-container DuckDB (**AgentCore not on this path**) |
| **Output** | Complete DOCX report with charts and citations | Inline table / chart per question |
| **User posture** | "Hand it off and wait" | "Poke at it directly" |

The inner loop is for the questions you have *while* (or *before*) deciding what
the full report should cover: "how many rows?", "what's the top category by
revenue?", "show me the monthly trend". Fast, cheap, and fully transparent.

Enabled automatically after upload — a "Data Q&A" tab appears next to "Analysis"
at the top of the page.

[▶️ Watch the Deep Insight Chat demo on YouTube](https://youtu.be/i5NoAIq7sDk?list=PLrAWXV_UoWzhwubfImuoz6GCHlZnrRdDc)

## How it works

```
Upload CSV --> DuckDB in-memory table (read_csv_auto)
                    |
User question --> Strands Agent + Claude Sonnet 4.6
                    |
                    |-- query_sql(sql)                     -> table (SSE)
                    |-- create_chart(sql, matplotlib_code) -> PNG (SSE)
                    |-- describe_schema
                    v
             Answer streamed back with SQL block + table/chart
                    |
User edits SQL --> POST /sql/execute (re-run without LLM, ms latency)
```

## Highlights

- **Text2SQL with transparency**: Generated SQL is always shown in the chat bubble; collapsible by default
- **Inline SQL editor**: `▶ 실행` re-runs as-is, `✎ 편집` opens editor; no extra LLM call needed
- **Light-themed charts**: matplotlib with Korean font (NanumGothic), bold titles, click to zoom
- **Dynamic starter questions**: From schema heuristics — no LLM call on welcome load
- **Follow-up chips**: LLM inlines `[SUGGESTIONS]q1|q2|q3[/SUGGESTIONS]` at response end
- **Column-definitions aware**: Uses `column_definitions.json` (optional, auto-generated) in the system prompt for domain-accurate SQL
- **Insight-first Response Rules**: System prompt forces concrete numeric headlines and bans filler phrases ("경향이 있습니다" etc.)

## Prompt caching

System prompt + tool specs + conversation history are cached via Bedrock
ephemeral cache using `SystemContentBlock + cachePoint` and
`CacheConfig(strategy="auto")`. TTL is 5 minutes, which is a Bedrock
platform default (not configurable); this matches the typical inter-turn
gap in an interactive Q&A session.

Measured 5-turn session in production:

| Turn | total input | cache_read | hit% |
|---|---|---|---|
| 1 | 5,938 | 2,653 | 44.7% |
| 2 | 12,243 | 10,822 | 88.4% |
| 3 | 10,963 | 9,760 | 89.0% |
| 4 | 13,048 | 12,112 | 92.8% |
| 5 | 15,281 | 14,038 | 91.9% |

Per-turn input cost drops to ~10% on cache hits; session-level savings
typically 50%+ depending on conversation length (write premium grows with
history).

Toggle via env var: `ENABLE_PROMPT_CACHE=0` disables caching (useful for
local debugging).

### Observing prompt caching hits

```bash
# Live tail of per-turn usage metrics
aws logs tail /ecs/deep-insight-web --region us-west-2 --follow | grep "chat usage"
```

Each chat turn logs `input=… output=… cache_read=… cache_write=…` (values are
cumulative within a task; diff consecutive lines for per-turn deltas).

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `CHAT_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Chat agent LLM |
| `ENABLE_PROMPT_CACHE` | `1` | Set `0` to disable prompt caching |
| `WEB_UTILITY_MODEL_ID` | `global.anthropic.claude-sonnet-4-6` | Column/prompt auto-generation utility |

## Local development

Chat runs without S3 if `S3_BUCKET_NAME` is unset — uploaded CSVs go to
`/tmp/deep-insight-uploads/{upload_id}/` instead. Only Bedrock credentials
(`AWS_PROFILE` or env vars) are required.

```bash
cd deep-insight-web
pip install -r requirements.txt
export AWS_REGION=us-west-2    # CHAT_MODEL_ID uses global. profile
python app.py
# localhost:8080 → upload CSV → "Data Q&A" tab → ask
```

## Troubleshooting

> Deployment/infra issues (image architecture, container startup, task cycling)
> are shared with the outer loop — see the
> [README Troubleshooting section](./README.md#troubleshooting).
> The items below are specific to the Data Q&A inner loop.

### `AccessDeniedException: bedrock:InvokeModel` or `s3:ListBucket`

The task role's inline policy is out of sync — happens when `deploy-cloudfront.sh`
or `deploy.sh` adds new Sids but the role already existed (older script
versions only created policy on role creation).

Re-run the deploy script; it now always refreshes the inline policy:

```bash
bash deploy-cloudfront.sh   # or deploy.sh
```

Verify the policy contains the expected Sids:

```bash
aws iam get-role-policy \
  --role-name deep-insight-web-task-role \
  --policy-name deep-insight-web-task-policy \
  --query 'PolicyDocument.Statement[].Sid'
# Expected: ["S3Upload", "S3UploadsList", "S3Feedback",
#            "S3ArtifactsList", "S3ArtifactsGet",
#            "AgentCoreInvoke", "BedrockInvokeClaude"]
```

### Chart labels render as □□□

The container is missing Korean fonts. The Dockerfile installs `fontconfig +
fonts-nanum` before the `USER appuser` switch. If an older image was pushed
before this change, rebuild and redeploy:

```bash
bash deploy-cloudfront.sh   # or deploy.sh — forces new image build + push
```

Verify Nanum is present inside the container:

```bash
docker run --rm 603420654815.dkr.ecr.us-west-2.amazonaws.com/deep-insight-web:latest \
  fc-list | grep -i nanum
```
