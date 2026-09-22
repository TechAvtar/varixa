"""Deterministic text statistics and structural observations. Pure functions.

These are measurements, not judgements: nothing here decides whether text is
machine-written. Later evidence rules may cite them as signals.
"""

import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from typing import Any

_WORD_RE = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*", re.UNICODE)
_SENTENCE_END_RE = re.compile(r"(?<=[.!?…])[\"'”’)\]]*\s+(?=[\"'“‘(\[]?[^\s])")
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.I)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_HEADING_MD_RE = re.compile(r"^\s{0,3}#{1,6}\s+\S")
_BULLET_RE = re.compile(r"^\s*(?:[-*•–]|\d+[.)])\s+\S")
_PUNCT = ".,;:!?\"'“”‘’()[]-–—…/"
_EMOJI_RE = re.compile(
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f900-\U0001f9ff]", re.UNICODE
)

TOP_NGRAM_LIMIT = 10


@dataclass
class TextStatistics:
    character_count: int = 0
    character_count_no_spaces: int = 0
    word_count: int = 0
    unique_word_count: int = 0
    type_token_ratio: float = 0.0
    sentence_count: int = 0
    paragraph_count: int = 0
    line_count: int = 0
    avg_sentence_length_words: float = 0.0
    longest_sentence_words: int = 0
    shortest_sentence_words: int = 0
    sentence_length_stddev: float = 0.0
    avg_word_length: float = 0.0
    avg_paragraph_length_sentences: float = 0.0
    punctuation_counts: dict[str, int] = field(default_factory=dict)
    punctuation_per_100_words: float = 0.0
    uppercase_ratio: float = 0.0
    digit_ratio: float = 0.0
    non_ascii_ratio: float = 0.0
    emoji_count: int = 0
    url_count: int = 0
    email_count: int = 0
    repeated_sentence_count: int = 0
    repeated_trigrams: list[dict[str, Any]] = field(default_factory=list)
    top_words: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TextStructure:
    markdown_headings: int = 0
    bullet_lines: int = 0
    numbered_lines: int = 0
    blank_line_count: int = 0
    max_line_length: int = 0
    has_multiple_paragraphs: bool = False
    starts_with_heading: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    for paragraph in split_paragraphs(text):
        flat = " ".join(paragraph.split())
        for s in _SENTENCE_END_RE.split(flat):
            s = s.strip()
            if s:
                parts.append(s)
    return parts


def split_paragraphs(text: str) -> list[str]:
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def words_of(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def compute_statistics(text: str) -> TextStatistics:
    st = TextStatistics()
    if not text:
        return st
    words = words_of(text)
    lowered = [w.lower() for w in words]
    sentences = split_sentences(text)
    paragraphs = split_paragraphs(text)
    lines = text.split("\n")

    st.character_count = len(text)
    st.character_count_no_spaces = sum(1 for c in text if not c.isspace())
    st.word_count = len(words)
    st.unique_word_count = len(set(lowered))
    st.type_token_ratio = round(st.unique_word_count / st.word_count, 4) if words else 0.0
    st.sentence_count = len(sentences)
    st.paragraph_count = len(paragraphs)
    st.line_count = len(lines)

    lengths = [len(words_of(s)) for s in sentences] or [0]
    st.avg_sentence_length_words = round(sum(lengths) / len(lengths), 2)
    st.longest_sentence_words = max(lengths)
    st.shortest_sentence_words = min(lengths)
    mean = sum(lengths) / len(lengths)
    st.sentence_length_stddev = round(
        (sum((x - mean) ** 2 for x in lengths) / len(lengths)) ** 0.5, 2
    )
    st.avg_word_length = round(sum(len(w) for w in words) / len(words), 2) if words else 0.0
    st.avg_paragraph_length_sentences = (
        round(st.sentence_count / st.paragraph_count, 2) if paragraphs else 0.0
    )

    punct = Counter(c for c in text if c in _PUNCT)
    st.punctuation_counts = {k: v for k, v in sorted(punct.items(), key=lambda kv: -kv[1])}
    st.punctuation_per_100_words = (
        round(sum(punct.values()) / st.word_count * 100, 2) if words else 0.0
    )

    letters = [c for c in text if c.isalpha()]
    st.uppercase_ratio = (
        round(sum(1 for c in letters if c.isupper()) / len(letters), 4) if letters else 0.0
    )
    st.digit_ratio = round(sum(1 for c in text if c.isdigit()) / len(text), 4)
    st.non_ascii_ratio = round(sum(1 for c in text if ord(c) > 127) / len(text), 4)
    st.emoji_count = len(_EMOJI_RE.findall(text))
    st.url_count = len(_URL_RE.findall(text))
    st.email_count = len(_EMAIL_RE.findall(text))

    sent_counter = Counter(s.lower() for s in sentences)
    st.repeated_sentence_count = sum(c - 1 for c in sent_counter.values() if c > 1)

    trigrams = Counter(" ".join(lowered[i : i + 3]) for i in range(len(lowered) - 2))
    st.repeated_trigrams = [
        {"phrase": p, "count": c} for p, c in trigrams.most_common(TOP_NGRAM_LIMIT) if c > 1
    ]
    st.top_words = [
        {"word": w, "count": c}
        for w, c in Counter(w for w in lowered if len(w) > 3).most_common(TOP_NGRAM_LIMIT)
    ]
    return st


def compute_structure(text: str) -> TextStructure:
    s = TextStructure()
    lines = text.split("\n")
    s.markdown_headings = sum(1 for ln in lines if _HEADING_MD_RE.match(ln))
    s.bullet_lines = sum(1 for ln in lines if _BULLET_RE.match(ln) and not re.match(r"^\s*\d", ln))
    s.numbered_lines = sum(1 for ln in lines if re.match(r"^\s*\d+[.)]\s+\S", ln))
    s.blank_line_count = sum(1 for ln in lines if not ln.strip())
    s.max_line_length = max((len(ln) for ln in lines), default=0)
    s.has_multiple_paragraphs = len(split_paragraphs(text)) > 1
    s.starts_with_heading = bool(lines and _HEADING_MD_RE.match(lines[0]))
    return s
