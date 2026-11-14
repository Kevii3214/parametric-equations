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
