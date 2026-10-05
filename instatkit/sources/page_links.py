"""Parse an INSTAT sub-topic page (HTML) into the list of Excel files it offers.

All knowledge about the website's markup lives in this one module. The pages are server-rendered; files appear
as ``/media/<id>/<name>.xlsx|xls`` links, often twice (once with the label, once without), grouped in tabs
(Latest / Figures / Publications / Methods). Parsing uses the standard library only.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import quote, unquote, urljoin, urlparse

EXCEL_EXT = (".xlsx", ".xls", ".xlsm")
DATA_EXT = EXCEL_EXT + (".csv",)
_VOID = frozenset(["area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"])
_SITE_SUFFIX = re.compile(r"\s+[|\-–—]\s+(?=[^|\-–—]*(?:instat|institute|statistik|statistics)[^|\-–—]*$)", re.I)
_TAB_HREF = re.compile(r"^#tab\d+$")


@dataclass
class FileLink:
    url: str
    label: str
    ext: str
    filename: str
    section: str | None = None  # the tab it sits in: Figures, Publications, ...

    @property
    def is_legacy_xls(self) -> bool:
        return self.ext == ".xls"


@dataclass
class PageListing:
    url: str
    title: str
    files: list[FileLink] = field(default_factory=list)
    n_pdfs: int = 0


def normalize_url(href: str, base: str) -> str:
    """Absolute URL with NFC-normalised, UTF-8 percent-encoded path (INSTAT filenames contain ë, ç ...)."""
    absolute = urljoin(base, href.strip())
    parts = urlparse(absolute)
    path = unicodedata.normalize("NFC", unquote(parts.path))
    encoded = quote(path, safe="/:@!$&'()*+,;=-._~")
    return parts._replace(path=encoded, fragment="").geturl()


def filename_of(url: str) -> str:
    return unquote(urlparse(url).path.rsplit("/", 1)[-1])


def _prettify(filename: str) -> str:
    stem = re.sub(r"\.\w+$", "", filename)
    return re.sub(r"[-_]+", " ", stem).strip().capitalize()


class _Page(HTMLParser):
    """Collects what the listing needs: the title, the h1s and every link with its text and the ids around it."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.h1: list[str] = []
        self.links: list[tuple[str, str, tuple[str, ...]]] = []  # (href, text, ids of the enclosing elements)
        self._stack: list[tuple[str, str]] = []  # (tag, id) of the open elements
        self._href: str | None = None
        self._ids: tuple[str, ...] = ()
        self._text: list[str] = []
        self._in_title = self._in_h1 = False
        self._h1_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1, self._h1_text = True, []
        elif tag == "a" and a.get("href") is not None:
            self._href, self._text = a["href"] or "", []
            self._ids = tuple(i for _t, i in self._stack if i)
        if tag not in _VOID:
            self._stack.append((tag, a.get("id") or ""))

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
            self.h1.append(" ".join("".join(self._h1_text).split()))
        elif tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join("".join(self._text).split()), self._ids))
            self._href = None
        for i in range(len(self._stack) - 1, -1, -1):  # close the matching element and anything left open inside it
            if self._stack[i][0] == tag:
                del self._stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        if self._in_h1:
            self._h1_text.append(data)
        if self._href is not None:
            self._text.append(data)


def _page_title(page: _Page, page_url: str) -> str:
    """The page's own name. A menu or footer can carry an ``h1`` of its own ("Legal Bases"), so an ``h1`` only counts
    when it agrees with the ``<title>``; otherwise the ``<title>`` (minus the site suffix) wins."""
    head = _SITE_SUFFIX.split(" ".join(page.title.split()), maxsplit=1)[0].strip()
    for h in page.h1:
        if h and head and (h.lower() in head.lower() or head.lower() in h.lower()):
            return h
    return head or next((h for h in page.h1 if h), "") or page_url


def parse_page(html: str, page_url: str) -> PageListing:
    """Extract Excel/CSV links (deduplicated, label preferred over empty duplicate) from a page."""
    page = _Page()
    page.feed(html)
    page.close()
    tabs: dict[str, str] = {}  # {'tab2': 'Figures', ...} from the in-page tab navigation
    for href, text, _ids in page.links:
        if _TAB_HREF.match(href) and text:
            tabs.setdefault(href[1:], text)

    def section_of(ids: tuple[str, ...]) -> str | None:
        return next((tabs[i] for i in reversed(ids) if i in tabs), None)

    files: dict[str, FileLink] = {}
    n_pdfs = 0
    for href, text, ids in page.links:
        if href.startswith("#"):
            continue
        try:
            url = normalize_url(href, page_url)
            parts = urlparse(url)
        except ValueError:  # a malformed address, e.g. an unterminated IPv6 literal
            continue
        if parts.scheme not in ("http", "https") or not parts.hostname:  # javascript:, mailto:, file: ...
            continue
        path = parts.path.lower()
        if path.endswith(".pdf"):
            n_pdfs += 1
        elif path.endswith(DATA_EXT):
            ext = "." + path.rsplit(".", 1)[-1]
            cur = files.get(url)
            if cur is None:
                files[url] = FileLink(url, text or _prettify(filename_of(url)), ext, filename_of(url), section_of(ids))
            elif text and (not cur.label or cur.label == _prettify(cur.filename)):
                cur.label = text
                cur.section = cur.section or section_of(ids)
    return PageListing(page_url, _page_title(page, page_url), list(files.values()), n_pdfs)
