"""
Classical reasoning.

The propositional engine is a *decision procedure*, so it is tested against the
textbook inventory of valid and invalid argument forms. Every classically valid
form must come back `valid`; every fallacy must come back `invalid` with a
countermodel that actually witnesses the failure — a countermodel that does not
falsify the argument is worse than none.
"""

import pytest

from src.reasoning import logic as L
from src.reasoning.audit import audit_findings


class TestParser:
    @pytest.mark.parametrize("text,kind", [
        ("A", "atom"), ("~A", "not"), ("A & B", "and"), ("A | B", "or"),
        ("A -> B", "implies"), ("A <-> B", "iff"),
    ])
    def test_connectives(self, text, kind):
        assert L.parse(text).kind == kind

    @pytest.mark.parametrize("a,b", [
        ("~A", "!A"), ("~A", "not A"), ("A & B", "A and B"), ("A & B", "A ^ B"),
        ("A | B", "A or B"), ("A -> B", "A => B"), ("A -> B", "A implies B"),
        ("A <-> B", "A iff B"),
    ])
    def test_alternative_spellings_agree(self, a, b):
        assert str(L.parse(a)) == str(L.parse(b))

    def test_precedence_binds_not_tightest_and_iff_loosest(self):
        # ~A & B is (~A) & B, not ~(A & B)
        assert str(L.parse("~A & B")) == "(¬A ∧ B)"
        # A & B -> C is (A & B) -> C
        assert str(L.parse("A & B -> C")) == "((A ∧ B) → C)"
        # A -> B <-> C is (A -> B) <-> C
        assert str(L.parse("A -> B <-> C")) == "((A → B) ↔ C)"

    def test_implication_is_right_associative(self):
        assert str(L.parse("A -> B -> C")) == "(A → (B → C))"

    def test_parentheses_override(self):
        assert str(L.parse("~(A & B)")) == "¬(A ∧ B)"

    @pytest.mark.parametrize("bad", ["", "   ", "A &", "(A", "A)", "& B", "A B C", "@"])
    def test_malformed_input_raises_a_usable_message(self, bad):
        with pytest.raises(L.LogicError):
            L.parse(bad)


class TestValidForms:
    """Every one of these is classically valid and must be proved."""

    @pytest.mark.parametrize("premises,conclusion,name", [
        (["A -> B", "A"], "B", "modus ponens"),
        (["A -> B", "~B"], "~A", "modus tollens"),
        (["A -> B", "B -> C"], "A -> C", "hypothetical syllogism"),
        (["A | B", "~A"], "B", "disjunctive syllogism"),
        (["A & B"], "A", "simplification"),
        (["A"], "A | B", "addition"),
        (["A", "B"], "A & B", "conjunction"),
        (["A -> B", "C -> D", "A | C"], "B | D", "constructive dilemma"),
        (["~(A & B)"], "~A | ~B", "de morgan (conjunction)"),
        (["~(A | B)"], "~A & ~B", "de morgan (disjunction)"),
        (["A -> B"], "~B -> ~A", "contraposition"),
        (["~A -> (B & ~B)"], "A", "reductio"),
        ([], "A | ~A", "excluded middle"),
        ([], "~(A & ~A)", "non-contradiction"),
        (["A <-> B", "A"], "B", "biconditional elimination"),
    ])
    def test_is_valid(self, premises, conclusion, name):
        v = L.check(premises, conclusion)
        assert v.verdict == "valid", f"{name} should be valid, got {v.verdict}"


class TestFallacies:
    """Invalid forms must be refuted, and the countermodel must really witness it."""

    @pytest.mark.parametrize("premises,conclusion,name", [
        (["A -> B", "B"], "A", "affirming the consequent"),
        (["A -> B", "~A"], "~B", "denying the antecedent"),
        (["A | B"], "A & B", "disjunction to conjunction"),
        (["A"], "A & B", "unwarranted conjunction"),
        (["A -> B"], "B -> A", "converse error"),
    ])
    def test_is_invalid_with_a_real_countermodel(self, premises, conclusion, name):
        v = L.check(premises, conclusion)
        assert v.verdict == "invalid", f"{name} should be invalid"
        assert v.countermodel is not None

        # The countermodel must satisfy every premise and falsify the conclusion.
        model = v.countermodel
        assert all(L.parse(p).evaluate(model) for p in premises)
        assert not L.parse(conclusion).evaluate(model)


class TestConsistency:
    def test_contradictory_set_is_rejected(self):
        assert L.is_consistent([L.parse("A"), L.parse("~A")]).verdict == "invalid"

    def test_satisfiable_set_returns_a_witnessing_model(self):
        formulas = [L.parse("A -> B"), L.parse("A")]
        v = L.is_consistent(formulas)
        assert v.verdict == "valid"
        assert all(f.evaluate(v.countermodel) for f in formulas)

    def test_empty_set_is_consistent(self):
        assert L.is_consistent([]).verdict == "valid"

    def test_finds_the_contradicting_pair(self):
        formulas = [L.parse("A"), L.parse("B"), L.parse("~A")]
        assert L.find_contradictions(formulas) == [(0, 2)]

    def test_a_self_contradictory_claim_does_not_blame_its_neighbours(self):
        formulas = [L.parse("A & ~A"), L.parse("B")]
        assert L.find_contradictions(formulas) == []

    def test_three_way_clash_reports_each_pair(self):
        formulas = [L.parse("A"), L.parse("~A"), L.parse("~A | ~A")]
        assert (0, 1) in L.find_contradictions(formulas)


class TestLimits:
    def test_too_many_atoms_returns_unknown_not_a_hang(self):
        atoms = [chr(ord("A") + i) for i in range(L.MAX_ATOMS + 2)]
        v = L.entails([L.parse(a) for a in atoms], L.parse("A"))
        assert v.verdict == "unknown"
        assert "exceeds" in v.reason

    def test_unparseable_input_is_unknown_not_an_exception(self):
        assert L.check(["A &"], "B").verdict == "unknown"

    def test_tautology_detection(self):
        assert L.is_tautology(L.parse("A | ~A"))
        assert not L.is_tautology(L.parse("A & ~A"))


class TestFindingsAudit:
    def test_detects_opposite_claims_about_the_same_subject(self):
        r = audit_findings([
            "The consultant market for note tools is growing rapidly",
            "The consultant market for note tools is shrinking fast",
        ])
        assert not r.consistent
        assert r.conflicts[0].left_index == 0 and r.conflicts[0].right_index == 1

    def test_ignores_opposite_claims_about_different_subjects(self):
        r = audit_findings([
            "The market for legal software is growing rapidly",
            "Warehouse robotics hardware costs are shrinking fast",
        ])
        assert r.consistent

    def test_unrelated_findings_are_consistent(self):
        r = audit_findings([
            "Buyers are enterprise IT departments with central procurement",
            "Pricing should sit near twenty dollars per seat monthly",
            "Offline access matters more than real-time collaboration",
        ])
        assert r.consistent

    def test_provenance_markers_do_not_affect_the_comparison(self):
        r = audit_findings([
            "[unverified] The consultant tooling market is expanding quickly",
            "[inferred] The consultant tooling market is contracting quickly",
        ])
        assert not r.consistent

    def test_a_single_finding_cannot_conflict(self):
        assert audit_findings(["Only one finding here about markets"]).consistent

    def test_empty_input_is_consistent(self):
        r = audit_findings([])
        assert r.consistent and r.checked == 0

    @pytest.mark.parametrize("meta", [
        "The search results do not provide information on local-first note-taking apps",
        "Search results do not contain relevant information about pricing",
        "No relevant information was found in the sources",
        "The context does not mention any competitors",
        "Unable to determine the market size from these results",
    ])
    def test_statements_about_the_search_never_count_as_contradictions(self, meta):
        """Observed live: one meta-statement produced eight false conflicts.

        "No information was found" is a remark about the search, not the
        negation of any claim about the world.
        """
        r = audit_findings([
            "The market for consultant note-taking tools is growing steadily",
            meta,
        ])
        assert r.consistent, f"meta-statement wrongly flagged: {meta}"

    def test_negation_alone_needs_near_total_subject_overlap(self):
        """Loose negation matching was the source of the false positives."""
        r = audit_findings([
            "Evernote offers a mature SDK for iOS and Android developers",
            "Microsoft Graph API does not support offline-first sync for Android",
        ])
        assert r.consistent

    def test_a_genuine_negated_pair_is_still_caught(self):
        r = audit_findings([
            "Independent consultants prefer offline-first note tools",
            "Independent consultants do not prefer offline-first note tools",
        ])
        assert not r.consistent

    def test_result_serializes_for_storage(self):
        d = audit_findings([
            "The market for AI tools is growing steadily",
            "The market for AI tools is shrinking steadily",
        ]).to_dict()
        assert d["consistent"] is False
        assert d["conflicts"][0]["left_index"] == 0
        assert "explanation" in d["conflicts"][0]
