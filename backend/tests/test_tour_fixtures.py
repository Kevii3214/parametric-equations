import json
import sys
from pathlib import Path

import pytest

from app.tour import Tour

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "notebooks"))

from make_tours import SAMPLES, sample_tour


@pytest.mark.parametrize("building_id", list(SAMPLES))
def test_the_saved_sample_tour_matches_what_the_code_produces_now(building_id):
    """If the router, the graph or the tour builder changes, rerun notebooks/make_tours.py."""
    saved = json.loads(
        (ROOT / "fixtures" / "buildings" / building_id / "tour_sample.json").read_text(
            encoding="utf-8"
        )
    )
    assert saved == sample_tour(building_id)
    Tour.model_validate(saved)


def test_the_published_schema_matches_the_model():
    published = json.loads((ROOT / "contracts" / "tour.schema.json").read_text(encoding="utf-8"))
    assert published == Tour.model_json_schema()
