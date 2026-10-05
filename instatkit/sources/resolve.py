"""Decide what the user typed into the search box: a topic, an INSTAT page, a theme, a file link, or nothing usable."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

from ..i18n import tr
from .fetch import is_instat_host
from .page_links import DATA_EXT, normalize_url
from .search import Hit, search_topics
from .topic_index import THEMES, Topic, topic_for_url, topics_in_theme


@dataclass
class Resolution:
    kind: str  # empty | topics | topic | theme | page | file | unsupported
    query: str = ""
    url: str | None = None
    hits: list[Hit] = field(default_factory=list)
    topic: Topic | None = None
    topics: list[Topic] = field(default_factory=list)
    message: str | None = None
    external: bool = False


_URLISH = re.compile(r"^(?:https?://|(?:www\.)?(?:databaza\.)?instat\.gov\.al)", re.I)


def looks_like_url(text: str) -> bool:
    return bool(_URLISH.match(text.strip()))


def resolve(text: str) -> Resolution:
    q = (text or "").strip()
    if not q:
        return Resolution("empty")
    if not looks_like_url(q):
        hits = search_topics(q)
        if not hits:
            return Resolution("topics", q, message=tr("No INSTAT topic matched. Try a broader word such as 'prices', 'labour', "
                                                      "'population', 'tourism' or 'trade', or paste a link."))
        return Resolution("topics", q, hits=hits)

    url = q if re.match(r"^https?://", q, re.I) else "https://" + q
    try:
        parts = urlparse(url)
        norm = normalize_url(url, url)
    except ValueError:  # e.g. an unterminated IPv6 literal
        return Resolution("unsupported", q, message=tr("This is not a valid web address."))
    host = (parts.hostname or "").lower()
    path = parts.path
    if host.startswith("databaza."):
        return Resolution("unsupported", q, url,
                          message=tr("INSTAT's statistical database (PxWeb) is not supported. Use the Excel files on the topic pages instead."))
    if path.lower().endswith(DATA_EXT):
        return Resolution("file", q, norm, external=not is_instat_host(host))
    if path.lower().endswith((".pdf", ".doc", ".docx", ".zip")):
        return Resolution("unsupported", q, norm, message=tr("Only Excel (.xlsx and .xls) and CSV files can be analysed, not PDFs or other documents."))
    if not is_instat_host(host):
        return Resolution("unsupported", q, norm, message=tr("Paste a direct link to an Excel or CSV file, or a page of INSTAT (instat.gov.al)."),
                          external=True)
    topic = topic_for_url(norm)
    if topic:
        return Resolution("topic", q, topic.url, topic=topic)
    m = re.match(r"^/en/themes/([^/]+)/?$", path)
    if m and m.group(1) in THEMES:
        return Resolution("theme", q, norm, topics=topics_in_theme(m.group(1)))
    return Resolution("page", q, norm)
