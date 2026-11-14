from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import incidents, telemetry
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Beeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_origin],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(incidents.router)
app.include_router(telemetry.router)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
