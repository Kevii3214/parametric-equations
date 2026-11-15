"""What each lookup subagent reports back to the main agent.

Giving a subagent a response_format makes the parent receive this as JSON instead of free text, so the main
agent reads fields (an entrance list, a goal node) instead of parsing a paragraph.
"""

from pydantic import BaseModel, Field


class Entrance(BaseModel):
    node_id: str
    label: str | None = None
    floor: int | None = None


class SiteFindings(BaseModel):
    """The building as the router sees it: where to enter and where the patient is."""

    building_id: str | None = Field(
        default=None, description="The building id, or null if not found"
    )
    entrances: list[Entrance] = Field(default_factory=list, description="Every entrance node")
    goal_node: str | None = Field(
        default=None, description="The node id of the most specific place the call names, or null"
    )
    goal_label: str | None = None
    estimates: str = Field(
        default="",
        description="One or two sentences from the building notes file: which parts of the map are "
        "measured and which are estimated",
    )
    error: str | None = Field(default=None, description="Set when a lookup failed")


class RecordsFindings(BaseModel):
    """CoStar facts about the building and the patient's suite."""

    building_id: str | None = None
    name: str | None = None
    suite: str | None = None
    tenant: str | None = None
    floor: int | None = Field(
        default=None, description="The patient's floor if the call or suite gives one"
    )
    floor_is_guess: bool = Field(
        default=False, description="True when the floor came from the suite number"
    )
    passenger_elevators: int | None = None
    warnings: list[str] = Field(default_factory=list, description="Data-quality warnings, if any")
    error: str | None = None


class NotesFindings(BaseModel):
    """Tips earlier crews saved for this building."""

    building_id: str | None = None
    tips: list[str] = Field(
        default_factory=list, description="Only tips that matter for getting in"
    )
    error: str | None = None
