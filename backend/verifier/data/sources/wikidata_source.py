"""
Wikidata Source - Structured Data Verification
Free, unlimited, no API key required
"""
import requests
import json
import re
import time
from typing import Optional, Dict, Any

class WikidataSource:
    def __init__(self):
        # Use multiple endpoints for redundancy
        self.endpoints = [
            "https://www.wikidata.org/w/api.php",
            "https://wikidata.org/w/api.php",
            "https://query.wikidata.org/sparql"
        ]
        self.current_endpoint = 0
        
        # Common Wikidata properties (P-IDs)
        self.properties = {
            'capital': 'P36',
            'population': 'P1082',
            'area': 'P2046',
            'country': 'P17',
            'born': 'P569',
            'died': 'P570',
            'inception': 'P571',
            'official_language': 'P37',
            'head_of_state': 'P35',
            'president': 'P35',
            'prime_minister': 'P6',
            'currency': 'P38',
            'highest_point': 'P610',
            'lowest_point': 'P1589',
            'continent': 'P30',
            'located_in': 'P131',
            'instance_of': 'P31',
            'occupation': 'P106',
            'educated_at': 'P69',
            'spouse': 'P26',
            'child': 'P40',
            'discovered': 'P575',
            'inventor': 'P61',
            'author': 'P50',
            'composer': 'P86',
            'director': 'P57',
            'screenwriter': 'P58'
        }
        
        # Special multi-word entities
        self.special_entities = {
            'albert einstein': 'Albert Einstein',
            'leonardo da vinci': 'Leonardo da Vinci',
            'mona lisa': 'Mona Lisa',
            'william shakespeare': 'William Shakespeare',
            'narendra modi': 'Narendra Modi',
            'mount everest': 'Mount Everest',
            'amazon river': 'Amazon River',
            'river seine': 'River Seine',
            'world war 2': 'World War II',
            'world war ii': 'World War II',
            'pacific ocean': 'Pacific Ocean',
            'atlantic ocean': 'Atlantic Ocean',
            'indian ocean': 'Indian Ocean',
            'united states': 'United States',
            'united kingdom': 'United Kingdom',
            'south africa': 'South Africa',
            'new zealand': 'New Zealand',
            'new york': 'New York City',
            'los angeles': 'Los Angeles',
            'san francisco': 'San Francisco'
        }
        
        # Cache for results
        self.cache = {}
        self.country_qids = {
            "india": "Q668",
            "iran": "Q794",
            "france": "Q142",
            "united states": "Q30",
            "united kingdom": "Q145",
        }
        
        # User agent to avoid blocking
        self.headers = {
            'User-Agent': 'NyayaNLP/1.0 (research project; contact@example.com)',
            'Accept': 'application/json'
        }
    
    def make_request(self, url, params=None, timeout=10):
        """Make a request with retry logic"""
        for attempt in range(3):  # Try 3 times
            try:
                response = requests.get(
                    url, 
                    params=params, 
                    headers=self.headers, 
                    timeout=timeout
                )
                if response.status_code == 200:
                    return response.json()
                else:
                    print(f"  Wikidata attempt {attempt+1}: HTTP {response.status_code}")
            except requests.exceptions.Timeout:
                print(f"  Wikidata attempt {attempt+1}: Timeout")
            except requests.exceptions.ConnectionError:
                print(f"  Wikidata attempt {attempt+1}: Connection error")
            except json.JSONDecodeError:
                print(f"  Wikidata attempt {attempt+1}: JSON decode error")
            except Exception as e:
                print(f"  Wikidata attempt {attempt+1}: {str(e)}")
            
            time.sleep(1)  # Wait before retry
        
        return None
    
    def search_entity(self, query: str) -> Optional[Dict]:
        """
        Search for an entity in Wikidata
        Returns the best match with entity ID
        """
        # Check cache first
        cache_key = f"search_{query}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            ql = (query or "").strip().lower()
            if ql in self.country_qids:
                qid = self.country_qids[ql]
                return {
                    "id": qid,
                    "label": query.title(),
                    "description": "country",
                    "url": f"https://www.wikidata.org/wiki/{qid}",
                }

            params = {
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "search": query,
                "limit": 5,
                "type": "item"
            }
            
            data = self.make_request(self.endpoints[0], params)
            
            if data and data.get('search'):
                results = data["search"]
                # Prefer entries explicitly described as countries when query looks like country.
                if re.search(r"(?i)\b(country|capital|currency|population)\b", query):
                    for r in results:
                        if "country" in (r.get("description", "").lower()):
                            result = r
                            break
                    else:
                        result = results[0]
                else:
                    result = results[0]
                entity = {
                    'id': result['id'],
                    'label': result.get('label', query),
                    'description': result.get('description', ''),
                    'url': f"https://www.wikidata.org/wiki/{result['id']}"
                }
                self.cache[cache_key] = entity
                return entity
            
            return None
        except Exception as e:
            print(f"  Wikidata search error: {e}")
            return None
    
    def search_entity_with_fallback(self, query: str) -> Optional[Dict]:
        """
        Search with fallback strategies for common entities
        """
        # Try exact search first
        result = self.search_entity(query)
        if result:
            return result
        
        # Try with first word only (for "Albert Einstein" -> "Albert" might not work)
        words = query.split()
        if len(words) > 1:
            # Try with full name as single string
            result = self.search_entity(query.replace(' ', '_'))
            if result:
                return result
            
            # Try with last name (e.g., "Einstein")
            result = self.search_entity(words[-1])
            if result:
                # Check if the result is the correct person
                desc = result.get('description', '').lower()
                if any(term in desc for term in ['physicist', 'scientist', 'theoretical physicist', 'painter', 'artist', 'writer']):
                    return result
        
        return None
    
    def get_entity_data(self, entity_id: str) -> Optional[Dict]:
        """
        Get all data for a specific entity
        """
        cache_key = f"entity_{entity_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            params = {
                "action": "wbgetentities",
                "format": "json",
                "ids": entity_id,
                "props": "claims|labels|descriptions"
            }
            
            data = self.make_request(self.endpoints[0], params)
            
            if data:
                entities = data.get('entities', {})
                if entity_id in entities:
                    entity_data = entities[entity_id]
                    self.cache[cache_key] = entity_data
                    return entity_data
            
            return None
        except Exception as e:
            print(f"  Wikidata entity error: {e}")
            return None
    
    def get_property_value(self, entity_id: str, property_id: str) -> Optional[str]:
        """
        Get the value of a specific property for an entity
        """
        try:
            entity_data = self.get_entity_data(entity_id)
            if not entity_data:
                return None
            
            claims = entity_data.get('claims', {})
            if property_id not in claims:
                return None
            
            # Get the first claim
            claim = claims[property_id][0]
            mainsnak = claim.get('mainsnak', {})
            datavalue = mainsnak.get('datavalue', {})
            
            if not datavalue:
                return None
            
            value = datavalue.get('value')
            
            # Handle different value types
            if isinstance(value, dict):
                # For quantity values (population, area)
                if 'amount' in value:
                    amount = value['amount']
                    # Remove the "http://www.wikidata.org/entity/" prefix if present
                    if 'http' in amount:
                        return amount.split('/')[-1]
                    return amount
                # For time values (dates)
                if 'time' in value:
                    time_str = value['time']
                    # Extract year from format like "+1879-00-00T00:00:00Z"
                    match = re.search(r'([+-]?\d{4})', time_str)
                    if match:
                        return match.group(1)
                    return time_str
                # For entity references
                if 'id' in value:
                    ref_entity = self.search_entity_by_id(value['id'])
                    if ref_entity:
                        return ref_entity.get('label', value['id'])
                    return value['id']
                if 'text' in value:
                    return value['text']
            
            return str(value) if value else None
            
        except Exception as e:
            print(f"  Wikidata property error: {e}")
            return None
    
    def search_entity_by_id(self, entity_id: str) -> Optional[Dict]:
        """
        Get entity details by ID
        """
        cache_key = f"id_{entity_id}"
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        try:
            params = {
                "action": "wbgetentities",
                "format": "json",
                "ids": entity_id,
                "props": "labels|descriptions"
            }
            
            data = self.make_request(self.endpoints[0], params)
            
            if data:
                entities = data.get('entities', {})
                if entity_id in entities:
                    entity = entities[entity_id]
                    labels = entity.get('labels', {})
                    descs = entity.get('descriptions', {})
                    result = {
                        'id': entity_id,
                        'label': labels.get('en', {}).get('value', entity_id),
                        'description': descs.get('en', {}).get('value', '')
                    }
                    self.cache[cache_key] = result
                    return result
            
            return None
        except Exception as e:
            print(f"  Wikidata entity by ID error: {e}")
            return None
    
    def extract_subject(self, claim: str) -> Optional[str]:
        """
        Extract the main subject from a claim - Improved for full names
        """
        claim_lower = claim.lower()
        
        # Check for special multi-word entities first
        for key, value in self.special_entities.items():
            if key in claim_lower:
                return value
        
        # Extract potential entity (look for capitalized words)
        words = claim.split()
        proper_nouns = []
        
        for i, word in enumerate(words[:5]):  # Check first 5 words
            clean_word = re.sub(r'[^\w\s]', '', word)
            if clean_word and clean_word[0].isupper() and len(clean_word) > 1:
                # Skip common words
                if clean_word.lower() not in ['the', 'a', 'an', 'this', 'that', 'by', 'in', 'on', 'at']:
                    # Check if next word is also capitalized (multi-word entity)
                    if i + 1 < len(words):
                        next_word = re.sub(r'[^\w\s]', '', words[i+1])
                        if next_word and next_word[0].isupper():
                            proper_nouns.append(f"{clean_word} {next_word}")
                            break
                    proper_nouns.append(clean_word)
                    break
        
        if proper_nouns:
            return proper_nouns[0]
        
        return None
    
    def determine_property(self, claim: str) -> Optional[str]:
        """
        Determine which property to check based on claim - Improved
        """
        claim_lower = claim.lower()
        
        # Direct matches
        for prop_name, prop_id in self.properties.items():
            if prop_name in claim_lower:
                return prop_id
        
        # Pattern-based detection (expanded)
        patterns = {
            'capital': ['capital of', 'capital city', 'capital is'],
            'population': ['population', 'people live', 'inhabitants', 'population of'],
            'area': ['area', 'square', 'km²', 'sq mi', 'size of'],
            'born': ['born in', 'birthplace', 'born on', 'was born'],
            'died': ['died in', 'deathplace', 'died on', 'died at'],
            'author': ['written by', 'author of', 'wrote', 'written by'],
            'composer': ['composed by', 'composer of', 'music by'],
            'inventor': ['invented by', 'inventor of', 'created by'],
            'currency': ['currency', 'money', 'monetary unit'],
            'prime_minister': ['prime minister', 'pm of', 'current pm'],
            'president': ['president of', 'current president'],
            'location': ['located in', 'situated in', 'found in']
        }
        
        for prop_name, keywords in patterns.items():
            for keyword in keywords:
                if keyword in claim_lower:
                    return self.properties.get(prop_name)
        
        return None
    
    def verify_claim(self, claim: str) -> Optional[Dict]:
        """
        Verify a claim using Wikidata - Improved for full names
        """
        # Step 1: Extract subject
        subject = self.extract_subject(claim)
        if not subject:
            print(f"  Wikidata: Could not extract subject from '{claim[:50]}'")
            return None
        
        print(f"  Wikidata: Searching for '{subject}'")
        
        # Step 2: Find entity with fallback
        entity = self.search_entity_with_fallback(subject)
        
        # If not found, try direct search
        if not entity:
            entity = self.search_entity(subject)
        
        if not entity:
            print(f"  Wikidata: No entity found for '{subject}'")
            return None
        
        print(f"  Wikidata: Found entity '{entity['label']}' ({entity['id']})")
        
        # Step 3: Determine property to check
        property_id = self.determine_property(claim)
        if not property_id:
            print(f"  Wikidata: Could not determine property for claim")
            return None
        
        # Step 4: Get property value
        value = self.get_property_value(entity['id'], property_id)
        if not value:
            print(f"  Wikidata: No value found for property {property_id}")
            return None
        
        # Step 5: Check if the value matches the claim
        claim_lower = claim.lower()
        value_lower = str(value).lower()
        
        # Simple matching
        if value_lower in claim_lower:
            confidence = 95
            evidence = f"Wikidata confirms: {value}"
        elif any(word in claim_lower for word in value_lower.split()[:3]):
            confidence = 80
            evidence = f"Wikidata partially matches: {value}"
        else:
            confidence = 70
            evidence = f"Wikidata shows: {value}"
        
        return {
            'verified': True,
            'confidence': confidence,
            'source': 'wikidata',
            'evidence': evidence,
            'entity': entity['label'],
            'property': property_id,
            'value': value,
            'url': entity['url']
        }

    def _property_claim_agreement(self, claim: str, property_id: str, value: str) -> str:
        """How well Wikidata property value aligns with the claim text."""
        claim_lower = claim.lower()
        value_lower = value.lower().strip()
        if not value_lower:
            return "neutral"
        if value_lower in claim_lower:
            return "support"
        for w in value_lower.split():
            if len(w) > 3 and w in claim_lower:
                return "support"
        if property_id == "P36":
            m = re.search(
                r"capital(?:\s+city)?(?:\s+of\s+[^,.]+)?\s+is\s+"
                r"([A-Za-z][A-Za-z\s\-]{2,48}?)(?:\.|,|$|\s+and\s)",
                claim,
                re.I,
            )
            if m:
                stated = m.group(1).strip().lower().replace("-", " ")
                val_norm = value_lower.replace("-", " ")
                if stated and stated not in val_norm and val_norm not in stated:
                    return "conflict"
        return "neutral"

    def get_evidence_for_claim(self, claim: str, subject_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        Structured Wikidata snippet plus support / neutral / conflict for a detected property.
        Uses subject_hint from the lexical pipeline when available.
        """
        hint = (subject_hint or "").strip()
        subject = hint or self.extract_subject(claim)
        if not subject:
            return {
                "text": "",
                "property_match": None,
                "url": None,
                "entity_label": None,
                "property_id": None,
                "property_value": None,
            }

        entity = self.search_entity_with_fallback(subject) or self.search_entity(subject)
        if not entity:
            return {
                "text": "",
                "property_match": None,
                "url": None,
                "entity_label": None,
                "property_id": None,
                "property_value": None,
            }

        parts = [entity.get("label", ""), entity.get("description", "")]
        prop_id = self.determine_property(claim)
        prop_val = None
        match_status = None
        if prop_id:
            prop_val = self.get_property_value(entity["id"], prop_id)
            if prop_val:
                parts.append(f"{prop_id}: {prop_val}")
                match_status = self._property_claim_agreement(claim, prop_id, str(prop_val))

        text = " ".join(p for p in parts if p)
        return {
            "text": text,
            "property_match": match_status,
            "url": entity.get("url"),
            "entity_label": entity.get("label"),
            "property_id": prop_id,
            "property_value": prop_val,
        }

# Test function
if __name__ == "__main__":
    print("Testing Wikidata Source")
    print("=" * 50)
    
    wd = WikidataSource()
    
    test_claims = [
        "The capital of France is Paris",
        "The population of India is about 1.4 billion",
        "Albert Einstein was born in Germany",
        "The Mona Lisa was painted by Leonardo da Vinci",
        "Who wrote Romeo and Juliet?",
        "What is the currency of Japan?"
    ]
    
    for claim in test_claims:
        print(f"\nClaim: {claim}")
        result = wd.verify_claim(claim)
        if result:
            print(f"  ✅ Verified - Confidence: {result['confidence']}%")
            print(f"     {result['evidence']}")
            print(f"     Source: {result['url']}")
        else:
            print(f"  ❌ Could not verify")
    
    print("\n" + "=" * 50)
    print("Wikidata source ready for integration!")