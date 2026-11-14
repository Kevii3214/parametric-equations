"""The agent's visible trail: every plan, subagent call, tool call and tool result goes into plan_steps.

Person 1's web app shows these rows live, and they are how judges see the agent working.
"""

import asyncio
import json
import logging
from uuid import UUID

from langchain_core.callbacks import AsyncCallbackHandler

logger = logging.getLogger(__name__)

MAX_TITLE = 200
MAX_TEXT = 4000


def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _clip_detail(detail: dict) -> dict:
    return {k: _clip(v, MAX_TEXT) if isinstance(v, str) else v for k, v in detail.items()}


def _as_text(value) -> str:
    update = getattr(
        value, "update", None
    )  # a subagent's reply arrives as a Command holding messages
    if isinstance(update, dict) and update.get("messages"):
        value = update["messages"][-1]
    value = getattr(value, "content", value)  # a ToolMessage carries its text in .content
    return value if isinstance(value, str) else json.dumps(value, default=str)


class PlanTrace:
    """Writes numbered plan_steps rows for one incident. A failing database never stops the agent."""

    def __init__(self, db, incident_id: str):
        self._db = db
        self._incident_id = incident_id
        self._seq = 0
        self._lock = asyncio.Lock()

    async def add(self, kind: str, title: str, detail: dict | None = None) -> None:
        async with self._lock:  # keeps seq in step with the order rows are written
            self._seq += 1
            row = {
                "incident_id": self._incident_id,
                "seq": self._seq,
                "kind": kind,
                "title": _clip(title, MAX_TITLE),
                "detail": _clip_detail(detail or {}),
            }
            try:
                await asyncio.to_thread(lambda: self._db.table("plan_steps").insert(row).execute())
            except Exception:
                logger.exception("Could not write plan step %s", self._seq)


class TraceHandler(AsyncCallbackHandler):
    """Turns the agent's tool activity into plan_steps rows.

    make_plan -> plan, task (a subagent call) -> subagent, every other tool -> tool_call then tool_result.
    """

    def __init__(self, trace: PlanTrace):
        self._trace = trace
        self._names: dict[UUID, str] = {}

    async def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        args = inputs if isinstance(inputs, dict) else {"input": input_str}
        self._names[run_id] = name

        if name == "make_plan":
            steps = args.get("steps") or []
            await self._trace.add("plan", "Plan: " + "; ".join(steps), {"steps": steps})
        elif name == "task":
            agent = args.get("subagent_type", "subagent")
            description = str(args.get("description", ""))
            await self._trace.add(
                "subagent",
                f"{agent} subagent: {description}",
                {"subagent": agent, "description": description},
            )
        else:
            shown = ", ".join(f"{k}={v!r}" for k, v in args.items())
            await self._trace.add("tool_call", f"{name}({shown})", {"tool": name, "args": args})

    async def on_tool_end(self, output, *, run_id, **kwargs):
        name = self._names.pop(run_id, "tool")
        if name == "make_plan":
            return  # the plan step already says everything
        text = _as_text(output)
        await self._trace.add(
            "tool_result", f"{name} returned: {text}", {"tool": name, "output": text}
        )

    async def on_tool_error(self, error, *, run_id, **kwargs):
        name = self._names.pop(run_id, "tool")
        await self._trace.add(
            "tool_result", f"{name} failed: {error}", {"tool": name, "error": str(error)}
        )
