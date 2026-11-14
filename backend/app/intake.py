import logging

from app.config import get_settings
from app.models import ParsedNote

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You read a dispatcher's short note about an emergency medical call and fill in the fields.
Use only what the note says. Never invent an address, suite, floor or detail that is not written there;
leave a field empty instead. Give a floor only if the note states one explicitly. The suite is only its number or identifier
(for example "1800"), without the word Suite or a tenant name. Do not add advice."""

# A dispatcher's call must not hang on a busy model: give up fast and move to the next one.
TIMEOUT_S = 10
MAX_RETRIES = 0


def model_names(primary: str, fallbacks: str) -> list[str]:
    """Models to try in order: the main one, then each fallback (comma separated), skipping repeats."""
    ordered: list[str] = []
    for name in [primary, *fallbacks.split(",")]:
        name = name.strip()
        if name and name not in ordered:
            ordered.append(name)
    return ordered


class NoteParser:
    """Turns a call note into a ParsedNote with Gemini structured output.

    Tries each model in turn and raises only if all of them fail. The Gemini clients are built on first
    use, so a missing key fails inside the request (where the endpoint handles it), not at startup.
    """

    def __init__(self, chains=None):
        self._chains = chains

    def _get_chains(self):
        if self._chains is None:
            from langchain_google_genai import ChatGoogleGenerativeAI

            settings = get_settings()
            self._chains = [
                ChatGoogleGenerativeAI(
                    model=name,
                    google_api_key=settings.google_api_key,
                    temperature=0,
                    timeout=TIMEOUT_S,
                    max_retries=MAX_RETRIES,
                ).with_structured_output(ParsedNote)
                for name in model_names(settings.gemini_model, settings.gemini_fallback_model)
            ]
        return self._chains

    async def __call__(self, note: str) -> ParsedNote:
        error: Exception | None = None
        for chain in self._get_chains():
            try:
                return await chain.ainvoke([("system", SYSTEM_PROMPT), ("human", note)])
            except Exception as failure:  # noqa: BLE001 - any failure moves on to the next model
                logger.warning(
                    "Gemini call failed (%s); trying the next model", type(failure).__name__
                )
                error = failure
        raise error or RuntimeError("No Gemini model is configured")
