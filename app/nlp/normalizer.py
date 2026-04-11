"""Simple text normalization helpers for early event pipelines."""

from __future__ import annotations

import re


WHITESPACE_RE = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    collapsed = WHITESPACE_RE.sub(" ", text.strip())
    return collapsed.lower()


def score_headline_sentiment(headline: str) -> float:
    normalized = normalize_text(headline)
    positive_terms = ["급등", "상승", "호실적", "수주", "흑자", "성장"]
    negative_terms = ["급락", "하락", "적자", "악화", "정지", "리스크"]
    score = 0.0
    for term in positive_terms:
        if term in normalized:
            score += 1.0
    for term in negative_terms:
        if term in normalized:
            score -= 1.0
    return score
