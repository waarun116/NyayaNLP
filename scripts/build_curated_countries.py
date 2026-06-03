from __future__ import annotations

import json
from pathlib import Path

import requests


def build() -> int:
    url = "https://restcountries.com/v3.1/all"
    fields = "name,capital,population,currencies,cca2,unMember,independent"
    resp = requests.get(f"{url}?fields={fields}", timeout=30)
    resp.raise_for_status()
    rows = resp.json()

    facts = []
    for r in rows:
        name = ((r.get("name") or {}).get("common") or "").strip()
        if not name:
            continue
        # Keep broad country coverage; include UN members and independent states.
        if not (r.get("unMember") or r.get("independent")):
            continue

        source_url = f"https://restcountries.com/v3.1/name/{requests.utils.quote(name)}"
        capitals = r.get("capital") or []
        if capitals:
            facts.append(
                {
                    "entity": name,
                    "attribute": "capital",
                    "value": capitals[0],
                    "aliases": capitals[1:] if len(capitals) > 1 else [],
                    "source_name": "RestCountries (UN-aligned metadata)",
                    "source_url": source_url,
                    "evidence_snippet": f"The capital of {name} is {capitals[0]}",
                }
            )

        pop = r.get("population")
        if isinstance(pop, int) and pop > 0:
            facts.append(
                {
                    "entity": name,
                    "attribute": "population",
                    "value": str(pop),
                    "aliases": [],
                    "source_name": "RestCountries (UN-aligned metadata)",
                    "source_url": source_url,
                    "evidence_snippet": f"The population of {name} is {pop}",
                }
            )

        curr = (r.get("currencies") or {}).keys()
        curr_list = [c for c in curr if c]
        if curr_list:
            facts.append(
                {
                    "entity": name,
                    "attribute": "currency",
                    "value": curr_list[0],
                    "aliases": curr_list[1:],
                    "source_name": "RestCountries (UN-aligned metadata)",
                    "source_url": source_url,
                    "evidence_snippet": f"The currency code of {name} is {curr_list[0]}",
                }
            )

    out = {
        "domain": "countries",
        "generated_from": url,
        "facts": facts,
    }
    root = Path(__file__).resolve().parents[1]
    path = root / "data" / "curated_facts" / "countries_generated.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(facts)} facts to {path}")
    return len(facts)


if __name__ == "__main__":
    build()

