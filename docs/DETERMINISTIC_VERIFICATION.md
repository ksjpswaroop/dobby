# Deterministic Verification Architecture

## 🎯 Problem: LLM-Based Verification Hallucinates

**Original approach (WRONG):**
```python
# LLM verifies content → can hallucinate too ❌
verification = await llm.verify("Check this section for quality")
# LLM might say "95% quality" even if content is wrong
```

**Why this fails:**
1. **LLM hallucinates verification scores** - Makes up numbers
2. **Inconsistent criteria** - Different standards each time
3. **Cannot reproduce** - Same content gets different scores
4. **False positives** - Says "passed" when issues exist
5. **False negatives** - Flags correct content as wrong

---

## ✅ Solution: Fully Deterministic Verification

**New approach (CORRECT):**
```python
# Deterministic checks - NO LLM calls ✓
result = await deterministic_verifier.verify_section(
    section_id="09",
    section_name="Functional Requirements",
    content=content,
    context=context,
)

# Result is reproducible, auditable, explainable
assert result.overall_score == 87.5  # Same score every time
assert result.issues[0].description == "Required header missing"  # Exact issue
```

**All checks are:**
- ✅ **Rule-based** - Explicit conditions
- ✅ **Pattern matching** - Regex, string matching
- ✅ **Algorithm-driven** - Calculated scores
- ✅ **Externally verified** - APIs for fact-checking
- ✅ **100% reproducible** - Same input = same output

---

## 🏗️ Verification System Architecture

### 7 Deterministic Check Types

```
┌─────────────────────────────────────────────────────────────┐
│              DETERMINISTIC VERIFICATION                      │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. STRUCTURE CHECK                                          │
│     - Required headers present                               │
│     - Section hierarchy correct                              │
│     - No missing subsections                                 │
│                                                              │
│  2. FORMAT CHECK                                             │
│     - Valid markdown syntax                                  │
│     - Code blocks have language tags                         │
│     - Links are complete                                     │
│     - Lists properly formatted                               │
│                                                              │
│  3. CONSISTENCY CHECK                                        │
│     - Terminology used consistently                          │
│     - Acronyms defined on first use                          │
│     - No contradictory definitions                           │
│                                                              │
│  4. CROSS-REFERENCE CHECK                                    │
│     - Section references point to existing sections          │
│     - Figure/table references exist                          │
│     - No circular references                                 │
│                                                              │
│  5. COMPLETENESS CHECK                                       │
│     - Minimum word count met                                 │
│     - No placeholder text ([TODO], {{var}})                  │
│     - Required keywords present                              │
│                                                              │
│  6. STATISTICAL CHECK                                        │
│     - Percentages in valid range (0-100%)                    │
│     - Dates in ISO 8601 format                               │
│     - Numbers consistent (totals = sum of parts)             │
│                                                              │
│  7. QUALITY CHECK                                            │
│     - Readability score (Flesch-Kincaid)                     │
│     - Sentence length variance                               │
│     - Passive voice detection                                │
│     - Repetition detection                                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 Verification Scoring (Deterministic)

### Scoring Algorithm

```python
def _calculate_score(issues, metrics):
    base_score = 100.0
    
    # Deduct points for each issue
    critical_count = sum(1 for i in issues if i.severity == "critical")
    warning_count = sum(1 for i in issues if i.severity == "warning")
    info_count = sum(1 for i in issues if i.severity == "info")
    
    # Deterministic deduction
    score = base_score - (critical_count * 20) - (warning_count * 10) - (info_count * 2)
    
    return max(0.0, min(100.0, score))
```

### Issue Severity Levels

| Severity | Points Deducted | Examples |
|----------|----------------|----------|
| **Critical** | -20 | Missing required header, broken cross-reference, placeholder text, invalid percentage |
| **Warning** | -10 | Section too short, undefined acronym, high passive voice |
| **Info** | -2 | Minor formatting issue, word repetition |

### Example Score Calculation

```
Section: "Functional Requirements"

Issues found:
- [CRITICAL] Required header "Acceptance Criteria" missing (-20)
- [CRITICAL] Reference to non-existent section 45 (-20)
- [WARNING] Section too short: 85 words (min: 100) (-10)
- [INFO] High passive voice: 8 instances (-2)

Score = 100 - 20 - 20 - 10 - 2 = 48/100 ❌ (below 85% threshold)
```

---

## 🔍 Check Details

### 1. Structure Check

**What it checks:**
```python
# Required headers for PRD Section 09 (Functional Requirements)
required_headers = [
    "Overview",
    "Requirements",
    "Acceptance Criteria",
]

# Check each header exists
for header in required_headers:
    if header not in content:
        issues.append(VerificationIssue(
            severity="critical",
            description=f"Required header missing: {header}",
        ))
```

**Metrics tracked:**
- `headers_found`: Total headers in section
- `required_present`: Required headers found
- `required_total`: Total required headers

---

### 2. Format Check

**What it checks:**
```python
# Code blocks must have language tags
code_blocks = re.findall(r'```(\w*)', content)
untagged = sum(1 for lang in code_blocks if not lang)

if untagged > 0:
    issues.append(VerificationIssue(
        severity="warning",
        description=f"{untagged} code block(s) missing language tag",
    ))

# Links must be complete
links = re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', content)
for text, url in links:
    if 'http' in url and not url.startswith('http'):
        issues.append(VerificationIssue(
            severity="warning",
            description=f"Potentially broken link: {url}",
        ))
```

**Metrics tracked:**
- `code_blocks`: Total code blocks
- `code_blocks_tagged`: Code blocks with language
- `links`: Total links
- `broken_links`: Potentially broken links

---

### 3. Consistency Check

**What it checks:**
```python
# Terminology must be used consistently
terminology = context.get("terminology", {
    "TAM": "Total Addressable Market",
    "SAM": "Serviceable Addressable Market",
})

for term, definition in terminology.items():
    # Find all uses
    uses = re.findall(r'\b' + term + r'\b', content, re.IGNORECASE)
    
    if uses:
        # Check if defined on first use
        if not re.search(term + r'[^.]*\b(?:is|means)\b', content):
            issues.append(VerificationIssue(
                severity="warning",
                description=f"Term '{term}' used but not defined",
            ))
```

**Metrics tracked:**
- `terminology_count`: Terms in memory
- `consistent_uses`: Correct uses
- `inconsistent_uses`: Incorrect uses

---

### 4. Cross-Reference Check

**What it checks:**
```python
# Section references must point to existing sections
all_sections = ["01", "02", ..., "39"]

section_refs = re.findall(r'(?:Section)\s*(\d+)', content)
for ref in section_refs:
    if ref not in all_sections:
        issues.append(VerificationIssue(
            severity="critical",
            description=f"Reference to non-existent section: {ref}",
        ))
```

**Metrics tracked:**
- `section_refs`: Total section references
- `valid_refs`: References to existing sections
- `invalid_refs`: References to non-existent sections

---

### 5. Completeness Check

**What it checks:**
```python
# No placeholder text
placeholders = [
    r'\[TODO\]',
    r'\[FIXME\]',
    r'{{\w+}}',  # Jinja2 templates
    r'TBD',
]

for pattern in placeholders:
    matches = re.findall(pattern, content, re.IGNORECASE)
    if matches:
        issues.append(VerificationIssue(
            severity="critical",
            description=f"Placeholder text found: {matches[0]}",
        ))

# Minimum word count
if len(content.split()) < min_words:
    issues.append(VerificationIssue(
        severity="warning",
        description=f"Section too short: {len(words)} words (min: {min_words})",
    ))
```

**Metrics tracked:**
- `word_count`: Total words
- `placeholders_found`: Placeholder instances
- `required_keywords`: Required keywords found

---

### 6. Statistical Check

**What it checks:**
```python
# Percentages must be 0-100%
percentages = re.findall(r'(\d+(?:\.\d+)?)\s*%', content)
for pct in percentages:
    pct_value = float(pct)
    if pct_value < 0 or pct_value > 100:
        issues.append(VerificationIssue(
            severity="critical",
            description=f"Invalid percentage: {pct}% (must be 0-100)",
        ))

# Dates must be valid ISO 8601
dates = re.findall(r'\b(\d{4}-\d{2}-\d{2})\b', content)
for date_str in dates:
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        issues.append(VerificationIssue(
            severity="critical",
            description=f"Invalid date: {date_str}",
        ))
```

**Metrics tracked:**
- `percentages_found`: Total percentages
- `invalid_percentages`: Out-of-range percentages
- `dates_found`: Total dates

---

### 7. Quality Check

**What it checks:**
```python
# Sentence length
sentences = re.split(r'[.!?]+', content)
sentence_lengths = [len(s.split()) for s in sentences if s.strip()]

avg_length = sum(sentence_lengths) / len(sentence_lengths)
long_sentences = sum(1 for length in sentence_lengths if length > 40)

if long_sentences > len(sentences) * 0.3:  # >30% long
    issues.append(VerificationIssue(
        severity="warning",
        description=f"{long_sentences} sentences exceed 40 words",
    ))

# Passive voice detection
passive_patterns = [
    r'\b(was|were|been|being)\s+\w+ed\b',
    r'\b(is|are|was|were)\s+\w+ed\s+by\b',
]

passive_count = sum(len(re.findall(p, content)) for p in passive_patterns)

if passive_count > len(sentences) * 0.2:  # >20% passive
    issues.append(VerificationIssue(
        severity="info",
        description=f"High passive voice: {passive_count} instances",
    ))
```

**Metrics tracked:**
- `sentences`: Total sentences
- `avg_sentence_length`: Average words per sentence
- `long_sentences`: Sentences >40 words
- `passive_voice_count`: Passive voice instances

---

## 📈 Verification Result Structure

```python
@dataclass
class VerificationResult:
    section_id: str
    section_name: str
    overall_score: float  # 0-100
    passed: bool  # True if score >= threshold
    issues: List[VerificationIssue]
    checks_performed: List[str]
    metrics: Dict[str, Any]
```

### Example Result

```json
{
  "section_id": "09",
  "section_name": "Functional Requirements",
  "overall_score": 78.0,
  "passed": false,
  "issues": [
    {
      "check_type": "structure",
      "severity": "critical",
      "description": "Required header missing: Acceptance Criteria",
      "location": "Section header",
      "suggestion": "Add header: Acceptance Criteria"
    },
    {
      "check_type": "completeness",
      "severity": "warning",
      "description": "Section too short: 85 words (minimum: 100)",
      "location": "Section 09",
      "suggestion": "Expand content to meet minimum 100 words"
    }
  ],
  "checks_performed": [
    "structure_check",
    "format_check",
    "consistency_check",
    "cross_reference_check",
    "completeness_check",
    "statistical_check",
    "quality_check"
  ],
  "metrics": {
    "headers_found": 2,
    "word_count": 85,
    "placeholders_found": 0,
    "section_refs": 3,
    "valid_refs": 3
  }
}
```

---

## 🚀 Integration with Iterative Generator

```python
async def _verify_section_deterministic(
    self,
    section: Section,
    memory: DocumentMemory,
    context: Dict[str, Any],
) -> Section:
    """Verify using ONLY deterministic checks (NO LLM)"""
    
    # Build verification context
    verification_context = {
        "terminology": memory.get_terminology(),
        "all_sections": list(memory.sections.keys()),
        "min_words": context.get("min_words", {}),
    }
    
    # Run deterministic verification
    result = await self.verifier.verify_section(
        section_id=section.section_id,
        section_name=section.section_name,
        content=section.content,
        context=verification_context,
    )
    
    # Store result
    section.verification_result = result
    section.verification_score = result.overall_score
    
    # Update status
    if result.passed:
        section.status = SectionStatus.VERIFIED
    else:
        section.status = SectionStatus.DRAFT  # → Correction
    
    return section
```

---

## ✅ Benefits of Deterministic Verification

### 1. **No Hallucinations**
- LLM can't make up verification scores
- All checks are algorithm-driven
- Results are auditable

### 2. **100% Reproducible**
```python
# Same content → Same score every time
score1 = await verifier.verify(content)
score2 = await verifier.verify(content)
assert score1 == score2  # Always true
```

### 3. **Explainable**
```python
# Every issue has exact location and suggestion
issue.description  # "Required header missing: Acceptance Criteria"
issue.location     # "Section header"
issue.suggestion   # "Add header: Acceptance Criteria"
```

### 4. **Configurable**
```python
# Adjust thresholds per project
config = VerificationConfig(
    min_words={"09": 100, "10": 200},
    required_headers={"09": ["Overview", "Acceptance Criteria"]},
    severity_weights={"critical": 20, "warning": 10, "info": 2},
)
```

### 5. **Testable**
```python
# Unit tests for each check
def test_structure_check_missing_header():
    content = "# Overview\nSome text"
    result = await verifier._check_structure(content)
    assert len(result.issues) == 1
    assert "Required header missing" in result.issues[0].description
```

---

## 📊 Quality Gates

```python
# Per-section quality gate
if result.overall_score >= 85.0:
    section.status = SectionStatus.VERIFIED
elif result.overall_score >= 70.0:
    section.status = SectionStatus.DRAFT  # → Correction
else:
    section.status = SectionStatus.PENDING  # → Regenerate

# Document-level quality gate
consistency_score = memory.calculate_consistency_score()
if consistency_score >= 90.0:
    logger.info("document_quality_passed", score=consistency_score)
else:
    logger.warning("document_quality_failed", score=consistency_score)
```

---

## 🔮 Future Enhancements

1. **External Fact-Checking APIs**
   - Cross-check statistics with official sources
   - Verify market research data
   - Validate competitor claims

2. **Plagiarism Detection**
   - Check for copied content
   - Ensure original writing

3. **Domain-Specific Rules**
   - PRD-specific checks (e.g., all FR-XXX numbered)
   - Architecture-specific checks (e.g., all components documented)

4. **Machine Learning (Optional)**
   - Train on high-quality documents
   - Detect patterns of good writing
   - Still deterministic (same model → same output)

---

**Dobby now uses 100% deterministic verification - no LLM hallucinations, fully reproducible, auditable results.** ✅
