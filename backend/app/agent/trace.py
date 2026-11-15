"""The agent's visible trail: every plan, subagent call, tool call and tool result goes into plan_steps.

Person 1's web app shows these rows live, and they are how judges see the agent working.
"""

import asyncio
import json
import logging
import threading
import weakref
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


# The last step number used for each incident, shared by every PlanTrace for it. The agent, a re-plan and the crew
# chat can all write to one incident's trail at the same moment, and each used to count on its own, which gave two
# rows the same number. Kept per database object, so tests with separate in-memory databases stay separate.
_LAST_SEQ: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
_LAST_SEQ_BY_ID: dict = {}  # fallback for a database object that cannot be weakly referenced
_SEQ_LOCK = threading.Lock()


def _counters(db) -> dict:
    try:
        return _LAST_SEQ.setdefault(db, {})
    except TypeError:
        return _LAST_SEQ_BY_ID.setdefault(id(db), {})


def _next_seq(db, incident_id: str, at_least: int = 0) -> int:
    with _SEQ_LOCK:  # numbers each step; never held across an await
        counters = _counters(db)
        seq = max(counters.get(incident_id, 0), at_least) + 1
        counters[incident_id] = seq
        return seq


class PlanTrace:
    """Writes numbered plan_steps rows for one incident. A failing database never stops the agent."""

    def __init__(self, db, incident_id: str):
        self._db = db
        self._incident_id = incident_id

    @classmethod
    async def resume(cls, db, incident_id: str) -> "PlanTrace":
        """A trace that carries on numbering after the plan steps already saved for this incident."""
        trace = cls(db, incident_id)
        try:
            rows = await asyncio.to_thread(
                lambda: db.table("plan_steps").select("*").eq("incident_id", incident_id).execute()
            )
            highest = max((r["seq"] for r in rows.data), default=0)
            with _SEQ_LOCK:  # raise the shared counter to what is already saved, never lower it
                counters = _counters(db)
                counters[incident_id] = max(counters.get(incident_id, 0), highest)
        except Exception:
            logger.exception("Could not read existing plan steps for %s", incident_id)
        return trace

    async def add(self, kind: str, title: str, detail: dict | None = None) -> None:
        seq = _next_seq(self._db, self._incident_id)
        row = {
            "incident_id": self._incident_id,
            "seq": seq,
            "kind": kind,
            "title": _clip(title, MAX_TITLE),
            "detail": _clip_detail(detail or {}),
        }
        try:
            await asyncio.to_thread(lambda: self._db.table("plan_steps").insert(row).execute())
        except Exception:
            logger.exception("Could not write plan step %s", seq)


class TraceHandler(AsyncCallbackHandler):
    """Turns the agent's tool activity into plan_steps rows.

    write_todos -> plan (the first call only; later calls just tick items off), task (a subagent call) ->
    subagent, every other tool -> tool_call then tool_result.
    """

    def __init__(self, trace: PlanTrace):
        self._trace = trace
        self._names: dict[UUID, str] = {}
        self._planned = False

    async def on_tool_start(self, serialized, input_str, *, run_id, inputs=None, **kwargs):
        name = (serialized or {}).get("name") or kwargs.get("name") or "tool"
        args = inputs if isinstance(inputs, dict) else {"input": input_str}
        self._names[run_id] = name

        if name == "write_todos":
            if self._planned:
                return  # a status update on the same list
            self._planned = True
            steps = [
                str(t.get("content", t)) if isinstance(t, dict) else str(t)
                for t in args.get("todos") or []
            ]
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
        if name == "write_todos":
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
