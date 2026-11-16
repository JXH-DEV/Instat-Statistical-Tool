"""The forgiving topic search: how a word is cut down, how two words are scored, and how a whole query is ranked, in English and in Albanian,
with typos and partial words. The scoring is checked on a small made-up index so every number can be worked out by hand; the bundled index is
checked for the questions people actually type."""

from __future__ import annotations

import pytest

from instatkit.sources import search
from instatkit.sources.search import _match, _stem, _tokens, search_topics
from instatkit.sources.topic_index import Topic


# --- words ---
def test_words_are_lower_case_without_accents_and_without_filler_words():
    assert _tokens("The Statistics of Prices and Wages") == ["prices", "wages"]
    assert _tokens("Papunësia në Shqipëri") == ["papunesia", "shqiperi"]
    assert _tokens("Births, deaths & marriages (2024)") == ["births", "deaths", "marriages", "2024"]
    assert _tokens("") == [] and _tokens("the of and") == [] and _tokens("   ?!  ") == []


@pytest.mark.parametrize("word, stem", [
    ("prices", "price"), ("price", "price"), ("wages", "wage"), ("houses", "house"), ("cars", "car"), ("jobs", "job"),
    ("cities", "city"), ("companies", "company"),                                                   # "ies" becomes "y"
    ("boxes", "box"), ("taxes", "tax"), ("businesses", "business"),                                 # "es" only after s, x, z, ch, sh
    ("business", "business"), ("census", "census"), ("analysis", "analysis"), ("bus", "bus"), ("abs", "abs"),
    ("abcs", "abc"), ("abc", "abc"),                                                                # "s" needs a word of four letters
    ("shtepiat", "shtepi"), ("vendeve", "vende"), ("abcdi", "abcd"),
    ("xxxxve", "xxxx"), ("xxxve", "xxxve"),                                                         # a two-letter ending needs a stem of four letters
    ("abci", "abci"), ("benefits", "benef"), ("benefit", "benef"), ("", ""),                        # the plural goes first, then the Albanian ending
])
def test_a_word_loses_an_english_plural_and_then_an_albanian_ending_but_never_all_of_itself(word, stem):
    assert _stem(word) == stem


@pytest.mark.parametrize("plural, singular", [
    ("prices", "price"), ("offices", "office"), ("marriages", "marriage"), ("phones", "phone"), ("tables", "table"), ("vehicles", "vehicle"),
    ("cars", "car"), ("jobs", "job"), ("benefits", "benefit"), ("deposits", "deposit"), ("cities", "city"), ("companies", "company"),
    ("countries", "country"), ("municipalities", "municipality"), ("taxes", "tax"), ("businesses", "business"),
])
def test_the_plural_and_the_singular_of_the_words_in_the_index_are_one_word(plural, singular):
    assert _stem(plural) == _stem(singular) and _match(plural, singular) == 0.95 and _match(singular, plural) == 0.95


# --- two words ---
@pytest.mark.parametrize("query, term, score", [
    ("price", "price", 1.0),
    ("papunesia", "papunesia", 1.0),
    ("wages", "wage", 0.95),                                  # same stem
    ("births", "birth", 0.95),
    ("pop", "population", 0.85),                              # the start of a word
    ("tot", "total", 0.85),
    ("prices", "price", 0.95),
    ("prices", "pricey", 0.85),                               # the stem of the query starts the term
    ("vendev", "vendeve", 0.85),                              # the query starts the term, the stems do not
    ("po", "population", 0.0),                                # two letters are too few to count as the start of a word
    ("to", "total", 0.0),
    ("inflasion", "inflation", 0.75),                         # a typo
    ("anual", "annual", 0.75),                                # five letters is the shortest word allowed a typo
    ("gods", "goods", 0.0),                                   # four is not
    ("annuel", "annual", 0.0),                                # similarity 0.833: just under the line
    ("xyz", "population", 0.0),
])
def test_how_well_a_typed_word_matches_a_word_of_the_index(query, term, score):
    assert _match(query, term) == score


def test_a_typo_is_accepted_from_a_similarity_of_84_percent():
    assert _match("abcdefghi", "abcdXfghiY") == 0.75           # 8 of 9 and 10 letters in common: 16/19 = 0.842
    assert _match("abcdefghi", "abcdXfgYiZ") == 0.0            # 7 of 9 and 10: 14/19 = 0.737


# --- ranking, by hand ---
@pytest.fixture
def small_index(monkeypatch):
    topics = [
        Topic("t1", "a", "Alpha bravo"),
        Topic("t1", "b", "Delta", ("alpha", "tango victor")),
        Topic("t2", "c", "Echo", ("whiskey",)),
        Topic("t2", "d", "Foxtrot"),
        Topic("t3", "e", "Golf", ("the of",)),                  # a keyword that is all filler: nothing to match
    ]
    themes = {"t1": ("Zulu theme", "Zulu tema"), "t2": ("Kilo", "Lima"), "t3": ("Mike", "Novembre")}
    monkeypatch.setattr(search, "TOPICS", topics)
    monkeypatch.setattr(search, "THEMES", themes)
    monkeypatch.setattr(search, "POPULAR", frozenset())
    return topics


def scores(query, **kw):
    return {h.topic.slug: h.score for h in search_topics(query, **kw)}


def test_a_word_in_the_name_counts_three_a_keyword_two_and_a_half_and_the_theme_one(small_index):
    assert scores("alpha") == pytest.approx({"a": 3.0, "b": 2.5})                  # name (3) beats keyword (2.5)
    assert scores("whiskey") == pytest.approx({"c": 2.5})
    assert scores("zulu") == pytest.approx({"a": 0.5, "b": 0.5})                   # theme only (1) and no word of the topic matches: half
    assert scores("lima") == pytest.approx({"c": 0.5, "d": 0.5})                   # the Albanian name of the theme is searched too


def test_only_the_best_match_of_each_typed_word_counts_and_each_word_adds_up(small_index):
    assert scores("alpha bravo") == pytest.approx({"a": 6.0, "b": 2.5 * 0.75})     # a: 3+3; b: the keyword 2.5 + nothing, one of two words found
    assert scores("alpha delta") == pytest.approx({"a": 3.0 * 0.75, "b": 5.5})


def test_a_word_that_matches_nothing_lowers_the_score_in_proportion(small_index):
    assert scores("alpha qqqq") == pytest.approx({"a": 3.0 * 0.75, "b": 2.5 * 0.75})
    assert scores("alpha qqqq jjjj") == pytest.approx({"a": 3.0 * (0.5 + 0.5 / 3), "b": 2.5 * (0.5 + 0.5 / 3)})


def test_a_match_with_the_theme_alone_does_not_count_as_found(small_index):
    assert scores("zulu alpha") == pytest.approx({"a": (1.0 + 3.0) * 0.75, "b": (1.0 + 2.5) * 0.75})


def test_a_whole_multi_word_query_equal_to_one_keyword_scores_four_per_word(small_index):
    assert scores("tango victor") == pytest.approx({"b": 8.0})
    assert scores("victor tango") == pytest.approx({"b": 5.0})                     # another order is no longer the keyword; each word gives 2.5
    assert scores("tango") == pytest.approx({"b": 2.5})                            # one word alone is never "the whole keyword"


def test_the_whole_query_is_compared_with_the_keyword_without_regard_to_case_or_spacing(small_index):
    assert scores("TANGO   Victor") == pytest.approx({"b": 8.0})
    assert scores("  Tango Victor ") == pytest.approx({"b": 8.0})


def test_a_keyword_made_only_of_filler_words_is_ignored_and_matches_nothing(small_index):
    assert scores("golf") == pytest.approx({"e": 3.0})
    assert scores("the of") == {} and scores("of") == {}


def test_popular_topics_get_a_small_bonus_that_decides_ties(monkeypatch, small_index):
    monkeypatch.setattr(search, "POPULAR", frozenset({"t2/d"}))
    assert scores("kilo") == pytest.approx({"c": 0.5, "d": 0.8})
    assert [h.topic.slug for h in search_topics("kilo")] == ["d", "c"]                 # Echo would come first without the bonus


def test_equal_scores_are_listed_by_name(small_index):
    assert [h.topic.slug for h in search_topics("lima")] == ["c", "d"]             # Echo before Foxtrot


def test_the_best_hits_come_first_and_the_limit_cuts_the_list(small_index):
    assert [h.topic.slug for h in search_topics("alpha")] == ["a", "b"]
    assert [h.topic.slug for h in search_topics("alpha", limit=1)] == ["a"]
    assert search_topics("alpha", limit=0) == []


def test_the_default_limit_is_eight(monkeypatch):
    many = [Topic("t1", f"s{i}", f"Alpha{chr(97 + i)}x") for i in range(10)]
    monkeypatch.setattr(search, "TOPICS", many)
    monkeypatch.setattr(search, "THEMES", {"t1": ("One", "Nje")})
    monkeypatch.setattr(search, "POPULAR", frozenset())
    assert len(search_topics("alpha")) == 8 and len(search_topics("alpha", limit=20)) == 10


def test_a_query_with_nothing_to_search_for_finds_nothing(small_index):
    assert search_topics("") == [] and search_topics("   ") == [] and search_topics("statistics the") == [] and search_topics("???") == []


# --- the questions people type, against the bundled index ---
@pytest.mark.parametrize("query, name", [
    ("inflation", "Consumer Price Index"), ("inflasion", "Consumer Price Index"), ("çmimet", "Consumer Price Index"),
    ("cmimet", "Consumer Price Index"), ("PRICES", "Consumer Price Index"),
    ("unemployment", "Employment and unemployment from LFS"), ("papunësia", "Employment and unemployment from LFS"),
    ("tourism arrivals", "Tourism Statistics"), ("turizmi", "Tourism Statistics"),
    ("wages", "Wages"), ("paga", "Wages"),
    ("GDP", "National Accounts"),
    ("trade", "International Trade in Goods"), ("eksporte", "International Trade in Goods"),
    ("popullsia", "Population"), ("population", "Population"),
    ("births", "Births, deaths and marriages"), ("lindjet", "Births, deaths and marriages"),
    ("constructon", "Construction"),
])
def test_the_question_people_type_leads_to_the_page_they_mean(query, name):
    assert search_topics(query, limit=3)[0].topic.name == name


def test_albanian_letters_are_optional_in_the_query():
    assert [h.topic.key for h in search_topics("papunësia")] == [h.topic.key for h in search_topics("papunesia")]
    assert [h.topic.key for h in search_topics("ÇMIMET")] == [h.topic.key for h in search_topics("cmimet")]


def test_gibberish_finds_nothing_and_a_filler_word_alone_finds_nothing():
    assert search_topics("zzzzqqq") == [] and search_topics("the") == [] and search_topics("statistics") == []


def test_every_hit_is_ranked_best_first_and_scores_are_positive():
    hits = search_topics("price", limit=20)
    assert len(hits) > 3 and all(h.score > 0 for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)
