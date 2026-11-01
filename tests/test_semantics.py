"""Numbers, units, text normalisation and number formatting in both languages."""

from __future__ import annotations

import pytest

from instatkit import i18n
from instatkit.pipeline import slug
from instatkit.semantics import glossary
from instatkit.semantics.numbers import looks_numeric, parse_number
from instatkit.semantics.textnorm import clean_text, detect_language, fold, split_bilingual
from instatkit.semantics.units import parse_units


@pytest.mark.parametrize("text, value", [
    ("1 234,5", 1234.5), ("1.234,5", 1234.5), ("61 500", 61500.0), ("12,5%", 12.5), ("(12)", -12.0), ("−3,5", -3.5),
    ("1,234", 1234.0),          # ambiguous; read as thousands, as English does
    ("0,500", 0.5),             # a thousands group never starts with 0: this is a half, not 500
    ("0.500", 0.5), ("0,125", 0.125),
    ("1.234.567", 1234567.0), ("12e3", 12000.0),
])
def test_text_numbers(text, value):
    assert parse_number(text).value == pytest.approx(value)


def test_forced_decimal_comma():
    assert parse_number("1,234", decimal=",").value == pytest.approx(1.234)
    assert parse_number("1.234", decimal=",").value == pytest.approx(1234.0)
    assert parse_number("0.500", decimal=",").value == pytest.approx(0.5)


@pytest.mark.parametrize("text, flag", [("..", "na"), ("...", "na"), ("-", "nil"), ("–", "nil"), ("x", "suppressed"), ("n/a", "na")])
def test_missing_markers(text, flag):
    n = parse_number(text)
    assert n.value is None and n.flag == flag and n.is_marker


def test_status_letters_and_codes():
    assert parse_number("123p").flag == "p" and parse_number("123p").value == 123.0
    assert parse_number("45 e").flag == "e"
    assert parse_number("000000").value is None          # a code with leading zeros is text, not a quantity
    assert parse_number("01.1").value is None
    assert parse_number("abc").flag == "text"
    assert parse_number(float("nan")).flag == "na"
    assert not looks_numeric("Tirana") and looks_numeric("..") and looks_numeric("1 234")


def test_units_scale_and_currency():
    u = parse_units("miliardë lekë/billion ALL")
    assert (u.unit, u.scale_label) == ("ALL", "billion")
    u = parse_units("(Dhjetor / December 2020 = 100)")
    assert u.unit == "index" and u.base_period == "2020-12" and u.base_value == 100
    assert parse_units("Në mijë persona").scale_label == "thousand"
    assert parse_units("in million ALL").unit == "ALL"
    assert parse_units("Ndryshimi vjetor (%)").unit == "%"
    assert parse_units("MILLION ALL").unit == "ALL"          # a title in capitals still names the currency
    assert parse_units("(ALL)").unit == "ALL" and parse_units("ALL").unit == "ALL"


def test_the_english_word_all_is_not_the_currency():
    assert parse_units("Employment, all persons").unit == "persons"
    assert parse_units("EMPLOYMENT, ALL PERSONS").unit == "persons"
    assert parse_units("all ages").unit is None


def test_ten_thousand_is_not_a_thousand_scale():
    """The end of ``10,000`` is not a thousand marker."""
    for text in ("per 10,000 inhabitants", "over 100,000 residents", "10.000 banorë"):
        assert parse_units(text).scale is None, text
    assert parse_units("(000)").scale == 1000.0 and parse_units("in 000 persons").scale == 1000.0


def test_bilingual_split_either_order():
    assert split_bilingual("Gjithsej/Total") == ("Gjithsej", "Total")
    assert split_bilingual("Shënim\nNote") == ("Shënim", "Note")
    assert split_bilingual("Meshkuj Male") == ("Meshkuj", "Male")
    assert split_bilingual("Male Meshkuj") == ("Meshkuj", "Male")
    assert split_bilingual("Total Gjithsej") == ("Gjithsej", "Total")
    assert split_bilingual("km/h") is None and split_bilingual("and/or") is None
    assert split_bilingual("Consumer Price Index") is None                 # one language is never cut


def test_text_normalisation():
    assert clean_text("  Nëntor   2023 ") == "Nëntor 2023"
    assert fold("Çmimet e Konsumit") == fold("cmimet e konsumit")
    assert clean_text("Régjistrimi") == clean_text("Régjistrimi")       # NFD and NFC are the same label
    assert detect_language("Indeksi i çmimeve të konsumit") == "sq"
    assert detect_language("Consumer price index") == "en"


def test_glossary():
    assert glossary.is_total_label("Gjithsej") and glossary.is_total_label("Total")
    assert not glossary.is_total_label("Tirana")
    assert glossary.translate("Meshkuj") == "Males"
    assert glossary.looks_like_age_band(["0-14", "15-64", "65+"]) and not glossary.looks_like_age_band(["Tirana", "Durrës"])


def test_slug_keeps_base_letters_of_albanian_words():
    assert slug("Çmimet e konsumit") == "Cmimet-e-konsumit"
    assert slug("Tiranë – 2023") == "Tirane-2023"
    assert slug("***") == "dataset" and slug("a" * 200, 10) == "a" * 10


def test_number_formats_follow_the_language():
    assert i18n.num(1234567.891, 1) == "1,234,567.9"
    with i18n.using("sq"):
        assert i18n.num(1234567.891, 1) == "1 234 567,9"
        assert i18n.plain(12.34) == "12,3"
    assert i18n.num(-0.0001, 2) == "0.00"                                    # no "−0.00"
    assert i18n.num(-5, 0).startswith("−")
    assert i18n.join(["a", "b", "c"]) == "a, b and c"
    with i18n.using("sq"):
        assert i18n.join(["a", "b", "c"]).endswith(" dhe c")
    assert i18n.tn(1, "{n} row", "{n} rows") == "1 row" and i18n.tn(2, "{n} row", "{n} rows") == "2 rows"
    assert i18n.guess("sq-AL,sq;q=0.9") == "sq" and i18n.guess("en-GB") == "en" and i18n.guess(None) == "en"


@pytest.mark.parametrize("text", ["000Lekë / 000ALL", "'000Lekë", "(000 lekë)", "000EUR", "000 ALL", "000ALL"])
def test_a_thousand_marker_written_against_the_currency(text):
    """INSTAT's building-permit values say "000Lekë / 000ALL". Not seen as thousand lek, they were counted as "buildings" from the title."""
    u = parse_units(text)
    assert u.scale == 1000.0 and u.unit in ("ALL", "EUR"), (text, u.unit, u.scale)


def test_a_thousand_marker_glued_to_a_longer_number_is_not_one():
    assert parse_units("2000Lekë").scale is None and parse_units("10,000Lekë").scale is None
