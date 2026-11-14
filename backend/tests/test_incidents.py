import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.incidents import get_agent_runner, get_parser
from app.db import get_db
from app.intake import SYSTEM_PROMPT, NoteParser
from app.main import app
from app.models import ParsedNote

INCIDENT_ID = "11111111-2222-3333-4444-555555555555"
NOTE = "65M chest pain, Regus Suite 1800, 1415 Louisiana St"
PARSED = ParsedNote(
    address="1415 Louisiana St",
    suite="1800",
    floor=18,
    complaint="chest pain, 65 year old male",
    access_notes=None,
)


class FakeDb:
    """Stands in for the Supabase client: remembers inserts, returns a fixed id."""

    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    def table(self, name):
        assert name == "incidents"
        return self

    def insert(self, row):
        self.row = row
        return self

    def execute(self):
        if self.fail:
            raise RuntimeError("database is down")
        self.rows.append(self.row)
        return SimpleNamespace(data=[{**self.row, "id": INCIDENT_ID}])


@pytest.fixture
def runner():
    """Stands in for the background agent so these tests never start a real one."""
    calls = []

    async def run(incident_id):
        calls.append(incident_id)

    run.calls = calls
    app.dependency_overrides[get_agent_runner] = lambda: run
    return run


@pytest.fixture
def db(runner):
    fake = FakeDb()
    app.dependency_overrides[get_db] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def use_parser(parse):
    app.dependency_overrides[get_parser] = lambda: parse


async def good_parser(note):
    return PARSED


async def broken_parser(note):
    raise RuntimeError("Gemini is unreachable")


client = TestClient(app)


def test_valid_note_creates_an_incident(db):
    use_parser(good_parser)
    response = client.post("/incidents", json={"note": NOTE})
    assert response.status_code == 200
    assert response.json() == {"incident_id": INCIDENT_ID}


def test_incident_row_has_note_parsed_fields_and_planning_status(db):
    use_parser(good_parser)
    client.post("/incidents", json={"note": NOTE})
    (row,) = db.rows
    assert row["note"] == NOTE
    assert row["status"] == "planning"
    assert row["parsed"] == {
        "address": "1415 Louisiana St",
        "suite": "1800",
        "floor": 18,
        "complaint": "chest pain, 65 year old male",
        "access_notes": None,
    }


def test_note_is_trimmed_before_saving(db):
    use_parser(good_parser)
    client.post("/incidents", json={"note": f"  {NOTE}\n"})
    assert db.rows[0]["note"] == NOTE


def test_call_is_not_lost_when_gemini_fails(db):
    """A dispatcher's call must still be recorded if parsing breaks; the agent can retry the parse."""
    use_parser(broken_parser)
    response = client.post("/incidents", json={"note": NOTE})
    assert response.status_code == 200
    (row,) = db.rows
    assert row["parsed"] is None and row["note"] == NOTE and row["status"] == "planning"


def test_database_failure_returns_503(db):
    db.fail = True
    use_parser(good_parser)
    response = client.post("/incidents", json={"note": NOTE})
    assert response.status_code == 503


@pytest.mark.parametrize(
    "body", [{}, {"note": ""}, {"note": "   "}, {"note": "x" * 2001}, {"note": 5}]
)
def test_bad_note_is_rejected_and_nothing_is_saved(db, body):
    use_parser(good_parser)
    assert client.post("/incidents", json=body).status_code == 422
    assert db.rows == []


def test_parsed_note_requires_an_address_and_a_complaint():
    with pytest.raises(ValueError):
        ParsedNote(address="", suite=None, floor=None, complaint="chest pain", access_notes=None)
    with pytest.raises(ValueError):
        ParsedNote(address="1 Main St", suite=None, floor=None, complaint="", access_notes=None)


class FakeChain:
    """Stands in for a Gemini structured-output chain."""

    def __init__(self, result=None, error=None):
        self.result, self.error, self.messages = result, error, None

    async def ainvoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return self.result


def test_note_parser_sends_the_note_to_the_model_with_the_rules():
    chain = FakeChain(PARSED)
    result = asyncio.run(NoteParser(chains=[chain])(NOTE))
    assert result == PARSED
    assert chain.messages == [("system", SYSTEM_PROMPT), ("human", NOTE)]
    assert "never invent" in SYSTEM_PROMPT.lower()


def test_note_parser_falls_back_to_the_next_model_when_the_first_fails():
    busy = FakeChain(error=RuntimeError("503 high demand"))
    backup = FakeChain(PARSED)
    assert asyncio.run(NoteParser(chains=[busy, backup])(NOTE)) == PARSED
    assert busy.messages is not None  # the first model was tried


def test_note_parser_raises_when_every_model_fails():
    chains = [FakeChain(error=RuntimeError("a")), FakeChain(error=RuntimeError("b"))]
    with pytest.raises(RuntimeError):
        asyncio.run(NoteParser(chains=chains)(NOTE))


def test_note_parser_skips_the_fallback_when_it_is_the_same_model():
    from app.intake import model_names

    assert model_names("gemini-x", "gemini-x") == ["gemini-x"]
    assert model_names("gemini-x", "") == ["gemini-x"]
    assert model_names("gemini-x", "gemini-y") == ["gemini-x", "gemini-y"]


def test_fallback_can_be_a_comma_separated_list_without_duplicates():
    from app.intake import model_names

    assert model_names("a", "b, c ,a,b") == ["a", "b", "c"]


def test_the_agent_starts_in_the_background_with_the_new_incident_id(db, runner):
    use_parser(good_parser)
    client.post("/incidents", json={"note": NOTE})
    assert runner.calls == [INCIDENT_ID]


def test_the_agent_still_starts_when_parsing_failed(db, runner):
    use_parser(broken_parser)
    client.post("/incidents", json={"note": NOTE})
    assert runner.calls == [INCIDENT_ID]


def test_no_agent_starts_when_the_incident_was_not_saved(db, runner):
    db.fail = True
    use_parser(good_parser)
    client.post("/incidents", json={"note": NOTE})
    assert runner.calls == []
