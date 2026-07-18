"""
Street extraction — pull a street name out of Bazoš listing text.

Bazoš provides only town + postal code as structured location, but ~15-30% of
titles/descriptions mention the street in free text ("Fibichova ul.",
"ul. Moyzesova 46", "na Sibírskej ulici", "na ulici Stará Baštová"). This
module finds such mentions with conservative regexes: better to return nothing
than a wrong street, since the result feeds map pins.

Slovak declension: in "na Sibírskej ulici" the name is locative; street
registries (and Nominatim) hold the nominative "Sibírska". We emit *candidate*
spellings (rhythmic law makes -skej → both -ská and -ska possible) and let the
geocoder try them in order. Names written after the word ("ulica Boženy
Nemcovej") are official genitive names and are kept verbatim.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A street name: capitalised word (Unicode letters, incl. "T.G." style
# initials), optionally followed by more capitalised words.
_NAME = r"[A-ZÀ-Ž][\w.\-À-ž]*(?:\s+[A-ZÀ-Ž][\w.\-À-ž]*)*"
_NUMBER = r"(?:\s+(\d{1,4}(?:/\d{1,4})?[a-zA-Z]?))?"

# Order matters: the "ul./ulica <Name>" prefix form is checked first because
# the name is already in its official (nominative/genitive) spelling.
_PREFIX_RE = re.compile(
    rf"(?:\b[Uu]l\.|\b[Uu]lic[aiou])\s+({_NAME}){_NUMBER}"
)
_SUFFIX_RE = re.compile(
    rf"\b({_NAME})\s+(?:ul\.|ulic[aiue]\b)", re.UNICODE
)
_SQUARE_RE = re.compile(
    rf"(?:\b[Nn]ám\.|\b[Nn]ámestie|\b[Nn]ámestí)\s+({_NAME}){_NUMBER}"
)

# Words that regularly precede "ulici/ulica" without being part of the name.
_STOPWORDS = {"na", "pri", "v", "vo", "byt", "izbový", "izb", "novej", "tejto"}


@dataclass
class StreetMention:
    raw: str                                  # as written in the text
    candidates: list[str] = field(default_factory=list)  # spellings to geocode, best first
    house_number: str | None = None


_INITIALS = re.compile(r"(?:[A-ZÀ-Ž]\.)+")


def _clean(name: str) -> str:
    """Trim punctuation and stop the capture at sentence/noise boundaries.

    The regex happily continues across ". " and into ALL-CAPS shouting
    ("Gudernova. ZARIADENÝ. LOGGIA") — keep words only up to the first
    sentence end (a dot that isn't part of initials like "T.G.") and drop
    trailing all-caps words.
    """
    out: list[str] = []
    for i, word in enumerate(name.strip().split()):
        ends_sentence = word.endswith(".") and not _INITIALS.fullmatch(word)
        if i > 0 and len(word) >= 3 and word.isupper():
            break
        out.append(word.rstrip(".,:;–-") if ends_sentence else word)
        if ends_sentence:
            break
    return re.sub(r"[\s,.:;–-]+$", "", " ".join(out))


def _drop_leading_stopwords(name: str) -> str:
    words = name.split()
    while words and words[0].lower() in _STOPWORDS:
        words.pop(0)
    return " ".join(words)


def _nominative_candidates(name: str) -> list[str]:
    """Candidate nominative spellings for a (possibly locative) name."""
    def convert(word: str) -> list[str]:
        lower = word.lower()
        if lower.endswith("skej") or lower.endswith("ckej"):
            stem = word[:-2]                      # Sibírskej → Sibírsk
            return [stem + "á", stem + "a"]       # -ská / -ska (rhythmic law)
        if lower.endswith("ovej"):
            return [word[:-2] + "a"]              # Gudernovej → Gudernova
        if lower.endswith("nej"):
            return [word[:-2] + "á", word[:-2] + "a"]
        return [word]

    words = name.split()
    variants: list[list[str]] = [convert(w) for w in words]
    # Cartesian product would explode only for absurd names; cap at 4.
    out: list[str] = []
    def build(i: int, acc: list[str]) -> None:
        if len(out) >= 4:
            return
        if i == len(variants):
            out.append(" ".join(acc))
            return
        for v in variants[i]:
            build(i + 1, acc + [v])
    build(0, [])
    if name not in out:
        out.append(name)  # always fall back to the raw form
    return out


def extract_street(*texts: str | None) -> StreetMention | None:
    """
    Find the first street mention across the given texts (title first).
    Returns None when nothing trustworthy is found.
    """
    for text in texts:
        if not text:
            continue
        m = _PREFIX_RE.search(text)
        if m:
            name = _clean(m.group(1))
            if len(name) >= 3:
                return StreetMention(raw=name, candidates=[name], house_number=m.group(2))
        m = _SUFFIX_RE.search(text)
        if m:
            name = _drop_leading_stopwords(_clean(m.group(1)))
            if len(name) >= 3:
                return StreetMention(raw=name, candidates=_nominative_candidates(name))
        m = _SQUARE_RE.search(text)
        if m:
            name = _clean(m.group(1))
            if len(name) >= 3:
                return StreetMention(
                    raw=f"námestie {name}",
                    candidates=[f"námestie {name}", name],
                    house_number=m.group(2),
                )
    return None
