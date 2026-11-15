# Crew chat (Photon): backend endpoints

Additive to `api.md`. Off unless the backend has `PHOTON_ENABLED=true`. The sidecar (`photon-sidecar/`) is the only
thing that talks to Photon; the backend never holds Photon keys. Needs `supabase/migrations/0004_crew_threads.sql`.

## Dispatcher side

| Method and path | Body | Response |
| --- | --- | --- |
| `POST /incidents/{id}/crew` | `{ "handle": "+15551234567", "name": "Sam" }` (phone with country code, or email) | `{ "ok": true, "handle", "text_this_number" }`. 422 bad handle, 502 Photon failed, 503 sidecar not configured |
| `GET /incidents/{id}/crew` | none | `{ "crew": [{ handle, name, assigned_phone_number, joined }] }` (`joined` = they have texted the line) |

A shared iMessage line cannot start a conversation, so a crew member gets nothing until they text `text_this_number`
once. When they do, and a route exists, it is sent straight away.

## Sidecar side (header `X-Photon-Secret` = `PHOTON_SHARED_SECRET`)

| Method and path | Body | Response |
| --- | --- | --- |
| `POST /crew-threads/resolve` | `{ handle, space_id, user_id }` | `{ incident_id, first_contact }`; 404 if that phone is not on an active incident. Remembers the chat |
| `POST /incidents/{id}/crew-report` | `{ text, sender, channel }` | `{ category, replies: [str] }`, or `{ ignored: true, reason, replies: [] }`. The sidecar posts `replies` back |

`category`: `blocker`, `destination_change`, `crew_tip`, `chatter` (Gemini labels it), then `confirmed`, `cancelled`,
`unclassified`. Chatter gets no reply. A blocker or a destination change asks "Reply YES to confirm" and changes
nothing until YES; YES runs the existing re-plan code (the router picks the path), then the new briefing and link
are texted. A crew tip is saved as a note, so `search_notes` finds it next time.

## Sidecar service

`POST /send` `{ incident_id, thread_id, sender_id, text?, url? }`, `POST /assign` `{ handle, name? }`,
`POST /photon/webhook` (signed by Photon). See `photon-sidecar/README.md`.

## The link and its card

`GET /medic/{incident_id}?t=<token>[&v=<route version>]` returns HTML with `og:` and `twitter:` tags in the head
(link-preview crawlers do not run JavaScript); a person's browser is sent on to `<PUBLIC_WEB_URL>/arrival?incident=…`.
`GET /medic/{incident_id}/card.png?t=…` is a 1200×630 PNG of the router's path on the floor plan (the building's
aerial picture if it cannot be drawn). The token is an HMAC of the incident id; without it both are 404. `v` only
makes the URL new for each route version, because chat apps cache previews by URL. The web app can serve the same
paths: `frontend/vercel.json` rewrites `/medic/:id` and `/medic/:id/card.png` to the backend.

## Dispatcher's trail

`plan_steps.kind = "crew"`: `crew texted: <text>`, `texted crew: <text>`, and "No crew member has joined the chat yet"
or "Could not text the crew" when nothing could be sent.
