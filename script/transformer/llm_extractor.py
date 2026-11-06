"""Entity extraction through an OpenAI-compatible chat completions endpoint (local Ollama by default)."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests

DEFAULT_BASE_URL = "http://localhost:11434/v1"
DEFAULT_MODEL = "qwen2.5:7b"

SYSTEM_PROMPT = """You extract named entities from free text about a scholar, for a later CIDOC-CRM mapping.
Return only a JSON object: {"entities": [ ... ]}.

Each entity has:
- "type": one of person, place, organization, role, work, event.
- "value": the entity as written in the text (original language and spelling). For an event, a short neutral label such as "Graduation".
- "context": the exact fragment of the text, usually one sentence, in which the entity appears. It must be copied character for character.
- optional "from" / "to": ISO dates (YYYY, YYYY-MM or YYYY-MM-DD) bounding the entity in time. A decade such as "1970s" is 1970 to 1979. "from 1978" has only "from"; "until 1995" has only "to"; a single year sets both.
- optional "place" / "organization": the place or organization tied to a role or event, as written in the text.
- optional "url": only for a work, a URL the text gives for it.

Types:
- person: other persons named in the text, not the subject.
- place: cities, regions and sites, even when they follow "at" or "in" ("professor at Bochum" names a place).
- organization: only named institutions such as universities, institutes and services.
- role: a job title, position or occupation held by the subject; add organization, place, from and to when the text states them.
- work: titled publications or works; "value" is the title, "from" the year of publication when given.
- event: a discrete happening such as a graduation, appointment or excavation campaign.

Rules: extract only what the text states and never add outside knowledge. Emit one entity per mention; do not merge mentions.
Never emit a date as an entity of its own: dates only appear as "from" / "to" of a role, event or work.
A text often lists several roles. Emit one separate role entity for each position, never one entity for the whole list:
- a role shared by several places or periods, such as "professor at A (1950-1960) and B (1961-1970)", is two role entities, one for A and one for B;
- a date in parentheses belongs to the role right before it; a role with no date has no "from" or "to";
- "and then", "later" and "until" start a new role;
- "value" is only the role title; put the place or organization in "place" or "organization", never in "value".

Example text: "Painter and lecturer at Padua (1950-1960) and Siena (1961-1970), then curator of the Uffizi Gallery in Florence (1971-1980)."
Example roles:
{"type": "role", "value": "Painter", "context": "Painter and lecturer at Padua (1950-1960) and Siena (1961-1970), then curator of the Uffizi Gallery in Florence (1971-1980)."},
{"type": "role", "value": "Lecturer", "place": "Padua", "from": "1950", "to": "1960", "context": "Painter and lecturer at Padua (1950-1960)"},
{"type": "role", "value": "Lecturer", "place": "Siena", "from": "1961", "to": "1970", "context": "Siena (1961-1970)"},
{"type": "role", "value": "Curator", "organization": "Uffizi Gallery", "place": "Florence", "from": "1971", "to": "1980", "context": "curator of the Uffizi Gallery in Florence (1971-1980)"}

If nothing applies, return {"entities": []}."""


@dataclass(frozen=True)
class LlmConfig:
    api_key: str | None
    base_url: str
    model: str


def config_from_env(base_url: str | None, model: str | None) -> LlmConfig:
    """Build the client configuration from CLI values, falling back to environment variables."""

    return LlmConfig(
        api_key=os.getenv("LLM_API_KEY") or os.getenv("OLLAMA_API_KEY"),
        base_url=(base_url or os.getenv("LLM_BASE_URL") or DEFAULT_BASE_URL).rstrip("/"),
        model=model or os.getenv("LLM_MODEL") or DEFAULT_MODEL,
    )


def extract_entities(config: LlmConfig, field: str, subject: str, text: str, attempts: int = 3) -> list:
    """Ask the model for the entities in one cell and return the raw, unvalidated list."""

    payload = {
        "model": config.model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Subject of the record: {subject or 'unknown'}\nField: {field}\n\nText:\n{text}",
            },
        ],
    }
    headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}

    for attempt in range(attempts):
        # Generous timeout: a 7B model on CPU can take minutes for a long biography.
        try:
            response = requests.post(
                f"{config.base_url}/chat/completions", headers=headers, json=payload, timeout=900
            )
        except requests.ConnectionError as exc:
            raise RuntimeError(
                f"Cannot reach {config.base_url}. Start Ollama and run: ollama pull {config.model}"
            ) from exc
        if response.status_code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
            time.sleep(2 ** (attempt + 1))
            continue
        response.raise_for_status()
        break

    try:
        content = response.json()["choices"][0]["message"]["content"]
        entities = json.loads(content)["entities"]
    except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Unexpected model response for field {field}: {exc}") from exc
    return entities
