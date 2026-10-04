"""Domain thresholds and boundaries stated by the PRD.

Every constant here is a number the PRD names in prose or inside a stated rule;
they exist so tests and fixtures can target a boundary without recomputing it.
"""

# --- governance clock --------------------------------------------------------

CLOCK_START_UTC = "2026-09-01T00:00:00Z"
CLOCK_BASE = "2026-09-15T00:00:00Z"

# --- community health --------------------------------------------------------

HEALTH_INDEX_MAX = 100.00
HEALTH_INDEX_MIN = 0.00
QUARANTINE_HEALTH_LINE = 40.00
REINSTATEMENT_HEALTH_FLOOR = 70.00
INACTIVITY_PENALTY_PER_MODERATOR = 2.5

TIER_WEIGHT = {1: 1.0, 2: 1.5, 3: 2.0}
REPORT_WEIGHT_DIVISOR = 3
TIER_1_OPEN_REPORT_WEIGHT = 0.33
TIER_2_OPEN_REPORT_WEIGHT = 0.50
TIER_3_OPEN_REPORT_WEIGHT = 0.67

# --- community posture gates -------------------------------------------------

SANCTION_INDEX_RESTRICTED_GATE = 0.60
SANCTION_INDEX_NEGOTIATION_GATE = 0.80
SANCTION_AGE_DAYS_FOR_INDEX = 30

# --- enforcement ladder ------------------------------------------------------

ENFORCEMENT_TIER_2_AT = 2
ENFORCEMENT_TIER_3_AT = 3

# --- effective enforcement tier ---------------------------------------------

TIER_CAP = 5
MATERIAL_EDIT_BAND_FLOOR = 3
CONFIDENCE_CREDIT_MIN = 0.60
PRECEDENT_APPROVAL_MIN = 3
OUTCOME_BASE = {
    "KEEP": 0,
    "REPORT_REJECTED": 0,
    "WARNING_ISSUED": 1,
    "REMOVE": 2,
    "LOCK": 3,
    "MUTE_ISSUED": 4,
    "BAN_ISSUED": 5,
}

# --- legitimacy scoring ------------------------------------------------------

LEGITIMACY_PENALTY_CAP = 40
LEGITIMACY_LOW_CEILING = 30
LEGITIMACY_MID_CEILING = 60
LEGITIMACY_BAND_WEIGHT = {"HIGH": 1.0, "MID": 1.5, "LOW": 2.0}
LEGITIMACY_TYPE_WEIGHT_AUTO = 1.5
LEGITIMACY_AGE_WEIGHT_ANCIENT = 1.0
LEGITIMACY_AGE_WEIGHT_RECENT = 1.5
LEGITIMACY_ANCIENT_DAYS = 365
LEGITIMACY_OLD_BASE_DAYS = 30
LEGITIMACY_BASE_OLD = 70
LEGITIMACY_BASE_FRESH = 50

# --- brigading ---------------------------------------------------------------

EVIDENCE_COMPLETE_MIN_RATIO = 0.30
BREAKDOWN_LINK_BREADTH_STEPS = (5, 10, 20)
PARTICIPANT_ESCALATOR = 50
OVERLAP_ESCALATOR = 0.60
SEVERITY_BAND_CAP = 5
PER_CLUSTER_PENALTY_CAP = 30
ESCALATION_HEALTH_ESCALATOR = 60

# --- sanction award points ---------------------------------------------------

ARMOR_POINTS = 30
REFUND_ADDEND = 120
REFUND_CAP = 150
AWARD_TIER_BASE = {"TIER_1": 150, "TIER_2": 250, "TIER_3": 400}
AWARD_REGISTRY_TIER_2_MAX = 2

# --- karma -------------------------------------------------------------------

KARMA_START = 100
KARMA_PENALTY_PER_COMMUNITY = 3
KARMA_FLOOR = 50

# --- temporal windows --------------------------------------------------------

INACTIVITY_WINDOW_DAYS = 90
QUARANTINE_CLOCK_DAYS = 90
APPEAL_FILING_WINDOW_DAYS = 7
APPEAL_DECISION_DEADLINE_DAYS = 30
BRIGADE_COOLING_OFF_DAYS = 7
HANDOVER_DEADLINE_DAYS = 30
NEGOTIATION_QUARANTINE_DAYS = 30
WATCHDOG_REFERRAL_DAYS = 30
WATCHDOG_MIN_REFERRALS = 2
PROTEST_MORATORIUM_DAYS = 7

# --- quorum ------------------------------------------------------------------

MIN_PROTEST_QUORUM = 2
PROTEST_CROSS_POWER_MIN = 2

# --- pagination --------------------------------------------------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- rule bands --------------------------------------------------------------

ALL_AGES_BAND = 1
MATURE_BAND = 2
ADULT_ONLY_BAND = 3
SITEWIDE_FLOOR_BAND = 2

# --- defaults used by factories ---------------------------------------------

TEST_DEFAULTS = {
    "COMMUNITY_NAME": "r/TestCommunity",
    "COMMUNITY_DESCRIPTION": "Test community",
    "RULE_CODE": "R-1",
    "RULE_TEXT": "Be civil",
    "POST_TITLE": "Test post",
    "POST_BODY": "Test body",
    "ACCOUNT_HANDLE": "test-handle",
    "DETECTION_OVERLAP_RATIO": 0.20,
    "DETECTION_CONFIDENCE": 0.90,
    "DETECTION_SEVERITY_BAND": 5,
    "FOUNDING_MODERATOR_ID": "mod-alpha",
    "SUBJECT_ACCOUNT_ID": "u-target",
}