from typing import Literal

from pydantic import BaseModel, Field, field_validator


class IncidentCreate(BaseModel):
    """Body of POST /incidents: the dispatcher's free-text call note."""

    note: str = Field(max_length=2000)

    @field_validator("note")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("note must not be empty")
        return value


class ParsedNote(BaseModel):
    """What the dispatcher's note says, in fields. Stored in incidents.parsed."""

    address: str = Field(
        min_length=1, description="Street address of the building, as written in the note"
    )
    suite: str | None = Field(
        default=None, description="Suite or unit number if the note gives one"
    )
    floor: int | None = Field(
        default=None, description="Floor number only if the note states it explicitly"
    )
    complaint: str = Field(
        min_length=1, description="The medical complaint, with age and sex if given"
    )
    access_notes: str | None = Field(
        default=None, description="Anything about getting in: gate codes, entrances, hazards"
    )


class Telemetry(BaseModel):
    """One wearable sample (contracts/telemetry.schema.json), about 5 per second."""

    t: int = Field(ge=0, description="Milliseconds since the wearable booted")
    steps: int = Field(ge=0, description="Running step count since boot")
    heading: float = Field(
        ge=0, le=360, description="Degrees from the gyroscope; relative, drifts slowly"
    )
    pressure: float = Field(gt=0, description="Air pressure in pascals")
    btn: Literal[0, 1, 2] = Field(description="0 none, 1 confirm, 2 elevator out")
    tag: str | None = Field(default=None, description="RFID tag UID scanned in this sample")


class AskIn(BaseModel):
    """Body of POST /ask."""

    incident_id: str
    question: str = Field(max_length=500)

    @field_validator("question")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be empty")
        return value


class EventIn(BaseModel):
    """Body of POST /incidents/{id}/events: something the crew reports."""

    type: Literal["elevator_out", "obstacle", "note", "arrived", "skip_floor", "rejoin"]
    text: str | None = Field(default=None, max_length=1000)
