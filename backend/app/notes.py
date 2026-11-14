"""Crew notes: short tips saved per building ("freight lift is faster after 6 pm") and found again later.

Each note is stored with an embedding so a search can match meaning, not just words. If the embedding
service is down, the note is still saved and searches fall back to matching words.
"""

import asyncio
import json
import logging
import math
import re
from collections.abc import Awaitable, Callable

from app.config import get_settings

logger = logging.getLogger(__name__)

Embedder = Callable[[str], Awaitable[list[float]]]
EMBEDDING_SIZE = 768  # must match notes.embedding vector(768) in the migration


def default_embedder() -> Embedder:
    """Gemini embeddings, built on first use so a missing key only fails inside a request."""
    state: dict = {}

    async def embed(text: str) -> list[float]:
        if "model" not in state:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            settings = get_settings()
            state["model"] = GoogleGenerativeAIEmbeddings(
                model=settings.gemini_embedding_model,
                google_api_key=settings.google_api_key,
                output_dimensionality=EMBEDDING_SIZE,
            )
        return await state["model"].aembed_query(text)

    return embed


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0


def _words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _vector(value) -> list[float] | None:
    """Postgres hands a vector back as text like '[0.1, 0.2]'; accept that or a list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, list) and value else None


async def _try_embed(embed: Embedder, text: str) -> list[float] | None:
    try:
        return await embed(text)
    except Exception:  # notes must still be saved and found without embeddings
        logger.warning("Could not embed text; falling back to word matching", exc_info=True)
        return None


async def save_note(db, embed: Embedder, building_id: str, text: str) -> None:
    row = {"building_id": building_id, "text": text, "embedding": await _try_embed(embed, text)}
    await asyncio.to_thread(lambda: db.table("notes").insert(row).execute())


async def search_notes(
    db, embed: Embedder, building_id: str, query: str, limit: int = 5
) -> list[str]:
    """The building's notes most relevant to the query, best first. Empty when none match."""
    rows = await asyncio.to_thread(
        lambda: db.table("notes").select("*").eq("building_id", building_id).execute()
    )
    if not rows.data:
        return []
    query_vector = await _try_embed(embed, query)
    query_words = _words(query)
    scored = []
    for row in rows.data:
        vector = _vector(row.get("embedding"))
        if query_vector and vector:
            score = cosine(query_vector, vector)
        else:
            score = len(query_words & _words(row["text"])) / (len(query_words) or 1)
        if score > 0:
            scored.append((score, row["text"]))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [text for _, text in scored[:limit]]
