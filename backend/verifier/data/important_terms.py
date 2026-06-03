"""
IMPORTANT TERMS - Words that indicate factual claims
These terms help identify sentences that contain verifiable information
"""
import re  # Added for text cleaning

# ============================================
# CORE IMPORTANT TERMS
# ============================================

IMPORTANT_TERMS = {
    # ===== GEOGRAPHY =====
    # Locations
    'capital', 'city', 'country', 'nation', 'state', 'province', 'region',
    'continent', 'island', 'peninsula', 'archipelago','pm', 'p.m.', 'cm', 'c.m.', 'dpm', 'deputy pm',
    
    # Water bodies
    'river', 'ocean', 'sea', 'lake', 'bay', 'gulf', 'strait', 'channel',
    'waterfall', 'glacier', 'reef', 'coral',
    
    # Landforms
    'mountain', 'hill', 'valley', 'desert', 'forest', 'jungle', 'plain',
    'plateau', 'canyon', 'cliff', 'volcano', 'cave',
    
    # Boundaries
    'border', 'boundary', 'coast', 'shore', 'beach',
    
    # ===== MEASUREMENTS =====
    # Dimensions
    'diameter', 'radius', 'circumference', 'perimeter', 'length', 'width',
    'height', 'depth', 'thickness', 'breadth', 'altitude',
    
    # Area & Volume
    'area', 'volume', 'capacity', 'size', 'magnitude', 'extent',
    
    # Mass & Weight
    'mass', 'weight', 'density', 'gravity',
    
    # Speed & Time
    'speed', 'velocity', 'acceleration', 'rate', 'frequency',
    'duration', 'period', 'interval', 'age', 'lifespan',
    
    # Temperature
    'temperature', 'heat', 'cold', 'freezing', 'boiling', 'melting',
    'boils', 'melts', 'freezes', 'evaporates', 'condenses', 'sublimates',
    'celsius', 'fahrenheit', 'kelvin', 'degrees',
    
    # Pressure
    'pressure', 'force', 'energy', 'power', 'intensity',
    
    # ===== POPULATION & DEMOGRAPHICS =====
    'population', 'people', 'inhabitant', 'resident', 'citizen',
    'density', 'census', 'demographics', 'birth', 'death', 'mortality',
    
    # ===== TIME & HISTORY =====
    # Events
    'born', 'died', 'birth', 'death', 'created', 'founded', 'established',
    'began', 'started', 'ended', 'finished', 'completed', 'occurred',
    'happened', 'took place', 'event', 'incident',
    
    # Eras
    'century', 'decade', 'year', 'month', 'day', 'era', 'period',
    'age', 'epoch', 'millennium',
    
    # ===== CREATION & DISCOVERY =====
    'invented', 'discovered', 'created', 'developed', 'designed',
    'built', 'constructed', 'made', 'produced', 'manufactured',
    'founded', 'established', 'originated', 'formed',
    
    # ===== ARTS & CULTURE =====
    'wrote', 'composed', 'painted', 'drew', 'sculpted', 'authored',
    'published', 'released', 'performed', 'premiered', 'exhibited',
    
    # ===== SCIENCE =====
    # Physics
    'gravity', 'relativity', 'quantum', 'particle', 'atom', 'molecule',
    'electron', 'proton', 'neutron', 'photon', 'energy', 'mass', 
    'boiling point', 'melting point', 'freezing point', 'absolute zero',
    
    # Chemistry
    'chemical', 'element', 'compound', 'reaction', 'acid', 'base',
    'ph', 'bond', 'molecule', 'atom',
    
    # Biology
    'cell', 'dna', 'rna', 'protein', 'gene', 'chromosome', 'organism',
    'species', 'genus', 'family', 'order', 'class', 'phylum', 'kingdom',
    'evolution', 'natural selection', 'mutation',
    
    # Astronomy
    'planet', 'star', 'moon', 'galaxy', 'universe', 'solar system',
    'orbit', 'asteroid', 'comet', 'meteor', 'eclipse', 'constellation',
    
    # Medicine
    'disease', 'illness', 'condition', 'syndrome', 'virus', 'bacteria',
    'infection', 'treatment', 'cure', 'vaccine', 'medicine', 'drug',
    'antibiotic', 'penicillin', 'insulin',
    
    # ===== SUPERLATIVES =====
    # Size
    'largest', 'smallest', 'biggest', 'tiniest', 'greatest', 'least',
    'massive', 'tiny', 'enormous', 'minuscule',
    
    # Age
    'oldest', 'newest', 'youngest', 'earliest', 'latest', 'most recent',
    'ancient', 'modern', 'contemporary',
    
    # Height/Depth
    'highest', 'lowest', 'tallest', 'shortest', 'deepest', 'shallowest',
    
    # Length
    'longest', 'shortest', 'widest', 'narrowest', 'broadest',
    
    # Speed
    'fastest', 'slowest', 'quickest', 'swiftest',
    
    # Temperature
    'hottest', 'coldest', 'warmest', 'coolest',
    
    # Population
    'most populous', 'least populous', 'densest', 'sparsest',
    
    # ===== FIRST/LAST =====
    'first', 'last', 'initial', 'final', 'original', 'ultimate',
    
    # ===== RANKINGS =====
    'rank', 'ranked', 'position', 'place', 'order', 'sequence',
    
    # ===== COMPOSITION =====
    'consists', 'comprises', 'contains', 'includes', 'composed',
    'made of', 'formed from', 'built from',
    
    # ===== LOCATION =====
    'located', 'situated', 'found', 'lies', 'stands', 'sits',
    'flows', 'runs', 'passes', 'crosses', 'enters', 'exits',
    
    # ===== ORBIT & MOTION =====
    'orbits', 'rotates', 'revolves', 'circles', 'travels', 'moves',
    'spins', 'turns', 'circulates',
    
    # ===== ATMOSPHERE & ENVIRONMENT =====
    'atmosphere', 'climate', 'weather', 'temperature', 'pressure',
    'wind', 'rain', 'snow', 'storm', 'hurricane', 'tornado',
    
    # ===== WAR & CONFLICT =====
    'war', 'battle', 'conflict', 'revolution', 'rebellion', 'uprising',
    'invasion', 'attack', 'defense', 'victory', 'defeat',
    
    # ===== GOVERNMENT & POLITICS =====
    'government', 'president', 'prime minister', 'deputy prime minister', 'king', 'queen',
    'emperor', 'ruler', 'leader', 'election', 'vote', 'policy',
    'law', 'act', 'treaty', 'agreement', 'alliance',
    
    # ===== ECONOMY =====
    'economy', 'gdp', 'income', 'wealth', 'poverty', 'unemployment',
    'inflation', 'currency', 'money', 'trade', 'export', 'import',
    
    # ===== TECHNOLOGY =====
    'invention', 'technology', 'device', 'machine', 'engine',
    'computer', 'internet', 'software', 'hardware', 'network',
    
    # ===== MATHEMATICS =====
    'pi', 'euler', 'pythagoras', 'calculus', 'algebra', 'geometry',
    'equation', 'formula', 'theorem', 'proof', 'calculation',
}

# ============================================
# CATEGORIZED TERMS (for reference)
# ============================================

CATEGORIES = {
    'geography': ['capital', 'city', 'country', 'river', 'mountain', 'ocean'],
    'measurements': ['diameter', 'area', 'volume', 'mass', 'weight', 'speed'],
    'time': ['born', 'died', 'created', 'founded', 'established'],
    'creation': ['invented', 'discovered', 'developed', 'designed', 'built'],
    'arts': ['wrote', 'composed', 'painted', 'authored', 'performed'],
    'science': ['dna', 'cell', 'atom', 'molecule', 'gravity', 'quantum'],
    'superlatives': ['largest', 'smallest', 'oldest', 'newest', 'highest'],
    'location': ['located', 'situated', 'found', 'flows', 'orbits'],
}

# ============================================
# IMPROVED HELPER FUNCTIONS
# ============================================

def is_important_term(word):
    """Check if a word is an important factual term"""
    return word.lower() in IMPORTANT_TERMS

def contains_important_term(text):
    """Check if text contains any important term (improved)"""
    text_lower = text.lower()
    words = [re.sub(r'[^\w\s]', '', w) for w in text_lower.split()]
    
    # Check each word in the text
    for word in words:
        # Clean the word of punctuation
        clean_word = re.sub(r'[^\w\s]', '', word)
        if clean_word and clean_word in IMPORTANT_TERMS:
            return True
    
    # Also check for multi-word phrases
    for i in range(len(words) - 1):
        phrase = ' '.join(words[i:i+2])
        if phrase in IMPORTANT_TERMS:
            return True
    for i in range(len(words) - 2):
        phrase3 = ' '.join(words[i:i+3])
        if phrase3 in IMPORTANT_TERMS:
            return True
    
    return False

def get_important_terms(text):
    """Extract all important terms from text (improved)"""
    text_lower = text.lower()
    words = text_lower.split()
    found = []
    
    # Check individual words
    for word in words:
        clean_word = re.sub(r'[^\w\s]', '', word)
        if clean_word.endswith("ies") and len(clean_word) > 4:
            alt = clean_word[:-3] + "y"
        elif clean_word.endswith("es") and len(clean_word) > 4:
            alt = clean_word[:-2]
        elif clean_word.endswith("s") and len(clean_word) > 3:
            alt = clean_word[:-1]
        else:
            alt = clean_word
        if clean_word and clean_word in IMPORTANT_TERMS:
            if clean_word not in found:
                found.append(clean_word)
        elif alt and alt in IMPORTANT_TERMS and alt not in found:
            found.append(alt)
    
    # Check for multi-word phrases
    for i in range(len(words) - 1):
        phrase = ' '.join(words[i:i+2])
        if phrase in IMPORTANT_TERMS and phrase not in found:
            found.append(phrase)
    for i in range(len(words) - 2):
        phrase3 = ' '.join(words[i:i+3])
        if phrase3 in IMPORTANT_TERMS and phrase3 not in found:
            found.append(phrase3)
    
    return found

def get_category(term):
    """Get the category of an important term"""
    term_lower = term.lower()
    for category, terms in CATEGORIES.items():
        if term_lower in terms:
            return category
    return 'other'

# ============================================
# POLITICAL TERM NORMALIZATION
# ============================================

POLITICAL_TERM_MAP = {
    # Head of State variations
    'president': 'head_of_state',
    'head of state': 'head_of_state',
    'monarch': 'head_of_state',
    'king': 'head_of_state',
    'queen': 'head_of_state',
    'emperor': 'head_of_state',
    
    # Head of Government variations
    'prime minister': 'head_of_government',
    'pm': 'head_of_government',
    'p.m.': 'head_of_government',
    'head of government': 'head_of_government',
    'chancellor': 'head_of_government',
    'premier': 'head_of_government',
    
    # Deputy Prime Minister variations
    'deputy prime minister': 'deputy_prime_minister',
    'deputy pm': 'deputy_prime_minister',
    'dpm': 'deputy_prime_minister',
    'vice prime minister': 'deputy_prime_minister',
    
    # Regional/State leaders
    'chief minister': 'chief_minister',
    'cm': 'chief_minister',
    'c.m.': 'chief_minister',
    'governor': 'governor',
    
    # Other leaders
    'leader': 'leader',
    'ruler': 'leader',
    
}

def normalize_political_term(term: str) -> str:
    """Normalize political term variations to canonical form"""
    term_lower = (term or "").lower().strip()
    term_clean = re.sub(r'[^\w\s]', '', term_lower)
    return POLITICAL_TERM_MAP.get(term_clean, term_clean)

# ============================================
# TEST THE FILE (if run directly)
# ============================================

if __name__ == "__main__":
    print("🧪 Testing important_terms.py")
    print("=" * 50)
    
    print(f"\n📊 Statistics:")
    print(f"   Total important terms: {len(IMPORTANT_TERMS)}")
    print(f"   Categories: {len(CATEGORIES)}")
    
    print("\n📋 Sample terms by category:")
    for category, terms in CATEGORIES.items():
        sample = [t for t in terms if t in IMPORTANT_TERMS][:3]
        print(f"   {category}: {', '.join(sample)}...")
    
    # Verify that 'boils' is in IMPORTANT_TERMS
    print("\n🔍 Verification:")
    test_terms = ['boils', 'melts', 'freezes', 'evaporates', 'condenses']
    for term in test_terms:
        print(f"   '{term}' in IMPORTANT_TERMS: {term in IMPORTANT_TERMS}")
    
    test_sentences = [
        "The capital of France is Paris",
        "Water boils at 100 degrees Celsius",
        "Einstein developed relativity",
        "The population of Japan is 125 million",
        "Mount Everest is the highest mountain",
        "The Amazon River flows through South America",
    ]
    
    print("\n📝 Testing sentences:")
    for sent in test_sentences:
        print(f"\n   Original: {sent}")
        contains = contains_important_term(sent)
        print(f"   Contains important terms: {contains}")
        if contains:
            terms = get_important_terms(sent)
            print(f"   Found terms: {terms}")
    
    print(f"\n✅ Important terms file loaded successfully!")
    print(f"   Total terms: {len(IMPORTANT_TERMS)}")