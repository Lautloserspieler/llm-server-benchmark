"""STT-Metriken (WER, CER).

Zunaechst minimale Implementierung ohne externe Abhaengigkeiten. WER wird ueber
Levenshtein-Distanz auf Wortebene berechnet. CER analog auf Zeichenebene.
"""
from __future__ import annotations

from typing import Any


def _levenshtein(a: list[str], b: list[str]) -> int:
    """Klassischer Levenshtein auf Listen von Tokens/Zeichen."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, start=1):
        curr = [i]
        for j, y in enumerate(b, start=1):
            cost = 0 if x == y else 1
            curr.append(min(curr[-1] + 1, prev[j] + 1, prev[j - 1] + cost))
        prev = curr
    return prev[-1]


def _normalize_text(text: str) -> str:
    """Kleinbuchstaben, entfernt mehrfache Leerzeichen, trimmt."""
    return " ".join(text.lower().split())


def word_error_rate(reference: str, hypothesis: str) -> float:
    """Word Error Rate zwischen Referenz und Hypothese (0.0 .. 1.0+)."""
    ref = _normalize_text(reference).split()
    hyp = _normalize_text(hypothesis).split()
    if not ref:
        return 1.0 if hyp else 0.0
    return _levenshtein(ref, hyp) / len(ref)


def char_error_rate(reference: str, hypothesis: str) -> float:
    """Character Error Rate zwischen Referenz und Hypothese."""
    ref = _normalize_text(reference)
    hyp = _normalize_text(hypothesis)
    if not ref:
        return 1.0 if hyp else 0.0
    return _levenshtein(list(ref), list(hyp)) / len(ref)


def compute_metrics(reference: str, hypothesis: str, requested: list[Any]) -> dict[str, float]:
    """Berechnet die angefragten Metriken fuer ein Transkriptionspaar."""
    out: dict[str, float] = {}
    names = set()
    for m in requested:
        name = m.name if hasattr(m, "name") else m.get("name")
        if name:
            names.add(name)
    if "wer" in names:
        out["wer"] = word_error_rate(reference, hypothesis)
    if "cer" in names:
        out["cer"] = char_error_rate(reference, hypothesis)
    return out
