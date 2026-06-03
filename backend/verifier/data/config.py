"""
CONFIGURATION - Settings for the Nyaya Verifier
All tunable parameters in one place for easy adjustment
"""

# ============================================
# CONFIDENCE THRESHOLDS
# ============================================

# Minimum confidence to consider a claim verified
# Range: 0-100, Default: 45
# Higher = more strict, Lower = more lenient
CONFIDENCE_THRESHOLD = 45

# Thresholds for different verification levels
THRESHOLDS = {
    'high_confidence': 80,    # Very likely true
    'medium_confidence': 60,   # Probably true
    'low_confidence': 40,      # Possibly true
    'very_low_confidence': 20, # Unlikely
}

# ============================================
# SIMILARITY MATCHING
# ============================================

# SequenceMatcher ratios for different match qualities
SIMILARITY = {
    'exact_match': 1.0,        # Perfect match
    'high_similarity': 0.9,     # Very close match
    'good_similarity': 0.8,     # Good match (counts as match)
    'medium_similarity': 0.7,   # Decent match
    'partial_match': 0.6,       # Partial match (counts as 0.5)
    'weak_match': 0.5,          # Weak match (counts as 0.3)
}

# ============================================
# NUMBER MATCHING TOLERANCES
# ============================================

# For exact number matching
NUMBER_TOLERANCE = {
    'absolute': 5,              # Allow difference of ±5 (for small numbers)
    'relative': 0.01,           # Allow 1% difference (for large numbers)
    'year_tolerance': 1,        # For years, allow ±1 year
}

# Numbers to treat specially (like years, dates)
SPECIAL_NUMBERS = {
    'years': range(1000, 2100),  # Years from 1000-2100
    'decades': range(1900, 2100, 10),  # Decades
    'centuries': [f"{i}th century" for i in range(1, 22)],  # 1st-21st century
}

# ============================================
# WIKIPEDIA SEARCH SETTINGS
# ============================================

# How much of Wikipedia to check
WIKIPEDIA = {
    'max_summary_words': 300,    # Words to check in summary
    'max_search_attempts': 6,    # Number of search strategies
    'cache_results': True,        # Cache Wikipedia results
    'cache_size': 100,            # Max cached pages
    'timeout_seconds': 5,         # Timeout for Wikipedia requests
}

# ============================================
# CONTEXT TRACKING
# ============================================

CONTEXT = {
    'max_entities': 10,           # Maximum entities to remember
    'max_claim_history': 20,      # Maximum claim history to keep
    'pronoun_lookback': 3,        # How far back to look for pronoun references
}

# ============================================
# CLAIM EXTRACTION
# ============================================

CLAIM_EXTRACTION = {
    'min_sentence_length': 5,     # Minimum characters for a claim
    'max_sentence_length': 500,    # Maximum characters for a claim
    'require_capital_start': True, # Sentences should start with capital
    'number_pattern': r'\b\d+\b',  # Pattern to find numbers
}

# ============================================
# BONUSES AND PENALTIES
# ============================================

# Confidence bonuses for different claim types
BONUSES = {
    'location': 10,                # Location claims (located in, flows through)
    'superlative': 5,              # Superlatives (largest, highest)
    'contains_numbers': 5,         # Claims with numbers
    'title_match': 10,             # Term matches page title
    'multiple_sources': 15,        # Found in multiple sources (future)
}

# Penalties for problematic patterns
PENALTIES = {
    'opinion_words': -20,          # Words indicating opinion (I think, maybe)
    'question_mark': -30,          # Questions aren't facts
    'future_tense': -10,           # Future predictions are uncertain
}

# ============================================
# LOGGING AND DEBUGGING
# ============================================

LOGGING = {
    'verbose': False,               # Print detailed output (disable for experiments)
    'log_file': 'nyaya_verifier.log',  # Log file name
    'log_level': 'INFO',            # DEBUG, INFO, WARNING, ERROR
    'show_context': False,          # Show context tracking
    'show_confidence_calc': False,   # Show detailed confidence calculation
}

# ============================================
# HYBRID VERIFICATION (lexical + semantic + Wikidata)
# ============================================

HYBRID = {
    # Final confidence: (1 - semantic_weight) * lexical + semantic_weight * (semantic_cosine * 100)
    "semantic_weight": 0.35,
    "wikidata_support_bonus": 12,
    "wikidata_conflict_penalty": 25,
    # Extra Wikipedia extract beyond summary (chars); larger = slower downloads
    "wikipedia_text_max_chars": 15000,
    "semantic_max_chunks": 48,
    "min_sentence_chars": 12,
}

# ============================================
# PERFORMANCE TUNING
# ============================================

PERFORMANCE = {
    'use_cache': True,              # Cache Wikipedia results
    'max_terms_per_claim': 20,       # Maximum key terms to extract
    'parallel_requests': False,      # Parallel Wikipedia requests (future)
    'request_delay': 0.1,            # Delay between requests (seconds)
}

# ============================================
# VALIDATION
# ============================================

def validate_config():
    """Check if config values are valid"""
    issues = []
    
    if not (0 <= CONFIDENCE_THRESHOLD <= 100):
        issues.append(f"CONFIDENCE_THRESHOLD should be 0-100, got {CONFIDENCE_THRESHOLD}")
    
    if SIMILARITY['high_similarity'] <= SIMILARITY['medium_similarity']:
        issues.append("Similarity thresholds should be in descending order")
    
    if CONTEXT['max_entities'] < 1:
        issues.append("CONTEXT['max_entities'] should be at least 1")
    
    return issues

# ============================================
# TEST THE FILE (if run directly)
# ============================================

if __name__ == "__main__":
    print("🧪 Testing config.py")
    print("=" * 50)
    
    print(f"\n📊 Configuration Summary:")
    print(f"   Confidence Threshold: {CONFIDENCE_THRESHOLD}")
    print(f"   Similarity Thresholds: {SIMILARITY['good_similarity']} (good), {SIMILARITY['partial_match']} (partial)")
    print(f"   Number Tolerance: ±{NUMBER_TOLERANCE['absolute']} or {NUMBER_TOLERANCE['relative']*100}%")
    print(f"   Max Wikipedia Words: {WIKIPEDIA['max_summary_words']}")
    print(f"   Context Entities: {CONTEXT['max_entities']}")
    
    issues = validate_config()
    if issues:
        print(f"\n⚠️ Configuration Issues Found:")
        for issue in issues:
            print(f"   • {issue}")
    else:
        print(f"\n✅ All configuration values are valid!")
    
    print(f"\n📝 Sample Bonuses:")
    for bonus_type, value in BONUSES.items():
        print(f"   {bonus_type}: +{value}%")
    
    print(f"\n✅ Config file loaded successfully!")