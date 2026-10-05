"""Text hygiene plus lightweight Albanian/English identification.

INSTAT tables are bilingual almost everywhere: title rows, stacked header rows, single cells such as
``Gjithsej/Total`` or ``Përqindja e mbulimit\\nCoverage ratio``. Telling the two languages apart is the
key to pairing them up.
"""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)
_WS = re.compile(r"[ \t\f\v]+")

# Words that (almost) only occur in one language. Weighted: strong words count double.
_SQ_STRONG = frozenset(
    ["gjithsej", "meshkuj", "femra", "vjeç", "vjet", "mosha", "grupmosha", "viti", "tremujori", "tremujor", "muaji", "totali", "shqipëria", "qarku", "qarqet", "bashkia", "numri", "aktiviteti", "ekonomik", "ekonomike", "çmimet", "çmimi", "indeksi", "popullsia", "punësimi", "papunësia", "tregtia", "eksporte", "importe", "eksporti", "importi", "bilanci", "përqindja", "mbulimit", "grupet", "peshat", "kodi", "shënim", "burimi", "vlera", "konsumi", "prodhimi", "brendshëm", "bruto", "rritja", "reale", "vjetore", "mujore", "mesatare", "paga", "pagë", "punonjës", "punësuar", "papunë", "sektori", "publik", "privat", "shtetet", "vendet", "sipas", "ndërmjetës", "taksa", "neto", "mbi", "produktet", "kapaku", "përmbajtja", "tabela", "tab", "publikuar", "përditësimi", "lindjet", "vdekjet", "martesat", "shkurorzimet", "banorë", "shtëpiake", "familje", "familjet", "arsimi", "shëndetësia", "transporti", "turizmi", "energjia", "ndërtimi", "bujqësia", "industria", "shërbimet", "blerje", "shitje", "shitjet", "investime", "investimet", "lekë", "mijë", "milion", "miliardë", "ushqime", "pije", "veshje", "këpucë", "banesa", "uji", "mobilje", "komunikimi", "rekreacion", "kulturë", "restorante", "hotele", "akomodimi", "mallra", "tjera", "jetëgjatësia", "foshnjore", "femijëve", "fëmijëve", "nëntor", "dhjetor", "janar", "shkurt", "mars", "prill", "maj", "qershor", "korrik", "gusht", "shtator", "tetor", "parë", "dytë", "tretë", "katërt", "gjysëm", "finale", "mëparshëm", "korente", "konstante", "kujdes", "personal", "jo", "alkoolike", "alkoolike", "duhan", "ndryshimet", "ndryshimi", "vjetor", "mujor"]
)
_SQ_WEAK = frozenset(["dhe", "të", "e", "në", "për", "nga", "me", "i", "së", "një", "ose", "pa", "mbi"])
_EN_STRONG = frozenset(
    ["total", "male", "males", "female", "females", "years", "age", "group", "groups", "year", "quarter", "month", "index", "rate", "number", "population", "employment", "unemployment", "trade", "exports", "imports", "export", "import", "balance", "coverage", "ratio", "prices", "price", "consumer", "gross", "domestic", "product", "products", "value", "added", "growth", "real", "annual", "monthly", "average", "wage", "wages", "sector", "public", "private", "source", "note", "notes", "code", "weights", "by", "of", "the", "and", "for", "from", "with", "in", "to", "households", "household", "economic", "activity", "activities", "country", "countries", "region", "regions", "county", "semi-final", "final", "provisional", "current", "constant", "previous", "change", "changes", "percent", "percentage", "thousand", "million", "billion", "persons", "people", "both", "sexes", "urban", "rural", "health", "education", "transport", "tourism", "energy", "construction", "agriculture", "industry", "services", "arrivals", "nights", "births", "deaths", "marriages", "life", "expectancy", "infant", "mortality", "inactive", "labour", "force", "participation", "summary", "table", "tables"]
)
_EN_WEAK = frozenset(["a", "an", "on", "at", "as"])

# Census vocabulary. Counted for the token-level bilingual split and for language detection of whole lines.
_SQ_STRONG |= frozenset(
    ["regjistrimi", "regjistrimit", "shqipëri", "banuese", "banues", "banesat", "banesave", "ndërtesa", "ndërtesat", "ndërtesave", "njësitë", "njësi", "njësia", "familjare", "familjar", "familja", "shtëpiakë", "gjinia", "gjinisë", "gjini", "moshës", "moshat", "grupmoshat", "grupmoshave", "zona", "zonat", "urbane", "rurale", "qytetare", "fshatare", "vendlindja", "lindjes", "lindja", "vendbanimi", "vendbanim", "vendbanimit", "zakonshëm", "zakonshme", "qarkut", "bashkitë", "bashkisë", "komuna", "fshati", "fshatrat", "vendi", "shtetësia", "kombësia", "gjuha", "amtare", "feja", "besimi", "arsimim", "arsimimi", "shkalla", "niveli", "statusi", "statusit", "punësimit", "inaktiv", "martuar", "martuara", "pamartuar", "pamartuara", "divorcuar", "vejusha", "gjendja", "civile", "bashkëjetues", "fëmijë", "lindur", "jetuar", "banojnë", "banor", "mesatar", "madhësia", "përbërja", "përbërje", "struktura", "strukturë", "ndarja", "shpërndarja", "dhoma", "dhomave", "dhomë", "sipërfaqja", "ngrohja", "ujësjellës", "kanalizime", "pajisje", "pajisjet", "afatgjata", "pronësia", "pronar", "qiraxhi", "qira", "lloji", "llojet", "tipi", "ndërtimit", "periudha", "periudhës", "para", "pas", "gjatë", "deri", "lart", "vjeçar", "vjeçare", "kryefamiljar", "kryefamiljare", "personit", "referencës", "emigrantë", "emigrim", "imigrim", "brendshme", "jashtme", "migrimi", "migrantët", "shkolla", "shkollë", "nxënës", "studentë", "paaftësi", "paaftësia", "vështirësi", "aftësi", "lëvizje", "pushtimi", "pushuar", "pensionist", "shtëpi", "sasia", "sasi", "fshat", "qytet", "beqar", "beqare", "ndarë"]
)
_EN_STRONG |= frozenset(
    ["census", "resident", "usually", "dwellings", "dwelling", "housing", "buildings", "building", "collective", "institutional", "occupied", "vacant", "seasonal", "occupancy", "tenure", "owner", "owned", "rented", "rent", "rooms", "room", "floor", "water", "supply", "sewage", "heating", "electricity", "appliances", "equipment", "television", "refrigerator", "washing", "dishwasher", "computer", "born", "birth", "abroad", "foreign", "place", "prefecture", "municipality", "municipalities", "village", "villages", "settlement", "area", "areas", "sex", "old", "older", "over", "under", "below", "up", "marital", "status", "single", "married", "widowed", "divorced", "cohabiting", "educational", "attainment", "level", "primary", "secondary", "tertiary", "higher", "university", "illiterate", "literate", "literacy", "ethnicity", "ethnic", "nationality", "citizenship", "language", "mother", "tongue", "religion", "religious", "employed", "unemployed", "occupation", "main", "working", "students", "pupils", "retired", "disabled", "disability", "difficulty", "difficulties", "migration", "migrants", "emigrants", "immigrants", "internal", "external", "moved", "residence", "usual", "size", "median", "other", "unknown", "stated", "reported", "declared", "albania", "reference", "person", "head"]
)

_TOKEN = re.compile(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", re.UNICODE)
_GAP = re.compile(r"(?<=\S)[ \t]{3,}(?=\S)")
_EN_SUFFIX = re.compile(r"(?:tion|sion|ing|ous|ity|ical|ness|ship|able)$")
_SQ_SUFFIX = re.compile(r"(?:uese|imet|imit|isë|ërve|ëve|shme)$")


def clean_text(value: object, *, keep_newlines: bool = False) -> str:
    """NFC-normalise, drop zero-width characters and collapse whitespace. ``None`` becomes ``''``.

    With ``keep_newlines`` line breaks survive, and so do the long runs of spaces INSTAT uses to line up the Albanian
    and English halves of one label (``'Mosha            Age'``): three or more spaces inside a line are a break too."""
    if value is None:
        return ""
    s = unicodedata.normalize("NFC", str(value)).translate(_ZERO_WIDTH)
    s = s.replace("\xa0", " ").replace("\u2007", " ").replace("\u202f", " ")
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if keep_newlines:
        s = _GAP.sub("\n", s)
        lines = [_WS.sub(" ", ln).strip() for ln in s.split("\n")]
        return "\n".join(ln for ln in lines if ln)
    return _WS.sub(" ", s.replace("\n", " ")).strip()


def fold(text: str) -> str:
    """Lower-case and strip diacritics (``Tiranë`` -> ``tirane``) for matching."""
    s = unicodedata.normalize("NFKD", clean_text(text).lower())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


_KEEP_UPPER = frozenset(
    ["GDP", "NACE", "CPI", "HICP", "LFS", "ALL", "EUR", "USD", "EU", "ICT", "PPP", "VAT", "COICOP", "NVE", "ISCO", "ISCED", "SDG", "INSTAT", "PBB", "ICK", "HS", "SITC", "CEFTA", "UN", "UK", "USA"])


def sentence_case(text: str) -> str:
    """``'GROSS DOMESTIC PRODUCT BY ECONOMIC ACTIVITY'`` -> ``'Gross domestic product by economic activity'``.

    Only touches all-capitals text (common in INSTAT sheet titles) and keeps well-known acronyms."""
    s = clean_text(text)
    letters = [c for c in s if c.isalpha()]
    if len(letters) < 6 or not all(c.isupper() for c in letters):
        return s
    words = []
    for w in s.lower().split(" "):
        bare = re.sub(r"\W+", "", w).upper()
        words.append(w.upper() if bare in _KEEP_UPPER else w)
    out = " ".join(words)
    return out[:1].upper() + out[1:]


def strip_leading_marker(text: str) -> str:
    """``'* Popullsia më 1 janar'`` -> ``'Popullsia më 1 janar'``."""
    return re.sub(r"^\s*[*•·]+\s*", "", clean_text(text))


def language_scores(text: str) -> tuple[float, float]:
    """(Albanian score, English score) for a piece of text."""
    s = clean_text(text)
    sq = 2.0 if re.search(r"[ëËçÇ]", s) else 0.0
    en = 0.0
    for tok in _TOKEN.findall(s.lower()):
        if tok in _SQ_STRONG:
            sq += 2
        elif tok in _SQ_WEAK:
            sq += 0.5
        if tok in _EN_STRONG:
            en += 2
        elif tok in _EN_WEAK:
            en += 0.5
    return sq, en


def detect_language(text: str) -> str:
    """``'sq'``, ``'en'`` or ``'unk'`` (too short / no evidence)."""
    sq, en = language_scores(text)
    if sq == en or max(sq, en) < 1:
        return "unk"
    return "sq" if sq > en else "en"


_SPLITTERS = (
    re.compile(r"\s*\n\s*"),
    re.compile(r"\s+/\s+"),
    re.compile(r"(?<=[^\W\d_])/(?=\s*[^\W\d_])"),  # letter/letter, e.g. Gjithsej/Total
    re.compile(r"\s+\|\s+"),
    re.compile(r"\s+[-–—]\s+"),  # "Gjinia - Sex": only taken when the halves are demonstrably Albanian and English
)

_EDGE_PUNCT = re.compile(r"^[^\w]+|[^\w]+$")


def _token_score(token: str) -> float:
    """Positive = Albanian, negative = English, 0 = no evidence (numbers, proper nouns, unknown words)."""
    w = _EDGE_PUNCT.sub("", token.lower())
    if not w or not any(ch.isalpha() for ch in w):
        return 0.0
    if w in _SQ_STRONG:
        return 3.0
    if w in _EN_STRONG:
        return -3.0
    if w in _SQ_WEAK:
        return 1.0
    if w in _EN_WEAK:
        return -1.0
    score = 0.0
    if "ë" in w or "ç" in w:
        score += 2.0
    elif any(d in w for d in ("gj", "xh", "zh")):
        score += 1.5
    if _SQ_SUFFIX.search(w):
        score += 1.5
    if "w" in w:  # the Albanian alphabet has no w
        score -= 2.0
    if len(w) > 4 and _EN_SUFFIX.search(w):
        score -= 1.5
    return score


def _cut(scores: list[float], toks: list[str]) -> int | None:
    """Best index to cut a token run into an Albanian head and an English tail, or ``None``.

    Unknown words between the last Albanian and the first English evidence tie; the English half starts with a
    capital (``'Numri i personave Number of persons'``), so a cut in front of a capitalised word wins a tie."""
    cuts: list[tuple[float, int]] = []
    for k in range(1, len(scores)):
        left, right = scores[:k], scores[k:]
        if min(left) <= -3 or max(right) >= 3:  # an unmistakable word of the wrong language on either side
            continue
        pos_left = sum(x for x in left if x > 0)
        neg_right = -sum(x for x in right if x < 0)
        if pos_left < 3 or neg_right < 3:
            continue
        cuts.append((pos_left + neg_right + sum(x for x in left if x < 0) - sum(x for x in right if x > 0), k))
    if not cuts:
        return None
    best = max(g for g, _ in cuts)
    tied = [k for g, k in cuts if g >= best - 1e-9]
    return next((k for k in tied if toks[k][:1].isupper()), tied[0])


def _split_tokens(s: str) -> tuple[str, str] | None:
    """``'Gjithsej Total'`` / ``'Mosha Age'`` / ``'Regjistrimi Census, 2001'``: both languages joined by one space.

    Needs unmistakable Albanian words in the head and unmistakable English words in the tail, so a label written in
    one language is never cut, however long."""
    toks = s.split(" ")
    if not 2 <= len(toks) <= 24:
        return None
    scores = [_token_score(t) for t in toks]
    k = _cut(scores, toks)
    if k is not None:
        return " ".join(toks[:k]), " ".join(toks[k:])
    k = _cut([-x for x in scores[::-1]], toks[::-1])  # English first, Albanian after (rare)
    if k is not None:
        cut = len(toks) - k
        return " ".join(toks[cut:]), " ".join(toks[:cut])
    return None


def _side_score(text: str) -> float:
    return sum(_token_score(t) for t in text.split(" "))


def split_bilingual(text: str) -> tuple[str, str] | None:
    """Split ``'Gjithsej/Total'``, ``'Shënim\\nNote'`` or ``'Meshkuj Male'`` into ``(albanian, english)``.

    Only splits when the two halves are demonstrably different languages (or a known glossary pair),
    so ``km/h`` or ``and/or`` are left alone.
    """
    from .glossary import translate  # local import: glossary depends on this module

    s = clean_text(text, keep_newlines=True)
    if not s:
        return None
    for splitter in _SPLITTERS:
        parts = splitter.split(s, maxsplit=1)
        if len(parts) != 2:
            continue
        a, b = clean_text(parts[0]), clean_text(parts[1])
        if not a or not b:
            continue
        la, lb = detect_language(a), detect_language(b)
        if la == "sq" and lb == "en":
            return a, b
        if la == "en" and lb == "sq":
            return b, a
        # One side unknown: accept when the glossary says they are translations of each other.
        for sq_side, en_side in ((a, b), (b, a)):
            tr = translate(sq_side)
            if tr and fold(tr) == fold(en_side):
                return sq_side, en_side
        # ... or when one side is clearly Albanian and the other shows English traits and no Albanian ones
        sa, sb = _side_score(a), _side_score(b)
        if sa >= 2 and -3 < sb <= -1.5 and la != "en":
            return a, b
        if sb >= 2 and -3 < sa <= -1.5 and lb != "en":
            return b, a
    return _split_tokens(clean_text(s))
