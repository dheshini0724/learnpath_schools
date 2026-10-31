"""
Central configuration for LearnPath for Schools.

All placeholders (board names, medium options, school names, helpline numbers,
model names, product name) live here.  Nothing is hardcoded in the rest of the
codebase.
"""
from __future__ import annotations

import os
from typing import Dict, List

# ── Product ──────────────────────────────────────────────────────────────────
PRODUCT_NAME: str = os.getenv("PRODUCT_NAME", "LearnPath for Schools")
PRODUCT_VERSION: str = "1.0.0"

# ── Age / consent ───────────────────────────────────────────────────────────
# Threshold is pending legal review; keep in configuration.
MIN_CONSENT_AGE: int = int(os.getenv("MIN_CONSENT_AGE", "18"))
CONSENT_VERSION: str = os.getenv("CONSENT_VERSION", "v1.0")

# ── Boards and mediums ──────────────────────────────────────────────────────
BOARDS: List[str] = ["CBSE", "ICSE", "State Board"]
MEDIUMS: List[str] = ["English", "Hindi", "Tamil", "Telugu", "Kannada", "Malayalam"]
GRADES: List[int] = list(range(5, 13))  # 5 to 12

# ── School names (placeholder list) ────────────────────────────────────────
SCHOOL_NAMES: List[str] = ["Demo School"]

# ── Helpline numbers (verify before launch) ─────────────────────────────────
HELPLINE_NUMBERS: Dict[str, str] = {
    "tele_manas": os.getenv("HELPLINE_TELE_MANAS", "14416"),
    "emergency": os.getenv("HELPLINE_EMERGENCY", "112"),
}

# ── LLM configuration ──────────────────────────────────────────────────────
LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gemini-2.5-flash")
LLM_API_KEY_ENV: str = "LLM_API_KEY"  # env var name; never log the value
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "512"))

# ── BKT engine parameters ──────────────────────────────────────────────────
BKT_P_INIT: float = 0.2
BKT_SLIP: float = 0.1
BKT_GUESS: float = 0.2
BKT_TRANSIT: float = 0.1
BKT_MASTERY_THRESHOLD: float = 0.9

# ── Diagnostic ──────────────────────────────────────────────────────────────
DIAGNOSTIC_MIN_ITEMS: int = 8
DIAGNOSTIC_MAX_ITEMS: int = 12
DIAGNOSTIC_ALL_CORRECT: float = 0.8
DIAGNOSTIC_PARTIAL: float = 0.5
DIAGNOSTIC_NONE_CORRECT: float = 0.2

# ── Spaced review intervals (days) ─────────────────────────────────────────
SPACED_REVIEW_INTERVALS: List[int] = [1, 3, 7, 21]

# ── Mock‑test scoring ──────────────────────────────────────────────────────
SCORING_CORRECT: float = 1.0
SCORING_WRONG: float = -0.25
SCORING_SKIPPED: float = 0.0

# ── Hint ladder ─────────────────────────────────────────────────────────────
HINT_MAX_LEVEL: int = 4
RECURRING_MISCONCEPTION_START_LEVEL: int = 3

# ── LLM guardrail thresholds ───────────────────────────────────────────────
MAX_REFERENCE_OVERLAP: float = 0.60  # <60 % overlap with reference material
HINT_LINE_LIMITS: Dict[int, int] = {1: 0, 2: 3, 3: 8, 4: 12}

# ── Reading‑level guide (grade → approx reading age) ───────────────────────
READING_LEVELS: Dict[int, str] = {
    5: "age 10", 6: "age 11", 7: "age 12", 8: "age 13",
    9: "age 14", 10: "age 15", 11: "age 16", 12: "age 17",
}

# ── Database ────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///learnpath.db")
STORE_JSON_PATH: str = os.getenv("STORE_JSON_PATH", "store.json")
EVENTS_LOG_PATH: str = os.getenv("EVENTS_LOG_PATH", "events.jsonl")

# ── Safety keywords (used by the safety screen) ────────────────────────────
SAFETY_CATEGORIES: Dict[str, List[str]] = {
    "self_harm": [
        "kill myself", "end my life", "suicide", "want to die",
        "hurt myself", "self harm", "self-harm", "cut myself",
    ],
    "abuse": [
        "hitting me", "beats me", "abusing me", "molest",
        "touching me", "hurting me at home",
    ],
    "bullying": [
        "being bullied", "bullying me", "they bully",
    ],
    "sexual": [
        "sexual content", "porn", "nude", "naked",
    ],
    "violence": [
        "kill someone", "hurt someone", "weapon", "bomb",
    ],
}

SAFETY_MESSAGE_TEMPLATE: str = (
    "I'm really sorry you're going through this. You are not alone. "
    "Please reach out to a trusted adult or call one of these helplines:\n"
    "- Tele-MANAS: {tele_manas}\n"
    "- Emergency: {emergency}\n"
    "Your safety matters more than anything else."
)
