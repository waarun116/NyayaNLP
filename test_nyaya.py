"""
Test Nyaya philosophy integration with the verifier
"""
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from backend.verifier.improved_verifier import NyayaVerifier

def test_nyaya_integration():
    """Test the Nyaya philosophy integration"""
    verifier = NyayaVerifier()
    
    test_cases = [
        {
            'name': 'Fully Correct Response',
            'question': 'What is the capital of France?',
            'response': 'The capital of France is Paris. It is located on the River Seine.'
        },
        {
            'name': 'Partially Correct Response',
            'question': 'Tell me about Einstein',
            'response': 'Einstein developed the theory of relativity. He was born in Germany in 1879.'
        },
        {
            'name': 'Mixed Response with False Claim',
            'question': 'Tell me about the Moon',
            'response': 'The Moon is made of cheese. It orbits Earth every 27.3 days.'
        }
    ]
    
    print("\n" + "="*70)
    print("🕉️  NYAYA PHILOSOPHY INTEGRATION TEST")
    print("="*70)
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n📌 TEST {i}: {test['name']}")
        print("-"*50)
        
        # Use the new Nyaya-enabled method
        result = verifier.verify_response_with_nyaya(test['question'], test['response'])
        
        # Display overall Nyaya verdict
        verdict = result['nyaya_verdict']
        print(f"\n📜 OVERALL NYAYA VERDICT:")
        print(f"   {verdict['icon']} {verdict['verdict']}")
        print(f"   {verdict['explanation']}")
        print(f"   Verified: {verdict['verified']}/{verdict['total']} claims")
        
        # Display each claim with Nyaya analysis
        if 'results' in result:
            print(f"\n🔍 CLAIM ANALYSIS:")
            for j, claim in enumerate(result['results'], 1):
                print(f"\n   Claim {j}: {claim['claim'][:60]}...")
                nyaya = claim['nyaya']
                status = "✅" if claim['verified'] else "❌"
                print(f"   {status} {nyaya['icon']} {nyaya['sutra']}")
                print(f"      Confidence: {claim['confidence']}%")
                print(f"      {nyaya['description']}")
        
        print("\n" + "="*70)

if __name__ == "__main__":
    test_nyaya_integration()