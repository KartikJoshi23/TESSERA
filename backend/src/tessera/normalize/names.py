"""Entity-name normalisation for matching, in English and Arabic.

A name such as ``"Lumen Crest Capital (DIFC) Limited"`` becomes the matching key
``"lumen crest capital"``, with legal form ``LTD`` and zone tag ``DIFC`` kept separately. Arabic
letter variants, diacritics and tatweel are folded, so spelling differences do not block a match.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

_ARABIC_MARKS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
_ARABIC_FOLD = str.maketrans(
    {
        "أ": "ا",  # alef with hamza above -> alef
        "إ": "ا",  # alef with hamza below -> alef
        "آ": "ا",  # alef with madda -> alef
        "ٱ": "ا",  # alef wasla -> alef
        "ى": "ي",  # alef maqsura -> ya
        "ة": "ه",  # ta marbuta -> ha
        "ؤ": "و",  # waw with hamza -> waw
        "ئ": "ي",  # ya with hamza -> ya
        "ـ": None,  # tatweel
        **{chr(0x0660 + i): str(i) for i in range(10)},  # Arabic-Indic digits
        **{chr(0x06F0 + i): str(i) for i in range(10)},  # Extended Arabic-Indic digits
    }
)
_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)

# Legal-form phrases, as token tuples after normalize_text() (punctuation becomes spaces).
_LEGAL_FORMS: dict[tuple[str, ...], str] = {
    ("limited", "liability", "company"): "LLC",
    ("l", "l", "c"): "LLC",
    ("llc",): "LLC",
    ("fz", "llc"): "FZ-LLC",
    ("fzllc",): "FZ-LLC",
    ("fz", "co"): "FZCO",
    ("fzco",): "FZCO",
    ("f", "z", "e"): "FZE",
    ("fze",): "FZE",
    ("dmcc",): "DMCC",
    ("p", "j", "s", "c"): "PJSC",
    ("pjsc",): "PJSC",
    ("psc",): "PSC",
    ("plc",): "PLC",
    ("ltd",): "LTD",
    ("limited",): "LTD",
    ("inc",): "INC",
    ("incorporated",): "INC",
    ("corp",): "CORP",
    ("corporation",): "CORP",
    ("branch",): "BRANCH",
    ("establishment",): "EST",
    ("ذ", "م", "م"): "LLC",  # ذ.م.م (limited liability company)
    ("ش", "ذ", "م", "م"): "LLC",
    ("ش", "م", "ع"): "PJSC",  # ش.م.ع (public joint stock company)
    ("ش", "م", "خ"): "PRJSC",  # ش.م.خ (private joint stock company)
}
_MAX_FORM_TOKENS = max(len(key) for key in _LEGAL_FORMS)

_ZONE_TAGS = {
    "difc": "DIFC",
    "adgm": "ADGM",
    "dafza": "DAFZA",
    "jafza": "JAFZA",
    "dso": "DSO",
    "dwtc": "DWTC",
    "rakez": "RAKEZ",
    "ifza": "IFZA",
    "shams": "SHAMS",
}
_STOPWORDS = frozenset({"the", "and"})


def fold_arabic(text: str) -> str:
    """Remove Arabic diacritics and tatweel, and fold common letter variants."""
    return _ARABIC_MARKS.sub("", text).translate(_ARABIC_FOLD)


def normalize_text(text: str) -> str:
    """NFKC, case-fold, Arabic folding, ``&`` → ``and``, punctuation → spaces."""
    folded = fold_arabic(unicodedata.normalize("NFKC", text).casefold())
    folded = _NON_WORD.sub(" ", folded.replace("&", " and ")).replace("_", " ")
    return " ".join(folded.split())


@dataclass(frozen=True)
class NormalizedName:
    original: str
    #: Matching key: the distinctive tokens, without legal forms, zone tags or stopwords.
    key: str
    core_tokens: tuple[str, ...]
    legal_forms: tuple[str, ...]
    zone_tags: tuple[str, ...]


def normalize_name(name: str) -> NormalizedName:
    tokens = normalize_text(name).split()
    core: list[str] = []
    forms: set[str] = set()
    zones: set[str] = set()
    i = 0
    while i < len(tokens):
        for size in range(min(_MAX_FORM_TOKENS, len(tokens) - i), 0, -1):
            form = _LEGAL_FORMS.get(tuple(tokens[i : i + size]))
            if form:
                forms.add(form)
                i += size
                break
        else:
            token = tokens[i]
            if token in _ZONE_TAGS:
                zones.add(_ZONE_TAGS[token])
            elif token not in _STOPWORDS:
                core.append(token)
            i += 1
    if not core:  # a name made only of legal-form words: keep what there is
        core = [t for t in tokens if t not in _STOPWORDS]
    return NormalizedName(
        original=name,
        key=" ".join(core),
        core_tokens=tuple(core),
        legal_forms=tuple(sorted(forms)),
        zone_tags=tuple(sorted(zones)),
    )
