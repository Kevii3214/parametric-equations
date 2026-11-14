import csv, json, os, re, sys, time, random
from pathlib import Path
import httpx
from dotenv import load_dotenv

BACKEND = Path(__file__).resolve().parents[1]
KIT = BACKEND / "data" / "costar-hackathon-kit"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("demo_candidates.json")
load_dotenv(BACKEND / ".env")
MP_AUTH = (os.environ["MATTERPORT_API_KEY"], os.environ["MATTERPORT_API_TOKEN"])
VX_KEY = os.environ["VEXCEL_API_KEY"]

CANDIDATES = [233899, 233903, 233905, 233918, 10819844, 233927, 247506, 233928,   # office towers
              9560001, 9354100, 9557833, 9432618, 10043113, 9395438, 691919, 9447351, 12862161]  # apartment high-rises
MAX_MODELS = 12

Q = """query($id: ID!) { model(id: $id) { id name
  floors { id label }
  rooms { id label classifications { label }
          boundary { edges { id openings { id type } } } } } }"""

KW = {
    "lobby": r"lobby|entry|entrance|reception|foyer|vestibule|atrium",
    "elevator": r"elevator|lift",
    "corridor": r"hall|corridor|passage|breezeway",
    "stairs": r"stair",
    "garage": r"garage|parking",
}


def mp(model_id):
    for attempt in range(6):
        r = httpx.post("https://api.matterport.com/api/models/graph", json={"query": Q, "variables": {"id": model_id}}, auth=MP_AUTH, timeout=90)
        if r.status_code == 429:
            time.sleep(2 ** attempt + random.random()); continue
        return r
    return r


def vx(path, params):
    for attempt in range(6):
        r = httpx.get(f"https://api.vexcelgroup.com/v2/{path}", params=params, headers={"X-API-KEY": VX_KEY}, timeout=120)
        if r.status_code == 429:
            time.sleep(2 ** attempt + random.random()); continue
        return r
    return r


rows = list(csv.DictReader(open(KIT / "commercial-properties.csv", encoding="utf-8")))
props = {}
want = {str(c) for c in CANDIDATES}
with open(KIT / "data" / "commercial-property.jsonl", encoding="utf-8") as f:
    for line in f:
        m = re.match(r'\{"id":(\d+),', line)
        if m and m.group(1) in want:
            props[m.group(1)] = json.loads(line)

results = []
for pid in map(str, CANDIDATES):
    p = props[pid]
    a = p["primaryAddress"]
    models = [r["MatterportModelId"] for r in rows if r["PropertyId"] == pid and r["MatterportModelId"]]
    res = {"property_id": pid, "name": p.get("buildingName"), "address": f"{a.get('streetNumber')} {a.get('streetName')} {a.get('streetType')}",
           "city": a["city"], "type": "office" if p["propertyType"] == 5 else "apartments", "stories": p.get("numStoriesAboveGrade"),
           "models_in_kit": len(models), "models": []}
    for mid in models[:MAX_MODELS]:
        r = mp(mid)
        e = {"id": mid}
        if not r.is_success:
            e["error"] = f"HTTP {r.status_code}"
        else:
            body = r.json()
            m = (body.get("data") or {}).get("model")
            if body.get("errors") or not m:
                e["error"] = (body.get("errors") or [{}])[0].get("message", "no model")[:120]
            else:
                texts = [m.get("name") or ""]
                rooms = m.get("rooms") or []
                for rm in rooms:
                    texts.append(rm.get("label") or "")
                    texts += [c.get("label") or "" for c in rm.get("classifications") or []]
                blob = " | ".join(texts).lower()
                edges = [ed for rm in rooms for ed in ((rm.get("boundary") or {}).get("edges") or [])]
                e.update(name=m.get("name"), rooms=len(rooms), wall_edges=len(edges),
                         doorways=sum(len(ed.get("openings") or []) for ed in edges),
                         tags=[k for k, rx in KW.items() if re.search(rx, blob)])
        res["models"].append(e)
        time.sleep(0.15)
    # Vexcel: parcel + oblique coverage
    lat, lon = a.get("latitude"), a.get("longitude")
    if lat and lon:
        pt = f"POINT({lon} {lat})"
        r = vx("property/extract", {"wkt": pt, "srid": 4326, "layer": "urban,urban-r,wide-area,urban-g", "latest": "true", "include": "structure"})
        res["vexcel_parcel"] = r.status_code
        r = vx("oriented/collections", {"wkt": pt, "srid": 4326, "layer": "urban", "product-type": "oblique", "include": "product-type,last-capture-date"})
        feats = r.json()["features"] if r.is_success else []
        res["vexcel_obliques"] = sorted({f["properties"]["product-type"] for f in feats})
    results.append(res)
    ok = [m for m in res["models"] if "error" not in m]
    print(pid, res["name"], "| models", len(res["models"]), "ok", len(ok), flush=True)

OUT.write_text(json.dumps(results, indent=1), encoding="utf-8")
print("saved", OUT)
