# Beeline

Beeline gets a paramedic from the ambulance to the patient's door inside an unfamiliar building as fast as possible.
Built for HackPrinceton Fall 2026 (CoStar "Inside and Out").

A dispatcher types a call note ("65M chest pain, Suite 1800, 1415 Louisiana St"). An AI agent combines CoStar
building data, Vexcel aerial imagery and a Matterport interior scan, a deterministic router finds the fastest
stretcher-safe path, and a forearm wearable tells the crew where to turn. If the crew reports "elevator out" or
leaves the route, Beeline re-plans.

```
Dispatcher / medic web app (frontend/)  ──HTTP──▶  FastAPI server (backend/)  ◀──telemetry──  wearable + Raspberry Pi
              ▲                                       │        │
              └────── Supabase Realtime ◀─────────────┘        └── Gemini (agent, notes, answers)
```

| Folder | What | Owner |
| --- | --- | --- |
| `backend/` | FastAPI server, agent, router, position engine | Person 2 |
| `frontend/` | Dispatch and medic web app (see its README) | Person 1 |
| `contracts/` | Frozen shared API and data shapes | both |
| `fixtures/` | Saved snapshot of the demo building, so the demo runs offline | Person 2 |
| `supabase/` | Database migration | Person 2 |

## Run the backend

Needs Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
cd backend
cp .env.example .env        # fill in the values below
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest               # tests
uv run ruff check .         # lint
```

Create the database by running `supabase/migrations/0001_init.sql` in your Supabase project, and turn Realtime on
for `incidents`, `plan_steps`, `routes`, `positions` and `cues`.

| Variable | Purpose |
| --- | --- |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Database. The service-role key stays on the server only |
| `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL` | Gemini for the agent, note parsing and `/ask`. Fallbacks are comma separated |
| `GEMINI_EMBEDDING_MODEL` | Embeddings for crew notes (default `gemini-embedding-001`, 768 dimensions) |
| `STRIDE_M` | Metres per step used by the position engine (default 0.7) |
| `WEB_ORIGIN` | Allowed browser origins for CORS, comma separated (add your Vercel URL) |
| `WEB_ORIGIN_REGEX` | Optional pattern for Vercel preview URLs, e.g. `https://beeline-.*\.vercel\.app` |
| `MATTERPORT_*`, `VEXCEL_API_KEY`, `COSTAR_*` | Only needed to re-pull data with `backend/notebooks/make_snapshot.py` |

Try it without hardware: create an incident, wait for its route, then run the mock wearable.

```bash
curl -X POST localhost:8000/incidents -H 'content-type: application/json' \
     -d '{"note": "65M chest pain, Suite 1800, 1415 Louisiana St"}'
uv run python tools/mock_wearable.py <incident_id>     # walks the route, moves the dot, produces cues
```

## API

Full contract in `contracts/api.md`.

| Endpoint | What it does |
| --- | --- |
| `POST /incidents` | Parses the note, saves the incident, starts the agent in the background |
| `POST /incidents/{id}/telemetry` | Feeds a wearable sample to the position engine; writes `positions` and `cues` |
| `POST /incidents/{id}/events` | `elevator_out` / `obstacle` re-plan; `note` saves a crew tip; `arrived` closes the incident |
| `POST /ask` | Answers a crew question from building data, the route and crew notes |
| `GET /health` | `{ "ok": true }` |

## How it works

**Golden rule: the router picks the path, never the LLM.** Gemini reads text, plans which tools to call and writes
short briefings. The route itself always comes from NetworkX A* over the building graph, so the language model
cannot invent a corridor.

1. **Intake** (`app/intake.py`). Gemini structured output turns the note into address, suite, floor, complaint
   and access notes. If Gemini fails the incident is still saved.
2. **Agent** (`app/agent/`). A LangChain `deepagents` agent runs in the background with a call limit and model
   fallbacks. It writes a plan, delegates the building and suite lookup to a **records** subagent (CoStar data),
   checks crew notes for the building, lists the entrances, asks the router for a route from every entrance in
   parallel, and saves the fastest with a briefing of about 30 words. Every plan step, subagent call, tool call and
   tool result is written to `plan_steps`, which is the trail the web app shows live.
3. **Router** (`app/graph/router.py`). A* over the graph, weight = seconds. It skips non-stretcher-safe edges and
   anything closed for the incident, and treats stairs as a last resort. Each step gets a cue (LEFT, RIGHT,
   FLOOR_UP, ARRIVE...) from the heading change between consecutive edges. Pure, no I/O.
4. **Position engine** (`app/position/engine.py`). A state machine per incident. It converts step counts to
   metres, writes a turn cue once when a turn is within 6 m, confirms turns from the gyroscope heading change,
   detects off-route (wrong-way turn or 5 m past the turn), detects floor changes from pressure (about 35 Pa) or
   the confirm button, and snaps to a node when an RFID tag is scanned. At most one `positions` row a second.
5. **Re-plan** (`app/agent/replan.py`). On `elevator_out` (event or wearable button) or `obstacle`, it writes a
   `closures` row, runs the router again from the crew's current node, saves the next `routes` version and a
   `replan` step. This path is deliberately deterministic so it is fast and works with no model.
6. **Crew notes** (`app/notes.py`). Tips are stored per building with a Gemini embedding. Search ranks by
   cosine similarity, falling back to word matching if embeddings are unavailable. The agent searches them on every
   call to that building and `/ask` includes them.

### Data layers for the demo building (1415 Louisiana, CoStar id 233928)

| Layer | Source | What it gives |
| --- | --- | --- |
| Building data | CoStar hackathon extract | Floors, tenants and suites, elevator and parking counts, data-quality warnings |
| Aerial | Vexcel imagery | Parcel outline and images of the building from above and four sides |
| Interior | Matterport scan | Measured geometry of the Regus Suite 1800 reception, hallway and phone room |

The demo runs from the saved snapshot in `fixtures/buildings/233928/` with no external calls (`SnapshotProvider`).
Rebuild the snapshot with `backend/notebooks/make_snapshot.py` and the graph with `make_demo_graph.py`.

## Honest limits

- No scan covers the street, ground-floor lobby, elevator bank or floor-18 corridor. Those graph nodes and the
  elevator and stair times are **estimates** and must be checked by hand (`fixtures/buildings/233928/GRAPH_NOTES.md`).
  Only the Suite 1800 interior is measured.
- Only the records layer is an LLM subagent. Aerial and interior data are processed ahead of time by scripts into the
  snapshot and graph, not live by subagents.
- RFID tag ids in the demo graph are placeholders until matched to the hardware team's tags.
- All data is synthetic or public building data; there is no patient information anywhere.
