# Brief: connecting the Beeline wearable to the backend

You are working in the Beeline repo for the backend owner (Person 2: `backend/`, `supabase/`, `fixtures/`). The hardware team has built a physical wearable. Your job is to add the backend pieces so that the wearable:
- **sends** sensor events that drive the existing position and route engine
- **receives** the existing cue stream as commands it can act on

Follow the house rules:
- Synthetic data only.
- Never commit keys. The service-role key stays on the server.
- Use branches named `p2/<n>-<slug>`, with one PR per task.
- Changes under `contracts/` must be additive and need Person 1's thumbs-up.

---

## 1. What the hardware is

A paramedic wears a chest-strap unit. It is a **Raspberry Pi 4 with a Grove Base HAT**, running one Python script, `Hardware/wearable.py` (in this repo, next to this brief). The script reads the sensors, talks to the server over HTTPS and plays the cues. There is no separate bridge and no Arduino.

| Part | What it gives the system |
|---|---|
| MPU-6050 IMU (GY-521) | Step detection (0.70 m stride, configurable), heading from the gyro, turn detection (≥60°), fall detection |
| BMP280 barometer | Relative altitude, converted to a relative floor number (3.5 m per floor) |
| Grove air-quality sensor | Raw 0–4095 reading plus a warn flag (smoke/fumes) |
| USB webcam (chest, facing forward) | 640×480 JPEG photos, meant for reading door and suite signs on the server |
| Button 1 "confirm" | Confirm or acknowledge. It also cancels a fall alert within 15 s, and takes a photo. |
| Button 2 "elevator out" | The medic signals they have stepped out of the lift |
| Buzzer | Turn cues: 1 beep left, 2 right, 3 U-turn. Also arrival, wrong-way, floor-change, air and fall patterns. |
| Status LED | Solid = online. Slow blink = turn cue. Fast blink = wrong way or fall. Short flash every 2 s = no server. |
| (optional, currently off) LCD, vibration motor | The current build has no screen. **The medic's phone (`/medic`) is the visual display.** |

**There is no RFID reader in the current hardware.** The demo graph's `TAG-*` ids have nothing to read them yet. Confirm with the hardware team whether one is coming. Until then, the "position fix" anchors are button presses and camera photos of signs (see Task 6).

**Important sensor caveats:**
- **Heading is relative, not compass.** It is 0° wherever the unit was facing at boot or at the last `RESET`.
- **The floor number is relative.** It is 0 at boot or at the last `RESET`.
- **Distance is dead reckoning:** step count × 0.70 m.

The backend must anchor all three to the route start (Task 3).

### Hardware status (updated 2026-11-15)
- All parts are verified working on the real device:
  - IMU (an MPU-6500)
  - barometer (a DPS310, not a BMP280; already handled in firmware)
  - air sensor, webcam, buzzer, LED and buttons
  - power bank
- The firmware runs as an auto-start service and survives sensor dropouts. On reconnect it sends `sensor`.
- **Still being tuned on the hardware side (doesn't change any message format):**
  - left/right direction is not yet confirmed
  - turn `deg` reads about 20–30% low on 90° corners, so **use `dir`, not exact `deg`**
  - stride length
  - occasional false `floor` changes from barometer drift
- **Networking:** the Pi gets internet through a phone hotspot (campus Wi-Fi blocks it), so expect higher latency and occasional brief dropouts. The firmware queues and re-sends events (see idempotency in Task 2).
- `DEVICE_ID` will be `wearable-1`.

---

## 2. The device protocol (already implemented on the wearable; do not change it without the hardware team)

The device only ever makes outbound HTTPS requests, so the server never connects to it. Downlink commands ride back in the HTTP responses.

### Uplink: events
```
POST {SERVER_URL}/api/device/{device_id}/events
Content-Type: application/json
{"events": [ {...}, {...} ]}

200 → {"commands": ["CUE L", "TXT 6M", ...]}     # may be []
```
- **Timing:** the device posts about every 0.5 s whenever it has events, and a `state` event is produced every 0.5 s, so in practice the server is polled at about 2 Hz. Urgent events (step, turn, floor, btn, fall…) trigger an immediate post.
- **Batching and retries:** a batch contains 1+ events. On a non-2xx response or a timeout (3 s), the device keeps the events and **re-sends them**, keeping at most the last 300. **Ingestion must therefore be idempotent:** de-duplicate on `(device_id, ts, t)`.
- **Timestamps:** every event has `ts`, Unix epoch in **milliseconds** from the Pi's clock.

**Event types (`t`):**

| t | Fields | Meaning |
|---|---|---|
| `hello` | `fw`, `imu`, `baro`, `air`, `lcd`, `led`, `cam` (0/1) | Boot. Shows which sensors are present. |
| `state` | `steps`, `d` (m), `hd` (deg 0–360), `fl`, `alt` (m), `p` (Pa), `air`? | Snapshot every 0.5 s |
| `step` | `n`, `d` (m total), `hd` (deg) | One footstep |
| `turn` | `dir` `"L"`/`"R"`, `deg` (signed int) | Rotation ≥60° finished |
| `floor` | `fl` (relative int), `alt` (m) | Floor change held for 2 s |
| `btn` | `id` 1/2, `ev` `"confirm"`/`"elevator_out"` | Button press |
| `air` | `v` (raw), `warn` 0/1 | Air-quality threshold crossed (either direction) |
| `fall` | – | Possible medic fall (free fall → impact → still) |
| `fall_cancel` | – | Medic pressed button 1 within 15 s ("I'm OK") |
| `sensor` | `imu` 0/1 | Motion sensor lost (0) or regained (1). While 0 there are no `step`/`turn` events. Show as a "tracking degraded" hint. |
| `photo` | `n`, `reason` (`scan`/`snap`/`button`), `bytes`, `sent`? | A photo was taken. `sent:0` means the upload failed. |
| `ack` | `cmd` | Command executed |
| `pong` | – | Reply to `PING` |
| `error` | `msg`, `cmd` | Unknown command |

### Uplink: photos
```
POST {SERVER_URL}/api/device/{device_id}/photo
multipart/form-data: image (JPEG, ~640×480, ~40 KB), ts (ms), n, reason
200 → {"commands": [...]}   (optional)
```
The timeout is 8 s and failed uploads are **not** retried.

### Downlink: commands (strings, case-insensitive)

| Command | Device does |
|---|---|
| `CUE L` / `CUE R` / `CUE S` / `CUE U` | Turn left / right / straight / U-turn: buzzer pattern + LED (S is silent) |
| `ARRIVED` | Arrival beep + LED |
| `WRONG` | Wrong-way alarm |
| `TXT <text>` | Text for the LCD (no-op on the current build; harmless) |
| `CLEAR` | Clear the display |
| `RESET` | Zero steps, heading, floor and altitude. **Send at route start.** |
| `CAL` | Re-calibrate the IMU (~2 s, the medic must hold still) |
| `SNAP` | Take one photo |
| `SCAN ON` / `SCAN OFF` | A photo every 2 s while on |
| `PING` | Replies with `pong` |

**There is no device command for `FLOOR_UP` / `FLOOR_DOWN` yet** (see Task 4).

---

## 3. The gap

The backend currently:
- creates incidents (`POST /incidents`)
- accepts telemetry samples in the format `tools/mock_wearable.py` posts
- writes cues into Supabase `cues` (`incident_id, route_version, cue, dist_m, text, created_at`), which the frontend reads over Realtime

The wearable speaks a **different, device-oriented protocol**:
- it doesn't know an `incident_id`
- it can't use Supabase Realtime
- it sends raw-ish events rather than telemetry samples

**Decision: build an adapter on the backend** (`/api/device/...`). Don't make the Pi subscribe to Supabase. This keeps keys off the device and the firmware simple, and it is additive: it doesn't change any existing contract.

---

## Tasks

### Task 1: Device registry and incident binding
- Add a `devices` table (or similar):
  - `device_id` text PK
  - `incident_id` nullable
  - `last_seen_at`
  - `fw`, plus the sensor flags from `hello`
  - `heading_offset_deg`, `floor_offset`, `last_cue_id`
- Add an endpoint to bind a device to an incident:
  - `POST /incidents/{id}/device {"device_id":"wearable-1"}`. The dispatcher or medic can call it; a button in `/medic` is a later frontend task for Person 1.
  - Also auto-bind via an env default (`DEFAULT_DEVICE_ID`) so the demo works with zero clicks: the newest active incident gets `wearable-1`.
- On bind, queue `RESET` (and optionally `CAL`) for that device.
- **Done when:** after `curl` binds `wearable-1` to an incident, a device POST is accepted and attributed to that incident.

### Task 2: `POST /api/device/{device_id}/events` (ingest + command delivery)
- Validate loosely: accept unknown `t` values and ignore them. Never 500 on a bad event; the device would retry it forever.
- De-duplicate on `(device_id, ts, t)`. Update `last_seen_at`.
- Store raw events (e.g. a `device_events` table). That makes debugging and replay easy.
- Respond within about 300 ms. **Always return `{"commands": [...]}`**, even if the device is unbound, in which case return `[]`.
- Keep a per-device command queue: in memory is fine for the demo; use a DB table if the Render instance might restart. Drain it into each response.
- **Done when:** a `curl` with a sample batch returns 200 + commands, and re-posting the same batch creates no duplicates.

### Task 3: Translate device events → the position engine's telemetry
- Map `step`, `turn`, `state` and `floor` into whatever telemetry samples the position engine consumes. Use the same internal path that `mock_wearable.py` → telemetry uses, so positions land in `positions` and the frontend's live dot moves.
- **Anchoring:**
  - When the route starts (on bind, or the first `btn id=1 confirm` after bind), record `heading_offset = route's first-segment bearing − device hd` and `floor_offset = route start floor − device fl`. Apply both to every later sample.
  - Distance from the device is `d`, steps × 0.70 m.
- Treat `btn id=2 elevator_out` as "lift exit": snap to the lift node on the current target floor.
- Treat a `floor` event as floor evidence for the router. FLOOR_UP/DOWN completion = the device floor + offset equals the target.
- **Done when:** walking the Pi in a straight line, then turning, makes the position dot on `/medic` move and turn.

### Task 4: Translate `cues` rows → device commands
- When a new `cues` row is inserted for the device's bound incident, enqueue the mapped command:
  - Either hook where the engine writes cues (simplest: same process), or subscribe server-side.
  - Track `last_cue_id` per device so each cue is sent once.

| `cues.cue` | Device command(s) |
|---|---|
| LEFT | `CUE L` |
| RIGHT | `CUE R` |
| STRAIGHT | `CUE S` |
| UTURN | `CUE U` |
| ARRIVE | `ARRIVED`, `SCAN OFF` |
| OFF_ROUTE | `WRONG` |
| FLOOR_UP / FLOOR_DOWN | `TXT FLOOR UP 18` (no-op without an LCD). Coordinate with the hardware team on adding a `FLOOR U` / `FLOOR D` buzzer command; they own `Hardware/`. |

- Also send `TXT <short text>` with each cue, built from `dist_m`/`text` and truncated to 16 chars. It costs nothing and works if the LCD gets turned on.
- Optional: when the remaining distance to the destination is under ~10 m, send `SCAN ON` so the camera starts reading door signs.
- **Done when:** the cue a frontend shows on `/medic` produces the matching beep on the wearable within about 1 s.

### Task 5: Safety events → alerts the UI can show
- `fall` (and `fall_cancel`) and `air warn=1/0` should become alert rows on the incident, e.g. a new `alerts` table (`incident_id, kind, active, created_at`) published over Realtime.
- This is an **additive contract change**: write the schema in `contracts/` and get Person 1's thumbs-up so `/medic` and `/dispatch` can show a banner.
- **Done when:** shaking the Pi hard and laying it still produces a fall alert row, and pressing button 1 within 15 s marks it cancelled.

### Task 6: `POST /api/device/{device_id}/photo` (sign reading as a position fix)
- Accept the multipart JPEG and return `{"commands": []}` quickly. Do the vision work asynchronously.
- Send the image to Gemini vision: "read any room / suite / floor sign text". If the text matches a graph node (e.g. "1800" → Suite 1800 node), use it as a position fix, the same role the `TAG-*` RFID ids were meant to play. Store the extracted text with the event.
- **Privacy:** the camera can capture real people. Don't keep the images after processing, or keep them only with an explicit short expiry, and never commit them. Log only the extracted text.
- **Done when:** a photo of a paper sign reading "SUITE 1800" snaps the position to that node.

### Task 7: A device-protocol simulator (so you can test without the Pi)
- Add `tools/mock_device.py`. It speaks *this* protocol:
  1. Posts `hello`.
  2. Walks the route using `position/simulate.py`, emitting `step` with `d`/`hd`, `turn` at corners, `state` every 0.5 s and `floor` on lift changes, with headings and floors expressed **relative to the start**, like the real device.
  3. Prints the commands it receives.
- **Done when:** `mock_device.py <incident_id>` against the Render URL drives the `/medic` dot and prints `CUE L` / `CUE R` / `ARRIVED` in the right order.

### Task 8: Operational details
- **Render cold start:** the device's request timeout is 3 s. During spin-up its requests fail and it retries (the LED shows "offline"), which is fine. Consider a keep-alive ping before demos.
- **Device auth:** there is none right now. For the demo, accept a shared secret header such as `X-Device-Key` (from env) if present, and log when it's missing. Ask the hardware team to add the header to the firmware before requiring it.
- **Logging:** log each device request in one line (device, n_events, n_commands, latency) so integration debugging is easy.

---

## Final task: integrate the real hardware (with the hardware team)

1. **Network:**
   - The Pi needs internet. Princeton eduroam doesn't work for it, and puvisitor isolates clients. Use a **phone hotspot**, or the laptop's Windows Internet Connection Sharing over Ethernet.
   - Check with `curl https://beeline-api-cbjp.onrender.com/` from the Pi.
2. **Dry run with no server on the Pi:**
   - `python3 wearable.py`
   - Check that `hello` shows `imu:1 baro:1 cam:1`.
   - Type `CUE L` / `ARRIVED` and hear the beeps.
   - Walk a few steps and see `step` and `turn` events printed.
3. **Server contract check without the Pi:** `curl` a sample batch to `/api/device/wearable-1/events` and run `tools/mock_device.py` end to end (Task 7).
4. **Create an incident and bind the device:**
   - `POST /incidents` with the TEST synthetic note
   - `POST /incidents/{id}/device {"device_id":"wearable-1"}`
   - Open `/medic` for that incident.
5. **Start the wearable against the server:**
   - `SERVER_URL=https://beeline-api-cbjp.onrender.com DEVICE_ID=wearable-1 python3 wearable.py`
   - The LED should go solid (online).
   - In the `device_events` log, confirm `hello` arrives, then `ack RESET`.
6. **Anchor:** the medic stands at the route start facing along the first segment and presses **button 1**. The server records the heading and floor offsets.
7. **Walk the measured part (Suite 1800 interior).** Verify:
   - The `/medic` dot moves with the steps and rotates on turns.
   - Each LEFT/RIGHT cue in `cues` produces the beep on the wearable within about 1 s, and the device `ack`s it.
   - Walking the wrong way produces `OFF_ROUTE` → `WRONG` alarm.
   - Near the destination, `SCAN ON` triggers photos, and a sign photo snaps the position.
   - At the end, `ARRIVE` → `ARRIVED` beep.
8. **Calibrate:**
   - If the distance drifts, the hardware team adjusts `STRIDE_M` (measured per wearer).
   - If left and right come out swapped, they flip `TURN_SIGN`.
   - If turns are missed, they lower `TURN_MIN_DEG`.
   - These are firmware constants, not backend changes.
9. **Safety check:**
   - A simulated fall (drop the unit onto a cushion, then leave it still) → an alert on `/medic`. Pressing button 1 cancels it.
   - Breathing on the air sensor or using a marker near it → an air alert. The threshold `AIR_WARN_LEVEL` is tuned on the device.
10. **Lock it in:** record the device-side settings and any protocol additions (e.g. `FLOOR U`/`FLOOR D`, `X-Device-Key`) in `contracts/` so both teams build against the same spec.
