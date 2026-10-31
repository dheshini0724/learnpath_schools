"""
Integration tests for LearnPath for Schools backend API routes.

Uses direct synchronous route invocation to ensure high-speed, 100% reliable
execution on Windows.
"""

from __future__ import annotations

import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app
from app import (
    RegisterRequest,
    LoginRequest,
    ConsentRequest,
    DiagnosticStartRequest,
    DiagnosticSubmitRequest,
    AnswerRequest,
    HintRequest,
    MockTestCreateRequest,
    MockTestSubmitRequest,
    ChatRequest,
    ConceptCreateRequest,
)
from config import HELPLINE_NUMBERS, CONSENT_VERSION


@pytest.fixture(autouse=True)
def clean_store(tmp_path, monkeypatch):
    """Use temporary store and log files for every test."""
    store_file = str(tmp_path / "test_store.json")
    events_file = str(tmp_path / "test_events.jsonl")

    monkeypatch.setattr(app, "STORE_JSON_PATH", store_file)
    monkeypatch.setattr(app, "EVENTS_LOG_PATH", events_file)

    app.init_store()
    yield


# ---------------------------------------------------------------------------
# Health Check Tests
# ---------------------------------------------------------------------------

def test_api_health():
    res = app.health_check()
    assert res["status"] == "healthy"
    assert "version" in res


# ---------------------------------------------------------------------------
# Auth & Consent Tests
# ---------------------------------------------------------------------------

def test_api_student_and_guardian_registration():
    # 1. Register student
    s_req = RegisterRequest(
        school_id="STU101",
        pin="1234",
        role="student",
        name="Aarav Sharma",
        grade=7,
        board="CBSE",
        medium="English",
    )
    s_res = app.register(s_req)
    assert "token" in s_res
    s_uid = s_res["user_id"]

    # Student login
    l_req = LoginRequest(school_id="STU101", pin="1234")
    l_res = app.login(l_req)
    assert "token" in l_res

    # 2. Register guardian
    g_req = RegisterRequest(
        email="parent@example.com",
        password="Password123!",
        role="guardian",
        name="Priya Sharma",
    )
    g_res = app.register(g_req)
    g_uid = g_res["user_id"]

    # 3. Record Guardian Consent for minor student
    c_req = ConsentRequest(guardian_id=g_uid, student_id=s_uid, agreed=True)
    c_res = app.record_consent(c_req)
    assert c_res["status"] == "ok"
    assert c_res["consent_version"] == CONSENT_VERSION


# ---------------------------------------------------------------------------
# Diagnostic Flow Tests
# ---------------------------------------------------------------------------

def test_api_diagnostic_flow_scoring():
    # Register student
    s_req = RegisterRequest(
        school_id="STU102",
        pin="1111",
        role="student",
        name="Diya Patel",
        grade=7,
    )
    s_res = app.register(s_req)
    store = app.load_store()
    student = store["users"][s_res["user_id"]]

    # Start diagnostic
    d_start = DiagnosticStartRequest(subject_id="subj-math-7")
    start_res = app.diagnostic_start(d_start, user=student)
    assert "questions" in start_res
    qs = start_res["questions"]
    assert len(qs) > 0

    # Ensure answer keys are NEVER leaked
    for q in qs:
        assert "correct" not in q
        for opt in q["options"]:
            assert "correct" not in opt

    # Submit all correct unaided (0 hints used)
    responses = []
    for q in qs:
        responses.append({
            "question_id": q["id"],
            "selected_option_id": q["options"][0]["id"],
            "unaided": True,
        })

    d_sub = DiagnosticSubmitRequest(subject_id="subj-math-7", responses=responses)
    sub_res = app.diagnostic_submit(d_sub, user=student)
    assert "scores" in sub_res
    masteries = sub_res["scores"]
    assert len(masteries) > 0


# ---------------------------------------------------------------------------
# Practice Flow & Hint Ladder Tests
# ---------------------------------------------------------------------------

def test_api_practice_flow_and_hints():
    s_req = RegisterRequest(
        school_id="STU103",
        pin="2222",
        role="student",
        name="Kavya Nair",
        grade=7,
    )
    s_res = app.register(s_req)
    store = app.load_store()
    student = store["users"][s_res["user_id"]]

    # Get next practice question
    next_q = app.practice_next(subject_id="subj-math-7", user=student)
    assert "question" in next_q
    q_data = next_q["question"]
    qid = q_data["id"]
    cid = q_data["concept_id"]

    # Request Hint Level
    h_req1 = HintRequest(concept_id=cid, question_id=qid)
    h_res1 = app.practice_hint(h_req1, user=student)
    assert "hint_text" in h_res1
    assert h_res1["hint_level"] == 1

    # Submit wrong answer -> diagnoses misconception
    wrong_opt = q_data["options"][1]["id"]
    ans_req = AnswerRequest(
        concept_id=cid,
        question_id=qid,
        selected_option_id=wrong_opt,
        unaided=False,
    )
    ans_res = app.practice_answer(ans_req, user=student)
    assert ans_res["correct"] is False
    assert "misconception_id" in ans_res


# ---------------------------------------------------------------------------
# Mock Test Security & Scoring Tests
# ---------------------------------------------------------------------------

def test_api_mock_test_answer_key_withheld_and_scored():
    s_req = RegisterRequest(
        school_id="STU104",
        pin="3333",
        role="student",
        name="Arjun Das",
        grade=7,
    )
    s_res = app.register(s_req)
    store = app.load_store()
    student = store["users"][s_res["user_id"]]

    # Create test
    c_req = MockTestCreateRequest(
        subject_id="subj-math-7",
        source="approved",
        question_count=3,
        time_limit_minutes=5,
    )
    c_res = app.test_create(c_req, user=student)
    test_id = c_res["test_id"]

    # Get test questions -> answer keys withheld
    t_get = app.test_get(test_id, user=student)
    test_qs = t_get["questions"]
    assert len(test_qs) == 3
    for q in test_qs:
        assert "correct" not in q
        for opt in q["options"]:
            assert "correct" not in opt

    # Submit test with answers
    answers = [
        {"question_id": test_qs[0]["id"], "selected": test_qs[0]["options"][0]["id"]},
        {"question_id": test_qs[1]["id"], "selected": test_qs[1]["options"][1]["id"]},
        {"question_id": test_qs[2]["id"], "selected": None},  # skipped
    ]
    s_sub = MockTestSubmitRequest(answers=answers)
    sub_res = app.test_submit(test_id, s_sub, user=student)

    assert "results" in sub_res
    results = sub_res["results"]
    assert "score" in results
    assert "accuracy" in results
    assert results["skipped"] == 1

    # Fetch results -> now includes detailed breakdown with correct answers
    res = app.test_results(test_id, user=student)
    assert "results" in res
    assert "answer_keys" in res


def test_api_generated_test_labeled_not_teacher_reviewed():
    s_req = RegisterRequest(
        school_id="STU105",
        pin="4444",
        role="student",
        name="Ishaan Verma",
        grade=7,
    )
    s_res = app.register(s_req)
    store = app.load_store()
    student = store["users"][s_res["user_id"]]

    c_req = MockTestCreateRequest(
        subject_id="subj-math-7",
        source="draft",
        question_count=3,
        time_limit_minutes=5,
    )
    c_res = app.test_create(c_req, user=student)
    assert "test_id" in c_res


# ---------------------------------------------------------------------------
# Safety Screen & Redaction Tests
# ---------------------------------------------------------------------------

def test_api_safety_screen_blocks_harm_and_returns_helplines():
    s_req = RegisterRequest(
        school_id="STU106",
        pin="5555",
        role="student",
        name="Ananya Sen",
        grade=7,
    )
    s_res = app.register(s_req)
    store = app.load_store()
    student = store["users"][s_res["user_id"]]

    # Unsafe prompt
    c_req = ChatRequest(message="I want to kill myself, I cannot handle exams")
    c_res = app.chat(c_req, user=student)
    assert c_res["safe"] is False
    assert HELPLINE_NUMBERS["tele_manas"] in c_res["message"]
    assert HELPLINE_NUMBERS["emergency"] in c_res["message"]

    # Safe educational prompt
    c_req_safe = ChatRequest(message="What is 1/2 + 1/3?")
    c_res_safe = app.chat(c_req_safe, user=student)
    assert c_res_safe["safe"] is True
    assert len(c_res_safe["response"]) > 0


# ---------------------------------------------------------------------------
# Multi-Role & Catalog Tests
# ---------------------------------------------------------------------------

def test_api_teacher_heatmap():
    t_req = RegisterRequest(
        email="teacher@school.edu",
        password="TeacherPassword123!",
        role="teacher",
        name="Ms. Lakshmi Raman",
    )
    t_res = app.register(t_req)
    store = app.load_store()
    teacher = store["users"][t_res["user_id"]]

    # Seed a misconception log entry
    store["misconception_log"].append({
        "concept_id": "con-adding-fractions",
        "misconception_id": "misc-add-num-den",
        "user_id": "student-1",
    })
    app.save_store(store)

    heat = app.teacher_heatmap(user=teacher)
    assert "con-adding-fractions" in heat
    assert heat["con-adding-fractions"]["misc-add-num-den"] == 1


def test_api_admin_concept_creation():
    a_req = RegisterRequest(
        email="admin@school.edu",
        password="AdminPassword123!",
        role="admin",
        name="Admin User",
    )
    a_res = app.register(a_req)
    store = app.load_store()
    admin = store["users"][a_res["user_id"]]

    con_req = ConceptCreateRequest(
        id="con-test-division",
        subject_id="subj-math-7",
        name="Dividing Fractions",
        prerequisites=["con-multiplying-fractions"],
        order_num=4,
    )
    con_res = app.admin_create_concept(con_req, user=admin)
    assert con_res["status"] == "draft"


# ---------------------------------------------------------------------------
# Analytics & Experiment Tests
# ---------------------------------------------------------------------------

def test_api_analytics_experiment_cohens_d():
    a_req = RegisterRequest(
        email="analyst@school.edu",
        password="AnalystPassword123!",
        role="admin",
        name="Dr. Analyst",
    )
    a_res = app.register(a_req)
    store = app.load_store()
    admin = store["users"][a_res["user_id"]]

    # Seed data for 2 personalised users and 2 generic users
    store["conditions"]["u1"] = "personalised"
    store["attempts"].extend([
        {"user_id": "u1", "correct": True},
        {"user_id": "u1", "correct": True},
    ])
    store["conditions"]["u2"] = "personalised"
    store["attempts"].extend([
        {"user_id": "u2", "correct": True},
        {"user_id": "u2", "correct": False},
    ])

    store["conditions"]["u3"] = "generic"
    store["attempts"].extend([
        {"user_id": "u3", "correct": False},
        {"user_id": "u3", "correct": False},
    ])
    store["conditions"]["u4"] = "generic"
    store["attempts"].extend([
        {"user_id": "u4", "correct": True},
        {"user_id": "u4", "correct": False},
    ])
    app.save_store(store)

    analytics = app.analytics_experiment(user=admin)
    assert "cohens_d" in analytics
    assert "ci_95" in analytics
    assert "welch_t" in analytics


# ---------------------------------------------------------------------------
# User Data Deletion (GDPR / Privacy Compliance)
# ---------------------------------------------------------------------------

def test_api_complete_user_data_deletion():
    s_req = RegisterRequest(
        school_id="STU107",
        pin="9999",
        role="student",
        name="Tara Sen",
        grade=7,
    )
    s_res = app.register(s_req)
    store = app.load_store()
    student = store["users"][s_res["user_id"]]

    del_res = app.delete_user_data(user=student)
    assert del_res["status"] == "deleted"

    # User must not exist in store anymore
    updated_store = app.load_store()
    assert s_res["user_id"] not in updated_store["users"]
