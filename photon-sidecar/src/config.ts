export interface Config {
  /** Photon project API key (pho_sk_...), sent as a Bearer token. */
  apiKey: string
  /** Photon project id (pho_prj_...). */
  projectId: string
  /** The webhook destination's signing secret (whsec_...). */
  webhookSecret: string
  /** The backend (FastAPI) this sidecar reports to. */
  backendUrl: string
  /** Shared with the backend's PHOTON_SHARED_SECRET: sent in X-Photon-Secret both ways. */
  sharedSecret: string
  port: number
  /** Only for tests and alternative environments. */
  photonBaseUrl?: string
}

export function loadConfig(env: NodeJS.ProcessEnv = process.env): Config {
  const need = (name: string): string => {
    const value = env[name]?.trim()
    if (!value) throw new Error(`${name} is not set (see photon-sidecar/.env.example)`)
    return value
  }
  return {
    apiKey: need('PHOTON_API_KEY'),
    projectId: need('PHOTON_PROJECT_ID'),
    webhookSecret: need('PHOTON_WEBHOOK_SECRET'),
    backendUrl: need('BACKEND_URL').replace(/\/+$/, ''),
    sharedSecret: need('PHOTON_SHARED_SECRET'),
    port: Number(env.PORT?.trim() || 8788), // a blank PORT= line must not become 0 (a random port)
    photonBaseUrl: env.PHOTON_BASE_URL?.trim() || undefined,
  }
}
