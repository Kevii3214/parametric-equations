import pytest

from app.db import normalize_supabase_url


@pytest.mark.parametrize(
    "pasted",
    [
        "https://abc.supabase.co",
        "https://abc.supabase.co/",
        "https://abc.supabase.co/rest/v1",
        "https://abc.supabase.co/rest/v1/",
        "  https://abc.supabase.co/rest/v1/  ",
    ],
)
def test_url_is_reduced_to_the_project_address(pasted):
    """The dashboard shows the REST address, but the client adds /rest/v1 itself."""
    assert normalize_supabase_url(pasted) == "https://abc.supabase.co"
