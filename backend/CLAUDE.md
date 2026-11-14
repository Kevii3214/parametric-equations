# CLAUDE.md — Beeline backend (Person 2)

You are helping **Person 2**, who owns the server, the AI agent and the data for **Beeline**, a HackPrinceton Fall 2026 project (the web app is called **Pairatech**). Person 2 is new to this stack: explain what you are doing in plain words, keep changes small, and stop to ask when something is unclear.

**Status (2026-11-14):** every ticket P2-0 to P2-12 is built, merged and deployed, plus extras listed under "What exists". 315 tests pass. Read "Where things stand" and "Hard-won lessons" before doing anything.

## What Beeline is

Beeline gets a paramedic from the ambulance to the patient's door inside an unfamiliar building as fast as possible.

1. A dispatcher types a call note, e.g. "65M chest pain, Suite 1800, 1415 Louisiana St, Houston, patient is in the phone room".
2. An AI agent combines three data layers: **CoStar** building data (floors, tenants, elevators, parking), **Vexcel** aerial imagery (entrances, ambulance stop) and a **Matterport** 3D scan (corridors, doors, stairs, real distances).
3. A deterministic router finds the fastest stretcher-safe path from the entrance to the patient.
4. A wearable on the paramedic's forearm (Arduino + sensors, via a Raspberry Pi) sends steps, heading, air pressure, buttons and RFID scans. The server tracks progress along the route and writes turn cues ("LEFT in 6 m").
5. If the paramedic goes off route or reports "elevator out", the system re-plans.
6. The web app plays an automatic 3D fly-through of the route inside the Matterport scan (the `tour`, see below).

**Prize targets:** CoStar "Inside and Out" (30% data use, 30% agentic depth, 25% usefulness, 15% demo), LangChain deepagents, Amazon, Gemini API, Healthcare, hardware.

## Golden rules

1. **The router picks the path, never the LLM.** Gemini parses text, plans tool calls, reads pictures and writes briefings. Path choice is always NetworkX A* over the graph. `choose_route` accepts only node ids plus a briefing and recomputes the steps itself. Do not break this.
2. **Stay in your folders.** Person 2 owns `backend/`, `supabase/` and `fixtures/`. Person 1 (Rex Tran, GitHub rexthanh) owns `frontend/`; the hardware team owns `firmware/`. Do not edit another person's folder unless Person 2 explicitly asks for that specific change (then do a minimal PR and say so).
3. **`contracts/` is shared.** Changes need Person 1's thumbs-up. Additive changes so far: `routes.tour` (migration 0002) and `contracts/tour.schema.json`.
4. **Secrets live in `backend/.env`** (git-ignored). `.env.example` is committed with empty values (only `USE_SNAPSHOT`, `STRIDE_M`, `WEB_ORIGIN` have defaults). Never print or log a key. Before every commit, scan changed files for the values in `.env`. The user once pasted real keys into `.env.example`: always check it.
5. **Synthetic data only.** No real patient information anywhere. Test call notes start with "TEST synthetic".
6. **The demo must survive bad Wi-Fi.** Everything for the demo buildings also works from `fixtures/` with no external calls.

## Where things stand

- **Repo:** github.com/Princeton-3-1/parametric-equations (public, an organization repo). Branches `p2/<number>-<slug>`, one PR per piece, merged with a merge commit. Person 1 uses `rex/*` branches.
- **Live API:** https://beeline-api-cbjp.onrender.com (Render, free tier: sleeps after ~15 min idle, 30-60 s to wake; Root Directory `backend`; branch `main`; check **Auto-Deploy is on** and the repo link is connected after any repo move, or merges silently do not deploy). **Live site:** https://pairatech.vercel.app (Person 1). The Vercel project is **`rexthanh/pairatech`** in Rex's team, not Person 2's account: Person 2 cannot read or set its env vars from this machine. The site needs `VITE_MATTERPORT_SDK_KEY` (same value as `MATTERPORT_SDK_KEY`) set there and a redeploy, and the SDK key's allowed-domains list (managed by the CoStar/Matterport sponsors, from `/costar-keys`) must include `pairatech.vercel.app` and `localhost:5173`; otherwise the player shows "SDK key not allowed on <host>" and falls back to a basic embed.
- **Render environment variables** must mirror `.env`: `SUPABASE_URL` (plain project address, no `/rest/v1`; the code also tolerates it), `SUPABASE_SERVICE_ROLE_KEY`, `GOOGLE_API_KEY`, `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL`, `WEB_ORIGIN`(+`WEB_ORIGIN_REGEX`), plus Matterport/Vexcel keys if running tools there.
- **Gemini models** (checked 2026-11-14; quotas and availability change daily, re-probe with a tiny `generateContent` call before trusting a name): `GEMINI_MODEL=gemini-3-flash-preview`, `GEMINI_FALLBACK_MODEL=gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-3.1-flash-lite`. `gemini-3.5-flash`, `gemini-3.6-flash` and `gemini-4-hydrogen` were rate-limited or too slow. Later the same day (17:00) the main model, `gemini-flash-lite-latest` and `gemini-3.5-flash-lite` were out of quota (429) while `gemini-3.1-flash-lite` and `gemini-3.5-flash` answered, and runs ended `Agent stopped: GoogleAPIError` (503 high demand, 504 deadline). Local `.env` fallback list is now `gemini-flash-lite-latest,gemini-3.5-flash-lite,gemini-3.1-flash-lite,gemini-3.5-flash`; Render must have the same list (put working models first). The real error text is in `plan_steps.detail` of the `final` row. A full agent run takes ~15-30 s with the fast models; the first call after an idle Render sleep is slower.
- **Open items:** (1) The Matterport fly-through works and is merged (PR #25, 2026-11-14, watched working by Person 2 on the preview). Not checked: that Render redeployed `main` after that merge (compare its last deploy with `fcfc106`), so live-generated tours may still have the old pacing. (2) Entrance and stairs positions for Rabinowitz Hall are placed from the scan's opening picture (a few metres off); the real doors and stairs should be checked by walking the building. (3) Licensed data (CoStar, Vexcel, Matterport) is in the public repo: confirm the hackathon terms. (4) If Gemini has a bad moment a call can end without a route; the frontend shows "The agent finished without a route" and offers the demo route.

## What exists

```
contracts/          shared schemas: api.md, telemetry/building_graph/route/tour .schema.json
fixtures/
  building_graph.json, route.json, plan_steps.json, incident.json   hand-typed ticket-0 samples
  buildings/<id>/   record.json, interior.json, sweeps.json, graph.json, aerial*.jpg, tour_sample.json, GRAPH_NOTES.md
  buildings/index.json   address/name aliases -> building id (how the agent finds a building)
supabase/migrations/    0001_init.sql (9 tables, RLS, Realtime), 0002_route_tour.sql (routes.tour)
backend/
  app/main.py config.py db.py models.py intake.py briefing.py notes.py tour.py
  app/api/        incidents.py telemetry.py events.py ask.py
  app/agent/      agent.py subagents.py tools.py trace.py replan.py vision_hints.py
  app/graph/      schema.py router.py from_scan.py
  app/position/   engine.py simulate.py
  app/providers/  base.py (BuildingProvider) snapshot.py (reads fixtures)
  tools/          mock_wearable.py  add_building.py
  notebooks/      costar_pull.ipynb, make_*.py (regenerate fixtures), rank_buildings.py
  tests/          315 tests; fakes.py is an in-memory Supabase stand-in
  data/ docs/     git-ignored: CoStar kit and Vexcel docs (not committed)
```

**Endpoints:** `GET /health`, `POST /incidents` (parse the note with Gemini, save the row, start the agent in the background), `POST /incidents/{id}/telemetry`, `POST /incidents/{id}/events` (elevator_out, obstacle, note, arrived; elevator_out triggers a re-plan), `POST /ask`.

**The agent** (`create_deep_agent`, Gemini with fallbacks): `make_plan` → `records` subagent (resolve_building, get_building_record, find_suite) → `search_notes`, `list_entrances`, `find_destination_nodes`, `plan_route` (every entrance, in parallel), `choose_route` (saves the router's steps, a spoken briefing and the tour), `save_note`. Every plan, subagent call, tool call and result goes to `plan_steps` (sort by `seq`). Capped at 25 model calls; model fallback applies to the subagent too; a failure after a route was saved is reported as "Route saved". Built-in deepagents `execute`/file tools are harmless (no sandbox, in-memory files) and a test locks that in.

**Position engine** (`app/position/engine.py`, pure): distance from steps × `STRIDE_M`; one cue within 6 m of a turn; turn confirmed by a ≥60° heading change; off route for a wrong-way turn or >5 m past a turn; floor change from a ≥35 Pa pressure change or the confirm button at a lift; RFID tag snaps the position and resets the heading baseline; button 2 = elevator_out; one `positions` row per second; the last step counts as done within 1 m (strides vary).

**Tour** (`app/tour.py`, pure): turns a route into stops for the 3D viewer: Matterport `sweep_id` to fly to, compass `bearing_deg` (0 = +y, clockwise), `t_ms`, caption, cue, `transition` (fly / fade / none) and `segments` marking `scanned` vs `gap` (no scan covers the street, lobby, elevator ride: the frontend shows the map there). Hops follow the scan's sweep `neighbors` links. Saved in `routes.tour` by `choose_route`; if the column is missing or the tour fails, the route is saved without it. Usage notes are at the end of `contracts/api.md`. Pacing: map/gap stretches play at 6× (`DEFAULT_SPEED_UP`), hops inside a scan at `SCAN_SPEED_UP = 2.0` (about 2.6 m/s, so it looks like walking); `MIN_HOP_MS = 700`. The in-scan chain of sweeps is chosen with squared hop length as the cost (`_sweep_path`), which prefers many short hops over a few long jumps (Rabinowitz 15 stops, Williams 13, Louisiana 11). Sweeps are only about 5 m apart, so that is the density limit. A test locks both in.

**Fly-through player** (`frontend/src/components/tour/TourPlayer.tsx`, `frontend/src/lib/tour.ts`; Person 1's folder, changed at Person 2's request in PR #25): uses `@matterport/sdk` (`setupSdk` on one https iframe, key from `VITE_MATTERPORT_SDK_KEY`, baked in at build time; `frontend/.env.local` is git-ignored). It matches each tour sweep to the viewer's own sweeps (`Sweep.data`: same id, else nearest position within 1.5 m), faces the next stop with `yawToward` (y-up frame, yaw 0 looks down -z, positive yaw turns left; the model API's z-up position maps to `{x, y: z, z: -y}`), and runs `Sweep.moveTo` **one at a time**, skipping ahead if late. The progress bar is a slider: click, drag or arrow keys; the clock pauses while dragging and the viewer cuts with a 400 ms fade. For Louisiana and Williams the tour **starts inside the scan** (`startInScan` cuts the unscanned street/lobby/lift stops); `Medic.tsx` lists those steps in a separate "Before the scan" card outside the 3D box, because nothing may cover the scan. No scan covers the street, lobby or lift of either Houston building (scans are floor 18 and floor 56 only); never stand in a scan of another floor.

**Buildings** (all work end to end on the live server):

| id | Building | What is measured | What is estimated |
| --- | --- | --- | --- |
| `233928` | 1415 Louisiana, Houston (CoStar) | Regus Suite 1800 on floor 18 (door positions from the scan) | street, lobby, elevators, floor corridor, all lift/stair times |
| `233903` | Williams Tower, Houston (CoStar) | the whole floor-56 suite: every doorway and open gap | street, lobby, elevators, corridor outside the suite |
| `jrr` | Rabinowitz Hall, Princeton (not in CoStar) | the two scanned levels, all 65 walkable camera positions | entrance and glass staircase placed from the scan's opening picture; stairs time; no elevator exists in the data |
| `thea-2br` | THEA at Metropolis 2BR unit (kit scan) | whole unit, 15 rooms, auto-generated by `add_building.py` | nothing hand-checked |

Sample calls (same as the website's buttons): Louisiana `65M chest pain, Suite 1800, 1415 Louisiana St, Houston, patient is in the phone room` (garage entrance, ~109 s); Williams `58F fall with head injury, Suite 5600, Williams Tower, 2800 Post Oak Blvd, Houston, patient is in the conference room` (~106 s); Rabinowitz `20M seizure, Rabinowitz Hall, Princeton University, patient is in the classroom on the upper level` (~51 s). Only Suite 1800 (Louisiana) has map nodes; other suites cannot be routed to.

**Onboarding a new building:** `python -m uv run python tools/add_building.py --model <Matterport id> --id <slug> --name "..." [--entrance-px N --stairs-px N] [--vision]`. It builds the map with `app/graph/from_scan.py` (camera positions as walkable waypoints, a destination per room named by the scan's room types, entrance cascade: exterior doorway → hint → scan start; stairs from a hint or a sweep taken between levels, otherwise a loud warning that levels are not connected) and prints everything it inferred. `--vision` asks Gemini for pixel columns of the entrance/stairs in the opening picture: it finds stairs fairly well, often misses entrances, never invents. Maps are made ahead of time and checked by a person, never at dispatch time.

## Stack

Python 3.11, `uv`, FastAPI + Pydantic v2, Supabase (Postgres, Realtime, pgvector), LangChain `deepagents` on LangGraph, Gemini via `langchain-google-genai`, NetworkX, shapely, pytest, ruff. **CoStar is a data extract in `backend/data/costar-hackathon-kit/`, not an MCP server** (never invent CoStar endpoints). Matterport Model API (GraphQL, Basic auth) and Vexcel API 2.0 (REST, `X-API-KEY`) are called only from tools/notebooks; the running server reads `fixtures/` through `SnapshotProvider`.

## Environment variables (`backend/.env.example`)

```
SUPABASE_URL=  SUPABASE_SERVICE_ROLE_KEY=  GOOGLE_API_KEY=  GEMINI_MODEL=  GEMINI_FALLBACK_MODEL=  GEMINI_EMBEDDING_MODEL=
MATTERPORT_API_KEY=  MATTERPORT_API_TOKEN=  MATTERPORT_SDK_KEY=  MATTERPORT_GRAPHQL_URL=  VEXCEL_API_KEY=  COSTAR_DATA_DIR=
DEMO_BUILDING_ID=  USE_SNAPSHOT=false  STRIDE_M=0.7  WEB_ORIGIN=http://localhost:5173  WEB_ORIGIN_REGEX=
```
`MATTERPORT_API_KEY` is the token id and `MATTERPORT_API_TOKEN` the secret (Basic auth to `https://api.matterport.com/api/models/graph`). `MATTERPORT_GRAPHQL_URL` is only a GraphiQL console link, not the endpoint. `GEMINI_FALLBACK_MODEL` is a comma-separated list.

## Commands (run from `backend/`)

`uv` is not on PATH on this machine: use `python -m uv ...`.

```
python -m uv run pytest -q                      # 315 tests
python -m uv run ruff format app tests tools    # NOT "ruff format ." : it reformats code blocks inside .md files
python -m uv run ruff check .
python -m uv run uvicorn app.main:app --port 8000
python -m uv run python tools/mock_wearable.py <incident_id> --base-url https://beeline-api-cbjp.onrender.com
python -m uv run python notebooks/make_tours.py      # regenerate fixtures/buildings/*/tour_sample.json after router/graph changes (a test fails if stale)
```

## Contracts (the only connection between the halves)

HTTP: see `contracts/api.md` (endpoints, cue values, how step cues are chosen, the tour). Telemetry: `{ t, steps, heading, pressure, btn, tag }` about 5 per second; use heading **changes**, never absolute values; `btn` 0 none / 1 confirm / 2 elevator out. Cue values: `LEFT RIGHT STRAIGHT UTURN FLOOR_UP FLOOR_DOWN ARRIVE OFF_ROUTE`. A step's cue is the action at the **end** of that step, except a floor-changing step gets FLOOR_UP/DOWN and the last step gets ARRIVE.

Supabase tables Person 1 reads live (Realtime on, anon key read-only): `incidents`, `plan_steps` (kinds plan, subagent, tool_call, tool_result, replan, final), `routes` (now with `tour` jsonb), `positions`, `cues`. Private tables: `buildings`, `graphs`, `notes` (embeddings), `closures`. Row-level security is on for all nine; the anon key can only read the five shared ones. Building graph shape: `contracts/building_graph.schema.json`; node kinds entrance/corridor/door/elevator/stairs/aed; edge `seconds` must be ≥ meters/1.3 (keeps A* optimal; a test enforces it).

## Hard-won lessons

- **Verify on the live URL after every merge.** Render once stayed 5+ hours behind `main`; only one of three buildings worked. Test every building, not one. Compare merge times with the last deploy.
- **Clean up after live tests**, including the agent's own writes: it calls `save_note`, which persists in `notes` and is fed into later briefings. Delete test notes, incidents, plan_steps, routes, cues, positions, closures. Do not delete rows you did not create (the database also holds other people's test incidents).
- **Do not trust scan names.** A Matterport model called "Lobby" was a tenant's reception. Fetch the thumbnail (`model{image{url snapshotLocation{position rotation}}}`) and look. The thumbnail pose gives the scan start and facing (forward = quaternion applied to −Z; bearing 55.5° for Rabinowitz).
- **Matterport quirks:** opening types include `window` (not a way through); the scan may mark no exterior doorway; `locations{neighbors}` means mutual visibility, not walkability; stacked sweeps on two levels are NOT stairs (8 of them in an atrium); only a sweep at an in-between height hints at stairs; rooms have `floor` and `holes` (subtract holes or an atrium void looks walkable); `geolocation` is `{lat long}`; floors can be labelled from 2.
- **CoStar floor names are unreliable** (a 43-story tower lists floors up to 67): derive a floor guess from the suite number and say it is a guess. CoStar units have no scans; scans exist only for some floor plans.
- **Gemini:** set short timeouts and `max_retries=0`, use a model list; probe candidate models with a tiny call; 503 "high demand" and 429 quota happen. Subagents do not inherit the main agent's middleware (fallback, call limit): pass it to the `SubAgent` too. Tell subagents to use only their own tools (they waste steps on `glob`/`grep` when a lookup fails).
- **Vercel CLI:** never run `vercel link --yes` here: it created an empty `frontend` project in Person 2's own account (still there unless deleted) instead of finding Rex's `pairatech`. Preview deployments are behind Vercel auth (curl gets 302). To check a deployed build, grep the served JS for a known string, including lazy chunks (the main `index-*.js` does not hold the Medic page).
- **Matterport SDK:** `@matterport/sdk` in `package.json` was not installed until `npm install` was run (the player failed silently into basic mode). A `moveTo` started during another move is refused, so queue them. The key works only on allowed domains.
- **Windows/shell:** the shell has `noclobber`, so `> file` on an existing file fails and the command never runs, leaving stale output: use `>|` or a new name. `grep` hides output containing stray bytes ("Binary file matches"): read files in Python with `errors="replace"`. Do not kill processes with broad filters (once killed unrelated `bash.exe`): stop only the port-8000 process. f-strings cannot reuse the outer quote on Python 3.11.
- **Vite bakes env vars at build time:** the website was stuck in demo mode until `VITE_SUPABASE_*` were set and Vercel redeployed. Ad-blocking extensions block `onrender.com` (`ERR_BLOCKED_BY_CLIENT`); proxying the API through Vercel avoids it.
- **Test the whole route with the simulator:** `simulate()` + `PositionEngine` found two real engine bugs that unit tests missed.
- Vision, scan data and Gemini output are **inferences**: always label them as such in the briefing/notes, never present a guess as fact. No fabricated AED or elevator nodes.

## How to work with Person 2

- Before starting a piece of work, restate what "done" means and list the files you will touch. Write the test first (router, position engine, tour, builder). After each change run `pytest` and `ruff check`.
- Prefer simple, readable code: Person 2 must be able to explain it to judges.
- Branch `p2/<number>-<slug>`, commit with the `Co-Authored-By` trailer, push, open a PR, merge (Person 2 has been saying "push and merge"); then `git pull` on `main`. Ask before pushing if Person 2 has not already agreed to merge.
- Stop and ask when a decision is only Person 2's or the team's (which building, a contract change, cutting a feature, publishing licensed data).
- Report outcomes faithfully: say what was verified live, what was only tested locally, and what was not tested. Correct earlier mistakes openly.
- Feature freeze is Sunday 3 AM; submission 8:30 AM; judging 9:30 AM-2 PM. After 3 AM only fix bugs.
