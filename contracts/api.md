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
