import hashlib
import io
from pathlib import Path

import pytest
from PIL import Image

from app.config import Settings
from app.graph.router import NoRouteError, find_route
from app.graph.schema import BuildingGraph
from app.photon import share
from app.photon.card import CARD_SIZE, render_route_card, static_card

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "buildings"


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    s = Settings(
        _env_file=None,
        supabase_service_role_key="service-role-key",
        public_api_url="https://api.example.com/",
    )
    monkeypatch.setattr(share, "get_settings", lambda: s)
    return s


def graph(building="233928"):
    return BuildingGraph.model_validate_json(
        (FIXTURES / building / "graph.json").read_text(encoding="utf-8")
    )


def png(data: bytes) -> Image.Image:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(data))


# ----------------------------------------------------------------- share links


def test_a_token_belongs_to_one_incident():
    token = share.make_token("inc-1")
    assert share.check_token("inc-1", token)
    assert not share.check_token("inc-2", token)
    assert not share.check_token("inc-1", "")
    assert not share.check_token("inc-1", token[:-1] + ("0" if token[-1] != "0" else "1"))


def test_the_token_does_not_contain_the_secret_it_is_derived_from():
    assert "service-role-key" not in share.make_token("inc-1")


def test_the_link_is_the_medic_path_with_the_token_and_no_double_slash():
    url = share.medic_url("inc-1")
    assert url == f"https://api.example.com/medic/inc-1?t={share.make_token('inc-1')}"
    assert share.card_url("inc-1").startswith("https://api.example.com/medic/inc-1/card.png?t=")


def test_the_version_makes_the_link_new_for_each_route_but_the_same_token_works():
    one, two = share.medic_url("inc-1", 1), share.medic_url("inc-1", 2)
    assert one != two and one.endswith("&v=1") and two.endswith("&v=2")
    assert share.card_url("inc-1", 2).endswith("&v=2")
    assert share.check_token("inc-1", share.make_token("inc-1"))


def test_a_configured_secret_changes_the_token(monkeypatch, settings):
    before = share.make_token("inc-1")
    monkeypatch.setattr(
        share, "get_settings", lambda: settings.model_copy(update={"share_secret": "x"})
    )
    assert share.make_token("inc-1") != before


# ------------------------------------------------------------------ route card


def test_the_route_card_is_a_png_of_the_standard_preview_size():
    g = graph()
    steps = find_route(g, "gar1", "phone_door")
    image = png(
        render_route_card(g, steps, title="1415 Louisiana", subtitle="Suite 1800, floor 18")
    )
    assert image.size == CARD_SIZE == (1200, 630)


def test_different_routes_draw_different_cards():
    g = graph()
    a = render_route_card(g, find_route(g, "gar1", "phone_door"), title="t", subtitle="s")
    b = render_route_card(g, find_route(g, "st_main", "phone_door"), title="t", subtitle="s")
    assert hashlib.sha256(a).digest() != hashlib.sha256(b).digest()


def test_a_single_floor_route_and_every_demo_building_render():
    for building in ("233903", "jrr", "233928"):
        g = graph(building)
        entrance = next(n.id for n in g.nodes if n.kind == "entrance")
        goal = next(n.id for n in g.nodes if n.kind != "entrance" and n.id != entrance)
        try:
            steps = find_route(g, entrance, goal)
        except NoRouteError:
            continue  # not every node pair is connected; the point is that drawing never fails
        assert png(render_route_card(g, steps, title=building, subtitle="x")).size == CARD_SIZE


def test_an_empty_route_still_gives_a_card():
    assert png(render_route_card(graph(), [], title="t", subtitle="s")).size == CARD_SIZE


# ----------------------------------------------------------- the static fallback


def test_the_fallback_uses_the_buildings_aerial_picture():
    image = png(static_card("233928", FIXTURES, title="1415 Louisiana", subtitle="Suite 1800"))
    assert image.size == CARD_SIZE


def test_the_fallback_for_an_unknown_building_is_still_a_card():
    assert png(static_card("nope", FIXTURES, title="t", subtitle="s")).size == CARD_SIZE
    assert png(static_card(None, FIXTURES, title="t", subtitle="s")).size == CARD_SIZE
