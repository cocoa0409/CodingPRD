"""Domain thresholds and pinned constants.

Every value below is stated verbatim in PRD.md; the trailing comment cites the
section that pins it. No unused constants are kept here.
"""

# --- Logical clock (PRD §2.4) ---------------------------------------------
# "At server startup the logical clock reads exactly 2026-09-01T00:00:00Z"
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- Research momentum (PRD §3.2) ------------------------------------------
# "each entry's points multiplied by 0.85 raised to the number of full weeks"
RESEARCH_DECAY_PER_WEEK = 0.85
# "the concept's momentum ... must be at least 40.0 — the gate is inclusive"
RESEARCH_SCORE_MIN = 40.0
# "has not reached ENGINEERING_LOCKED within 120 days of its creation"
CONCEPT_MAX_AGE_DAYS = 120

# --- Prototype cycle (PRD §3.2) --------------------------------------------
# "A round left OPEN for more than 21 days is expired by the run-review"
ROUND_MAX_OPEN_DAYS = 21
# "The per-cycle budget of 4 rounds"
MAX_ROUNDS_PER_CYCLE = 4
# "a score of at least 75 — the boundary is inclusive"
ROUND_PASS_SCORE = 75

# --- Claim substantiation (PRD §3.4) ---------------------------------------
# "The study's margin must be at least 0.15 — again inclusive"
CLAIM_MIN_MARGIN = 0.15
# "sample_size, which must be at least 30 — the gate is inclusive"
CLAIM_MIN_SAMPLES = 30

# --- Media efficiency ratio (PRD §3.5) --------------------------------------
# "multiplied by 0.85, which is one minus the 0.15 agency commission rate"
AGENCY_COMMISSION_RATE = 0.15
# "SCALE requires the settled ratio to be at least 2.0 — inclusive"
MER_SCALE_MIN = 2.0
# "A test still AIRING more than 28 days after aired_at ... is killed"
MEDIA_DECISION_MAX_DAYS = 28

# --- Litigation reserve & exposure (PRD §3.8) -------------------------------
# "the claim amount multiplied by the 0.30 prior-adverse probability"
PRIOR_ADVERSE_PROB = 0.30
# "the severity weights — 2 for LOW, 5 for MED, 9 for HIGH"
CASE_WEIGHT_LOW = 2
CASE_WEIGHT_MED = 5
CASE_WEIGHT_HIGH = 9
# "plus three times the severity weights summed over all cases in JUDGED_ADVERSE"
ADVERSE_WEIGHT_MULTIPLIER = 3
# "an index of 20 or more is SEVERE, an index of 8 or more ... is ELEVATED"
EXPOSURE_ELEVATED_MIN = 8
EXPOSURE_SEVERE_MIN = 20
# "the difference between the current review_index and
#  guarded_since_review_index is 2 or more at the moment the review runs"
GUARDED_GRACE_REVIEWS = 2

# --- Partner suspension penalty (PRD §3.3) ----------------------------------
# "penalty_cents equal to its committed_units multiplied by 150 cents per unit"
SHORTFALL_PENALTY_CENTS = 150

# --- Replenishment (PRD §3.7) -----------------------------------------------
# "three weeks of cover at the reported velocity"
COVER_WEEKS = 3
# "weekly_velocity must be at least 50 units per week — inclusive"
REPLENISH_MIN_WEEKLY_UNITS = 50

# --- Line refresh cadence (PRD §3.9 steps 9-10) ------------------------------
# "every variant RETAIL_LIVE whose retail_live_at is more than 240 days"
MODEL_MAX_AGE_DAYS = 240
# "every variant REFRESH_CANDIDATE whose refresh_candidate_at is more than 30 days"
REFRESH_GRACE_DAYS = 30

# --- Tooling windows (PRD §3.3) ---------------------------------------------
# "Tooling occupies a 14-day window"
TOOLING_WINDOW_DAYS = 14
# "a partner runs at most 2 tooling engagements in parallel"
TOOLING_PARALLEL_SLOTS = 2

# --- Pagination (PRD §2.3) ---------------------------------------------------
# "when omitted it defaults to 10, with a minimum of 1 and a maximum of 100"
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
# "The offset parameter ... defaults to 0"
PAGINATION_DEFAULT_OFFSET = 0

__all__ = [
    "CLOCK_DEFAULT_ISO",
    "RESEARCH_DECAY_PER_WEEK",
    "RESEARCH_SCORE_MIN",
    "CONCEPT_MAX_AGE_DAYS",
    "ROUND_MAX_OPEN_DAYS",
    "MAX_ROUNDS_PER_CYCLE",
    "ROUND_PASS_SCORE",
    "CLAIM_MIN_MARGIN",
    "CLAIM_MIN_SAMPLES",
    "AGENCY_COMMISSION_RATE",
    "MER_SCALE_MIN",
    "MEDIA_DECISION_MAX_DAYS",
    "PRIOR_ADVERSE_PROB",
    "CASE_WEIGHT_LOW",
    "CASE_WEIGHT_MED",
    "CASE_WEIGHT_HIGH",
    "ADVERSE_WEIGHT_MULTIPLIER",
    "EXPOSURE_ELEVATED_MIN",
    "EXPOSURE_SEVERE_MIN",
    "GUARDED_GRACE_REVIEWS",
    "SHORTFALL_PENALTY_CENTS",
    "COVER_WEEKS",
    "REPLENISH_MIN_WEEKLY_UNITS",
    "MODEL_MAX_AGE_DAYS",
    "REFRESH_GRACE_DAYS",
    "TOOLING_WINDOW_DAYS",
    "TOOLING_PARALLEL_SLOTS",
    "PAGINATION_DEFAULT_LIMIT",
    "PAGINATION_MIN_LIMIT",
    "PAGINATION_MAX_LIMIT",
    "PAGINATION_DEFAULT_OFFSET",
]
