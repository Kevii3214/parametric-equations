# Wearable (Raspberry Pi) protocol

The device side is defined by the hardware team in `Hardware/BACKEND_BRIEF.md` and `Hardware/wearable.py`; this file is
what the **server** does with it. The Pi only makes outbound HTTPS calls and holds **no Supabase keys**. Everything that
depends on event or command names lives in `backend/app/device/translate.py`.

Base URL: `https://beeline-api-cbjp.onrender.com` (free tier: sleeps after ~15 min idle, 30-60 s to wake; the Pi
retries, so call `GET /health` before a demo).

## 1. Bind the device to an incident

- `POST /incidents/{id}/device` with `{ "device_id": "wearable-1" }`, or `PUT /api/device/{device_id}/link` with
  `{ "incident_id": "<uuid>" }`. 404 if the incident does not exist. The link is saved, so it survives a server restart.
- **Zero clicks:** if the server has `DEFAULT_DEVICE_ID=wearable-1`, that device follows the newest incident that is not
  `arrived`, `closed` or `cancelled` (checked at most every 5 s). A manual bind stays until the server restarts.
- Binding queues **`RESET`** for the device (once), so its steps, heading and floor start at zero at the route start.

## 2. Events in, commands out

`POST /api/device/{device_id}/events` with `{ "events": [ { "t": "<type>", "ts": <epoch ms>, ... } ] }`.
The answer is **always 200** with `{ "commands": [...], "incident_id": ..., "status": "unbound" | "no_route" | "tracking" }`.
Unknown event types, a bad body or an internal problem are logged and answered with an empty list, never an error: the Pi
re-sends what it did not get a 2xx for. A request without a valid `X-Device-Key` (when `DEVICE_KEY` is set) is only logged.

- **Idempotent on `(device_id, ts, t)`:** a re-sent event is ignored. Recognised again after a server restart, from
  `device_events`.
- Events are processed in `ts` order. Commands from the engine and any queued ones come back in this response.

| `t` | Used for |
| --- | --- |
| `state` | `steps` (running count) and `fl` (relative floor), twice a second. Not stored |
| `step` | `n` running step count. Not stored |
| `turn` | `dir` `L`/`R`. Counts as exactly 90° (180° if `abs(deg)` ≥ 120): the Pi's `deg` reads low, `dir` is reliable. `hd` is **not** used |
| `floor` | `fl` relative floor. Floors become a 45 Pa pressure change for the position engine |
| `btn` | `ev` `confirm` (1) or `elevator_out` (2, the server re-plans once per route) |
| `hello` | Stored; `fw` and the sensor flags go on the `devices` row. Zeroes the server's counters, like RESET |
| `ack` | `cmd: RESET` zeroes the server's counters (floors already climbed are kept) |
| `fall`, `fall_cancel`, `air` | Stored in `device_events`, and open/clear a row in `alerts` (see `api.md`) |
| `sensor`, `photo`, `pong`, `error` | Stored in `device_events` (`kind` = `t`, `data` = the rest) |

Distance is `steps × STRIDE_M` on the server (the Pi's `d` is not used), so a stride calibration changes only `STRIDE_M`.
The server follows **changes** in steps, heading and floor, never absolute values, so no heading or floor offset is
needed; `RESET` at bind is what anchors the start.

## 3. Commands the server sends back

| Cue | Commands |
| --- | --- |
| LEFT / RIGHT / STRAIGHT / UTURN | `CUE L` / `CUE R` / `CUE S` / `CUE U` |
| ARRIVE | `ARRIVED`, `SCAN OFF` |
| OFF_ROUTE | `WRONG` |
| FLOOR_UP / FLOOR_DOWN | `FLOOR U` / `FLOOR D` (added to `wearable.py`: rising / falling buzzer pattern). An older firmware answers `error`, which is harmless |

Every cue is followed by `TXT <first 16 characters of the cue text>` (harmless without a display). Each command is sent
**once**. A bind sends `RESET` first. `FLOOR U` / `FLOOR D` were added to `Hardware/wearable.py` by Person 2 (the hardware team is no longer
available): copy the new file to the Pi.

## 4. Photos: reading door signs (**disabled in the backend for the demo**)

The demo only shows route detection, so the server ignores camera pictures (the endpoint still answers 200) and never sends
`SCAN ON`. The code is commented out at two places in `backend/app/api/device.py`; the description below is what happens
when they are switched back on.

`POST /api/device/{id}/photo` (multipart: `image` JPEG, `ts`, `n`, `reason`) answers `{ "commands": [...] }` at once; the
sign is read in the background (Gemini reads the text, code decides). If the text names a point **on the current route**
("SUITE 1800" matches "Regus Suite 1800 entrance", the shortest matching label wins, a tie matches nothing) the position
snaps there, like an RFID tag would. The picture is never stored; only the sign text and the node are saved
(`device_events`, `kind = sign`). When the destination is within 10 m the server sends `SCAN ON` (once); `SCAN OFF`
comes with `ARRIVED`.

## Try it without the Pi

```bash
cd backend
python -m uv run python tools/mock_device.py <incident_id> --base-url https://beeline-api-cbjp.onrender.com
```

It binds `wearable-1`, walks the incident's route as real-protocol events and prints each command it receives.

## Checklist for the first run with the real Pi

1. `GET /health` until it answers. 2. Create an incident; wait for `/medic` to show a route. 3. Bind the device (step 1);
the Pi's next request returns `RESET`. 4. Walk 10 steps: the dot on `/medic` moves. 5. Turn where the route turns:
`CUE L`/`CUE R` arrives before the corner. 6. Take the lift: a `floor` event, then the next step starts. 7. Press button 2:
a re-plan appears on `/medic`. 8. Walk the wrong way: `WRONG`. 9. Reach the door: `ARRIVED`, incident `arrived`.
10. Compare the step count with real distance; change `STRIDE_M` (server) and the Pi's stride together if the dot drifts.
