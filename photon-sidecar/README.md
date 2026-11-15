# photon-sidecar

The only service that talks to [Photon](https://photon.codes). The backend texts the crew's route through it, and
the crew's replies come back through it. Without it (or with `PHOTON_ENABLED=false` on the backend) the web app works
exactly as before.

**Which Photon:** Photon 2.0 (beta) API at `https://api.photon.codes/v1`, through the `@photon-ai/api` client.
`spectrum-ts` is Photon's *Stable* SDK and a different product (and it has no SMS provider). **Which channel:**
iMessage on a *shared* line, one chat per crew member. A shared line cannot create group chats and cannot start a
conversation: each crew member texts the line once, and after that we can message them any time.

```
dispatcher ──POST /incidents/{id}/crew──▶ backend ──POST /assign──▶ sidecar ──▶ Photon
   (crew member is given a number to text once)

route saved ──▶ backend ──POST /send {thread_id, sender_id, text, url}──▶ sidecar ──▶ Photon ──▶ crew's iMessage
                                                      the briefing, then the link on its own (so it unfurls)

crew's reply ──▶ Photon ──signed webhook──▶ sidecar ──▶ backend /crew-threads/resolve + /incidents/{id}/crew-report
                                                    ◀── replies ── (posted back into the same chat)
```

## Set up

1. At [app.photon.codes](https://app.photon.codes) create a **Photon 2.0 (beta)** project. Note its id (`pho_prj_…`) and
   create a project API key (`pho_sk_…`). Keep both out of git.
2. Run the sidecar so Photon can reach it over **public HTTPS** (localhost is blocked): deploy it as a Node web service
   (`npm ci && npm run build`, start `npm start`), or tunnel a local one (`cloudflared tunnel --url http://localhost:8788`).
3. In the project's **Webhooks** page add a destination: URL `https://<sidecar>/photon/webhook`, event
   `message.received`. Copy its `whsec_…` signing secret.
4. Set the variables below (`photon-sidecar/.env`, or the host's environment).
5. In `backend/.env` set `PHOTON_ENABLED=true`, `SIDECAR_URL` (this service), `PHOTON_SHARED_SECRET` (same value as
   here), `PUBLIC_API_URL` (the backend's public address) and run `supabase/migrations/0004_crew_threads.sql`.
6. Add a crew member: `POST /incidents/{id}/crew {"handle": "+15551234567", "name": "Sam"}`. The reply says which
   number to text. When they text it, they get the route (and every later change).

| Variable | What |
| --- | --- |
| `PHOTON_API_KEY` | Project API key `pho_sk_…` (Bearer) |
| `PHOTON_PROJECT_ID` | Project id `pho_prj_…` |
| `PHOTON_WEBHOOK_SECRET` | Webhook signing secret `whsec_…` |
| `BACKEND_URL` | The backend, e.g. `https://beeline-api-cbjp.onrender.com` |
| `PHOTON_SHARED_SECRET` | Shared with the backend, sent as `X-Photon-Secret` both ways |
| `PORT` | Default `8788` |
| `PHOTON_BASE_URL` | Optional: only for tests |

(`SIDECAR_URL` is the *backend's* setting for where this service is.)

## Endpoints

| | |
| --- | --- |
| `GET /health` | `{ok: true}` |
| `POST /send` | `{incident_id, thread_id, sender_id, text?, url?}` → posts `text`, then `url` as its own message. Needs `X-Photon-Secret` |
| `POST /assign` | `{handle, name?}` → `{assigned_phone_number, assignment_id}`. Needs `X-Photon-Secret` |
| `POST /photon/webhook` | Photon's signed `message.received` deliveries (Standard Webhooks). Answers 204 at once, handles the text after |

## Develop

```bash
npm install
npm test            # 20 tests: webhook signatures, the exact requests sent to Photon, the routes
npm run typecheck
npm run dev         # tsx watch
```

## Honest limits

- The Photon calls are checked against Photon's public OpenAPI contract and a stub, **not a live project**: nothing
  here has sent a real iMessage yet. The first live run is the real test.
- `202` from Photon means accepted, not delivered. A failed send is logged and shown to the dispatcher, never retried
  by the route code.
- A crew member who has not texted the line yet cannot be messaged; the dispatcher's trail says so.
- Webhook deliveries are de-duplicated in memory by `webhook-id`: after a restart a retried delivery could repeat once.
- Photon also offers WebSocket delivery, which would avoid needing a public URL. Not used.
