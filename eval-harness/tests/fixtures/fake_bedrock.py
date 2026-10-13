"""A fake Bedrock Converse client for tests: no network, no cost."""
import json


class FakeConverse:
    """Returns queued replies (dicts → JSON text) and records each request."""
    def __init__(self, replies, stop="end_turn"):
        self.replies, self.stop, self.requests = list(replies), stop, []

    def converse(self, **kw):
        self.requests.append(kw)
        r = self.replies.pop(0)
        text = r if isinstance(r, str) else json.dumps(r, ensure_ascii=False)
        return {"output": {"message": {"content": [{"text": text}]}}, "stopReason": self.stop,
                "usage": {"inputTokens": 10_000, "outputTokens": 2_000}}


CFG = {"model": "global.openai.gpt-6-astra", "region": "us-west-2", "effort": "high", "max_tokens": 1000, "max_report_chars": 200000}
