"""
Self-consistency utilities.

This module is designed to compute *stability* metrics across multiple
LLM samples, using the existing NyayaVerifier claim-level decisions.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set


def _normalize_text(s: str) -> str:
    s = (s or "").lower().strip()
    # Token-set normalization (order-insensitive) helps when the same claim
    # is expressed with different word order across LLM samples.
    words = re.findall(r"[a-z0-9]+", s)
    stop = {
        "the",
        "is",
        "of",
        "a",
        "an",
        "to",
        "in",
        "on",
        "at",
        "and",
        "or",
    }
    filtered = [w for w in words if w not in stop]
    filtered.sort()
    return " ".join(filtered)


def response_verified_bool(verification_result: Dict[str, Any]) -> bool:
    total = int(verification_result.get("total", 0) or 0)
    verified = int(verification_result.get("verified", 0) or 0)
    return total > 0 and verified == total


def verdict_tag(verification_result: Dict[str, Any]) -> str:
    verdict = str(verification_result.get("verdict", "") or "")
    if "FULLY CORRECT" in verdict:
        return "fully_correct"
    if "PARTIALLY CORRECT" in verdict:
        return "partially_correct"
    if "LARGELY INCORRECT" in verdict:
        return "largely_incorrect"
    if "NO_CLAIMS" in verdict:
        return "no_claims"
    return "unknown"


def _verified_claim_set(verification_result: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for cr in verification_result.get("results", []) or []:
        try:
            if cr.get("verified") is True:
                out.add(_normalize_text(str(cr.get("claim", "") or "")))
        except Exception:
            continue
    return out


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a and b:
        return 0.0
    if a and not b:
        return 0.0
    inter = len(a.intersection(b))
    union = len(a.union(b))
    return (inter / union) if union else 0.0


def compute_self_consistency_metrics(
    verification_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Computes:
      - verdict_majority_agreement: majority fraction over boolean correctness
      - verdict_tag_majority_agreement: majority fraction over Nyaya verdict tags
      - claim_verified_jaccard_avg: average pairwise Jaccard overlap of verified-claim sets
      - mean_verified_confidence: mean confidence of verified claims across runs
    """

    n = len(verification_results)
    if n == 0:
        return {
            "n": 0,
            "verdict_majority_agreement": 0.0,
            "verdict_tag_majority_agreement": 0.0,
            "claim_verified_jaccard_avg": 0.0,
            "mean_verified_confidence": None,
        }

    bool_labels = [response_verified_bool(r) for r in verification_results]
    true_count = sum(1 for x in bool_labels if x is True)
    false_count = n - true_count
    verdict_majority_agreement = max(true_count, false_count) / n

    tags = [verdict_tag(r) for r in verification_results]
    tag_counts: Dict[str, int] = {}
    for t in tags:
        tag_counts[t] = tag_counts.get(t, 0) + 1
    verdict_tag_majority_agreement = max(tag_counts.values()) / n if tag_counts else 0.0

    # Pairwise overlap over verified-claim sets.
    claim_sets = [_verified_claim_set(r) for r in verification_results]
    pairwise = []
    for i in range(n):
        for j in range(i + 1, n):
            pairwise.append(_jaccard(claim_sets[i], claim_sets[j]))
    claim_verified_jaccard_avg = sum(pairwise) / len(pairwise) if pairwise else 0.0

    # Confidence of verified claims.
    verified_conf = []
    for r in verification_results:
        for cr in r.get("results", []) or []:
            if cr.get("verified") is True:
                try:
                    verified_conf.append(float(cr.get("confidence")))
                except Exception:
                    continue
    mean_verified_confidence = (sum(verified_conf) / len(verified_conf)) if verified_conf else None

    return {
        "n": n,
        "verdict_majority_agreement": round(verdict_majority_agreement, 4),
        "verdict_tag_majority_agreement": round(verdict_tag_majority_agreement, 4),
        "claim_verified_jaccard_avg": round(claim_verified_jaccard_avg, 4),
        "mean_verified_confidence": mean_verified_confidence,
        "counts": {
            "verified_true_runs": true_count,
            "verified_false_runs": false_count,
        },
        "verdict_tag_counts": tag_counts,
    }

