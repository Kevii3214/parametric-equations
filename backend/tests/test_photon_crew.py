import asyncio
import json
from pathlib import Path

import pytest

from app.api.telemetry import EngineRegistry
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.photon import crew, notify
from app.photon.classify import CrewClassifier, CrewReport, is_no, is_yes
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"
DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928" / "graph.json"
ME = "+15551230000"


def graph():
    return BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))


def route_row(version=1, start="gar1", goal="phone_door"):
    steps = [s.model_dump() for s in find_route(graph(), start, goal)]
    return {"incident_id": INCIDENT, "version": version, "steps": steps, "entrance_node": start,
            "total_seconds": 109, "briefing": "Garage entrance, lift to 18."}  # fmt: skip


class FakeClassifier:
    def __init__(self, report: CrewReport | None):
        self.report, self.seen = report, []

    async def __call__(self, text: str):
        self.seen.append(text)
        return self.report


async def fake_embed(text):
    raise RuntimeError("no embeddings in tests")


class FakeSidecar:
    def __init__(self, fail=False):
        self.sent, self.fail = [], fail

    async def send(self, **kwargs):
        if self.fail:
            raise RuntimeError("sidecar is down")
        self.sent.append(kwargs)


@pytest.fixture
def db():
    return FakeSupabase(
        incidents=[{"id": INCIDENT, "building_id": "233928", "status": "en_route", "note": "n"}],
        routes=[route_row()],
        crew_threads=[{"incident_id": INCIDENT, "handle": ME, "name": "Sam", "photon_space_id": "pho_spc_1",
                       "photon_user_id": "pho_usr_1", "pending": None}],
        plan_steps=[], closures=[], notes=[], cues=[], positions=[],
    )  # fmt: skip


@pytest.fixture
def registry():
    return EngineRegistry(stride_m=0.7, recheck_s=0, provider=SnapshotProvider())


def report(db, registry, classifier, text, sender=ME, incident=INCIDENT):
    return asyncio.run(
        crew.handle_crew_report(
            db,
            SnapshotProvider(),
            registry,
            classifier,
            fake_embed,
            incident,
            text,
            sender,
            "imessage",
        )
    )


def trace_titles(db, kind="crew"):
    return [s["title"] for s in db.rows("plan_steps") if s["kind"] == kind]


# ------------------------------------------------------------- yes / no / models


def test_yes_and_no_are_recognised_loosely():
    assert all(is_yes(t) for t in ("YES", "yes", " Yes. ", "y", "yep", "Yeah!", "confirm"))
    assert not any(is_yes(t) for t in ("yesterday", "no", "not yet", "elevator out"))
    assert all(is_no(t) for t in ("no", "NO", "nope", "n", "cancel"))


def test_the_classifier_tries_the_next_model_and_gives_up_quietly():
    class Boom:
        async def ainvoke(self, *_):
            raise RuntimeError("429")

    class Fine:
        async def ainvoke(self, *_):
            return CrewReport(category="chatter", summary="thanks")

    assert asyncio.run(CrewClassifier(chains=[Boom(), Fine()])("thanks")).category == "chatter"
    assert asyncio.run(CrewClassifier(chains=[Boom()])("thanks")) is None  # never raises


# ------------------------------------------------------------------ the rules


def test_a_text_from_someone_not_on_the_incident_is_ignored(db, registry):
    out = report(
        db,
        registry,
        FakeClassifier(CrewReport(category="blocker", summary="x")),
        "hi",
        sender="+19998887777",
    )
    assert out == {"ignored": True, "reason": "not assigned to this incident", "replies": []}
    assert db.rows("plan_steps") == []


def test_a_text_for_a_finished_incident_is_ignored(db, registry):
    db.rows("incidents")[0]["status"] = "arrived"
    out = report(db, registry, FakeClassifier(CrewReport(category="blocker", summary="x")), "hi")
    assert out["ignored"] and out["reason"] == "incident is not active"


def test_chatter_is_logged_but_gets_no_reply(db, registry):
    out = report(
        db, registry, FakeClassifier(CrewReport(category="chatter", summary="")), "on my way"
    )
    assert out["category"] == "chatter" and out["replies"] == []
    assert trace_titles(db) == ["crew texted: on my way"]


def test_a_blocker_asks_for_a_yes_and_changes_nothing_yet(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="blocker", summary="elevator B is out", elevator=True)
    )
    out = report(db, registry, classifier, "elevator B is out of service")
    assert out["category"] == "blocker"
    assert out["replies"] == ["Re-routing around elevator B is out. Reply YES to confirm."]
    assert db.rows("closures") == [] and len(db.rows("routes")) == 1  # nothing changed yet
    assert json.loads(json.dumps(db.rows("crew_threads")[0]["pending"]))["kind"] == "elevator_out"
    assert trace_titles(db) == [
        "crew texted: elevator B is out of service",
        "texted crew: Re-routing around elevator B is out. Reply YES to confirm.",
    ]


def test_yes_runs_the_existing_replan_once_and_clears_the_question(db, registry, monkeypatch):
    sidecar = FakeSidecar()
    monkeypatch.setattr(notify, "get_sidecar", lambda: sidecar)
    monkeypatch.setattr(notify, "get_settings", lambda: type("S", (), {"photon_enabled": True})())
    classifier = FakeClassifier(
        CrewReport(category="blocker", summary="elevator B is out", elevator=True)
    )
    report(db, registry, classifier, "elevator B is out")
    out = report(db, registry, classifier, "YES")
    assert out["category"] == "confirmed" and out["replies"] == ["Re-routing now."]
    assert (
        len(db.rows("closures")) == 1 and len(db.rows("routes")) == 2
    )  # the router found a new path
    assert db.rows("crew_threads")[0]["pending"] is None
    assert classifier.seen == ["elevator B is out"]  # YES itself was not sent to Gemini
    (sent,) = sidecar.sent  # one call: the sidecar posts the briefing, then the link on its own
    assert "Re-routed" in sent["text"] and sent["url"].startswith("http")
    assert any("texted crew: Re-routed" in title for title in trace_titles(db))


def test_a_blocker_that_is_not_an_elevator_closes_the_walk_being_made(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="blocker", summary="door locked", elevator=False)
    )
    report(db, registry, classifier, "the door is locked")
    assert db.rows("crew_threads")[0]["pending"]["kind"] == "obstacle"


def test_no_cancels_the_question(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="blocker", summary="elevator B is out", elevator=True)
    )
    report(db, registry, classifier, "elevator out")
    out = report(db, registry, classifier, "no")
    assert out["replies"] == ["OK, the route stays as it is."]
    assert db.rows("crew_threads")[0]["pending"] is None and len(db.rows("routes")) == 1


def test_a_yes_with_nothing_pending_is_just_chatter(db, registry):
    out = report(db, registry, FakeClassifier(CrewReport(category="chatter", summary="")), "yes")
    assert out["replies"] == []


def test_a_destination_change_finds_the_place_on_the_map_in_code(db, registry):
    classifier = FakeClassifier(
        CrewReport(
            category="destination_change",
            summary="patient moved",
            place="Regus Suite 1800 phone room",
        )
    )
    out = report(db, registry, classifier, "patient is in the suite 1800 phone room now")
    label = "Regus Suite 1800 phone room (patient)"
    assert out["replies"] == [f"Change the destination to {label}? Reply YES to confirm."]
    assert db.rows("crew_threads")[0]["pending"] == {
        "type": "destination",
        "goal_node": "phone_door",
        "label": label,
    }


def test_a_destination_the_map_does_not_have_changes_nothing(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="destination_change", summary="x", place="the roof")
    )
    out = report(db, registry, classifier, "patient is on the roof")
    assert "couldn't find" in out["replies"][0] and db.rows("crew_threads")[0]["pending"] is None


def test_yes_to_a_new_destination_saves_a_new_route_from_the_router(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="destination_change", summary="moved", place="Regus reception")
    )
    out = report(db, registry, classifier, "patient is at reception")
    pending = db.rows("crew_threads")[0]["pending"]
    assert pending["type"] == "destination"
    report(db, registry, classifier, "yes")
    new = max(db.rows("routes"), key=lambda r: r["version"])
    assert new["version"] == 2 and new["steps"][-1]["to_node"] == pending["goal_node"]
    assert "New destination" in new["briefing"] and out["category"] == "destination_change"
    assert any(s["kind"] == "replan" for s in db.rows("plan_steps"))


def test_a_crew_tip_is_saved_as_a_note_the_agent_can_find(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="crew_tip", summary="use freight lift after 6pm")
    )
    out = report(db, registry, classifier, "FYI the freight lift is faster after 6pm")
    assert out["replies"] == ["Thanks, saved for the next crew."]
    (note,) = db.rows("notes")
    assert note["building_id"] == "233928" and "freight lift" in note["text"]


def test_a_failed_classification_is_logged_and_ignored(db, registry):
    out = report(db, registry, FakeClassifier(None), "???")
    assert out["category"] == "unclassified" and out["replies"] == []
    assert trace_titles(db) == ["crew texted: ???"]


def test_a_place_that_matches_several_nodes_asks_which_and_changes_nothing(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="destination_change", summary="x", place="phone room")
    )
    out = report(db, registry, classifier, "patient is in the phone room")
    assert out["replies"][0].startswith("Which one: ") and "phone room" in out["replies"][0]
    assert db.rows("crew_threads")[0]["pending"] is None


def test_extra_words_after_the_place_are_dropped_until_the_map_matches():
    g = graph()
    assert [n.id for n in crew.find_places(g, "Regus Suite 1800 phone room on 18")] == [
        "phone_door"
    ]
    assert [n.id for n in crew.find_places(g, "Regus reception")] == [
        "rec_a"
    ]  # an exact label wins
    assert crew.find_places(g, "the roof") == [] and crew.find_places(g, "  ") == []


def test_asking_for_directions_resends_the_route_without_asking_gemini(db, registry, monkeypatch):
    sidecar = FakeSidecar()
    monkeypatch.setattr(notify, "get_sidecar", lambda: sidecar)
    monkeypatch.setattr(notify, "get_settings", lambda: type("S", (), {"photon_enabled": True})())
    classifier = FakeClassifier(CrewReport(category="blocker", summary="x"))
    for ask in (
        "directions",
        "Directions?",
        "route",
        "send the route again",
        "where do I go",
        "resend",
        "help",
    ):
        sidecar.sent.clear()
        out = report(db, registry, classifier, ask)
        assert out["category"] == "resend" and out["replies"] == [], ask
        (sent,) = sidecar.sent
        assert (
            sent["thread_id"] == "pho_spc_1" and "Directions" in sent["text"] and sent["image_url"]
        ), ask
    assert classifier.seen == []  # a plain keyword, so no model call


def test_a_sentence_that_only_mentions_the_route_is_still_classified(db, registry):
    classifier = FakeClassifier(
        CrewReport(category="blocker", summary="route blocked", elevator=False)
    )
    out = report(db, registry, classifier, "the route is blocked by a cart")
    assert out["category"] == "blocker" and classifier.seen == ["the route is blocked by a cart"]
