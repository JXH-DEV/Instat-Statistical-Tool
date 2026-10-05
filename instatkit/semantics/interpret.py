"""Interpret a tidy table: what is it about, what are its dimensions, how is it measured?

Produces a :class:`DatasetProfile` and renames the generic ``dim_1 ...`` columns to role names such as
``sex`` or ``age_group``. Everything is rule-based (headers, glossary, value patterns) and records *why* a
decision was made so it can be shown to the user.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace

import pandas as pd

from ..excel.tidy import TidyTable
from ..i18n import pick, tr
from . import glossary
from .labels import role_name, topic_name
from .periods import FREQ_NAME, missing_periods, parse_period
from .textnorm import clean_text, detect_language, split_bilingual
from .units import parse_units

ROLE_BY_TAG = {
    "sex": "sex", "county": "region", "municipality": "region", "urban_rural": "urban_rural", "age": "age_group",
    "education": "education", "status": "labour_status", "country": "country", "continent": "country",
    "month": "month", "sector": "activity", "ownership": "ownership", "coicop": "product", "trade": "category",
    "national_accounts": "category", "period_word": "period_label", "marital": "marital_status",
}

# header-text cues (Albanian and English), first match wins
_HEADER_CUES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?i)\b(age|mosha|grupmosh\w*|grup-mosh\w*)\b"), "age_group"),
    (re.compile(r"(?i)\b(sex|gender|gjinia|gjinis[eë])\b"), "sex"),
    (re.compile(r"(?i)\b(urban\w*|rural\w*)\b"), "urban_rural"),
    (re.compile(r"(?i)\b(region\w*|prefecture|county|qark\w*|bashki\w*|municipalit\w*|vendbanim\w*|area|zona)\b"), "region"),
    (re.compile(r"(?i)\b(economic activit\w*|activit\w*|aktivitet\w*|nace|nve|sector\w*|sektor\w*|industry|industria)\b"), "activity"),
    (re.compile(r"(?i)\b(countr\w*|shteti|shtete\w*|vend\w*|partner\w*|origin|destination|nationality|shtet[eë]sia)\b"), "country"),
    (re.compile(r"(?i)\b(product\w*|commodit\w*|produkt\w*|mall\w*|goods|coicop|hs|sitc|kapitull\w*|chapter|group\w*|grup\w*)\b"), "product"),
    (re.compile(r"(?i)\b(education\w*|arsim\w*|isced)\b"), "education"),
    (re.compile(r"(?i)\b(marital|civil\w*|martes\w*)\b"), "marital_status"),
    (re.compile(r"(?i)\b(household|famil\w*|kryefamilj\w*|relationship|lidhja)\b.*\bstatus|statusi\s+i\s+(?:njesis|familj)\w*"), "household_status"),
    (re.compile(r"(?i)\b(labou?r\s+(?:force\s+)?status|activity\s+status|status\s+in\s+employment|occupation\w*|profesion\w*|employ\w*|pun[eë]sim\w*)\b"),
     "labour_status"),
    (re.compile(r"(?i)\b(month|muaji|muaj)\b"), "month"),
    (re.compile(r"(?i)\b(year|viti|vit)\b"), "year"),
]

# roles whose values come from a closed vocabulary: a header word alone does not prove them ("Country of birth and sex"
# heads a level of countries as well as one of sexes)
_VOCABULARY = {"sex": "sex", "marital_status": "marital", "urban_rural": "urban_rural"}
_SEX_CODE = re.compile(r"(?i)^(?:m|f|w|men|women|boys|girls|male|female)s?$")

# "1-2 / 3-4 / 5+" under "number of household members" are class sizes, not ages
_NOT_AGE_HEADER = re.compile(r"(?i)\b(members?|an[eë]tar\w*|rooms?|dhoma\w*|children|f[eë]mij\w*|size|madh[eë]sia|number|numri)\b")
_AGE_WORD = re.compile(r"(?i)\b(age|mosha\w*|grupmosh\w*|aged)\b")
# labels that are indicator names with their own kind of value (a % share, a ratio, an average ...)
_INDICATOR_LABEL = re.compile(r"(?i)%|\b(ratio|rate|average|mean|median|mesatar\w*|raporti|shkalla|density|dend[eë]sia|index|indeksi)\b")
_AGE_VALUE = re.compile(r"^(?:[1-9]?\d{1,2}\s*[-–]\s*\d{1,3}|\d{1,3}\s*\+|(?:under|over|up to|below)\s+\d+.*|\d+\s*years?.*|\d+\s*vje[cç].*)$", re.I)
# header words that say "this column holds classification codes" (NACE 01-03, COICOP 01.1, HS 84, ...)
_CODE_HEADER = re.compile(r"(?i)\b(nace|nve|coicop|isic|sitc|hs|cpa|prodcom|isco|code|kodi)\b")
_MEASURE_HEADER = re.compile(r"(?i)\b(indicators?|treguesi\w*|measures?|variables?|tregues)\b")
# measures that are averages, rates, prices or indices cannot be summed across categories
_NON_ADDITIVE = re.compile(
    r"(?i)\b(average|mean|median|mesatar\w*|per\s+\w+|rate|ratio|share|index|wage|salary|pag[eë]\w*|"
    r"shkall\w*|coverage|mbulim\w*|density|productivity|prodhimtari|life expectancy|jet[eë]gjat\w*|growth|change|rritj\w*|"
    r"ndryshim\w*|gini|percent\w*|p[eë]rqindj\w*)|%")

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "prices": ["consumer price", "çmimeve të konsumit", "cmimet", "price index", "inflation", "inflacion", "coicop",
               "producer price", "çmimeve të prodhuesit", "import price", "harmonized index"],
    "labour": ["labour force", "forcave të punës", "unemployment", "papunësi", "employment rate", "punësimi",
               "participation rate", "shkalla e punësimit", "inactive"],
    "national_accounts": ["gross domestic product", "prodhimi i brendshëm bruto", "gdp", "pbb", "national accounts",
                          "llogaritë kombëtare", "value added", "vlera e shtuar", "intermediate consumption"],
    "trade": ["foreign trade", "tregtia e jashtme", "exports", "imports", "eksport", "import", "flow of goods",
              "qarkullimi i mallrave", "partner countries"],
    "population": ["population", "popullsia", "life expectancy", "jetëgjatësia", "births", "lindjet", "deaths",
                   "vdekjet", "fertility", "infant mortality", "age group", "grupmosha", "migration", "migrim"],
    "tourism": ["tourism", "turizëm", "arrivals", "ardhjet", "nights spent", "netëqëndrime", "visitors", "vizitorë"],
    "wages": ["wage", "paga", "salary", "earnings", "gjinor i pagës", "minimum wage", "labour cost", "kostot e punës"],
    "education": ["education", "arsim", "enrolment", "enrollment", "students", "nxënës", "school", "shkolla"],
    "health": ["health", "shëndet", "hospital", "spital", "doctors", "mjekë"],
    "agriculture": ["agricultur", "bujqësi", "livestock", "blegtori", "crops", "fishery", "peshkim", "forest", "pyje"],
    "energy": ["energy", "energji", "electricity", "elektrike", "gas ", "oil", "naftë"],
    "construction": ["construction", "ndërtim", "building permits", "leje ndërtimi", "dwelling", "banesa"],
    "transport": ["transport", "vehicle", "automjet", "accidents", "aksident", "road", "rrugor"],
    "business": ["enterprise", "ndërmarrj", "business", "biznes", "turnover", "qarkullim", "industrial production"],
    "poverty_living": ["poverty", "varfëri", "income and living", "household budget", "buxheti i familjes", "gini"],
    "environment": ["environment", "mjedis", "waste", "mbetje", "emissions", "emetime", "water", "ujë"],
    "ict": ["information and communication", "ict", "internet", "komunikim"],
    "crime": ["crime", "krim", "criminal", "justice", "drejtësi"],
    "gender": ["gender", "gjinor", "women and men", "gra dhe burra"],
}

_ADDITIVE_UNITS = {"ALL", "EUR", "USD", "persons", "count", "households", "dwellings", "buildings", "visitors", "nights",
                   "tonnes", "ha", "kWh", "m3", "m2", "km", "litres", "kg"}


@dataclass
class DimInfo:
    name: str
    role: str
    header: str
    n_values: int
    total_values: list[str] = field(default_factory=list)
    reason: str = ""
    alias_of: str | None = None  # a code column that is 1:1 with the named dimension it duplicates


@dataclass
class MeasureInfo:
    name: str
    unit: str  # display label, e.g. 'million ALL'
    kind: str  # level | index | rate | growth | share
    additive: bool
    unit_code: str = ""
    scale: float | None = None
    scale_label: str | None = None
    display: str = ""  # the name as it is shown (Albanian when the file has one and Albanian is switched on)

    def __post_init__(self) -> None:
        self.display = self.display or self.name


@dataclass
class DatasetProfile:
    table_id: str
    sheet: str
    title: str
    title_en: str | None
    title_sq: str | None
    topics: list[str]
    kind: str  # time_series | short_panel | cross_section
    freq: str | None
    freq_name: str
    n_periods: int
    first_period: str | None
    last_period: str | None
    missing_periods: list[str]
    provisional_periods: list[str]
    dims: list[DimInfo]
    measures: list[MeasureInfo]
    unit: str
    base_period: str | None
    price_basis: str | None
    code_system: str | None
    n_series: int
    n_obs: int
    n_missing: int
    confidence: float
    warnings: list[str]
    notes: list[str]
    orientation: str
    source: dict = field(default_factory=dict)

    @property
    def shown_title(self) -> str:
        """The title as it is shown. ``title`` itself is what the analysis reasons with and does not change with the language."""
        return pick(self.title_en, self.title_sq, self.title)

    def dim(self, role: str) -> DimInfo | None:
        return next((d for d in self.dims if d.role == role), None)

    def measure(self, name: str) -> MeasureInfo | None:
        return next((m for m in self.measures if m.name == name), None)

    @property
    def dim_names(self) -> list[str]:
        return [d.name for d in self.dims]


def _age_like(values: list[str]) -> bool:
    """Age bands run on contiguously (0-4, 5-9, 10-14 ...) and never carry leading zeros (NACE 01-03)."""
    vs = [clean_text(v) for v in values if not glossary.is_total_label(v)]
    if not vs or sum(1 for v in vs if _AGE_VALUE.match(v)) / len(vs) < 0.7 or any(re.match(r"^0\d", v) for v in vs):
        return False
    bands = sorted(tuple(int(x) for x in re.findall(r"\d+", v)[:2]) for v in vs if re.match(r"^\d+\s*[-–]\s*\d+$", v))
    if len(bands) >= 3:
        contiguous = sum(1 for a, b in zip(bands, bands[1:]) if b[0] == a[1] + 1)
        return contiguous >= 0.6 * (len(bands) - 1)
    return True


def _has_vocabulary(role: str, values: list[str]) -> bool:
    return any(glossary.tag_of(v) == _VOCABULARY[role] or (role == "sex" and _SEX_CODE.match(v.strip())) for v in values)


def _mixed_kinds(values: list[str]) -> bool:
    """Do the values list two kinds of group side by side (Total / Male / Female / Urban / Rural)?"""
    kinds = Counter(ROLE_BY_TAG[t] for v in values if not glossary.is_total_label(v) and (t := glossary.tag_of(v)) in ROLE_BY_TAG)
    top = kinds.most_common(2)
    return len(top) == 2 and top[1][1] >= 2 and top[1][1] / max(1, sum(1 for v in values if not glossary.is_total_label(v))) >= 0.25


def infer_dim_role(header: str, values: list[str]) -> tuple[str, str]:
    """(role, reason) for one dimension from its header text and its distinct values."""
    vals = [v for v in values if v]
    if header and _MEASURE_HEADER.search(header):
        return "measure_name", tr("the header '{header}' introduces indicators", header=header)
    tag, share = glossary.dominant_tag(vals)
    if tag in ("trade", "national_accounts") and share >= 0.6:
        return "measure_name", tr("{share} of the values are {topic} indicator names", share=f"{share:.0%}", topic=topic_name(tag))
    if vals and sum(1 for v in vals if re.search(r"\((?:%|index|mln|million|000)[^)]*\)\s*$", v, re.I)) >= max(1, len(vals) // 2):
        return "measure_name", tr("the values carry their own units in brackets")
    if len(vals) >= 6 and not tag:
        mixed = sum(1 for v in vals if _INDICATOR_LABEL.search(v))
        if mixed >= 2 and mixed / len(vals) >= 0.15:
            return "measure_name", tr("the labels are indicators that mix counts, shares, ratios and averages")
    if header and _CODE_HEADER.search(header) and not tag:
        for pat, role in _HEADER_CUES:
            if pat.search(header):
                return f"{role}_code", tr("the header '{header}' holds {role} codes", header=header, role=role_name(role))
        return "code", tr("the header '{header}' holds classification codes", header=header)
    if tag in ROLE_BY_TAG and share >= 0.6:
        return ROLE_BY_TAG[tag], tr("{share} of the values look like {role} labels", share=f"{share:.0%}", role=role_name(ROLE_BY_TAG[tag]))
    if _mixed_kinds(vals):
        return "category", tr("the values mix several kinds of group (for example sexes and urban/rural areas)")
    if _age_like(vals) and not (_NOT_AGE_HEADER.search(header or "") and not _AGE_WORD.search(header or "")):
        return "age_group", tr("the values look like age ranges")
    for pat, role in _HEADER_CUES:
        if header and pat.search(header):
            if role == "year" and not all(re.fullmatch(r"(?:19|20)\d{2}\**", v.strip()) for v in vals if not glossary.is_total_label(v)):
                continue  # "Year of construction": classes like 'Before 1945' or '1946-1960' are categories, not points in time
            if role in _VOCABULARY and not _has_vocabulary(role, vals):
                if role == "urban_rural":  # "Urban and rural area" over measure names is not an area dimension
                    return "category", tr("the header '{header}' names urban/rural areas, but the values are not areas", header=header)
                continue
            return role, tr("the header '{header}' names a {role}", header=header, role=role_name(role))
    if vals and len(vals) >= 2 and all(parse_period(v) is not None for v in vals if not glossary.is_total_label(v)):
        return "period_label", tr("the values are periods")
    return "category", tr("nothing in the header or the values points to a role")


def detect_code_system(codes: list[str], header: str, title: str) -> str | None:
    cs = [c for c in codes if c]
    if not cs:
        return None
    h = f"{header} {title}".lower()
    dotted = sum(1 for c in cs if re.fullmatch(r"\d{1,2}(?:\.\d{1,2})+\.?|\d{1,2}\.", c))
    if "coicop" in h or "çmimeve të konsumit" in h or "consumer price" in h or dotted / len(cs) >= 0.5:
        return "COICOP"
    if "nace" in h or "nve" in h or "economic activit" in h or "aktivitet" in h:
        return "NACE"
    if re.search(r"\bhs\b|harmoni[sz]ed system|sitc|kapitull", h):
        return "HS"
    if "isco" in h or "profesion" in h or "occupation" in h:
        return "ISCO"
    return "code"


def topics_for(text: str) -> list[str]:
    low = text.lower()
    return [t for t, kws in TOPIC_KEYWORDS.items() if any(k in low for k in kws)]


def _measure_kind(unit: str, name: str) -> str:
    low = name.lower()
    if unit == "index":
        return "index"
    if unit == "%":
        if re.search(r"change|growth|ndryshim|rritj|variation", low):
            return "growth"
        if re.search(r"share|structure|struktur|përqindj|contribution|kontribut", low):
            return "share"
        return "rate"
    if unit == "per 1,000":
        return "rate"
    return "level"


def _is_additive(name: str, title: str, unit_code: str, kind: str) -> bool:
    """Can values be summed across categories? Not for averages, rates, prices, indices or ratios."""
    return kind == "level" and unit_code in _ADDITIVE_UNITS and not _NON_ADDITIVE.search(f"{name} {title}")


def _share(values: pd.Series, pred) -> float:
    return float(values.map(pred).mean()) if len(values) else 0.0


def _englishish(v: str) -> bool:
    lang = detect_language(v)
    return lang == "en" or (lang == "unk" and v.isascii())


def _translate_from_sibling(table: TidyTable) -> None:
    """If an English-language text column sits next to Albanian labels (1:1), the publisher's own English is used for
    display, ahead of the glossary; the labels as written stay in ``<dim>_orig``. "Total" keeps its standard wording."""
    df = table.df
    for attr in [c for c in df.columns if c.startswith("attr_")]:
        vals = df[attr].dropna().astype(str)
        if vals.empty or _share(vals, lambda v: re.fullmatch(r"-?[\d.,]+", v) is not None) > 0.5:
            continue
        if _share(vals, _englishish) < 0.8 or _share(vals, lambda v: detect_language(v) == "sq") > 0.2:
            continue
        for dim in table.dim_columns:
            orig = f"{dim}_orig"
            source = orig if orig in df.columns else dim  # the labels as written in the file
            pair = df[[source, attr]].dropna()
            pair = pair[pair[attr].map(lambda v: isinstance(v, str))].drop_duplicates()  # a stray number is not a label
            if pair.empty or not pair[source].is_unique or not pair[attr].is_unique or (pair[source] == pair[attr]).all():
                continue
            if _share(pair[source].astype(str), lambda v: detect_language(v) == "sq") < 0.4:
                continue
            english = df[source].map(dict(zip(pair[source], pair[attr])))
            if orig not in df.columns:
                df[orig] = df[dim]
            df[dim] = df[dim].where(df[dim].astype(str).map(glossary.is_total_label), english.fillna(df[dim]))
            df.drop(columns=[attr], inplace=True)
            break


_JOINERS = r"[\s\-–—/|:]"  # what separates the two halves of a label written in both languages


def _albanian_part(written: str, value: str) -> str:
    """The Albanian half of a label that the file wrote in both languages ('Meshkuj Male' for the value 'Male'), or all of it
    when it is Albanian only; empty when there is none. Two letters or fewer ('M' over 'Male') is a code, not a word."""
    if any(ch.isalpha() for ch in value):
        joined = rf"{_JOINERS}+"
        for pattern in (rf"(?P<sq>.+?){joined}{re.escape(value)}", rf"{re.escape(value)}{joined}(?P<sq>.+)"):  # English last, or first
            if (m := re.fullmatch(pattern, written, re.I)) and detect_language(m["sq"]) != "en":
                return m["sq"] if len(m["sq"]) > 2 else ""
    pair = split_bilingual(written)
    albanian = pair[0] if pair else (written if glossary.translate(written) or detect_language(written) == "sq" else "")
    return albanian if len(albanian) > 2 else ""


def _file_wording(table: TidyTable) -> dict[str, str]:
    """The Albanian words the file itself has for its categories ('Meshkuj' for 'Male'), taken from labels written in both
    languages or in Albanian only. With Albanian switched on they are shown ahead of the glossary's."""
    words: dict[str, str] = {}
    df = table.df
    for dim in table.dim_columns:
        if f"{dim}_orig" not in df.columns:
            continue
        for value, written in df[[dim, f"{dim}_orig"]].drop_duplicates().itertuples(index=False):
            if not (isinstance(value, str) and isinstance(written, str)) or value == written:
                continue
            albanian = _albanian_part(written, value)
            if len(albanian) > 3 and albanian.isupper():
                albanian = albanian.title()  # a region written DIBËR in the file reads Dibër in a sentence
            if albanian and albanian != value:
                words.setdefault(clean_text(value), albanian)
    return words


def _promote_measure_dims(table: TidyTable, dims_roles: dict[str, str]) -> None:
    """A dimension that lists *indicators* (Exports / Imports / Coverage ratio (%)) is really the measure."""
    df = table.df
    for col, role in list(dims_roles.items()):
        if role != "measure_name":
            continue
        base = df["measure"]
        df["measure"] = df[col].where(df[col] != "", base)
        df.drop(columns=[col], inplace=True)
        table.dim_columns = [c for c in table.dim_columns if c != col]
        table.dim_info.pop(col, None)
        del dims_roles[col]


def interpret(table: TidyTable, *, source: dict | None = None) -> DatasetProfile:
    """Profile ``table`` and rename its dimension columns in place according to the inferred roles."""
    _translate_from_sibling(table)
    df, spec = table.df, table.spec
    title = table.reading_title

    roles: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for col in table.dim_columns:
        values = [v for v in df[col].dropna().unique().tolist() if v != ""]
        header = table.dim_info.get(col, {}).get("header", "")
        roles[col], reasons[col] = infer_dim_role(header, values)
    _promote_measure_dims(table, roles)
    df = table.df

    dims: list[DimInfo] = []
    rename: dict[str, str] = {}
    used: set[str] = set(df.columns)
    for col in table.dim_columns:
        role = roles[col]
        values = [v for v in df[col].dropna().unique().tolist() if v != ""]
        header = table.dim_info.get(col, {}).get("header", "")
        name, i = role, 2
        while name in used and name != col:
            name = f"{role}_{i}"
            i += 1
        used.add(name)
        rename[col] = name
        totals = [v for v in values if glossary.is_total_label(v)]
        dims.append(DimInfo(name=name, role=role, header=header, n_values=len(values), total_values=totals, reason=reasons[col]))
    orig_rename = {f"{old}_orig": f"{new}_orig" for old, new in rename.items() if f"{old}_orig" in df.columns}
    df.rename(columns={**rename, **orig_rename}, inplace=True)
    table.dim_columns = [rename[c] for c in table.dim_columns]
    table.dim_info = {rename.get(k, k): v for k, v in table.dim_info.items()}
    by_role = {d.role: d for d in dims}
    for d in dims:  # a code column that maps 1:1 onto a named dimension only duplicates it
        if d.role.endswith("_code") and d.role[:-5] in by_role:
            base = by_role[d.role[:-5]]
            pair = df[[d.name, base.name]].drop_duplicates()
            if pair[d.name].is_unique and pair[base.name].is_unique:
                d.alias_of = base.name

    # frequency / coverage
    periods = df.loc[df["period"] != "", ["period", "freq", "period_start"]].drop_duplicates("period")
    periods = periods.sort_values("period_start")
    n_periods = len(periods)
    freq = spec.freq if spec.freq else (periods["freq"].mode().iloc[0] if n_periods else None)
    parsed = [parse_period(p) for p in periods["period"]]
    parsed = [p for p in parsed if p is not None]
    gaps = [p.label for p in missing_periods(parsed)] if n_periods > 2 else []
    prov = sorted(df.loc[df["flag"] == "p", "period"].unique().tolist())
    kind = "time_series" if n_periods >= 3 else ("short_panel" if n_periods == 2 else "cross_section")

    # measures: a unit written in the measure's own name (for example "Coverage ratio (%)") overrides the table's
    tu = spec.units
    if tu.unit == "%" and tu.unit_weak and len(df) and df["value"].abs().median() > 100:
        tu = replace(tu, unit=None, unit_weak=False)  # "rate", "growth" or "structure" in the title, but the numbers are not percentages
        df["unit"] = tu.label or ""
    measures: list[MeasureInfo] = []
    for m in df["measure"].unique().tolist():
        own = parse_units(m)
        explicit = own.unit is not None and not own.unit_weak and own.unit != tu.unit
        code = own.unit if explicit else (tu.unit or own.unit or "")
        scale, scale_label = (own.scale, own.scale_label) if explicit else (tu.scale, tu.scale_label)
        label = own.label if explicit else (tu.label or "")
        mk = _measure_kind(code, m if m else title)
        measures.append(MeasureInfo(m, label, mk, _is_additive(m, title, code, mk), code, scale, scale_label, table.measure_label(m)))
        if explicit:
            df.loc[df["measure"] == m, "unit"] = label
    if not measures:
        measures.append(MeasureInfo(title, tu.label or "", "level", False, tu.unit or "", tu.scale, tu.scale_label))

    code_system = None
    if "code" in df.columns:
        header = next((c.name for c in spec.columns if c.kind == "code"), "")
        code_system = detect_code_system(df["code"].dropna().unique().tolist(), header, title)
        if code_system == "COICOP" and not any(d.role == "product" for d in dims):
            for d in dims:
                if d.role == "category":
                    d.role = "product"
                    d.reason = tr("the rows carry COICOP codes")

    table.label_words.update(_file_wording(table))
    topics = topics_for(" ".join(filter(None, [title, table.title_sq or "", " ".join(spec.titles)] + [m.name for m in measures])))
    src = dict(source or {})
    src.setdefault("sheet", table.sheet)
    src["cells"] = _bbox(table)
    return DatasetProfile(
        table_id=table.table_id, sheet=table.sheet, title=title, title_en=table.title_en, title_sq=table.title_sq,
        topics=topics, kind=kind, freq=freq or None, freq_name=FREQ_NAME.get(freq or "", "none"), n_periods=n_periods,
        first_period=periods["period"].iloc[0] if n_periods else None,
        last_period=periods["period"].iloc[-1] if n_periods else None, missing_periods=gaps, provisional_periods=prov,
        dims=dims, measures=measures, unit=tu.label or "", base_period=tu.base_period, price_basis=tu.price_basis,
        code_system=code_system, n_series=int(df["series_id"].nunique()), n_obs=len(df),
        n_missing=int(df["value"].isna().sum()), confidence=spec.confidence, warnings=list(table.warnings),
        notes=list(spec.notes), orientation=spec.orientation, source=src,
    )


def _bbox(table: TidyTable) -> str:
    """A1-style range of the data block in the original sheet, e.g. ``C6:BG9``."""
    from ..excel.grid import col_letter

    spec = table.spec
    if not spec.data_rows or not spec.columns:
        return ""
    r0, c0 = spec.origin
    rows = spec.data_rows
    cols = [c.col for c in spec.columns]
    return f"{col_letter(min(cols) + c0)}{min(rows) + r0 + 1}:{col_letter(max(cols) + c0)}{max(rows) + r0 + 1}"
