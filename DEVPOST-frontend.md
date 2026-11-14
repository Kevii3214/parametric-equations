# Pairatech: Devpost, frontend half

Paste "What it does" and "Accomplishments" into their Devpost fields. The other sections add to the matching
sections in `DEVPOST.md` (the technical half): paste them underneath.

Live site: https://pairatech.vercel.app (`/dispatch` and `/medic`; add `?demo=1` for the offline replay).

## What it does

A paramedic crew can reach the right building in minutes, then lose more minutes inside it: which entrance, which
elevator bank, which floor, which door. Pairatech covers those last 100 metres.

**The dispatcher** types the call note ("65M chest pain, Suite 1800, 1415 Louisiana St") and presses Dispatch.
The screen fills in as the agent works:
- **Agent plan trace.** Every plan step, subagent result, router call and re-plan streams in live as a timeline,
  so you can see the agent think instead of taking its answer on trust.
- **The site, four ways.** A 3D flyover drops in over downtown Houston, circles the tower and lands on the
  entrance the agent chose. Vexcel's overhead image shows the CoStar parcel and both entrances. Vexcel's four
  oblique photos play as an approach tour from every side. The six Matterport scans open as 3D walkthroughs,
  starting with the patient's suite.
- **The CoStar record.** Class A, 43 stories, 15 passenger elevators and 1 freight, 1,604 covered parking spaces,
  and who is in the patient's suite (Regus, floor 18), with CoStar's own data-quality warnings one click away.
- **The route.** Door-to-patient time, distance, floors and every turn from the fastest entrance (the trace shows
  the times from each entrance it compared).

**The paramedic** opens the medic view on a phone:
- A large next-turn card ("In 6 m · Turn right") that turns red when the crew leaves the route.
- Time remaining, current floor and step, and the steps ahead, with finished steps checked off.
- A floor plan with the route line and a live position dot, which follows the crew from floor to floor, and a
  3D scan of the destination suite one tap away.

## How we built it: the web app

**React, TypeScript and Vite, styled with Tailwind, deployed on Vercel.** Two pages share one live view of the
incident. A single hook subscribes to the five shared Supabase tables (incidents, plan steps, routes, positions,
cues) with Realtime, so the dispatcher and the medic see the same agent output the moment the server writes it.
The browser only ever holds Supabase's public key; it reads and never writes.

**All three CoStar data layers on screen.**
- *CoStar building data* drives the record card and the tenant lookup for the patient's suite.
- *Vexcel imagery*: the overhead image is overlaid with the CoStar parcel, positioned from the parcel's own
  coordinates (the image is the parcel's bounding box plus a 10 m buffer), and the four obliques become the
  approach tour.
- *Matterport* scans are embedded as guided walkthroughs; the scan-derived building graph draws the medic's floor
  plan.

The 3D flyover uses MapLibre with free OpenStreetMap building heights, so it needs no map API key, and loads only
when opened to keep the first page load small.

**A demo that cannot fail on stage.** If the server is unreachable, the app replays the real demo building instead
of showing empty panels: a plan trace built from the CoStar, Vexcel and Matterport snapshot, and routes from a
TypeScript port of the server's A* router (same costs, closure rules, turn cues and step text). The medic view walks
that route on its own, floor change included, so the whole flow works with no server, no wearable and no Wi-Fi.

**Designed for a moving crew.** The medic view is built phone-first: one dominant instruction, high contrast,
and status that reads at a glance. One design system across both pages: warm off-white, blue
for the route and anything you can press, green for "go" and "arrived", and red and amber kept for real alerts.

## Challenges (web app)

- **Images without coordinates.** Vexcel's overhead image came with no georeference. We worked out its extent
  from how it was requested (the parcel's box plus 10 m), and the parcel outline lands on the building.
- **Estimated entrances.** No scan covers the street or lobby, so entrance pins are placed by eye on the aerial,
  and the interface says "position estimated" instead of implying precision we do not have.
- **The 3D map.** A map library CSS rule silently collapsed the map to zero height, and the newest major version
  never loaded its tiles; we pinned a stable release and load the map on demand.
- **Two pages, one incident.** Switching between dispatch and medic dropped the incident id from the URL until
  we carried it through navigation.

## Accomplishments that we're proud of

- A dispatcher sees every CoStar data layer for the building (records, overhead and oblique aerials, 3D interior
  scans and a 3D flyover) on one screen, seconds after typing a call note.
- The agent's reasoning is visible live, step by step, which makes the planning and re-planning easy to judge.
- The full demo runs offline with the real building, using the same routing rules as the server.

## What we learned (web app)

- Showing the agent's work builds more trust than showing only its answer.
- Imagery earns its place when it answers a question ("where do we stop?"), not as decoration.
- Build the offline path first; it makes every later demo calmer.

## What's next (web app)

Crew controls on the medic view ("elevator out", notes) feeding the server's re-plan, a clear re-plan banner and
before/after route, spoken briefings and voice questions through `POST /ask`, a direct Bluetooth link to the
wearable, and the Matterport camera following the crew along the route.

## Screenshots to upload

1. Dispatch with the plan trace and the 3D flyover.
2. The Vexcel overhead with the parcel outline and entrance pins.
3. An oblique from the approach tour.
4. The Regus Suite 1800 Matterport walkthrough.
5. The medic view on a phone: next-turn card and floor plan.
