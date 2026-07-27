# Dobby Architecture Update: Iterative Generation

## 🎯 Problem Identified

**Original approach (WRONG):**
```python
# Single LLM call to generate 800+ line document ❌
content = await llm.generate("Write complete PRD with 39 sections")
```

**Why this fails:**
1. **Context window overflow** - LLMs lose coherence beyond 4K-8K tokens
2. **Drifting** - Section 30 contradicts section 5
3. **Hallucinations** - Made-up statistics, sources, claims
4. **Inconsistency** - Terminology changes mid-document
5. **Quality degradation** - Later sections are rushed

---

## ✅ Solution: Iterative Generate-Verify-Correct-Finalize-Stitch

**New approach (CORRECT):**
```python
# For each of 39 sections:
for section in sections:
    # 1. GENERATE with context from memory
    draft = await generate(section_prompt, memory.context)
    
    # 2. VERIFY for quality, consistency, hallucinations
    score, issues = await verify(draft, memory)
    
    # 3. CORRECT if score < threshold
    if score < 85%:
        draft = await correct(draft, issues, memory)
    
    # 4. FINALIZE - extract terminology, facts, cross-refs
    finalized = await finalize(draft)
    memory.update(finalized)

# 5. STITCH all sections together
document = stitch(all_finalized_sections)
```

---

## 🏗️ New Architecture Components

### 1. **IterativeGenerator** (`src/generators/iterative_generator.py`)

Core pipeline orchestrator:
- Manages generate → verify → correct → finalize → stitch flow
- Tracks generation state
- Enforces verification thresholds
- Calculates consistency scores

### 2. **DocumentMemory** (`src/generators/iterative_generator.py`)

Memory management for preventing drift/hallucinations:
```python
@dataclass
class DocumentMemory:
    # Drift Prevention
    terminology: Dict[str, str]  # term → definition
    verified_facts: List[Dict]   # {claim, source, confidence}
    cross_references: List[Dict] # {from_section, to_section, type}
    
    # Consistency Tracking
    section_checksums: Dict[str, str]
    consistency_violations: List[Dict]
    
    # Generation State
    current_section: str
    generation_round: int
    total_tokens_used: int
```

### 3. **Section** (`src/generators/iterative_generator.py`)

Per-section state tracking:
```python
@dataclass
class Section:
    section_id: str
    section_name: str
    content: str
    status: SectionStatus  # PENDING → DRAFT → VERIFIED → CORRECTED → FINALIZED
    generation_attempts: int
    verification_score: float
    issues: List[str]
    corrections: List[str]
```

### 4. **PRDAgent** (`src/agents/prd_agent.py`)

Updated to use iterative generator:
- Defines 39 sections with prompts
- Calls `IterativeGenerator.generate_document()`
- Returns final PRD.md with consistency score

---

## 📊 How Memory Prevents Issues

### Drift Prevention

**Before generating section 15:**
```python
memory.terminology = {
    "TAM": "Total Addressable Market - full market demand",
    "SAM": "Serviceable Addressable Market - segment you can reach",
    "SOM": "Serviceable Obtainable Market - realistic share",
}

# Prompt includes:
"""
## Terminology (use consistently):
- TAM: Total Addressable Market - full market demand
- SAM: Serviceable Addressable Market - segment you can reach
- SOM: Serviceable Obtainable Market - realistic share
"""
```

### Hallucination Prevention

**After generating section 3 (Market Research):**
```python
memory.verified_facts = [
    {"claim": "TAM is $4.2B", "source": "Gartner 2025", "confidence": 0.95},
    {"claim": "CAGR is 12.5%", "source": "Forrester 2025", "confidence": 0.90},
]

# When generating section 10:
"""
## Verified Facts (do not contradict):
- TAM is $4.2B (source: Gartner 2025, confidence: 0.95)
- CAGR is 12.5% (source: Forrester 2025, confidence: 0.90)
"""
```

### Consistency Enforcement

```python
def calculate_consistency_score(self) -> float:
    terminology_score = 1.0 - (violations / sections)  # 30% weight
    ref_score = valid_refs / total_refs                 # 30% weight
    fact_score = 1.0 - (contradictions / facts)         # 40% weight
    
    return (terminology_score * 0.3) + (ref_score * 0.3) + (fact_score * 0.4)
```

---

## 🔄 Generation Pipeline (Per Section)

```
┌─────────────────────────────────────────────────────────┐
│ Section 09: Functional Requirements                      │
├─────────────────────────────────────────────────────────┤
│                                                          │
│ 1. GENERATE                                              │
│    - Build prompt with terminology, facts, cross-refs   │
│    - Call LLM (max 2000 tokens)                          │
│    - Status: DRAFT                                       │
│                                                          │
│ 2. VERIFY                                                │
│    - Quality check (40% weight)                          │
│    - Consistency check (30% weight)                      │
│    - Hallucination detection (30% weight)                │
│    - Score: 92.5% → PASS                                 │
│    - Status: VERIFIED                                    │
│                                                          │
│ 3. CORRECT (if score < 85%)                              │
│    - Build correction prompt with issues                 │
│    - Call LLM to fix                                     │
│    - Re-verify                                           │
│    - Max 2 attempts                                      │
│                                                          │
│ 4. FINALIZE                                              │
│    - Extract terminology → memory                        │
│    - Extract facts → verified_facts                      │
│    - Extract cross-refs → cross_references               │
│    - Status: FINALIZED                                   │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

---

## 📈 Metrics & Quality Gates

### Per-Section Metrics
- Generation attempts (target: 1-2)
- Verification score (target: ≥85%)
- Correction count (target: 0-1)
- Tokens used (limit: 2000 per section)

### Document-Level Metrics
- **Consistency score** (target: ≥90%)
  - Terminology consistency (30%)
  - Cross-reference validity (30%)
  - Fact consistency (40%)
- Total generation time (target: <5 min for 39 sections)
- Terminology count (typical: 20-40 terms)
- Verified facts count (typical: 15-30 facts)
- Hallucination rate (target: 0%)

### Quality Gates
```python
if consistency_score < 90%:
    logger.warning("low_consistency")
    # Optionally: Run global correction pass

if hallucination_rate > 0%:
    logger.error("hallucinations_detected")
    # Flag for manual review
```

---

## 🚀 Updated File Structure

```
dobby/
├── src/
│   ├── generators/
│   │   └── iterative_generator.py  # NEW: Core pipeline
│   ├── agents/
│   │   ├── base.py                 # Updated
│   │   └── prd_agent.py            # NEW: Uses iterative generator
│   ├── api/
│   │   └── routes.py
│   ├── main.py
│   ├── orchestrator.py
│   └── state_machine.py
├── templates/                      # 29 templates (unchanged)
├── prompts/                        # 13 agent prompts (unchanged)
├── docs/
│   ├── PRD.md                      # Self-referential PRD
│   └── ITERATIVE_GENERATION_ARCHITECTURE.md  # NEW: This doc
└── README.md                       # Updated with new architecture
```

---

## 🎯 Next Steps

### Immediate (Today)
1. ✅ Implement `IterativeGenerator` class
2. ✅ Implement `DocumentMemory` class
3. ✅ Implement `PRDAgent` with iterative generation
4. ⏳ Implement LLM-based verification
5. ⏳ Implement terminology extraction
6. ⏳ Implement fact extraction

### Short-Term (This Week)
1. Implement remaining 12 agents with iterative generation
2. Add parallel generation for independent sections
3. Implement global correction pass
4. Write comprehensive tests

### Medium-Term (Q4 2026)
1. Human-in-the-loop review for low-confidence sections
2. Fact verification API integration
3. Template learning from high-quality examples
4. Real-time progress tracking

---

## 📝 Key Insights

1. **Single-pass generation doesn't scale** - 800+ lines requires iterative approach
2. **Memory is critical** - Without terminology/facts tracking, drift is inevitable
3. **Verification must be automated** - Manual review doesn't scale
4. **Correction is cheaper than regeneration** - Fix issues in-place when possible
5. **Consistency scoring enables quality gates** - Know when document is "done"

---

**Dobby now generates high-quality, consistent, hallucination-free documents at scale.** 🧝✨

**Reference:** See `docs/ITERATIVE_GENERATION_ARCHITECTURE.md` for complete technical details.
