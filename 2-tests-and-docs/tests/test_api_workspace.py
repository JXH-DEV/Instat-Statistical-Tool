"""The functions behind the page's requests, called directly: page listings and downloads (with the network replaced), closing files, the
Explore tab with filters, search and paging, and the replies to wrong input."""

from __future__ import annotations

import hashlib

import pytest

from instatkit import demo, i18n
from instatkit.sources.fetch import Downloaded, FetchError
from instatkit.sources.page_links import FileLink, PageListing
from instatkit.web import api
from instatkit.web.common import ApiError

from .conftest import process_demo

PAGE = "https://www.instat.gov.al/al/temat/tregu-i-punës/punësimi/"
FILE_URL = "https://www.instat.gov.al/media/1/punesimi.xlsx"


class FakeFetcher:
    def __init__(self):
        self.pages: list[str] = []
        self.downloads: list[str] = []
        self.error: Exception | None = None
        self.data = b""

    def get_html(self, url):
        self.pages.append(url)
        if self.error:
            raise self.error
        return "<html></html>"

    def download(self, url):
        self.downloads.append(url)
        if self.error:
            raise self.error
        return Downloaded(url, "cpi.xlsx", self.data, hashlib.sha256(self.data).hexdigest(), len(self.data), "xlsx")


@pytest.fixture
def ws():
    return api.Workspace(FakeFetcher())


# --- page listings ---
@pytest.mark.parametrize("url", ["ftp://www.instat.gov.al/x", "https://example.com/", "javascript:alert(1)", "https://instat.gov.al.evil.example/",
                                 "", "  ", "www.instat.gov.al/page", "file:///etc/passwd"])
def test_only_pages_on_instat_can_be_listed(ws, url):
    with pytest.raises(ApiError) as caught:
        api.listing(ws, url)
    assert str(caught.value) == "Only pages on instat.gov.al can be opened here." and caught.value.status == 400
    assert ws.fetcher.pages == []


def listing_of(*files, n_pdfs=2):
    return PageListing(PAGE, "Employment", list(files), n_pdfs)


def test_a_listing_names_every_file_with_its_section_and_whether_it_is_the_old_format(ws, monkeypatch):
    monkeypatch.setattr(api, "parse_page", lambda html, url: listing_of(
        FileLink(FILE_URL, "Employed persons", ".xlsx", "punesimi.xlsx", "Figures"), FileLink(FILE_URL + "2", "Old table", ".xls", "vjeter.xls")))
    reply = api.listing(ws, PAGE)
    assert reply["title"] == "Employment" and reply["url"] == PAGE and reply["pdfs"] == 2
    assert reply["files"] == [
        {"url": FILE_URL, "label": "Employed persons", "ext": ".xlsx", "filename": "punesimi.xlsx", "section": "Figures", "legacy": False},
        {"url": FILE_URL + "2", "label": "Old table", "ext": ".xls", "filename": "vjeter.xls", "section": "Other", "legacy": True}]


def test_a_listing_is_fetched_once_and_kept_for_an_hour(ws, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api, "parse_page", lambda html, url: listing_of())
    api.listing(ws, PAGE)
    clock[0] += api.LISTING_TTL - 1
    api.listing(ws, PAGE)
    assert len(ws.fetcher.pages) == 1
    clock[0] += 2
    api.listing(ws, PAGE)
    assert len(ws.fetcher.pages) == 2
    api.listing(ws, PAGE.replace("punësimi", "pagat"))
    assert len(ws.fetcher.pages) == 3                                                             # another page is another listing


def test_a_page_that_cannot_be_opened_is_a_bad_gateway_with_the_reason(ws):
    ws.fetcher.error = FetchError("timed out")
    with pytest.raises(ApiError) as caught:
        api.listing(ws, PAGE)
    assert (str(caught.value), caught.value.status) == ("The page could not be opened: timed out", 502)
    ws.fetcher.error = None
    assert api.listing(ws, PAGE)["files"] == []                                                  # a failure is not remembered


# --- downloads ---
def test_a_file_from_instat_is_downloaded_read_and_opened(ws):
    ws.fetcher.data = demo.DEMOS["cpi"][2]()
    reply = api.load_url(ws, FILE_URL, label="Prices")
    assert ws.fetcher.downloads == [FILE_URL] and reply["closed"] == []
    pf = ws.files[reply["key"]]
    assert pf.ok and pf.source.label == "Prices" and pf.source.url == FILE_URL


@pytest.mark.parametrize("url", ["https://example.com/a.xlsx", "http://localhost/a.xlsx", "https://instat.gov.al.evil.example/a.xlsx"])
def test_a_file_from_elsewhere_needs_the_user_to_trust_the_source(ws, url):
    with pytest.raises(ApiError) as caught:
        api.load_url(ws, url)
    assert str(caught.value).startswith("This file is not on instat.gov.al. Confirm that you trust the source") and caught.value.status == 400
    assert ws.fetcher.downloads == []
    ws.fetcher.data = demo.DEMOS["cpi"][2]()
    assert api.load_url(ws, url, allow_external=True)["key"] in ws.files
    assert ws.fetcher.downloads == [url]


def test_a_failed_download_is_a_bad_gateway_with_the_reason(ws):
    ws.fetcher.error = FetchError("HTTP 404")
    with pytest.raises(ApiError) as caught:
        api.load_url(ws, FILE_URL)
    assert (str(caught.value), caught.value.status) == ("HTTP 404", 502)


def test_an_unknown_demo_is_not_found(ws):
    with pytest.raises(ApiError) as caught:
        api.load_demo(ws, "nope")
    assert (str(caught.value), caught.value.status) == ("Unknown demo.", 404)


@pytest.mark.parametrize("name, expected", [("report.xlsx", "report.xlsx"), ("..\\..\\evil name?.xlsx", "evil name_.xlsx"), ("a/b/c.xlsx", "c.xlsx"),
                                            ("", "upload.xlsx"), ("x" * 300 + ".xlsx", "x" * 120)])
def test_an_uploaded_name_is_a_plain_file_name(ws, name, expected):
    reply = api.load_upload(ws, demo.DEMOS["cpi"][2](), name)
    assert ws.files[reply["key"]].source.filename == expected


# --- open files ---
def test_closing_one_file_or_all(ws):
    keys = [api.load_demo(ws, n)["key"] for n in ("cpi", "gdp", "trade")]
    assert [f["key"] for f in api.close_file(ws, keys[1])["files"]] == [keys[0], keys[2]]
    assert api.close_file(ws, "unknown")["files"] and len(ws.files) == 2                        # an unknown key changes nothing
    assert api.close_file(ws, None)["files"] == [] and ws.files == {}


def test_the_state_lists_the_demos_and_the_tables_of_each_open_file(ws):
    api.load_demo(ws, "cpi")
    state = api.state(ws)
    assert [d[0] for d in state["demos"]] == list(demo.DEMOS) and state["language"] == "en"
    [f] = state["files"]
    assert f["ok"] and f["kind"] == "demo" and f["tables"][0]["i"] == 0 and 0 < f["tables"][0]["confidence"] <= 1


# --- the Explore tab ---
@pytest.fixture(scope="module")
def population():
    return process_demo("population").tables[0]


@pytest.fixture(scope="module")
def cpi():
    return process_demo("cpi").tables[0]


def all_options(reply):
    return {d["name"]: [o[0] for o in d["options"]] for d in reply["dims"]}


def test_explore_starts_with_the_totals_as_lines_when_there_is_a_time_axis(cpi):
    reply = api.explore(cpi, {})
    assert reply["kind"] == "lines" and reply["kinds"] == ["lines", "bars", "table"] and reply["svg"].startswith("<svg")
    [product] = reply["dims"]
    assert product["selected"][0] == "Total" and len(product["options"]) == 7
    assert reply["lo"] == reply["periods"][0][0] and reply["hi"] == reply["periods"][-1][0]


def test_explore_without_a_time_axis_offers_bars_and_a_table_only():
    reply = api.explore(process_demo("wages").tables[0], {})
    assert reply["kinds"] == ["bars", "table"] and reply["kind"] == "bars" and reply["caption"] == "Values for 2023"
    assert reply["lo"] is None and reply["hi"] is None


def test_a_kind_that_is_not_offered_falls_back_to_the_first(cpi):
    assert api.explore(cpi, {"kind": "pie"})["kind"] == "lines"
    assert api.explore(cpi, {"kind": "table"})["kind"] == "table" and api.explore(cpi, {"kind": "table"})["svg"] == ""


def test_choosing_categories_changes_the_series_and_the_rows(cpi):
    everything = all_options(api.explore(cpi, {}))
    one = api.explore(cpi, {"filters": {"product": ["Total"]}, "kind": "table"})
    many = api.explore(cpi, {"filters": everything, "kind": "table"})
    assert many["total"] == one["total"] * 7 and one["shown"] == one["total"]
    assert api.explore(cpi, {"filters": {"product": ["not a product"]}})["dims"][0]["selected"] == []


def test_filters_that_match_nothing_say_so(cpi):
    reply = api.explore(cpi, {"filters": {"product": []}})
    assert (reply["caption"], reply["kind"], reply["rows"], reply["total"], reply["svg"]) == ("Nothing matches these filters.", "table", [], 0, "")


def test_the_period_range_is_applied_and_put_in_order(cpi):
    periods = [p[0] for p in api.explore(cpi, {})["periods"]]
    lo, hi = periods[10], periods[20]
    wanted = api.explore(cpi, {"lo": lo, "hi": hi, "kind": "table"})
    swapped = api.explore(cpi, {"lo": hi, "hi": lo, "kind": "table"})
    assert (wanted["lo"], wanted["hi"]) == (lo, hi) == (swapped["lo"], swapped["hi"]) and wanted["rows"] == swapped["rows"]
    assert wanted["total"] == 11 * len(wanted["dims"][0]["selected"])                            # eleven periods of each chosen series
    assert api.explore(cpi, {"lo": "nonsense", "hi": hi})["lo"] == periods[0]               # an unknown end is ignored


def test_a_measure_that_does_not_exist_falls_back_to_the_first(cpi):
    reply = api.explore(cpi, {"measure": "nothing"})
    assert reply["measure"] == reply["measures"][0][0]


def test_too_many_series_are_cut_at_24_and_the_page_is_told(population):
    reply = api.explore(population, {"filters": all_options(api.explore(population, {})), "kind": "lines"})
    assert reply["caption"] == "There are too many series to draw clearly. Narrow the filters (the first 24 are shown)."
    assert reply["total"] == 24 * len(reply["periods"])


def test_the_rows_of_the_table_are_capped_but_the_total_is_not():
    pt = process_demo("lfs").tables[0]
    reply = api.explore(pt, {"filters": all_options(api.explore(pt, {})), "kind": "table"})
    assert reply["total"] == 240 and reply["shown"] == min(240, api.EXPLORE_ROWS) and len(reply["rows"]) == reply["shown"]


def test_explore_can_hand_over_the_table_as_csv(cpi):
    reply = api.explore(cpi, {"csv": True})
    assert list(reply) == ["csv"]
    lines = reply["csv"].splitlines()
    assert lines[0] == "product,product_orig,code,level,parent_code,is_total,measure,period,freq,value,flag,unit,attr_weights,src_ref,label"
    assert len(lines) == api.explore(cpi, {"kind": "table"})["total"] + 1


def test_the_albanian_table_shows_albanian_category_names(cpi):
    english = api.explore(cpi, {"kind": "table"})
    with i18n.using("sq"):
        albanian = api.explore(cpi, {"kind": "table"})
    col = english["columns"].index("product")
    assert english["rows"][0][col] == "Total" and albanian["rows"][0][col] == "Gjithsej"
    assert albanian["total"] == english["total"]


def test_an_empty_table_cannot_be_explored(cpi, monkeypatch):
    monkeypatch.setattr(cpi.table, "df", cpi.table.df.iloc[0:0])
    with pytest.raises(ApiError) as caught:
        api.explore(cpi, {})
    assert str(caught.value) == "There is no data to explore."


# --- the data tab ---
def test_data_paging_search_and_sort(ws, cpi):
    key = api.load_demo(ws, "cpi")["key"]
    pf, pt = ws.get(key)
    first = api.data_page(ws, key, 0, pt, {})
    assert first["size"] == 100 and len(first["rows"]) == 100 and first["page"] == 0 and first["total"] > 100
    second = api.data_page(ws, key, 0, pt, {"page": "1"})
    assert second["rows"] != first["rows"] and second["page"] == 1
    last_page = (first["total"] - 1) // 100
    assert len(api.data_page(ws, key, 0, pt, {"page": last_page})["rows"]) == first["total"] - 100 * last_page
    assert api.data_page(ws, key, 0, pt, {"page": last_page + 1})["rows"] == []
    found = api.data_page(ws, key, 0, pt, {"q": "FOOD"})
    assert 0 < found["total"] < first["total"]
    assert api.data_page(ws, key, 0, pt, {"q": "no such text"})["total"] == 0
    col = first["columns"].index("value")
    ascending = [r[col] for r in api.data_page(ws, key, 0, pt, {"sort": "value"})["rows"] if r[col] is not None]
    descending = [r[col] for r in api.data_page(ws, key, 0, pt, {"sort": "value", "desc": "1"})["rows"] if r[col] is not None]
    assert ascending == sorted(ascending) and descending == sorted(descending, reverse=True) and ascending[0] <= descending[-1]


def test_the_wide_layout_has_one_column_per_period(ws):
    key = api.load_demo(ws, "cpi")["key"]
    pf, pt = ws.get(key)
    wide = api.data_page(ws, key, 0, pt, {"layout": "wide"})
    assert len(wide["columns"]) > 20 and wide["total"] < api.data_page(ws, key, 0, pt, {})["total"]


@pytest.mark.parametrize("page", ["x", "1.5", -1, "-1"])
def test_a_page_number_that_is_not_a_whole_number_of_zero_or_more_is_refused(ws, page):
    key = api.load_demo(ws, "gdp")["key"]
    pf, pt = ws.get(key)
    with pytest.raises(ApiError) as caught:
        api.data_page(ws, key, 0, pt, {"page": page})
    assert str(caught.value) in ("Page must be a whole number.", "Page must be 0 or more.")


# --- exports and corrections ---
def test_an_unknown_export_is_not_found(ws):
    key = api.load_demo(ws, "gdp")["key"]
    with pytest.raises(ApiError) as caught:
        api.export(ws, key, 0, "pdf")
    assert (str(caught.value), caught.value.status) == ("Unknown export.", 404)


def test_export_names_say_what_they_are_and_which_table(ws):
    key = api.load_demo(ws, "gdp")["key"]
    names = {kind: api.export(ws, key, 0, kind)[0] for kind in ("report", "tidy", "wide", "xlsx", "sqlite", "zip", "diagnostic")}
    assert names["xlsx"].endswith(".xlsx") and names["tidy"].endswith("-tidy.csv") and names["report"].endswith("-report.html")
    assert names["diagnostic"].endswith("-diagnostic.json") and names["zip"].endswith("-bundle.zip") and names["sqlite"].endswith(".sqlite")
    assert len(set(names.values())) == 7
    with pytest.raises(ApiError):
        api.export(ws, key, 5, "tidy")


def test_a_file_that_has_lost_its_workbook_cannot_be_corrected(ws):
    key = api.load_demo(ws, "gdp")["key"]
    ws.files[key].workbook = None
    with pytest.raises(ApiError) as caught:
        api.reread(ws, key, 0, {"data_first": 5, "data_last": 9})
    assert (str(caught.value), caught.value.status) == ("That file is no longer open. Load it again.", 404)
    pf, pt = ws.get(key)
    assert api.read_info(pf, pt)["grid"] is None


@pytest.mark.parametrize("answers, message", [
    ({"data_first": 0, "data_last": 9}, "Data: first row must be 1 or more."),
    ({"data_first": 5, "data_last": 0}, "Data: first row must be 1 or more."),
    ({"data_first": 9, "data_last": 5}, "The last data row cannot be above the first one."),
    ({"data_first": 5, "data_last": 9, "header_first": 4, "header_last": 2}, "The last header row cannot be above the first one."),
    ({"data_first": 5, "data_last": 9, "layout": "sideways"}, "Unknown layout."),
    ({"data_first": "five", "data_last": 9}, "Data: first row must be a whole number."),
])
def test_a_correction_that_makes_no_sense_is_refused_and_the_file_is_kept(ws, answers, message):
    key = api.load_demo(ws, "gdp")["key"]
    before = ws.files[key]
    with pytest.raises(ApiError) as caught:
        api.reread(ws, key, 0, answers)
    assert str(caught.value) == message and ws.files[key] is before


def test_resetting_a_correction_goes_back_to_the_automatic_reading(ws):
    key = api.load_demo(ws, "cpi")["key"]
    pf, pt = ws.get(key)
    info = api.read_info(pf, pt)["override"]
    assert info["active"] is False
    api.reread(ws, key, 0, {"data_first": info["data_first"] + 1, "data_last": info["data_last"], "header_first": info["header_first"],
                            "header_last": info["header_last"], "n_labels": info["n_labels"], "layout": "auto"})
    corrected = ws.get(key)[0]
    assert api.read_info(*ws.get(key))["override"]["active"] is True and corrected is not pf
    api.reread(ws, key, 0, {"reset": True})
    assert api.read_info(*ws.get(key))["override"]["active"] is False
    assert len(ws.files) == 1


def test_a_correction_may_name_a_single_data_row(ws):
    key = api.load_demo(ws, "cpi")["key"]
    info = api.read_info(*ws.get(key))["override"]
    api.reread(ws, key, 0, {"data_first": info["data_first"], "data_last": info["data_first"], "header_first": info["header_first"],
                            "header_last": info["header_last"], "n_labels": info["n_labels"], "layout": "auto"})
    assert len(set(ws.get(key)[1].table.df["src_ref"].str.extract(r"(\d+)$")[0])) == 1             # every value comes from that one sheet row


def test_a_listing_older_than_exactly_an_hour_is_fetched_again(ws, monkeypatch):
    clock = [5000.0]
    monkeypatch.setattr(api.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(api, "parse_page", lambda html, url: listing_of())
    api.listing(ws, PAGE)
    clock[0] += api.LISTING_TTL - 0.001
    api.listing(ws, PAGE)
    assert len(ws.fetcher.pages) == 1
    clock[0] += 0.001
    api.listing(ws, PAGE)
    assert len(ws.fetcher.pages) == 2
