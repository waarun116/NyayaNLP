"""
NYAYA PHILOSOPHY PRINCIPLES
Only the sutras relevant to our hallucination detection system
"""
from enum import Enum


class ConfidenceLevel(str, Enum):
    HIGH = "high_confidence"      # >=80 certainty
    MEDIUM = "medium_confidence"  # 40-79 uncertainty/doubt
    LOW = "low_confidence"        # <40 likely error


class EvidenceType(str, Enum):
    DIRECT = "Direct Evidence"
    INFERRED = "Inferred Evidence"
    TESTIMONIAL = "Testimonial Evidence"
    CONFLICTING = "Conflicting Evidence"

# ============================================
# THE FOUR RELEVANT NYAYA SUTRAS
# ============================================

NYAYA_PRINCIPLES = {
    'pratyaksha': {
        'name': 'Pratyaksha',
        'english': 'Direct Perception',
        'description': 'Knowledge gained through direct evidence',
        'explanation': 'The claim matches exactly with verified sources.',
        'xai_focus': 'Direct source match, high lexical + semantic agreement',
        'icon': '👁️',
        'color': '#4CAF50',  # Green
        'threshold': 90,      # ≥90% confidence
    },
    
    'anumana': {
        'name': 'Anumana',
        'english': 'Inference',
        'description': 'Knowledge through logical reasoning',
        'explanation': 'The claim can be inferred from available evidence.',
        'xai_focus': 'Cross-source inference, indirect but coherent support',
        'icon': '🤔',
        'color': '#2196F3',  # Blue
        'threshold': 60,      # 60-89% confidence
    },
    
    'shabda': {
        'name': 'Shabda',
        'english': 'Testimony',
        'description': 'Knowledge from reliable sources',
        'explanation': 'The claim is supported by authoritative sources.',
        'xai_focus': 'Source testimony exists but direct grounding is partial',
        'icon': '📚',
        'color': '#FF9800',  # Orange
        'threshold': 40,      # 40-59% confidence
    },
    
    'nigrahasthana': {
        'name': 'Nigrahasthana',
        'english': 'Points of Defeat',
        'description': 'Where reasoning fails',
        'explanation': 'The claim cannot be verified or contradicts facts.',
        'xai_focus': 'Evidence gap, contradiction, or unresolved subject/entity',
        'icon': '❌',
        'color': '#F44336',  # Red
        'threshold': 0,       # <40% confidence
    }
}

# ============================================
# NYAYA VERDICT TYPES
# ============================================

NYAYA_VERDICTS = {
    'satya': {
        'name': 'fully_verified',
        'english': 'Truth',
        'description': 'All claims verified',
        'icon': '✅',
        'color': '#4CAF50',
        'explanation': 'All claims verified through Pratyaksha and Shabda.'
    },
    
    'prama': {
        'name': 'mostly_verified',
        'english': 'Valid Knowledge',
        'description': 'Most claims verified',
        'icon': '⚠️',
        'color': '#FF9800',
        'explanation': 'Response contains valid knowledge with some inferred elements.'
    },
    
    'sandigdha': {
        'name': 'partially_verified',
        'english': 'Doubtful',
        'description': 'Some claims verified',
        'icon': '❓',
        'color': '#9C27B0',
        'explanation': 'Response mixes truth with unverified claims.'
    },
    
    'viparyaya': {
        'name': 'not_verified',
        'english': 'Error',
        'description': 'No claims verified',
        'icon': '❌',
        'color': '#F44336',
        'explanation': 'Response contains no verifiable truth - hallucinated.'
    }
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def map_confidence_to_nyaya(confidence):
    """Map confidence to the relevant Nyaya sutra"""
    if confidence >= 90:
        return 'pratyaksha'
    elif confidence >= 60:
        return 'anumana'
    elif confidence >= 40:
        return 'shabda'
    else:
        return 'nigrahasthana'


def map_confidence_level(confidence: float) -> ConfidenceLevel:
    """Nyaya confidence level independent from sutra naming."""
    if confidence >= 80:
        return ConfidenceLevel.HIGH
    if confidence >= 40:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def infer_evidence_type(source_count: int, has_direct: bool, has_conflict: bool) -> EvidenceType:
    """Map source characteristics (not confidence %) to evidence type."""
    if has_conflict:
        return EvidenceType.CONFLICTING
    if has_direct and source_count >= 2:
        return EvidenceType.DIRECT
    if source_count >= 2:
        return EvidenceType.INFERRED
    return EvidenceType.TESTIMONIAL

def get_nyaya_verdict(verified, total):
    """Get overall Nyaya verdict"""
    if verified == total:
        return 'satya'
    elif verified >= total / 2:
        return 'prama'
    elif verified > 0:
        return 'sandigdha'
    else:
        return 'viparyaya'

def get_principle_details(principle_key):
    """Get full details of a Nyaya principle"""
    return NYAYA_PRINCIPLES.get(principle_key, {})

def get_verdict_details(verdict_key):
    """Get full details of a Nyaya verdict"""
    return NYAYA_VERDICTS.get(verdict_key, {})

# ============================================
# TEST THE FILE
# ============================================

if __name__ == "__main__":
    print("🧪 Testing Simplified Nyaya Principles")
    print("=" * 50)
    
    print("\n📜 THE FOUR RELEVANT SUTRAS:")
    for key, p in NYAYA_PRINCIPLES.items():
        print(f"\n  {p['icon']} {p['name']}")
        print(f"     {p['description']}")
        print(f"     Applies to: ≥{p['threshold']}% confidence")
    
    print("\n⚖️  VERDICTS:")
    for key, v in NYAYA_VERDICTS.items():
        print(f"  {v['icon']} {v['name']} - {v['description']}")
    
    print("\n🔄 TEST MAPPING:")
    test_confidences = [100, 95, 85, 75, 55, 45, 35, 25, 15, 5]
    for conf in test_confidences:
        principle = map_confidence_to_nyaya(conf)
        p = NYAYA_PRINCIPLES[principle]
        print(f"   {conf:3}% → {p['icon']} {p['name']}")
    
    print("\n⚖️  TEST VERDICTS:")
    test_cases = [(5,5), (4,5), (2,5), (0,5)]
    for v, t in test_cases:
        verdict = get_nyaya_verdict(v, t)
        vd = NYAYA_VERDICTS[verdict]
        print(f"   {v}/{t} verified → {vd['icon']} {vd['name']}")
    
    print(f"\n✅ Simplified Nyaya principles file ready!")
    print(f"   Sutras: {len(NYAYA_PRINCIPLES)}")
    print(f"   Verdicts: {len(NYAYA_VERDICTS)}")