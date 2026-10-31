"""
Adaptive Learning Engine for LearnPath for Schools.

Pure-Python module — does NOT import any LLM code.

Provides:
  - Bayesian Knowledge Tracing (BKT)
  - Diagnostic scoring
  - Prerequisite-aware concept selection
  - Question selection (prefer unseen, difficulty scaling)
  - Hint ladder (4 levels, escalation/de-escalation rules)
  - Misconception diagnosis and recurring-mistake detection
  - Repair cycle for recurring misconceptions
  - Spaced-review scheduling (1, 3, 7, 21 days)
  - Transfer-check handling
  - Generic (non-adaptive) condition
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple


# ============================================================================
# BKT — Bayesian Knowledge Tracing
# ============================================================================

@dataclass
class BKTParams:
    """Parameters exactly matching the specification."""
    p_init: float = 0.2
    p_transit: float = 0.1
    p_slip: float = 0.1
    p_guess: float = 0.2
    mastery_threshold: float = 0.9


class BKT:
    """Bayesian Knowledge Tracing model.

    Only an *unaided* correct answer counts as correct for mastery.
    A correct answer with any hint counts as incorrect for mastery
    and is logged as "with help".
    """

    def __init__(self, params: BKTParams | None = None):
        self.params = params or BKTParams()

    def update(self, p_known: float, correct: bool, unaided: bool) -> float:
        """Return updated mastery probability after one observation.

        Parameters
        ----------
        p_known : float
            Current mastery probability in [0, 1].
        correct : bool
            Whether the student's answer was correct.
        unaided : bool
            True only if no hints were used.
        """
        p = self.params
        # Treat hinted-correct as incorrect for mastery
        effective_correct = correct and unaided

        if effective_correct:
            # P(correct | known) = 1 - slip;  P(correct | ~known) = guess
            p_correct = p_known * (1 - p.p_slip) + (1 - p_known) * p.p_guess
            if p_correct == 0:
                posterior = 0.0
            else:
                posterior = (p_known * (1 - p.p_slip)) / p_correct
        else:
            # P(wrong | known) = slip;  P(wrong | ~known) = 1 - guess
            p_wrong = p_known * p.p_slip + (1 - p_known) * (1 - p.p_guess)
            if p_wrong == 0:
                posterior = 0.0
            else:
                posterior = (p_known * p.p_slip) / p_wrong

        # Learning transition
        new_p = posterior + (1 - posterior) * p.p_transit
        return max(0.0, min(1.0, new_p))

    def is_mastered(self, p_known: float) -> bool:
        return p_known >= self.params.mastery_threshold


# ============================================================================
# Diagnostic scoring
# ============================================================================

def score_diagnostic(correct_without_hints: int, total: int) -> float:
    """Score a diagnostic block for a single concept.

    Returns:
        0.8 if all items correct unaided,
        0.5 if some items correct unaided,
        0.2 if no items correct unaided.
    """
    if total <= 0:
        return 0.2
    if correct_without_hints >= total:
        return 0.8
    if correct_without_hints <= 0:
        return 0.2
    return 0.5


def run_diagnostic(
    responses: List[Dict[str, Any]],
    concept_ids: List[str],
) -> Dict[str, float]:
    """Run diagnostic and return mastery scores per concept.

    ``responses`` is a list of dicts with keys:
        concept_id, correct (bool), unaided (bool)

    Strong students (all correct unaided) skip concepts they already know.
    """
    # Group by concept
    by_concept: Dict[str, List[Dict[str, Any]]] = {}
    for r in responses:
        cid = r["concept_id"]
        by_concept.setdefault(cid, []).append(r)

    scores: Dict[str, float] = {}
    for cid in concept_ids:
        items = by_concept.get(cid, [])
        total = len(items)
        correct_unaided = sum(
            1 for i in items if i.get("correct") and i.get("unaided", True)
        )
        scores[cid] = score_diagnostic(correct_unaided, total)
    return scores


# ============================================================================
# Concept selection (prerequisite-aware)
# ============================================================================

def select_next_concept(
    masteries: Dict[str, float],
    prerequisites: Dict[str, List[str]],
    threshold: float = 0.9,
) -> Optional[str]:
    """Select the eligible concept with the lowest mastery.

    Eligible means all prerequisites >= threshold and the concept itself < threshold.
    """
    eligible: List[Tuple[str, float]] = []
    for cid, prereqs in prerequisites.items():
        own = masteries.get(cid, 0.0)
        if own >= threshold:
            continue
        if all(masteries.get(p, 0.0) >= threshold for p in prereqs):
            eligible.append((cid, own))
    if not eligible:
        return None
    return min(eligible, key=lambda x: x[1])[0]


# ============================================================================
# Spaced-review scheduling
# ============================================================================

SPACED_REVIEW_INTERVALS = [1, 3, 7, 21]  # days


def get_spaced_review_concepts(
    masteries: Dict[str, float],
    mastery_dates: Dict[str, datetime],
    review_counts: Dict[str, int],
    now: datetime | None = None,
    threshold: float = 0.9,
) -> List[str]:
    """Return concept IDs that are due for spaced review *now*."""
    if now is None:
        now = datetime.utcnow()
    due: List[str] = []
    for cid, p in masteries.items():
        if p < threshold:
            continue
        mdate = mastery_dates.get(cid)
        if mdate is None:
            continue
        count = review_counts.get(cid, 0)
        idx = min(count, len(SPACED_REVIEW_INTERVALS) - 1)
        interval = timedelta(days=SPACED_REVIEW_INTERVALS[idx])
        if now >= mdate + interval:
            due.append(cid)
    return due


# ============================================================================
# Question selection
# ============================================================================

def select_question(
    concept_id: str,
    all_questions: List[Dict[str, Any]],
    seen_ids: Set[str],
    mastery: float,
    include_transfer: bool = False,
) -> Optional[Dict[str, Any]]:
    """Select the next question for the concept.

    Rules:
    - Prefer unseen questions.
    - Repeat only after every item for the concept has been seen.
    - Difficulty: medium for new concepts, harder for strong students.
    - Transfer questions are never in the practice set unless include_transfer is True.
    """
    pool = [
        q for q in all_questions
        if q.get("concept_id") == concept_id
        and (include_transfer or not q.get("is_transfer", False))
    ]
    if not pool:
        return None

    # Separate unseen and seen
    unseen = [q for q in pool if q["id"] not in seen_ids]
    if not unseen:
        # All seen — reset and pick from full pool
        unseen = pool

    # Difficulty preference
    if mastery >= 0.7:
        preferred_diff = "hard"
    else:
        preferred_diff = "medium"

    # Try preferred difficulty first
    preferred = [q for q in unseen if q.get("difficulty") == preferred_diff]
    if preferred:
        return random.choice(preferred)
    return random.choice(unseen)


def select_transfer_question(
    concept_id: str,
    all_questions: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Select a transfer question — shown only when student presses 'I think I've got it'."""
    transfer = [
        q for q in all_questions
        if q.get("concept_id") == concept_id and q.get("is_transfer", False)
    ]
    if not transfer:
        return None
    return random.choice(transfer)


# ============================================================================
# Hint ladder
# ============================================================================

HINT_LEVELS = [1, 2, 3, 4]


@dataclass
class HintState:
    """Tracks the current hint level for a student on a concept."""
    level: int = 1
    consecutive_unaided_correct: int = 0


class HintLadder:
    """Manages hint escalation and de-escalation.

    Rules:
    - An error raises the level by 1.
    - Two unaided correct answers in a row lower it by 1.
    - A recurring misconception starts at level 3.
    """

    @staticmethod
    def escalate(state: HintState) -> HintState:
        """Raise hint level by 1 (on error)."""
        state.level = min(state.level + 1, 4)
        state.consecutive_unaided_correct = 0
        return state

    @staticmethod
    def on_correct_unaided(state: HintState) -> HintState:
        """Record an unaided correct answer; de-escalate after 2 in a row."""
        state.consecutive_unaided_correct += 1
        if state.consecutive_unaided_correct >= 2:
            state.level = max(state.level - 1, 1)
            state.consecutive_unaided_correct = 0
        return state

    @staticmethod
    def for_recurring_misconception() -> HintState:
        """Return a hint state starting at level 3 for recurring misconceptions."""
        return HintState(level=3, consecutive_unaided_correct=0)

    @staticmethod
    def get_hint_text(
        question_hints: List[Dict[str, Any]],
        level: int,
    ) -> str:
        """Look up the hint text for the given level from question hint data."""
        for h in question_hints:
            if h.get("level") == level:
                return h.get("text", "")
        return f"Hint level {level}"


# ============================================================================
# Misconception diagnosis and recurring-mistake detection
# ============================================================================

def diagnose_answer(
    selected_option_id: str,
    options: List[Dict[str, Any]],
) -> Optional[str]:
    """Return the misconception_id for the selected option, or None if correct.

    Each wrong option is linked to a misconception ID or "gap".
    """
    for opt in options:
        if opt["id"] == selected_option_id:
            if opt.get("correct", False):
                return None
            return opt.get("misconception_id", "gap")
    return None


def detect_recurring(
    misconception_log: List[Dict[str, Any]],
    concept_id: str,
) -> List[str]:
    """Return misconception IDs seen 2+ times for the same concept (recurring)."""
    counts: Dict[str, int] = {}
    for entry in misconception_log:
        if entry.get("concept_id") != concept_id:
            continue
        mid = entry.get("misconception_id")
        if mid and mid != "gap":
            counts[mid] = counts.get(mid, 0) + 1
    return [mid for mid, c in counts.items() if c >= 2]


# ============================================================================
# Repair cycle for recurring misconceptions
# ============================================================================

@dataclass
class RepairCycle:
    """Tracks the repair state for a recurring misconception.

    Sequence:
    1. Contrasting example
    2. 2-3 practice questions on the misconception
    3. Check question with no hints
    """
    misconception_id: str
    concept_id: str
    stage: str = "contrasting_example"  # contrasting_example | practice | check
    practice_count: int = 0
    max_practice: int = 3

    def advance(self, correct: bool) -> str:
        """Advance the repair cycle. Returns new stage."""
        if self.stage == "contrasting_example":
            self.stage = "practice"
            return self.stage
        if self.stage == "practice":
            self.practice_count += 1
            if self.practice_count >= 2:  # at least 2
                self.stage = "check"
            return self.stage
        return "done"


# ============================================================================
# Transfer check
# ============================================================================

def check_transfer(
    correct: bool,
    unaided: bool,
    mastery: float,
    threshold: float = 0.9,
) -> Dict[str, Any]:
    """Evaluate a transfer check attempt.

    Pass: correct with zero hints.
    A pass with mastery >= threshold marks the concept mastered.
    A fail returns the student to diagnosis for that concept.
    """
    passed = correct and unaided
    mastered = passed and mastery >= threshold
    return {
        "passed": passed,
        "mastered": mastered,
        "action": "mastered" if mastered else ("continue" if passed else "re_diagnose"),
    }


# ============================================================================
# Generic (non-adaptive) condition
# ============================================================================

GENERIC_HINT_LEVEL = 2


def get_generic_question(
    all_questions: List[Dict[str, Any]],
    index: int,
) -> Optional[Dict[str, Any]]:
    """Return a question from the fixed sequence for the generic condition.

    The generic condition uses a fixed order, fixed hint level 2, and
    must never call the adaptive engine.
    """
    non_transfer = [q for q in all_questions if not q.get("is_transfer", False)]
    if 0 <= index < len(non_transfer):
        return non_transfer[index]
    return None


# ============================================================================
# Mock-test scoring
# ============================================================================

def score_mock_test(
    answers: List[Dict[str, Any]],
    correct_map: Dict[str, str],
) -> Dict[str, Any]:
    """Score a mock test.

    Scoring rule: correct +1, wrong -0.25, skipped 0.

    Parameters
    ----------
    answers : list of dict
        Each dict has "question_id" and "selected" (option id or None for skip).
    correct_map : dict
        Maps question_id to the correct option id.
    """
    total = len(answers)
    correct_count = 0
    wrong_count = 0
    skipped_count = 0
    score = 0.0

    details: List[Dict[str, Any]] = []
    for a in answers:
        qid = a["question_id"]
        selected = a.get("selected")
        correct_option = correct_map.get(qid)
        if selected is None:
            skipped_count += 1
            details.append({"question_id": qid, "result": "skipped", "points": 0.0})
        elif selected == correct_option:
            correct_count += 1
            score += 1.0
            details.append({"question_id": qid, "result": "correct", "points": 1.0})
        else:
            wrong_count += 1
            score -= 0.25
            details.append({"question_id": qid, "result": "wrong", "points": -0.25})

    accuracy = (correct_count / total * 100) if total > 0 else 0.0

    return {
        "total": total,
        "correct": correct_count,
        "wrong": wrong_count,
        "skipped": skipped_count,
        "score": round(score, 2),
        "max_score": total,
        "accuracy": round(accuracy, 1),
        "details": details,
    }
