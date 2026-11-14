"""Pydantic models mirroring contracts/building_graph.schema.json and contracts/route.schema.json."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NodeKind = Literal["entrance", "corridor", "door", "elevator", "stairs", "aed"]
EdgeKind = Literal["corridor", "door", "elevator", "stairs"]
Cue = Literal["LEFT", "RIGHT", "STRAIGHT", "UTURN", "FLOOR_UP", "FLOOR_DOWN", "ARRIVE", "OFF_ROUTE"]


class Node(BaseModel):
    id: str
    floor: int
    x: float  # metres east on this floor's plan
    y: float  # metres north on this floor's plan
    kind: NodeKind
    label: str | None = None
    tag_id: str | None = None  # RFID tag UID placed at this node


class Edge(BaseModel):
    # "from" is a Python keyword, so the field is from_node and the JSON key is "from".
    model_config = ConfigDict(populate_by_name=True)

    from_node: str = Field(alias="from")
    to_node: str = Field(alias="to")
    meters: float
    kind: EdgeKind
    stretcher_ok: bool
    seconds: float  # includes wait or climb time for elevator and stair edges


class BuildingGraph(BaseModel):
    building_id: str
    nodes: list[Node]
    edges: list[Edge]


class RouteStep(BaseModel):
    index: int
    from_node: str
    to_node: str
    cue: Cue
    meters: float
    seconds: float
    floor: int  # floor the paramedic is on when this step ends
    text: str
