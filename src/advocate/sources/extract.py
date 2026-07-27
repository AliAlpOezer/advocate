"""JD -> normalized skills.

We learned the hard way (in the TS spike) that free gpt-oss routes don't support
schema-constrained structured output — providers ignore the schema and return
reasoning-only, empty responses. So we prompt for JSON and validate with Pydantic
ourselves. Works on any provider; Claude produces clean JSON, free routes are flaky
so we retry, then return [] for that posting rather than aborting the run.
"""

from __future__ import annotations

import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from .llm import build_system_prefix
from .skills import CANONICAL_SKILLS, ExtractedSkill, SkillExtraction

# Stable across every posting -> the cache breakpoint on Anthropic.
_SYSTEM_PREFIX = (
    "You extract the technical skills, tools, and frameworks a job posting demands.\n"
    "Respond with ONLY a JSON object (no prose, no markdown) shaped exactly like:\n"
    '{"skills":[{"canonical":"...","raw":"...","required":true}]}\n'
    f"Each \"canonical\" MUST be one of: {', '.join(CANONICAL_SKILLS)}. "
    'Use "other" only if nothing fits. "raw" is the exact phrase from the posting. '
    'Set "required":true only for hard requirements.'
)


def _parse_json_object(text: str) -> object | None:
    body = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    body_text = body.group(1) if body else text
    start, end = body_text.find("{"), body_text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(body_text[start : end + 1])
    except json.JSONDecodeError:
        return None


def extract_skills(llm: BaseChatModel, provider: str, title: str, jd: str) -> list[ExtractedSkill]:
    if not jd.strip():
        return []
    messages = [
        build_system_prefix(provider, _SYSTEM_PREFIX),
        HumanMessage(content=f"TITLE: {title}\n\nPOSTING:\n{jd}"),
    ]
    for attempt in range(1, 4):
        try:
            text = str(llm.invoke(messages).content)
        except Exception as err:  # noqa: BLE001 — free routes throw transient errors
            if attempt == 3:
                print(f"  ⚠️  skipped \"{title}\" — LLM error after {attempt} tries: {err}")
                return []
            continue
        parsed = _parse_json_object(text)
        if parsed is not None:
            try:
                return SkillExtraction.model_validate(parsed).skills
            except ValidationError:
                pass
    print(f'  ⚠️  skipped "{title}" — no valid skills JSON after 3 tries')
    return []
