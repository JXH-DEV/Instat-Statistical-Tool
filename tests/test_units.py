"""What a table's numbers are measured in: the unit, the scale (thousands, millions), the base of an index and the price basis, as they are
written in INSTAT's titles and headers in Albanian and English."""

from __future__ import annotations

import pytest

from instatkit import i18n
from instatkit.semantics.units import UnitInfo, parse_units, subject_unit, unit_text


def read(text):
    u = parse_units(text)
    return u.unit, u.scale


@pytest.mark.parametrize("text, unit, scale", [
    ("billion ALL", "ALL", 1e9), ("miliardë lekë", "ALL", 1e9), ("bn EUR", "EUR", 1e9),
    ("million ALL", "ALL", 1e6), ("milion euro", "EUR", 1e6), ("mln USD", "USD", 1e6), ("mio EUR", "EUR", 1e6),
    ("thousand tonnes", "tonnes", 1e3), ("në mijë persona", "persons", 1e3), ("(000)", None, 1e3), ("in 000 persons", "persons", 1e3),
    ("000Lekë", "ALL", 1e3), ("'000 ALL", "ALL", 1e3),
    ("2000 lekë", "ALL", None), ("10,000 inhabitants", "persons", None),           # the end of a longer number is not a thousand marker
])
def test_scale_and_unit(text, unit, scale):
    assert read(text) == (unit, scale)


@pytest.mark.parametrize("text, unit", [
    ("%", "%"), ("përqindje", "%"), ("per cent", "%"), ("percent", "%"), ("pp", "%"),
    ("lekë", "ALL"), ("euro", "EUR"), ("€", "EUR"), ("EUR", "EUR"), ("USD", "USD"), ("dollar", "USD"), ("$", "USD"),
    ("index", "index"), ("indeks", "index"), ("indices", "index"),
    ("persons", "persons"), ("people", "persons"), ("banorë", "persons"), ("inhabitants", "persons"),
    ("tonnes", "tonnes"), ("tons", "tonnes"), ("tonë", "tonnes"),
    ("hectares", "ha"), ("ha", "ha"), ("kWh", "kWh"), ("GWh", "kWh"), ("m3", "m3"), ("m³", "m3"), ("m2", "m2"), ("m²", "m2"),
    ("km", "km"), ("kilometres", "km"), ("litres", "litres"), ("litra", "litres"), ("kg", "kg"), ("kilogram", "kg"),
    ("(years)", "years"), ("in years", "years"), ("në vite", "years"),
    ("number", "count"), ("numri", "count"), ("count", "count"), ("nr.", "count"),
])
def test_unit_words(text, unit):
    assert parse_units(text).unit == unit and not parse_units(text).unit_weak


@pytest.mark.parametrize("text", ["aged 10 years and over", "15 vjeç e lart", "all ages", "", "Total"])
def test_text_that_names_no_unit(text):
    assert parse_units(text).unit is None


def test_years_that_only_say_who_is_counted_are_not_a_duration():
    assert parse_units("persons aged 10 years and over").unit == "persons"


def test_the_unit_named_first_wins():
    assert parse_units("tonnes per hectare").unit == "tonnes"
    assert parse_units("hectares per tonne").unit == "ha"
    assert parse_units("persons per km2").unit == "persons"
    assert parse_units("lekë per person").unit == "ALL"


@pytest.mark.parametrize("text, unit", [
    ("Unemployment rate", "%"), ("Participation ratio", "%"), ("Structure of employment", "%"), ("Growth", "%"), ("Shkalla e papunësisë", "%"),
    ("Births per 1,000", "per 1,000"), ("Birth rate", "per 1,000"), ("Mortality", "per 1,000"),
    ("Population", "persons"), ("Popullsia", "persons"),
])
def test_a_weak_cue_gives_a_unit_that_an_explicit_one_can_replace(text, unit):
    u = parse_units(text)
    assert (u.unit, u.unit_weak) == (unit, True)
    assert parse_units(f"{text} (million ALL)").unit in ("ALL",) and not parse_units(f"{text} (million ALL)").unit_weak


@pytest.mark.parametrize("text, period, value", [
    ("(Dhjetor / December 2020 = 100)", "2020-12", 100.0),
    ("December 2020 = 100", "2020-12", 100.0),
    ("Janar 2015 = 100", "2015-01", 100.0),
    ("Mars / March 2018 = 1000", "2018-03", 1000.0),
    ("2015=100", "2015", 100.0), ("2010 = 100.5", "2010", 100.5), ("(2021 = 100)", "2021", 100.0),
    ("base year 2015", "2015", 100.0), ("viti bazë 2012", "2012", 100.0), ("baza: 2010", "2010", 100.0),
    ("previous year = 100", "previous_year", 100.0), ("viti i mëparshëm = 100", "previous_year", 100.0),
    ("same month of the previous year = 100", "same_period", 100.0),
    ("dhjetor i vitit të mëparshëm = 100", "previous_december", 100.0),
    ("December of the previous year = 100", "previous_december", 100.0), ("December previous year = 100", "previous_december", 100.0),
    ("Dhjetor i vitit të mëparshëm = 100 / December previous year = 100", "previous_december", 100.0),     # a bilingual header
    ("Periudha përkatëse e vitit të kaluar = 100", "same_period", 100.0),
])
def test_the_base_of_an_index(text, period, value):
    u = parse_units(text)
    assert (u.base_period, u.base_value) == (period, value)
    assert u.unit == "index"                                                       # a base period means an index


def test_a_word_that_is_not_a_month_before_the_year_leaves_a_year_base():
    assert parse_units("Blah 2020 = 100").base_period == "2020"


@pytest.mark.parametrize("text, basis", [
    ("në çmime korente", "current"), ("at current prices", "current"),
    ("në çmimet e vitit të mëparshëm", "previous_year"), ("previous year's prices", "previous_year"), ("prices of the previous year", "previous_year"),
    ("në çmime konstante", "constant"), ("constant prices", "constant"), ("chain-linked volumes", "constant"), ("çmime të pandryshuara", "constant"),
])
def test_price_basis(text, basis):
    assert parse_units(text).price_basis == basis


def test_a_change_in_an_index_is_a_percentage_but_the_index_itself_is_not():
    assert parse_units("Annual change of the consumer price index").unit == "%"
    assert parse_units("Consumer price index (2015 = 100)").unit == "index"
    assert parse_units("Consumer price index").unit == "index"


def test_all_persons_is_not_a_currency_but_all_alone_in_the_right_place_is():
    assert parse_units("Employment, all persons").unit == "persons"
    assert parse_units("EMPLOYMENT, ALL PERSONS").unit == "persons"
    assert parse_units("MILLION ALL").unit == "ALL" and parse_units("(ALL)").unit == "ALL" and parse_units("PRICES (ALL)").unit == "ALL"
    assert parse_units("Value, ALL million").unit == "ALL"


# --- putting what several fragments say together ---
def test_the_first_fragment_to_say_something_wins():
    a = UnitInfo(scale=1e3, scale_label="thousand", raw=["a"])
    b = UnitInfo(scale=1e6, scale_label="million", base_period="2015", base_value=100.0, price_basis="constant", raw=["b"])
    merged = a.merge(b)
    assert merged is a
    assert (a.scale, a.scale_label) == (1e3, "thousand")                            # kept
    assert (a.base_period, a.base_value, a.price_basis) == ("2015", 100.0, "constant")   # filled in
    assert a.raw == ["a", "b"]


def test_a_fragment_that_adds_nothing_changes_nothing():
    a = UnitInfo(scale=1e3, unit="ALL", raw=["a"])
    a.merge(UnitInfo(raw=["a"]))
    assert (a.scale, a.unit, a.raw) == (1e3, "ALL", ["a"])


def test_an_explicit_unit_replaces_a_weak_one_and_not_the_other_way_round():
    weak_persons = UnitInfo(unit="persons", unit_weak=True)
    assert (weak_persons.merge(UnitInfo(unit="ALL")).unit, weak_persons.unit_weak) == ("ALL", False)
    explicit = UnitInfo(unit="ALL")
    assert (explicit.merge(UnitInfo(unit="%", unit_weak=True)).unit, explicit.unit_weak) == ("ALL", False)
    first_weak = UnitInfo(unit="persons", unit_weak=True)
    assert first_weak.merge(UnitInfo(unit="%", unit_weak=True)).unit == "persons"
    nothing = UnitInfo()
    assert (nothing.merge(UnitInfo(unit="%", unit_weak=True)).unit, nothing.unit_weak) == ("%", True)
    first_explicit = UnitInfo(unit="ALL")
    assert first_explicit.merge(UnitInfo(unit="EUR")).unit == "ALL"


def test_several_fragments_of_a_header_are_read_together():
    u = parse_units("Qarkullimi i mallrave", "miliardë lekë/billion ALL", "(Dhjetor / December 2020 = 100)")
    assert (u.unit, u.scale, u.base_period) == ("ALL", 1e9, "2020-12")


# --- how a unit is shown ---
def test_unit_labels():
    assert UnitInfo(unit="ALL", scale_label="million").label == "million ALL"
    assert UnitInfo(unit="persons", scale_label="thousand").label == "thousand persons"
    assert UnitInfo(unit="%").label == "%"
    assert UnitInfo(unit="index", base_period="2020-12", base_value=100.0).label == "index (2020-12=100)"
    assert UnitInfo(unit="index", base_period="previous_year").label == "index (base previous_year)"
    assert UnitInfo(unit="ALL", base_period="2015", base_value=100.0).label == "ALL"
    assert UnitInfo().label == ""


def test_unit_words_are_shown_in_the_language_in_use():
    assert unit_text("million ALL") == "million ALL" and unit_text(None) == ""
    with i18n.using("sq"):
        shown = unit_text("thousand persons")
    assert shown != "thousand persons" and "persons" not in shown and "thousand" not in shown
    with i18n.using("sq"):
        assert unit_text("index (base 2015)").startswith("indeks") or "index" not in unit_text("index (base 2015)")
        assert unit_text("2015") == "2015"


# --- what a count counts ---
@pytest.mark.parametrize("title, unit", [
    ("Resident population in private households by sex", "persons"),
    ("Private households by size", "households"),
    ("Dwellings by type", "dwellings"), ("Buildings with permits by use", "buildings"),
    ("Tourist arrivals by country", "visitors"), ("Overnight nights by month", "nights"),
    ("Households and persons by region", "households"),                           # the first noun named is the subject
    ("Popullsia sipas gjinisë", "persons"), ("Banesat sipas llojit", "dwellings"),
    ("Gross domestic product by activity", None), ("", None), (None, None),
])
def test_what_a_count_counts(title, unit):
    assert subject_unit(title) == unit


def test_a_title_that_is_mostly_but_not_entirely_in_capitals_still_has_the_currency_code():
    assert parse_units("Vs ALL").unit == "ALL"                                      # four letters of five in capitals: not yet shouting
    assert parse_units("VALUES ALL").unit is None                                   # all of them: ALL is only a currency where one would stand
    assert parse_units("VALUES (ALL)").unit == "ALL" and parse_units("VALUES, MILLION ALL").unit == "ALL"
