"""
Self-consistency evaluation using the existing NyayaVerifier.

Default mode: uses the provided `responses` in the dataset file (offline-friendly).
Optional mode: generates responses with Ollama if `--generate` is enabled.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

# Ensure `backend/` is importable when running this script directly.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.verifier.improved_verifier import NyayaVerifier
from backend.verifier.self_consistency import (
    compute_self_consistency_metrics,
    response_verified_bool,
)


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def _set_env_flag(name: str, enabled: bool) -> None:
    # Convention: NYAYA_DISABLE_X=1 means disabled.
    if enabled:
        os.environ[name] = "1"
    else:
        os.environ.pop(name, None)


def _generate_with_ollama(model: str, question: str, temperature: float) -> str:
    from ollama import Client

    client = Client()
    resp = client.chat(
        model=model,
        messages=[{"role": "user", "content": question}],
        options={"temperature": float(temperature)},
    )
    return (resp.get("message") or {}).get("content") or ""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=str,
        default="backend/verifier/data/benchmarks/toy_self_consistency.jsonl",
        help="JSONL dataset with fields: id, question, responses(optional), expected_response_verified(optional).",
    )
    parser.add_argument("--model", type=str, default="llama3", help="Ollama model name (used only with --generate).")
    parser.add_argument("--n-samples", type=int, default=3, help="Number of samples per question (with --generate).")
    parser.add_argument(
        "--temperatures",
        type=str,
        default="0.2,0.7,1.0",
        help="Comma-separated temperatures for generation (with --generate).",
    )
    parser.add_argument("--generate", action="store_true", help="Generate responses with Ollama instead of using dataset responses.")
    parser.add_argument("--disable-semantic", action="store_true", help="Disable semantic similarity fusion.")
    parser.add_argument("--disable-wikidata", action="store_true", help="Disable Wikidata evidence.")
    parser.add_argument("--out", type=str, default="data/results/self_consistency_results.json")
    args = parser.parse_args()

    _set_env_flag("NYAYA_DISABLE_SEMANTIC", args.disable_semantic)
    _set_env_flag("NYAYA_DISABLE_WIKIDATA", args.disable_wikidata)

    dataset_path = Path(args.dataset)
    if not dataset_path.is_absolute():
        dataset_path = (Path(__file__).resolve().parents[1] / dataset_path).resolve()

    items = _read_jsonl(dataset_path)
    verifier = NyayaVerifier()

    temperatures = [float(x.strip()) for x in args.temperatures.split(",") if x.strip()]
    if not temperatures:
        temperatures = [0.7]

    results: List[Dict[str, Any]] = []
    for it in items:
        item_id = it.get("id")
        question = it.get("question") or ""
        expected = it.get("expected_response_verified")
        provided_responses = it.get("responses") or []

        responses: List[str] = []
        if not args.generate:
            responses = [str(x) for x in provided_responses]
        else:
            for i in range(args.n_samples):
                t = temperatures[i % len(temperatures)]
                try:
                    responses.append(_generate_with_ollama(args.model, question, t))
                except Exception as e:
                    responses.append(f"Error: {e}")

        verification_results: List[Dict[str, Any]] = []
        for r in responses:
            verification_results.append(verifier.verify_response_with_nyaya(question, r))

        metrics = compute_self_consistency_metrics(verification_results)
        majority_pred = response_verified_bool(verification_results[0])
        # Majority over boolean correctness:
        bools = [response_verified_bool(x) for x in verification_results]
        true_count = sum(1 for b in bools if b is True)
        majority_pred = true_count >= (len(bools) / 2)

        item_out: Dict[str, Any] = {
            "id": item_id,
            "question": question,
            "n_responses": len(responses),
            "metrics": metrics,
            "majority_predicted_verified": majority_pred,
            "expected_response_verified": expected,
        }
        results.append(item_out)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (Path(__file__).resolve().parents[1] / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"generated_at": ts, "results": results}, indent=2), encoding="utf-8")

    # Human-friendly summary
    print("Self-consistency summary (toy dataset)")
    for it in results:
        m = it["metrics"]
        print(
            f"  id={it['id']} verdict_majority_agreement={m['verdict_majority_agreement']} "
            f"claim_verified_jaccard_avg={m['claim_verified_jaccard_avg']} "
            f"majority_pred_verified={it['majority_predicted_verified']} expected={it['expected_response_verified']}"
        )

    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()

