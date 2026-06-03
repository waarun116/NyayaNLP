"""
Tiny sanity benchmark for the hybrid verifier (no Ollama).

From project root:

  set NYAYA_DISABLE_SEMANTIC=1   # optional: faster, lexical+Wikidata only
  python scripts/verify_benchmark.py

With semantic (first run downloads ~80MB model):

  python scripts/verify_benchmark.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Default: skip heavy model for quick checks unless user unsets this
if "NYAYA_DISABLE_SEMANTIC" not in os.environ:
    os.environ["NYAYA_DISABLE_SEMANTIC"] = "1"


def main() -> None:
    from backend.verifier.improved_verifier import NyayaVerifier

    v = NyayaVerifier()
    cases = [
        ("The capital of France is Paris.", True),
        ("The Moon is made of cheese.", False),
        ("Water boils at 100 degrees Celsius at sea level.", True),
        ("Einstein was a theoretical physicist.", True),
    ]
    print("Hybrid verifier smoke (semantic disabled unless you cleared NYAYA_DISABLE_SEMANTIC)\n")
    ok = 0
    for claim, expect_verified in cases:
        r = v.verify_claim(claim)
        passed = r["verified"] == expect_verified
        ok += int(passed)
        flag = "PASS" if passed else "FAIL"
        print(f"  [{flag}] verified={r['verified']} (want {expect_verified}) conf={r['confidence']}")
        print(f"        sources={r.get('sources_used')} sem={r.get('semantic_score')}")
        print(f"        {claim[:70]}...\n")
    print(f"Result: {ok}/{len(cases)} cases matched expected verified flag")
    if ok < len(cases):
        sys.exit(1)


if __name__ == "__main__":
    main()
