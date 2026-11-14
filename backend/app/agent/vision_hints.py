"""Ask Gemini where the entrance and the stairs are in a scan's opening picture. A helper, never a decision-maker.

The model only answers with pixel columns; code turns them into map positions (app/graph/from_scan.py), and every
position is listed as inferred so a person checks it. Tests on the demo scans showed the model finds a staircase
reasonably well but often misses an entrance, and says "not visible" rather than inventing one, so a missing hint
is normal and a hint is only a starting point.
"""

import base64
import json
import logging
import re

from langchain_core.messages import HumanMessage

from app.graph.from_scan import DEFAULT_IMAGE_WIDTH, Hints

logger = logging.getLogger(__name__)

MIN_CONFIDENCE = 0.6
SOURCE = "vision, from the opening picture: check it"

PROMPT = """This is the opening view of a 3D indoor scan of a building, from one camera position, {width} pixels wide.
Look carefully across the WHOLE width. Answer ONLY with JSON:
{{"entrance": {{"px": <column of the centre>, "confidence": 0-1, "why": "..."}} or null,
  "stairs": {{"px": <column of the centre>, "confidence": 0-1, "why": "..."}} or null}}
"entrance" = the way in from outside the building: glass doors, arched doorways with daylight or an outdoor view
beyond, revolving doors. "stairs" = a staircase to another level (including glass or open stairs).
Use null when it is not clearly visible; never guess. Pixel columns count from 0 at the left edge to {width} at the right."""


def _find(answer, key: str, width: float) -> float | None:
    item = answer.get(key) if isinstance(answer, dict) else None
    if not isinstance(item, dict):
        return None
    px, confidence = item.get("px"), item.get("confidence")
    if (
        isinstance(px, bool)
        or not isinstance(px, int | float)
        or isinstance(confidence, bool)
        or not isinstance(confidence, int | float)
    ):
        return None
    if confidence < MIN_CONFIDENCE or not 0 <= px <= width:
        return None
    return float(px)


def parse_hints(text: str, width: float) -> Hints:
    """Turn the model's reply into hints. Anything unclear, weak or out of range becomes 'no hint'."""
    answer = None
    match = re.search(r"\{.*\}", text or "", re.DOTALL)
    if match:
        try:
            answer = json.loads(match.group(0))
        except json.JSONDecodeError:
            answer = None
    return Hints(
        entrance_px=_find(answer, "entrance", width),
        stairs_px=_find(answer, "stairs", width),
        image_width=width,
        source=SOURCE,
    )


def propose_hints(llm, image_bytes: bytes, width: float = DEFAULT_IMAGE_WIDTH) -> Hints:
    """Send the picture to the model and return its hints; any failure means no hints."""
    data_url = "data:image/jpeg;base64," + base64.b64encode(image_bytes).decode()
    message = HumanMessage(
        content=[
            {"type": "text", "text": PROMPT.format(width=int(width))},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
    )
    try:
        content = llm.invoke([message]).content
    except Exception:
        logger.warning("The vision helper could not answer", exc_info=True)
        return Hints(image_width=width, source=SOURCE)
    if not isinstance(content, str):  # Gemini can return a list of parts
        content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return parse_hints(content, width)
