import { createBackend } from './backend.js'
import { loadConfig } from './config.js'
import { createInbound } from './inbound.js'
import { createPhoton } from './photon.js'
import { createApp } from './server.js'

const config = loadConfig()
const photon = createPhoton(config)
const backend = createBackend(config)
const app = createApp({ config, photon, onInbound: createInbound(backend, photon) })

app.listen(config.port, () => {
  console.log(`photon-sidecar listening on :${config.port} -> backend ${config.backendUrl}`)
  console.log('Photon webhook destination must point (public HTTPS) at POST /photon/webhook')
})
