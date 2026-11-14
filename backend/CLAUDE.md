# CLAUDE.md — Beeline backend (Person 2)

You are helping **Person 2**, who owns the server, the AI agent and the data for **Beeline**, a HackPrinceton Fall 2026 project. Person 2 is new to this stack: explain what you are doing in plain words, keep changes small, and stop to ask when something is unclear.

## What Beeline is

Beeline gets a paramedic from the ambulance to the patient's door inside an unfamiliar building as fast as possible.

1. A dispatcher types a call note, e.g. "65M chest pain, Suite 1420, 1000 Main St".
2. An AI agent combines three data layers for that building, all from CoStar's toolkit:
   - **CoStar building data**: floors, tenants and suites, elevators, parking.
   - **Vexcel aerial imagery**: entrances, driveways, loading dock, where the ambulance should stop.
   - **Matterport 3D scan**: the interior layout: corridors, doors, elevators, stairs, with real distances.
3. A deterministic router finds the fastest stretcher-safe path from the curb to the suite door.
4. A wearable on the paramedic's forearm (Arduino Mega + sensors, linked through a Raspberry Pi) sends steps, heading, air pressure, button presses and RFID tag scans. The server tracks progress along the route and sends turn cues back ("LEFT in 6 m").
5. If the paramedic goes off-route or reports "elevator out", the agent re-plans.

**Primary prize:** CoStar "Inside and Out". Scored 30% data use (combine at least two layers intelligently), 30% agentic depth (plans, acts, re-plans; not a chat wrapper), 25% usefulness, 15% demo. Also entered: LangChain "Best use of deepagents", Amazon "Best Practical AI Innovation", Gemini API, Healthcare track, hardware prizes.

**Demo building:** a real Houston or Los Angeles building from the CoStar dataset with a Matterport scan covering the lobby, an elevator bank and an upper-floor suite. Not chosen yet; choosing it is ticket P2-2.

## Golden rules

1. **The router picks the path, never the LLM.** Gemini parses text, reads images, plans which tools to call and writes briefings. Path choice is always NetworkX A* over the graph. This is a safety rule; do not break it.
2. **Stay in your folders.** Person 2 owns `server/`, `supabase/` and `fixtures/`. Never edit `web/` (Person 1) or `firmware/` (hardware team).
3. **`contracts/` is shared and frozen.** If a change is needed there, stop and tell Person 2 to get a thumbs-up from Person 1 first. Do not edit it on your own.
4. **Secrets live in `.env`** (git-ignored). Only `.env.example`, with empty values, is committed. Never print or log keys.
5. **Synthetic data only.** No real patient information anywhere: fixtures, logs, prompts or commits.
6. **The demo must survive bad Wi-Fi.** Everything for the demo building must also work from a saved snapshot in `fixtures/` with no external calls.

## Stack

| Piece | Choice |
| --- | --- |
| Language | Python 3.11+ |
| Package manager | `uv` (`uv add <pkg>`, `uv run <cmd>`) |
| Web framework | FastAPI + Pydantic v2, served by uvicorn |
| Database | Supabase (Postgres + Realtime + pgvector), via the `supabase` Python client |
| Agent | LangChain `deepagents` (`create_deep_agent`), which runs on LangGraph |
| LLM | Gemini via `langchain-google-genai`; model name from `GEMINI_MODEL` env var |
| CoStar tools | CoStar's MCP servers, loaded with `langchain-mcp-adapters` (`MultiServerMCPClient`) |
| Routing | NetworkX |
| Tests and lint | pytest, ruff |
| Hosting | Render or Railway (Person 1 hosts the frontend on Vercel) |

**The CoStar toolkit is unknown until ticket P2-2.** Do not invent CoStar endpoints, field names or MCP tool names. Inspect what the toolkit actually exposes first, then write code against that. Keep all CoStar-specific code behind the `BuildingProvider` interface.

## Repo layout

```
beeline/
  contracts/        SHARED, frozen after ticket 0: JSON schemas both halves build against
  fixtures/         Person 2 writes, Person 1 reads: sample data in contract shapes
  server/           Person 2
    pyproject.toml
    app/
      main.py         FastAPI app, CORS, router registration
      config.py       Settings from env vars (pydantic-settings)
      models.py       Pydantic models mirroring contracts/
      db.py           Supabase client and table helpers
      api/            incidents.py, telemetry.py, events.py, ask.py
      providers/      base.py (BuildingProvider), costar.py, snapshot.py
      graph/          schema.py, build.py, router.py (A*)
      position/       engine.py
      agent/          agent.py, subagents.py, tools.py, trace.py
    tests/
    notebooks/        costar_pull.ipynb (P2-2)
  supabase/         Person 2
    migrations/0001_init.sql
  web/              Person 1 — do not touch
  firmware/         hardware team — do not touch
```

## Environment variables (`.env.example`)

```
SUPABASE_URL=
SUPABASE_SERVICE_ROLE_KEY=
GOOGLE_API_KEY=
GEMINI_MODEL=
COSTAR_API_KEY=
COSTAR_MCP_URL=
DEMO_BUILDING_ID=
USE_SNAPSHOT=false
STRIDE_M=0.7
WEB_ORIGIN=http://localhost:5173
```

Add CoStar variables to match whatever the toolkit actually needs. The service-role key stays on the server only; never send it to the browser.

## Commands

```
uv sync                                         # install
uv run uvicorn app.main:app --reload --port 8000  # run locally (from server/)
uv run pytest                                   # tests
uv run ruff check . && uv run ruff format .     # lint and format
```

## Contracts (the only connection between halves)

### HTTP endpoints Person 1 calls

| Method and path | Body | Response |
| --- | --- | --- |
| `POST /incidents` | `{ "note": str }` | `{ "incident_id": uuid }`; agent starts in the background |
| `POST /incidents/{id}/telemetry` | Telemetry (below) | `{ "ok": true }` |
| `POST /incidents/{id}/events` | `{ "type": "elevator_out" \| "obstacle" \| "note" \| "arrived", "text": str \| null }` | `{ "ok": true }` |
| `POST /ask` | `{ "incident_id": uuid, "question": str }` | `{ "answer": str }` |
| `GET /health` | — | `{ "ok": true }` |

The telemetry endpoint is also called by the hardware team's bridge script on the Raspberry Pi.

### Telemetry (wearable bridge → server, about 5 per second)

```json
{ "t": 182340, "steps": 57, "heading": 271.5, "pressure": 100982.4, "btn": 0, "tag": null }
```

- `t`: milliseconds since the wearable booted.
- `steps`: running step count since boot. Compute deltas server-side.
- `heading`: degrees 0–360 from the gyroscope; relative, drifts slowly. Use **changes** in heading, never absolute values.
- `pressure`: pascals. About 40–50 Pa drop per floor climbed.
- `btn`: 0 none, 1 confirm (checkpoint or elevator ride), 2 "elevator out".
- `tag`: RFID tag UID string when a tag was scanned in this sample, else null.

### Cue values (server → wearable and phone)

`LEFT`, `RIGHT`, `STRAIGHT`, `UTURN`, `FLOOR_UP`, `FLOOR_DOWN`, `ARRIVE`, `OFF_ROUTE`

### Supabase tables Person 1 reads live (Realtime enabled)

```sql
incidents (id uuid pk default gen_random_uuid(), created_at timestamptz default now(),
           note text, parsed jsonb, building_id text, status text)        -- status: planning | routing | en_route | arrived
plan_steps (id bigserial pk, incident_id uuid fk, seq int, kind text,      -- kind: plan | subagent | tool_call | tool_result | replan | final
            title text, detail jsonb, created_at timestamptz default now())
routes    (id bigserial pk, incident_id uuid fk, version int, entrance_node text,
           steps jsonb, total_seconds int, briefing text, created_at timestamptz default now())
positions (id bigserial pk, incident_id uuid fk, route_version int, step_index int,
           progress_m real, floor int, off_route bool, created_at timestamptz default now())
cues      (id bigserial pk, incident_id uuid fk, route_version int, cue text,
           dist_m real, text text, created_at timestamptz default now())
```

`routes.steps` is a list of `{ "index", "from_node", "to_node", "cue", "meters", "seconds", "floor", "text" }`.

### Person 2's private tables (Person 1 never reads these)

```sql
buildings (id text pk, name text, address text, record jsonb, aerial jsonb, updated_at timestamptz)
graphs    (building_id text pk fk, graph jsonb, source text, checked_by_hand bool default false, updated_at timestamptz)
notes     (id bigserial pk, building_id text fk, text text, embedding vector(768), created_at timestamptz default now())
closures  (id bigserial pk, incident_id uuid fk, node_or_edge text, reason text, created_at timestamptz default now())
```

Check the embedding size against the Gemini embedding model actually used, and change `768` to match.

### Building graph

```json
{
  "building_id": "costar-property-id",
  "nodes": [
    { "id": "n12", "floor": 14, "x": 14.2, "y": 6.0, "kind": "door",
      "label": "Suite 1420", "tag_id": null }
  ],
  "edges": [
    { "from": "n11", "to": "n12", "meters": 8.5, "kind": "corridor",
      "stretcher_ok": true, "seconds": 7 }
  ]
}
```

- Node kinds: `entrance`, `corridor`, `door`, `elevator`, `stairs`, `aed`.
- Elevator and stair edges connect floors; `seconds` includes wait or climb time.
- `tag_id` links a node to an RFID tag UID (entrance and suite door in the demo).
- Coordinates are metres on that floor's plan.

## Design notes

### BuildingProvider

```python
class BuildingProvider(Protocol):
    async def resolve(self, address: str) -> str: ...            # address → building_id
    async def record(self, building_id: str) -> dict: ...        # CoStar building data
    async def aerial(self, building_id: str) -> bytes: ...       # Vexcel image
    async def interior(self, building_id: str) -> dict: ...      # Matterport scan data
```

`CoStarProvider` calls the real toolkit. `SnapshotProvider` reads `fixtures/`. `USE_SNAPSHOT=true` switches to it.

### Router (`graph/router.py`)

- Build a `networkx.DiGraph` from the graph JSON; edge weight = `seconds`.
- A* heuristic: straight-line distance on the same floor ÷ 1.3 m/s; 0 across floors.
- Constraints: skip edges with `stretcher_ok: false`; skip anything listed in `closures` for this incident; prefer elevators over stairs (add a large penalty to stairs unless no elevator path exists).
- Output: turn-by-turn steps. Compute each step's cue from the heading change between consecutive edges (about ±45° or more = LEFT/RIGHT, about 180° = UTURN, floor change = FLOOR_UP/FLOOR_DOWN, last step = ARRIVE).
- Must be pure and fast: no I/O, fully unit-tested against `fixtures/`.

### Position engine (`position/engine.py`)

A small state machine per incident, also pure and unit-tested:

- Distance walked = (steps − steps at route start) × `STRIDE_M`. Advance along the route by distance.
- Within 6 m of the next turn, write a cue row **once** for that step.
- After a LEFT or RIGHT cue, a heading change of about 60–120° in the expected direction confirms the turn. A large change the wrong way, or walking more than about 5 m past the turn, sets `off_route` and writes an `OFF_ROUTE` cue.
- Floor change: pressure drop or rise beyond about 35 Pa from the floor baseline, or `btn: 1` while at an elevator node.
- `tag` scan: snap position to the node with that `tag_id` and reset the heading baseline.
- `btn: 2`: treat as an `elevator_out` event.
- Write at most one `positions` row per second to keep Realtime traffic low.

### Agent (`agent/`)

- `create_deep_agent(model=..., tools=..., subagents=..., system_prompt=...)` with Gemini via `langchain-google-genai`.
- Subagents, one per layer:
  - **records**: CoStar building data → building, floor and suite for the patient; elevator and parking facts.
  - **aerial**: Vexcel image + Gemini vision → entrances with positions, ambulance stopping point, hazards.
  - **interior**: Matterport scan + Gemini vision → building graph in the schema above. Cache in `graphs`; for the demo building, check it by hand and set `checked_by_hand`.
- Main-agent tools: `route(building_id, start_node, goal_node)`, `brief_crew(route)`, `send_cue(incident_id, cue)`, `save_note(building_id, text)`, `search_notes(building_id, query)`, plus CoStar MCP tools.
- The main agent matches each aerial entrance to an interior entrance node and asks `route` for each, then picks the fastest.
- **Every plan step, subagent call, tool call and tool result is written to `plan_steps`** (`agent/trace.py`). This trace is what judges see; it proves the "agentic depth" score.
- Re-plan triggers: `OFF_ROUTE`, `elevator_out`, `obstacle`. Write a `closures` row, reroute from the current node, write a new `routes` version and a `replan` plan step.
- Cap the agent (LangGraph recursion limit) so it cannot loop during the demo.
- Run the agent as a background task after `POST /incidents` returns; never block the request.

## Tickets (Person 2)

Work one ticket at a time on a branch named `p2/<number>-<slug>`, e.g. `p2/4-router`. Open a PR and merge the same hour. Pull `main` before starting each ticket.

- [ ] **Ticket 0 (with Person 1, first 45 min):** repo layout, `contracts/` written, hand-typed `fixtures/` (one building graph, one route, six plan steps), Supabase project with the five shared tables and Realtime on, `.env` shared.
- [ ] **P2-1 Scaffold.** FastAPI app with `/health`, CORS for `WEB_ORIGIN`, settings, Supabase client, `supabase/migrations/0001_init.sql`. Deployed to Render or Railway. *Done when* the deployed `/health` returns ok.
- [ ] **P2-2 CoStar pull.** Notebook that fetches building data, the Matterport scan and the Vexcel image for one address and prints what comes back. Pick the demo building and a spare. *Done when* all three layers load for the demo building.
- [ ] **P2-3 Real fixtures.** Save the demo building's data as a snapshot in `fixtures/`, same shapes as ticket 0. Implement `SnapshotProvider`. Tell Person 1 when merged.
- [ ] **P2-4 Router.** A* with constraints and turn-by-turn output. *Done when* pytest passes on the fixture graph, including a closed-elevator case.
- [ ] **P2-5 Intake.** `POST /incidents`: Gemini structured output parses the note into `{address, suite, floor, complaint, access_notes}` and writes an `incidents` row. *Done when* Person 1's form creates a row (sync point Saturday 10 AM).
- [ ] **P2-6 Agent + records subagent.** Deep agent with CoStar MCP tools, records subagent, plan trace written to `plan_steps`.
- [ ] **P2-7 Aerial subagent.** Vexcel image → entrances and stopping point.
- [ ] **P2-8 Interior subagent.** Scan → graph, cached in `graphs`; demo building checked by hand. *Done when* the agent produces a real route visible live in Person 1's view (sync point Saturday 3 PM).
- [ ] **P2-9 Position engine.** Telemetry endpoint feeding the engine; writes `positions` and `cues`; off-route detection; tag snapping. *Done when* the mock wearable moves the dot and produces cues (sync point Saturday 7 PM).
- [ ] **P2-10 Re-plan and notes.** Events endpoint; `elevator_out` triggers a reroute; crew notes stored with embeddings and retrieved on the next call to that building.
- [ ] **P2-11 Briefing and questions.** 10-second spoken briefing text on each route; `POST /ask` answers from building data and notes.
- [ ] **P2-12 Write-up.** README (setup, architecture, how the agent works) and the technical half of the Devpost. Photon messaging only if time allows.

## How to work with Person 2

- Before starting a ticket, restate what "done" means and list the files you will touch. All must be in `server/`, `supabase/` or `fixtures/`.
- Write the test first for the router and position engine.
- After each change, run `uv run pytest` and `uv run ruff check .`.
- Prefer simple, readable code over clever code; Person 2 must be able to explain it to judges.
- When a step needs a decision only Person 2 or the team can make (which building, changing a contract, cutting a feature), stop and ask.
- Feature freeze is Sunday 3 AM. Submission deadline is Sunday 8:30 AM; judging runs 9:30 AM–2 PM. After 3 AM, only fix bugs.
