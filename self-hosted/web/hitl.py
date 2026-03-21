"""
Async HITL (Human-in-the-Loop) manager for web-based plan review.
Replaces blocking input() with asyncio-based wait/submit pattern.
"""

import asyncio
import logging
import uuid

logger = logging.getLogger(__name__)


class HITLManager:
    """Manages async feedback exchange between SSE stream and /feedback endpoint."""

    def __init__(self):
        self._event: asyncio.Event | None = None
        self._approved: bool = True
        self._feedback: str = ""
        self._request_id: str = ""

    def new_request_id(self) -> str:
        self._request_id = str(uuid.uuid4())
        return self._request_id

    @property
    def request_id(self) -> str:
        return self._request_id

    async def wait_for_feedback(self, timeout: float = 300) -> tuple[bool, str]:
        """Wait for user feedback via /feedback POST. Called from plan_reviewer_node."""
        self._event = asyncio.Event()
        self._approved = True
        self._feedback = ""
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.info("HITL timeout — auto-approving plan")
            self._approved = True
            self._feedback = ""
        return self._approved, self._feedback

    def submit_feedback(self, approved: bool, feedback: str = "") -> None:
        """Submit user feedback. Called from /feedback endpoint."""
        self._approved = approved
        self._feedback = feedback
        if self._event:
            self._event.set()


hitl_manager = HITLManager()
