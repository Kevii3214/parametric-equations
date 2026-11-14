from pathlib import Path

from app.briefing import MAX_WORDS, clip_words, spoken_briefing
from app.graph.router import find_route
from app.graph.schema import BuildingGraph

DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928" / "graph.json"
GRAPH = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))


def test_briefing_names_entrance_lift_floor_and_destination_in_few_words():
    text = spoken_briefing(GRAPH, find_route(GRAPH, "st_main", "phone_door"))
    assert len(text.split()) <= MAX_WORDS
    assert "Louisiana St main entrance" in text
    assert "elevator" in text.lower() and "18" in text
    assert "phone room" in text.lower()


def test_briefing_mentions_stairs_when_the_route_uses_them():
    steps = find_route(GRAPH, "st_main", "phone_door", ["el1->el18"])
    assert "stairs" in spoken_briefing(GRAPH, steps).lower()


def test_empty_route_gives_empty_briefing():
    assert spoken_briefing(GRAPH, []) == ""


def test_clip_words_keeps_short_text_and_cuts_long_text_at_a_sentence_end():
    assert clip_words("Short one.", 5) == "Short one."
    assert clip_words("One two three. Four five six seven eight.", 5) == "One two three."
    assert clip_words("a b c d e f g h", 4) == "a b c d"
