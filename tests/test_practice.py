"""
Tests for the practice flow: hint ladder state through practice sessions,
misconception detection, recurring mistakes, and the generic condition.
"""

from __future__ import annotations

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import (
    BKT,
    HintLadder,
    HintState,
    RepairCycle,
    GENERIC_HINT_LEVEL,
    check_transfer,
    detect_recurring,
    diagnose_answer,
    get_generic_question,
    select_question,
)


# ---------------------------------------------------------------------------
# Practice session integration tests
# ---------------------------------------------------------------------------

class TestPracticeFlow:
    """Simulate a practice session to verify end-to-end engine logic."""

    def _make_questions(self):
        return [
            {
                "id": "q1", "concept_id": "c1", "difficulty": "medium",
                "is_transfer": False,
                "options": [
                    {"id": "q1-a", "correct": True, "misconception_id": None},
                    {"id": "q1-b", "correct": False, "misconception_id": "misc-1"},
                    {"id": "q1-c", "correct": False, "misconception_id": "gap"},
                    {"id": "q1-d", "correct": False, "misconception_id": "misc-2"},
                ],
                "hints": [
                    {"level": 1, "text": "Hint 1"},
                    {"level": 2, "text": "Hint 2"},
                    {"level": 3, "text": "Hint 3"},
                    {"level": 4, "text": "Hint 4"},
                ],
            },
            {
                "id": "q2", "concept_id": "c1", "difficulty": "medium",
                "is_transfer": False,
                "options": [
                    {"id": "q2-a", "correct": True, "misconception_id": None},
                    {"id": "q2-b", "correct": False, "misconception_id": "misc-1"},
                    {"id": "q2-c", "correct": False, "misconception_id": "misc-2"},
                    {"id": "q2-d", "correct": False, "misconception_id": "gap"},
                ],
                "hints": [
                    {"level": 1, "text": "Hint A"},
                    {"level": 2, "text": "Hint B"},
                    {"level": 3, "text": "Hint C"},
                    {"level": 4, "text": "Hint D"},
                ],
            },
        ]

    def test_wrong_answer_escalates_hint_and_detects_misconception(self):
        questions = self._make_questions()
        state = HintState(level=1)

        # Student picks wrong option q1-b -> misconception misc-1
        mid = diagnose_answer("q1-b", questions[0]["options"])
        assert mid == "misc-1"

        # Hint should escalate
        HintLadder.escalate(state)
        assert state.level == 2

    def test_correct_unaided_updates_mastery(self):
        bkt = BKT()
        p = 0.2

        # Student answers correctly without hints
        p = bkt.update(p, correct=True, unaided=True)
        assert p > 0.2

    def test_correct_with_hint_does_not_raise_mastery_much(self):
        bkt = BKT()
        p = 0.5

        # Correct with hint is treated as wrong
        new_p = bkt.update(p, correct=True, unaided=False)
        assert new_p < p

    def test_full_practice_session_flow(self):
        """Simulate: wrong -> hint escalate -> correct unaided -> correct unaided -> de-escalate."""
        bkt = BKT()
        state = HintState(level=1)
        p = 0.2

        # Round 1: wrong answer
        p = bkt.update(p, correct=False, unaided=True)
        HintLadder.escalate(state)
        assert state.level == 2

        # Round 2: correct with hint (hint was shown)
        p = bkt.update(p, correct=True, unaided=False)
        # Level stays same (no escalation for correct)

        # Round 3: correct unaided
        p_before = p
        p = bkt.update(p, correct=True, unaided=True)
        assert p > p_before
        HintLadder.on_correct_unaided(state)
        assert state.consecutive_unaided_correct == 1

        # Round 4: correct unaided again -> de-escalate
        p = bkt.update(p, correct=True, unaided=True)
        HintLadder.on_correct_unaided(state)
        assert state.level == 1  # de-escalated

    def test_recurring_misconception_triggers_repair(self):
        log = [
            {"concept_id": "c1", "misconception_id": "misc-1"},
            {"concept_id": "c1", "misconception_id": "misc-1"},
        ]
        recurring = detect_recurring(log, "c1")
        assert "misc-1" in recurring

        # Start repair cycle
        rc = RepairCycle(misconception_id="misc-1", concept_id="c1")
        assert rc.stage == "contrasting_example"

        # Start hint at level 3 for recurring
        state = HintLadder.for_recurring_misconception()
        assert state.level == 3

    def test_transfer_after_mastery(self):
        result = check_transfer(correct=True, unaided=True, mastery=0.95)
        assert result["mastered"] is True

    def test_transfer_fail_returns_to_diagnosis(self):
        result = check_transfer(correct=False, unaided=True, mastery=0.95)
        assert result["action"] == "re_diagnose"


# ---------------------------------------------------------------------------
# Generic condition tests (never calls adaptive engine)
# ---------------------------------------------------------------------------

class TestGenericPractice:

    def test_generic_uses_fixed_hint_level(self):
        assert GENERIC_HINT_LEVEL == 2

    def test_generic_fixed_sequence(self):
        qs = [
            {"id": "q1", "concept_id": "c1", "is_transfer": False},
            {"id": "q2", "concept_id": "c1", "is_transfer": False},
        ]
        q0 = get_generic_question(qs, 0)
        q1 = get_generic_question(qs, 1)
        assert q0["id"] == "q1"
        assert q1["id"] == "q2"

    def test_generic_no_transfer_questions(self):
        qs = [
            {"id": "q1", "concept_id": "c1", "is_transfer": True},
            {"id": "q2", "concept_id": "c1", "is_transfer": False},
        ]
        q = get_generic_question(qs, 0)
        assert q["is_transfer"] is False


# ---------------------------------------------------------------------------
# Question selection edge cases
# ---------------------------------------------------------------------------

class TestQuestionEdgeCases:

    def test_all_seen_resets_pool(self):
        qs = [
            {"id": "q1", "concept_id": "c1", "difficulty": "medium", "is_transfer": False},
        ]
        seen = {"q1"}
        q = select_question("c1", qs, seen, mastery=0.3)
        assert q is not None  # should still return something

    def test_empty_pool_returns_none(self):
        q = select_question("c1", [], set(), mastery=0.3)
        assert q is None
