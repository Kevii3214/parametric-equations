"""Read a door or suite sign from the wearable's camera and find the map point it names.

Gemini only reads the text in the picture. Which map point that is, and whether it is on the route, is decided in
code (`match_sign`), the same split as the rest of the agent: the model reads, the code decides.

Privacy: the camera can see real people. The picture lives in memory for one model call and is never written
anywhere; only the sign text is logged and stored.
"""

import base64
import logging
import re

from pydantic import BaseModel, Field

from app.config import get_settings
from app.intake import model_names

logger = logging.getLogger(__name__)

TIMEOUT_S = 15
MAX_RETRIES = 0
MAX_PICTURE_BYTES = 2_000_000

PROMPT = (
    "This picture is from a camera on a paramedic's chest, facing forward inside a building. "
    "List the text of every room, suite, floor or door sign you can read, exactly as written, one string per sign. "
    "Ignore posters, people and anything that is not a sign. If you cannot read a sign, return an empty list. "
    "Never guess or complete text you cannot see."
)


class Signs(BaseModel):
    texts: list[str] = Field(default_factory=list, description="Sign text, as written")


class SignReader:
    """Tries each Gemini model in turn. Returns [] (never raises) when none of them answers."""

    def __init__(self, chains=None):
        self._chains = chains

    def _get_chains(self):
        if self._chains is None:
            from langchain_google_genai import ChatGoogleGenerativeAI

            settings = get_settings()
            self._chains = [
                ChatGoogleGenerativeAI(
                    model=name,
                    google_api_key=settings.google_api_key,
                    temperature=0,
                    timeout=TIMEOUT_S,
                    max_retries=MAX_RETRIES,
                ).with_structured_output(Signs)
                for name in model_names(settings.gemini_model, settings.gemini_fallback_model)
            ]
        return self._chains

    async def __call__(self, image: bytes) -> list[str]:
        if not image or len(image) > MAX_PICTURE_BYTES:
            return []
        url = "data:image/jpeg;base64," + base64.b64encode(image).decode()
        message = (
            "human",
            [
                {"type": "text", "text": PROMPT},
                {"type": "image_url", "image_url": {"url": url}},
            ],
        )
        for chain in self._get_chains():
            try:
                found = await chain.ainvoke([message])
                return [t.strip() for t in found.texts if t.strip()]
            except Exception as failure:  # noqa: BLE001 - any failure moves on to the next model
                logger.warning(
                    "Reading a sign failed (%s); trying the next model", type(failure).__name__
                )
        return []


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def match_sign(texts: list[str], nodes: list[dict]) -> str | None:
    """The id of the node a sign names, or None. `nodes` is the candidates (the nodes on the route).

    A sign matches a node when every word of the sign is in the node's label ("SUITE 1800" matches "Regus Suite
    1800 entrance"). Several matches: the node with the shortest label wins, because a door's own label is shorter
    than a room inside it. A tie, or a sign of one very common word, matches nothing: a wrong fix is worse than none.
    """
    best: tuple[int, str] | None = None
    tied = False
    for text in texts:
        sign = _words(text) - {"the", "of", "room", "suite", "floor", "no", "number"} or _words(
            text
        )
        if not sign or sign <= {"a", "b", "c", "1", "2", "3", "exit", "stairs"}:
            continue
        for node in nodes:
            label = _words(node.get("label", ""))
            if label and sign <= label:
                size = len(label)
                if best is None or size < best[0]:
                    best, tied = (size, node["id"]), False
                elif size == best[0] and node["id"] != best[1]:
                    tied = True
    return None if best is None or tied else best[1]
