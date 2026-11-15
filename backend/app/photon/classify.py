"""What did the crew's text mean? Gemini structured output, the same pattern as intake.py.

The model only labels the text. It never picks a path: a blocker or a new destination goes back through the
deterministic router (app/agent/replan.py) after the crew confirms with YES.
"""

import logging
import re
from typing import Literal

from pydantic import BaseModel, Field

from app.config import get_settings
from app.intake import model_names

logger = logging.getLogger(__name__)

TIMEOUT_S = 10
MAX_RETRIES = 0

SYSTEM_PROMPT = """You read one text message from an ambulance crew who are walking through a building to a patient.
Label it. Use only what the text says; never invent a place, a problem or a detail.

- blocker: something stops them getting through (an elevator is out or stuck, a door is locked, a corridor is blocked).
  Set `elevator` to true only if it is about an elevator or lift.
- destination_change: the patient is somewhere other than expected. Put the room, suite or place they now name in
  `place`, in the words they used.
- crew_tip: lasting information that would help a later crew at this building (a gate code, which elevator is fastest,
  a door that is always locked).
- chatter: anything else (thanks, "on my way", an ETA, a question, a greeting).
`summary` is a short restatement, a few words, with no advice."""

_YES = re.compile(r"^\W*(y|yes|yep|yeah|yup|confirm|confirmed|ok|okay|do it)\W*$", re.IGNORECASE)
_NO = re.compile(r"^\W*(n|no|nope|nah|cancel|stop)\W*$", re.IGNORECASE)


def is_yes(text: str) -> bool:
    return bool(_YES.match(text))


def is_no(text: str) -> bool:
    return bool(_NO.match(text))


class CrewReport(BaseModel):
    category: Literal["blocker", "destination_change", "crew_tip", "chatter"]
    summary: str = Field(default="", description="A few words restating the text")
    place: str | None = Field(default=None, description="destination_change: the place now named")
    elevator: bool = Field(default=False, description="blocker: it is about an elevator or lift")


class CrewClassifier:
    """Tries each Gemini model in turn. Returns None, never raises, when none of them answers."""

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
                ).with_structured_output(CrewReport)
                for name in model_names(settings.gemini_model, settings.gemini_fallback_model)
            ]
        return self._chains

    async def __call__(self, text: str) -> CrewReport | None:
        for chain in self._get_chains():
            try:
                return await chain.ainvoke([("system", SYSTEM_PROMPT), ("human", text)])
            except Exception as failure:  # noqa: BLE001 - any failure moves on to the next model
                logger.warning(
                    "Crew text classification failed (%s); trying the next model",
                    type(failure).__name__,
                )
        return None
