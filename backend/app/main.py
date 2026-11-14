from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ask, events, incidents, telemetry
from app.config import get_settings

settings = get_settings()

app = FastAPI(title="Beeline")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip().rstrip("/") for o in settings.web_origin.split(",") if o.strip()],
    allow_origin_regex=settings.web_origin_regex or None,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(incidents.router)
app.include_router(telemetry.router)
app.include_router(events.router)
app.include_router(ask.router)


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}
