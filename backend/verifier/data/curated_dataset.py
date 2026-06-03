from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from backend.verifier import semantic_support


class CuratedDataset:
    """
    Tier-1 curated facts dataset.

    Schema (countries.json):
    {
      "domain": "countries",
      "facts": [
        {"entity":"India","attribute":"capital","value":"New Delhi","aliases":["Delhi"]},
        ...
      ]
    }
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        base = Path(__file__).resolve().parents[3]
        self.path = path or (base / "data" / "curated_facts" / "countries.json")
        self.generated_path = base / "data" / "curated_facts" / "countries_generated.json"
        self.geopolitical_path = base / "data" / "curated_facts" / "countries_geopolitical_2026.json"
        self.facts: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        generated = []
        geopolitical = []
        overrides = []
        if self.generated_path.exists():
            gd = json.loads(self.generated_path.read_text(encoding="utf-8"))
            generated = list(gd.get("facts", []))
        if self.geopolitical_path.exists():
            pd = json.loads(self.geopolitical_path.read_text(encoding="utf-8"))
            geopolitical = list(pd.get("facts", []))
        if self.path.exists():
            od = json.loads(self.path.read_text(encoding="utf-8"))
            overrides = list(od.get("facts", []))

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for fact in generated:
            k = (self.normalize(str(fact.get("entity", ""))), self.normalize(str(fact.get("attribute", ""))))
            if k[0] and k[1]:
                merged[k] = fact
        for fact in geopolitical:
            k = (self.normalize(str(fact.get("entity", ""))), self.normalize(str(fact.get("attribute", ""))))
            if k[0] and k[1]:
                merged[k] = fact
        for fact in overrides:
            k = (self.normalize(str(fact.get("entity", ""))), self.normalize(str(fact.get("attribute", ""))))
            if k[0] and k[1]:
                merged[k] = fact
        self.facts = list(merged.values())

    @staticmethod
    def normalize(text: str) -> str:
        t = (text or "").lower().strip()
        t = re.sub(r"[^\w\s]", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t

    def _claim_target_value(self, claim: str, fact: dict[str, Any]) -> Optional[str]:
        n = self.normalize(claim)
        value = str(fact.get("value", "")).strip()
        aliases = [str(a).strip() for a in fact.get("aliases", []) if str(a).strip()]
        for cand in [value] + aliases:
            if self.normalize(cand) in n:
                return cand
        return None

    def exact_match(self, claim: str) -> Optional[Dict[str, Any]]:
        n = self.normalize(claim)
        for fact in self.facts:
            entity = self.normalize(str(fact.get("entity", "")))
            attribute = self.normalize(str(fact.get("attribute", "")))
            value = self.normalize(str(fact.get("value", "")))
            aliases = [self.normalize(str(a)) for a in fact.get("aliases", [])]
            if entity and attribute and entity in n and attribute in n and (value in n or any(a and a in n for a in aliases)):
                return fact
        return None

    def semantic_match(self, claim: str, min_score: float = 0.70) -> Optional[Tuple[Dict[str, Any], float]]:
        model = semantic_support.get_sentence_model()
        if model is None or not self.facts:
            return None
        try:
            from sentence_transformers import util
        except Exception:
            return None

        claim_text = self.normalize(claim)
        best_fact = None
        best_score = -1.0
        claim_emb = model.encode(claim_text, convert_to_tensor=True)
        for fact in self.facts:
            fact_sentence = f"{fact.get('entity','')} {fact.get('attribute','')} {fact.get('value','')}"
            emb = model.encode(self.normalize(fact_sentence), convert_to_tensor=True)
            score = float(util.cos_sim(claim_emb, emb).item())
            if score > best_score:
                best_score = score
                best_fact = fact
        if best_fact is not None and best_score >= min_score:
            return best_fact, best_score
        return None

