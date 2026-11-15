"""The picture a link unfurls into: the route drawn on the building's floor plan, as a PNG.

Pure drawing with Pillow, no network. `render_route_card` draws the router's path (never anything the language
model said); `static_card` is the fallback when there is no route or no graph to draw: the building's saved aerial
picture with the call's title on it.
"""

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.graph.schema import BuildingGraph, RouteStep

CARD_SIZE = (1200, 630)  # the size link previews are designed for (1.91:1)
BACKGROUND = (248, 250, 252)
INK = (15, 23, 42)
MUTED = (100, 116, 139)
GRID = (203, 213, 225)
ROUTE = (37, 99, 235)
ENTRANCE = (22, 163, 74)
PATIENT = (220, 38, 38)
HEADER_HEIGHT = 215
MARGIN = 40


def _font(size: int) -> ImageFont.ImageFont:
    return ImageFont.load_default(size=size)


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.convert("RGB").save(out, format="PNG", optimize=True)
    return out.getvalue()


def _header(draw: ImageDraw.ImageDraw, title: str, subtitle: str, extra: str, colour=INK) -> None:
    draw.text((MARGIN, 34), title[:48], font=_font(56), fill=colour)
    draw.text((MARGIN, 112), subtitle[:70], font=_font(36), fill=colour if colour != INK else MUTED)
    if extra:
        draw.text(
            (MARGIN, 162), extra[:70], font=_font(32), fill=ROUTE if colour == INK else colour
        )
    brand = "Pairatech"
    draw.text(
        (CARD_SIZE[0] - MARGIN - 170, 40),
        brand,
        font=_font(34),
        fill=ROUTE if colour == INK else colour,
    )


def _eta(steps: list[RouteStep]) -> str:
    seconds = round(sum(s.seconds for s in steps))
    if seconds <= 0:
        return ""
    minutes, rest = divmod(seconds, 60)
    return (
        f"About {minutes} min {rest} s from the entrance"
        if minutes
        else f"About {rest} s from the entrance"
    )


def _floors_to_draw(graph: BuildingGraph, steps: list[RouteStep]) -> list[int]:
    nodes = {n.id: n for n in graph.nodes}
    on_route = [nodes[i].floor for s in steps for i in (s.from_node, s.to_node) if i in nodes]
    if not on_route:
        return [min((n.floor for n in graph.nodes), default=0)]
    ordered = list(dict.fromkeys(on_route))  # in the order the crew meets them
    return [ordered[0], ordered[-1]] if len(ordered) > 2 else ordered


def _draw_floor(
    draw: ImageDraw.ImageDraw, graph: BuildingGraph, steps: list[RouteStep], floor: int, box: tuple
) -> None:
    left, top, right, bottom = box
    nodes = {n.id: n for n in graph.nodes}
    here = [n for n in graph.nodes if n.floor == floor]
    draw.rounded_rectangle(box, radius=16, fill=(255, 255, 255), outline=GRID, width=2)
    draw.text((left + 16, top + 10), f"Floor {floor}", font=_font(26), fill=MUTED)
    if not here:
        return
    xs, ys = [n.x for n in here], [n.y for n in here]
    pad = 46
    span_x, span_y = max(xs) - min(xs) or 1.0, max(ys) - min(ys) or 1.0
    scale = min((right - left - 2 * pad) / span_x, (bottom - top - 2 * pad - 20) / span_y)
    # centre the drawing in the box; north is up, so y is flipped
    off_x = left + (right - left - span_x * scale) / 2
    off_y = top + 20 + (bottom - top - 20 - span_y * scale) / 2

    def at(node) -> tuple[float, float]:
        return off_x + (node.x - min(xs)) * scale, off_y + (max(ys) - node.y) * scale

    for e in graph.edges:
        a, b = nodes.get(e.from_node), nodes.get(e.to_node)
        if a and b and a.floor == floor and b.floor == floor:
            draw.line([at(a), at(b)], fill=GRID, width=3)
    for s in steps:
        a, b = nodes.get(s.from_node), nodes.get(s.to_node)
        if a and b and a.floor == floor and b.floor == floor:
            draw.line([at(a), at(b)], fill=ROUTE, width=9, joint="curve")
    for n in here:
        if n.kind in ("elevator", "stairs"):
            x, y = at(n)
            draw.rectangle([x - 7, y - 7, x + 7, y + 7], fill=MUTED)
    if steps:
        for node_id, colour, label in (
            (steps[0].from_node, ENTRANCE, "Start"),
            (steps[-1].to_node, PATIENT, "Patient"),
        ):
            node = nodes.get(node_id)
            if node and node.floor == floor:
                x, y = at(node)
                draw.ellipse(
                    [x - 14, y - 14, x + 14, y + 14], fill=colour, outline=(255, 255, 255), width=3
                )
                font = _font(24)
                width = draw.textlength(label, font=font)
                # keep the label inside the box: to the left of the dot when there is no room on the right
                if x + 20 + width < right - 12:
                    label_at = (x + 20, y - 14)
                else:  # no room on the right: above the dot, where the route line is not
                    label_at = (max(left + 12, min(x - width / 2, right - 12 - width)), y - 52)
                draw.text(label_at, label, font=font, fill=colour)


def render_route_card(
    graph: BuildingGraph, steps: list[RouteStep], *, title: str, subtitle: str
) -> bytes:
    """The router's path over the floor plan, with the entrance and the patient marked."""
    image = Image.new("RGB", CARD_SIZE, BACKGROUND)
    draw = ImageDraw.Draw(image)
    _header(draw, title, subtitle, _eta(steps))
    floors = _floors_to_draw(graph, steps)
    width = CARD_SIZE[0] - 2 * MARGIN
    gap = 24
    panel_w = (width - gap * (len(floors) - 1)) / len(floors)
    for i, floor in enumerate(floors):
        left = MARGIN + i * (panel_w + gap)
        _draw_floor(
            draw, graph, steps, floor, (left, HEADER_HEIGHT, left + panel_w, CARD_SIZE[1] - MARGIN)
        )
    return _png(image)


def static_card(building_id: str | None, fixtures: Path, *, title: str, subtitle: str) -> bytes:
    """The fallback card: the building's saved aerial picture with the title over it, or a plain card."""
    image = None
    if building_id:
        for path in sorted((fixtures / building_id).glob("aerial*.jpg")):
            try:
                image = ImageOps.fit(Image.open(path).convert("RGB"), CARD_SIZE)
                break
            except OSError:
                continue
    if image is None:
        image = Image.new("RGB", CARD_SIZE, ROUTE)
    overlay = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    ImageDraw.Draw(overlay).rectangle(
        [0, CARD_SIZE[1] - 200, CARD_SIZE[0], CARD_SIZE[1]], fill=(15, 23, 42, 200)
    )
    image = Image.alpha_composite(image.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)
    draw.text((MARGIN, CARD_SIZE[1] - 175), title[:48], font=_font(56), fill=(255, 255, 255))
    draw.text((MARGIN, CARD_SIZE[1] - 100), subtitle[:70], font=_font(36), fill=(203, 213, 225))
    draw.text((CARD_SIZE[0] - MARGIN - 170, 40), "Pairatech", font=_font(34), fill=(255, 255, 255))
    return _png(image)
