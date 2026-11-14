import asyncio

import pytest

from app.notes import cosine, save_note, search_notes
from tests.fakes import FakeSupabase


async def embed(text):
    # tiny fake embedding: one axis per topic word
    t = text.lower()
    return [1.0 if "lift" in t else 0.0, 1.0 if "parking" in t else 0.0, 0.1]


async def broken(text):
    raise RuntimeError("down")


def test_cosine_of_matching_and_orthogonal_vectors():
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
    assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)
    assert cosine([0, 0], [1, 1]) == 0.0


def test_search_ranks_by_meaning_and_only_returns_this_building():
    async def go():
        db = FakeSupabase(notes=[])
        await save_note(db, embed, "B1", "The lift is slow at night")
        await save_note(db, embed, "B1", "Parking gate code is open")
        await save_note(db, embed, "B2", "Other building lift note")
        return await search_notes(db, embed, "B1", "which lift to use", limit=2)

    found = asyncio.run(go())
    assert found[0] == "The lift is slow at night"
    assert "Other building lift note" not in found


def test_search_works_by_keywords_when_embeddings_are_missing():
    async def go():
        db = FakeSupabase(notes=[])
        await save_note(db, broken, "B1", "Loading dock door sticks")
        await save_note(db, broken, "B1", "Reception is on floor two")
        return await search_notes(db, broken, "B1", "dock door", limit=1)

    assert asyncio.run(go()) == ["Loading dock door sticks"]


def test_search_with_no_notes_is_empty():
    assert asyncio.run(search_notes(FakeSupabase(notes=[]), embed, "B1", "anything")) == []


def test_embeddings_stored_as_text_by_postgres_are_understood():
    db = FakeSupabase(
        notes=[{"building_id": "B1", "text": "lift note", "embedding": "[1.0, 0.0, 0.1]"}]
    )
    assert asyncio.run(search_notes(db, embed, "B1", "lift")) == ["lift note"]


def test_agent_notes_tools_save_and_find():
    from app.agent.tools import make_notes_tools

    search, save = make_notes_tools(FakeSupabase(notes=[]), embed)

    async def go():
        await save.ainvoke({"building_id": "B1", "text": "Lift 3 is reserved for stretchers"})
        return await search.ainvoke({"building_id": "B1", "query": "lift"})

    assert asyncio.run(go()) == {"notes": ["Lift 3 is reserved for stretchers"]}


def test_saving_a_note_creates_the_building_row_once():
    db = FakeSupabase(notes=[], buildings=[])

    async def go():
        await save_note(db, embed, "B1", "one")
        await save_note(db, embed, "B1", "two")

    asyncio.run(go())
    assert [b["id"] for b in db.rows("buildings")] == ["B1"]
