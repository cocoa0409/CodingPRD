"""Domain constants for the Meat & Poultry Inspection API.

Every value below is pinned by PRD prose: the logical-clock boot value and
pagination bounds (PRD §2.3/§2.4), the derived-score formulas (PRD §2.10), the
sampling and escalation windows (PRD §3.3/§3.6), the recall class requirements
(PRD §3.8), the label documentation minimums (PRD §3.7), the travel buffer
(PRD §3.2), the withdrawal conditions (PRD §3.4) and the text-length minimums
(PRD §3.4/§3.9). The generic ``NON_EXISTENT_UUID`` comes from the framework.
"""

# ── Role strings (the seven declared roles, PRD §2.1) ────────────────────────

ROLE_ESTABLISHMENT_MANAGER = "EstablishmentManager"
ROLE_INSPECTOR = "Inspector"
ROLE_SUPERVISORY_REVIEWER = "SupervisoryReviewer"
ROLE_DISTRICT_MANAGER = "DistrictManager"
ROLE_LABEL_OFFICER = "LabelOfficer"
ROLE_RECALL_COORDINATOR = "RecallCoordinator"
ROLE_PROGRAM_ADMINISTRATOR = "ProgramAdministrator"

ALL_ROLES = (
    ROLE_ESTABLISHMENT_MANAGER,
    ROLE_INSPECTOR,
    ROLE_SUPERVISORY_REVIEWER,
    ROLE_DISTRICT_MANAGER,
    ROLE_LABEL_OFFICER,
    ROLE_RECALL_COORDINATOR,
    ROLE_PROGRAM_ADMINISTRATOR,
)

# ── Logical clock (PRD §2.4) ─────────────────────────────────────────────────

# "Before any call to the clock endpoint, the logical clock reads exactly
# 2026-09-01T00:00:00Z; there is no wall-clock fallback at startup or at any
# later point."
CLOCK_START_ISO = "2026-09-01T00:00:00Z"

# ── Pagination (PRD §2.3) ────────────────────────────────────────────────────

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# ── Establishment risk scores (PRD §2.10) ────────────────────────────────────

# rolling_risk_score window: "issued_at lies within the trailing 90 days".
RISK_ROLLING_WINDOW_DAYS = 90

# Family weights: 2 SANITATION, 3 HACCP, 5 HUMANE, 1 LABELING, 1 OTHER.
RISK_WEIGHT_SANITATION = 2
RISK_WEIGHT_HACCP = 3
RISK_WEIGHT_HUMANE = 5
RISK_WEIGHT_LABELING = 1
RISK_WEIGHT_OTHER = 1

FAMILY_RISK_WEIGHTS = {
    "SANITATION": RISK_WEIGHT_SANITATION,
    "HACCP": RISK_WEIGHT_HACCP,
    "HUMANE": RISK_WEIGHT_HUMANE,
    "LABELING": RISK_WEIGHT_LABELING,
    "OTHER": RISK_WEIGHT_OTHER,
}

# Recency bands: "3 when the age is at most 30 days, 2 when the age is 31 to
# 60 days, and 1 when the age is 61 to 90 days; a record older than 90 days
# contributes 0."
RECENCY_BAND_1_MAX_DAYS = 30
RECENCY_BAND_2_MAX_DAYS = 60
RECENCY_FACTOR_BAND_1 = 3
RECENCY_FACTOR_BAND_2 = 2
RECENCY_FACTOR_BAND_3 = 1

# ── Compliance score (PRD §2.10) ─────────────────────────────────────────────

# family penalty = round_half_up(open_F * 10 / 3, 1); score = 100 - sum.
NR_PENALTY_NUMERATOR = 10
NR_PENALTY_DENOMINATOR = 3
COMPLIANCE_PASS_THRESHOLD = 80.0

# ── Enforcement priority score (PRD §2.10) ───────────────────────────────────

# base = 10 * open_nr_count + 25 * suspension_count; tier from base alone.
OPEN_NR_POINTS = 10
SUSPENSION_POINTS = 25
TIER_HIGH_MIN_BASE = 100
TIER_MEDIUM_MIN_BASE = 50
BONUS_HIGH = 15
BONUS_MEDIUM = 10
BONUS_LOW = 5

# ── NR escalation (PRD §3.3) ─────────────────────────────────────────────────

# "If that count reaches 3 — exactly at threshold fires" within "the trailing
# 90 days of the logical clock inclusive of the boundary day".
NR_ESCALATION_THRESHOLD = 3
NR_ESCALATION_WINDOW_DAYS = 90

# ── Pathogen categorization (PRD §3.6) ───────────────────────────────────────

SAMPLING_WINDOW_DAYS = 90
MIN_SAMPLES_FOR_CATEGORIZATION = 10
SALMONELLA_STANDARD_RATE = 0.10
CAMPYLOBACTER_STANDARD_RATE = 0.15

# ── Recall class requirements (PRD §3.8) ─────────────────────────────────────

CLASS_I_MIN_CHECKS = 10
CLASS_I_MIN_RATIO = 0.95
CLASS_II_MIN_CHECKS = 5
CLASS_II_MIN_RATIO = 0.80
CLASS_III_MIN_CHECKS = 4
CLASS_III_MIN_RATIO = 0.75

RECALL_CLASS_REQUIREMENTS = {
    "CLASS_I": (CLASS_I_MIN_CHECKS, CLASS_I_MIN_RATIO),
    "CLASS_II": (CLASS_II_MIN_CHECKS, CLASS_II_MIN_RATIO),
    "CLASS_III": (CLASS_III_MIN_CHECKS, CLASS_III_MIN_RATIO),
}

# ── Label documentation minimums (PRD §3.7) ──────────────────────────────────

DOCS_GRASS_FED = 2
DOCS_NO_ANTIBIOTICS = 2
DOCS_ORGANIC = 3
DOCS_BREED_SPECIFIC = 1

LABEL_DOC_MINIMUMS = {
    "GRASS_FED": DOCS_GRASS_FED,
    "NO_ANTIBIOTICS": DOCS_NO_ANTIBIOTICS,
    "ORGANIC": DOCS_ORGANIC,
    "BREED_SPECIFIC": DOCS_BREED_SPECIFIC,
}

# ── Assignment temporal rules (PRD §3.2) ─────────────────────────────────────

# "an inspector may not be scheduled at two different establishments within
# 30 minutes of one another".
TRAVEL_BUFFER_MINUTES = 30

# ── Withdrawal eligibility (PRD §3.4) ────────────────────────────────────────

# "an IN_EFFECT suspension whose effective_at is at least 30 days before the
# logical clock, or ... at least 2 of its suspension actions with status
# IN_EFFECT or LIFTED were created within the trailing 365 days".
WITHDRAWAL_ABATEMENT_DAYS = 30
WITHDRAWAL_SUSPENSION_COUNT = 2
WITHDRAWAL_SUSPENSION_WINDOW_DAYS = 365

# ── Text-length minimums (PRD §3.4 / §3.9) ───────────────────────────────────

# appeal "grounds, which must be at least 10 characters long".
APPEAL_GROUNDS_MIN_CHARS = 10
# lift "requires abatement_evidence of at least 20 characters".
ABATEMENT_EVIDENCE_MIN_CHARS = 20
