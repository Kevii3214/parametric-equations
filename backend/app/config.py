from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings read from environment variables or backend/.env (git-ignored)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    supabase_url: str = ""
    supabase_service_role_key: str = ""
    google_api_key: str = ""
    gemini_model: str = ""
    gemini_fallback_model: str = ""
    gemini_subagent_model: str = ""  # optional faster model for the lookup subagents
    gemini_embedding_model: str = "gemini-embedding-001"
    costar_api_key: str = ""
    costar_mcp_url: str = ""
    demo_building_id: str = ""
    use_snapshot: bool = False
    stride_m: float = 0.7
    web_origin: str = "http://localhost:5173"  # one origin, or several separated by commas
    web_origin_regex: str = ""  # optional, e.g. https://beeline-.*\.vercel\.app for Vercel previews


@lru_cache
def get_settings() -> Settings:
    return Settings()
