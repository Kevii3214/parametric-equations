/**
 * Base URL of the FastAPI server (Person 2). By default the browser calls
 * same-origin /api, which Vercel (vercel.json) and the Vite dev server
 * (vite.config.ts) forward to the server, so CORS never applies. Set
 * VITE_API_URL only to call a server directly.
 */
export const API_URL = (import.meta.env.VITE_API_URL as string | undefined) || '/api'
