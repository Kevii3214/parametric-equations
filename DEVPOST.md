# Beeline: Devpost, technical half

Paste these sections into the Devpost "How we built it", "Challenges" and "What we learned" fields.

## How we built it

Beeline is a FastAPI server with a LangChain `deepagents` agent on Gemini, a NetworkX router, a position engine
fed by a forearm wearable, and Supabase Realtime pushing everything to a React web app.

**Three CoStar data layers, combined.** For the demo building, 1415 Louisiana in Houston, we use CoStar building
data (suite and tenant lookup, elevator and parking counts, data-quality warnings), Vexcel aerial imagery (parcel
outline and four oblique views), and a Matterport scan (measured doorways and rooms of Suite 1800). The agent
resolves the address and suite from CoStar data, picks the goal in the Matterport-derived graph, and uses the
building's entrances as route starting points. CoStar's own floor names were wrong for this 43-story building, so
the records tool derives the floor from the suite number and flags it as a guess.

**An agent that plans, acts and re-plans.**
- It writes a plan, delegates the suite lookup to a records subagent, checks saved crew notes, asks the router for
  a route from every entrance in parallel, picks the fastest and writes a 30-word spoken briefing.
- Every plan step, subagent call, tool call and tool result is saved to `plan_steps`, so judges watch it work
  live in the web app.
- When the paramedic presses "elevator out" on the wearable, or the web app reports an obstacle, the server
  closes that part of the building, reroutes from the crew's current node, saves a new route version and logs a
  `replan` step. In the demo building the elevator closure sends the crew up the stairs.
- Guard rails: a cap on model calls and LangGraph recursion, model fallbacks, and honest failure reporting in the
  trace. If the model fails after the route is saved, the trace says the route was saved.

**Safety rule: the LLM never picks the path.** Gemini parses the note, chooses between router results and writes
briefings. The route is always A* over the building graph, skipping non-stretcher-safe edges and closed places, and
the tool that saves a route takes only node ids: the model cannot supply route steps. A hallucination cannot send a
crew down a corridor that does not exist.

**Wearable to cue.** An Arduino Mega with step, gyroscope, pressure and RFID sensors, bridged by a Raspberry Pi,
posts about five samples a second. The position engine turns step counts into metres along the route, writes a turn
cue once when a turn is 6 m away, confirms turns from heading change (the gyroscope drifts, so we only use
changes), notices floor changes from a roughly 35 Pa pressure shift, and snaps to a node when an RFID tag is
scanned. A wrong-way turn or walking 5 m past a turn raises `OFF_ROUTE`. A mock wearable replays a route for
testing without hardware.

**Memory.** Crew notes ("freight lift is key-only") are stored per building with Gemini embeddings in
Postgres (pgvector) and searched on the next call to that building by the agent and by `POST /ask`, which also
answers from CoStar data and the live route.

**Built to survive bad Wi-Fi.** The demo building runs entirely from a saved snapshot (`SnapshotProvider`), the
re-plan path needs no model, notes still work without embeddings (word matching), and `/ask` falls back to the route
briefing if Gemini is unreachable.

**Stack:** Python, FastAPI, Pydantic, LangChain deepagents and LangGraph, Gemini (`langchain-google-genai`),
NetworkX, Supabase (Postgres, Realtime, pgvector), React and Vite, Arduino and Raspberry Pi. 204 automated tests.

## Challenges

- **The scans were not what their names said.** The Matterport model named "Lobby" is a coworking reception on
  floor 18, not the street lobby. We checked thumbnails and rebuilt the demo around it: street, lobby and
  elevators are estimated, Suite 1800 is measured. We label which is which instead of hiding it.
- **Unreliable CoStar floors.** Listed floors did not match the building, so floors come from suite numbers.
- **Indoor positioning without GPS.** Steps and a drifting gyroscope are noisy. Using heading changes, RFID tags
  as snap points and pressure for floors keeps the dot honest.
- **Re-plan spam.** The "elevator out" button is held for many samples, which would trigger many re-plans. We
  re-plan once per route version.
- **Demo reliability.** We cut model calls where a deterministic path works, run the agent's route comparisons in
  parallel, and add fallbacks everywhere a network call could fail.

## What we learned

- Let the model plan and explain; let tested code make the safety-critical decision.
- A visible agent trace is the best way to show agentic depth.
- Label estimated data as estimated. Trust is worth more than a cleaner demo.

## What's next

Live aerial and interior subagents (today these layers are processed ahead of time into the snapshot), scanning
real elevator banks and corridors for every building, matching the RFID tags to the real hardware, and sending
the briefing straight to the wearable.
