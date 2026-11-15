"""The agent's read-only file system: what the building data is and how far to trust it.

Seeded into the run's virtual file system (deepagents' StateBackend), so nothing touches the real disk.
`/AGENTS.md` is loaded into the agent's prompt as memory; `/buildings/<id>/GRAPH_NOTES.md` is read on demand by
the `site` subagent, so the briefing can say plainly which parts of a route are estimates.
"""

from pathlib import Path

from deepagents import FilesystemPermission
from deepagents.backends.utils import create_file_data

from app.providers.snapshot import DEFAULT_DIR

AGENTS_MD = """# How to work (dispatch playbook)

- The router, not you, picks the walking route. You choose between router results and write the briefing.
- Say plainly what is an estimate. CoStar floor names are unreliable (use the suite number and say it is a
  guess). The street, lobby, lifts and corridors of most buildings are estimated, not scanned: each building's
  notes are in /buildings/<building_id>/GRAPH_NOTES.md.
- Never invent a building, node, route, time, AED or elevator. If a tool returns an error, say so and stop.
- The briefing is spoken to a paramedic walking: 30 words at most, entrance first, then the turns and floors.
"""

# The model may read these files but never change them.
READ_ONLY = [FilesystemPermission(operations=["write"], paths=["/**"], mode="deny")]


def knowledge_files(directory: Path = DEFAULT_DIR) -> dict:
    """Path -> file data for the run's virtual file system."""
    files = {"/AGENTS.md": create_file_data(AGENTS_MD)}
    for notes in sorted(directory.glob("*/GRAPH_NOTES*.md")):
        files[f"/buildings/{notes.parent.name}/GRAPH_NOTES.md"] = create_file_data(
            notes.read_text(encoding="utf-8")
        )
    return files
