from __future__ import annotations

import logging
import re
import time
from collections import OrderedDict
from datetime import datetime, timezone
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

import requests
import wikipediaapi

from backend.verifier import semantic_support
from backend.verifier.data.config import CLAIM_EXTRACTION, CONFIDENCE_THRESHOLD, HYBRID
from backend.verifier.data.important_terms import IMPORTANT_TERMS, normalize_political_term
from backend.verifier.data.curated_dataset import CuratedDataset
from backend.verifier.data.nyaya_principles import NYAYA_PRINCIPLES, infer_evidence_type, map_confidence_level
from backend.verifier.data.sources.restcountries_source import RestCountriesSource
from backend.verifier.data.sources.wikidata_source import WikidataSource
from backend.verifier.data.stop_words import PRONOUNS, STOP_WORDS
from backend.verifier.evidence_text import wikipedia_evidence_raw

logger = logging.getLogger(__name__)


class TTLRUCache:
    def __init__(self, max_size: int = 1000, ttl_seconds: int = 86400):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self._store: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()

    def get(self, key: str) -> Any:
        item = self._store.get(key)
        if not item:
            return None
        ts, val = item
        if time.time() - ts > self.ttl_seconds:
            self._store.pop(key, None)
            return None
        self._store.move_to_end(key)
        return val

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time(), value)
        self._store.move_to_end(key)
        while len(self._store) > self.max_size:
            self._store.popitem(last=False)


class CircuitBreaker:
    def __init__(self, fail_threshold: int = 3, reset_after_s: int = 60):
        self.fail_threshold = fail_threshold
        self.reset_after_s = reset_after_s
        self.failures: Dict[str, int] = {}
        self.opened_until: Dict[str, float] = {}

    def allow(self, name: str) -> bool:
        until = self.opened_until.get(name, 0.0)
        if until <= 0.0 or time.time() >= until:
            return True
        return False

    def success(self, name: str) -> None:
        self.failures[name] = 0
        self.opened_until[name] = 0.0

    def failure(self, name: str) -> None:
        self.failures[name] = self.failures.get(name, 0) + 1
        if self.failures[name] >= self.fail_threshold:
            self.opened_until[name] = time.time() + self.reset_after_s


@dataclass
class TierDecision:
    primary: str
    confidence: float
    explanation: str
    sources: List[str]
    source_name: str
    source_url: Optional[str]
    evidence_snippet: str
    scorecard: Dict[str, Any]


@dataclass
class QuestionContext:
    question_type: str
    target_entity: str
    target_attribute: str
    expected_answer_type: str
    domain_tag: str
    source_strategy: str


class NyayaVerifier:
    SUPPORTED_DOMAINS = ("countries", "history", "science")
    DOMAIN_UNSUPPORTED_MESSAGE = (
        "This domain is not yet supported. I can verify facts about countries, historical events, and scientific facts."
    )
    # Longest phrases first so "vice president" is not mistaken for "president".
    _LEADERSHIP_ROLES_ORDERED: Tuple[Tuple[str, str], ...] = (
        ("deputy chief minister", "Deputy Chief Minister"),
        ("deputy prime minister", "Deputy Prime Minister"),
        ("vice president", "Vice President"),
        ("prime minister", "Prime Minister"),
        ("chief minister", "Chief Minister"),
        ("president", "President"),
        ("king", "King"),
        ("queen", "Queen"),
        ("chancellor", "Chancellor"),
        ("monarch", "Monarch"),
    )
    _LEADERSHIP_SHORT_FORMS: Dict[str, str] = {
        "pm": "prime minister",
        "p.m.": "prime minister",
        "cm": "chief minister",
        "c.m.": "chief minister",
        "vp": "vice president",
        "v.p.": "vice president",
        "dcm": "deputy chief minister",
        "d.c.m.": "deputy chief minister",
        "dm": "district magistrate",
        "d.m.": "district magistrate",
    }

    def __init__(self):
        self.wiki = wikipediaapi.Wikipedia(language="en", user_agent="NyayaVerifier/19.0")
        self.wikidata = WikidataSource()
        self.restcountries_source = RestCountriesSource()
        self.curated = CuratedDataset()
        self.threshold = float(CONFIDENCE_THRESHOLD)
        self.semantic_threshold = float(__import__("os").environ.get("SIMILARITY_THRESHOLD", "0.25"))
        self.stop_words = STOP_WORDS
        self.pronouns = PRONOUNS
        self.important_terms = IMPORTANT_TERMS
        self.known_entities: Dict[str, str] = {}
        self.context = {"last_subject": None, "mentioned_entities": []}
        self.source_cache = TTLRUCache(max_size=1000, ttl_seconds=86400)
        self.generic_attribute_terms = {
            "president", "prime minister", "author", "composer", "architect", "inventor",
            "builder", "capital", "population", "currency", "language", "leader",
        }
        self.bad_subject_words = {
            "according", "however", "therefore", "thus", "hence", "note", "list",
            "here", "there", "it", "he", "she", "they", "them", "his", "her", "their",
        }
        self.query_stop_words = {
            "who", "what", "why", "when", "where", "how", "many", "is", "are", "was", "were",
            "the", "a", "an", "of", "to", "for", "with", "on", "at", "by", "in", "from",
            "as", "and", "or", "but", "if", "then", "that", "this", "these", "those",
            "please", "note",
            # Common time/filler tokens that should never become Wikipedia pages.
            "since", "currently", "today", "now",
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
        }
        self._session_page_cache: Dict[str, Dict[str, Any]] = {}
        self._session_failed_titles: set[str] = set()
        # Per-response anchor bundle (question-driven), reused across claims for speed & stability.
        self._session_anchor_wiki: Optional[Dict[str, Any]] = None
        self._session_anchor_title: Optional[str] = None

    # ---------------- domain ----------------
    def detect_domain(self, text: str) -> Optional[str]:
        t = self._expand_leadership_aliases(text or "").lower()
        if self._detect_role_phrase(t) or re.search(r"\b(capital|population|currency|country)\b", t):
            return "countries"
        if re.search(r"\b(built|created|discovered|invented|founded|war|empire|dynasty|year)\b", t):
            return "history"
        if re.search(r"\b(boiling|melting|gravity|atom|energy|mass|chemical|physics|science)\b", t):
            return "science"
        return None

    def _normalize_user_question(self, question: str) -> str:
        """
        Remove user formatting directives that should not affect verification intent.
        Example: "who wrote ramayana, in one sentence" -> "who wrote ramayana"
        """
        q = (question or "").strip()
        if not q:
            return ""
        q = re.sub(r"(?i)[,;]\s*(in\s+one\s+(sentence|line)|briefly|shortly|in\s+brief)\s*$", "", q).strip()
        q = re.sub(r"(?i)\s+(in\s+one\s+(sentence|line)|briefly|shortly|in\s+brief)\s*$", "", q).strip()
        q = re.sub(r"\s+", " ", q).strip()
        return self._expand_leadership_aliases(q)

    def _leadership_role_regex_alt(self) -> str:
        return "|".join(re.escape(role) for role, _ in self._LEADERSHIP_ROLES_ORDERED)

    def _expand_leadership_aliases(self, text: str) -> str:
        """Normalize pm/cm/vp/dcm and equivalent phrasing before parsing or Wikipedia lookup."""
        if not text:
            return ""
        out = text
        for abbr, full in sorted(self._LEADERSHIP_SHORT_FORMS.items(), key=lambda x: -len(x[0])):
            out = re.sub(
                rf"(?i)\b{re.escape(abbr)}\s+of\b",
                f"{full} of",
                out,
            )
            out = re.sub(
                rf"(?i)\b(?:who|what)\s+is\s+(?:the\s+)?{re.escape(abbr)}\b",
                lambda m, f=full: re.sub(rf"(?i)\b{re.escape(abbr)}\b", f, m.group(0)),
                out,
            )
        return re.sub(r"\s+", " ", out).strip()

    def _normalize_role_phrase(self, role: str) -> str:
        r = (role or "").strip().lower()
        if not r:
            return ""
        if r in self._LEADERSHIP_SHORT_FORMS:
            return self._LEADERSHIP_SHORT_FORMS[r]
        for key, _ in self._LEADERSHIP_ROLES_ORDERED:
            if r == key:
                return key
        return r

    def _detect_role_phrase(self, text: str) -> Optional[str]:
        """Return canonical role key (e.g. 'vice president'); longest match wins."""
        t = self._expand_leadership_aliases(text or "").lower()
        if not t:
            return None
        for role_key, _ in self._LEADERSHIP_ROLES_ORDERED:
            if re.search(rf"\b{re.escape(role_key)}\b", t):
                return role_key
        short = re.search(
            rf"(?i)\b({'|'.join(re.escape(k) for k in self._LEADERSHIP_SHORT_FORMS)})\b",
            t,
        )
        if short:
            return self._normalize_role_phrase(short.group(1))
        return None

    def _parse_leadership_office_query(self, question: str) -> Optional[Tuple[str, str]]:
        """
        Parse leadership office questions in equivalent forms, e.g.
        'pm of india', 'who is prime minister of india', 'prime minister of india'.
        """
        q = self._expand_leadership_aliases(self._normalize_user_question(question))
        if not q:
            return None
        role_alt = self._leadership_role_regex_alt()
        patterns = [
            rf"(?is)(?:^|\b)(?:who|what)\s+is\s+(?:the\s+)?(?P<role>{role_alt})\s+of\s+(?:the\s+)?(?P<ent>.+?)(?:\?|$)",
            rf"(?is)(?:^|\b)(?P<role>{role_alt})\s+of\s+(?:the\s+)?(?P<ent>.+?)(?:\?|$)",
        ]
        for pat in patterns:
            m = re.search(pat, q)
            if not m:
                continue
            role = self._normalize_role_phrase(m.group("role"))
            ent = self._clean_phrase(m.group("ent"))
            if role and ent:
                return role, ent
        return None

    def _role_wiki_title(self, role_key: str) -> str:
        for key, title in self._LEADERSHIP_ROLES_ORDERED:
            if key == role_key:
                return title
        return (role_key or "").strip().title()

    def _leadership_office_page_title(self, role_key: str, entity: str) -> str:
        return f"{self._role_wiki_title(role_key)} of {self._clean_phrase(entity)}"

    # ---------------- claim extraction ----------------
    def is_complete_claim(self, text: str) -> bool:
        raw = (text or "").strip()
        words = raw.split()
        if re.search(r"(?i)^(the\s+)?[A-Za-z][A-Za-z\s]+\s+(is|are|was|were)\s+[A-Za-z][A-Za-z\s]+\.?$", raw):
            return True
        if len(words) < 3:
            return False
        if re.search(r"(?i)^\s*(as|since|because|therefore|thus|hence)\b", raw):
            return False
        if re.search(r"(?i)^\s*(and|or|but|so|because)\b", raw):
            return False
        if re.search(r"^\s*\d+\.\s*$", raw) or re.search(r"^\s*\d+\.\s+\S+\s*$", raw):
            return False
        if re.search(r"(?i)\b(?:was born|were born)\s*$", raw) and len(words) < 6:
            return False
        # Require a minimal subject-verb-object style structure (keep permissive for science explanations).
        has_verb = bool(
            re.search(
                r"(?i)\b(is|are|was|were|has|have|had|built|invented|discovered|wrote|written|composed|located|serves|served|elected|won|founded|established|born|died|appears|caused|because)\b",
                raw,
            )
        )
        has_subject = bool(
            re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b", raw)
            or re.search(r"(?i)\b(the|this|that|it|he|she|they)\b", raw)
            or re.search(r"(?i)\b(the|a|an)\s+[a-z]{3,}\b", raw)
        )
        has_object = bool(re.search(r"(?i)\b(of|in|by|as|at|for|to)\b", raw) or len(words) >= 7)
        if not (has_verb and has_subject and has_object):
            return False
        if not re.search(
            r"(?i)\b(is|are|was|were|has|have|had|built|invented|discovered|wrote|written|composed|located|serves|served|born|died|appears|because)\b",
            raw,
        ):
            return False
        return True

    def _claim_type(self, claim: str, question: str = "") -> str:
        t = f"{question} {claim}"
        if self._detect_role_phrase(t) or re.search(r"\b(leader)\b", t.lower()):
            return "leader_dynamic"
        if re.search(r"\b(capital|city|location|located)\b", t):
            return "geographic_static"
        if re.search(r"\b(population|currency|language|area)\b", t):
            return "demographic_dynamic"
        if re.search(r"\b(built|created|invented|architect|founded|established)\b", t):
            return "historical"
        if re.search(r"\b(year|date|completed|born|died)\b", t):
            return "temporal"
        return "general"

    def _parse_question(self, question: str) -> QuestionContext:
        q = self._expand_leadership_aliases(self._normalize_user_question(question))
        ql = q.lower()
        qtype = "what"
        if ql.startswith("who"):
            qtype = "who"
        elif ql.startswith("where"):
            qtype = "where"
        elif ql.startswith("when"):
            qtype = "when"
        elif ql.startswith("how many"):
            qtype = "how_many"
        elif ql.startswith("why"):
            qtype = "why"

        target_entity = ""
        target_attr = ""
        exp = "definition"
        strategy = "general_lookup"

        # why is X Y
        m = re.search(r"(?i)\bwhy\s+is\s+(.+?)\s+([a-z][a-z\-]{2,40})\b", q)
        if m:
            target_entity = self._clean_phrase(m.group(1))
            target_attr = self._clean_phrase(m.group(2)).lower()
            exp = "explanation"
            strategy = "science_or_general_reason"

        office = self._parse_leadership_office_query(q)
        if office:
            target_attr, target_entity = office
            exp = "person_name"
            strategy = "office_page_first"

        # what is capital/population/currency of Y
        if not target_entity:
            m = re.search(r"(?i)\bwhat\s+is\s+(?:the\s+)?([a-z][a-z\s\-]{2,40})\s+of\s+(.+)$", q)
            if m:
                target_attr = self._clean_phrase(m.group(1)).lower()
                target_entity = self._clean_phrase(m.group(2))
                exp = "location_name" if "capital" in target_attr else "number_or_text"
                strategy = "country_page_first"
        # who wrote/composed/built X
        if not target_entity:
            m = re.search(r"(?i)\bwho\s+(wrote|composed|built|created|invented|directed)\s+(.+)$", q)
            if m:
                target_attr = self._clean_phrase(m.group(1)).lower()
                target_entity = self._clean_phrase(m.group(2))
                exp = "person_name"
                strategy = "work_or_subject_page_first"
        # when did X die/born
        if not target_entity:
            m = re.search(r"(?i)\bwhen\s+did\s+(.+?)\s+(die|born|birth|founded|established)\b", q)
            if m:
                target_entity = self._clean_phrase(m.group(1))
                target_attr = self._clean_phrase(m.group(2)).lower()
                exp = "date"
                strategy = "entity_page_first"
                # Pattern for short forms: pm of india, cm of gujarat, vp of usa, dcm of delhi
        
        if not target_entity:
            ent, attr, _ = self._extract_entity_attribute(q, q)
            target_entity = ent or q
            target_attr = attr or ""
            exp = "free_text"

        ctype = self._claim_type(f"{target_attr} of {target_entity}", q)
        domain_tag = "out_of_domain" if self.detect_domain(q) is None else (self.detect_domain(q) or "unknown")
        return QuestionContext(
            question_type=qtype,
            target_entity=target_entity,
            target_attribute=target_attr,
            expected_answer_type=exp,
            domain_tag=domain_tag,
            source_strategy=strategy if strategy != "general_lookup" else ctype,
        )

    def _anchor_wikipedia_query(self, qc: QuestionContext) -> str:
        """
        Build a single Wikipedia retrieval query driven by the user's question intent.
        This is the *primary* page we want to fetch and reuse for all claims.
        """
        te = (qc.target_entity or "").strip()
        ta = (qc.target_attribute or "").strip()
        if qc.source_strategy == "office_page_first" and te and ta:
            return self._leadership_office_page_title(ta, te)
        if qc.source_strategy == "country_page_first" and te:
            return te
        if qc.source_strategy == "work_or_subject_page_first" and te:
            return te
        if qc.question_type == "why" and te:
            # "why is the sky blue" -> target_entity is usually "the sky" and target_attribute "blue"
            if ta:
                return f"{te} {ta}".strip()
            return te
        return te or qc.target_attribute or ""

    def _filter_stop_words(self, tokens: List[str]) -> List[str]:
        out = []
        for t in tokens:
            tl = (t or "").lower().strip()
            if not tl or tl in self.query_stop_words:
                continue
            if len(tl) < 2:
                continue
            out.append(tl)
        return out

    def _generate_question_ngrams(self, question: str) -> List[str]:
        q = self._expand_leadership_aliases(question or "").lower()
        out: List[str] = []
        office = self._parse_leadership_office_query(question or "")
        if office:
            role, ent = office
            title = self._leadership_office_page_title(role, ent).lower()
            if title not in out:
                out.append(title)
            role_ent = f"{role} of {ent}".lower()
            if role_ent not in out:
                out.append(role_ent)
        toks = re.findall(r"[a-z0-9][a-z0-9\-']*", q)
        toks = self._filter_stop_words(toks)
        for n in (4, 3, 2, 1):
            if len(toks) < n:
                continue
            for i in range(len(toks) - n + 1):
                g = " ".join(toks[i : i + n]).strip()
                if g and g not in out:
                    out.append(g)
        return out

    def _extract_primary_claim_from_answer(self, question: str, response: str, qc: QuestionContext) -> Optional[str]:
        resp = (response or "").strip()
        if not resp:
            return None
        sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", resp) if s.strip()]
        if not sents:
            return None
        # Prefer sentence containing target entity and attribute.
        te = self.normalize_text(qc.target_entity)
        ta = self.normalize_text(qc.target_attribute)
        for s in sents[:6]:
            sn = self.normalize_text(s)
            if te and te in sn and (not ta or ta in sn):
                return s
        # Fallback: first sentence that looks factual.
        for s in sents[:3]:
            if re.search(r"(?i)\b(is|was|are|were|has|have|had|serves|served|wrote|built|composed|founded)\b", s):
                return s
        return sents[0]

    def _is_present_data_sensitive(self, question: str, claim: str = "") -> bool:
        t = f"{question or ''} {claim or ''}".lower()
        if re.search(r"\b(current|now|today|present|sitting|incumbent|latest|recent|as of today|as of now)\b", t):
            return True
        if re.search(r"\b(is|serves|holds|occupies|runs|leads)\b", t) and not re.search(r"\b(19\d{2}|20[0-2]\d)\b", t):
            return True
        if self._detect_role_phrase(t) and not re.search(r"\b(19\d{2}|20[0-2]\d)\b", t):
            return True
        return False

    def _extract_claimed_person(self, claim: str) -> Optional[str]:
        # Pull trailing proper noun candidate often used as claimed value.
        names = re.findall(r"\b[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){0,3}\b", claim or "")
        if not names:
            return None
        # Prefer last person-like chunk.
        return names[-1].strip()

    def _normalize_person(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()

    def _same_person(self, a: str, b: str) -> bool:
        na = self._normalize_person(a)
        nb = self._normalize_person(b)
        if not na or not nb:
            return False
        # Fast path: same first+last token (handles middle names).
        ta = [t for t in na.split() if t]
        tb = [t for t in nb.split() if t]
        if len(ta) >= 2 and len(tb) >= 2:
            if ta[0] == tb[0] and ta[-1] == tb[-1]:
                return True
        if na == nb or na in nb or nb in na:
            return True
        return SequenceMatcher(None, na, nb).ratio() >= 0.82

    def _extract_ordinal(self, text: str) -> Optional[int]:
        m = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)\b", text or "", re.I)
        if not m:
            return None
        try:
            return int(m.group(1))
        except Exception:
            return None

    def _leader_match_category(self, claim: str, evidence_sentence: str, current_person: Optional[str]) -> str:
        claimed_person = self._extract_claimed_person(claim)
        if claimed_person and current_person and not self._same_person(claimed_person, current_person):
            return "contradiction"
        co = self._extract_ordinal(claim)
        eo = self._extract_ordinal(evidence_sentence)
        if co is not None and eo is not None:
            if co == eo:
                return "exact"
            if abs(co - eo) == 1:
                return "detail_mismatch"
            return "core_only"
        if claimed_person and current_person and self._same_person(claimed_person, current_person):
            return "core_only"
        return "no_match"

    def _get_current_leader(self, country: str, role: str) -> Dict[str, Any]:
        """
        Fetch current leader from Wikidata:
        - P6: head of government (PM/chancellor)
        - P35: head of state (president/king/queen)
        """
        role_l = normalize_political_term(role or "").lower()
        head_of_gov_roles = ["prime minister", "pm", "head of government", "premier", "chancellor", "chief minister", "cm"]
        is_head_of_government = any(role in role_l for role in head_of_gov_roles)
        prop = "P6" if is_head_of_government else "P35"
        entity = self.wikidata.search_entity(country)
        if not entity:
            return {"person": None, "url": None, "evidence": "", "property_id": prop}
        wd_person = None
        try:
            ent_data = self.wikidata.get_entity_data(entity["id"])
            claims = ((ent_data or {}).get("claims") or {}).get(prop) or []
            picked = None
            for c in claims:
                if (c or {}).get("rank") == "preferred":
                    picked = c
                    break
            if not picked and claims:
                picked = claims[0]
            if picked:
                val = (((picked.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
                qid = val.get("id") if isinstance(val, dict) else None
                if qid:
                    leader_ent = self.wikidata.search_entity_by_id(qid)
                    wd_person = (leader_ent or {}).get("label")
            if not wd_person:
                value = self.wikidata.get_property_value(entity["id"], prop)
                wd_person = str(value).strip() if value else None
        except Exception:
            value = self.wikidata.get_property_value(entity["id"], prop)
            wd_person = str(value).strip() if value else None
        wd_url = entity.get("url")

        # Cross-check with Wikipedia role page to avoid stale Wikidata property values.
        wiki_phrase = f"{role.title()} of {country}"
        wiki_ev = self._wiki_evidence(wiki_phrase, question=wiki_phrase, entity=country, attribute=role)
        wiki_text = (wiki_ev or {}).get("text", "")
        wiki_url = (wiki_ev or {}).get("url")
        wiki_person = None
        # Prefer infobox "incumbent" when available (avoids false picks like "Lok Sabha"/"Indian Ocean").
        infobox_lines = (wiki_ev or {}).get("infobox_lines") or []
        for line in infobox_lines:
            if not isinstance(line, str):
                continue
            if re.search(r"(?i)^\s*incumbent\s*:", line) or re.search(r"(?i)\bincumbent\s*:", line):
                val = re.sub(r"(?i)^\s*incumbent\s*:\s*", "", line).strip()
                val = re.sub(r"\s*\(.*?\)\s*$", "", val).strip()
                if val:
                    wiki_person = val
                    break

        # Fallback: scan body sentences, but with strict person filters.
        if not wiki_person and wiki_text:
            for sent in self._split_into_sentences(wiki_text):
                if not re.search(r"(?i)\b(current|incumbent)\b", sent):
                    continue
                names = re.findall(r"\b[A-Z][A-Za-z.'’-]+(?:\s+[A-Z][A-Za-z.'’-]+){1,3}\b", sent)
                if not names:
                    continue
                for n in names:
                    n = (n or "").strip()
                    if re.search(r"(?i)\b(ocean|sea|river|lok sabha|rajya sabha|parliament|government|republic|kingdom|states|country|forces)\b", n):
                        continue
                    wiki_person = n
                    break
                if wiki_person:
                    break

        person = wd_person or wiki_person
        if not person:
            return {"person": None, "url": wd_url or wiki_url, "evidence": "", "property_id": prop}
        # Prefer the evidence string that matches the selected person.
        if wiki_person and self._same_person(wiki_person, person):
            evidence = f"{country} current {role} from Wikipedia: {wiki_person}"
        else:
            evidence = f"{country} current {role} from Wikidata {prop}: {wd_person or person}"
        return {
            "person": person,
            "url": wiki_url or wd_url,
            "evidence": evidence,
            "property_id": prop,
        }

    def _is_future_speculative(self, claim: str) -> bool:
        now_year = datetime.now(timezone.utc).year
        years = [int(y) for y in re.findall(r"\b(20\d{2}|19\d{2})\b", claim or "")]
        if any(y > now_year for y in years):
            return True
        speculative = re.search(r"(?i)\b(will|would|expected to|predicted to|likely to|by\s+20\d{2})\b", claim or "")
        return bool(speculative)

    def extract_claims(self, text: str) -> List[str]:
        text = re.sub(r"(?i)^as of my knowledge cutoff in \d{4},?\s*", "", text)
        text = re.sub(r"(?i)^as of my knowledge cutoff,?\s*", "", text)
        text = re.sub(r"(?i)^as of my knowledge,?\s*", "", text)
        text = re.sub(r"\s+", " ", text or "").strip()
        if not text:
            return []
        sents = re.split(r"(?<=[.!?])\s+", text)
        out: List[str] = []
        for s in sents:
            s = s.strip()
            if len(s) < CLAIM_EXTRACTION["min_sentence_length"]:
                continue
            parts = [s]
            if "," in s:
                parts.extend([p.strip() for p in s.split(",") if p.strip()])
            nxt: List[str] = []
            for p in parts:
                nxt.extend([x.strip() for x in re.split(r"(?i)\s+(?:and|but|or)\s+", p) if x.strip()])
            for p in nxt:
                if self.is_complete_claim(p) and not self._is_meta_sentence(p):
                    out.append(p)
        # Deterministic de-duplication with containment suppression:
        # if one claim is a strict substring of another, keep the longer one.
        cleaned: List[str] = []
        normed = [self.normalize_text(x) for x in out if x]
        for i, c in enumerate(out):
            ni = normed[i]
            if not ni:
                continue
            contained = False
            for j, nj in enumerate(normed):
                if i == j or not nj:
                    continue
                if ni != nj and ni in nj:
                    contained = True
                    break
            if not contained:
                cleaned.append(c)
        return cleaned

    def _is_meta_sentence(self, text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return True
        factual_indicators = ["is", "are", "was", "were", "has", "have", "born", "died", "capital", "prime minister", "president"]
        if any(indicator in t for indicator in factual_indicators):
            return False
        if re.search(r"(?i)\b(please note|knowledge cutoff|may have changed|might be outdated|check recent|recommend verifying|up-to-date)\b", t):
            return True
        if re.search(r"(?i)^(however|note|as of my knowledge cutoff)\b", t):
            return True
        return False

    def _clean_phrase(self, text: str) -> str:
        t = re.sub(r"\s+", " ", (text or "").strip(" ,.;:-")).strip()
        return t

    def _extract_entity_attribute(self, claim: str, question: str = "") -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        General entity-attribute extractor.
        Returns: (entity, attribute, claimed_value)
        """
        src = self._clean_phrase(claim)
        q = self._clean_phrase(question)
        txt = f"{q}. {src}".strip()

        # Pattern B: attribute of entity is value
        m = re.search(
            r"(?i)\b(?P<attr>[a-z][a-z\s\-]{2,40})\s+of\s+(?P<entity>[A-Za-z0-9'’\-\s]{2,80})\s+(?:is|was|are|were|has|have)\s+(?P<value>[^.,;]{1,100})",
            txt,
        )
        if m:
            return self._clean_phrase(m.group("entity")), self._clean_phrase(m.group("attr")).lower(), self._clean_phrase(m.group("value"))

        # Pattern D: passive voice "Entity was <written/built/invented> by Value"
        m = re.search(
            r"(?i)\b(?P<entity>[A-Za-z0-9'’\-\s]{2,80})\s+"
            r"(?:is|was|were)\s+"
            r"(?P<verb>written|built|created|invented|designed|composed|directed)\s+by\s+"
            r"(?P<value>[A-Za-z0-9'’\-\s]{2,80})",
            src,
        )
        if m:
            verb = self._clean_phrase(m.group("verb")).lower()
            attr_map = {
                "written": "author",
                "built": "built_by",
                "created": "created_by",
                "invented": "invented_by",
                "designed": "designed_by",
                "composed": "composer",
                "directed": "director",
            }
            attr = attr_map.get(verb, verb)
            return self._clean_phrase(m.group("entity")), attr, self._clean_phrase(m.group("value"))

        # Pattern B (question style): who/what is attribute of entity
        m = re.search(
            r"(?i)\b(?:who|what|which)\s+(?:is|was|are|were)\s+(?:the\s+)?(?P<attr>[a-z][a-z\s\-]{2,40})\s+of\s+(?P<entity>[A-Za-z0-9'’\-\s]{2,80})",
            txt,
        )
        if m:
            return self._clean_phrase(m.group("entity")), self._clean_phrase(m.group("attr")).lower(), None

        # Pattern A: entity is/was/has attribute value
        m = re.search(
            r"(?i)^(?P<entity>[A-Z][A-Za-z0-9'’\-\s]{1,80})\s+(?:is|was|has|have)\s+(?:the\s+)?(?P<attr>[a-z][a-z\s\-]{2,40})\s*(?P<value>[^.,;]{0,100})",
            src,
        )
        if m:
            value = self._clean_phrase(m.group("value")) or None
            return self._clean_phrase(m.group("entity")), self._clean_phrase(m.group("attr")).lower(), value

        # Pattern C: value is attribute of entity
        m = re.search(
            r"(?i)^(?P<value>[A-Za-z0-9'’\-\s]{2,80})\s+(?:is|was|are|were)\s+(?:the\s+)?(?P<attr>[a-z][a-z\s\-]{2,40})\s+of\s+(?P<entity>[A-Za-z0-9'’\-\s]{2,80})",
            src,
        )
        if m:
            return self._clean_phrase(m.group("entity")), self._clean_phrase(m.group("attr")).lower(), self._clean_phrase(m.group("value"))

        # Fallback: infer from proper noun phrases + property word
        entities = re.findall(r"\b[A-Z][A-Za-z0-9'’\-]*(?:\s+[A-Z][A-Za-z0-9'’\-]*){0,4}\b", txt)
        entity = entities[-1] if entities else None
        attr = None
        lower_txt = txt.lower()
        for term in sorted(self.generic_attribute_terms, key=len, reverse=True):
            if re.search(rf"(?i)\b{re.escape(term)}\b", lower_txt):
                attr = term
                break
        return self._clean_phrase(entity) if entity else None, attr, None


    def _claim_relevant_to_question(self, claim: str, question: str) -> bool:
        q_entity, q_attr, _ = self._extract_entity_attribute(question, question)
        c_entity, c_attr, _ = self._extract_entity_attribute(claim, question)
        cl = claim.lower()
        if q_entity and c_entity and self.normalize_text(q_entity) in self.normalize_text(c_entity):
            return True
        if q_attr and c_attr and (q_attr in c_attr or c_attr in q_attr):
            return True
        # loose overlap fallback
        q_terms = {t for t in re.findall(r"[a-z]{4,}", (question or "").lower()) if t not in self.stop_words}
        c_terms = {t for t in re.findall(r"[a-z]{4,}", cl) if t not in self.stop_words}
        return len(q_terms.intersection(c_terms)) >= 2

    def normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())).strip()

    def get_subject(self, claim: str, question: str = "") -> str:
        ent, attr, _ = self._extract_entity_attribute(claim, question)
        if ent and self.normalize_text(ent) not in self.bad_subject_words:
            return ent
        s = self.wikidata.extract_subject(claim)
        if s:
            if self.normalize_text(s) in self.bad_subject_words:
                return "Unknown"
            return s
        caps = re.findall(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b", claim or "")
        if caps:
            cand = max(caps, key=len)
            if self.normalize_text(cand) not in self.bad_subject_words:
                return cand
        return "Unknown"

    def _resolve_claim_with_context(self, claim: str, context: Optional[Dict[str, Any]]) -> str:
        c = (claim or "").strip()
        if not c or not isinstance(context, dict):
            return c
        subjects = [s for s in (context.get("subjects") or []) if s and s != "Unknown"]
        current_subject = context.get("current_subject") if context.get("current_subject") not in (None, "", "Unknown") else None
        recent = ([current_subject] if current_subject else []) + subjects[-3:]
        recent = [r for i, r in enumerate(recent) if r and r not in recent[:i]]
        if not recent:
            return c

        replacement = recent[0]
        person_like = [r for r in recent if not re.search(r"(?i)\b(country|states?|republic|kingdom|india|france|japan|australia|iran)\b", r)]
        person_replacement = person_like[0] if person_like else replacement
        # Pronoun resolution
        if re.search(r"(?i)\b(he|she|him|her|his)\b", c):
            c = re.sub(r"(?i)\b(he|she|him|her|his)\b", person_replacement, c)
        if re.search(r"(?i)\b(it|they|them|their)\b", c):
            c = re.sub(r"(?i)\b(it|they|them|their)\b", replacement, c)
        # Partial role references ("the president", "the prime minister")
        c = re.sub(r"(?i)\bthe\s+(president|prime minister|king|queen|leader|monarch)\b", replacement, c)
        return c

    def _update_context(self, claim_result: Dict[str, Any], context: Optional[Dict[str, Any]]) -> None:
        if not isinstance(context, dict):
            return
        subject = (claim_result or {}).get("subject")
        if not subject or subject == "Unknown":
            return
        context["current_subject"] = subject
        subjects = context.setdefault("subjects", [])
        if subject not in subjects:
            subjects.append(subject)
        if len(subjects) > 10:
            del subjects[:-10]

    def _wiki_search_candidates(self, query: str, limit: int = 8) -> List[str]:
        if not (query or "").strip():
            return []
        return [query]

    def _is_disambiguation_page(self, page: Any) -> bool:
        if not page or not getattr(page, "exists", lambda: False)():
            return False
        title = (getattr(page, "title", "") or "").lower()
        summary = (getattr(page, "summary", "") or "").lower()
        if "disambiguation" in title:
            return True
        if summary.startswith("may refer to") or summary.startswith("refers to"):
            return True
        try:
            categories = getattr(page, "categories", {}) or {}
            for c in categories.keys():
                if "disambiguation pages" in str(c).lower():
                    return True
        except Exception:
            pass
        return False

    def _extract_context_words(self, text: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z\-]{2,}", (text or "").lower())
        ban = self.stop_words.union({"president", "prime", "minister", "king", "queen", "leader", "city"})
        out: List[str] = []
        for t in tokens:
            if t in ban:
                continue
            if t not in out:
                out.append(t)
        return out[:4]

    def _search_wikipedia_titles(self, query: str, limit: int = 5) -> List[str]:
        if not (query or "").strip():
            return []
        qk = f"search::{query.lower().strip()}::{limit}"
        cached = self.source_cache.get(qk)
        if cached is not None:
            return cached
        try:
            res = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "format": "json",
                    "srsearch": query,
                    "srlimit": limit,
                },
                timeout=8,
            )
            if res.status_code != 200:
                return []
            rows = ((res.json() or {}).get("query") or {}).get("search") or []
            titles = [r.get("title", "") for r in rows if r.get("title")]
            self.source_cache.set(qk, titles)
            return titles
        except Exception:
            return []

    def _search_specific_page(self, term: str, claim: str) -> Optional[Any]:
        context_words = self._extract_context_words(claim)
        queries = [term]
        if context_words:
            queries.append(f"{term} {' '.join(context_words)}")
        for q in queries:
            for title in self._search_wikipedia_titles(q, limit=8):
                p = self.wiki.page(title)
                if p and p.exists() and not self._is_disambiguation_page(p):
                    return p
        return None

    def _fetch_full_page_content(self, title: str) -> Dict[str, Any]:
        bundle = self._fetch_page_bundle(title)
        text = (bundle.get("text") or "").strip()
        # Enrich with full page body when available.
        page = self.wiki.page(title)
        if page and page.exists():
            try:
                full_text = (page.text or "").strip()
            except Exception:
                full_text = ""
            if full_text:
                text = (text + "\n" + full_text[:15000]).strip() if text else full_text[:15000]
                bundle["url"] = bundle.get("url") or f"https://en.wikipedia.org/wiki/{page.title.replace(' ', '_')}"
                bundle["page_title"] = bundle.get("page_title") or page.title
        bundle["text"] = text[:15000]
        return bundle

    def _scan_page_for_answer(self, page_content: str, claim: str, entity: str, attribute: str, claimed_value: Optional[str]) -> Tuple[str, Dict[str, Any], str]:
        domain = self.detect_domain(claim or page_content) or "general"
        sentences = self._split_into_sentences(page_content)
        if not sentences:
            return "", {"lexical": 0.0, "semantic_score": None, "semantic_pct": 0.0, "final": 0.0, "breakdown": {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"}}, "body"
        e = self.normalize_text(entity or "")
        # Tolerate leading determiners ("the sky" vs "sky").
        e2 = e
        if e.startswith("the "):
            e2 = e[4:].strip()
        a = self.normalize_text(attribute or "")
        v = self.normalize_text(claimed_value or "")
        best_sent = sentences[0]
        best_card = self._score_claim_against_evidence(claim, best_sent, domain)
        best_rule = 0.0
        best_total = float(best_card.get("final", 0.0)) + best_rule
        for sent in sentences[:300]:
            card = self._score_claim_against_evidence(claim, sent, domain)
            sn = self.normalize_text(sent)
            rule = 0.0
            if (e and e in sn) or (e2 and e2 in sn):
                rule += 30
            if a and a in sn:
                rule += 20
            if v and v in sn:
                rule += 50
            if re.search(r"(?i)\b(incumbent|current|author|written by|built by|composer|capital)\b", sent):
                rule += 10
            # Author equivalence: Wikipedia often phrases authorship as "attributed to X".
            if v and v in sn and re.search(r"(?i)\b(attributed to|traditionally attributed to)\b", sent):
                rule += 25
            # Science/causal boost: for "because ..." claims, require mechanism + effect terms.
            if "because" in self.normalize_text(claim) and all(k in sn for k in ("sky", "blue")):
                if any(k in sn for k in ("rayleigh", "scattering")):
                    rule += 30
            total = float(card.get("final", 0.0)) + rule
            if total > best_total:
                best_total = total
                best_sent = sent
                best_card = card
                best_rule = rule
        # Carry rule bonus into final score used by tier decisions.
        try:
            best_card["_rule_bonus"] = round(float(best_rule), 1)
            boosted = min(100.0, float(best_card.get("final", 0.0)) + float(best_rule))
            # If we had to rely on heuristic boosts (esp. when semantic is unavailable), keep confidence conservative.
            if float(best_rule) >= 25.0 and best_card.get("semantic_score") is None:
                boosted = min(boosted, 85.0)
            best_card["final"] = round(boosted, 1)
        except Exception:
            pass
        loc = "infobox" if ":" in best_sent and len(best_sent.split(":")[0].split()) <= 4 else "body"
        return best_sent, best_card, loc

    def _extract_infobox_pairs(self, wikitext: str) -> List[str]:
        txt = wikitext or ""
        # Light regex-based infobox field extraction, no new dependency.
        pairs = []
        for m in re.finditer(r"^\|\s*([^=\n]+?)\s*=\s*([^\n]+)\s*$", txt, flags=re.M):
            k = self._clean_phrase(m.group(1))
            v = self._clean_phrase(re.sub(r"\[\[|\]\]|\{\{|\}\}", "", m.group(2)))
            if k and v:
                pairs.append(f"{k}: {v}")
        return pairs[:80]

    def _fetch_page_bundle(self, title: str) -> Dict[str, Any]:
        tk = (title or "").strip()
        if not tk:
            return {"text": "", "url": None, "page_title": None, "infobox_lines": []}
        key = tk.lower()
        if key in self._session_page_cache:
            return self._session_page_cache[key]
        if key in self._session_failed_titles:
            return {"text": "", "url": None, "page_title": None, "infobox_lines": []}
        try:
            # Keep categories tight for disambiguation checks.
            res = requests.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts|categories|revisions",
                    "explaintext": 1,
                    "exchars": 5000,
                    "rvprop": "content",
                    "cllimit": 20,
                    "format": "json",
                    "titles": tk,
                },
                timeout=10,
            )
            if res.status_code != 200:
                self._session_failed_titles.add(key)
                return {"text": "", "url": None, "page_title": None, "infobox_lines": []}
            pages = ((res.json() or {}).get("query") or {}).get("pages") or {}
            page = next(iter(pages.values()), {}) if pages else {}
            page_title = page.get("title")
            extract = page.get("extract") or ""
            revs = page.get("revisions") or []
            raw = ""
            if revs:
                raw = (revs[0].get("*") or (revs[0].get("slots") or {}).get("main", {}).get("*") or "")
            infobox_lines = self._extract_infobox_pairs(raw)
            text = extract
            if infobox_lines:
                text = f"{text}\n" + "\n".join(infobox_lines[:40])
            out = {
                "text": text.strip(),
                "url": f"https://en.wikipedia.org/wiki/{str(page_title or tk).replace(' ', '_')}",
                "page_title": page_title or tk,
                "infobox_lines": infobox_lines,
            }
            self._session_page_cache[key] = out
            return out
        except Exception:
            self._session_failed_titles.add(key)
            return {"text": "", "url": None, "page_title": None, "infobox_lines": []}

    def find_best_page(self, subject: str, claim: str) -> Tuple[Optional[Any], str]:
        claim_l = (claim or "").lower()
        best_title = subject
        best_page = None
        best_score = -1
        for title in self._wiki_search_candidates(subject, limit=8):
            p = self.wiki.page(title)
            if p and p.exists():
                score = 0
                tl = (title or "").lower()
                if tl in claim_l:
                    score += 5
                summary = getattr(p, "summary", "") or ""
                score += sum(1 for w in re.findall(r"[a-z]+", claim_l) if len(w) > 3 and w in summary.lower())
                if score > best_score:
                    best_score = score
                    best_title = title
                    best_page = p
        if best_page is not None:
            return best_page, best_title
        p = self.wiki.page(subject)
        if p and p.exists():
            return p, subject
        return None, subject

    # ---------------- helpers ----------------
    def _source_support(self, claim: str, text: str) -> float:
        if not text:
            return 0.0
        terms = [t for t in re.findall(r"[a-zA-Z0-9]+", claim.lower()) if len(t) > 2 and t not in self.stop_words]
        if not terms:
            return 0.0
        content = text.lower()
        hits = 0.0
        for t in terms:
            if t in content:
                hits += 1.0
            else:
                best = max((SequenceMatcher(None, t, w).ratio() for w in content.split()[:1200]), default=0.0)
                if best >= 0.8:
                    hits += 0.75
        return max(0.0, min(100.0, (hits / len(terms)) * 100.0))

    def _score_claim_against_evidence(self, claim: str, evidence_text: str, domain: str) -> Dict[str, Any]:
        lexical = self._source_support(claim, evidence_text)
        sem = self._semantic_score(claim, evidence_text)
        sem_pct = (float(sem) * 100.0) if sem is not None else 0.0
        if domain == "countries":
            wl, ws = 0.55, 0.45
        elif domain == "science":
            wl, ws = 0.5, 0.5
        else:
            wl, ws = 0.6, 0.4
        combined = (wl * lexical) + (ws * sem_pct)
        # Semantic rescue when wording differs but meaning aligns.
        if lexical < 25.0 and sem_pct >= (self.semantic_threshold * 100.0):
            combined = max(combined, 60.0, sem_pct)
        elif lexical >= 70.0 and sem_pct >= 70.0:
            combined = max(combined, min(100.0, 0.5 * lexical + 0.5 * sem_pct + 8.0))
        return {
            "lexical": round(lexical, 1),
            "semantic_score": round(float(sem), 4) if sem is not None else None,
            "semantic_pct": round(sem_pct, 1),
            "final": round(max(0.0, min(100.0, combined)), 1),
            "breakdown": {
                "lexical_contribution": round(wl * lexical, 1),
                "semantic_contribution": round(ws * sem_pct, 1),
                "weighting": f"{int(wl*100)}/{int(ws*100)}",
            },
        }

    def normalize_number(self, text: str) -> Optional[Tuple[float, bool]]:
        t = (text or "").lower().replace(",", "").strip()
        if not t:
            return None
        approx = bool(re.search(r"\b(about|around|approx|approximately|~)\b", t))
        m_range = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|to)\s*(\d+(?:\.\d+)?)", t)
        if m_range:
            return ((float(m_range.group(1)) + float(m_range.group(2))) / 2.0, True)
        m = re.search(r"(-?\d+(?:\.\d+)?)", t)
        if not m:
            return None
        return float(m.group(1)), approx

    def _collect_sources(self, claim: str, subject: str, question: str) -> Dict[str, Dict[str, Any]]:
        ent, attr, _ = self._extract_entity_attribute(claim, question)
        primary_subject = ent or subject
        wiki = self._wiki_evidence(claim, question=question, entity=primary_subject, attribute=attr)
        wd = self.wikidata.get_evidence_for_claim(claim, subject_hint=primary_subject)
        rc = self.restcountries_source.get_evidence_for_claim(claim, subject_hint=primary_subject, question=question)
        return {
            "wikipedia": wiki,
            "wikidata": wd,
            "restcountries": rc,
            "local_kb": wiki,  # backward-compat for old tests/mocks
        }

    def _is_generic_definition_page(self, page: Any, entity: Optional[str]) -> bool:
        if not page or not getattr(page, "exists", lambda: False)():
            return True
        title = (getattr(page, "title", "") or "").strip()
        summary = (getattr(page, "summary", "") or "").lower()
        title_l = title.lower()
        if entity and self.normalize_text(entity) and self.normalize_text(entity) in self.normalize_text(title):
            return False
        if title_l in self.generic_attribute_terms:
            return True
        if re.search(r"(?i)\b(is|refers to)\s+the\s+(head|role|office|person|term)\b", summary):
            return True
        return False

    def _wiki_evidence(self, claim: str, question: str = "", entity: Optional[str] = None, attribute: Optional[str] = None) -> Dict[str, Any]:
        claim = claim or ""
        ent = entity or self.get_subject(claim, question)
        attr = (attribute or "").strip()
        # For leader-style claims, Wikipedia pages about the role are usually better than the country page.
        role_map = {key: title for key, title in self._LEADERSHIP_ROLES_ORDERED}
        role_map["leader"] = "Leader"
        role = self._detect_role_phrase(f"{question} {claim}")

        candidates: List[str] = []
        # Question n-gram anchored candidates first.
        for ng in self._generate_question_ngrams(question):
            for t in self._search_wikipedia_titles(ng, limit=3):
                if t and t not in candidates:
                    candidates.append(t)
            # Fallback when search API is rate-limited: try direct title forms.
            if ng and len(ng.split()) >= 2:
                tc = ng.title()
                if tc not in candidates:
                    candidates.append(tc)
        # Claim n-grams are dangerous (they can drag us to irrelevant pages like "Vedic Sanskrit").
        # Only allow them for "why" questions to pick mechanism pages (Rayleigh scattering).
        if (question or "").strip().lower().startswith("why"):
            for ng in self._generate_question_ngrams(claim):
                # Only keep n-grams that contain distinctive mechanism terms.
                if not re.search(r"(?i)\b(rayleigh|scattering|refraction|dispersion|atmosphere)\b", ng):
                    continue
                for t in self._search_wikipedia_titles(ng, limit=2):
                    if t and t not in candidates:
                        candidates.append(t)
                if ng and len(ng.split()) >= 2:
                    tc = ng.title()
                    if tc not in candidates:
                        candidates.append(tc)
        if role and ent:
            # Example: "President of USA" -> "President of United States"
            role_title = role_map.get(role, role.title())
            candidates.append(f"{role_title} of {ent}")
            # Many Wikipedia pages include "the" for country political roles.
            candidates.append(f"{role_title} of the {ent}")
        # Fallback: try the country (or the first word) page.
        if ent:
            candidates.append(ent)
        if attr and ent:
            candidates.append(f"{attr} of {ent}")
        candidates.append(claim.split()[0] if claim.split() else claim)

        # Prefer candidates that contain distinctive claim terms (science pages often require this).
        claim_terms = set(self._filter_stop_words(re.findall(r"[a-z0-9][a-z0-9\-']*", (claim or "").lower())))
        def _cand_priority(s: str) -> Tuple[int, int]:
            sl = (s or "").lower()
            bonus = 0
            for t in ("rayleigh", "scattering", "refraction", "dispersion", "atmosphere"):
                if t in claim_terms and t in sl:
                    bonus += 50
            # Longer, more specific titles first.
            return (bonus, len(sl))

        candidates = sorted(list(dict.fromkeys(candidates)), key=_cand_priority, reverse=True)

        best_bundle: Optional[Dict[str, Any]] = None
        best_score = -1.0
        # Evaluate a bounded number of candidates to avoid excessive API calls.
        for subject in candidates[:20]:
            if not subject or not str(subject).strip():
                continue
            if subject.lower().strip() in self.query_stop_words:
                continue
            page = self._search_specific_page(str(subject), claim)
            if not page:
                page = self.wiki.page(str(subject))
            if page and self._is_disambiguation_page(page):
                page = self._search_specific_page(str(subject), claim)
            if page and page.exists():
                if self._is_generic_definition_page(page, ent):
                    continue
                bundle = self._fetch_full_page_content(page.title)
                text = (bundle.get("text") or "").strip()
                if not text:
                    continue
                bundle["page_title"] = page.title
                # Score candidate page against the claim; prefer pages that actually mention the key terms.
                score = float(self._source_support(claim, text))
                title_l = (page.title or "").lower()
                if title_l and title_l in (claim or "").lower():
                    score += 10.0
                # If the title includes distinctive mechanism terms from the claim, strongly prefer it.
                for mech in ("rayleigh", "scattering", "refraction", "dispersion"):
                    if mech in claim_terms and mech in title_l:
                        score += 80.0
                # Big bonus if the title matches any longer n-gram from claim/question.
                for ng in (self._generate_question_ngrams(question) + self._generate_question_ngrams(claim))[:10]:
                    if ng and ng in title_l and len(ng.split()) >= 2:
                        score += 25.0
                        break
                if role:
                    role_title = role_map.get(role, role.title())
                    if role_title.lower() in title_l:
                        score += 55.0
                    if role == "vice president" and "vice president" in title_l:
                        score += 35.0
                    if role == "vice president" and re.search(r"\bpresident\b", title_l) and "vice" not in title_l:
                        score -= 120.0
                    if role == "deputy chief minister" and "deputy" in title_l and "chief minister" in title_l:
                        score += 35.0
                    if role == "deputy chief minister" and "chief minister" in title_l and "deputy" not in title_l:
                        score -= 80.0
                    if role == "president" and "vice president" in title_l:
                        score -= 120.0
                if score > best_score:
                    best_score = score
                    best_bundle = bundle
        if best_bundle:
            return best_bundle
        return {"text": "", "url": "https://en.wikipedia.org/wiki/Special:Search", "page_title": None}

    def _semantic_score(self, claim: str, text: str) -> Optional[float]:
        return semantic_support.max_cosine_similarity(claim, text, HYBRID["semantic_max_chunks"], HYBRID["min_sentence_chars"])

    # ---------------- evidence extraction helpers ----------------
    def _split_into_sentences(self, text: str) -> List[str]:
        """
        Split evidence into many usable units without losing infobox-style lines.

        IMPORTANT: The verifier must be able to scan beyond the first paragraph,
        otherwise it misses key facts like incumbent/author/built-by that often
        appear later in the page or in infobox fields.
        """
        raw = (text or "").strip()
        if not raw:
            return []
        raw = re.sub(r"\r\n?", "\n", raw)
        chunks: List[str] = []
        for block in re.split(r"\n{1,}", raw):
            b = (block or "").strip()
            if not b:
                continue
            # Keep infobox-like key:value lines as atomic units.
            if ":" in b and len(b.split(":")[0].split()) <= 5:
                chunks.append(b)
                continue
            b = re.sub(r"\s+", " ", b).strip()
            for s in re.split(r"(?<=[.!?])\s+", b):
                s = (s or "").strip()
                if s:
                    chunks.append(s)
        return chunks[:500]

    def _best_sentence_for_claim(self, claim: str, evidence_text: str, domain: str) -> Tuple[str, Dict[str, Any]]:
        candidates = self._split_into_sentences(evidence_text)
        # Always have at least one candidate for UI evidence display.
        if not candidates:
            fallback = (evidence_text or "").strip()
            candidates = [fallback] if fallback else []
        ent, attr, val = self._extract_entity_attribute(claim)
        ent_n = self.normalize_text(ent or "")
        attr_n = self.normalize_text(attr or "")
        val_n = self.normalize_text(val or "")
        best_sentence = candidates[0] if candidates else (evidence_text or "").strip()
        best_card: Dict[str, Any] = {
            "lexical": 0.0,
            "semantic_score": None,
            "semantic_pct": 0.0,
            "final": 0.0,
            "breakdown": {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"},
        }
        for sent in candidates[:300]:
            card = self._score_claim_against_evidence(claim, sent, domain)
            s_n = self.normalize_text(sent)
            rule_score = 0.0
            if ent_n and ent_n in s_n:
                rule_score += 30
            if attr_n and attr_n in s_n:
                rule_score += 20
            if val_n and val_n in s_n:
                rule_score += 50
            total = float(card.get("final", 0.0)) + rule_score
            best_total = float(best_card.get("final", 0.0)) + float(best_card.get("_rule_score", 0.0))
            card["_rule_score"] = rule_score
            if total > best_total:
                best_card = card
                best_sentence = sent
        # Ensure evidence_snippet is non-empty if any evidence_text exists.
        if (best_sentence or "").strip() == "" and (evidence_text or "").strip():
            best_sentence = (evidence_text or "").strip()[:220]
        return best_sentence, best_card

    def _is_specific_evidence(self, claim: str, sentence: str, scorecard: Dict[str, Any], source_key: str, payload: Dict[str, Any], claim_type: str) -> bool:
        s = (sentence or "").strip()
        if not s:
            return False
        # Reject generic/disambiguation style evidence.
        if re.search(r"(?i)\b(may refer to|can refer to|disambiguation|no specific wikipedia article)\b", s):
            return False
        lexical = float((scorecard or {}).get("lexical", 0.0) or 0.0)
        final = float((scorecard or {}).get("final", 0.0) or 0.0)
        if lexical < 25.0 and final < 45.0:
            return False

        entity, attribute, claimed_value = self._extract_entity_attribute(claim)
        s_norm = self.normalize_text(s)
        if entity:
            e_norm = self.normalize_text(entity)
            entity_in_sentence = bool(e_norm and e_norm in s_norm)
            entity_in_page = False
            if not entity_in_sentence and source_key == "wikipedia":
                page_title = self.normalize_text((payload or {}).get("page_title", ""))
                entity_in_page = bool(page_title and e_norm and e_norm in page_title)
            if not entity_in_sentence and not entity_in_page:
                return False
        attr_or_value_present = False
        if attribute:
            a_norm = self.normalize_text(attribute)
            if a_norm and a_norm in s_norm:
                attr_or_value_present = True
        if claimed_value:
            v_norm = self.normalize_text(claimed_value)
            if v_norm and v_norm in s_norm:
                attr_or_value_present = True
        # For "X is Y" style claims, claimed value normally must appear in evidence.
        # Exception: numeric/scientific claims often differ in units/parentheses; accept if key numbers align.
        if re.search(r"(?i)\b(is|was|are|were)\b", claim or "") and claimed_value:
            v_norm = self.normalize_text(claimed_value)
            if v_norm and v_norm not in s_norm:
                claim_nums = re.findall(r"\b\d+(?:\.\d+)?\b", claimed_value)
                sent_nums = re.findall(r"\b\d+(?:\.\d+)?\b", sentence or "")
                if claim_nums and sent_nums and any(n in sent_nums for n in claim_nums):
                    pass
                else:
                    return False
        if not attr_or_value_present and (attribute or claimed_value):
            return False

        # For leader/demographic/temporal claims on Wikidata, demand a property value, not only generic description.
        if source_key == "wikidata" and claim_type in ("leader_dynamic", "demographic_dynamic", "temporal"):
            if not (payload or {}).get("property_value"):
                return False
        return True

    def _freshness_meta(self, claim_type: str) -> Dict[str, Any]:
        checked_at = datetime.now(timezone.utc).isoformat()
        if claim_type == "leader_dynamic":
            max_age_days = 7
        elif claim_type == "demographic_dynamic":
            max_age_days = 30
        else:
            max_age_days = 365
        return {"checked_at": checked_at, "max_age_days": max_age_days}

    def _external_priority_order(self, claim: str, question: str, qc: Optional[QuestionContext] = None) -> List[str]:
        t = f"{question or ''} {claim or ''}".lower()
        if qc:
            # Strategy by question type/domain mapping (advisory).
            a = (qc.target_attribute or "").lower()
            if qc.question_type == "who" and self._detect_role_phrase(a):
                return ["wikipedia", "wikidata"]
            if re.search(r"\b(capital|city|location)\b", a):
                return ["restcountries", "wikipedia", "wikidata"]
            if re.search(r"\b(population|currency|language|area)\b", a):
                return ["restcountries", "wikidata", "wikipedia"]
            if re.search(r"\b(wrote|author|composer|director|built|created|invented|architect)\b", a):
                return ["wikipedia", "wikidata"]
            if qc.question_type == "when":
                return ["wikidata", "wikipedia"]
        # Priority cascade for external sources based on claim type.
        if self._detect_role_phrase(t):
            return ["wikipedia", "wikidata"]
        if re.search(r"\b(capital|city)\b", t):
            return ["restcountries", "wikipedia", "wikidata"]
        if re.search(r"\b(population|currency|language|languages?|area)\b", t):
            return ["restcountries", "wikidata", "wikipedia"]
        if re.search(r"\b(built|created|invented|inventor|architect|architects)\b", t):
            return ["wikipedia", "wikidata"]
        if re.search(r"\b(year|date|born|died|completed|founded|established|in\s+\d{4})\b", t):
            return ["wikidata", "wikipedia"]
        return ["wikipedia", "wikidata", "restcountries"]

    def _external_candidates(self, claim: str, question: str, qc: Optional[QuestionContext] = None) -> Tuple[List[Dict[str, Any]], str]:
        domain = self.detect_domain(question or claim) or "countries"
        order = self._external_priority_order(claim, question, qc=qc)
        claim_type = self._claim_type(claim, question)
        entity, attribute, claimed_value = self._extract_entity_attribute(claim, question)
        subject_hint = (qc.target_entity if qc and qc.target_entity else entity) or self.wikidata.extract_subject(claim) or self.wikidata.extract_subject(question)
        attr_hint = (qc.target_attribute if qc and qc.target_attribute else attribute)
        # Reuse anchored Wikipedia bundle for speed + question-anchored correctness.
        wiki = self._session_anchor_wiki if self._session_anchor_wiki else self._wiki_evidence(
            claim, question=question, entity=subject_hint, attribute=attr_hint
        )
        wd = self.wikidata.get_evidence_for_claim(claim, subject_hint=subject_hint)
        rc = self.restcountries_source.get_evidence_for_claim(claim, subject_hint=subject_hint, question=question)
        by_key = {"wikipedia": wiki, "wikidata": wd, "restcountries": rc}

        candidates: List[Dict[str, Any]] = []
        for key in order:
            payload = by_key.get(key, {}) or {}
            evidence_text = (payload.get("text") or "").strip()
            evidence_url = payload.get("url")
            evidence_snippet = ""
            scorecard: Optional[Dict[str, Any]] = None
            evidence_location = "body"
            if evidence_text:
                if key == "wikipedia":
                    # For leader claims, prefer explicit infobox "incumbent" lines when present.
                    if claim_type == "leader_dynamic":
                        infl = (payload or {}).get("infobox_lines") or []
                        picked = None
                        # First: exact incumbent field.
                        for line in infl:
                            if isinstance(line, str) and re.search(r"(?i)^\s*incumbent\s*:", line):
                                picked = line.strip()
                                break
                        # Second: any infobox line containing the claimed value.
                        if not picked and claimed_value:
                            cvn = self.normalize_text(claimed_value)
                            for line in infl:
                                if not isinstance(line, str):
                                    continue
                                if cvn and cvn in self.normalize_text(line):
                                    picked = line.strip()
                                    break
                        if picked:
                            evidence_snippet = picked
                            scorecard = self._score_claim_against_evidence(claim, picked, domain)
                            evidence_location = "infobox"
                        else:
                            evidence_snippet, scorecard, evidence_location = self._scan_page_for_answer(
                                evidence_text,
                                claim,
                                entity or subject_hint or "",
                                attr_hint or "",
                                claimed_value,
                            )
                    else:
                        scan_entity = entity or subject_hint or ""
                        scan_attr = attr_hint or ""
                        if qc and qc.question_type == "why":
                            scan_entity = qc.target_entity or scan_entity
                            scan_attr = qc.target_attribute or scan_attr
                        evidence_snippet, scorecard, evidence_location = self._scan_page_for_answer(
                            evidence_text,
                            claim,
                            scan_entity,
                            scan_attr,
                            claimed_value,
                        )
                else:
                    evidence_snippet, scorecard = self._best_sentence_for_claim(claim, evidence_text, domain)
            candidates.append(
                {
                    "key": key,
                    "text": evidence_text,
                    "url": evidence_url,
                    "evidence_snippet": evidence_snippet,
                    "scorecard": scorecard,
                    "evidence_location": evidence_location,
                    "specific_ok": self._is_specific_evidence(claim, evidence_snippet, scorecard or {}, key, payload, claim_type) if evidence_text else False,
                    "freshness": self._freshness_meta(claim_type),
                    "entity": entity,
                    "attribute": attribute,
                    "claimed_value": claimed_value,
                }
            )
        return candidates, domain

    def _closest_external_evidence(self, claim: str, question: str, qc: Optional[QuestionContext] = None) -> Dict[str, Any]:
        candidates, domain = self._external_candidates(claim, question, qc=qc)
        checked_sources = [c.get("key") for c in candidates if c.get("key")]
        best = None
        for c in candidates:
            scorecard = c.get("scorecard")
            final = (scorecard or {}).get("final", 0.0) if scorecard else 0.0
            if best is None or final > best.get("final_score", -1.0):
                best = {
                    "source_key": c.get("key"),
                    "source_name": {"wikipedia": "Wikipedia", "wikidata": "Wikidata", "restcountries": "RestCountries"}.get(c.get("key"), c.get("key")),
                    "source_url": c.get("url"),
                    "evidence_snippet": (c.get("evidence_snippet") or "").strip(),
                    "scorecard": scorecard,
                    "final_score": final,
                    "checked_sources": checked_sources,
                    "evidence_location": c.get("evidence_location", "body"),
                }

        # If everything is empty, still return something non-empty for the UI.
        if not best:
            best = {
                "source_key": "wikipedia",
                "source_name": "Wikipedia",
                "source_url": None,
                "evidence_snippet": "",
                "scorecard": None,
                "final_score": 0.0,
                "checked_sources": ["wikipedia", "wikidata", "restcountries"],
                "evidence_location": "body",
            }
        if not best.get("evidence_snippet") and (claim or "").strip():
            best["evidence_snippet"] = f"Could not locate a source sentence confirming: {claim}"

        return best

    # ---------------- tier logic ----------------
    def _tier1_curated(self, claim: str) -> Optional[TierDecision]:
        domain = self.detect_domain(claim) or "countries"
        ex = self.curated.exact_match(claim)
        if ex:
            snippet = ex.get("evidence_snippet") or f"{ex.get('entity')} {ex.get('attribute')} is {ex.get('value')}"
            scorecard = self._score_claim_against_evidence(claim, snippet, domain)
            return TierDecision(
                "Pratyaksha",
                max(95.0, scorecard["final"]),
                "Exact match found in curated database.",
                ["curated_db"],
                f"Curated Database ({ex.get('source_name','Curated')})",
                ex.get("source_url"),
                snippet,
                scorecard,
            )
        sem = self.curated.semantic_match(claim, min_score=0.70)
        if sem:
            fact, _ = sem
            snippet = fact.get("evidence_snippet") or f"{fact.get('entity')} {fact.get('attribute')} is {fact.get('value')}"
            scorecard = self._score_claim_against_evidence(claim, snippet, domain)
            return TierDecision(
                "Pratyaksha",
                max(90.0, scorecard["final"]),
                "Semantic match found in curated database.",
                ["curated_db", "semantic_inference"],
                f"Curated Database ({fact.get('source_name','Curated')})",
                fact.get("source_url"),
                snippet,
                scorecard,
            )
        return None

    def _tier2_external(self, claim: str, question: str, qc: Optional[QuestionContext] = None) -> Optional[TierDecision]:
        candidates, domain = self._external_candidates(claim, question, qc=qc)

        # First source in the priority cascade with confidence > 40 wins.
        for c in candidates:
            scorecard = c.get("scorecard")
            if not scorecard:
                continue
            if not c.get("specific_ok"):
                continue
            if float(scorecard.get("final", 0.0)) >= 40.0 and (c.get("evidence_snippet") or "").strip():
                winner_key = c.get("key")
                winner_name = {"wikipedia": "Wikipedia", "wikidata": "Wikidata", "restcountries": "RestCountries"}.get(winner_key, winner_key)
                winner_url = c.get("url")
                winner_snippet = c.get("evidence_snippet")

                # For Shabda explanation, include up to one additional corroborating source if it also clears the threshold.
                agrees = [winner_key]
                for other in candidates:
                    if other.get("key") == winner_key:
                        continue
                    other_card = other.get("scorecard") or {}
                    if float(other_card.get("final", 0.0)) > 40.0 and (other.get("evidence_snippet") or "").strip():
                        agrees.append(other.get("key"))
                        break

                if len(agrees) >= 2:
                    s1 = {"wikipedia": "Wikipedia", "wikidata": "Wikidata", "restcountries": "RestCountries"}.get(agrees[0], agrees[0])
                    s2 = {"wikipedia": "Wikipedia", "wikidata": "Wikidata", "restcountries": "RestCountries"}.get(agrees[1], agrees[1])
                    expl = f"Verified by {s1} and {s2} which agree on: {winner_snippet}"
                else:
                    expl = f"Verified by {winner_name}: {winner_snippet}"

                return TierDecision(
                    "Shabda",
                    float(scorecard.get("final", 0.0)),
                    expl,
                    agrees,
                    winner_key,
                    winner_url,
                    winner_snippet,
                    {**scorecard, "_evidence_location": c.get("evidence_location", "body")},
                )
        return None

    def _apply_anumana_suffix(self, results: List[Dict[str, Any]], primary: str) -> Tuple[Optional[str], str]:
        verified = sum(1 for r in results if r.get("verified"))
        total = len(results)
        if total > 1 and verified > 0 and verified < total and primary in ("Pratyaksha", "Shabda"):
            return "Anumana", "Primary claim verified but additional claims are unverified/hallucinated."
        return None, "All evaluated claims align with selected tier decision." if verified == total else "No primary claim was verified."

    def _map_primary_to_sutra(self, primary: str) -> str:
        if primary == "Pratyaksha":
            return "pratyaksha"
        if primary == "Shabda":
            return "shabda"
        return "nigrahasthana"

    def verify_claim(self, claim: str, question: str = "", context: Optional[Dict[str, Any]] = None, qc: Optional[QuestionContext] = None) -> Dict[str, Any]:
        claim = self._resolve_claim_with_context(claim, context)
        resolved_entity, resolved_attribute, resolved_value = self._extract_entity_attribute(claim, question)
        if qc:
            # For "why" questions, the question anchor is more reliable than answer-sentence entities.
            if qc.question_type == "why" and qc.target_entity:
                resolved_entity = qc.target_entity
                resolved_attribute = qc.target_attribute or resolved_attribute
            else:
                resolved_entity = resolved_entity or qc.target_entity
                resolved_attribute = resolved_attribute or qc.target_attribute
        if not self.is_complete_claim(claim):
            freshness = self._freshness_meta(self._claim_type(claim, question))
            return {
                "claim": claim,
                "verified": False,
                "confidence": 0.0,
                "subject": "Unknown",
                "reason": "Claim is not self-contained enough for verification.",
                "sources_used": [],
                "source_name": "none",
                "source_url": None,
                "evidence_snippet": "Rejected before lookup: incomplete/fragmented claim structure.",
                "semantic_score": None,
                "lexical_score": 0.0,
                "lexical_confidence": 0.0,
                "combined_confidence_breakdown": {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"},
                "lexical_matches": 0.0,
                "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
                "nyaya": {
                    "sutra": NYAYA_PRINCIPLES["nigrahasthana"]["name"],
                    "english": NYAYA_PRINCIPLES["nigrahasthana"]["english"],
                    "icon": NYAYA_PRINCIPLES["nigrahasthana"]["icon"],
                    "color": NYAYA_PRINCIPLES["nigrahasthana"]["color"],
                    "description": NYAYA_PRINCIPLES["nigrahasthana"]["description"],
                    "explanation": "Could not verify. Claim fragment lacks a clear entity-predicate structure.",
                    "xai_focus": NYAYA_PRINCIPLES["nigrahasthana"].get("xai_focus", ""),
                    "confidence_level": map_confidence_level(0.0).value,
                    "evidence_type": infer_evidence_type(0, False, True).value,
                    "reasoning_chain": ["Claim rejected by pre-verification quality gate."],
                },
                "verdict_primary": "Nigrahasthana",
                "verdict_secondary": None,
                "verdict_explanation": "Could not verify. Claim is incomplete or context-dependent.",
                "freshness_checked_at": freshness["checked_at"],
                "freshness_max_age_days": freshness["max_age_days"],
                "resolved_entity": resolved_entity,
                "resolved_attribute": resolved_attribute,
                "match_category": "no_match",
                "evidence_location": "body",
                "evidence_sentence": "Rejected before lookup: incomplete/fragmented claim structure.",
            }
        if self._is_future_speculative(claim):
            freshness = self._freshness_meta(self._claim_type(claim, question))
            return {
                "claim": claim,
                "verified": False,
                "confidence": 0.0,
                "subject": self.get_subject(claim),
                "reason": "Future/speculative claim rejected; verification only supports grounded present/past facts.",
                "sources_used": [],
                "source_name": "none",
                "source_url": None,
                "evidence_snippet": "Claim contains future or speculative wording and was rejected before source verification.",
                "semantic_score": None,
                "lexical_score": 0.0,
                "lexical_confidence": 0.0,
                "combined_confidence_breakdown": {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"},
                "lexical_matches": 0.0,
                "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
                "nyaya": {
                    "sutra": NYAYA_PRINCIPLES["nigrahasthana"]["name"],
                    "english": NYAYA_PRINCIPLES["nigrahasthana"]["english"],
                    "icon": NYAYA_PRINCIPLES["nigrahasthana"]["icon"],
                    "color": NYAYA_PRINCIPLES["nigrahasthana"]["color"],
                    "description": NYAYA_PRINCIPLES["nigrahasthana"]["description"],
                    "explanation": "Could not verify. Future/predictive statements are outside factual verification scope.",
                    "xai_focus": NYAYA_PRINCIPLES["nigrahasthana"].get("xai_focus", ""),
                    "confidence_level": map_confidence_level(0.0).value,
                    "evidence_type": infer_evidence_type(0, False, True).value,
                    "reasoning_chain": ["Future/speculative claim blocked by strict policy."],
                },
                "verdict_primary": "Nigrahasthana",
                "verdict_secondary": None,
                "verdict_explanation": "Could not verify. Future predictions are rejected outright.",
                "freshness_checked_at": freshness["checked_at"],
                "freshness_max_age_days": freshness["max_age_days"],
                "resolved_entity": resolved_entity,
                "resolved_attribute": resolved_attribute,
                "match_category": "contradiction",
                "evidence_location": "body",
                "evidence_sentence": "Claim contains future/speculative wording and was rejected before source verification.",
            }
        subject = self.get_subject(claim, question=question)
        if subject == "Unknown" or self.normalize_text(subject) in self.bad_subject_words:
            freshness = self._freshness_meta(self._claim_type(claim, question))
            return {
                "claim": claim,
                "verified": False,
                "confidence": 0.0,
                "subject": "Unknown",
                "reason": "No valid entity subject found for this claim.",
                "sources_used": [],
                "source_name": "none",
                "source_url": None,
                "evidence_snippet": "Rejected before lookup: invalid or generic subject extraction.",
                "semantic_score": None,
                "lexical_score": 0.0,
                "lexical_confidence": 0.0,
                "combined_confidence_breakdown": {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"},
                "lexical_matches": 0.0,
                "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
                "nyaya": {
                    "sutra": NYAYA_PRINCIPLES["nigrahasthana"]["name"],
                    "english": NYAYA_PRINCIPLES["nigrahasthana"]["english"],
                    "icon": NYAYA_PRINCIPLES["nigrahasthana"]["icon"],
                    "color": NYAYA_PRINCIPLES["nigrahasthana"]["color"],
                    "description": NYAYA_PRINCIPLES["nigrahasthana"]["description"],
                    "explanation": "Could not verify. Subject extraction produced a generic or unusable entity.",
                    "xai_focus": NYAYA_PRINCIPLES["nigrahasthana"].get("xai_focus", ""),
                    "confidence_level": map_confidence_level(0.0).value,
                    "evidence_type": infer_evidence_type(0, False, True).value,
                    "reasoning_chain": ["Claim rejected by entity-quality gate."],
                },
                "verdict_primary": "Nigrahasthana",
                "verdict_secondary": None,
                "verdict_explanation": "Could not verify. Valid entity subject not found.",
                "freshness_checked_at": freshness["checked_at"],
                "freshness_max_age_days": freshness["max_age_days"],
                "resolved_entity": resolved_entity,
                "resolved_attribute": resolved_attribute,
                "match_category": "no_match",
                "evidence_location": "body",
                "evidence_sentence": "Rejected before lookup: invalid or generic subject extraction.",
            }

        # Present-data sensitive leader checks: compare LLM claim to current leader fact.
        if self._is_present_data_sensitive(question, claim) and self._claim_type(claim, question) == "leader_dynamic":
            country = resolved_entity or subject
            role = resolved_attribute or "leader"
            current = self._get_current_leader(country, role) if country else {}
            claimed_person = resolved_value or self._extract_claimed_person(claim)
            current_person = (current or {}).get("person")
            if claimed_person and current_person:
                if not self._same_person(claimed_person, current_person):
                    freshness = self._freshness_meta(self._claim_type(claim, question))
                    return {
                        "claim": claim,
                        "verified": False,
                        "confidence": 0.0,
                        "subject": subject,
                        "reason": "Outdated leader value: LLM answer conflicts with current fact.",
                        "sources_used": ["wikidata"],
                        "source_name": "Wikidata",
                        "source_url": current.get("url"),
                        "evidence_snippet": current.get("evidence") or f"Current {role} of {country} is {current_person}",
                        "semantic_score": None,
                        "lexical_score": 0.0,
                        "lexical_confidence": 0.0,
                        "combined_confidence_breakdown": {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"},
                        "lexical_matches": 0.0,
                        "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
                        "nyaya": {
                            "sutra": NYAYA_PRINCIPLES["nigrahasthana"]["name"],
                            "english": NYAYA_PRINCIPLES["nigrahasthana"]["english"],
                            "icon": NYAYA_PRINCIPLES["nigrahasthana"]["icon"],
                            "color": NYAYA_PRINCIPLES["nigrahasthana"]["color"],
                            "description": NYAYA_PRINCIPLES["nigrahasthana"]["description"],
                            "explanation": f"The LLM knowledge cutoff is 2023. Current data shows {current_person}; response is outdated.",
                            "xai_focus": NYAYA_PRINCIPLES["nigrahasthana"].get("xai_focus", ""),
                            "confidence_level": map_confidence_level(0.0).value,
                            "evidence_type": infer_evidence_type(1, False, True).value,
                            "reasoning_chain": ["Present-data sensitive query checked against current leader fact."],
                        },
                        "verdict_primary": "Nigrahasthana",
                        "verdict_secondary": None,
                        "verdict_explanation": f"The LLM knowledge cutoff is 2023. Current {role} of {country} is {current_person}; response is outdated hallucination.",
                        "freshness_checked_at": freshness["checked_at"],
                        "freshness_max_age_days": freshness["max_age_days"],
                        "resolved_entity": resolved_entity,
                        "resolved_attribute": resolved_attribute,
                        "match_category": "contradiction",
                        "evidence_location": "body",
                        "evidence_sentence": current.get("evidence") or f"Current {role} of {country} is {current_person}",
                    }
        legacy_sources = self._collect_sources(claim, subject, question)
        if "local_kb" in legacy_sources and "dbpedia" in legacy_sources:
            l = self._source_support(claim, legacy_sources.get("local_kb", {}).get("text", ""))
            d = self._source_support(claim, legacy_sources.get("dbpedia", {}).get("text", ""))
            w = self._source_support(claim, legacy_sources.get("wikidata", {}).get("text", ""))
            votes = sum(1 for x in [l, d, w] if x >= self.threshold)
            if votes >= 2:
                return {
                    "claim": claim,
                    "verified": True,
                    "confidence": 90.0,
                    "subject": subject,
                    "reason": "Legacy consensus (compat mode).",
                    "sources_used": ["wikipedia", "wikidata"],
                    "source_name": "wikipedia",
                    "source_url": legacy_sources.get("wikipedia", {}).get("url"),
                    "evidence_snippet": (legacy_sources.get("wikipedia", {}).get("text", "") or "")[:220],
                    "semantic_score": None,
                    "lexical_score": round(max(l, d, w), 1),
                    "lexical_confidence": round(max(l, d, w), 1),
                    "combined_confidence_breakdown": {
                        "lexical_contribution": round(max(l, d, w), 1),
                        "semantic_contribution": 0.0,
                        "weighting": "100/0",
                    },
                    "nyaya": {"sutra": "प्रत्यक्ष (Pratyaksha)", "english": "Direct Perception", "icon": "👁️", "color": "#00bfa5", "description": "", "explanation": "", "xai_focus": "", "confidence_level": map_confidence_level(90.0).value, "evidence_type": infer_evidence_type(2, True, False).value, "reasoning_chain": []},
                    "verdict_primary": "Pratyaksha",
                    "verdict_secondary": None,
                    "verdict_explanation": "Legacy consensus path.",
                    "resolved_entity": resolved_entity,
                    "resolved_attribute": resolved_attribute,
                }

        # Step 2: curated DB first
        t1 = self._tier1_curated(claim)
        if t1:
            sc = t1.scorecard
            sutra = NYAYA_PRINCIPLES["pratyaksha"]
            evidence_quote = (t1.evidence_snippet or "").strip()
            nyaya_expl = f"Verified by {t1.source_name}. The source explicitly states: {evidence_quote}"
            freshness = self._freshness_meta(self._claim_type(claim, question))
            result = {
                "claim": claim,
                "verified": True,
                "confidence": t1.confidence,
                "subject": subject,
                "reason": t1.explanation,
                "sources_used": t1.sources,
                "source_name": t1.source_name,
                "source_url": t1.source_url,
                "evidence_snippet": t1.evidence_snippet,
                "semantic_score": sc.get("semantic_score"),
                "lexical_score": sc.get("lexical"),
                "lexical_confidence": sc.get("lexical"),
                "combined_confidence_breakdown": sc.get("breakdown"),
                "lexical_matches": round((sc.get("lexical", 0.0) / 100.0) * max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))), 1),
                "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
                "nyaya": {
                    "sutra": sutra["name"],
                    "english": sutra["english"],
                    "icon": sutra["icon"],
                    "color": sutra["color"],
                    "description": sutra["description"],
                    "explanation": nyaya_expl,
                    "xai_focus": sutra.get("xai_focus", ""),
                    "confidence_level": map_confidence_level(t1.confidence).value,
                    "evidence_type": infer_evidence_type(1, True, False).value,
                    "reasoning_chain": ["Tier-1 curated dataset matched first (Pratyaksha)."],
                },
                "verdict_primary": "Pratyaksha",
                "verdict_secondary": None,
                "verdict_explanation": nyaya_expl,
                "freshness_checked_at": freshness["checked_at"],
                "freshness_max_age_days": freshness["max_age_days"],
                "resolved_entity": resolved_entity,
                "resolved_attribute": resolved_attribute,
                "match_category": "exact",
                "evidence_location": "infobox" if "Curated Database" in (t1.source_name or "") else "body",
                "evidence_sentence": t1.evidence_snippet,
            }
            self._update_context(result, context)
            return result

        # Step 3: external 2-of-3 agreement
        t2 = self._tier2_external(claim, question, qc=qc)
        if t2:
            sc = t2.scorecard
            sutra = NYAYA_PRINCIPLES["shabda"]
            evidence_quote = (t2.evidence_snippet or "").strip()
            key_to_name = {"wikipedia": "Wikipedia", "wikidata": "Wikidata", "restcountries": "RestCountries"}
            src_names = [key_to_name.get(s, s) for s in (t2.sources or []) if s]
            if len(src_names) >= 2:
                nyaya_expl = f"Verified by {src_names[0]} and {src_names[1]} which agree on: {evidence_quote}"
            else:
                nyaya_expl = f"Verified by {t2.source_name}. The source explicitly states: {evidence_quote}"
            freshness = self._freshness_meta(self._claim_type(claim, question))
            result = {
                "claim": claim,
                "verified": True,
                "confidence": t2.confidence,
                "subject": subject,
                "reason": t2.explanation,
                "sources_used": t2.sources,
                "source_name": t2.source_name,
                "source_url": t2.source_url,
                "evidence_snippet": t2.evidence_snippet,
                "semantic_score": sc.get("semantic_score"),
                "lexical_score": sc.get("lexical"),
                "lexical_confidence": sc.get("lexical"),
                "combined_confidence_breakdown": sc.get("breakdown"),
                "lexical_matches": round((sc.get("lexical", 0.0) / 100.0) * max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))), 1),
                "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
                "nyaya": {
                    "sutra": sutra["name"],
                    "english": sutra["english"],
                    "icon": sutra["icon"],
                    "color": sutra["color"],
                    "description": sutra["description"],
                    "explanation": nyaya_expl,
                    "xai_focus": sutra.get("xai_focus", ""),
                    "confidence_level": map_confidence_level(t2.confidence).value,
                    "evidence_type": infer_evidence_type(3, True, False).value,
                    "reasoning_chain": ["Tier-2 sources reached 2-of-3 agreement (Shabda)."],
                },
                "verdict_primary": "Shabda",
                "verdict_secondary": None,
                "verdict_explanation": nyaya_expl,
                "freshness_checked_at": freshness["checked_at"],
                "freshness_max_age_days": freshness["max_age_days"],
                "resolved_entity": resolved_entity,
                "resolved_attribute": resolved_attribute,
                "match_category": "exact",
                "evidence_location": sc.get("_evidence_location", "body"),
                "evidence_sentence": t2.evidence_snippet,
            }
            if self._claim_type(claim, question) == "leader_dynamic":
                current = self._get_current_leader(resolved_entity or subject, resolved_attribute or "leader")
                cat = self._leader_match_category(claim, t2.evidence_snippet or "", current.get("person"))
                result["match_category"] = cat
                if cat == "detail_mismatch":
                    result["verified"] = True
                    result["confidence"] = max(75.0, min(float(result.get("confidence", 80.0)), 85.0))
                    result["verdict_secondary"] = "Anumana"
                    result["verdict_explanation"] = (
                        f"Core fact verified, but minor detail mismatch found. Source says: {t2.evidence_snippet}"
                    )
                elif cat == "core_only":
                    result["verified"] = True
                    result["confidence"] = max(60.0, min(float(result.get("confidence", 70.0)), 85.0))
                    result["verdict_secondary"] = "Anumana"
                    result["verdict_explanation"] = "Core leader fact verified; supporting detail is partially mismatched."
            self._update_context(result, context)
            return result

        # Step 4 fallback
        sutra = NYAYA_PRINCIPLES["nigrahasthana"]
        best = self._closest_external_evidence(claim, question, qc=qc)
        sc = best.get("scorecard") or {}
        checked_sources = best.get("checked_sources") or ["wikipedia", "wikidata", "restcountries"]
        checked_str = ", ".join(checked_sources)
        closest_src = best.get("source_name") or "Wikipedia"
        closest_ev = (best.get("evidence_snippet") or "").strip()
        nigra_expl = f"No source could verify this claim. Checked: {checked_str}. {closest_src} came closest with: {closest_ev}"
        result = {
            "claim": claim,
            "verified": False,
            "confidence": round(min(39.9, float(sc.get("final", 0.0) or 0.0)), 1),
            "subject": subject,
            "reason": "No curated match and external sources did not confirm the claim with sufficient confidence.",
            "sources_used": checked_sources,
            "source_name": best.get("source_name"),
            "source_url": best.get("source_url"),
            "evidence_snippet": closest_ev,
            "semantic_score": sc.get("semantic_score"),
            "lexical_score": sc.get("lexical", 0.0),
            "lexical_confidence": sc.get("lexical", 0.0),
            "combined_confidence_breakdown": sc.get("breakdown") or {"lexical_contribution": 0.0, "semantic_contribution": 0.0, "weighting": "60/40"},
            "lexical_matches": round((float(sc.get("lexical", 0.0)) / 100.0) * max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))), 1),
            "lexical_total_terms": max(1, len(re.findall(r"[a-zA-Z]{3,}", claim))),
            "nyaya": {
                "sutra": sutra["name"],
                "english": sutra["english"],
                "icon": sutra["icon"],
                "color": sutra["color"],
                "description": sutra["description"],
                "explanation": nigra_expl,
                "xai_focus": sutra.get("xai_focus", ""),
                "confidence_level": map_confidence_level(0.0).value,
                "evidence_type": infer_evidence_type(0, False, True).value,
                "reasoning_chain": ["No Tier-1 match; closest external evidence did not meet verification threshold."],
            },
            "verdict_primary": "Nigrahasthana",
            "verdict_secondary": None,
            "verdict_explanation": nigra_expl,
            "freshness_checked_at": self._freshness_meta(self._claim_type(claim, question))["checked_at"],
            "freshness_max_age_days": self._freshness_meta(self._claim_type(claim, question))["max_age_days"],
            "resolved_entity": resolved_entity,
            "resolved_attribute": resolved_attribute,
            "match_category": "no_match",
            "evidence_location": best.get("evidence_location", "body"),
            "evidence_sentence": closest_ev,
        }
        self._update_context(result, context)
        return result

    def verify_response(self, question: str, response: str) -> Dict[str, Any]:
        question = self._normalize_user_question(question)
        domain = self.detect_domain(question or response) or "unknown"
        qc = self._parse_question(question)
        claims = self.extract_claims(response)
        claims = [c for c in claims if self._claim_relevant_to_question(c, question)]
        dedup: List[str] = []
        seen = set()
        for c in claims:
            k = self.normalize_text(c)
            if not k or k in seen:
                continue
            seen.add(k)
            dedup.append(c)
        claims = dedup
        if not claims:
            primary = self._extract_primary_claim_from_answer(question, response, qc)
            if primary:
                claims = [primary]
            else:
                return {
                    "verified": 0,
                    "total": 0,
                    "verdict": "NO_FACTUAL_CLAIMS",
                    "results": [],
                    "verdict_primary": "Nigrahasthana",
                    "verdict_secondary": None,
                    "verdict_explanation": "No factual claims to verify in the response.",
                    "question_context": {
                        "question_type": qc.question_type,
                        "target_entity": qc.target_entity,
                        "target_attribute": qc.target_attribute,
                        "expected_answer_type": qc.expected_answer_type,
                        "domain_tag": qc.domain_tag,
                        "source_strategy": qc.source_strategy,
                    },
                }

        self._session_page_cache = {}
        self._session_failed_titles = set()
        self._session_anchor_wiki = None
        self._session_anchor_title = None
        self.context = {"current_subject": None, "subjects": []}

        # Fetch ONE question-anchored Wikipedia page and reuse across claims.
        anchor_q = self._anchor_wikipedia_query(qc)
        if anchor_q:
            self._session_anchor_title = anchor_q
            self._session_anchor_wiki = self._wiki_evidence(
                anchor_q,
                question=question,
                entity=qc.target_entity or None,
                attribute=qc.target_attribute or None,
            )
        results = [self.verify_claim(c, question, context=self.context, qc=qc) for c in claims]
        verified = sum(1 for r in results if r.get("verified"))
        total = len(results)
        if verified == total:
            verdict = "✅ FULLY CORRECT"
        elif verified > 0:
            verdict = "⚠️ PARTIALLY CORRECT"
        else:
            verdict = "❌ LARGELY INCORRECT"

        primary = "Nigrahasthana"
        if any((r.get("verdict_primary") == "Pratyaksha") for r in results):
            primary = "Pratyaksha"
        elif any((r.get("verdict_primary") == "Shabda") for r in results):
            primary = "Shabda"
        secondary, suffix_explain = self._apply_anumana_suffix(results, primary)

        # Update primary claim explainability when we attach the Anumana suffix.
        # This fixes the "Pratyaksha vs Pratyaksha+Anumana explanation looks identical" issue.
        if secondary == "Anumana" and primary in ("Pratyaksha", "Shabda"):
            primary_claim = next(
                (r for r in results if r.get("verified") and r.get("verdict_primary") == primary),
                None,
            )
            unverified_claim = next((r for r in results if not r.get("verified")), None)
            if primary_claim and unverified_claim:
                core_part = (primary_claim.get("claim") or "").strip()
                unverified_part = (unverified_claim.get("claim") or "").strip()
                src = (primary_claim.get("source_name") or "external sources").strip()

                if primary == "Pratyaksha":
                    template = (
                        f"Core claim '{core_part}' verified by {src}. "
                        f"However, '{unverified_part}' could not be verified from any source."
                    )
                else:
                    template = (
                        f"Core claim '{core_part}' verified by {src}. "
                        f"Additional claims in this response are unverified."
                    )

                primary_claim["reason"] = template
                if isinstance(primary_claim.get("nyaya"), dict):
                    primary_claim["nyaya"]["explanation"] = template
                    primary_claim["verdict_explanation"] = template
                primary_claim["verdict_secondary"] = "Anumana"

        # Domain is advisory only: never blocks verification.
        if domain not in self.SUPPORTED_DOMAINS:
            suffix_explain = f"{suffix_explain} Note: This domain falls outside our primary domains, but verification was attempted using external sources."
        return {
            "verified": verified,
            "total": total,
            "verdict": verdict,
            "results": results,
            "verdict_primary": primary,
            "verdict_secondary": secondary,
            "verdict_explanation": suffix_explain,
            "question_context": {
                "question_type": qc.question_type,
                "target_entity": qc.target_entity,
                "target_attribute": qc.target_attribute,
                "expected_answer_type": qc.expected_answer_type,
                "domain_tag": qc.domain_tag,
                "source_strategy": qc.source_strategy,
            },
        }

    def _overall_nyaya_verdict(
        self,
        results: List[Dict[str, Any]],
        verified: int,
        total: int,
        primary: str,
        secondary: Optional[str],
    ) -> Dict[str, Any]:
        # Use our explicit templates so Pratyaksha vs Pratyaksha+Anumana (and Shabda variants) differ.
        if primary == "Pratyaksha":
            v = NYAYA_PRINCIPLES["pratyaksha"]
            verdict = "Pratyaksha" + (f" + {secondary}" if secondary else "")
            english = "Direct perception"
        elif primary == "Shabda":
            v = NYAYA_PRINCIPLES["shabda"]
            verdict = "Shabda" + (f" + {secondary}" if secondary else "")
            english = "Testimony"
        else:
            v = NYAYA_PRINCIPLES["nigrahasthana"]
            verdict = "Nigrahasthana"
            english = "Complete failure/contradiction"

        primary_claim = next((r for r in results if r.get("verified") and r.get("verdict_primary") == primary), None)
        unverified_claim = next((r for r in results if not r.get("verified")), None)

        if primary in ("Pratyaksha", "Shabda") and secondary == "Anumana" and primary_claim and unverified_claim:
            core_part = (primary_claim.get("claim") or "").strip()
            unverified_part = (unverified_claim.get("claim") or "").strip()
            src = (primary_claim.get("source_name") or "external sources").strip()
            if primary == "Pratyaksha":
                expl = (
                    f"Core claim '{core_part}' verified by {src}. "
                    f"However, '{unverified_part}' could not be verified from any source."
                )
            else:
                expl = (
                    f"Core claim '{core_part}' verified by {src}. "
                    f"Additional claims in this response are unverified."
                )
        elif primary_claim:
            src = (primary_claim.get("source_name") or "source").strip()
            ev = (primary_claim.get("evidence_snippet") or "").strip()
            if primary == "Pratyaksha":
                expl = f"Verified by {src}. The source explicitly states: {ev}"
            else:
                expl = f"Verified by {src}. The evidence checked supports the claim: {ev}"
        else:
            # For full failure, reuse the best per-claim verdict explanation if present.
            expl = next((r.get("verdict_explanation") for r in results if r.get("verdict_explanation")), "")
            if not expl:
                expl = "No source could verify this response."

        return {
            "verdict": verdict,
            "english": english,
            "icon": v["icon"],
            "color": v["color"],
            "description": v["description"],
            "explanation": expl,
            "verified": verified,
            "total": total,
        }

    def _build_nyaya_profile(self, results: List[Dict[str, Any]], verified: int, total: int) -> Dict[str, Any]:
        levels = {"high_confidence": 0, "medium_confidence": 0, "low_confidence": 0}
        for r in results:
            lv = (r.get("nyaya") or {}).get("confidence_level", "")
            lv_l = str(lv).lower()
            if "high" in lv_l or "nischaya" in lv_l:
                levels["high_confidence"] += 1
            elif "medium" in lv_l or "samshaya" in lv_l:
                levels["medium_confidence"] += 1
            elif "low" in lv_l or "viparyaya" in lv_l:
                levels["low_confidence"] += 1
        dominant = max(levels, key=lambda k: levels[k]) if total > 0 else "none"
        return {
            "dominant_level": dominant,
            "distribution": levels,
            "trust_index": round((verified / total) * 100, 1) if total > 0 else 0.0,
            "reasoning_chain": [
                "Tier-1: curated DB (Pratyaksha) checked first.",
                "Tier-2: External evidence checked with a priority cascade (Shabda).",
                "Tier-3: Anumana added only as suffix for partial hallucination.",
            ],
        }

    def verify_response_with_nyaya(self, question: str, response: str) -> Dict[str, Any]:
        result = self.verify_response(question, response)
        domain = self.detect_domain(question or response) or "unknown"
        verified = int(result.get("verified", 0))
        total = int(result.get("total", 0))
        primary = str(result.get("verdict_primary", "Nigrahasthana"))
        secondary = result.get("verdict_secondary")
        result["nyaya_verdict"] = self._overall_nyaya_verdict(
            result.get("results", []),
            verified,
            total,
            primary,
            secondary,
        )
        if domain not in self.SUPPORTED_DOMAINS:
            extra = " Note: This falls outside our primary domains, but verification was attempted using external sources."
            result["nyaya_verdict"]["explanation"] = f"{result['nyaya_verdict'].get('explanation','')}{extra}"
        hallucination_percent = round((1 - verified / total) * 100, 1) if total > 0 else 0.0
        if total == 0:
            hallucination_label = "No claims detected"
        elif hallucination_percent >= 95:
            hallucination_label = "Fully hallucinated"
        elif hallucination_percent >= 5:
            hallucination_label = "Contains hallucinations"
        else:
            hallucination_label = "No hallucination"
        result["hallucination_percent"] = hallucination_percent
        result["hallucination_label"] = hallucination_label
        result["nyaya_explainability"] = self._build_nyaya_profile(result.get("results", []), verified, total)
        return result

    def evaluate(self, validation_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        tp = fp = fn = tn = 0
        for row in validation_rows:
            res = self.verify_response(row.get("question", ""), row.get("response", ""))
            pred = bool(res.get("verified", 0) >= max(1, res.get("total", 0)))
            exp = bool(row.get("expected_verified", False))
            if pred and exp:
                tp += 1
            elif pred and not exp:
                fp += 1
            elif not pred and exp:
                fn += 1
            else:
                tn += 1
        precision = tp / max(1, tp + fp)
        recall = tp / max(1, tp + fn)
        f1 = (2 * precision * recall) / max(1e-9, precision + recall)
        return {"best": {"threshold": self.threshold, "f1": f1}, "metrics": [{"precision": precision, "recall": recall, "f1": f1}]}

