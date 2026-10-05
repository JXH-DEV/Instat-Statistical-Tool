"""Forgiving topic search over the bundled index: English or Albanian, typos and partial words allowed."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from ..semantics.textnorm import fold
from .topic_index import POPULAR, THEMES, TOPICS, Topic

_STOP = frozenset(["the", "of", "and", "in", "on", "for", "by", "to", "a", "an", "statistics", "statistika", "e", "te", "dhe", "i", "per", "ne"])


@dataclass(frozen=True)
class Hit:
    topic: Topic
    score: float


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", fold(text)) if t not in _STOP]


def _stem(tok: str) -> str:
    for suffix in ("ies", "es", "s", "ve", "it", "at", "ja", "ia", "i"):
        if len(tok) > len(suffix) + 3 and tok.endswith(suffix):
            return tok[: -len(suffix)]
    return tok


def _match(q: str, term: str) -> float:
    """0..1 similarity of a query token to a term token."""
    if q == term:
        return 1.0
    qs, ts = _stem(q), _stem(term)
    if qs == ts:
        return 0.95
    if len(q) >= 3 and (term.startswith(q) or ts.startswith(qs)):
        return 0.85
    if len(q) >= 5 and SequenceMatcher(None, q, term).ratio() >= 0.84:
        return 0.75
    return 0.0


def search_topics(query: str, *, limit: int = 8) -> list[Hit]:
    """Rank INSTAT sub-topics for a free-text query such as 'inflation', 'papunësia' or 'tourism arrivals'."""
    q_tokens = _tokens(query)
    if not q_tokens:
        return []
    whole_query = fold(query).strip()
    hits: list[Hit] = []
    for topic in TOPICS:
        name_tokens = _tokens(topic.name)
        theme_tokens = _tokens(" ".join(THEMES[topic.theme]))
        keywords = [(kw, _tokens(kw)) for kw in topic.keywords]
        all_tokens = name_tokens + [t for _kw, tokens in keywords for t in tokens]
        score = 0.0
        for qt in q_tokens:
            candidates = [_match(qt, tok) * 3.0 for tok in name_tokens] + [_match(qt, tok) for tok in theme_tokens]
            for kw, tokens in keywords:
                if not tokens:
                    continue
                if len(q_tokens) > 1 and whole_query == fold(kw):  # the whole multi-word query is one keyword
                    candidates.append(4.0)
                else:
                    candidates.append(max(_match(qt, tok) for tok in tokens) * 2.5)
            score += max(candidates, default=0.0)
        if score > 0:
            coverage = sum(1 for qt in q_tokens if any(_match(qt, t) for t in all_tokens)) / len(q_tokens)
            hits.append(Hit(topic, score * (0.5 + 0.5 * coverage) + (0.3 if topic.key in POPULAR else 0.0)))
    hits.sort(key=lambda h: (-h.score, h.topic.name))
    return hits[:limit]
