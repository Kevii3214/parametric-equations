import json
import re
from pathlib import Path

DEFAULT_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "buildings"


def _normalize(text: str) -> str:
    """Lowercase, drop punctuation and collapse spaces: '1415 Louisiana St.' -> '1415 louisiana st'."""
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", text.lower()).split())


class SnapshotProvider:
    """Reads the saved snapshot in fixtures/buildings/<building_id>/. Makes no network calls."""

    def __init__(self, directory: Path = DEFAULT_DIR):
        self.directory = directory

    async def resolve(self, address: str) -> str:
        index = json.loads((self.directory / "index.json").read_text(encoding="utf-8"))
        wanted = f" {_normalize(address)} "
        for building_id, entry in index.items():
            if any(f" {_normalize(alias)} " in wanted for alias in entry["aliases"]):
                return building_id
        raise LookupError(f"No snapshot building matches address {address!r}")

    async def record(self, building_id: str) -> dict:
        return json.loads(self._file(building_id, "record.json").read_text(encoding="utf-8"))

    async def aerial(self, building_id: str) -> bytes:
        return self._file(building_id, "aerial.jpg").read_bytes()

    async def interior(self, building_id: str) -> dict:
        return json.loads(self._file(building_id, "interior.json").read_text(encoding="utf-8"))

    async def graph(self, building_id: str) -> dict:
        return json.loads(self._file(building_id, "graph.json").read_text(encoding="utf-8"))

    async def scans(self, building_id: str) -> dict:
        return json.loads(self._file(building_id, "sweeps.json").read_text(encoding="utf-8"))

    def _file(self, building_id: str, name: str) -> Path:
        # building_id becomes part of a path, so only plain ids are allowed.
        if not re.fullmatch(r"[A-Za-z0-9_-]+", building_id):
            raise LookupError(f"Invalid building id {building_id!r}")
        path = self.directory / building_id / name
        if not path.is_file():
            raise LookupError(f"No snapshot {name} for building {building_id!r}")
        return path
