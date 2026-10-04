"""Domain thresholds and tables stated in the contract.

Every value here is a number the contract itself fixes. Nothing in this module
is inferred: where the contract names a threshold without giving it a value
(for example the per-severity remediation window), the constant is deliberately
absent rather than guessed.
"""

# ─── Logical clock ─────────────────────────────────────────────────────────

#: The instant the logical clock reports on a fresh deployment.
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

# ─── Client risk score ─────────────────────────────────────────────────────

INDUSTRY_RISK_INDEX = {
    "TECH": 20,
    "FINANCIAL_SERVICES": 35,
    "HEALTHCARE": 25,
    "MANUFACTURING": 20,
    "RETAIL": 15,
    "ENERGY": 30,
    "PUBLIC_SECTOR": 10,
}

JURISDICTION_RISK_INDEX = {
    "US": 0,
    "GB": 5,
    "DE": 5,
    "CA": 5,
    "AU": 10,
    "IN": 15,
    "BR": 20,
    "CN": 25,
}

#: A country outside the table above carries this default jurisdiction risk.
DEFAULT_JURISDICTION_RISK = 10

#: Added to the base layer when the client is a public interest entity.
PIE_SURCHARGE = 15

# ─── Integrity / risk decay ────────────────────────────────────────────────

#: Age at or below this many whole months decays not at all.
DECAY_TIER_1_MONTHS = 12
#: Age above tier 1 and at or below this many months halves the impact.
DECAY_TIER_2_MONTHS = 24

DECAY_TIER_1_FACTOR = 1.0
DECAY_TIER_2_FACTOR = 0.5
DECAY_TIER_3_FACTOR = 0.25

#: The integrity score starts from a perfect 100.
INTEGRITY_MAX_SCORE = 100

SCORE_FLOOR = 0
SCORE_CEILING = 100

# ─── Acceptance decision bands ─────────────────────────────────────────────

#: An APPROVE requires the clamped combined risk score to be strictly below this.
APPROVE_RISK_CEILING = 70
#: A CONDITIONAL requires the combined score to be at least this and below 70.
CONDITIONAL_RISK_FLOOR = 50

# ─── Rotation regime ───────────────────────────────────────────────────────

#: A gap of at most this many whole months keeps a service run continuous.
ROTATION_GAP_TOLERANCE_MONTHS = 12

#: Time-on limit in whole months; 0 means unlimited service.
TIME_ON_LIMIT_MONTHS = {
    "STANDARD": {
        "LEAD_PARTNER": 84,
        "CONCURRING_PARTNER": 84,
        "EQ_REVIEWER": 84,
        "ENGAGEMENT_MANAGER": 0,
    },
    "PIE_ACCELERATED": {
        "LEAD_PARTNER": 60,
        "CONCURRING_PARTNER": 60,
        "EQ_REVIEWER": 84,
        "ENGAGEMENT_MANAGER": 0,
    },
}

#: Time-off owed once an assignment ends, in whole months.
TIME_OFF_MONTHS = {
    "STANDARD": {
        "LEAD_PARTNER": 24,
        "CONCURRING_PARTNER": 24,
        "EQ_REVIEWER": 36,
        "ENGAGEMENT_MANAGER": 12,
    },
    "PIE_ACCELERATED": {
        "LEAD_PARTNER": 60,
        "CONCURRING_PARTNER": 60,
        "EQ_REVIEWER": 36,
        "ENGAGEMENT_MANAGER": 12,
    },
}

# ─── Workload points ───────────────────────────────────────────────────────

BASE_WORKLOAD_POINTS = {
    "LEAD_PARTNER": 40,
    "CONCURRING_PARTNER": 25,
    "EQ_REVIEWER": 20,
    "ENGAGEMENT_MANAGER": 15,
}

TIER_MULTIPLIER = {
    "LOW": 1.0,
    "MODERATE": 1.25,
    "HIGH": 1.5,
    "SIGNIFICANT": 2.0,
}

#: The highest tier whose threshold the base sum strictly exceeds supplies its
#: points; a base sum at or below the lowest threshold adds nothing.
OVERLOAD_TIERS = [
    {"threshold": 60, "points": 5},
    {"threshold": 80, "points": 10},
]

MAX_WORKLOAD_POINTS_DEFAULT = 100

# ─── Non-audit fee pool ────────────────────────────────────────────────────

#: Each fee is rounded to the nearest whole dollar before it joins the pool.
ROUNDING_UNIT_CENTS = 100

# ─── Independence posture ladder ───────────────────────────────────────────

#: Two live HIGH findings freeze an engagement.
FROZEN_HIGH_MIN = 2
#: Network risk points at or above this freeze an engagement.
FROZEN_NETWORK_MIN = 12
#: Network risk points at or above this restrict an engagement.
RESTRICTED_NETWORK_MIN = 6

# ─── Financial-interest materiality ────────────────────────────────────────

MATERIALITY_CENTS = {
    "PARTNER": 500000,
    "DIRECTOR": 100000,
    "SENIOR_MANAGER": 50000,
    "MANAGER": 25000,
}

#: An indirect holding (a mutual fund) is compared against twice the threshold.
INDIRECT_MULTIPLIER = 2

#: Instruments treated as a direct holding.
DIRECT_INSTRUMENTS = ("EQUITY", "DEBT", "DERIVATIVE", "TRUST")
#: The one instrument treated as an indirect holding.
INDIRECT_INSTRUMENT = "MUTUAL_FUND"

# ─── Cooling-off windows ───────────────────────────────────────────────────

COOLING_OFF_MONTHS = {
    "IMMEDIATE_FAMILY_EMPLOYED_BY_CLIENT": 0,
    "FORMER_FIRM_PROFESSIONAL_JOINED_CLIENT": 12,
    "PROFESSIONAL_PRIOR_CLIENT_EMPLOYEE": 24,
    "CLIENT_BOARD_MEMBERSHIP": 0,
}

# ─── Network risk weighting ────────────────────────────────────────────────

NETWORK_TIER_WEIGHT = {
    "MEMBER_FIRM": 3,
    "CORRESPONDENT": 2,
    "ALLIANCE": 1,
}

NETWORK_RISK_CEILING = 50

#: An affiliate is suspended once this many of its attestations are breached.
AFFILIATE_SUSPENSION_BREACHES = 3

# ─── Inspection response windows ───────────────────────────────────────────

RESPONSE_WINDOW_DAYS = {
    "PCAOB": 30,
    "SEC": 21,
    "LOCAL_REGULATOR": 45,
    "INTERNAL_QC": 15,
}

#: A review carrying this many deficiencies or more has its window halved.
DEFICIENCY_HALVING_THRESHOLD = 5

# ─── Review scheduling buffer ──────────────────────────────────────────────

#: A successor review must start at least this many days after the predecessor's due date.
REVIEW_BUFFER_DAYS = 5

# ─── Remediation budget ────────────────────────────────────────────────────

#: A finding may re-enter remediation while it carries fewer than this many failures.
MAX_REMEDIATION_ATTEMPTS = 3

# ─── Payload defaults used by the factories ────────────────────────────────

TEST_DEFAULTS = {
    "CLOCK": DEFAULT_CLOCK,
    "ENGAGEMENT_FISCAL_YEAR_END": "2026-12-31T00:00:00Z",
    "PROPOSED_BY": "P. Rao",
    "MAX_WORKLOAD_POINTS": 100,
}
