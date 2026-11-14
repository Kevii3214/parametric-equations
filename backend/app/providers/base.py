from typing import Protocol, runtime_checkable


@runtime_checkable
class BuildingProvider(Protocol):
    """Where the three data layers for a building come from.

    All CoStar, Vexcel and Matterport specifics live behind this interface, so the router
    and the agent never know whether the data is live or a saved snapshot.
    """

    async def resolve(self, address: str) -> str:
        """Address -> building_id. Raises LookupError if the building is unknown."""
        ...

    async def record(self, building_id: str) -> dict:
        """CoStar building data. Raises LookupError if the building is unknown."""
        ...

    async def aerial(self, building_id: str) -> bytes:
        """Vexcel aerial image (JPEG bytes). Raises LookupError if the building is unknown."""
        ...

    async def interior(self, building_id: str) -> dict:
        """Matterport scan data. Raises LookupError if the building is unknown."""
        ...

    async def graph(self, building_id: str) -> dict:
        """Indoor routing graph (contracts/building_graph.schema.json). Raises LookupError if there is none."""
        ...
