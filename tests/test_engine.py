"""
Comprehensive unit tests for the adaptive learning engine.

Tests all engine modules: BKT, diagnostic scoring, concept selection,
question selection, hint ladder, misconception diagnosis, repair cycle,
spaced review, transfer check, generic condition, and mock-test scoring.
"""

from __future__ import annotations

import sys
import os
from datetime import datetime, timedelta

import pytest

# Ensure the project root is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import (
    BKT,
    BKTParams,
    HintLadder,
    HintState,
    RepairCycle,
    GENERIC_HINT_LEVEL,
    SPACED_REVIEW_INTERVALS,
    check_transfer,
    detect_recurring,
    diagnose_answer,
    get_generic_question,
    get_spaced_review_concepts,
    run_diagnostic,
    score_diagnostic,
    score_mock_test,
    select_next_concept,
    select_question,
    select_transfer_question,
)


# ---------------------------------------------------------------------------
# BKT Tests
# ---------------------------------------------------------------------------

class TestBKT:

    def test_default_params(self):
        params = BKTParams()
        assert params.p_init == 0.2
        assert params.p_transit == 0.1
        assert params.p_slip == 0.1
        assert params.p_guess == 0.2
        assert params.mastery_threshold == 0.9

    def test_correct_unaided_raises_mastery(self):
        bkt = BKT()
        p = 0.2
        new_p = bkt.update(p, correct=True, unaided=True)
        assert new_p > p

    def test_wrong_answer_lowers_mastery(self):
        bkt = BKT()
        p = 0.5
        new_p = bkt.update(p, correct=False, unaided=True)
        assert new_p < p

    def test_correct_with_hint_treated_as_wrong(self):
        bkt = BKT()
        p = 0.5
        # Correct with hint should be treated as incorrect for mastery
        new_p_hinted = bkt.update(p, correct=True, unaided=False)
        new_p_wrong = bkt.update(p, correct=False, unaided=True)
        assert new_p_hinted == new_p_wrong

    def test_mastery_stays_in_0_1(self):
        bkt = BKT()
        p = 0.0
        for _ in range(100):
            p = bkt.update(p, correct=True, unaided=True)
        assert 0.0 <= p <= 1.0

        p = 1.0
        for _ in range(100):
            p = bkt.update(p, correct=False, unaided=True)
        assert 0.0 <= p <= 1.0

    def test_repeated_correct_approaches_mastery(self):
        bkt = BKT()
        p = 0.2
        for _ in range(20):
            p = bkt.update(p, correct=True, unaided=True)
        assert p >= 0.9

    def test_is_mastered(self):
        bkt = BKT()
        assert bkt.is_mastered(0.95) is True
        assert bkt.is_mastered(0.9) is True
        assert bkt.is_mastered(0.89) is False
        assert bkt.is_mastered(0.0) is False


# ---------------------------------------------------------------------------
# Diagnostic Tests
# ---------------------------------------------------------------------------

class TestDiagnostic:

    def test_all_correct(self):
        assert score_diagnostic(5, 5) == 0.8

    def test_none_correct(self):
        assert score_diagnostic(0, 5) == 0.2

    def test_partial_correct(self):
        assert score_diagnostic(3, 5) == 0.5

    def test_zero_total(self):
        assert score_diagnostic(0, 0) == 0.2

    def test_run_diagnostic_all_correct(self):
        responses = [
            {"concept_id": "c1", "correct": True, "unaided": True},
            {"concept_id": "c1", "correct": True, "unaided": True},
        ]
        scores = run_diagnostic(responses, ["c1"])
        assert scores["c1"] == 0.8

    def test_run_diagnostic_none_correct(self):
        responses = [
            {"concept_id": "c1", "correct": False, "unaided": True},
            {"concept_id": "c1", "correct": False, "unaided": True},
        ]
        scores = run_diagnostic(responses, ["c1"])
        assert scores["c1"] == 0.2

    def test_run_diagnostic_mixed(self):
        responses = [
            {"concept_id": "c1", "correct": True, "unaided": True},
            {"concept_id": "c1", "correct": False, "unaided": True},
        ]
        scores = run_diagnostic(responses, ["c1"])
        assert scores["c1"] == 0.5

    def test_run_diagnostic_hinted_correct_not_counted(self):
        """Correct with hint should not count as unaided correct."""
        responses = [
            {"concept_id": "c1", "correct": True, "unaided": False},
            {"concept_id": "c1", "correct": True, "unaided": False},
        ]
        scores = run_diagnostic(responses, ["c1"])
        assert scores["c1"] == 0.2  # none unaided

    def test_run_diagnostic_multiple_concepts(self):
        responses = [
            {"concept_id": "c1", "correct": True, "unaided": True},
            {"concept_id": "c1", "correct": True, "unaided": True},
            {"concept_id": "c2", "correct": False, "unaided": True},
        ]
        scores = run_diagnostic(responses, ["c1", "c2"])
        assert scores["c1"] == 0.8
        assert scores["c2"] == 0.2

    def test_missing_concept_gets_default(self):
        scores = run_diagnostic([], ["c1"])
        assert scores["c1"] == 0.2


# ---------------------------------------------------------------------------
# Concept Selection Tests
# ---------------------------------------------------------------------------

class TestConceptSelection:

    def test_selects_lowest_mastery(self):
        masteries = {"c1": 0.3, "c2": 0.1, "c3": 0.95}
        prereqs = {"c1": [], "c2": [], "c3": []}
        assert select_next_concept(masteries, prereqs) == "c2"

    def test_respects_prerequisites(self):
        masteries = {"c1": 0.95, "c2": 0.3, "c3": 0.1}
        prereqs = {"c1": [], "c2": ["c1"], "c3": ["c2"]}
        # c3 depends on c2 which is not mastered
        assert select_next_concept(masteries, prereqs) == "c2"

    def test_all_mastered_returns_none(self):
        masteries = {"c1": 0.95, "c2": 0.95}
        prereqs = {"c1": [], "c2": ["c1"]}
        assert select_next_concept(masteries, prereqs) is None

    def test_prereq_not_met_excluded(self):
        masteries = {"c1": 0.3, "c2": 0.1}
        prereqs = {"c1": [], "c2": ["c1"]}
        # c2 needs c1 >= 0.9, c1 is 0.3
        assert select_next_concept(masteries, prereqs) == "c1"

    def test_empty_input(self):
        assert select_next_concept({}, {}) is None


# ---------------------------------------------------------------------------
# Spaced Review Tests
# ---------------------------------------------------------------------------

class TestSpacedReview:

    def test_intervals(self):
        assert SPACED_REVIEW_INTERVALS == [1, 3, 7, 21]

    def test_due_concept_returned(self):
        now = datetime(2025, 1, 10)
        masteries = {"c1": 0.95}
        mastery_dates = {"c1": datetime(2025, 1, 8)}  # 2 days ago
        review_counts = {"c1": 0}  # first review at 1 day
        due = get_spaced_review_concepts(masteries, mastery_dates, review_counts, now=now)
        assert "c1" in due

    def test_not_due_yet(self):
        now = datetime(2025, 1, 9, 0, 0)
        masteries = {"c1": 0.95}
        mastery_dates = {"c1": datetime(2025, 1, 9, 0, 0)}  # just mastered
        review_counts = {"c1": 0}
        due = get_spaced_review_concepts(masteries, mastery_dates, review_counts, now=now)
        assert "c1" not in due

    def test_unmastered_not_reviewed(self):
        now = datetime(2025, 1, 20)
        masteries = {"c1": 0.5}
        mastery_dates = {"c1": datetime(2025, 1, 1)}
        review_counts = {"c1": 0}
        due = get_spaced_review_concepts(masteries, mastery_dates, review_counts, now=now)
        assert "c1" not in due


# ---------------------------------------------------------------------------
# Question Selection Tests
# ---------------------------------------------------------------------------

class TestQuestionSelection:

    def _make_questions(self):
        return [
            {"id": "q1", "concept_id": "c1", "difficulty": "medium", "is_transfer": False},
            {"id": "q2", "concept_id": "c1", "difficulty": "hard", "is_transfer": False},
            {"id": "q3", "concept_id": "c1", "difficulty": "medium", "is_transfer": True},
            {"id": "q4", "concept_id": "c2", "difficulty": "medium", "is_transfer": False},
        ]

    def test_selects_from_concept(self):
        qs = self._make_questions()
        q = select_question("c1", qs, set(), mastery=0.3)
        assert q is not None
        assert q["concept_id"] == "c1"

    def test_prefers_unseen(self):
        qs = self._make_questions()
        seen = {"q1"}
        q = select_question("c1", qs, seen, mastery=0.3)
        # Should pick q2 (unseen, non-transfer)
        assert q["id"] == "q2"

    def test_excludes_transfer_by_default(self):
        qs = self._make_questions()
        for _ in range(20):
            q = select_question("c1", qs, set(), mastery=0.3)
            assert not q.get("is_transfer", False)

    def test_includes_transfer_when_requested(self):
        qs = [
            {"id": "q3", "concept_id": "c1", "difficulty": "medium", "is_transfer": True},
        ]
        q = select_question("c1", qs, set(), mastery=0.3, include_transfer=True)
        assert q is not None
        assert q["is_transfer"] is True

    def test_returns_none_for_no_questions(self):
        assert select_question("c99", [], set(), mastery=0.3) is None

    def test_select_transfer_question(self):
        qs = self._make_questions()
        q = select_transfer_question("c1", qs)
        assert q is not None
        assert q["is_transfer"] is True

    def test_prefers_hard_for_strong_students(self):
        qs = self._make_questions()
        hard_count = 0
        for _ in range(50):
            q = select_question("c1", qs, set(), mastery=0.8)
            if q["difficulty"] == "hard":
                hard_count += 1
        # Should prefer hard questions for strong students
        assert hard_count > 25


# ---------------------------------------------------------------------------
# Hint Ladder Tests
# ---------------------------------------------------------------------------

class TestHintLadder:

    def test_initial_state(self):
        state = HintState()
        assert state.level == 1
        assert state.consecutive_unaided_correct == 0

    def test_escalate(self):
        state = HintState(level=1)
        HintLadder.escalate(state)
        assert state.level == 2

    def test_escalate_capped_at_4(self):
        state = HintState(level=4)
        HintLadder.escalate(state)
        assert state.level == 4

    def test_de_escalate_after_two_correct(self):
        state = HintState(level=3)
        HintLadder.on_correct_unaided(state)
        assert state.level == 3  # first correct, no change
        HintLadder.on_correct_unaided(state)
        assert state.level == 2  # second correct, de-escalate

    def test_de_escalate_not_below_1(self):
        state = HintState(level=1)
        HintLadder.on_correct_unaided(state)
        HintLadder.on_correct_unaided(state)
        assert state.level == 1

    def test_recurring_misconception_starts_at_3(self):
        state = HintLadder.for_recurring_misconception()
        assert state.level == 3

    def test_escalate_resets_consecutive_count(self):
        state = HintState(level=2, consecutive_unaided_correct=1)
        HintLadder.escalate(state)
        assert state.consecutive_unaided_correct == 0

    def test_get_hint_text(self):
        hints = [
            {"level": 1, "text": "Think about it"},
            {"level": 2, "text": "Here is an explanation"},
            {"level": 3, "text": "Worked example"},
            {"level": 4, "text": "Step by step"},
        ]
        assert HintLadder.get_hint_text(hints, 1) == "Think about it"
        assert HintLadder.get_hint_text(hints, 4) == "Step by step"
        assert "Hint level 5" in HintLadder.get_hint_text(hints, 5)


# ---------------------------------------------------------------------------
# Misconception Diagnosis Tests
# ---------------------------------------------------------------------------

class TestMisconception:

    def _make_options(self):
        return [
            {"id": "a", "correct": True, "misconception_id": None},
            {"id": "b", "correct": False, "misconception_id": "misc-1"},
            {"id": "c", "correct": False, "misconception_id": "gap"},
            {"id": "d", "correct": False, "misconception_id": "misc-2"},
        ]

    def test_correct_returns_none(self):
        opts = self._make_options()
        assert diagnose_answer("a", opts) is None

    def test_wrong_returns_misconception(self):
        opts = self._make_options()
        assert diagnose_answer("b", opts) == "misc-1"

    def test_gap_returned(self):
        opts = self._make_options()
        assert diagnose_answer("c", opts) == "gap"

    def test_unknown_option(self):
        opts = self._make_options()
        assert diagnose_answer("z", opts) is None

    def test_detect_recurring(self):
        log = [
            {"concept_id": "c1", "misconception_id": "misc-1"},
            {"concept_id": "c1", "misconception_id": "misc-1"},
            {"concept_id": "c1", "misconception_id": "misc-2"},
            {"concept_id": "c2", "misconception_id": "misc-1"},
        ]
        recurring = detect_recurring(log, "c1")
        assert "misc-1" in recurring
        assert "misc-2" not in recurring

    def test_detect_recurring_ignores_gap(self):
        log = [
            {"concept_id": "c1", "misconception_id": "gap"},
            {"concept_id": "c1", "misconception_id": "gap"},
        ]
        recurring = detect_recurring(log, "c1")
        assert len(recurring) == 0


# ---------------------------------------------------------------------------
# Repair Cycle Tests
# ---------------------------------------------------------------------------

class TestRepairCycle:

    def test_initial_stage(self):
        rc = RepairCycle(misconception_id="m1", concept_id="c1")
        assert rc.stage == "contrasting_example"

    def test_advance_to_practice(self):
        rc = RepairCycle(misconception_id="m1", concept_id="c1")
        rc.advance(correct=True)
        assert rc.stage == "practice"

    def test_advance_to_check(self):
        rc = RepairCycle(misconception_id="m1", concept_id="c1")
        rc.advance(correct=True)  # -> practice
        rc.advance(correct=True)  # practice 1
        rc.advance(correct=True)  # practice 2 -> check
        assert rc.stage == "check"

    def test_advance_past_check(self):
        rc = RepairCycle(misconception_id="m1", concept_id="c1")
        rc.advance(True)  # -> practice
        rc.advance(True)  # practice 1
        rc.advance(True)  # practice 2 -> check
        result = rc.advance(True)  # -> done
        assert result == "done"


# ---------------------------------------------------------------------------
# Transfer Check Tests
# ---------------------------------------------------------------------------

class TestTransferCheck:

    def test_pass_with_mastery(self):
        result = check_transfer(correct=True, unaided=True, mastery=0.95)
        assert result["passed"] is True
        assert result["mastered"] is True
        assert result["action"] == "mastered"

    def test_pass_without_mastery(self):
        result = check_transfer(correct=True, unaided=True, mastery=0.7)
        assert result["passed"] is True
        assert result["mastered"] is False
        assert result["action"] == "continue"

    def test_fail_returns_to_diagnosis(self):
        result = check_transfer(correct=False, unaided=True, mastery=0.95)
        assert result["passed"] is False
        assert result["action"] == "re_diagnose"

    def test_hinted_correct_fails(self):
        result = check_transfer(correct=True, unaided=False, mastery=0.95)
        assert result["passed"] is False
        assert result["action"] == "re_diagnose"


# ---------------------------------------------------------------------------
# Generic Condition Tests
# ---------------------------------------------------------------------------

class TestGenericCondition:

    def test_hint_level_is_2(self):
        assert GENERIC_HINT_LEVEL == 2

    def test_get_generic_question(self):
        qs = [
            {"id": "q1", "concept_id": "c1", "is_transfer": False},
            {"id": "q2", "concept_id": "c1", "is_transfer": False},
            {"id": "q3", "concept_id": "c1", "is_transfer": True},
        ]
        q = get_generic_question(qs, 0)
        assert q is not None
        assert q["id"] == "q1"

    def test_generic_skips_transfer(self):
        qs = [
            {"id": "q1", "concept_id": "c1", "is_transfer": True},
            {"id": "q2", "concept_id": "c1", "is_transfer": False},
        ]
        q = get_generic_question(qs, 0)
        assert q["id"] == "q2"

    def test_generic_out_of_range(self):
        qs = [{"id": "q1", "concept_id": "c1", "is_transfer": False}]
        assert get_generic_question(qs, 5) is None


# ---------------------------------------------------------------------------
# Mock-Test Scoring Tests
# ---------------------------------------------------------------------------

class TestMockTestScoring:

    def test_all_correct(self):
        answers = [
            {"question_id": "q1", "selected": "a"},
            {"question_id": "q2", "selected": "b"},
        ]
        correct_map = {"q1": "a", "q2": "b"}
        result = score_mock_test(answers, correct_map)
        assert result["correct"] == 2
        assert result["wrong"] == 0
        assert result["skipped"] == 0
        assert result["score"] == 2.0

    def test_all_wrong(self):
        answers = [
            {"question_id": "q1", "selected": "b"},
            {"question_id": "q2", "selected": "a"},
        ]
        correct_map = {"q1": "a", "q2": "b"}
        result = score_mock_test(answers, correct_map)
        assert result["correct"] == 0
        assert result["wrong"] == 2
        assert result["score"] == -0.5

    def test_skipped(self):
        answers = [
            {"question_id": "q1", "selected": None},
        ]
        correct_map = {"q1": "a"}
        result = score_mock_test(answers, correct_map)
        assert result["skipped"] == 1
        assert result["score"] == 0.0

    def test_mixed(self):
        answers = [
            {"question_id": "q1", "selected": "a"},  # correct +1
            {"question_id": "q2", "selected": "a"},  # wrong -0.25
            {"question_id": "q3", "selected": None},  # skipped 0
        ]
        correct_map = {"q1": "a", "q2": "b", "q3": "c"}
        result = score_mock_test(answers, correct_map)
        assert result["correct"] == 1
        assert result["wrong"] == 1
        assert result["skipped"] == 1
        assert result["score"] == 0.75
        assert result["accuracy"] == pytest.approx(33.3, abs=0.1)

    def test_scoring_details(self):
        answers = [
            {"question_id": "q1", "selected": "a"},
        ]
        correct_map = {"q1": "a"}
        result = score_mock_test(answers, correct_map)
        assert len(result["details"]) == 1
        assert result["details"][0]["result"] == "correct"
        assert result["details"][0]["points"] == 1.0
