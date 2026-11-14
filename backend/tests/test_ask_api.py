from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.ask import get_answerer
from app.api.events import get_embedder
from app.db import get_db
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.main import app
from tests.fakes import FakeSupabase

DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928" / "graph.json"
client = TestClient(app)
seen = {}


async def embed(text):
    return [1.0 if "lift" in text.lower() else 0.0, 0.1]


async def answerer(question, context):
    seen["question"], seen["context"] = question, context
    return "Use the Louisiana St entrance."


@pytest.fixture
def db():
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    steps = [s.model_dump() for s in find_route(graph, "st_main", "phone_door")]
    fake = FakeSupabase(
        incidents=[{"id": "i1", "building_id": "233928", "note": "chest pain", "parsed": None}],
        routes=[
            {
                "incident_id": "i1",
                "version": 1,
                "steps": steps,
                "total_seconds": 100,
                "briefing": "old",
            },
            {
                "incident_id": "i1",
                "version": 2,
                "steps": steps,
                "total_seconds": 120,
                "briefing": "newest",
            },
        ],
        notes=[
            {"building_id": "233928", "text": "Freight lift is key-only", "embedding": [1.0, 0.1]}
        ],
    )
    seen.clear()
    app.dependency_overrides[get_db] = lambda: fake
    app.dependency_overrides[get_answerer] = lambda: answerer
    app.dependency_overrides[get_embedder] = lambda: embed
    yield fake
    app.dependency_overrides.clear()


def ask(question="Which way in?", incident="i1"):
    return client.post("/ask", json={"incident_id": incident, "question": question})


def test_answer_is_returned(db):
    assert ask().json() == {"answer": "Use the Louisiana St entrance."}


def test_context_has_building_facts_newest_route_and_relevant_notes(db):
    ask("Is the lift ok?")
    context = seen["context"]
    assert "1415 Louisiana" in context and "newest" in context
    assert "Freight lift is key-only" in context
    assert "old" not in context.replace("hold", "")


def test_unknown_incident_is_404(db):
    assert ask(incident="nope").status_code == 404


def test_blank_question_is_422(db):
    assert ask("  ").status_code == 422


def test_when_the_model_fails_the_reply_says_so_and_gives_the_briefing(db):
    async def broken(question, context):
        raise RuntimeError("down")

    app.dependency_overrides[get_answerer] = lambda: broken
    response = ask()
    assert response.status_code == 200
    assert "newest" in response.json()["answer"]
