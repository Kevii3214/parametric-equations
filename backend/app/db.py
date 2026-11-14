from functools import lru_cache

from supabase import Client, create_client

from app.config import get_settings


def normalize_supabase_url(url: str) -> str:
    """Reduce a pasted Supabase URL to the project address: the client adds /rest/v1 itself."""
    return url.strip().rstrip("/").removesuffix("/rest/v1").rstrip("/")


@lru_cache
def get_db() -> Client:
    """Supabase client using the service-role key. Server only: never send this key to the browser."""
    settings = get_settings()
    if not settings.supabase_url or not settings.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in backend/.env")
    return create_client(
        normalize_supabase_url(settings.supabase_url), settings.supabase_service_role_key
    )
