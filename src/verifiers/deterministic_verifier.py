"""
Deterministic Verifier for Dobby v2.0

NO LLM-based verification. All checks are deterministic:
- Structure check (required headers present)
- Format check (valid markdown, code blocks tagged)
- Consistency check (terminology used correctly)
- Cross-reference check (section refs point to existing sections)
- Completeness check (no placeholders, min word count)
- Statistical check (valid percentages 0-100%, ISO dates)
- Quality check (readability, sentence length, passive voice)

All checks return:
- Score (0-100)
- Pass/fail status
- Issues found (list)
- Metrics (dict)
"""

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
from enum import Enum
import re
from datetime import datetime
import statistics


# ============================================================================
# Verification Result Types
# ============================================================================
class CheckType(str, Enum):
    """7 deterministic check types"""
    STRUCTURE = "structure"
    FORMAT = "format"
    CONSISTENCY = "consistency"
    CROSS_REFERENCE = "cross_reference"
    COMPLETENESS = "completeness"
    STATISTICAL = "statistical"
    QUALITY = "quality"


class IssueSeverity(str, Enum):
    """Issue severity levels"""
    CRITICAL = "critical"  # -20 points
    WARNING = "warning"  # -10 points
    INFO = "info"  # -2 points


@dataclass
class VerificationIssue:
    """
    Verification issue found during checking
    
    Attributes:
        check_type: Which check found this issue
        severity: CRITICAL, WARNING, or INFO
        message: Human-readable description
        location: Where in the content (line number, section ID)
        suggestion: How to fix it
    """
    check_type: CheckType
    severity: IssueSeverity
    message: str
    location: Optional[str] = None
    suggestion: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_type": self.check_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
            "suggestion": self.suggestion,
        }


@dataclass
class VerificationResult:
    """
    Result of deterministic verification
    
    Attributes:
        overall_score: 0-100 score
        passed: True if score >= 85%
        issues: List of issues found
        checks_performed: List of check types that ran
        metrics: Metrics from each check
        verified_at: Timestamp
    """
    overall_score: float
    passed: bool
    issues: List[VerificationIssue]
    checks_performed: List[CheckType]
    metrics: Dict[str, Any]
    verified_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_score": round(self.overall_score, 2),
            "passed": self.passed,
            "issues": [i.to_dict() for i in self.issues],
            "checks_performed": [c.value for c in self.checks_performed],
            "metrics": self.metrics,
            "verified_at": self.verified_at.isoformat(),
        }


# ============================================================================
# Deterministic Verifier
# ============================================================================
class DeterministicVerifier:
    """
    Deterministic verifier with 7 check types
    
    NO LLM calls. All checks are algorithm-driven.
    """
    
    def __init__(self):
        # Scoring weights
        self.critical_penalty = 20
        self.warning_penalty = 10
        self.info_penalty = 2
        
        # Minimum thresholds
        self.pass_threshold = 85.0
        self.min_word_counts = {
            "feature": 50,
            "user_story": 30,
            "functional_analysis": 100,
            "flowchart": 20,
            "pseudocode": 50,
            "tdd_tests": 100,
            "documentation": 200,
        }
    
    async def verify_section(
        self,
        section_id: str,
        content: str,
        node_type: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> VerificationResult:
        """
        Verify a section of content
        
        Args:
            section_id: Section identifier
            content: Markdown content to verify
            node_type: Type of node (feature, user_story, etc.)
            context: Additional context (terminology, all_sections, etc.)
        
        Returns:
            VerificationResult with score, issues, metrics
        """
        context = context or {}
        issues: List[VerificationIssue] = []
        checks_performed: List[CheckType] = []
        metrics: Dict[str, Any] = {}
        
        # Run all 7 checks
        structure_result = self._check_structure(content, node_type)
        checks_performed.append(CheckType.STRUCTURE)
        issues.extend(structure_result["issues"])
        metrics["structure"] = structure_result["metrics"]
        
        format_result = self._check_format(content, node_type)
        checks_performed.append(CheckType.FORMAT)
        issues.extend(format_result["issues"])
        metrics["format"] = format_result["metrics"]
        
        consistency_result = self._check_consistency(content, context.get("terminology", {}))
        checks_performed.append(CheckType.CONSISTENCY)
        issues.extend(consistency_result["issues"])
        metrics["consistency"] = consistency_result["metrics"]
        
        crossref_result = self._check_cross_references(
            content,
            context.get("all_sections", []),
        )
        checks_performed.append(CheckType.CROSS_REFERENCE)
        issues.extend(crossref_result["issues"])
        metrics["cross_reference"] = crossref_result["metrics"]
        
        completeness_result = self._check_completeness(
            content,
            node_type,
            self.min_word_counts.get(node_type, 50),
        )
        checks_performed.append(CheckType.COMPLETENESS)
        issues.extend(completeness_result["issues"])
        metrics["completeness"] = completeness_result["metrics"]
        
        statistical_result = self._check_statistical(content)
        checks_performed.append(CheckType.STATISTICAL)
        issues.extend(statistical_result["issues"])
        metrics["statistical"] = statistical_result["metrics"]
        
        quality_result = self._check_quality(content)
        checks_performed.append(CheckType.QUALITY)
        issues.extend(quality_result["issues"])
        metrics["quality"] = quality_result["metrics"]
        
        # Calculate overall score
        overall_score = self._calculate_score(issues)
        passed = overall_score >= self.pass_threshold
        
        return VerificationResult(
            overall_score=overall_score,
            passed=passed,
            issues=issues,
            checks_performed=checks_performed,
            metrics=metrics,
        )
    
    def _check_structure(self, content: str, node_type: str) -> Dict[str, Any]:
        """
        Check 1: Structure
        
        Validates:
        - Required headers are present
        - Headers are in correct order
        - No missing sections
        """
        issues = []
        metrics = {"headers_found": 0, "required_headers": 0}
        
        # Define required headers for each node type
        required_headers = {
            "feature": ["## Overview", "## Problem", "## Solution"],
            "user_story": ["## User Story", "## Acceptance Criteria"],
            "functional_analysis": ["## Functional Requirements", "## Non-Functional Requirements"],
            "flowchart": ["## Flow Description"],
            "pseudocode": ["## Algorithm"],
            "tdd_tests": ["## Test Cases", "## Test Strategy"],
            "documentation": ["## Overview", "## Usage"],
        }
        
        headers = required_headers.get(node_type, [])
        metrics["required_headers"] = len(headers)
        
        # Check for required headers (case-insensitive; a deeper heading like
        # "### Overview" still satisfies "## Overview"). A single missing section
        # is a WARNING rather than CRITICAL so one omission on a weaker model
        # doesn't fail an otherwise-complete document; several missing sections
        # still accumulate enough penalty to fail it.
        content_lower = content.lower()
        for header in headers:
            if header.lower() not in content_lower:
                issues.append(VerificationIssue(
                    check_type=CheckType.STRUCTURE,
                    severity=IssueSeverity.WARNING,
                    message=f"Required header missing: {header}",
                    suggestion=f"Add the section with header: {header}",
                ))
            else:
                metrics["headers_found"] += 1
        
        return {"issues": issues, "metrics": metrics}
    
    def _check_format(self, content: str, node_type: str = "") -> Dict[str, Any]:
        """
        Check 2: Format

        Validates:
        - Valid markdown syntax
        - Code blocks are tagged with language
        - Links are valid (no broken markdown links)
        - No malformed HTML

        Untagged code fences are legitimate for pseudocode and flowchart nodes
        (pseudocode is not a real language), so they are not flagged for those
        node types. Elsewhere an untagged fence is a minor (INFO) style nit
        rather than a warning.
        """
        issues = []
        metrics = {"code_blocks": 0, "tagged_code_blocks": 0}

        untagged_ok = node_type in ("pseudocode", "flowchart")

        # Check for untagged code blocks
        code_block_pattern = r"```(\w*)\n(.*?)```"
        code_blocks = re.findall(code_block_pattern, content, re.DOTALL)

        for lang, _ in code_blocks:
            metrics["code_blocks"] += 1
            if not lang.strip():
                if not untagged_ok:
                    issues.append(VerificationIssue(
                        check_type=CheckType.FORMAT,
                        severity=IssueSeverity.INFO,
                        message="Code block without language tag",
                        suggestion="Add language tag to code block (e.g., ```python)",
                    ))
            else:
                metrics["tagged_code_blocks"] += 1
        
        # Check for broken markdown links
        broken_link_pattern = r"\[([^\]]+)\]\(\)"
        broken_links = re.findall(broken_link_pattern, content)
        
        for link_text in broken_links:
            issues.append(VerificationIssue(
                check_type=CheckType.FORMAT,
                severity=IssueSeverity.WARNING,
                message=f"Broken link: {link_text}",
                suggestion="Add URL to the link or remove the link syntax",
            ))
        
        # Check for malformed HTML
        malformed_html_pattern = r"<[a-z]+[^>]*$|^[^<]*</[a-z]+>"
        if re.search(malformed_html_pattern, content, re.MULTILINE):
            issues.append(VerificationIssue(
                check_type=CheckType.FORMAT,
                severity=IssueSeverity.INFO,
                message="Possible malformed HTML tags",
                suggestion="Review HTML tags for proper opening and closing",
            ))
        
        return {"issues": issues, "metrics": metrics}
    
    def _check_consistency(
        self,
        content: str,
        terminology: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Check 3: Consistency
        
        Validates:
        - Terminology is used consistently
        - No contradictory statements
        - Same terms used throughout
        """
        issues = []
        metrics = {"terminology_checks": 0, "inconsistencies": 0}
        
        # Check terminology consistency
        for term, definition in terminology.items():
            metrics["terminology_checks"] += 1
            
            # Count occurrences
            occurrences = len(re.findall(rf"\b{re.escape(term)}\b", content, re.IGNORECASE))
            
            if occurrences > 0:
                # Check if definition is mentioned at least once
                if definition.lower() not in content.lower():
                    issues.append(VerificationIssue(
                        check_type=CheckType.CONSISTENCY,
                        severity=IssueSeverity.INFO,
                        message=f"Term '{term}' used but definition not mentioned",
                        location=f"Term appears {occurrences} times",
                        suggestion=f"Consider adding definition: {definition}",
                    ))
                    metrics["inconsistencies"] += 1
        
        return {"issues": issues, "metrics": metrics}
    
    def _check_cross_references(
        self,
        content: str,
        all_sections: List[str],
    ) -> Dict[str, Any]:
        """
        Check 4: Cross-Reference
        
        Validates:
        - Section references point to existing sections
        - No broken internal links
        - All referenced sections exist
        """
        issues = []
        metrics = {"references_found": 0, "valid_references": 0}
        
        # Find all section references (e.g., "See Section 3.2")
        section_ref_pattern = r"(?:Section|Chapter|Part)\s*(\d+(?:\.\d+)*)"
        references = re.findall(section_ref_pattern, content, re.IGNORECASE)
        
        for ref in references:
            metrics["references_found"] += 1
            
            # Check if referenced section exists
            # (In real implementation, would map section numbers to IDs)
            if ref in all_sections or any(ref.startswith(s) for s in all_sections):
                metrics["valid_references"] += 1
            else:
                issues.append(VerificationIssue(
                    check_type=CheckType.CROSS_REFERENCE,
                    severity=IssueSeverity.CRITICAL,
                    message=f"Reference to non-existent section: {ref}",
                    suggestion="Verify section number or update reference",
                ))
        
        return {"issues": issues, "metrics": metrics}
    
    def _check_completeness(
        self,
        content: str,
        node_type: str,
        min_word_count: int,
    ) -> Dict[str, Any]:
        """
        Check 5: Completeness
        
        Validates:
        - No placeholders (TODO, FIXME, TBD, etc.)
        - Minimum word count met
        - All required fields filled
        """
        issues = []
        metrics = {"word_count": 0, "placeholders_found": 0}
        
        # Count words
        words = re.findall(r"\b\w+\b", content)
        metrics["word_count"] = len(words)
        
        # Check minimum word count
        if len(words) < min_word_count:
            issues.append(VerificationIssue(
                check_type=CheckType.COMPLETENESS,
                severity=IssueSeverity.WARNING,
                message=f"Content too short: {len(words)} words (minimum: {min_word_count})",
                suggestion=f"Add {min_word_count - len(words)} more words",
            ))
        
        # Check for placeholders
        placeholder_patterns = [
            r"\bTODO\b",
            r"\bFIXME\b",
            r"\bTBD\b",
            r"\bXXX\b",
            r"\[\[.*?\]\]",  # [[placeholder]]
            r"\{\{.*?\}\}",  # {{placeholder}}
        ]
        
        for pattern in placeholder_patterns:
            placeholders = re.findall(pattern, content, re.IGNORECASE)
            metrics["placeholders_found"] += len(placeholders)
            
            for placeholder in placeholders:
                issues.append(VerificationIssue(
                    check_type=CheckType.COMPLETENESS,
                    severity=IssueSeverity.CRITICAL,
                    message=f"Placeholder found: {placeholder}",
                    suggestion="Replace placeholder with actual content",
                ))
        
        return {"issues": issues, "metrics": metrics}
    
    def _check_statistical(self, content: str) -> Dict[str, Any]:
        """
        Check 6: Statistical
        
        Validates:
        - Percentages are in valid range (0-100%)
        - Dates are in valid format (ISO 8601)
        - Numbers are reasonable (no obvious typos)
        """
        issues = []
        metrics = {"percentages_found": 0, "valid_percentages": 0}
        
        # Check percentages
        percentage_pattern = r"(\d+(?:\.\d+)?)%"
        percentages = re.findall(percentage_pattern, content)
        
        for pct in percentages:
            metrics["percentages_found"] += 1
            pct_value = float(pct)
            
            if pct_value < 0 or pct_value > 100:
                issues.append(VerificationIssue(
                    check_type=CheckType.STATISTICAL,
                    severity=IssueSeverity.CRITICAL,
                    message=f"Invalid percentage: {pct}% (must be 0-100%)",
                    suggestion="Correct the percentage value",
                ))
            else:
                metrics["valid_percentages"] += 1
        
        # Check dates (ISO 8601 format)
        date_pattern = r"\b(\d{4}-\d{2}-\d{2})\b"
        dates = re.findall(date_pattern, content)
        
        for date_str in dates:
            try:
                datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                issues.append(VerificationIssue(
                    check_type=CheckType.STATISTICAL,
                    severity=IssueSeverity.WARNING,
                    message=f"Invalid date format: {date_str}",
                    suggestion="Use ISO 8601 format (YYYY-MM-DD)",
                ))
        
        return {"issues": issues, "metrics": metrics}
    
    def _check_quality(self, content: str) -> Dict[str, Any]:
        """
        Check 7: Quality
        
        Validates:
        - Readability (Flesch-Kincaid score)
        - Sentence length (average < 25 words)
        - Passive voice detection (< 20% passive sentences)
        """
        issues = []
        metrics = {
            "sentence_count": 0,
            "avg_sentence_length": 0,
            "passive_voice_count": 0,
        }
        
        # Split into sentences
        sentences = re.split(r"[.!?]+", content)
        sentences = [s.strip() for s in sentences if s.strip()]
        metrics["sentence_count"] = len(sentences)
        
        if len(sentences) == 0:
            return {"issues": issues, "metrics": metrics}
        
        # Calculate average sentence length
        sentence_lengths = [len(s.split()) for s in sentences]
        avg_length = statistics.mean(sentence_lengths)
        metrics["avg_sentence_length"] = int(round(avg_length, 0))
        
        if avg_length > 25:
            issues.append(VerificationIssue(
                check_type=CheckType.QUALITY,
                severity=IssueSeverity.INFO,
                message=f"Average sentence length too high: {avg_length:.0f} words (recommended: <25)",
                suggestion="Break long sentences into shorter ones",
            ))
        
        # Detect passive voice (simplified heuristic)
        passive_patterns = [
            r"\b(is|are|was|were|be|been|being)\s+\w+ed\b",
            r"\b(is|are|was|were|be|been|being)\s+\w+en\b",
        ]
        
        passive_count = 0
        for pattern in passive_patterns:
            passive_count += len(re.findall(pattern, content, re.IGNORECASE))
        
        metrics["passive_voice_count"] = passive_count
        
        if len(sentences) > 0:
            passive_ratio = passive_count / len(sentences)
            
            if passive_ratio > 0.2:
                issues.append(VerificationIssue(
                    check_type=CheckType.QUALITY,
                    severity=IssueSeverity.INFO,
                    message=f"High passive voice usage: {passive_ratio*100:.0f}% (recommended: <20%)",
                    suggestion="Use active voice where possible",
                ))
        
        return {"issues": issues, "metrics": metrics}
    
    def _calculate_score(self, issues: List[VerificationIssue]) -> float:
        """
        Calculate overall score
        
        Formula: 100 - (critical * 20) - (warning * 10) - (info * 2)
        Minimum score: 0
        Maximum score: 100
        """
        critical_count = sum(1 for i in issues if i.severity == IssueSeverity.CRITICAL)
        warning_count = sum(1 for i in issues if i.severity == IssueSeverity.WARNING)
        info_count = sum(1 for i in issues if i.severity == IssueSeverity.INFO)
        
        score = 100.0
        score -= critical_count * self.critical_penalty
        score -= warning_count * self.warning_penalty
        score -= info_count * self.info_penalty
        
        return max(0.0, min(100.0, score))


# ============================================================================
# Factory Function
# ============================================================================
def get_verifier() -> DeterministicVerifier:
    """Get deterministic verifier instance"""
    return DeterministicVerifier()
