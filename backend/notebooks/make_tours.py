"""Write a sample fly-through tour per demo building into fixtures/buildings/<id>/tour_sample.json.

Run from backend/:  python -m uv run python notebooks/make_tours.py

Same routes the agent picks for the sample calls (fastest entrance to the patient). The frontend can develop and
demo against these without a server, like the other fixtures. tests/test_tour_fixtures.py keeps them in sync.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.tour import build_tour

BUILDINGS = Path(__file__).resolve().parents[2] / "fixtures" / "buildings"

# building id -> (entrance, text in the patient node's label)
SAMPLES = {
    "233928": ("gar1", "phone room (patient)"),
    "233903": ("gar1", "conference room (patient)"),
    "jrr": ("entrance1", "classroom (patient)"),
}


def sample_tour(building_id: str) -> dict:
    start, text = SAMPLES[building_id]
    folder = BUILDINGS / building_id
    graph = BuildingGraph.model_validate_json((folder / "graph.json").read_text(encoding="utf-8"))
    scans = json.loads((folder / "sweeps.json").read_text(encoding="utf-8"))
    goal = next(n.id for n in graph.nodes if n.label and text in n.label.lower())
    return build_tour(find_route(graph, start, goal), graph, scans)


if __name__ == "__main__":
    for building_id in SAMPLES:
        tour = sample_tour(building_id)
        (BUILDINGS / building_id / "tour_sample.json").write_text(
            json.dumps(tour, indent=1) + "\n", encoding="utf-8"
        )
        print(
            f"{building_id}: {len(tour['keyframes'])} stops, {tour['duration_ms'] / 1000:.1f} s, segments {[s['kind'] for s in tour['segments']]}"
        )
