"""
REST Countries Source
Free public API for country-level facts (capital, population, currencies, languages).

IMPORTANT: Only used when the question/claim clearly asks for country-level geo facts.
Uses whole-word matching for country names (avoids matching "india" inside "Indian"/territory names).
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

import requests

# When question/claim matches this, RestCountries evidence is allowed (strict default).
_GEO_QUESTION = re.compile(
    r"(?i)\b(capital|population|currency|currencies|languages?|citizens?|people)\b.*\b(of|in)\b",
)
_GEO_CLAIM = re.compile(
    r"(?i)\b(capital|population|currency|currencies|languages?)\s+of\b",
)
_GEO_SHORT = re.compile(
    r"(?i)^(what|which)\s+(is|are)\s+the\s+(capital|population|currency|languages?)\b",
)


class RestCountriesSource:
    def __init__(self) -> None:
        self.endpoint = "https://restcountries.com/v3.1/name/"
        self.cache: dict[str, Dict[str, Any]] = {}
        # Multi-word first (sorted by length desc when iterating)
        self.country_hints: List[str] = sorted(
            [
                "united states",
                "united kingdom",
                "new zealand",
                "south africa",
                "south korea",
                "north korea",
                "saudi arabia",
                "south sudan",
                "costa rica",
                "dominican republic",
                "el salvador",
                "sri lanka",
                "burkina faso",
                "czech republic",
                "france",
                "india",
                "china",
                "japan",
                "germany",
                "italy",
                "spain",
                "brazil",
                "canada",
                "australia",
                "russia",
                "mexico",
                "argentina",
                "indonesia",
                "pakistan",
                "bangladesh",
                "nigeria",
                "egypt",
                "turkey",
                "iran",
                "iraq",
                "afghanistan",
                "nepal",
                "philippines",
                "vietnam",
                "thailand",
                "poland",
                "ukraine",
                "usa",
                "uk",
            ],
            key=len,
            reverse=True,
        )

    def should_use_restcountries(
        self, claim: str, subject_hint: Optional[str], question: Optional[str]
    ) -> bool:
        """Only enable RestCountries for explicit country-fact queries.

        This prevents irrelevant country-style evidence being attached to
        non-geo questions like "who built X".
        """
        if os.environ.get("NYAYA_RESTCOUNTRIES_LOOSE", "").lower() in ("1", "true", "yes"):
            return True
        q = (question or "").strip()
        c = (claim or "").strip()
        strict_keywords = re.compile(r"(?i)\b(country|capital|population)\b")
        return bool(strict_keywords.search(q) or strict_keywords.search(c))

    def _hint_matches(self, hint: str, txt: str) -> bool:
        """Whole-word / phrase match only — never match 'india' inside 'indian' or territory names."""
        if not hint or not txt:
            return False
        h = hint.lower().strip()
        t = txt.lower()
        if " " in h:
            return re.search(rf"(?i)\b{re.escape(h)}\b", t) is not None
        # Word boundary: "india" matches India but not Indian / British Indian Ocean…
        return re.search(rf"(?i)\b{re.escape(h)}\b", t) is not None

    def _detect_country(self, claim: str, subject_hint: Optional[str]) -> Optional[str]:
        txt = f"{subject_hint or ''} {claim or ''}"
        for c in self.country_hints:
            if self._hint_matches(c, txt):
                if c == "usa":
                    return "united states"
                if c == "uk":
                    return "united kingdom"
                return c
        # Do not treat arbitrary subjects (e.g. "Taj Mahal") as country names — major source of noise.
        if os.environ.get("NYAYA_RESTCOUNTRIES_LOOSE", "").lower() in ("1", "true", "yes"):
            h = (subject_hint or "").strip()
            if h and len(h) < 48 and re.match(r"^[A-Za-z\s\-]+$", h):
                return h
        return None

    def _pick_best_match(self, arr: List[Dict[str, Any]], requested: str) -> Dict[str, Any]:
        """Prefer exact name match (e.g. India vs British Indian Ocean Territory)."""
        if len(arr) == 1:
            return arr[0]
        req = (requested or "").lower().strip()
        best: Optional[Dict[str, Any]] = None
        best_score = -999
        for c in arr:
            common = ((c.get("name") or {}).get("common") or "").lower()
            official = ((c.get("name") or {}).get("official") or "").lower()
            score = 0
            if common == req:
                score += 200
            elif req and common.startswith(req + " "):
                score += 80
            elif req and req == common[: len(req)] and len(req) >= 4:
                score += 40
            if "british indian ocean" in common or "indian ocean territory" in common:
                score -= 150
            if req == "india" and common == "india":
                score += 300
            if req == "united states" and common in ("united states", "united states of america"):
                score += 300
            if score > best_score:
                best_score = score
                best = c
        return best if best is not None else arr[0]

    def get_evidence_for_claim(
        self, claim: str, subject_hint: Optional[str] = None, question: Optional[str] = None
    ) -> Dict[str, Any]:
        if not self.should_use_restcountries(claim, subject_hint, question):
            return {"text": "", "url": None}

        country = self._detect_country(claim, subject_hint)
        if not country:
            return {"text": "", "url": None}
        key = country.lower().strip()
        if key in self.cache:
            return self.cache[key]

        try:
            url = self.endpoint + requests.utils.quote(country)
            res = requests.get(url, timeout=8)
            if res.status_code != 200:
                out = {"text": "", "url": None}
                self.cache[key] = out
                return out
            arr = res.json()
            if not isinstance(arr, list) or not arr:
                out = {"text": "", "url": None}
                self.cache[key] = out
                return out
            c0 = self._pick_best_match(arr, key)
            name = (c0.get("name", {}) or {}).get("common", country)
            capital = ", ".join(c0.get("capital", []) or [])
            population = c0.get("population")
            region = c0.get("region")
            currencies = ", ".join((c0.get("currencies", {}) or {}).keys())
            languages = ", ".join((c0.get("languages", {}) or {}).values())

            parts = [f"Country: {name}"]
            if capital:
                parts.append(f"Capital: {capital}")
            if population is not None:
                parts.append(f"Population: {population}")
            if region:
                parts.append(f"Region: {region}")
            if currencies:
                parts.append(f"Currencies: {currencies}")
            if languages:
                parts.append(f"Languages: {languages}")

            text = ". ".join(parts)
            out = {"text": text, "url": url}
            self.cache[key] = out
            return out
        except Exception:
            out = {"text": "", "url": None}
            self.cache[key] = out
            return out
