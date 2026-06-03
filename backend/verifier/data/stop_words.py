"""
STOP WORDS - Common words to ignore in subject extraction
These are words that don't help identify the main subject of a claim
"""

# ============================================
# CORE STOP WORDS
# ============================================

STOP_WORDS = {
    # Articles
    'the', 'a', 'an',
    
    # Being verbs
    'is', 'are', 'was', 'were', 'be', 'been', 'being', 'am',
    
    # Prepositions
    'in', 'at', 'on', 'for', 'to', 'with', 'of', 'and', 'or', 'but',
    'by', 'from', 'up', 'down', 'into', 'onto', 'upon', 'via',
    
    # Pronouns
    'it', 'he', 'she', 'they', 'we', 'you', 'i', 'me', 'him', 'her',
    'us', 'them', 'my', 'your', 'his', 'its', 'our', 'their',
    
    # Demonstratives
    'this', 'that', 'these', 'those',
    
    # Possessives
    'my', 'your', 'his', 'her', 'its', 'our', 'their', 'mine', 'yours',
    'hers', 'ours', 'theirs',
    
    # Time-related
    'now', 'then', 'today', 'yesterday', 'tomorrow', 'always', 'never',
    'often', 'sometimes', 'usually', 'frequently', 'rarely',
    
    # Quantity
    'some', 'any', 'many', 'much', 'most', 'few', 'several', 'all',
    'both', 'each', 'every', 'either', 'neither',
    
    # Question words
    'what', 'why', 'when', 'where', 'who', 'whom', 'whose', 'which',
    'how', 'whether',
    
    # Conjunctions
    'and', 'or', 'but', 'because', 'since', 'although', 'though',
    'if', 'unless', 'while', 'whereas', 'however', 'therefore',
    
    # Adverbs
    'very', 'quite', 'rather', 'pretty', 'somewhat', 'fairly',
    'extremely', 'highly', 'deeply', 'greatly',
    
    # Approximation
    'about', 'around', 'approximately', 'roughly', 'nearly', 'almost',
    'just', 'exactly', 'precisely', 'virtually',
    
    # Existence
    'there', 'here', 'everywhere', 'anywhere', 'somewhere', 'nowhere',
    
    # Modal verbs
    'can', 'could', 'will', 'would', 'shall', 'should', 'may', 'might',
    'must', 'ought', 'need', 'dare',
    
    # Common verbs (non-factual)
    'think', 'believe', 'feel', 'seem', 'appear', 'look', 'sound',
    'become', 'remain', 'stay', 'keep', 'continue',
    
    # Common nouns (too generic)
    'thing', 'stuff', 'way', 'kind', 'type', 'sort', 'part', 'piece',
    'bit', 'lot', 'number', 'amount', 'level', 'point', 'fact',
    
    # Filler words
    'well', 'so', 'then', 'just', 'like', 'basically', 'actually',
    'literally', 'basically', 'essentially', 'practically',

    # LLM/discourse wrappers often present in generated answers
    'summary', 'overall', 'generally', 'typically', 'notably', 'importantly',
    'however', 'therefore', 'moreover', 'furthermore', 'meanwhile',
    'in', 'summary', 'in summary', 'in conclusion',

    # List formatting tokens that should not become subjects
    'first', 'second', 'third', 'fourth', 'fifth',
    '1', '2', '3', '4', '5',
}

# ============================================
# PRONOUNS - For context resolution
# ============================================

PRONOUNS = {
    # Subject pronouns
    'it', 'he', 'she', 'they', 'we', 'you', 'i',
    
    # Object pronouns
    'me', 'him', 'her', 'us', 'them',
    
    # Possessive pronouns
    'its', 'his', 'her', 'their', 'our', 'my', 'your',
    
    # Demonstrative pronouns
    'this', 'that', 'these', 'those',
    
    # Indefinite pronouns
    'someone', 'something', 'anyone', 'anything', 'everyone',
    'everything', 'no one', 'nothing', 'one', 'ones',
}

# ============================================
# VERBS THAT INDICATE FACTS (included separately)
# ============================================

# These are NOT stop words - they're important for fact detection
FACT_VERBS = {
    'is', 'are', 'was', 'were', 'has', 'have', 'had',
    'invented', 'discovered', 'created', 'developed', 'founded',
    'wrote', 'composed', 'painted', 'built', 'designed',
    'orbits', 'rotates', 'revolves', 'contains', 'consists',
    'located', 'situated', 'found', 'exists', 'lives',
    'born', 'died', 'occurred', 'happened', 'took place',
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def is_stop_word(word):
    """Check if a word is a stop word"""
    return word.lower() in STOP_WORDS

def is_pronoun(word):
    """Check if a word is a pronoun"""
    return word.lower() in PRONOUNS

def is_fact_verb(word):
    """Check if a word is a fact-indicating verb"""
    return word.lower() in FACT_VERBS

def clean_text(text):
    """Remove stop words from text (for debugging)"""
    words = text.split()
    return ' '.join([w for w in words if not is_stop_word(w)])

# ============================================
# TEST THE FILE (if run directly)
# ============================================

if __name__ == "__main__":
    print("🧪 Testing stop_words.py")
    print("=" * 50)
    
    test_words = ['the', 'is', 'in', 'paris', 'france', 'it', 'he']
    
    print("\n📋 Stop Word Check:")
    for word in test_words:
        print(f"  '{word}': is_stop_word={is_stop_word(word)}, is_pronoun={is_pronoun(word)}")
    
    test_sentence = "The capital of France is Paris"
    print(f"\n📝 Original: {test_sentence}")
    print(f"📝 Cleaned:  {clean_text(test_sentence)}")
    
    print(f"\n✅ Stop words file loaded successfully!")
    print(f"   Total stop words: {len(STOP_WORDS)}")
    print(f"   Total pronouns: {len(PRONOUNS)}")
    print(f"   Total fact verbs: {len(FACT_VERBS)}")