"""
Diagnostic test to see what's happening with false claims
"""
import sys
import os
import re
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.verifier.improved_verifier import NyayaVerifier

def diagnose_false_claim():
    verifier = NyayaVerifier()
    
    print("\n🔍 DIAGNOSING FALSE CLAIM DETECTION")
    print("=" * 60)
    
    claim = "The Moon is made of cheese"
    print(f"\nClaim: {claim}")
    
    # Step 1: Get subject
    subject = verifier.get_subject(claim)
    print(f"Subject: '{subject}'")
    
    # Step 2: Find Wikipedia page
    page, found_subject = verifier.find_best_page(subject, claim)
    print(f"Wikipedia page: {page.title if page else 'Not found'}")
    
    if page:
        # Step 3: Get key terms
        terms = verifier.get_key_terms(claim, found_subject.lower())
        print(f"Key terms: {terms}")
        
        # Step 4: Calculate confidence step by step
        content = (page.summary + " " + page.title).lower()
        print(f"\nContent preview: {content[:200]}...")
        
        matches = 0
        partial_matches = 0
        
        print("\nTerm matching:")
        for term in terms:
            term_lower = term.lower()
            print(f"\n  Term: '{term}'")
            
            if term_lower in content:
                matches += 1
                print(f"    ✓ Exact match in content")
            elif term_lower in page.title.lower():
                matches += 1
                print(f"    ✓ Match in page title")
            else:
                # Check partial matches
                found = False
                for word in content.split()[:100]:
                    if len(word) > 3:
                        if term_lower in word or word in term_lower:
                            partial_matches += 0.5
                            print(f"    ⚠ Partial match: '{word}'")
                            found = True
                            break
                if not found:
                    print(f"    ✗ No match found")
        
        total_matches = matches + partial_matches
        base_confidence = (total_matches / len(terms)) * 100
        print(f"\nBase confidence: {base_confidence:.1f}% ({matches} exact + {partial_matches} partial)")
        
        # Show bonuses applied
        claim_lower = claim.lower()
        bonuses = 0
        
        # Check location bonus (fixed - check whole words)
        location_words = ['located', 'flows', 'orbits', 'in', 'on', 'at']
        is_location_claim = False
        for word in claim_lower.split():
            if word in location_words:
                is_location_claim = True
                break
        if is_location_claim:
            bonuses += 10
            print(f"Location bonus: +10%")
        
        # Check superlative bonus
        superlative_words = ['largest', 'smallest', 'highest', 'lowest', 'longest', 'shortest']
        if any(word in claim_lower for word in superlative_words):
            bonuses += 5
            print(f"Superlative bonus: +5%")
        
        # Check number bonus
        if re.search(r'\d', claim):
            bonuses += 5
            print(f"Number bonus: +5%")
        
        # Check unlikely combination penalty
        unlikely_pairs = [
            ('moon', 'cheese'),
            ('earth', 'flat'),
            ('sun', 'small'),
            ('mars', 'inhabited'),
            ('water', 'poisonous'),
            ('moon', 'made of cheese'),
        ]
        for term1, term2 in unlikely_pairs:
            if term1 in claim_lower and term2 in claim_lower:
                bonuses -= 20
                print(f"Unlikely combination penalty: -20% ({term1} + {term2})")
                break
        
        final_confidence = min(max(base_confidence + bonuses, 0), 100)
        print(f"\nFinal confidence: {final_confidence:.1f}%")

if __name__ == "__main__":
    diagnose_false_claim()