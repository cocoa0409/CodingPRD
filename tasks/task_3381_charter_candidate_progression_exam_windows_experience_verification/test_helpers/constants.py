"""Domain constants — every value below is taken verbatim from PRD.md prose.

API MANIFEST (frozen for Phase B):
  CLOCK_INITIAL_ISO: str                  — logical-clock value before any set call (PRD §2.4)
  PROGRAM_FEE_CENTS: int = 35003          — program enrollment list price (PRD §3.1)
  EDUCATION_WINDOW_MONTHS: int = 23       — education-pathway graduation horizon (PRD §3.1)
  WORK_MIN_MONTHS: int = 36               — work-pathway minimum months (PRD §3.1)
  WORK_MIN_HOURS: int = 4000              — work-pathway minimum hours (PRD §3.1)
  SCHOLARSHIP_PCT_MAX: float = 0.5        — inclusive scholarship ceiling (PRD §3.1)
  SCORE_MIN: int = 0                      — scaled-score floor, inclusive (PRD §3.5)
  SCORE_MAX: int = 1000                   — scaled-score ceiling, inclusive (PRD §3.5)
  MAX_ATTEMPTS_MIN: int = 1               — level max_attempts lower bound (PRD §3.2)
  MAX_ATTEMPTS_MAX: int = 10              — level max_attempts upper bound (PRD §3.2)
  BLACKOUT_BUFFER_DAYS: int = 1           — buffer each side of a blackout range (PRD §3.2)
  RESCHEDULE_BASE_CENTS: int = 25000      — reschedule fee base (PRD §3.4)
  LATE_THRESHOLD_DAYS: int = 14           — late surcharge when notice < this (PRD §3.4)
  RESCHEDULE_LATE_SURCHARGE_CENTS = 25000 — late surcharge (PRD §3.4)
  PER_PRIOR_RESCHEDULE_CENTS = 10000      — per-prior-reschedule adder (PRD §3.4)
  PRIOR_CAP_COUNT: int = 2                — priors counted at most this many (PRD §3.4)
  RESCHEDULE_FEE_CAP_CENTS: int = 60000   — reschedule fee cap (PRD §3.4)
  MIN_QUALIFYING_PCT: int = 50            — inclusive qualifying-activity bar (PRD §3.6)
  MIN_REFERENCES: int = 2                 — references needed to submit/approve (PRD §3.6)
  REFERENCE_EXPIRY_DAYS: int = 30         — reference lifetime from creation (PRD §3.6)
  APPEAL_WINDOW_DAYS: int = 30            — appeal horizon after sanctioned_at (PRD §3.7)
  SUSPENSION_DURATION_DAYS: int = 365     — SUSPENSION_12M duration (PRD §3.7)
  MIN_CHARTER_MONTHS: int = 36            — award gate on summed committee months (PRD §3.8)
  ROLLING_WINDOW_DAYS: int = 365          — trailing window for rolling CE credits (PRD §3.9)
  DEFAULT_CE_CREDITS_REQUIRED_PER_YEAR = 20 — society CE default (PRD §3.9)
  PAGINATION_DEFAULT_LIMIT: int = 10      — list default limit (PRD §2.3)
  PAGINATION_MIN_LIMIT: int = 1           — list min limit (PRD §2.3)
  PAGINATION_MAX_LIMIT: int = 100         — list max limit (PRD §2.3)
  PAGINATION_DEFAULT_OFFSET: int = 0      — list default offset (PRD §2.3)
  APPROVED_CALCULATOR_MODELS: tuple       — the two approved calculators (PRD §3.3)
  LEVEL_CODES_IN_ORDER: tuple             — progression order (PRD §3.2)
"""

# --- Logical clock ---
# PRD §2.4: "Before any administrative call has been made, the clock reads
# exactly 2026-09-01T00:00:00Z, and it never falls back to wall-clock time."
CLOCK_INITIAL_ISO = "2026-09-01T00:00:00Z"

# --- Enrollment eligibility & program fee (PRD §3.1) ---
PROGRAM_FEE_CENTS = 35003
EDUCATION_WINDOW_MONTHS = 23
WORK_MIN_MONTHS = 36
WORK_MIN_HOURS = 4000
SCHOLARSHIP_PCT_MAX = 0.5

# --- Exam levels & scoring (PRD §3.2, §3.5) ---
SCORE_MIN = 0
SCORE_MAX = 1000
MAX_ATTEMPTS_MIN = 1
MAX_ATTEMPTS_MAX = 10

# --- Test centers (PRD §3.2) ---
BLACKOUT_BUFFER_DAYS = 1

# --- Reschedule fee card (PRD §3.4) ---
RESCHEDULE_BASE_CENTS = 25000
LATE_THRESHOLD_DAYS = 14
RESCHEDULE_LATE_SURCHARGE_CENTS = 25000
PER_PRIOR_RESCHEDULE_CENTS = 10000
PRIOR_CAP_COUNT = 2
RESCHEDULE_FEE_CAP_CENTS = 60000

# --- Work experience & references (PRD §3.6) ---
MIN_QUALIFYING_PCT = 50
MIN_REFERENCES = 2
REFERENCE_EXPIRY_DAYS = 30

# --- Misconduct & sanctions (PRD §3.7) ---
APPEAL_WINDOW_DAYS = 30
SUSPENSION_DURATION_DAYS = 365

# --- Charter award (PRD §3.8) ---
MIN_CHARTER_MONTHS = 36

# --- Societies & continuing education (PRD §3.9) ---
ROLLING_WINDOW_DAYS = 365
DEFAULT_CE_CREDITS_REQUIRED_PER_YEAR = 20

# --- Pagination (PRD §2.3) ---
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Enumerated vocabularies pinned by PRD prose ---
# PRD §3.3: "which must be one of the two approved models, TI_BA_II_PLUS or HP_12C"
APPROVED_CALCULATOR_MODELS = ("TI_BA_II_PLUS", "HP_12C")
# PRD §3.2: "the enum order is the progression order: LEVEL_I has no
# prerequisite, and each later level requires its predecessor"
LEVEL_CODES_IN_ORDER = ("LEVEL_I", "LEVEL_II", "LEVEL_III")

__all__ = [
    "CLOCK_INITIAL_ISO",
    "PROGRAM_FEE_CENTS",
    "EDUCATION_WINDOW_MONTHS",
    "WORK_MIN_MONTHS",
    "WORK_MIN_HOURS",
    "SCHOLARSHIP_PCT_MAX",
    "SCORE_MIN",
    "SCORE_MAX",
    "MAX_ATTEMPTS_MIN",
    "MAX_ATTEMPTS_MAX",
    "BLACKOUT_BUFFER_DAYS",
    "RESCHEDULE_BASE_CENTS",
    "LATE_THRESHOLD_DAYS",
    "RESCHEDULE_LATE_SURCHARGE_CENTS",
    "PER_PRIOR_RESCHEDULE_CENTS",
    "PRIOR_CAP_COUNT",
    "RESCHEDULE_FEE_CAP_CENTS",
    "MIN_QUALIFYING_PCT",
    "MIN_REFERENCES",
    "REFERENCE_EXPIRY_DAYS",
    "APPEAL_WINDOW_DAYS",
    "SUSPENSION_DURATION_DAYS",
    "MIN_CHARTER_MONTHS",
    "ROLLING_WINDOW_DAYS",
    "DEFAULT_CE_CREDITS_REQUIRED_PER_YEAR",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
    "APPROVED_CALCULATOR_MODELS",
    "LEVEL_CODES_IN_ORDER",
]
