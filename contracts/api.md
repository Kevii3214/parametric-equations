# HTTP API (Person 2's server)

Base URL: `http://localhost:8000` locally, the Render/Railway URL when deployed. JSON in, JSON out.

| Method and path | Body | Response |
| --- | --- | --- |
| `POST /incidents` | `{ "note": str }` | `{ "incident_id": uuid }`. The agent starts in the background; watch progress in Supabase |
| `POST /incidents/{id}/telemetry` | Telemetry, see `telemetry.schema.json` | `{ "ok": true }` |
| `POST /incidents/{id}/events` | `{ "type": "elevator_out" \| "obstacle" \| "note" \| "arrived", "text": str \| null }` | `{ "ok": true }` |
| `POST /ask` | `{ "incident_id": uuid, "question": str }` | `{ "answer": str }` |
| `GET /health` | none | `{ "ok": true }` |

The telemetry endpoint is also called by the hardware team's Raspberry Pi bridge script.

## Cue values (server → wearable and phone)

`LEFT`, `RIGHT`, `STRAIGHT`, `UTURN`, `FLOOR_UP`, `FLOOR_DOWN`, `ARRIVE`, `OFF_ROUTE`

## Route step cues

Each entry in `routes.steps` has a `cue`:

- A step that changes floor (elevator or stairs): `FLOOR_UP` or `FLOOR_DOWN`.
- The last step: `ARRIVE`.
- Any other step: what to do **at the end of that step** to continue onto the next one (the heading change between the two edges). About ±45° or more is `LEFT`/`RIGHT`, about 180° is `UTURN`, otherwise `STRAIGHT`.
- A step's `floor` is the floor the paramedic is on when the step ends.

## Supabase tables Person 1 reads live

`incidents`, `plan_steps`, `routes`, `positions`, `cues` (Realtime on). Columns are in `supabase/migrations/0001_init.sql`.

- `incidents.status`: `planning` | `routing` | `en_route` | `arrived`
- `plan_steps.kind`: `plan` | `subagent` | `tool_call` | `tool_result` | `replan` | `final`
- Person 1 uses the Supabase **anon** key (read only). The service-role key never leaves the server.

## Fly-through tour (`routes.tour`)

Each `routes` row can carry a `tour` (jsonb, added by `supabase/migrations/0002_route_tour.sql`; it is `null` or missing
for a building with no scan data). It is built by code from the route, never by the model, and a re-plan (new
`routes.version`) gets a new tour. The exact shape is `contracts/tour.schema.json`; samples are in
`fixtures/buildings/<id>/tour_sample.json`.

- `keyframes` are the stops, in order. `t_ms` is when the viewer should arrive, `dwell_ms` how long to stay.
- `kind: "scanned"` stops have a `model_id` and a `sweep_id`: fly the Matterport viewer to that sweep, facing
  `bearing_deg` (compass: 0 = +y of the scan's plan, 90 = +x, clockwise). `transition` is `fly` (a move the viewer can
  make), `fade` (a cut: a change of level, or entering the scan from a gap) or `none`.
- `kind: "gap"` stops are not covered by any scan (for example the street, lobby and elevator ride). Their position is
  in the plan frame (`frame: "plan"`), with no sweep: show the 3D map or aerial view for the `segments` marked `gap`.
- `waypoint: false` stops are in-between sweeps on the way between two route stops.
- `caption` and `cue` are the instruction to show at that stop.
- `models` has each scan's opening camera view (`bearing_deg`): use it once to check the viewer's compass against
  the plan's before trusting the other bearings.
