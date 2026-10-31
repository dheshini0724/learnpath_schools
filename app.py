# -*- coding: utf-8 -*-
"""
LearnPath for Schools -- FastAPI backend.

Single-file application that provides:
  - JSON-file storage (store.json) and append-only event log (events.jsonl)
  - JWT-based auth with bcrypt password hashing (graceful fallback)
  - Guardian consent workflow
  - Onboarding (students, guardians, teachers, admins)
  - Content loading and validation from content/*.json
  - Diagnostic, practice, hint, transfer, and mock-test flows
  - Ask-Anything chat with safety screen, PII redaction, and mock LLM
  - Library vault
  - Guardian and teacher views
  - Admin CRUD for content catalog
  - Analytics (Cohen's d, Welch's t-test)
  - Data deletion

All adaptive decisions (mastery, next concept, next question, hint level) are
made by the engine -- the LLM is NEVER used for those.
"""
from __future__ import annotations

import glob
import json
import math
import os
import re
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, Depends, HTTPException, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── Engine imports (same directory) ──────────────────────────────────────────
from engine import (
    BKT,
    BKTParams,
    score_diagnostic,
    run_diagnostic,
    select_next_concept,
    get_spaced_review_concepts,
    SPACED_REVIEW_INTERVALS,
    select_question,
    select_transfer_question,
    HintState,
    HintLadder,
    diagnose_answer,
    detect_recurring,
    RepairCycle,
    check_transfer,
    GENERIC_HINT_LEVEL,
    get_generic_question,
    score_mock_test,
)

# ── Config imports (same directory) ──────────────────────────────────────────
from config import (
    PRODUCT_NAME,
    PRODUCT_VERSION,
    MIN_CONSENT_AGE,
    CONSENT_VERSION,
    BOARDS,
    MEDIUMS,
    GRADES,
    SCHOOL_NAMES,
    HELPLINE_NUMBERS,
    LLM_MODEL_NAME,
    LLM_API_KEY_ENV,
    LLM_MAX_TOKENS,
    BKT_P_INIT,
    BKT_SLIP,
    BKT_GUESS,
    BKT_TRANSIT,
    BKT_MASTERY_THRESHOLD,
    DIAGNOSTIC_MIN_ITEMS,
    DIAGNOSTIC_MAX_ITEMS,
    DIAGNOSTIC_ALL_CORRECT,
    DIAGNOSTIC_PARTIAL,
    DIAGNOSTIC_NONE_CORRECT,
    SCORING_CORRECT,
    SCORING_WRONG,
    SCORING_SKIPPED,
    HINT_MAX_LEVEL,
    RECURRING_MISCONCEPTION_START_LEVEL,
    MAX_REFERENCE_OVERLAP,
    HINT_LINE_LIMITS,
    READING_LEVELS,
    DATABASE_URL,
    STORE_JSON_PATH,
    EVENTS_LOG_PATH,
    SAFETY_CATEGORIES,
    SAFETY_MESSAGE_TEMPLATE,
)

# ── Optional dependencies with fallbacks ─────────────────────────────────────
try:
    import bcrypt  # type: ignore

    def hash_password(password: str) -> str:
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    def verify_password(password: str, hashed: str) -> bool:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

except ImportError:
    import hashlib

    def hash_password(password: str) -> str:  # type: ignore[misc]
        return hashlib.sha256(password.encode("utf-8")).hexdigest()

    def verify_password(password: str, hashed: str) -> bool:  # type: ignore[misc]
        return hashlib.sha256(password.encode("utf-8")).hexdigest() == hashed


try:
    import jwt as pyjwt  # type: ignore

    _HAS_JWT = True
except ImportError:
    import base64 as _b64

    _HAS_JWT = False


JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-secret-change-me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24


def create_token(payload: Dict[str, Any]) -> str:
    """Create a JWT (or base64-fallback) token."""
    payload["exp"] = time.time() + JWT_EXPIRY_HOURS * 3600
    if _HAS_JWT:
        return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)
    # Fallback: base64-encoded JSON (NOT secure -- dev only)
    return _b64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and validate a JWT (or base64-fallback) token."""
    try:
        if _HAS_JWT:
            return pyjwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        raw = json.loads(_b64.urlsafe_b64decode(token.encode()).decode())
        if raw.get("exp", 0) < time.time():
            raise HTTPException(status_code=401, detail="Token expired")
        return raw
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")


# ============================================================================
# Storage helpers
# ============================================================================

_EMPTY_STORE: Dict[str, Any] = {
    "users": {},
    "students": {},
    "guardian_links": {},
    "consent_records": {},
    "masteries": {},
    "attempts": [],
    "mock_tests": {},
    "chat_history": {},
    "hint_states": {},
    "misconception_log": [],
    "seen_questions": {},
    "review_counts": {},
    "mastery_dates": {},
    "conditions": {},
}


def load_store() -> Dict[str, Any]:
    """Read store.json and return dict.  Create empty store if missing."""
    if not os.path.exists(STORE_JSON_PATH):
        save_store(dict(_EMPTY_STORE))
        return dict(_EMPTY_STORE)
    with open(STORE_JSON_PATH, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # Ensure all keys present
    for key, default in _EMPTY_STORE.items():
        if key not in data:
            data[key] = type(default)()
    return data


def save_store(data: Dict[str, Any]) -> None:
    """Write dict to store.json."""
    with open(STORE_JSON_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


def log_event(event_type: str, data: Dict[str, Any]) -> None:
    """Append a single event to events.jsonl."""
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "event": event_type,
        "data": data,
    }
    with open(EVENTS_LOG_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, default=str) + "\n")


# ============================================================================
# PII redaction
# ============================================================================

_PII_PATTERNS = [
    (re.compile(r"\b\d{10}\b"), "[REDACTED]"),                # 10-digit phone
    (re.compile(r"\b\d{12}\b"), "[REDACTED]"),                # 12-digit Aadhaar
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[REDACTED]"),  # email
]


def redact_pii(text: str) -> str:
    """Replace phone numbers, email addresses, and Aadhaar patterns."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


# ============================================================================
# Safety screen
# ============================================================================

def safety_screen(text: str) -> Optional[Dict[str, Any]]:
    """Check text against SAFETY_CATEGORIES.

    Returns a dict with category and message if unsafe, else None.
    """
    lower = text.lower()
    for category, keywords in SAFETY_CATEGORIES.items():
        for kw in keywords:
            if kw in lower:
                message = SAFETY_MESSAGE_TEMPLATE.format(**HELPLINE_NUMBERS)
                return {
                    "is_safe": False,
                    "category": category,
                    "message": message,
                    "helpline_numbers": HELPLINE_NUMBERS,
                }
    return None


# ============================================================================
# LLM adapter (mock by default)
# ============================================================================

class MockLLMProvider:
    """Returns canned educational responses (no real API call)."""

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = 512,
    ) -> str:
        lower = user_message.lower()
        if "hint" in lower or "help" in lower:
            return (
                "Here is a helpful hint: try breaking the problem into "
                "smaller steps. First, identify what you already know, "
                "then work through each part one at a time."
            )
        if "explain" in lower or "wrong" in lower or "why" in lower:
            return (
                "Great question! Let me explain: the key idea here is to "
                "apply the concept step by step. Review the worked example "
                "in your hints for a similar problem."
            )
        return (
            "That is a good question! In this topic, the important thing "
            "to remember is to follow the method carefully. Practice more "
            "problems and you will get the hang of it."
        )


class LLMAdapter:
    """Adapter for LLM calls.  Uses MockLLMProvider by default."""

    def __init__(self, provider: Any = None):
        self.provider = provider or MockLLMProvider()

    def complete(
        self,
        system_prompt: str,
        user_message: str,
        max_tokens: int = LLM_MAX_TOKENS,
    ) -> str:
        return self.provider.complete(system_prompt, user_message, max_tokens)


llm = LLMAdapter()

# ============================================================================
# BKT instance
# ============================================================================

bkt = BKT(BKTParams(
    p_init=BKT_P_INIT,
    p_transit=BKT_TRANSIT,
    p_slip=BKT_SLIP,
    p_guess=BKT_GUESS,
    mastery_threshold=BKT_MASTERY_THRESHOLD,
))

# ============================================================================
# Content catalog (loaded on startup)
# ============================================================================

SUBJECTS: Dict[str, Dict[str, Any]] = {}
CONCEPTS: Dict[str, Dict[str, Any]] = {}
QUESTIONS: Dict[str, Dict[str, Any]] = {}
MISCONCEPTIONS: Dict[str, Dict[str, Any]] = {}
LIBRARY_RESOURCES: Dict[str, Dict[str, Any]] = {}
PREREQUISITES: Dict[str, List[str]] = {}


def _validate_question(q: Dict[str, Any]) -> List[str]:
    """Return list of validation errors for a question."""
    errors: List[str] = []
    if not q.get("concept_id"):
        errors.append(f"Question {q.get('id', '?')} has no concept_id")
    for opt in q.get("options", []):
        if not opt.get("correct", False):
            mid = opt.get("misconception_id")
            if not mid:
                errors.append(
                    f"Question {q.get('id', '?')} option {opt.get('id', '?')} "
                    f"has no misconception_id"
                )
    return errors


def load_content() -> None:
    """Load all content/*.json files and the library."""
    content_dir = Path(__file__).parent / "content"
    if not content_dir.exists():
        return

    # Load subject/concept/question files
    for filepath in sorted(content_dir.glob("grade*.json")):
        with open(filepath, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        subj = data.get("subject")
        if subj:
            SUBJECTS[subj["id"]] = subj
        for c in data.get("concepts", []):
            CONCEPTS[c["id"]] = c
            PREREQUISITES[c["id"]] = c.get("prerequisites", [])
        for m in data.get("misconceptions", []):
            MISCONCEPTIONS[m["id"]] = m
        for q in data.get("questions", []):
            QUESTIONS[q["id"]] = q
            # Validate
            errs = _validate_question(q)
            if errs and q.get("status") == "approved":
                for e in errs:
                    print(f"[content-warn] {e}")

    # Load library
    lib_path = content_dir / "library.json"
    if lib_path.exists():
        with open(lib_path, "r", encoding="utf-8") as fh:
            lib_data = json.load(fh)
        for r in lib_data.get("resources", []):
            LIBRARY_RESOURCES[r["id"]] = r


# ============================================================================
# FastAPI app
# ============================================================================

app = FastAPI(
    title=PRODUCT_NAME,
    version=PRODUCT_VERSION,
    docs_url="/docs",
)


def init_store() -> None:
    """Initialize store.json and load content."""
    save_store(dict(_EMPTY_STORE))
    load_content()


@app.on_event("startup")
def startup():
    """Load content on startup."""
    init_store()


# ── Static files ─────────────────────────────────────────────────────────────
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def serve_index():
    """Serve the SPA index page."""
    index = static_dir / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return JSONResponse({"message": f"{PRODUCT_NAME} API v{PRODUCT_VERSION}"})


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "product": PRODUCT_NAME, "version": PRODUCT_VERSION}


# ============================================================================
# Auth dependency
# ============================================================================

def get_current_user(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Extract and validate the current user from the Authorization header."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    payload = decode_token(parts[1])
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")
    store = load_store()
    user = store["users"].get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_role(*roles: str):
    """Return a dependency that checks the user has one of the specified roles."""
    def checker(user: Dict[str, Any] = Depends(get_current_user)):
        if user.get("role") not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Requires one of roles: {', '.join(roles)}",
            )
        return user
    return checker


# ============================================================================
# Pydantic models
# ============================================================================

class RegisterRequest(BaseModel):
    name: str
    role: str = "student"
    grade: Optional[int] = None
    medium: Optional[str] = None
    board: Optional[str] = None
    school_id: Optional[str] = None
    pin: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class LoginRequest(BaseModel):
    school_id: Optional[str] = None
    pin: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None


class OnboardRequest(BaseModel):
    name: str
    grade: int
    medium: str
    board: str
    role: str = "student"
    school_id: Optional[str] = None
    pin: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    linked_student_ids: Optional[List[str]] = None


class ConsentRequest(BaseModel):
    guardian_id: str
    student_id: str
    agreed: bool = True


class DiagnosticStartRequest(BaseModel):
    subject_id: str


class DiagnosticSubmitRequest(BaseModel):
    subject_id: str
    responses: List[Dict[str, Any]]


class AnswerRequest(BaseModel):
    question_id: str
    selected_option_id: str
    concept_id: str
    unaided: bool = True


class HintRequest(BaseModel):
    concept_id: str
    question_id: str


class TransferRequest(BaseModel):
    concept_id: str
    question_id: str
    selected_option_id: str


class MockTestCreateRequest(BaseModel):
    subject_id: str
    source: str = "approved"
    question_count: int = 10
    time_limit_minutes: int = 30


class MockTestSubmitRequest(BaseModel):
    answers: List[Dict[str, Any]]


class ChatRequest(BaseModel):
    message: str
    subject_id: Optional[str] = None


class LibraryUploadRequest(BaseModel):
    title: str
    type: str = "text"
    pages: int = 1
    grade: int = 7
    subject_id: str = ""
    description: str = ""


class ApproveRequest(BaseModel):
    pass  # no body needed


class DifficultyOverrideRequest(BaseModel):
    question_id: str
    difficulty: str


class ConceptCreateRequest(BaseModel):
    name: str
    subject_id: str
    prerequisites: List[str] = Field(default_factory=list)
    order_num: int = 1


class QuestionCreateRequest(BaseModel):
    concept_id: str
    stem: str
    options: List[Dict[str, Any]]
    difficulty: str = "medium"
    is_diagnostic: bool = False
    is_transfer: bool = False
    hints: List[Dict[str, Any]] = Field(default_factory=list)


class HintCreateRequest(BaseModel):
    question_id: str
    level: int
    text: str


class MisconceptionCreateRequest(BaseModel):
    concept_id: str
    description: str


# ============================================================================
# Auth endpoints
# ============================================================================

@app.post("/api/auth/register")
def register(req: RegisterRequest):
    """Register a new user."""
    store = load_store()
    user_id = str(uuid.uuid4())

    if req.role == "student":
        if not req.school_id or not req.pin:
            raise HTTPException(status_code=400, detail="Students require school_id and pin")
        if len(req.pin) != 4 or not req.pin.isdigit():
            raise HTTPException(status_code=400, detail="PIN must be exactly 4 digits")
        # Check duplicate school_id
        for u in store["users"].values():
            if u.get("school_id") == req.school_id:
                raise HTTPException(status_code=409, detail="school_id already registered")
        hashed = hash_password(req.pin)
        user = {
            "id": user_id,
            "name": req.name,
            "role": "student",
            "school_id": req.school_id,
            "pin_hash": hashed,
            "grade": req.grade,
            "medium": req.medium,
            "board": req.board,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }
    else:
        if not req.email or not req.password:
            raise HTTPException(
                status_code=400,
                detail="Non-student roles require email and password",
            )
        # Check duplicate email
        for u in store["users"].values():
            if u.get("email") == req.email:
                raise HTTPException(status_code=409, detail="Email already registered")
        hashed = hash_password(req.password)
        user = {
            "id": user_id,
            "name": req.name,
            "role": req.role,
            "email": req.email,
            "password_hash": hashed,
            "grade": req.grade,
            "medium": req.medium,
            "board": req.board,
            "created_at": datetime.utcnow().isoformat() + "Z",
        }

    store["users"][user_id] = user
    save_store(store)
    log_event("user_registered", {"user_id": user_id, "role": req.role})

    token = create_token({"sub": user_id, "role": user["role"]})
    return {"user_id": user_id, "token": token}


@app.post("/api/auth/login")
def login(req: LoginRequest):
    """Login and return a JWT token."""
    store = load_store()

    if req.school_id and req.pin:
        # Student login
        for u in store["users"].values():
            if u.get("school_id") == req.school_id:
                if verify_password(req.pin, u.get("pin_hash", "")):
                    token = create_token({"sub": u["id"], "role": u["role"]})
                    log_event("login", {"user_id": u["id"], "method": "school_id"})
                    return {"user_id": u["id"], "token": token, "role": u["role"]}
                raise HTTPException(status_code=401, detail="Invalid PIN")
        raise HTTPException(status_code=404, detail="School ID not found")

    if req.email and req.password:
        # Staff / guardian login
        for u in store["users"].values():
            if u.get("email") == req.email:
                if verify_password(req.password, u.get("password_hash", "")):
                    token = create_token({"sub": u["id"], "role": u["role"]})
                    log_event("login", {"user_id": u["id"], "method": "email"})
                    return {"user_id": u["id"], "token": token, "role": u["role"]}
                raise HTTPException(status_code=401, detail="Invalid password")
        raise HTTPException(status_code=404, detail="Email not found")

    raise HTTPException(status_code=400, detail="Provide school_id+pin or email+password")


@app.get("/api/auth/me")
def auth_me(user: Dict[str, Any] = Depends(get_current_user)):
    """Return the current authenticated user's info."""
    safe = {k: v for k, v in user.items() if k not in ("pin_hash", "password_hash")}
    return safe


# ============================================================================
# Onboarding
# ============================================================================

@app.post("/api/onboard")
def onboard(req: OnboardRequest):
    """Onboard a new user (student, guardian, teacher, admin)."""
    if req.grade not in GRADES:
        raise HTTPException(status_code=400, detail=f"Grade must be one of {GRADES}")
    if req.medium not in MEDIUMS:
        raise HTTPException(status_code=400, detail=f"Medium must be one of {MEDIUMS}")
    if req.board not in BOARDS:
        raise HTTPException(status_code=400, detail=f"Board must be one of {BOARDS}")

    reg = RegisterRequest(
        name=req.name,
        role=req.role,
        grade=req.grade,
        medium=req.medium,
        board=req.board,
        school_id=req.school_id,
        pin=req.pin,
        email=req.email,
        password=req.password,
    )
    result = register(reg)

    # For guardians, link students
    if req.role == "guardian" and req.linked_student_ids:
        store = load_store()
        guardian_id = result["user_id"]
        for sid in req.linked_student_ids:
            store["guardian_links"].setdefault(guardian_id, [])
            if sid not in store["guardian_links"][guardian_id]:
                store["guardian_links"][guardian_id].append(sid)
        save_store(store)

    return result


# ============================================================================
# Consent
# ============================================================================

@app.post("/api/consent")
def record_consent(req: ConsentRequest):
    """Record guardian consent for a student under MIN_CONSENT_AGE."""
    if not req.agreed:
        raise HTTPException(status_code=400, detail="Consent must be agreed=True")

    store = load_store()

    # Verify guardian exists and is a guardian
    guardian = store["users"].get(req.guardian_id)
    if not guardian or guardian.get("role") != "guardian":
        raise HTTPException(status_code=404, detail="Guardian not found")

    # Verify student exists
    student = store["users"].get(req.student_id)
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    record = {
        "guardian_id": req.guardian_id,
        "student_id": req.student_id,
        "agreed": True,
        "consent_version": CONSENT_VERSION,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    store["consent_records"][req.student_id] = record
    save_store(store)
    log_event("consent_recorded", record)

    return {"status": "ok", "consent_version": CONSENT_VERSION}


# ============================================================================
# Subjects & content
# ============================================================================

@app.get("/api/subjects")
def list_subjects(
    grade: Optional[int] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List subjects, optionally filtered by grade."""
    result = []
    for s in SUBJECTS.values():
        if grade is not None and s.get("grade") != grade:
            continue
        result.append(s)
    return result


@app.get("/api/concepts/{subject_id}")
def list_concepts(
    subject_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List concepts for a subject."""
    result = [
        c for c in CONCEPTS.values() if c.get("subject_id") == subject_id
    ]
    result.sort(key=lambda c: c.get("order_num", 0))
    return result


@app.get("/api/questions/{concept_id}")
def list_questions(
    concept_id: str,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Get questions for a concept.  Answer keys are NEVER sent."""
    result = []
    for q in QUESTIONS.values():
        if q.get("concept_id") != concept_id:
            continue
        safe_q = {
            "id": q["id"],
            "concept_id": q["concept_id"],
            "stem": q["stem"],
            "difficulty": q.get("difficulty"),
            "is_diagnostic": q.get("is_diagnostic", False),
            "is_transfer": q.get("is_transfer", False),
            "options": [
                {"id": o["id"], "text": o["text"]}
                for o in q.get("options", [])
            ],
        }
        result.append(safe_q)
    return result


# ============================================================================
# Diagnostic
# ============================================================================

@app.post("/api/diagnostic/start")
def diagnostic_start(
    req: DiagnosticStartRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Start a diagnostic for a subject.  Returns 8-12 questions (no answer keys)."""
    concept_ids = [
        c["id"]
        for c in CONCEPTS.values()
        if c.get("subject_id") == req.subject_id
    ]
    if not concept_ids:
        raise HTTPException(status_code=404, detail="No concepts for this subject")

    diag_questions: List[Dict[str, Any]] = []
    for q in QUESTIONS.values():
        if (
            q.get("concept_id") in concept_ids
            and q.get("is_diagnostic", False)
            and not q.get("is_transfer", False)
        ):
            diag_questions.append(q)

    # Limit to DIAGNOSTIC_MAX_ITEMS, ensure at least DIAGNOSTIC_MIN_ITEMS
    import random
    random.shuffle(diag_questions)
    diag_questions = diag_questions[:DIAGNOSTIC_MAX_ITEMS]

    # Return without answer keys
    safe = []
    for q in diag_questions:
        safe.append({
            "id": q["id"],
            "concept_id": q["concept_id"],
            "stem": q["stem"],
            "difficulty": q.get("difficulty"),
            "options": [{"id": o["id"], "text": o["text"]} for o in q.get("options", [])],
        })
    return {"subject_id": req.subject_id, "questions": safe}


@app.post("/api/diagnostic/submit")
def diagnostic_submit(
    req: DiagnosticSubmitRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Submit diagnostic answers and return mastery scores per concept."""
    uid = user["id"]
    concept_ids = [
        c["id"]
        for c in CONCEPTS.values()
        if c.get("subject_id") == req.subject_id
    ]

    # Build responses with correct/unaided flags
    responses: List[Dict[str, Any]] = []
    for r in req.responses:
        qid = r.get("question_id")
        selected = r.get("selected_option_id")
        q = QUESTIONS.get(qid)
        if not q:
            continue
        correct = False
        for opt in q.get("options", []):
            if opt["id"] == selected and opt.get("correct", False):
                correct = True
                break
        responses.append({
            "concept_id": q["concept_id"],
            "correct": correct,
            "unaided": r.get("unaided", True),
        })

    scores = run_diagnostic(responses, concept_ids)

    # Persist mastery
    store = load_store()
    if uid not in store["masteries"]:
        store["masteries"][uid] = {}
    for cid, score in scores.items():
        store["masteries"][uid][cid] = score
        # If mastered from diagnostic, record date
        if score >= BKT_MASTERY_THRESHOLD:
            store["mastery_dates"].setdefault(uid, {})[cid] = (
                datetime.utcnow().isoformat() + "Z"
            )
    save_store(store)
    log_event("diagnostic_completed", {
        "user_id": uid,
        "subject_id": req.subject_id,
        "scores": scores,
    })

    return {"scores": scores, "concept_count": len(concept_ids)}


# ============================================================================
# Practice
# ============================================================================

@app.get("/api/practice/next")
def practice_next(
    subject_id: str = Query(...),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Get the next practice question (personalised or generic)."""
    uid = user["id"]
    store = load_store()
    condition = store["conditions"].get(uid, "personalised")

    all_qs = [q for q in QUESTIONS.values() if not q.get("is_transfer", False)]
    subject_qs = [
        q for q in all_qs
        if CONCEPTS.get(q.get("concept_id", ""), {}).get("subject_id") == subject_id
    ]

    if condition == "generic":
        # Generic condition: fixed order, no adaptation
        idx = store.get("generic_index", {}).get(uid, 0)
        q = get_generic_question(subject_qs, idx)
        if not q:
            return {"done": True, "message": "No more questions in the generic set."}
        store.setdefault("generic_index", {})[uid] = idx + 1
        save_store(store)
        return {
            "question": {
                "id": q["id"],
                "concept_id": q["concept_id"],
                "stem": q["stem"],
                "difficulty": q.get("difficulty"),
                "options": [{"id": o["id"], "text": o["text"]} for o in q.get("options", [])],
            },
            "hint_level": GENERIC_HINT_LEVEL,
            "condition": "generic",
        }

    # Personalised path
    masteries = store["masteries"].get(uid, {})
    seen = set(store["seen_questions"].get(uid, []))

    # Check spaced review first
    mastery_dates_raw = store["mastery_dates"].get(uid, {})
    mastery_dates_dt: Dict[str, datetime] = {}
    for cid, dstr in mastery_dates_raw.items():
        try:
            mastery_dates_dt[cid] = datetime.fromisoformat(dstr.replace("Z", ""))
        except Exception:
            pass
    review_counts = store["review_counts"].get(uid, {})
    review_due = get_spaced_review_concepts(
        masteries, mastery_dates_dt, review_counts
    )

    concept_id = None
    if review_due:
        concept_id = review_due[0]
    else:
        concept_id = select_next_concept(masteries, PREREQUISITES, BKT_MASTERY_THRESHOLD)

    if not concept_id:
        return {"done": True, "message": "All concepts mastered or no eligible concepts."}

    mastery = masteries.get(concept_id, BKT_P_INIT)
    q = select_question(concept_id, subject_qs, seen, mastery)
    if not q:
        return {"done": True, "message": "No questions available for this concept."}

    # Hint state
    hint_key = f"{uid}:{concept_id}"
    hs_data = store["hint_states"].get(hint_key)
    hint_level = 1
    if hs_data:
        hint_level = hs_data.get("level", 1)

    return {
        "question": {
            "id": q["id"],
            "concept_id": q["concept_id"],
            "stem": q["stem"],
            "difficulty": q.get("difficulty"),
            "options": [{"id": o["id"], "text": o["text"]} for o in q.get("options", [])],
        },
        "concept_id": concept_id,
        "mastery": round(mastery, 4),
        "hint_level": hint_level,
        "condition": "personalised",
    }


@app.post("/api/practice/answer")
def practice_answer(
    req: AnswerRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Submit a practice answer.  Returns feedback, misconception, and mastery update."""
    uid = user["id"]
    store = load_store()

    q = QUESTIONS.get(req.question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    # Determine correctness
    correct = False
    for opt in q.get("options", []):
        if opt["id"] == req.selected_option_id and opt.get("correct", False):
            correct = True
            break

    # Diagnose misconception
    misconception_id = diagnose_answer(req.selected_option_id, q.get("options", []))

    # Update mastery via BKT
    masteries = store["masteries"].setdefault(uid, {})
    old_mastery = masteries.get(req.concept_id, BKT_P_INIT)
    new_mastery = bkt.update(old_mastery, correct, req.unaided)
    masteries[req.concept_id] = new_mastery

    # If newly mastered, record date
    if new_mastery >= BKT_MASTERY_THRESHOLD and old_mastery < BKT_MASTERY_THRESHOLD:
        store["mastery_dates"].setdefault(uid, {})[req.concept_id] = (
            datetime.utcnow().isoformat() + "Z"
        )

    # Update hint state
    hint_key = f"{uid}:{req.concept_id}"
    hs_data = store["hint_states"].get(hint_key, {"level": 1, "consecutive_unaided_correct": 0})
    hs = HintState(
        level=hs_data.get("level", 1),
        consecutive_unaided_correct=hs_data.get("consecutive_unaided_correct", 0),
    )
    if not correct:
        hs = HintLadder.escalate(hs)
    elif req.unaided:
        hs = HintLadder.on_correct_unaided(hs)
    store["hint_states"][hint_key] = {
        "level": hs.level,
        "consecutive_unaided_correct": hs.consecutive_unaided_correct,
    }

    # Log misconception
    if misconception_id:
        store["misconception_log"].append({
            "user_id": uid,
            "concept_id": req.concept_id,
            "question_id": req.question_id,
            "misconception_id": misconception_id,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        })

    # Detect recurring misconceptions
    user_misc_log = [
        m for m in store["misconception_log"] if m.get("user_id") == uid
    ]
    recurring = detect_recurring(user_misc_log, req.concept_id)

    # Mark question as seen
    store["seen_questions"].setdefault(uid, [])
    if req.question_id not in store["seen_questions"][uid]:
        store["seen_questions"][uid].append(req.question_id)

    # Record attempt
    store["attempts"].append({
        "user_id": uid,
        "question_id": req.question_id,
        "concept_id": req.concept_id,
        "selected_option_id": req.selected_option_id,
        "correct": correct,
        "unaided": req.unaided,
        "misconception_id": misconception_id,
        "old_mastery": round(old_mastery, 4),
        "new_mastery": round(new_mastery, 4),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })

    save_store(store)
    log_event("practice_answer", {
        "user_id": uid,
        "question_id": req.question_id,
        "correct": correct,
        "unaided": req.unaided,
        "misconception_id": misconception_id,
    })

    # Build feedback
    feedback: Dict[str, Any] = {
        "correct": correct,
        "mastery": round(new_mastery, 4),
        "mastered": bkt.is_mastered(new_mastery),
        "hint_level": hs.level,
    }
    if misconception_id:
        feedback["misconception_id"] = misconception_id
        misc = MISCONCEPTIONS.get(misconception_id)
        if misc:
            feedback["misconception_description"] = misc.get("description", "")
        # LLM explanation for wrong answer
        feedback["explanation"] = llm.complete(
            system_prompt="You are a helpful maths tutor for grade-school students.",
            user_message=f"Explain why the selected answer is wrong for: {q['stem']}",
        )
    if recurring:
        feedback["recurring_misconceptions"] = recurring

    # Correct answer key now included in feedback
    for opt in q.get("options", []):
        if opt.get("correct", False):
            feedback["correct_option_id"] = opt["id"]
            feedback["correct_option_text"] = opt["text"]
            break

    return feedback


@app.post("/api/practice/hint")
def practice_hint(
    req: HintRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Request the next hint level for a question."""
    uid = user["id"]
    store = load_store()

    q = QUESTIONS.get(req.question_id)
    if not q:
        raise HTTPException(status_code=404, detail="Question not found")

    hint_key = f"{uid}:{req.concept_id}"
    hs_data = store["hint_states"].get(hint_key, {"level": 1, "consecutive_unaided_correct": 0})
    level = hs_data.get("level", 1)

    hints = q.get("hints", [])
    hint_text = HintLadder.get_hint_text(hints, level)

    # Personalise hint via LLM
    personalised = llm.complete(
        system_prompt="You are a kind tutor. Rephrase this hint for a student.",
        user_message=hint_text,
    )

    return {
        "hint_level": level,
        "hint_text": hint_text,
        "personalised_hint": personalised,
        "max_level": HINT_MAX_LEVEL,
    }


@app.post("/api/practice/transfer")
def practice_transfer(
    req: TransferRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """'I think I've got it' -- transfer check."""
    uid = user["id"]
    store = load_store()

    q = QUESTIONS.get(req.question_id)
    if not q:
        # Try selecting a transfer question
        tq = select_transfer_question(req.concept_id, list(QUESTIONS.values()))
        if not tq:
            raise HTTPException(status_code=404, detail="No transfer question available")
        # Return the question for the student to answer
        return {
            "transfer_question": {
                "id": tq["id"],
                "concept_id": tq["concept_id"],
                "stem": tq["stem"],
                "options": [{"id": o["id"], "text": o["text"]} for o in tq.get("options", [])],
            }
        }

    # Evaluate answer
    correct = False
    for opt in q.get("options", []):
        if opt["id"] == req.selected_option_id and opt.get("correct", False):
            correct = True
            break

    masteries = store["masteries"].setdefault(uid, {})
    mastery = masteries.get(req.concept_id, BKT_P_INIT)

    result = check_transfer(correct, unaided=True, mastery=mastery, threshold=BKT_MASTERY_THRESHOLD)

    if result["mastered"]:
        masteries[req.concept_id] = max(mastery, BKT_MASTERY_THRESHOLD)
        store["mastery_dates"].setdefault(uid, {})[req.concept_id] = (
            datetime.utcnow().isoformat() + "Z"
        )

    save_store(store)
    return result


# ============================================================================
# Mock tests
# ============================================================================

@app.post("/api/test/create")
def test_create(
    req: MockTestCreateRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Create a mock test."""
    # Gather approved questions for the subject
    concept_ids = [
        c["id"]
        for c in CONCEPTS.values()
        if c.get("subject_id") == req.subject_id and c.get("status") == "approved"
    ]
    pool = [
        q for q in QUESTIONS.values()
        if q.get("concept_id") in concept_ids
        and not q.get("is_transfer", False)
    ]

    if req.source == "approved":
        pool = [q for q in pool if q.get("status", "approved") == "approved"]

    import random
    random.shuffle(pool)
    selected = pool[: req.question_count]
    if not selected:
        raise HTTPException(status_code=400, detail="No questions available for this subject")

    test_id = str(uuid.uuid4())
    test = {
        "id": test_id,
        "user_id": user["id"],
        "subject_id": req.subject_id,
        "question_ids": [q["id"] for q in selected],
        "time_limit_minutes": req.time_limit_minutes,
        "start_time": datetime.utcnow().isoformat() + "Z",
        "status": "in_progress",
        "submitted": False,
        "results": None,
    }

    store = load_store()
    store["mock_tests"][test_id] = test
    save_store(store)

    return {"test_id": test_id, "question_count": len(selected), "time_limit_minutes": req.time_limit_minutes}


@app.get("/api/test/{test_id}")
def test_get(test_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Get test questions (NO answer keys)."""
    store = load_store()
    test = store["mock_tests"].get(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    if test["user_id"] != user["id"] and user.get("role") not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Access denied")

    # Check timer
    start = datetime.fromisoformat(test["start_time"].replace("Z", ""))
    elapsed = (datetime.utcnow() - start).total_seconds() / 60.0
    if elapsed > test["time_limit_minutes"] and not test["submitted"]:
        test["status"] = "expired"
        save_store(store)

    questions = []
    for qid in test["question_ids"]:
        q = QUESTIONS.get(qid)
        if not q:
            continue
        questions.append({
            "id": q["id"],
            "concept_id": q["concept_id"],
            "stem": q["stem"],
            "difficulty": q.get("difficulty"),
            "options": [{"id": o["id"], "text": o["text"]} for o in q.get("options", [])],
        })

    return {
        "test_id": test_id,
        "status": test["status"],
        "time_limit_minutes": test["time_limit_minutes"],
        "start_time": test["start_time"],
        "questions": questions,
    }


@app.post("/api/test/{test_id}/submit")
def test_submit(
    test_id: str,
    req: MockTestSubmitRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Submit a mock test and return results with answer keys."""
    store = load_store()
    test = store["mock_tests"].get(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    if test["user_id"] != user["id"]:
        raise HTTPException(status_code=403, detail="Access denied")
    if test["submitted"]:
        raise HTTPException(status_code=400, detail="Test already submitted")

    # Check timer -- allow submission even if slightly over
    start = datetime.fromisoformat(test["start_time"].replace("Z", ""))
    elapsed = (datetime.utcnow() - start).total_seconds() / 60.0
    if elapsed > test["time_limit_minutes"] + 1:  # 1 min grace
        test["status"] = "expired"
        save_store(store)
        raise HTTPException(status_code=400, detail="Test time has expired")

    # Build correct map
    correct_map: Dict[str, str] = {}
    for qid in test["question_ids"]:
        q = QUESTIONS.get(qid)
        if not q:
            continue
        for opt in q.get("options", []):
            if opt.get("correct", False):
                correct_map[qid] = opt["id"]
                break

    results = score_mock_test(req.answers, correct_map)
    test["submitted"] = True
    test["status"] = "completed"
    test["results"] = results
    test["submit_time"] = datetime.utcnow().isoformat() + "Z"
    save_store(store)

    log_event("test_submitted", {
        "user_id": user["id"],
        "test_id": test_id,
        "score": results["score"],
        "accuracy": results["accuracy"],
    })

    # Include answer keys in response
    answer_keys: Dict[str, str] = {}
    for qid in test["question_ids"]:
        q = QUESTIONS.get(qid)
        if q:
            for opt in q.get("options", []):
                if opt.get("correct", False):
                    answer_keys[qid] = opt["id"]
                    break

    return {
        "results": results,
        "answer_keys": answer_keys,
    }


@app.get("/api/test/{test_id}/results")
def test_results(test_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    """Get test results (answer keys included ONLY after submission)."""
    store = load_store()
    test = store["mock_tests"].get(test_id)
    if not test:
        raise HTTPException(status_code=404, detail="Test not found")
    if test["user_id"] != user["id"] and user.get("role") not in ("teacher", "admin"):
        raise HTTPException(status_code=403, detail="Access denied")
    if not test["submitted"]:
        raise HTTPException(status_code=400, detail="Test not yet submitted")

    answer_keys: Dict[str, str] = {}
    for qid in test["question_ids"]:
        q = QUESTIONS.get(qid)
        if q:
            for opt in q.get("options", []):
                if opt.get("correct", False):
                    answer_keys[qid] = opt["id"]
                    break

    return {
        "test_id": test_id,
        "results": test["results"],
        "answer_keys": answer_keys,
        "submit_time": test.get("submit_time"),
    }


@app.get("/api/test/history")
def test_history(user: Dict[str, Any] = Depends(get_current_user)):
    """List past tests for the current user."""
    store = load_store()
    tests = [
        {
            "test_id": t["id"],
            "subject_id": t["subject_id"],
            "status": t["status"],
            "submitted": t["submitted"],
            "start_time": t["start_time"],
            "question_count": len(t["question_ids"]),
            "score": t["results"]["score"] if t.get("results") else None,
            "accuracy": t["results"]["accuracy"] if t.get("results") else None,
        }
        for t in store["mock_tests"].values()
        if t["user_id"] == user["id"]
    ]
    return tests


# ============================================================================
# Chat (Ask Anything)
# ============================================================================

@app.post("/api/chat")
def chat(
    req: ChatRequest,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """Send a message to the Ask Anything chat."""
    uid = user["id"]

    # Safety screen
    safety_result = safety_screen(req.message)
    if safety_result:
        log_event("chat_safety_triggered", {
            "user_id": uid,
            "category": safety_result["category"],
            "message_redacted": redact_pii(req.message),
        })
        return {
            "safe": False,
            "category": safety_result["category"],
            "message": safety_result["message"],
            "helpline_numbers": safety_result["helpline_numbers"],
        }

    # Get LLM response
    system_prompt = (
        f"You are a helpful educational assistant for {PRODUCT_NAME}. "
        f"The student is in grade {user.get('grade', '?')} studying "
        f"in {user.get('medium', 'English')} medium. "
        f"Give clear, age-appropriate explanations."
    )
    response = llm.complete(system_prompt, req.message, LLM_MAX_TOKENS)

    # Store chat history
    store = load_store()
    store["chat_history"].setdefault(uid, [])
    store["chat_history"][uid].append({
        "role": "user",
        "content": redact_pii(req.message),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    store["chat_history"][uid].append({
        "role": "assistant",
        "content": response,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    })
    save_store(store)

    log_event("chat_message", {
        "user_id": uid,
        "message_redacted": redact_pii(req.message),
    })

    return {"safe": True, "response": response}


@app.get("/api/chat/history")
def chat_history(user: Dict[str, Any] = Depends(get_current_user)):
    """Get chat history for the current user."""
    store = load_store()
    return store["chat_history"].get(user["id"], [])


# ============================================================================
# Library vault
# ============================================================================

@app.get("/api/library")
def library_list(
    search: Optional[str] = Query(None),
    grade: Optional[int] = Query(None),
    user: Dict[str, Any] = Depends(get_current_user),
):
    """List library resources with optional search and grade filter."""
    results = []
    for r in LIBRARY_RESOURCES.values():
        if grade is not None and r.get("grade") != grade:
            continue
        if search:
            search_lower = search.lower()
            title_lower = r.get("title", "").lower()
            desc_lower = r.get("description", "").lower()
            if search_lower not in title_lower and search_lower not in desc_lower:
                continue
        results.append(r)
    return results


@app.post("/api/library/upload")
def library_upload(
    req: LibraryUploadRequest,
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Upload a library resource (teacher/admin only).  Starts as draft."""
    resource_id = f"lib-{uuid.uuid4().hex[:8]}"
    resource = {
        "id": resource_id,
        "title": req.title,
        "type": req.type,
        "pages": req.pages,
        "grade": req.grade,
        "subject_id": req.subject_id,
        "status": "draft",
        "description": req.description,
        "uploaded_by": user["id"],
        "created_at": datetime.utcnow().isoformat() + "Z",
    }
    LIBRARY_RESOURCES[resource_id] = resource
    return {"id": resource_id, "status": "draft"}


# ============================================================================
# Guardian view
# ============================================================================

@app.get("/api/guardian/children")
def guardian_children(
    user: Dict[str, Any] = Depends(require_role("guardian")),
):
    """List linked children for a guardian."""
    store = load_store()
    linked_ids = store["guardian_links"].get(user["id"], [])
    children = []
    for sid in linked_ids:
        student = store["users"].get(sid)
        if student:
            children.append({
                "id": sid,
                "name": student.get("name"),
                "grade": student.get("grade"),
            })
    return children


@app.get("/api/guardian/child/{student_id}/summary")
def guardian_child_summary(
    student_id: str,
    user: Dict[str, Any] = Depends(require_role("guardian")),
):
    """Get summary for a linked child (mastery, time on task, misconceptions)."""
    store = load_store()
    linked_ids = store["guardian_links"].get(user["id"], [])
    if student_id not in linked_ids:
        raise HTTPException(status_code=403, detail="Not linked to this student")

    masteries = store["masteries"].get(student_id, {})
    attempts = [a for a in store["attempts"] if a.get("user_id") == student_id]
    misconceptions = [
        m for m in store["misconception_log"] if m.get("user_id") == student_id
    ]

    total_attempts = len(attempts)
    correct_count = sum(1 for a in attempts if a.get("correct"))

    # Unique misconceptions
    unique_misc: Dict[str, int] = {}
    for m in misconceptions:
        mid = m.get("misconception_id", "unknown")
        unique_misc[mid] = unique_misc.get(mid, 0) + 1

    return {
        "student_id": student_id,
        "masteries": masteries,
        "total_attempts": total_attempts,
        "correct_count": correct_count,
        "accuracy": round(correct_count / total_attempts * 100, 1) if total_attempts else 0,
        "misconception_counts": unique_misc,
    }


# ============================================================================
# Teacher view
# ============================================================================

@app.get("/api/teacher/class")
def teacher_class(
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Class progress overview."""
    store = load_store()
    students = [
        u for u in store["users"].values() if u.get("role") == "student"
    ]
    overview = []
    for s in students:
        sid = s["id"]
        masteries = store["masteries"].get(sid, {})
        attempts = [a for a in store["attempts"] if a.get("user_id") == sid]
        overview.append({
            "student_id": sid,
            "name": s.get("name"),
            "grade": s.get("grade"),
            "concepts_mastered": sum(
                1 for v in masteries.values() if v >= BKT_MASTERY_THRESHOLD
            ),
            "total_concepts": len(masteries),
            "total_attempts": len(attempts),
        })
    return overview


@app.get("/api/teacher/heatmap")
def teacher_heatmap(
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Misconception heatmap data -- concept x misconception x count."""
    store = load_store()
    heatmap: Dict[str, Dict[str, int]] = {}
    for entry in store["misconception_log"]:
        cid = entry.get("concept_id", "unknown")
        mid = entry.get("misconception_id", "unknown")
        heatmap.setdefault(cid, {})
        heatmap[cid][mid] = heatmap[cid].get(mid, 0) + 1
    return heatmap


@app.get("/api/teacher/approval-queue")
def teacher_approval_queue(
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Pending content items awaiting approval."""
    pending = []
    for q in QUESTIONS.values():
        if q.get("status") == "draft":
            pending.append({"type": "question", "id": q["id"], "item": q})
    for c in CONCEPTS.values():
        if c.get("status") == "draft":
            pending.append({"type": "concept", "id": c["id"], "item": c})
    for r in LIBRARY_RESOURCES.values():
        if r.get("status") == "draft":
            pending.append({"type": "resource", "id": r["id"], "item": r})
    return pending


@app.post("/api/teacher/approve/{item_id}")
def teacher_approve(
    item_id: str,
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Approve a content item.

    Cannot approve a question unless every wrong option links to a
    misconception or 'gap'.
    """
    # Check questions
    if item_id in QUESTIONS:
        q = QUESTIONS[item_id]
        errs = _validate_question(q)
        if errs:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot approve: {'; '.join(errs)}",
            )
        QUESTIONS[item_id]["status"] = "approved"
        return {"id": item_id, "status": "approved"}

    # Check concepts
    if item_id in CONCEPTS:
        CONCEPTS[item_id]["status"] = "approved"
        return {"id": item_id, "status": "approved"}

    # Check library
    if item_id in LIBRARY_RESOURCES:
        LIBRARY_RESOURCES[item_id]["status"] = "approved"
        return {"id": item_id, "status": "approved"}

    raise HTTPException(status_code=404, detail="Item not found")


@app.post("/api/teacher/difficulty")
def teacher_difficulty(
    req: DifficultyOverrideRequest,
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Override question difficulty."""
    if req.question_id not in QUESTIONS:
        raise HTTPException(status_code=404, detail="Question not found")
    if req.difficulty not in ("easy", "medium", "hard"):
        raise HTTPException(status_code=400, detail="Difficulty must be easy, medium, or hard")
    QUESTIONS[req.question_id]["difficulty"] = req.difficulty
    return {"id": req.question_id, "difficulty": req.difficulty}


# ============================================================================
# Admin CRUD
# ============================================================================

@app.post("/api/admin/concepts")
def admin_create_concept(
    req: ConceptCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Create a new concept (starts as draft)."""
    concept_id = f"con-{uuid.uuid4().hex[:8]}"
    concept = {
        "id": concept_id,
        "subject_id": req.subject_id,
        "name": req.name,
        "prerequisites": req.prerequisites,
        "order_num": req.order_num,
        "status": "draft",
    }
    CONCEPTS[concept_id] = concept
    PREREQUISITES[concept_id] = req.prerequisites
    return concept


@app.get("/api/admin/concepts")
def admin_list_concepts(
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """List all concepts (including drafts)."""
    return list(CONCEPTS.values())


@app.put("/api/admin/concepts/{concept_id}")
def admin_update_concept(
    concept_id: str,
    req: ConceptCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Update a concept."""
    if concept_id not in CONCEPTS:
        raise HTTPException(status_code=404, detail="Concept not found")
    CONCEPTS[concept_id].update({
        "name": req.name,
        "subject_id": req.subject_id,
        "prerequisites": req.prerequisites,
        "order_num": req.order_num,
    })
    PREREQUISITES[concept_id] = req.prerequisites
    return CONCEPTS[concept_id]


@app.delete("/api/admin/concepts/{concept_id}")
def admin_delete_concept(
    concept_id: str,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Delete a concept."""
    if concept_id not in CONCEPTS:
        raise HTTPException(status_code=404, detail="Concept not found")
    del CONCEPTS[concept_id]
    PREREQUISITES.pop(concept_id, None)
    return {"deleted": concept_id}


@app.post("/api/admin/questions")
def admin_create_question(
    req: QuestionCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Create a new question (starts as draft)."""
    if req.concept_id not in CONCEPTS:
        raise HTTPException(status_code=400, detail="Concept not found")
    question_id = f"q-{uuid.uuid4().hex[:8]}"
    question = {
        "id": question_id,
        "concept_id": req.concept_id,
        "stem": req.stem,
        "options": req.options,
        "difficulty": req.difficulty,
        "is_diagnostic": req.is_diagnostic,
        "is_transfer": req.is_transfer,
        "hints": req.hints,
        "status": "draft",
    }
    QUESTIONS[question_id] = question
    return question


@app.get("/api/admin/questions")
def admin_list_questions(
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """List all questions (including drafts, with answer keys)."""
    return list(QUESTIONS.values())


@app.put("/api/admin/questions/{question_id}")
def admin_update_question(
    question_id: str,
    req: QuestionCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Update a question."""
    if question_id not in QUESTIONS:
        raise HTTPException(status_code=404, detail="Question not found")
    QUESTIONS[question_id].update({
        "concept_id": req.concept_id,
        "stem": req.stem,
        "options": req.options,
        "difficulty": req.difficulty,
        "is_diagnostic": req.is_diagnostic,
        "is_transfer": req.is_transfer,
        "hints": req.hints,
    })
    return QUESTIONS[question_id]


@app.delete("/api/admin/questions/{question_id}")
def admin_delete_question(
    question_id: str,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Delete a question."""
    if question_id not in QUESTIONS:
        raise HTTPException(status_code=404, detail="Question not found")
    del QUESTIONS[question_id]
    return {"deleted": question_id}


@app.post("/api/admin/hints")
def admin_create_hint(
    req: HintCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Add a hint to a question."""
    if req.question_id not in QUESTIONS:
        raise HTTPException(status_code=404, detail="Question not found")
    hint = {"level": req.level, "text": req.text}
    QUESTIONS[req.question_id].setdefault("hints", []).append(hint)
    return {"question_id": req.question_id, "hint": hint}


@app.post("/api/admin/misconceptions")
def admin_create_misconception(
    req: MisconceptionCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Create a new misconception (starts as draft)."""
    misc_id = f"misc-{uuid.uuid4().hex[:8]}"
    misconception = {
        "id": misc_id,
        "concept_id": req.concept_id,
        "description": req.description,
        "status": "draft",
    }
    MISCONCEPTIONS[misc_id] = misconception
    return misconception


@app.get("/api/admin/misconceptions")
def admin_list_misconceptions(
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """List all misconceptions."""
    return list(MISCONCEPTIONS.values())


@app.put("/api/admin/misconceptions/{misc_id}")
def admin_update_misconception(
    misc_id: str,
    req: MisconceptionCreateRequest,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Update a misconception."""
    if misc_id not in MISCONCEPTIONS:
        raise HTTPException(status_code=404, detail="Misconception not found")
    MISCONCEPTIONS[misc_id].update({
        "concept_id": req.concept_id,
        "description": req.description,
    })
    return MISCONCEPTIONS[misc_id]


@app.delete("/api/admin/misconceptions/{misc_id}")
def admin_delete_misconception(
    misc_id: str,
    user: Dict[str, Any] = Depends(require_role("admin")),
):
    """Delete a misconception."""
    if misc_id not in MISCONCEPTIONS:
        raise HTTPException(status_code=404, detail="Misconception not found")
    del MISCONCEPTIONS[misc_id]
    return {"deleted": misc_id}


# ============================================================================
# Analytics
# ============================================================================

@app.get("/api/analytics/experiment")
def analytics_experiment(
    user: Dict[str, Any] = Depends(require_role("teacher", "admin")),
):
    """Cohen's d, 95% CI, and Welch's t-test between personalised and generic conditions."""
    store = load_store()

    # Gather per-user accuracy for each condition
    personalised_acc: List[float] = []
    generic_acc: List[float] = []

    user_attempts: Dict[str, List[Dict[str, Any]]] = {}
    for a in store["attempts"]:
        uid = a.get("user_id", "")
        user_attempts.setdefault(uid, []).append(a)

    for uid, attempts in user_attempts.items():
        if not attempts:
            continue
        correct = sum(1 for a in attempts if a.get("correct"))
        acc = correct / len(attempts)
        condition = store["conditions"].get(uid, "personalised")
        if condition == "generic":
            generic_acc.append(acc)
        else:
            personalised_acc.append(acc)

    if len(personalised_acc) < 2 or len(generic_acc) < 2:
        return {
            "message": "Not enough data for statistical comparison",
            "personalised_n": len(personalised_acc),
            "generic_n": len(generic_acc),
        }

    # Means and variances
    n1 = len(personalised_acc)
    n2 = len(generic_acc)
    m1 = sum(personalised_acc) / n1
    m2 = sum(generic_acc) / n2
    var1 = sum((x - m1) ** 2 for x in personalised_acc) / (n1 - 1)
    var2 = sum((x - m2) ** 2 for x in generic_acc) / (n2 - 1)

    # Pooled SD for Cohen's d
    pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    pooled_sd = math.sqrt(pooled_var) if pooled_var > 0 else 1e-9
    cohens_d = (m1 - m2) / pooled_sd

    # Welch's t-test
    se = math.sqrt(var1 / n1 + var2 / n2) if (var1 / n1 + var2 / n2) > 0 else 1e-9
    t_stat = (m1 - m2) / se

    # Welch-Satterthwaite degrees of freedom
    num = (var1 / n1 + var2 / n2) ** 2
    denom = ((var1 / n1) ** 2 / (n1 - 1)) + ((var2 / n2) ** 2 / (n2 - 1))
    df = num / denom if denom > 0 else 1

    # 95% CI for difference in means (approx using t ~ 1.96 for large df)
    t_crit = 1.96  # approximate
    ci_lower = (m1 - m2) - t_crit * se
    ci_upper = (m1 - m2) + t_crit * se

    return {
        "personalised": {
            "n": n1,
            "mean_accuracy": round(m1, 4),
            "variance": round(var1, 6),
        },
        "generic": {
            "n": n2,
            "mean_accuracy": round(m2, 4),
            "variance": round(var2, 6),
        },
        "cohens_d": round(cohens_d, 4),
        "welch_t": round(t_stat, 4),
        "df": round(df, 2),
        "ci_95": [round(ci_lower, 4), round(ci_upper, 4)],
        "mean_difference": round(m1 - m2, 4),
    }


# ============================================================================
# Data management
# ============================================================================

@app.delete("/api/user/data")
def delete_user_data(user: Dict[str, Any] = Depends(get_current_user)):
    """Complete data deletion for the current user."""
    uid = user["id"]
    store = load_store()

    # Remove from all store sections
    store["users"].pop(uid, None)
    store["students"].pop(uid, None)
    store["masteries"].pop(uid, None)
    store["chat_history"].pop(uid, None)
    store["seen_questions"].pop(uid, None)
    store["review_counts"].pop(uid, None)
    store["mastery_dates"].pop(uid, None)
    store["conditions"].pop(uid, None)
    store["consent_records"].pop(uid, None)

    # Remove from guardian links (both as guardian and as student)
    store["guardian_links"].pop(uid, None)
    for gid in list(store["guardian_links"].keys()):
        links = store["guardian_links"][gid]
        if uid in links:
            links.remove(uid)

    # Remove hint states
    keys_to_remove = [k for k in store["hint_states"] if k.startswith(f"{uid}:")]
    for k in keys_to_remove:
        del store["hint_states"][k]

    # Remove attempts
    store["attempts"] = [a for a in store["attempts"] if a.get("user_id") != uid]

    # Remove misconception log entries
    store["misconception_log"] = [
        m for m in store["misconception_log"] if m.get("user_id") != uid
    ]

    # Remove mock tests
    test_keys = [k for k, v in store["mock_tests"].items() if v.get("user_id") == uid]
    for k in test_keys:
        del store["mock_tests"][k]

    save_store(store)
    log_event("user_data_deleted", {"user_id": uid})

    return {"status": "deleted", "user_id": uid}


# ============================================================================
# Main entry point
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
