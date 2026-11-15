import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import crew as crew_api
from app.api.crew import get_classifier, get_sidecar_client, normalize_handle
from app.api.events import get_embedder
from app.api.telemetry import EngineRegistry, get_registry
from app.config import Settings
from app.db import get_db
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.main import app
from app.photon import notify, share
from app.photon.classify import CrewReport
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "00000000-0000-0000-0000-0000000000a1"
DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928" / "graph.json"
SECRET = {"X-Photon-Secret": "shh"}
ME = "+15551230000"
client = TestClient(app)


class FakeSidecar:
    def __init__(self):
        self.sent, self.assigned = [], []

    async def send(self, **kwargs):
        self.sent.append(kwargs)

    async def assign(self, *, handle, name):
        self.assigned.append((handle, name))
        return {"assigned_phone_number": "+15559990000"}


class FakeClassifier:
    def __init__(self, report=None):
        self.report = report

    async def __call__(self, text):
        return self.report


async def no_embed(text):
    raise RuntimeError("no embeddings in tests")


def route_row():
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    steps = [s.model_dump() for s in find_route(graph, "gar1", "phone_door")]
    return {"incident_id": INCIDENT, "version": 1, "steps": steps, "entrance_node": "gar1",
            "total_seconds": 109, "briefing": "Garage entrance, lift to 18, phone room ahead."}  # fmt: skip


@pytest.fixture
def env(monkeypatch):
    settings = Settings(
        _env_file=None,
        photon_enabled=True,
        photon_shared_secret="shh",
        public_api_url="https://api.example.com",
        public_web_url="https://app.example.com",
        supabase_service_role_key="k",
    )
    for module in (crew_api, share, notify):
        monkeypatch.setattr(module, "get_settings", lambda: settings, raising=False)
    sidecar = FakeSidecar()
    db = FakeSupabase(
        incidents=[{"id": INCIDENT, "building_id": "233928", "status": "en_route", "note": "n",
                    "parsed": {"address": "1415 Louisiana St", "suite": "1800"}}],
        routes=[route_row()], crew_threads=[], plan_steps=[], closures=[], notes=[], cues=[], positions=[],
    )  # fmt: skip
    registry = EngineRegistry(stride_m=0.7, recheck_s=0, provider=SnapshotProvider())
    classifier = FakeClassifier(CrewReport(category="chatter", summary=""))
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_sidecar_client] = lambda: sidecar
    app.dependency_overrides[get_classifier] = lambda: classifier
    app.dependency_overrides[get_embedder] = lambda: no_embed
    monkeypatch.setattr(notify, "get_sidecar", lambda: sidecar)
    yield type("Env", (), {"db": db, "sidecar": sidecar, "classifier": classifier})
    app.dependency_overrides.clear()


def add_crew(handle=ME, name="Sam"):
    return client.post(f"/incidents/{INCIDENT}/crew", json={"handle": handle, "name": name})


def resolve(handle=ME, space="pho_spc_1", user="pho_usr_1", headers=SECRET):
    body = {"handle": handle, "space_id": space, "user_id": user}
    return client.post("/crew-threads/resolve", json=body, headers=headers)


# ------------------------------------------------------------------ phone numbers


def test_phone_numbers_are_cleaned_up_and_bad_ones_rejected():
    assert normalize_handle(" +1 (555) 123-0000 ") == "+15551230000"
    assert normalize_handle("Sam@Example.com") == "sam@example.com"
    for bad in ("5551230000", "hello", "+0123", "sam@", ""):
        with pytest.raises(ValueError):
            normalize_handle(bad)


# ------------------------------------------------------------ assigning the crew


def test_adding_a_crew_member_asks_photon_for_a_line_and_returns_the_number_to_text(env):
    out = add_crew(handle="+1 555 123 0000").json()
    assert out == {"ok": True, "handle": ME, "text_this_number": "+15559990000"}
    assert env.sidecar.assigned == [(ME, "Sam")]
    assert client.get(f"/incidents/{INCIDENT}/crew").json() == {
        "crew": [
            {"handle": ME, "name": "Sam", "assigned_phone_number": "+15559990000", "joined": False}
        ]
    }
    add_crew()  # adding again updates, it does not duplicate
    assert len(env.db.rows("crew_threads")) == 1


def test_adding_a_crew_member_rejects_a_bad_number_and_an_unknown_incident(env):
    assert add_crew(handle="555").status_code == 422
    assert client.post("/incidents/nope/crew", json={"handle": ME}).status_code == 404


def test_a_photon_failure_when_assigning_is_a_502_not_a_crash(env):
    async def boom(**_):
        raise RuntimeError("photon is down")

    env.sidecar.assign = boom
    assert add_crew().status_code == 502


# ------------------------------------------------------------ the sidecar's calls


def test_the_sidecar_endpoints_need_the_shared_secret(env):
    assert resolve(headers={}).status_code == 401
    assert resolve(headers={"X-Photon-Secret": "wrong"}).status_code == 401
    body = {"text": "hi", "sender": ME, "channel": "imessage"}
    assert client.post(f"/incidents/{INCIDENT}/crew-report", json=body).status_code == 401


def test_the_first_text_links_the_chat_and_sends_the_route_that_already_exists(env):
    add_crew()
    out = resolve().json()
    assert out == {"incident_id": INCIDENT, "first_contact": True}
    row = env.db.rows("crew_threads")[0]
    assert (row["photon_space_id"], row["photon_user_id"]) == ("pho_spc_1", "pho_usr_1")
    (sent,) = env.sidecar.sent  # the briefing and the card link, sent in the background
    assert sent["thread_id"] == "pho_spc_1" and "Garage entrance" in sent["text"]
    assert sent["url"].startswith(f"https://api.example.com/medic/{INCIDENT}?t=")
    assert sent["url"].endswith("&v=1")  # the route version, so the preview is fetched afresh
    assert sent["image_url"].startswith(
        f"https://api.example.com/medic/{INCIDENT}/card.png?t="
    )  # the route picture
    assert sent["image_url"].endswith("&v=1")
    assert resolve().json()["first_contact"] is False and len(env.sidecar.sent) == 1


def test_a_text_from_a_stranger_or_for_a_finished_incident_is_not_resolved(env):
    add_crew()
    assert resolve(handle="+19998887777").status_code == 404
    env.db.rows("incidents")[0]["status"] = "arrived"
    assert resolve().status_code == 404


def test_a_crew_report_goes_through_the_classifier_and_returns_the_replies(env):
    add_crew()
    resolve()
    env.classifier.report = CrewReport(
        category="blocker", summary="elevator B is out", elevator=True
    )
    body = {"text": "elevator B is out", "sender": ME, "channel": "imessage"}
    out = client.post(f"/incidents/{INCIDENT}/crew-report", json=body, headers=SECRET).json()
    assert out["category"] == "blocker" and out["replies"][0].endswith("Reply YES to confirm.")
    assert any(s["title"] == "crew texted: elevator B is out" for s in env.db.rows("plan_steps"))


def test_a_report_from_someone_not_on_the_incident_is_ignored(env):
    body = {"text": "hi", "sender": "+19998887777", "channel": "imessage"}
    out = client.post(f"/incidents/{INCIDENT}/crew-report", json=body, headers=SECRET).json()
    assert out["ignored"] is True and env.db.rows("plan_steps") == []


# ------------------------------------------------------------- notifications


def test_a_saved_route_is_texted_to_everyone_who_joined(env):
    add_crew()
    add_crew(handle="+15557770000", name="Alex")
    resolve()  # only Sam has texted the line
    env.sidecar.sent.clear()
    asyncio.run(notify.notify_route(env.db, INCIDENT, "Go left."))
    assert [s["thread_id"] for s in env.sidecar.sent] == ["pho_spc_1"]
    assert any(s["title"] == "texted crew: Go left." for s in env.db.rows("plan_steps"))


def test_with_nobody_joined_the_dispatcher_is_told_instead_of_nothing_happening(env):
    asyncio.run(notify.notify_route(env.db, INCIDENT, "Go left."))
    assert env.sidecar.sent == []
    assert any("No crew member has joined" in s["title"] for s in env.db.rows("plan_steps"))


def test_a_photon_failure_is_logged_and_never_raises(env):
    add_crew()
    resolve()

    async def boom(**_):
        raise RuntimeError("photon is down")

    env.sidecar.send = boom
    asyncio.run(notify.notify_route(env.db, INCIDENT, "Go left."))  # must not raise
    assert any("Could not text the crew" in s["title"] for s in env.db.rows("plan_steps"))


def test_nothing_is_sent_when_photon_is_off(env, monkeypatch):
    add_crew()
    resolve()
    env.sidecar.sent.clear()
    env.db.rows("plan_steps").clear()
    monkeypatch.setattr(
        notify, "get_settings", lambda: Settings(_env_file=None, photon_enabled=False)
    )
    asyncio.run(notify.notify_route(env.db, INCIDENT, "Go left."))
    assert env.sidecar.sent == [] and not [
        s for s in env.db.rows("plan_steps") if s["kind"] == "crew"
    ]


# ------------------------------------------------------------- the link preview


def link():
    return f"/medic/{INCIDENT}?t={share.make_token(INCIDENT)}"


def test_the_link_page_carries_open_graph_tags_a_crawler_can_read_without_javascript(env):
    page = client.get(link())
    assert "&amp;v=3" not in page.text
    versioned = client.get(link() + "&v=3").text
    assert f"/medic/{INCIDENT}/card.png?t={share.make_token(INCIDENT)}&amp;v=3" in versioned
    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    text = page.text
    assert '<meta property="og:title" content="' in text and "Suite 1800, floor 18" in text
    assert (
        'property="og:description" content="Garage entrance, lift to 18, phone room ahead."' in text
    )
    assert f'content="https://api.example.com/medic/{INCIDENT}/card.png?t=' in text
    assert 'name="twitter:card" content="summary_large_image"' in text
    assert (
        f"https://app.example.com/arrival?incident={INCIDENT}" in text
    )  # where people are sent on


def test_dynamic_text_in_the_page_is_escaped(env):
    env.db.rows("routes")[0]["briefing"] = '</head><script>alert("x")</script>'
    text = client.get(link()).text
    assert '<script>alert("x")' not in text and "&lt;script&gt;" in text


def test_the_link_needs_the_token_and_an_unknown_incident_looks_the_same(env):
    assert client.get(f"/medic/{INCIDENT}").status_code == 404
    assert client.get(f"/medic/{INCIDENT}?t=wrong").status_code == 404
    other = "00000000-0000-0000-0000-0000000000b2"
    assert client.get(f"/medic/{other}?t={share.make_token(other)}").status_code == 404
    assert client.get(f"/medic/{INCIDENT}/card.png?t=wrong").status_code == 404


def test_the_card_is_a_png_of_the_route(env):
    card = client.get(f"/medic/{INCIDENT}/card.png?t={share.make_token(INCIDENT)}")
    assert card.status_code == 200 and card.headers["content-type"] == "image/png"
    assert card.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_when_the_route_cannot_be_drawn_the_card_falls_back_to_the_building_picture(env):
    env.db.rows("routes")[0]["steps"] = [{"bogus": True}]
    card = client.get(f"/medic/{INCIDENT}/card.png?t={share.make_token(INCIDENT)}")
    assert card.status_code == 200 and card.content[:8] == b"\x89PNG\r\n\x1a\n"
    env.db.rows("routes").clear()  # no route yet at all
    assert (
        client.get(f"/medic/{INCIDENT}/card.png?t={share.make_token(INCIDENT)}").status_code == 200
    )


# ---------------------------------------------------- choose_route sends the briefing


def choose(env, briefing="Garage entrance, lift to 18."):
    from app.agent.tools import make_route_tools

    tools = {t.name: t for t in make_route_tools(SnapshotProvider(), env.db, INCIDENT)}
    args = {
        "building_id": "233928",
        "start_node": "gar1",
        "goal_node": "phone_door",
        "briefing": briefing,
    }
    return asyncio.run(tools["choose_route"].ainvoke(args))


def test_saving_the_route_texts_the_briefing_and_link_to_the_crew(env):
    env.db.rows("routes").clear()
    add_crew()
    resolve()  # nothing to send yet: there is no route
    assert env.sidecar.sent == []
    out = choose(env)
    assert out["route_version"] == 1
    (sent,) = env.sidecar.sent
    assert sent["text"].startswith("Garage entrance, lift to 18.") and "/medic/" in sent["url"]


def test_a_photon_outage_never_stops_the_route_being_saved(env):
    env.db.rows("routes").clear()
    add_crew()
    resolve()

    async def boom(**_):
        raise RuntimeError("photon is down")

    env.sidecar.send = boom
    out = choose(env)
    assert out["route_version"] == 1 and len(env.db.rows("routes")) == 1
    assert env.db.rows("incidents")[0]["status"] == "en_route"


# --------------------------------------------------------------- the directions


def test_directions_are_the_routers_steps_numbered_with_the_total_time():
    steps = [
        {"text": "Walk 25 m to Elevators (floor 1)."},
        {"text": "Take the elevator up to floor 18."},
    ]
    assert notify.directions_text(steps, 109) == (
        "Directions (about 1 min 49 s):\n1. Walk 25 m to Elevators (floor 1).\n2. Take the elevator up to floor 18."
    )
    assert notify.directions_text(steps, 45).startswith("Directions (about 45 s):")
    assert notify.directions_text([], 0) == ""


def test_a_long_route_is_cut_short_and_points_to_the_link():
    steps = [{"text": f"Step {i}."} for i in range(1, 16)]
    text = notify.directions_text(steps, 200)
    assert "10. Step 10." in text and "11. Step 11." not in text
    assert text.endswith("(5 more steps: open the link)")


def test_the_text_the_crew_gets_has_the_briefing_and_then_the_directions(env):
    env.db.rows("routes").clear()
    add_crew()
    resolve()
    choose(env, briefing="Garage entrance, lift to 18.")
    (sent,) = env.sidecar.sent
    assert sent["text"].startswith(
        "Garage entrance, lift to 18.\n\nDirections (about 1 min 49 s):\n1. Walk "
    )
    assert "Take the elevator up to floor 18." in sent["text"]
    assert sent["text"].rstrip().endswith("phone room (patient) is ahead.")
