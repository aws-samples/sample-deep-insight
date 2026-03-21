"""
Adapts self-hosted engine events to the format expected by the frontend (analyze.js).

Mapping:
  {type:"agent_text_stream", data:"..."}         → {type:"agent_text_stream", text:"..."}
  {type:"agent_reasoning_stream", reasoning_text} → {type:"agent_reasoning_stream", text:"..."}
  {type:"agent_tool_stream", tool_name:"..."}     → {type:"agent_text_stream", text:"Tool calling: ..."}
  {type:"plan_review_request", ...}               → pass-through
  {type:"workflow_complete", ...}                  → pass-through (enriched with artifacts)
  {type:"agent_usage_stream", ...}                → ignored
"""


def adapt_event(event: dict) -> dict | None:
    """Convert a self-hosted engine event to the frontend SSE format.

    Returns None if the event should be suppressed.
    """
    event_type = event.get("type", "")

    if event_type == "agent_text_stream":
        return {"type": "agent_text_stream", "text": event.get("data", "")}

    if event_type == "agent_reasoning_stream":
        return {"type": "agent_reasoning_stream", "text": event.get("reasoning_text", "")}

    if event_type == "agent_tool_stream":
        sub_type = event.get("event_type", "")
        tool_name = event.get("tool_name", "unknown")
        if sub_type == "tool_use":
            return {"type": "agent_text_stream", "text": f"Tool calling: {tool_name}"}
        # tool_result events are noisy — skip them
        return None

    if event_type == "plan_review_request":
        return event

    if event_type == "workflow_complete":
        return event

    if event_type == "agent_usage_stream":
        return None

    # Unknown types — pass text through if present
    text = event.get("text") or event.get("data") or ""
    if text:
        return {"type": event_type, "text": text}

    return None
