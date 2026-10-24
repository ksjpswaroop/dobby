"""
Deductive reasoning for Dobby.

`logic` is a complete, dependency-free decision procedure for classical
propositional logic — it always runs. `symbolica` is an optional escalation to
a full symbolic engine (first-order logic, Fitch proofs, causal and deontic
queries) when the user has one configured.
"""

from src.reasoning.logic import (  # noqa: F401
    Formula, LogicError, Verdict, check, entails, find_contradictions,
    is_consistent, is_tautology, parse,
)
