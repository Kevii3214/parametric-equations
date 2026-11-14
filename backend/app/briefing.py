"""The short spoken briefing the crew hears when a route is ready (about 10 seconds, so ~30 words)."""

from app.graph.schema import BuildingGraph, RouteStep

MAX_WORDS = 30  # about ten seconds of speech
HARD_LIMIT_WORDS = 35  # a model-written briefing is cut at this many words


def clip_words(text: str, limit: int) -> str:
    """At most `limit` words, ending at a full stop when there is one inside the limit."""
    words = text.split()
    if len(words) <= limit:
        return text.strip()
    kept = " ".join(words[:limit])
    cut = kept.rfind(".")
    return kept[: cut + 1] if cut > 0 else kept


def spoken_briefing(graph: BuildingGraph, steps: list[RouteStep]) -> str:
    """A plain briefing written from the route itself: entrance, lift or stairs, destination."""
    if not steps:
        return ""
    nodes = {n.id: n for n in graph.nodes}
    edge_kinds = {(e.from_node, e.to_node): e.kind for e in graph.edges}
    parts = []
    entrance = nodes[steps[0].from_node]
    parts.append(f"Enter at {entrance.label or 'the entrance'}.")
    floor = entrance.floor
    for step in steps:
        if step.floor != floor:
            how = (
                "stairs"
                if edge_kinds.get((step.from_node, step.to_node)) == "stairs"
                else "elevator"
            )
            parts.append(f"Take the {how} to floor {step.floor}.")
            floor = step.floor
    goal = nodes[steps[-1].to_node].label or "Your destination"
    parts.append(f"{goal} is ahead.")
    return clip_words(" ".join(parts), MAX_WORDS)
