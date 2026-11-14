/**
 * Base URL of the FastAPI server (Person 2). By default the browser calls
 * same-origin /api, which Vercel (vercel.json) and the Vite dev server
 * (vite.config.ts) forward to the server, so CORS never applies.
 * VITE_API_DIRECT_URL is an optional override to call a server directly.
 * (The old VITE_API_URL is deliberately ignored so a stale value can't
 * bypass the forward.)
 */
export const API_URL = (import.meta.env.VITE_API_DIRECT_URL as string | undefined) || '/api'
