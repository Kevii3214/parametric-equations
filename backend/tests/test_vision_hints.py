from types import SimpleNamespace

import pytest

from app.agent.vision_hints import MIN_CONFIDENCE, parse_hints, propose_hints
from app.graph.from_scan import Hints

WIDTH = 3034


def test_a_clear_answer_becomes_hints_in_the_pictures_pixel_columns():
    text = '{"entrance": {"px": 2000, "confidence": 0.9, "why": "arched glass doors"}, "stairs": {"px": 300, "confidence": 0.8, "why": "glass stairs"}}'
    hints = parse_hints(text, WIDTH)
    assert (hints.entrance_px, hints.stairs_px, hints.image_width) == (2000, 300, WIDTH)
    assert "vision" in hints.source


def test_json_wrapped_in_a_code_fence_is_understood():
    text = '```json\n{"entrance": null, "stairs": {"px": 105, "left_px": 0, "left_px": 0, "right_px": 211, "confidence": 0.9, "why": "stairs"}}\n```'
    hints = parse_hints(text, WIDTH)
    assert hints.entrance_px is None and hints.stairs_px == 105


def test_not_visible_means_no_hint_never_a_guess():
    assert parse_hints('{"entrance": null, "stairs": null}', WIDTH) == Hints(
        image_width=WIDTH, source=parse_hints("{}", WIDTH).source
    )


@pytest.mark.parametrize(
    "text",
    [
        '{"entrance": {"px": 2000, "confidence": 0.3, "why": "maybe a door"}, "stairs": null}',  # not sure enough
        '{"entrance": {"px": 99999, "confidence": 0.9, "why": "x"}, "stairs": null}',  # outside the picture
        '{"entrance": {"px": -5, "confidence": 0.9, "why": "x"}, "stairs": null}',
        '{"entrance": {"px": "left", "confidence": 0.9, "why": "x"}, "stairs": null}',  # not a number
        '{"entrance": {"confidence": 0.9}, "stairs": null}',  # no position
    ],
)
def test_weak_or_nonsense_answers_are_dropped(text):
    assert parse_hints(text, WIDTH).entrance_px is None


@pytest.mark.parametrize("text", ["", "I cannot see anything", "[1, 2, 3]", "{not json", "null"])
def test_text_that_is_not_the_expected_json_gives_no_hints(text):
    hints = parse_hints(text, WIDTH)
    assert hints.entrance_px is None and hints.stairs_px is None


def test_the_confidence_bar_is_not_trivially_low():
    assert MIN_CONFIDENCE >= 0.6


class FakeLlm:
    def __init__(self, answer=None, error=None):
        self.answer, self.error, self.messages = answer, error, None

    def invoke(self, messages):
        self.messages = messages
        if self.error:
            raise self.error
        return SimpleNamespace(content=self.answer)


def test_the_picture_and_the_rules_are_sent_to_the_model():
    llm = FakeLlm('{"entrance": null, "stairs": null}')
    propose_hints(llm, b"\xff\xd8fake-jpeg", WIDTH)
    content = llm.messages[0].content
    assert any(
        part["type"] == "image_url"
        and part["image_url"]["url"].startswith("data:image/jpeg;base64,")
        for part in content
    )
    text = next(part["text"] for part in content if part["type"] == "text")
    assert "never guess" in text.lower() and str(WIDTH) in text


def test_a_failing_model_means_no_hints_not_a_crash():
    hints = propose_hints(FakeLlm(error=RuntimeError("429")), b"x", WIDTH)
    assert hints.entrance_px is None and hints.stairs_px is None


def test_a_model_that_answers_in_parts_is_understood():
    llm = FakeLlm(
        [
            {
                "type": "text",
                "text": '{"entrance": null, "stairs": {"px": 400, "confidence": 0.85, "why": "stairs"}}',
            }
        ]
    )
    assert propose_hints(llm, b"x", WIDTH).stairs_px == 400
