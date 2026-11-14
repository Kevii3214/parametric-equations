# Wearable (Raspberry Pi) protocol

For the hardware team. The Pi talks to the server over plain HTTP and holds **no Supabase keys**. The server turns the
Pi's events into positions and cues on the web app, and sends cue **commands** back in the response.

**Status: proposed.** Built on the server from a summary of `wearable.py`, not from the file. If your field names or
command strings differ, tell Person 2: only `backend/app/device/translate.py` changes.

Base URL: `https://beeline-api-cbjp.onrender.com` (free tier: sleeps after ~15 min idle, 30-60 s to wake. Call
`GET /health` first and retry).

## 1. Link the device to an incident (once per call)

`PUT /api/device/{device_id}/link` with `{ "incident_id": "<uuid>" }` → `{ "ok": true, "incident_id": "..." }`.
404 if the incident does not exist. Linking again re-points the device and resets its counters. The link is saved on the
server, so it survives a server restart.

## 2. Send events, get commands

`POST /api/device/{device_id}/events` every 200-500 ms. An empty `events` list is fine.

```json
{ "t": 182340, "events": [
  { "kind": "steps",  "n": 3 },
  { "kind": "turn",   "dir": "L" },
  { "kind": "floor",  "dir": "up" },
  { "kind": "button", "n": 1 },
  { "kind": "tag",    "id": "TAG-SUITE-1800" },
  { "kind": "fall" },
  { "kind": "air",    "level": "warn", "ppm": 900 }
] }
```

Response: `{ "commands": ["CUE L"], "incident_id": "...", "status": "tracking" }`. `status` is `no_route` until the
agent has saved a route (commands are empty then). 404 if the device is not linked, 422 for a malformed event.

| Event | Fields | Meaning |
| --- | --- | --- |
| `steps` | `n` ≥ 0 | New steps since the last post (not a running total) |
| `turn` | `dir` `L`\|`R`, optional `deg` (default 90) | A turn the IMU detected |
| `floor` | `dir` `up`\|`down` | One floor changed (barometer). Send once per floor |
| `button` | `n` 1 or 2 | 1 = confirm (start, checkpoint, lift ride), 2 = elevator out (server re-plans) |
| `tag` | `id` | RFID tag read. Snaps the position to that spot |
| `fall`, `air` | `level`, `ppm` (air) | Logged by the server. Not shown on the web app yet |

Heading and floor start at 0 when the Pi boots. No calibration is needed: the server only looks at changes.

## 3. Commands the server sends back

| Command | Meaning | Cue |
| --- | --- | --- |
| `CUE L` / `CUE R` | Turn left / right (sent once, about 6 m before the turn) | LEFT / RIGHT |
| `CUE S` | Go straight | STRAIGHT |
| `CUE U` | U-turn | UTURN |
| `CUE UP` / `CUE DN` | Take the lift or stairs up / down | FLOOR_UP / FLOOR_DOWN |
| `CUE A` | Arrived | ARRIVE |
| `CUE X` | Off route | OFF_ROUTE |

Each command is sent **once**, in the response to the batch that triggered it: handle every response, and do not drop a
reply. `CUE UP` / `CUE DN` need a buzzer/LED pattern on the wearable (none exists yet).

## Try it without the Pi

```bash
cd backend
python -m uv run python tools/mock_device.py <incident_id> --base-url https://beeline-api-cbjp.onrender.com
```

It links `pi-01`, walks the incident's route as events and prints each command it receives.

## Checklist for the first run with the real Pi

1. `GET /health` until it answers. 2. Dispatcher creates an incident; wait for `/medic` to show a route.
3. Link the device (step 1). 4. Walk 10 steps: the dot on `/medic` moves. 5. Turn where the route turns: `CUE L`/`CUE R`
arrives before the corner. 6. Take the lift: `floor` event, then the next step starts. 7. Press button 2: a re-plan
appears on `/medic`. 8. Walk the wrong way: `CUE X`. 9. Reach the door: `CUE A`, incident `arrived`.
10. Compare the Pi's step count with real distance; tell Person 2 to change `STRIDE_M` if the dot drifts.
