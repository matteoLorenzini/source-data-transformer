"""Local entity extraction with GLiNER, in the same entity format as llm_extractor.

GLiNER finds the spans (people, places, organizations, job titles, publications) sentence by
sentence; this module cleans them and turns them into the entities extract_entities.py expects:

  person        {"type": "person", "value", "context", "relation"?}
                relation "teacher" for "under X", "supervised by X", "pupil of X";
                "mentor" for "his mentors X, Y, and Z" (every name of the list)
  place         {"type": "place", "value", "context"}
  organization  {"type": "organization", "value", "context"}
  role          {"type": "role", "value", "context", "from"?, "to"?, "place"?, "organization"?}
  work          {"type": "work", "value", "context", "from"?}

Clean-up on top of GLiNER:
  - pronouns ("he", "his") and possessives that belong to a place ("Tiberius" in
    "Tiberius's Villa") are not persons; the place is extended to "Tiberius's Villa in Sperlonga";
  - trailing generic words are cut from places ("Baiae excavations" -> "Baiae");
  - common job titles (Director, Professor, Archaeologist, ...) are added when GLiNER misses them;
  - quoted titles are works as a whole ("Odysseus: Archäologie des europäischen Mythos"); in a
    sentence with quoted titles only those are works; lowercase spans ("thesis") are not works;
  - sentences are not split at abbreviations ("vs.", "trans.", initials) or inside URLs.

Events are not produced here: detect_events() and fill_event_from_context() in extract_entities.py
find them in the text and complete them from these entities.

Install once:  pip install gliner sentencepiece protobuf   (pulls PyTorch; for CPU only, first:
               pip install torch --index-url https://download.pytorch.org/whl/cpu)
The model is downloaded from Hugging Face on first use and cached.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DEFAULT_MODEL = "urchade/gliner_multi-v2.1"  # multilingual; names in English, Italian, German texts
DEFAULT_THRESHOLD = 0.4

# GLiNER label -> entity type. GLiNER works best with plain-language labels.
LABELS = {
    "person": "person",
    "location": "place",
    "organization": "organization",
    "job title": "role",
    "publication": "work",
}

# ---------------------------------------------------------------- sentences

ABBREVIATIONS = {
    "vs", "e.g", "i.e", "cf", "ca", "c", "trans", "transl", "ed", "eds", "vol", "vols", "no", "nos",
    "dr", "prof", "st", "mr", "mrs", "fig", "figs", "pp", "p", "approx", "jr", "sr", "ital", "germ", "engl",
}


def sentences(text: str) -> list[str]:
    """Split text into sentences, keeping each one verbatim (callers strip the whitespace).

    A boundary is . ! or ? followed by whitespace and an uppercase letter, a quote or a bracket;
    not after an abbreviation or an initial, and never inside a URL ("https://archive.org").
    """

    out: list[str] = []
    start = 0
    for match in re.finditer(r"[.!?]+(?=\s|$)", text):
        before = re.search(r"([\w.]+)$", text[start:match.start()])
        token = before.group(1) if before else ""
        following = text[match.end():].lstrip()[:1]
        if token.rstrip(".").lower() in ABBREVIATIONS or re.fullmatch(r"[A-Z]", token):
            continue
        if following and not (following.isupper() or following.isdigit() or following in "\"“„«'‘("):
            continue
        out.append(text[start:match.end()])
        start = match.end()
    if text[start:].strip():
        out.append(text[start:])
    return out


# ---------------------------------------------------------------- patterns

# Date expressions after (or before) a role, tried in this order at each position.
DATES_RE = re.compile(
    r"(?P<range>\b(?:from\s+)?(?P<r1>\d{4}s?)\s*(?:-|–|—|to|until)\s*(?P<r2>\d{4}s?)\b)"
    r"|(?P<inuntil>\bin\s+(?P<i1>\d{4})\s*\(\s*until\s+(?P<i2>\d{4})\s*\))"
    r"|(?P<since>\b(?:from|since)\s+(?P<s1>\d{4}s?)\b)"
    r"|(?P<until>\buntil\s+(?P<u1>\d{4})\b)"
    r"|(?P<year>\b(?P<y1>\d{4}s?)\b)",
    re.I,
)
# Words right before a person that state how the person relates to the subject.
RELATION_CUES = [
    (re.compile(r"\b(?:under|supervis(?:ed|ion|or)\s+(?:by|of)?|pupil of|student of|teachers?)\s*$", re.I), "teacher"),
    (re.compile(r"\bmentors?\s*$", re.I), "mentor"),
    (re.compile(r"\b(?:with|together with|and his colleague|colleagues?)\s*$", re.I), "collaborator"),
]
LIST_GAP_RE = re.compile(r"^\s*,?\s*(?:and\s+)?$", re.I)  # "Matz, Herbig, and Langlotz"
PRONOUNS = {"he", "she", "him", "her", "his", "hers", "they", "them", "their", "i", "we", "it", "who", "whom"}
POSSESSIVE_NEXT_RE = re.compile(r"^['’]s?\s+[A-Z]")      # "Tiberius" + "'s Villa"
POSSESSIVE_BEFORE_RE = re.compile(r"([A-Z][\w-]*['’]s?\s+)$")  # "Tiberius's " + "Villa"
PLACE_TRAILING_RE = re.compile(r"\s+(?:excavations?|site|sites|area|region|campaigns?)$", re.I)
# Organization followed by its location: "German Archaeological Institute in Rome".
ORG_PLACE_GAP_RE = re.compile(r"^\s*(?:in|at|,)\s*$", re.I)
# Job titles added when GLiNER misses them (longest first).
TITLE_RE = re.compile(
    r"\b(?:scientific director|general director|director general|director|vice[- ]director|professor emeritus|"
    r"full professor|associate professor|assistant professor|professor|lecturer|reader|privatdozent|"
    r"research assistant|assistant|curator|conservator|researcher|research fellow|fellow|president|"
    r"vice[- ]president|superintendent|soprintendente|inspector|ispettore|archa?eologist|art historian|"
    r"epigraphist|architect|restorer|librarian|archivist|dean|rector)\b",
    re.I,
)
QUOTED_RE = re.compile(r"[\"“„«]([^\"“”„«»]{3,}?)[\"”»“]")


@dataclass
class Span:
    start: int
    end: int
    text: str
    kind: str  # entity type after LABELS
    score: float = 1.0


def _dates(text: str) -> tuple[int, dict] | None:
    """First date expression in text: (position, {"from": ..., "to": ...})."""

    match = DATES_RE.search(text)
    if not match:
        return None
    if match.group("range"):
        found = {"from": match.group("r1"), "to": match.group("r2")}
    elif match.group("inuntil"):
        found = {"from": match.group("i1"), "to": match.group("i2")}
    elif match.group("since"):
        found = {"from": match.group("s1")}
    elif match.group("until"):
        found = {"to": match.group("u1")}
    else:
        found = {"from": match.group("y1")}
    return match.start(), found


def _overlaps(a: Span, spans: list[Span]) -> bool:
    return any(a.start < b.end and b.start < a.end for b in spans)


def _clean(text: str) -> str:
    return text.strip(" ,;:()\"“”„«»'").strip()


def _work_year(sentence: str, start: int, end: int) -> str | None:
    """Year of a work: '(1962)' right after it, or inside the parentheses that contain it."""

    after = sentence[end:]
    direct = re.match(r"[\"”»]?\s*\(\s*(\d{4})\b", after)
    if direct:
        return direct.group(1)
    if sentence[:start].count("(") > sentence[:start].count(")"):
        inside = after.split(")", 1)[0]
        year = re.search(r"\b(\d{4})\b", inside)
        if year:
            return year.group(1)
    years = set(re.findall(r"\b(\d{4})\b", re.sub(r"https?://\S+", "", sentence)))
    if len(years) == 1:  # "In 1962, he completed his habilitation ... ("Studien zur roemischen Grabkunst")"
        return years.pop()
    return None


class GlinerExtractor:
    def __init__(self, model_name: str = DEFAULT_MODEL, threshold: float = DEFAULT_THRESHOLD, model=None) -> None:
        if model is None:
            try:
                from gliner import GLiNER
            except ImportError as exc:  # pragma: no cover - depends on the environment
                raise SystemExit("GLiNER is not installed: pip install gliner sentencepiece protobuf") from exc
            print(f"Loading GLiNER model {model_name}...")
            model = GLiNER.from_pretrained(model_name)
        self.model = model
        self.name = f"gliner:{model_name}"
        self.threshold = threshold

    # ------------------------------------------------------------ spans

    def _spans(self, sentence: str) -> list[Span]:
        raw = self.model.predict_entities(sentence, list(LABELS), threshold=self.threshold)
        candidates: list[Span] = []
        for ent in raw:
            kind = LABELS.get(ent["label"], "")
            span = Span(ent["start"], ent["end"], sentence[ent["start"]:ent["end"]], kind, ent.get("score", 0.5))
            if not kind or not _clean(span.text):
                continue
            if kind == "person":
                if span.text.strip().lower() in PRONOUNS or not span.text.strip()[:1].isupper():
                    continue
                if POSSESSIVE_NEXT_RE.match(sentence[span.end:]):
                    continue  # "Tiberius" of "Tiberius's Villa" is part of a place name
            if kind == "place":
                owner = POSSESSIVE_BEFORE_RE.search(sentence[:span.start])
                if owner:  # "Villa in Sperlonga" -> "Tiberius's Villa in Sperlonga"
                    span.start = owner.start(1)
                trailing = PLACE_TRAILING_RE.search(sentence[span.start:span.end])
                if trailing:  # "Baiae excavations" -> "Baiae"
                    span.end = span.start + trailing.start()
                span.text = sentence[span.start:span.end]
            candidates.append(span)

        # Quoted titles are works as a whole and win over GLiNER spans inside them.
        quoted = [Span(m.start(1), m.end(1), m.group(1), "work", 2.0) for m in QUOTED_RE.finditer(sentence)]
        if quoted:
            candidates = [c for c in candidates if c.kind != "work"]
        candidates += quoted

        spans: list[Span] = []
        for span in sorted(candidates, key=lambda s: (-s.score, -(s.end - s.start))):
            if not _overlaps(span, spans):
                spans.append(span)
        for match in TITLE_RE.finditer(sentence):  # titles GLiNER missed
            span = Span(match.start(), match.end(), match.group(), "role", 0.0)
            if not _overlaps(span, spans):
                spans.append(span)
        return sorted(spans, key=lambda s: s.start)

    # ------------------------------------------------------------ assembly

    def _roles(self, sentence: str, spans: list[Span]) -> list[dict]:
        roles = [s for s in spans if s.kind == "role"]
        places = [s for s in spans if s.kind in ("place", "organization")]
        out: list[dict] = []
        for i, role in enumerate(roles):
            seg_end = roles[i + 1].start if i + 1 < len(roles) else len(sentence)
            prev_end = roles[i - 1].end if i else 0

            # Institutions after the role, grouped: organization + "in" + place = one group.
            groups: list[list[Span]] = []
            for span in (p for p in places if role.end <= p.start < seg_end):
                last = groups[-1][-1] if groups else None
                if (
                    last is not None
                    and last.kind == "organization"
                    and span.kind == "place"
                    and ORG_PLACE_GAP_RE.match(sentence[last.end:span.start])
                ):
                    groups[-1].append(span)
                else:
                    groups.append([span])

            value = _clean(role.text)
            value = value[:1].upper() + value[1:]
            base = {"type": "role", "value": value, "context": sentence.strip()}

            def dated(start: int, end: int) -> dict:
                found = _dates(sentence[start:end])
                return found[1] if found else {}

            if not groups:
                out.append({**base, **(dated(role.end, seg_end) or dated(prev_end, role.start))})
                continue
            for g, group in enumerate(groups):
                next_start = groups[g + 1][0].start if g + 1 < len(groups) else seg_end
                dates = dated(group[-1].end, next_start)
                if not dates and len(groups) == 1:
                    dates = dated(role.end, seg_end) or dated(prev_end, role.start)
                entity = {**base, **dates}
                for span in group:
                    entity.setdefault(span.kind, _clean(span.text))
                out.append(entity)
        return out

    def _people(self, sentence: str, spans: list[Span], subject_tokens: set[str]) -> list[dict]:
        people = [s for s in spans if s.kind == "person"]
        out: list[dict] = []
        relation = None
        for i, span in enumerate(people):
            value = _clean(span.text)
            before = sentence[: span.start]
            cue = next((rel for pattern, rel in RELATION_CUES if pattern.search(before)), None)
            if cue:
                relation = cue
            elif not (i and relation and LIST_GAP_RE.match(sentence[people[i - 1].end:span.start])):
                relation = None  # the list "mentors X, Y, and Z" ended
            if {t.lower() for t in re.findall(r"\w+", value)} & subject_tokens:
                continue  # the subject himself
            entity = {"type": "person", "value": value, "context": sentence.strip()}
            if relation:
                entity["relation"] = relation
            out.append(entity)
        return out

    def extract(self, field: str, subject: str, text: str) -> list[dict]:
        subject_tokens = {t.lower() for t in re.findall(r"\w+", subject) if len(t) > 2}
        entities: list[dict] = []
        seen: set[tuple[str, str, str]] = set()

        def add(entity: dict) -> None:
            key = (entity["type"], entity["value"].lower(), entity["context"])
            if key not in seen:
                seen.add(key)
                entities.append(entity)

        for sentence in sentences(text):
            if not sentence.strip():
                continue
            spans = self._spans(sentence)
            context = sentence.strip()
            for person in self._people(sentence, spans, subject_tokens):
                add(person)
            for span in spans:
                value = _clean(span.text)
                if span.kind in ("place", "organization"):
                    add({"type": span.kind, "value": value, "context": context})
                elif span.kind == "work":
                    if not value[:1].isupper() and not span.score > 1:
                        # "new edition of the Alexander Mosaic" -> "Alexander Mosaic"; "thesis" -> dropped
                        capital = re.search(r"\b[A-Z]", value)
                        if not capital:
                            continue
                        value = value[capital.start():]
                    entity = {"type": "work", "value": value, "context": context}
                    year = _work_year(sentence, span.start, span.end)
                    if year:
                        entity["from"] = year
                    add(entity)
            for role in self._roles(sentence, spans):
                entities.append(role)
        return entities