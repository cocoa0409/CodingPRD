"""Pinned constants from PRD.md / SCAFFOLD.yaml. Every named literal lives here.

No module may invent its own thresholds, weights, cutoffs, or status strings.
"""

# Logical clock boot instant (PRD 2.4): server boots at exactly this instant.
BOOT_ISO = "2026-09-01T00:00:00Z"

# Declared roles (PRD 2.1), spelled exactly.
ROLES = [
    "ProgramAdmin",
    "Nominator",
    "Assessor",
    "SelectionOfficer",
    "Nominee",
    "FacultyMentor",
    "CareerDirector",
    "Scholar",
]

# evaluation_weighted_score (PRD 3.2)
W_LEADERSHIP = 4
W_TEAMWORK = 3
W_GROUP_PRESENCE = 3
DIMENSION_FLOOR = 40
FLOOR_CAP_SCORE = 499

# nominee_round_score (PRD 3.2)
REQUIRED_EVALUATIONS_PER_ROUND = 2

# round_advancement_gate (PRD 3.2) — inclusive cutoffs
ROUND_1_CUTOFF = 600
ROUND_2_CUTOFF = 700
ROUND_3_CUTOFF = 800
ROUND_CUTOFFS = {1: ROUND_1_CUTOFF, 2: ROUND_2_CUTOFF, 3: ROUND_3_CUTOFF}

# cohort_fill_projection (PRD 3.4)
PROVISIONAL_OFFER_WEIGHT_BPS = 7500
BPS_DENOMINATOR = 10000

# offers (PRD 2.4)
OFFER_TTL_DAYS = 14

# cohort_program_fee_invoice (PRD 3.6)
FEE_BASE_CENTS = 250000
FEE_RATE_BPS = 125

# partner_standing_derivation (PRD 3.9)
PROBATION_RETENTION_FLOOR_BPS = 7000
RECOVERY_RETENTION_BPS = 8000

# renewal gate (PRD 3.9) — census variant
RENEWAL_MIN_RETENTION_BPS = 8000
RENEWAL_MIN_GRADUATION_BPS = 6000

# nomination quota / cohort size bounds (PRD 3.1, 3.3)
NOMINATION_QUOTA_MIN = 1
NOMINATION_QUOTA_MAX = 20
COHORT_SIZE_MIN = 3
COHORT_SIZE_MAX = 6

# mentor 15-minute meeting buffer (PRD 3.8)
MENTOR_BUFFER_MINUTES = 15

# pre-collegiate training curriculum (PRD 3.7)
TRAINING_MODULES = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"]
TRAINING_CATEGORY = {
    "T1": "ACADEMIC", "T2": "ACADEMIC", "T3": "ACADEMIC",
    "T4": "LEADERSHIP", "T5": "LEADERSHIP", "T6": "LEADERSHIP",
    "T7": "TEAM_BUILDING", "T8": "TEAM_BUILDING",
}
TRAINING_TOTAL = 8

# pagination (PRD 2.3)
PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

# enum value sets
NOMINEE_STATUSES = [
    "NOMINATED", "ROUND_1", "ROUND_2", "ROUND_3", "SELECTED",
    "WAITLISTED", "PLACED", "DROPPED", "WITHDRAWN",
]
PARTNER_KINDS = ["HIGH_SCHOOL", "COMMUNITY_ORG"]
COLLEGE_STATUSES = ["ACTIVE", "PROBATION", "LAPSED"]
AGREEMENT_STATUSES = ["DRAFT", "ACTIVE", "SUPERSEDED", "FULFILLED", "EXPIRED"]
COHORT_STATUSES = ["FORMING", "LOCKED", "MATRICULATED", "COMPLETED"]
OFFER_STATUSES = ["OFFERED", "ACCEPTED", "DECLINED", "EXPIRED", "REVOKED", "FULFILLED"]
ENROLLMENT_STATUSES = [
    "PRE_COLLEGIATE", "MATRICULATED", "RETAINED",
    "GRADUATED", "WITHDRAWN", "DISMISSED",
]
TERMINAL_ENROLLMENT = ["GRADUATED", "WITHDRAWN", "DISMISSED"]
STANDING_VALUES = ["GOOD_STANDING", "PROBATION"]
TRAINING_STATUSES = ["NOT_STARTED", "COMPLETED"]
MEETING_KINDS = ["COHORT", "INDIVIDUAL"]
INTERNSHIP_STATUSES = ["PROPOSED", "CONFIRMED", "COMPLETED", "TERMINATED"]
DECISIONS = ["ADVANCE", "WAITLIST", "DROP"]
RENEWAL_DECISIONS = ["RENEW", "LAPSE"]

# Declared scholar enrollment transitions driven by POST /scholars/{id}/lifecycle
# (PRD 3.7). PRE_COLLEGIATE -> MATRICULATED is deliberately absent: it happens
# only inside cohort matriculation, so requesting it is ERR_INVALID_STATE.
ENROLLMENT_TRANSITIONS = {
    "PRE_COLLEGIATE": ["WITHDRAWN"],
    "MATRICULATED": ["RETAINED", "WITHDRAWN", "DISMISSED"],
    "RETAINED": ["GRADUATED", "WITHDRAWN", "DISMISSED"],
    "GRADUATED": [],
    "WITHDRAWN": [],
    "DISMISSED": [],
}

# Internship transitions (PRD 3.8).
INTERNSHIP_TRANSITIONS = {
    "PROPOSED": ["CONFIRMED", "TERMINATED"],
    "CONFIRMED": ["COMPLETED", "TERMINATED"],
    "COMPLETED": [],
    "TERMINATED": [],
}
