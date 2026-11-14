# contracts/

The only connection between the server (Person 2) and the web app (Person 1), plus the wearable bridge.

**Frozen after ticket 0.** To change anything here, get a thumbs-up from Person 1 first.

| File | What it defines |
| --- | --- |
| `api.md` | The five HTTP endpoints, cue values, and how step cues are computed |
| `telemetry.schema.json` | Wearable bridge → server sample (about 5 per second) |
| `building_graph.schema.json` | The building graph the router runs on |
| `route.schema.json` | `routes.steps`: the turn-by-turn list |
| `tour.schema.json` | `routes.tour`: the fly-through the 3D viewer follows (see the end of `api.md`) |
| `../supabase/migrations/0001_init.sql` | Table definitions. The five shared tables (Realtime on) are the contract; the private tables are Person 2's only |

Sample data in these shapes lives in `../fixtures/`.
