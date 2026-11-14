"""Save the Princeton Rabinowitz Hall (JRR) snapshot into fixtures/buildings/jrr/.

Run from backend/:  python -m uv run python notebooks/make_jrr_snapshot.py

This building is not in the CoStar kit, so record.json is written by hand (marked as such). The Matterport
scan (model P3S6VUTP3qB) and Vexcel imagery are fetched from the APIs, as for the other buildings.
"""

import json
import os
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND.parent / "fixtures" / "buildings"
OUT = FIXTURES / "jrr"
OUT.mkdir(parents=True, exist_ok=True)
load_dotenv(BACKEND / ".env")

BUILDING_ID = "jrr"
MODEL_ID = "P3S6VUTP3qB"
LAYERS = "urban,urban-r,wide-area,urban-g"
today = str(date.today())


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


# ------------------------------------------------------------------ Matterport
auth = (os.environ["MATTERPORT_API_KEY"], os.environ["MATTERPORT_API_TOKEN"])
QUERY = """query($id: ID!) { model(id: $id) { id name created modified
  geolocation { lat long }
  floors { id label sequence }
  rooms { id label classifications { label } floor { id label sequence }
    boundary { edges { id type thickness
      openings { id type width height lowerElevation relativeCenter }
      vertices { id position { x y } } } }
    holes { edges { id type
      openings { id type width relativeCenter }
      vertices { id position { x y } } } } }
  locations { id label position { x y z } floor { id } room { id } }
} }"""
r = httpx.post(
    "https://api.matterport.com/api/models/graph",
    json={"query": QUERY, "variables": {"id": MODEL_ID}},
    auth=auth,
    timeout=180,
)
r.raise_for_status()
body = r.json()
assert not body.get("errors"), body["errors"]
model = body["data"]["model"]
write_json(
    "interior.json",
    {
        "building_id": BUILDING_ID,
        "source": "Matterport Model API",
        "snapshot_date": today,
        "note": "Coordinates (metres) are relative to the model's own centre. The scan names its two levels Floor 2 and Floor 3; Floor 1 is empty.",
        "models": [model],
    },
)
lat, lon = float(model["geolocation"]["lat"]), float(model["geolocation"]["long"])

# ---------------------------------------------------------------------- record
record = {
    "building_id": BUILDING_ID,
    "source": "written by hand: not in the CoStar kit",
    "snapshot_date": today,
    "name": "Rabinowitz Hall (JRR)",
    "address": "Princeton University",
    "city": "Princeton",
    "state": "NJ",
    "postcode": "08544",
    "latitude": lat,
    "longitude": lon,
    "property_type": "Education",
    "stories_above_grade": None,
    "floor_names": ["Floor 2", "Floor 3"],
    "elevators": [],
    "parking": [],
    "matterport_model_ids": [MODEL_ID],
    "current_tenants": [],
    "data_quality_notes": [
        "Not a CoStar building: this record was written by hand from the Matterport scan. The street address, "
        "number of floors and elevators are unknown.",
        "The scan covers two levels, which it calls Floor 2 (the open atrium hall) and Floor 3 (a ring corridor "
        "around the atrium, with a classroom). Whether these are the building's real second and third floors is "
        "not known.",
        "No elevator is recorded: the scan does not show one.",
    ],
}
write_json("record.json", record)

# ---------------------------------------------------------------------- Vexcel
VX = {"X-API-KEY": os.environ["VEXCEL_API_KEY"]}
vx = lambda method, path, **kw: httpx.request(
    method, f"https://api.vexcelgroup.com/v2/{path}", headers=VX, timeout=300, **kw
)
point = f"POINT({lon} {lat})"
aerial = {
    "building_id": BUILDING_ID,
    "source": "Vexcel API 2.0",
    "snapshot_date": today,
    "images": {},
}
area = point
r = vx(
    "GET",
    "property/extract",
    params={
        "wkt": point,
        "srid": 4326,
        "layer": LAYERS,
        "latest": "true",
        "include": "precomputed",
        "unit-system": "imperial",
    },
)
print("vexcel property/extract:", r.status_code)
if r.status_code == 200:
    from shapely import wkt as swkt
    from shapely.geometry import shape

    feat = r.json()["features"][0]
    g = feat["geometry"]
    area = swkt.loads(g).wkt if isinstance(g, str) else shape(g).wkt
    aerial["parcel_wkt"] = area
    aerial["collection"] = feat["properties"].get("metadata.collection")
elif r.status_code != 404:
    print("  unexpected:", r.text[:200])
size = {"destination-dimensions": "1200,1200"}
r = vx(
    "POST",
    "ortho/extract",
    json={
        "wkt": area,
        "srid": 4326,
        "layer": LAYERS,
        "buffer-meter": 40,
        "crop": "bounding_box",
        "image-format": "jpeg",
        **size,
    },
)
print("vexcel ortho:", r.status_code)
if r.is_success and r.content:
    (OUT / "aerial.jpg").write_bytes(r.content)
    aerial["images"]["ortho"] = {"file": "aerial.jpg", "kb": len(r.content) // 1024}
    r = vx(
        "GET",
        "oriented/collections",
        params={
            "wkt": area,
            "srid": 4326,
            "layer": "urban",
            "product-type": "oblique",
            "include": "product-type,collection,last-capture-date",
        },
    )
    feats = r.json()["features"] if r.is_success else []
    newest = max((f["properties"]["last-capture-date"] for f in feats), default=None)
    for d in sorted(
        {
            f["properties"]["product-type"]
            for f in feats
            if f["properties"]["last-capture-date"] == newest
        }
    ):
        rr = vx(
            "POST",
            "oriented/extract",
            json={
                "wkt": area,
                "srid": 4326,
                "layer": "urban",
                "product-type": d,
                "rotation": "natural",
                "buffer-meter": 40,
                "crop": "bbox",
                "image-format": "jpeg/png",
                **size,
            },
        )
        if rr.is_success:
            (OUT / f"{d}.jpg").write_bytes(rr.content)
            aerial["images"][d] = {
                "file": f"{d}.jpg",
                "kb": len(rr.content) // 1024,
                "captured": newest,
            }
else:
    aerial["note"] = f"Vexcel returned HTTP {r.status_code} for this location: {r.text[:150]}"
write_json("aerial.json", aerial)

# ---------------------------------------------------------------- address index
index_path = FIXTURES / "index.json"
index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
aliases = [
    "jrr",
    "jrr building",
    "rabinowitz",
    "rabinowitz hall",
    "rabinowitz building",
    "julis romo rabinowitz",
]
index[BUILDING_ID] = {"name": record["name"], "aliases": aliases}
index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
print("index updated; aliases:", aliases)
print("images:", sorted(aerial["images"]) or "none (see aerial.json)")
