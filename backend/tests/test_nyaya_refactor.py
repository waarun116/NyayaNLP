from __future__ import annotations

from backend.verifier.data.nyaya_principles import (
    ConfidenceLevel,
    EvidenceType,
    infer_evidence_type,
    map_confidence_level,
)
from backend.verifier.improved_verifier import CircuitBreaker, NyayaVerifier, TTLRUCache


def test_fix1_confidence_level_enum():
    assert map_confidence_level(85) == ConfidenceLevel.NISCHAYA
    assert map_confidence_level(60) == ConfidenceLevel.SAMSHAYA
    assert map_confidence_level(20) == ConfidenceLevel.VIPARYAYA


def test_fix1_evidence_type_enum():
    assert infer_evidence_type(3, True, False) == EvidenceType.DIRECT
    assert infer_evidence_type(2, False, False) == EvidenceType.INFERRED
    assert infer_evidence_type(1, False, False) == EvidenceType.TESTIMONIAL
    assert infer_evidence_type(3, True, True) == EvidenceType.CONFLICTING


def test_fix5_ttl_lru_cache():
    c = TTLRUCache(max_size=2, ttl_seconds=1)
    c.set("a", 1)
    c.set("b", 2)
    assert c.get("a") == 1
    c.set("c", 3)  # evicts least recently used "b"
    assert c.get("b") is None


def test_fix10_circuit_breaker():
    br = CircuitBreaker(fail_threshold=2, reset_after_s=1)
    assert br.allow("w")
    br.failure("w")
    br.failure("w")
    assert not br.allow("w")


def test_fix9_number_normalization():
    v = NyayaVerifier()
    assert v.normalize_number("about 1,200") == (1200.0, True)
    rng = v.normalize_number("10-20")
    assert rng is not None and abs(rng[0] - 15.0) < 1e-9


def test_fix6_claim_splitting_lists_and_compounds():
    v = NyayaVerifier()
    text = "Paris is the capital of France, and Berlin is the capital of Germany."
    claims = v.extract_claims(text)
    assert len(claims) >= 2


def test_fix2_page_disambiguation_prefers_relevant(monkeypatch):
    v = NyayaVerifier()

    class DummyPage:
        def __init__(self, title, summary):
            self.title = title
            self.summary = summary
            self.categories = {"Category:Architecture": None}

        def exists(self):
            return True

    def fake_page(title):
        if title == "Taj Mahal":
            return DummyPage("Taj Mahal", "Mausoleum in Agra commissioned by Shah Jahan.")
        return DummyPage(title, "Unrelated topic")

    monkeypatch.setattr(v.wiki, "page", fake_page)
    monkeypatch.setattr(v, "_wiki_search_candidates", lambda q, limit=8: ["India", "Taj Mahal", "Architecture"])
    p, title = v.find_best_page("Taj", "Who built Taj Mahal in Agra?")
    assert p is not None
    assert title == "Taj Mahal"


def test_fix3_consensus_required(monkeypatch):
    v = NyayaVerifier()
    monkeypatch.setattr(v, "_collect_sources", lambda claim, subject, question: {
        "local_kb": {"text": "Taj Mahal was commissioned by Shah Jahan.", "url": "x"},
        "dbpedia": {"text": "Taj Mahal commissioned by Shah Jahan.", "url": "y"},
        "wikidata": {"text": "Taj Mahal in Agra", "url": "z"},
        "duckduckgo": {"text": "", "url": None},
        "restcountries": {"text": "", "url": None},
    })
    monkeypatch.setattr(v, "_source_support", lambda claim, txt, title="": 90.0 if "Shah Jahan" in txt else 10.0)
    r = v.verify_claim("Taj Mahal was commissioned by Shah Jahan.", "who built taj mahal")
    assert r["verified"] is True


def test_fix7_threshold_calibration():
    v = NyayaVerifier()
    data = [
        {"question": "q1", "response": "The capital of France is Paris.", "expected_verified": True},
        {"question": "q2", "response": "The moon is made of cheese.", "expected_verified": False},
    ]
    # keep deterministic; avoid network in unit test
    v.verify_response = lambda q, r: {"verified": 1 if "Paris" in r else 0, "total": 1}
    out = v.evaluate(data)
    assert "best" in out
    assert 30 <= out["best"]["threshold"] <= 70


def test_fix8_subject_extraction_fallback():
    v = NyayaVerifier()
    s = v.get_subject("Taj Mahal was built by Shah Jahan.")
    assert ("Taj Mahal" in s) or ("Shah Jahan" in s) or (s == "Taj")


def test_leadership_alias_expansion_pm_and_full_form_equivalent():
    v = NyayaVerifier()
    q_short = v._normalize_user_question("pm of india")
    q_long = v._normalize_user_question("prime minister of india")
    assert "prime minister of india" in q_short
    assert "prime minister of india" in q_long
    office_short = v._parse_leadership_office_query(q_short)
    office_long = v._parse_leadership_office_query(q_long)
    assert office_short == office_long == ("prime minister", "india")
    qc_short = v._parse_question("pm of india")
    qc_long = v._parse_question("who is the prime minister of india")
    assert qc_short.target_attribute == qc_long.target_attribute == "prime minister"
    assert qc_short.target_entity == qc_long.target_entity == "india"
    assert v._anchor_wikipedia_query(qc_short) == v._anchor_wikipedia_query(qc_long) == "Prime Minister of india"


def test_leadership_role_detection_vice_president_not_president():
    v = NyayaVerifier()
    assert v._detect_role_phrase("vice president of india") == "vice president"
    assert v._detect_role_phrase("president of india") == "president"
    assert v._detect_role_phrase("who is vp of usa") == "vice president"
    office = v._parse_leadership_office_query("vice president of india")
    assert office == ("vice president", "india")
    qc_vp = v._parse_question("who is vice president of india")
    qc_p = v._parse_question("who is president of india")
    assert v._anchor_wikipedia_query(qc_vp) == "Vice President of india"
    assert v._anchor_wikipedia_query(qc_p) == "President of india"
    assert v._anchor_wikipedia_query(qc_vp) != v._anchor_wikipedia_query(qc_p)


def test_leadership_ngrams_prefer_office_title():
    v = NyayaVerifier()
    grams = v._generate_question_ngrams("pm of india")
    assert grams[0] == "prime minister of india"

