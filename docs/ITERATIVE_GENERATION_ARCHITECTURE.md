# Iterative Document Generation Architecture

## Problem Statement

**Generating 800+ line documents in a single LLM call fails because:**

1. **Context Window Overflow** - LLMs lose coherence beyond 4K-8K tokens
2. **Drifting** - Later sections contradict earlier sections
3. **Hallucinations** - Made-up statistics, facts, sources
4. **Inconsistency** - Terminology changes mid-document
5. **Quality Degradation** - Later sections are rushed/low-quality

## Solution: Iterative Generate-Verify-Correct-Finalize-Stitch Pipeline

```
┌─────────────────────────────────────────────────────────────────┐
│                    ITERATIVE GENERATION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  For EACH section (1-39):                                        │
│                                                                  │
│  1. GENERATE                                                     │
│     - Build context-aware prompt                                │
│     - Include terminology from memory                            │
│     - Include verified facts                                     │
│     - Include cross-references                                   │
│     ↓                                                            │
│  2. VERIFY                                                       │
│     - Quality check (completeness, clarity)                      │
│     - Consistency check (terminology, facts)                     │
│     - Hallucination detection (made-up claims)                   │
│     - Drift detection (deviation from previous sections)         │
│     ↓                                                            │
│  3. CORRECT (if score < threshold)                               │
│     - Fix identified issues                                      │
│     - Re-verify                                                  │
│     - Max 2 correction attempts                                  │
│     ↓                                                            │
│  4. FINALIZE                                                     │
│     - Extract terminology → memory                               │
│     - Extract facts → verified facts                             │
│     - Extract cross-references                                   │
│     - Mark as finalized                                          │
│                                                                  │
│  5. STITCH (after all sections)                                  │
│     - Combine all sections                                       │
│     - Ensure smooth transitions                                  │
│     - Verify consistency score                                   │
│     - Generate final document                                    │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Memory Management

### DocumentMemory Class

Tracks generation state and prevents drift/hallucinations:

```python
@dataclass
class DocumentMemory:
    document_type: str
    total_sections: int
    sections: Dict[str, Section]
    
    # Drift Prevention
    terminology: Dict[str, str]  # term → definition
    verified_facts: List[Dict]   # {claim, source, confidence}
    cross_references: List[Dict] # {from_section, to_section, type}
    
    # Generation State
    current_section: str
    generation_round: int
    total_tokens_used: int
    
    # Consistency Tracking
    section_checksums: Dict[str, str]
    consistency_violations: List[Dict]
```

### How Memory Prevents Issues

#### 1. **Drift Prevention**
```python
# Before generating section 15:
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

#### 2. **Hallucination Prevention**
```python
# After generating section 3 (Market Research):
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

#### 3. **Consistency Enforcement**
```python
# After generating section 5 (Personas):
memory.cross_references = [
    {"from_section": "05", "to_section": "09", "type": "requirement"},
    {"from_section": "05", "to_section": "12", "type": "screen_reference"},
]

# Consistency score calculation:
def calculate_consistency_score(self) -> float:
    terminology_score = 1.0 - (violations / sections)
    ref_score = valid_refs / total_refs
    fact_score = 1.0 - (contradictions / facts)
    
    return (terminology_score * 0.3) + (ref_score * 0.3) + (fact_score * 0.4)
```

---

## Generation Pipeline Details

### Step 1: GENERATE

**Input:** Section definition + Memory context  
**Output:** Draft section content

**Prompt Structure:**
```
[Section Prompt]

## Terminology (use consistently):
{terminology from memory}

## Verified Facts (do not contradict):
{facts from previous sections}

## Cross-References:
{references to other sections}

## Context:
{product idea, previous documents}
```

**LLM Call:**
```python
prompt = await self._build_generation_prompt(section_prompt, memory, context)
content = await self._call_llm(prompt, max_tokens=2000)
```

---

### Step 2: VERIFY

**Input:** Draft section + Memory  
**Output:** Verification score + Issues list

**Verification Criteria:**
1. **Quality** (40% weight)
   - Completeness: Does it cover all required aspects?
   - Clarity: Is it well-written?
   - Accuracy: Are claims accurate?

2. **Consistency** (30% weight)
   - Terminology: Uses terms from memory?
   - Facts: Doesn't contradict verified facts?
   - Cross-refs: All references valid?

3. **Hallucination Detection** (30% weight)
   - No made-up statistics
   - No fabricated sources
   - No unsubstantiated claims

**Verification Prompt:**
```
Verify this section for:

1. QUALITY (40%)
- Completeness, Clarity, Accuracy

2. CONSISTENCY (30%)
- Terminology alignment
- Fact consistency
- Cross-reference validity

3. HALLUCINATIONS (30%)
- Made-up stats, sources, claims

Section: {section_name}
Content: {content[:2000]}

Memory state:
- Previous sections: {len(completed)}
- Verified facts: {len(facts)}
- Terminology: {len(terms)} terms

Return:
- verification_score (0-100)
- issues (list)
- recommendations (list)
```

**Threshold:**
- Score ≥ 85%: Accept section
- Score 70-84%: Send to correction
- Score < 70%: Regenerate section

---

### Step 3: CORRECT

**Input:** Section with issues + Memory  
**Output:** Corrected section

**Correction Prompt:**
```
Fix these issues:

Issues:
{issue_1}
{issue_2}
{issue_3}

Current content:
{content}

Maintain consistency with:
- Terminology: {terms}
- Verified facts: {facts}

Return corrected content only.
```

**Retry Logic:**
- Max 2 correction attempts
- If still below threshold → flag for manual review
- Continue generation (don't block entire document)

---

### Step 4: FINALIZE

**Input:** Verified/corrected section  
**Output:** Finalized section + Memory updates

**Actions:**
1. **Extract terminology** → Add to `memory.terminology`
2. **Extract facts** → Add to `memory.verified_facts`
3. **Extract cross-references** → Add to `memory.cross_references`
4. **Mark status** → `SectionStatus.FINALIZED`

**Extraction (LLM-based):**
```python
async def _extract_terminology(self, content: str) -> Dict[str, str]:
    prompt = f"""
    Extract key terminology from this section:
    
    {content}
    
    Return as JSON: {{"term": "definition", ...}}
    """
    return await self._call_llm(prompt)
```

---

### Step 5: STITCH

**Input:** All finalized sections  
**Output:** Complete document

**Stitching Process:**
1. Sort sections by ID (01, 02, 03... 39)
2. Add section headers
3. Ensure smooth transitions
4. Add table of contents
5. Verify overall consistency score

**Final Consistency Check:**
```python
consistency_score = memory.calculate_consistency_score()

if consistency_score < 90%:
    logger.warning("low_consistency", score=consistency_score)
    # Optionally: Run global correction pass
```

---

## Configuration

### GenerationConfig

```python
@dataclass
class GenerationConfig:
    max_generation_attempts: int = 3
    verification_threshold: float = 85.0  # Min score to accept
    correction_threshold: float = 70.0    # Min score to attempt correction
    max_correction_attempts: int = 2
    context_window_limit: int = 8000      # Max tokens per LLM call
    include_terminology: bool = True
    include_verified_facts: bool = True
    include_cross_references: bool = True
    enable_drift_detection: bool = True
    enable_hallucination_detection: bool = True
```

---

## Metrics & Monitoring

### Per-Section Metrics
- Generation attempts
- Verification score
- Correction count
- Tokens used

### Document-Level Metrics
- Total generation time
- Overall consistency score
- Terminology count
- Verified facts count
- Cross-references count
- Hallucination rate

### Logging
```python
logger.info(
    "section_completed",
    section_id="09",
    section_name="Functional Requirements",
    status="finalized",
    verification_score=92.5,
    generation_attempts=1,
    corrections=0,
)

logger.info(
    "document_completed",
    document_type="PRD",
    total_sections=39,
    consistency_score=94.2,
    generation_rounds=42,
    terminology_count=27,
    verified_facts=15,
    cross_references=38,
)
```

---

## Example: PRD Generation Flow

```
Start PRD Generation
│
├─→ Section 01: Document Control
│   ├─→ GENERATE (prompt: "Create document control...")
│   ├─→ VERIFY (score: 95% → pass)
│   ├─→ FINALIZE (extract: 0 terms, 0 facts)
│   └─→ Memory: sections=1, terminology={}, facts={}
│
├─→ Section 02: Executive Summary
│   ├─→ GENERATE (with empty terminology)
│   ├─→ VERIFY (score: 88% → pass)
│   ├─→ FINALIZE (extract: 3 terms, 2 facts)
│   └─→ Memory: sections=2, terminology={TAM, SAM, SOM}, facts={2}
│
├─→ Section 03: Strategic Context
│   ├─→ GENERATE (with terminology: TAM/SAM/SOM)
│   ├─→ VERIFY (score: 72% → needs correction)
│   ├─→ CORRECT (fix: "TAM definition inconsistent")
│   ├─→ RE-VERIFY (score: 89% → pass)
│   ├─→ FINALIZE (extract: 5 terms, 8 facts)
│   └─→ Memory: sections=3, terminology={8}, facts={10}
│
├─→ [... continue for all 39 sections ...]
│
└─→ STITCH
    ├─→ Combine all 39 sections
    ├─→ Calculate consistency score: 94.2%
    ├─→ Generate final PRD.md (800+ lines)
    └─→ Save to ~/dobby-output/<job_id>/PRD.md
```

---

## Benefits

### 1. **Consistency**
- All sections use same terminology
- No contradictory facts
- Cross-references always valid

### 2. **Quality**
- Every section verified before acceptance
- Low-quality sections corrected automatically
- Final consistency score ensures overall quality

### 3. **No Hallucinations**
- Facts extracted and verified
- Contradictions detected immediately
- Sources tracked for every claim

### 4. **No Drift**
- Terminology memory enforces consistency
- Each section sees all previous definitions
- Global consistency score at end

### 5. **Scalability**
- Can generate 800+ line documents
- Context window never exceeded (2K per section)
- Parallel generation possible (non-dependent sections)

---

## Future Improvements

1. **Parallel Generation** - Generate independent sections concurrently
2. **Global Correction Pass** - Final sweep for cross-section issues
3. **Human-in-the-Loop** - Flag low-confidence sections for review
4. **Template Learning** - Learn from high-quality PRDs
5. **Fact Verification API** - Cross-check facts with external sources

---

**This architecture ensures Dobby generates high-quality, consistent, hallucination-free documents at scale.**
