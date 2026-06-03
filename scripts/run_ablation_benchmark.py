"""
Ablation benchmark runner (toy dataset by default).

Computes precision/recall/F1 at the *response level* using:
  predicted_verified = (verified_claims == total_claims && total_claims > 0)
  gold_verified      = expected_response_verified

This script is designed to be fast and offline-friendly, and provides a clean
foundation for replacing the toy dataset with a public benchmark later.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Ensure `backend/` is importable when running this script directly.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.verifier.improved_verifier import NyayaVerifier
from backend.verifier.self_consistency import response_verified_bool


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _set_env_flag(name: str, disabled: bool) -> None:
    if disabled:
        os.environ[name] = "1"
    else:
        os.environ.pop(name, None)


def _compute_prf1(tp: int, fp: int, tn: int, fn: int) -> Dict[str, float]:
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + tn) / (tp + fp + tn + fn) if (tp + fp + tn + fn) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }


def _evaluate_config(verifier: NyayaVerifier, dataset: List[Dict[str, Any]]) -> Tuple[Dict[str, float], List[Dict[str, Any]]]:
    tp = fp = tn = fn = 0
    per_item: List[Dict[str, Any]] = []

    for it in dataset:
        question = it.get("question") or ""
        response = it.get("response") or ""
        gold = bool(it.get("expected_response_verified"))

        vr = verifier.verify_response_with_nyaya(question, response)
        pred = response_verified_bool(vr)

        if pred and gold:
            tp += 1
        elif pred and not gold:
            fp += 1
        elif (not pred) and (not gold):
            tn += 1
        else:
            fn += 1

        per_item.append(
            {
                "id": it.get("id"),
                "gold_verified": gold,
                "pred_verified": pred,
                "nyaya_verdict": vr.get("verdict"),
                "verified_claims": vr.get("verified"),
                "total_claims": vr.get("total"),
            }
        )

    prf = _compute_prf1(tp=tp, fp=fp, tn=tn, fn=fn)
    prf["counts"] = {"tp": tp, "fp": fp, "tn": tn, "fn": fn}
    return prf, per_item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=str,
        default="backend/verifier/data/benchmarks/toy_benchmark.jsonl",
        help="JSONL dataset with fields: id, question, response, expected_response_verified.",
    )
    parser.add_argument("--run-semantic", action="store_true", help="Include semantic-enabled configurations (slower first run).")
    parser.add_argument("--out", type=str, default="data/results/ablation_benchmark_results.json")
    args = parser.parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = (Path(__file__).resolve().parents[1] / dataset_path).resolve()

    dataset = _read_jsonl(dataset_path)

    # Default configs (fast, no embedding downloads).
    configs: List[Dict[str, Any]] = [
        {"name": "lexical+wikidata (semantic OFF)", "disable_semantic": True, "disable_wikidata": False},
        {"name": "lexical only (wikidata OFF)", "disable_semantic": True, "disable_wikidata": True},
    ]
    if args.run_semantic:
        configs.extend(
            [
                {"name": "hybrid + wikidata (semantic ON)", "disable_semantic": False, "disable_wikidata": False},
                {"name": "hybrid only (semantic ON, wikidata OFF)", "disable_semantic": False, "disable_wikidata": True},
            ]
        )

    all_out: List[Dict[str, Any]] = []
    for cfg in configs:
        print(f"Running config: {cfg['name']}")
        _set_env_flag("NYAYA_DISABLE_SEMANTIC", cfg["disable_semantic"])
        _set_env_flag("NYAYA_DISABLE_WIKIDATA", cfg["disable_wikidata"])

        verifier = NyayaVerifier()
        prf, per_item = _evaluate_config(verifier, dataset)
        all_out.append(
            {
                "config": cfg,
                "metrics": prf,
                "per_item": per_item,
            }
        )
        print(f"  F1={prf['f1']} Accuracy={prf['accuracy']} counts={prf['counts']}")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (Path(__file__).resolve().parents[1] / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"generated_at": ts, "results": all_out}, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()

