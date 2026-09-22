"""Selects distinctive phrases to query a source-search provider with.

Deterministic and cheap: prefer sentences with longer, rarer-looking words,
avoid boilerplate, and cap the number of phrases so provider cost stays bounded.
"""

import re

from app.services.text.statistics import split_sentences, words_of

DEFAULT_MAX_PHRASES = 5
PHRASE_WORDS = 10
MIN_SENTENCE_WORDS = 6
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "by",
        "from",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "they",
        "them",
        "their",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "his",
        "her",
        "not",
        "no",
        "yes",
        "if",
        "then",
        "than",
        "so",
        "such",
        "very",
        "can",
        "could",
        "may",
        "might",
        "will",
        "would",
        "shall",
        "should",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "into",
        "over",
        "under",
        "about",
        "after",
        "before",
        "between",
        "through",
        "during",
        "without",
        "within",
    ]
)
_BOILERPLATE_RE = re.compile(r"^(dear|regards|sincerely|thanks|thank you|hello|hi)\b", re.I)


def _distinctiveness(words: list[str]) -> float:
    content = [w for w in words if w.lower() not in _STOPWORDS]
    if not content:
        return 0.0
    avg_len = sum(len(w) for w in content) / len(content)
    return avg_len * (len(content) / len(words))


def select_distinctive_phrases(text: str, *, max_phrases: int = DEFAULT_MAX_PHRASES) -> list[str]:
    scored: list[tuple[float, int, str]] = []
    for index, sentence in enumerate(split_sentences(text)):
        words = words_of(sentence)
        if len(words) < MIN_SENTENCE_WORDS or _BOILERPLATE_RE.match(sentence):
            continue
        phrase = " ".join(words[:PHRASE_WORDS])
        scored.append((_distinctiveness(words), index, phrase))
    # Highest distinctiveness first; ties keep document order. Dedupe case-insensitively.
    scored.sort(key=lambda s: (-s[0], s[1]))
    seen: set[str] = set()
    phrases: list[str] = []
    for _, _, phrase in scored:
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
        if len(phrases) >= max_phrases:
            break
    return phrases
