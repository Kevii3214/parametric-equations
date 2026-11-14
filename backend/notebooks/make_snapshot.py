"""Save one building's three data layers into fixtures/buildings/<id>/ so the demo runs with no internet.

Usage (from backend/):  python -m uv run python notebooks/make_snapshot.py 233928

Reads the CoStar kit in backend/data/, calls the Matterport and Vexcel APIs (keys in backend/.env),
and writes record.json, interior.json, aerial.json and the aerial JPEGs. Only fields the routing
needs are kept: no broker or contact details.
"""

import csv
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
KIT = BACKEND / "data" / "costar-hackathon-kit"
FIXTURES = BACKEND.parent / "fixtures" / "buildings"
LAYERS = "urban,urban-r,wide-area,urban-g"
load_dotenv(BACKEND / ".env")

PID = sys.argv[1]
OUT = FIXTURES / PID
OUT.mkdir(parents=True, exist_ok=True)
enums = json.load(open(KIT / "schemas" / "enums.json", encoding="utf-8"))
decode = lambda enum, v: enums[enum].get(str(v), v)


def find_line(path, prefix):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith(prefix):
                return json.loads(line)


def find_key(obj, key):
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, key)
            if found is not None:
                return found


def write_json(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote", name)


# ---------------------------------------------------------------- CoStar record
prop = find_line(KIT / "data" / "commercial-property.jsonl", f'{{"id":{PID},')
addr = prop["primaryAddress"]
floors = {f["propertyFloorId"]: f["floorName"] for f in prop.get("floors") or []}
models = sorted(
    {
        r["MatterportModelId"]
        for r in csv.DictReader(open(KIT / "commercial-properties.csv", encoding="utf-8"))
        if r["PropertyId"] == PID and r["MatterportModelId"]
    }
)

occupancies = []
needle = f'"propertyId":{PID},'
with open(KIT / "data" / "location-occupancy.jsonl", encoding="utf-8") as f:
    for line in f:
        if needle in line:
            r = json.loads(line)
            if r["propertyId"] == int(PID):
                occupancies.append(r)
company_ids = {o["tenantLocationId"] for o in occupancies if o.get("tenantLocationId")}
companies = {}
with open(KIT / "data" / "company-detail.jsonl", encoding="utf-8") as f:
    for line in f:
        c = json.loads(line)
        if c["id"] in company_ids:
            companies[c["id"]] = c.get("name")

tenants = []
for o in occupancies:
    if o.get("expirationReason"):  # has an expiration reason = no longer there
        continue
    for s in o.get("spaces") or []:
        suite = (s.get("suite") or "").strip() or None
        tenants.append(
            {
                "suite": suite,
                # CoStar's floorName does not match real floors (suite 3000 -> "63" in a 43-story building),
                # so the floor is guessed from the suite number instead: 2350 -> floor 23.
                "floor_guess_from_suite": int(suite) // 100
                if suite and re.fullmatch(r"\d{3,4}", suite)
                else None,
                "company": companies.get(o.get("tenantLocationId")),
            }
        )

record = {
    "building_id": PID,
    "source": "CoStar hackathon data kit",
    "snapshot_date": str(date.today()),
    "name": prop.get("buildingName"),
    "address": f"{addr.get('streetNumber')} {addr.get('streetName')} {addr.get('streetType')}",
    "city": addr["city"],
    "state": addr["state"],
    "postcode": addr.get("postcode"),
    "latitude": addr.get("latitude"),
    "longitude": addr.get("longitude"),
    "property_type": decode("PropertyType", prop.get("propertyType")),
    "building_class": prop.get("buildingClass"),
    "building_rating": prop.get("buildingRating"),
    "stories_above_grade": prop.get("numStoriesAboveGrade"),
    "gross_area_sqft": prop.get("grossBuildingAreaSquareFeet"),
    "typical_floor_sqft": prop.get("grossTypicalFloorSquareFeet"),
    "data_quality_notes": [
        "CoStar lists 45 floors named 1, 18, 21, 24..67 for a 43-story building, and tenant floor names do not match "
        "suite numbers, so CoStar floor names are not used. Trust stories_above_grade and the suite numbers.",
        "Elevator counts are building totals; which elevator serves which floors is not in the data.",
    ],
    "elevators": [
        {
            "type": decode("ElevatorType", e.get("elevatorType")),
            "count": e.get("numElevators"),
            "exists": e.get("elevatorState") == 1,
        }
        for e in (find_key(prop, "elevators") or [])
    ],
    "parking": [
        {
            "type": decode("ParkingType", p.get("parkingType")),
            "spaces": p.get("totalSpaces"),
            "monthly_fee": p.get("monthlyParkingFee"),
        }
        for p in prop.get("parking") or []
    ],
    "matterport_model_ids": models,
    "current_tenants": tenants,
}
write_json("record.json", record)

# ------------------------------------------------------------------ Matterport
MP_AUTH = (os.environ["MATTERPORT_API_KEY"], os.environ["MATTERPORT_API_TOKEN"])
QUERY = """query($id: ID!) { model(id: $id) { id name created modified
  floors { id sequence label }
  rooms { id label classifications { label }
    boundary { edges { id type thickness
      openings { id type width height lowerElevation relativeCenter }
      vertices { id position { x y } } } } } } }"""
interior = {
    "building_id": PID,
    "source": "Matterport Model API",
    "snapshot_date": str(date.today()),
    "note": "Room coordinates (metres) are relative to each model's own centre, not to each other.",
    "models": [],
}
for mid in models:
    r = httpx.post(
        "https://api.matterport.com/api/models/graph",
        json={"query": QUERY, "variables": {"id": mid}},
        auth=MP_AUTH,
        timeout=120,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors") or not body["data"]["model"]:
        print("matterport error for", mid, body.get("errors"))
        continue
    interior["models"].append(body["data"]["model"])
    time.sleep(0.2)
write_json("interior.json", interior)

# ---------------------------------------------------------------------- Vexcel
VX = {"X-API-KEY": os.environ["VEXCEL_API_KEY"]}
vx = lambda method, path, **kw: httpx.request(
    method, f"https://api.vexcelgroup.com/v2/{path}", headers=VX, timeout=300, **kw
)
point = f"POINT({addr['longitude']} {addr['latitude']})"
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
aerial = {
    "building_id": PID,
    "source": "Vexcel API 2.0",
    "snapshot_date": str(date.today()),
    "images": {},
}
if r.status_code == 404:
    parcel_wkt = None
else:
    r.raise_for_status()
    feat = r.json()["features"][0]
    attrs = feat["properties"]
    g = feat["geometry"]
    from shapely import wkt as swkt
    from shapely.geometry import shape

    parcel_wkt = swkt.loads(g).wkt if isinstance(g, str) else shape(g).wkt
    aerial["parcel_wkt"] = parcel_wkt
    aerial["collection"] = attrs.get("metadata.collection")
    aerial["structure_count"] = attrs.get("structure.count")
    aerial["structure_footprints_sqft"] = [
        round(s.get("footprint.area", 0)) for s in attrs.get("structures", [])
    ]
area = parcel_wkt or point
size = {"destination-dimensions": "1200,1200"}
r = vx(
    "POST",
    "ortho/extract",
    json={
        "wkt": area,
        "srid": 4326,
        "layer": LAYERS,
        "buffer-meter": 30,
        "crop": "bounding_box",
        "image-format": "jpeg",
        **size,
    },
)
r.raise_for_status()
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
    r = vx(
        "POST",
        "oriented/extract",
        json={
            "wkt": area,
            "srid": 4326,
            "layer": "urban",
            "product-type": d,
            "rotation": "natural",
            "buffer-meter": 30,
            "crop": "bbox",
            "image-format": "jpeg/png",
            **size,
        },
    )
    if r.is_success:
        (OUT / f"{d}.jpg").write_bytes(r.content)
        aerial["images"][d] = {"file": f"{d}.jpg", "kb": len(r.content) // 1024, "captured": newest}
    else:
        print("oblique failed", d, r.status_code, r.text[:200])
write_json("aerial.json", aerial)

# ------------------------------------------------------------------ address index
index_path = FIXTURES / "index.json"
index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
street = re.sub(
    r"[^a-z0-9 ]",
    "",
    f"{addr['streetNumber']} {addr['streetName']} {addr.get('streetType') or ''}".lower(),
).strip()
index[PID] = {
    "name": record["name"],
    "aliases": [street, re.sub(r"[^a-z0-9 ]", "", (record["name"] or "").lower())],
}
index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
print("snapshot done:", OUT)
