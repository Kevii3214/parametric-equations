from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.config import Settings


def client_for(**env):
    settings = Settings(_env_file=None, **env)
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip().rstrip("/") for o in settings.web_origin.split(",") if o.strip()],
        allow_origin_regex=settings.web_origin_regex or None,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    def health():
        return {"ok": True}

    return TestClient(app)


def allowed(client, origin):
    return client.get("/health", headers={"Origin": origin}).headers.get(
        "access-control-allow-origin"
    )


def test_main_app_reads_settings_the_same_way():
    import app.main  # noqa: F401  (imports without error with the new settings)


def test_several_origins_and_a_trailing_slash():
    c = client_for(web_origin="http://localhost:5173, https://beeline.vercel.app/")
    assert allowed(c, "https://beeline.vercel.app") == "https://beeline.vercel.app"
    assert allowed(c, "http://localhost:5173") == "http://localhost:5173"
    assert allowed(c, "https://evil.example") is None


def test_regex_allows_preview_urls_only_when_set():
    c = client_for(
        web_origin="https://beeline.vercel.app", web_origin_regex=r"https://beeline-.*\.vercel\.app"
    )
    assert allowed(c, "https://beeline-git-x.vercel.app")
    assert (
        allowed(
            client_for(web_origin="https://beeline.vercel.app"), "https://beeline-git-x.vercel.app"
        )
        is None
    )
