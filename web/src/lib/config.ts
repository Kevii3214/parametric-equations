/** Base URL of the FastAPI server (Person 2). Defaults to local dev. */
export const API_URL =
  (import.meta.env.VITE_API_URL as string | undefined) ?? 'http://localhost:8000'
