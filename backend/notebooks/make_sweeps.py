"""Save each demo building's Matterport sweeps (camera positions) into fixtures/buildings/<id>/sweeps.json.

Run from backend/:  python -m uv run python notebooks/make_sweeps.py [building_id ...]

The fly-through tour is built from these: a sweep id is the stop the 3D viewer flies to, `neighbors` lists the sweeps
visible from it (the moves the viewer can make), and `start_pose` is the scan's opening camera view, which lets the
frontend calibrate the viewer's compass.
"""

import json
import math
import os
import sys
from datetime import date
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND.parent / "fixtures" / "buildings"
load_dotenv(BACKEND / ".env")

# building id -> {scan model id: {the scan's floor label: the floor number used in graph.json}}
BUILDINGS = {
    "233928": {"LJn59uoV759": {"Floor 1": 18}},  # the Regus suite scan covers floor 18 only
    "233903": {"eJKnR3x44eh": {"Floor 1": 56}},  # the 56th-floor scan
    "jrr": {
        "P3S6VUTP3qB": {"Floor 2": 2, "Floor 3": 3}
    },  # the scan names its two levels Floor 2 and Floor 3
}

QUERY = """query($id: ID!) { model(id: $id) { id name
  floors { id label sequence }
  locations { id position { x y z } floor { id } neighbors }
  image { snapshotLocation { position { x y z } rotation { x y z w } } }
} }"""


def bearing_and_pitch(q: dict) -> tuple[float, float]:
    """Compass bearing (0 = +y, clockwise) and pitch of a camera whose forward axis is -Z, rotated by quaternion q."""
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    vx, vy, vz = 0.0, 0.0, -1.0
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    fx, fy, fz = (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )
    return round(math.degrees(math.atan2(fx, fy)) % 360, 1), round(
        math.degrees(math.asin(max(-1, min(1, fz)))), 1
    )


def pull(model_id: str, floor_map: dict[str, int]) -> dict:
    auth = (os.environ["MATTERPORT_API_KEY"], os.environ["MATTERPORT_API_TOKEN"])
    r = httpx.post(
        "https://api.matterport.com/api/models/graph",
        json={"query": QUERY, "variables": {"id": model_id}},
        auth=auth,
        timeout=180,
    )
    r.raise_for_status()
    body = r.json()
    assert not body.get("errors"), body["errors"]
    m = body["data"]["model"]
    level_of = {f["id"]: floor_map[f["label"]] for f in m["floors"] if f["label"] in floor_map}
    sweeps = []
    for loc in m["locations"]:
        level = level_of.get(loc["floor"]["id"])
        if level is None:
            continue
        p = loc["position"]
        sweeps.append(
            {
                "id": loc["id"],
                "x": round(p["x"], 3),
                "y": round(p["y"], 3),
                "z": round(p["z"], 3),
                "level": level,
                "neighbors": loc["neighbors"] or [],
            }
        )
    snap = (m.get("image") or {}).get("snapshotLocation")
    start = None
    if snap:
        bearing, pitch = bearing_and_pitch(snap["rotation"])
        start = {
            "position": {k: round(snap["position"][k], 3) for k in "xyz"},
            "bearing_deg": bearing,
            "pitch_deg": pitch,
        }
    return {"id": model_id, "name": m["name"], "start_pose": start, "sweeps": sweeps}


if __name__ == "__main__":
    wanted = sys.argv[1:] or list(BUILDINGS)
    for building_id in wanted:
        models = [pull(mid, fm) for mid, fm in BUILDINGS[building_id].items()]
        data = {
            "building_id": building_id,
            "source": "Matterport Model API",
            "snapshot_date": str(date.today()),
            "note": "Sweep positions are metres in the scan's own frame (z up). A sweep id is the stop the viewer flies to; neighbors are the sweeps visible from it.",
            "models": models,
        }
        out = FIXTURES / building_id / "sweeps.json"
        out.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        for m in models:
            print(
                f"{building_id}: {m['name']!r}: {len(m['sweeps'])} sweeps, levels {sorted({s['level'] for s in m['sweeps']})}, start bearing {m['start_pose'] and m['start_pose']['bearing_deg']}"
            )
