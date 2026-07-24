from __future__ import annotations

import re
import unicodedata

_SPACES = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


def normalize_lookup(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.strip().casefold())
    unmarked = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    separated = _NON_WORD.sub(" ", unmarked.replace("&", " and "))
    return _SPACES.sub(" ", separated).strip()


def is_latin_output_candidate(value: str) -> bool:
    letters = [character for character in value if character.isalpha()]
    if not letters:
        return False
    latin_letters = sum(
        "LATIN" in unicodedata.name(character, "") for character in letters
    )
    return latin_letters / len(letters) >= 0.8
