# frontend — dispatch + medic frontend

Vite + React + TypeScript + Tailwind v4, routing with react-router, Supabase JS client.

## Run it

```bash
cd frontend
npm install
cp .env.example .env.local   # fill in Supabase URL + anon key, API URL
npm run dev                  # http://localhost:5173
```

Pages: `/dispatch` and `/medic` (`/` redirects to `/dispatch`).

The app still loads without Supabase env vars. The header shows "Supabase not configured", and `supabase` from `src/lib/supabase.ts` is `null`.

## Layout

- `src/lib/supabase.ts`: shared Supabase client
- `src/lib/config.ts`: `API_URL` for the FastAPI server
- `src/components/Layout.tsx`: header and nav
- `src/pages/`: one file per page
- `vercel.json`: SPA rewrite so deep links like `/medic` work on Vercel
