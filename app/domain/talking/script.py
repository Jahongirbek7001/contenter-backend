"""Scripts for spoken videos. Hydrogen checks the selfie and writes one line per 10 s part
(talking = 1 part, series = 3) plus a story bible that keeps the parts visually consistent.
Writing and rewriting a script is free for the user; the video is what costs ⚡."""

import json
from dataclasses import dataclass
from decimal import Decimal

from app.domain.generations.runner import RejectReason, reject_reason
from app.gateway.base import MediaInput, ProviderFailedError, TextProvider
from app.models.enums import Language, Product

PART_SECONDS = 10
PARTS = {Product.TALKING: 1, Product.SERIES: 3}
# ~2.2 spoken words per second in Uzbek and Russian; a little slack for the user's own text.
MAX_WORDS_PER_LINE = 26
SPOKEN_LANGUAGE = {Language.UZ: "Uzbek (Latin script)", Language.RU: "Russian"}

SCRIPT_INSTRUCTIONS = """You write the spoken script of a short vertical video in which the
person from the selfie talks to the camera. Return JSON only:
{"photo_ok": true, "reject_reason": null, "idea_ok": true, "idea": "...",
 "lines": ["..."], "story_bible": "..."}

1. Check the selfie. Set photo_ok to false and reject_reason to one of these when it applies:
- "no_face": no clearly visible human face
- "several_people": more than one person in the photo
- "minor": the person may be under 18
- "celebrity": the person is a well-known public figure
- "nudity": nudity or sexual content
- "low_quality": too blurry, dark or small to keep the face recognisable

2. Check the idea (text, or the attached voice message). Set idea_ok to false when it is
sexual, hateful, violent, illegal, political, impersonates someone, or targets children.

3. When both are fine, write:
- idea: the user's idea in one or two sentences in the spoken language (transcribe a voice
  message).
- lines: exactly the requested number of lines in the spoken language. Each line is spoken in
  10 seconds: 14 to 22 words of natural, everyday speech. Uzbek is written in Latin script.
  No hashtags, emojis, stage directions or quotation marks. With several lines they form one
  story: the first hooks the viewer, the middle develops it, the last one ends it.
- story_bible: in English, 2-3 sentences fixing what stays the same in every part: one setting
  that fits the idea, framing, lighting, the person's clothing as in the selfie, and the voice
  tone. Do not describe the face.
Follow the style rules, including whether a call to action is allowed. Never invent prices,
dates, brands, medical or financial promises. When something is rejected, idea, lines and
story_bible may be empty."""


class ScriptError(ValueError):
    """The user's own script cannot be used; `code` picks the message shown to them."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Script:
    idea: str
    lines: tuple[str, ...]
    story_bible: str

    def to_json(self) -> str:
        return json.dumps(
            {"idea": self.idea, "lines": list(self.lines), "story_bible": self.story_bible},
            ensure_ascii=False,
        )

    @classmethod
    def from_json(cls, raw: str) -> "Script":
        data = json.loads(raw)
        return cls(
            idea=str(data["idea"]),
            lines=tuple(str(line) for line in data["lines"]),
            story_bible=str(data["story_bible"]),
        )


@dataclass(frozen=True)
class ScriptDraft:
    """Either a script, or the reason none was written."""

    script: Script | None
    photo_reason: RejectReason | None
    idea_rejected: bool
    cost_usd: Decimal


async def write_script(
    text: TextProvider,
    *,
    style_instructions: str,
    language: Language,
    parts: int,
    selfie: MediaInput,
    idea: str | None,
    voice: MediaInput | None = None,
    previous: Script | None = None,
) -> ScriptDraft:
    if idea is None and voice is None:
        raise ValueError("an idea or a voice message is required")
    prompt = [
        f"Style rules:\n{style_instructions}",
        f"Spoken language: {SPOKEN_LANGUAGE[language]}",
        f"Number of lines: {parts}",
        f"Idea: {idea}" if idea else "Idea: in the attached voice message.",
    ]
    if previous is not None:
        prompt.append(
            "The user asked for a different version. Previous lines, do not repeat them:\n"
            + "\n".join(previous.lines)
        )
    media = (selfie, voice) if voice is not None else (selfie,)
    result = await text.complete(SCRIPT_INSTRUCTIONS, "\n\n".join(prompt), media)
    return parse_script(result.text, parts, result.cost_usd)


def parse_script(text: str, parts: int, cost_usd: Decimal) -> ScriptDraft:
    cleaned = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```")
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ProviderFailedError(f"script is not JSON: {text[:200]}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("photo_ok"), bool):
        raise ProviderFailedError(f"script has no photo_ok: {text[:200]}")
    if not data["photo_ok"]:
        return ScriptDraft(None, reject_reason(data.get("reject_reason")), False, cost_usd)
    if data.get("idea_ok") is False:
        return ScriptDraft(None, None, True, cost_usd)
    lines, bible, idea = data.get("lines"), data.get("story_bible"), data.get("idea")
    if not isinstance(lines, list) or len(lines) != parts:
        raise ProviderFailedError(f"expected {parts} lines: {text[:200]}")
    if not isinstance(bible, str) or not bible.strip() or not isinstance(idea, str):
        raise ProviderFailedError("script is missing the story bible or idea")
    clean_lines = tuple(str(line).strip() for line in lines)
    if not all(clean_lines):
        raise ProviderFailedError("script has an empty line")
    return ScriptDraft(Script(idea.strip(), clean_lines, bible.strip()), None, False, cost_usd)


def script_from_user(text: str, base: Script) -> Script:
    """The user's own wording replaces the lines; one non-empty line per part."""
    lines = tuple(line.strip() for line in text.strip().splitlines() if line.strip())
    if len(lines) != len(base.lines):
        raise ScriptError("wrong_parts")
    if any(len(line.split()) > MAX_WORDS_PER_LINE for line in lines):
        raise ScriptError("too_long")
    return Script(base.idea, lines, base.story_bible)


def speech_prompt(language: Language, line: str, story_bible: str) -> str:
    return (
        f"Vertical 9:16 selfie-style video. {story_bible} The person from the photo looks into "
        f"the camera and speaks naturally in {SPOKEN_LANGUAGE[language]} with native "
        f"pronunciation and accurate lip sync, saying exactly: «{line}». Natural hand gestures. "
        "Only this person speaks. No on-screen text, no subtitles, no background music."
    )


def continuation_prompt(language: Language, line: str, story_bible: str) -> str:
    return (
        "Continue the same shot: same person, place, clothing, lighting and voice. "
        + speech_prompt(language, line, story_bible)
    )
