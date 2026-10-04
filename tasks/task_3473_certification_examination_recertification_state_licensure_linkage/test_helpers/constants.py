"""Domain thresholds and default fixtures values — every value is stated in
the PRD (sections noted per block)."""

# --- Logical clock (PRD §2.5) ------------------------------------------------
# "Before any call, the logical clock stands at exactly 2026-09-01T00:00:00Z"
CLOCK_DEFAULT_ISO = "2026-09-01T00:00:00Z"
CLOCK_ENDPOINT = "/_clock/set_current_utc"  # mounted OUTSIDE the /registry prefix

# --- Cognitive adaptive examination (PRD §3.4) --------------------------------
# "Once at least six items have been delivered" / "no more than twelve item
# responses" / "1.645 standard errors" / theta stored "rounded half up to four
# decimal places" on the unrounded value.
CAT_MIN_ITEMS = 6
CAT_MAX_ITEMS = 12
CAT_Z = 1.645
CAT_THETA_DECIMAL_PLACES = 4

# --- Retake budgeting (PRD §3.3 / §3.4) ---------------------------------------
# "the hard cap of six" attempts per basis; "once three or more attempts have
# been consumed" the remedial gate applies; the new window's start must fall
# "at least fifteen days after the most recent scored attempt's delivered_at"
# (equality allowed); an authorization "expires_on ninety calendar days later".
ATTEMPT_HARD_CAP = 6
REMEDIAL_GATE_CONSUMED = 3
RETAKE_WAIT_DAYS = 15
ATT_VALIDITY_DAYS = 90

# --- Education validity (PRD §3.3) --------------------------------------------
# "the date twenty-four calendar months after the completion date — both ends
# inclusive".
EDUCATION_VALIDITY_MONTHS = 24

# --- Psychomotor validity window (PRD §3.5) -----------------------------------
# "from the calendar date of its verified_at up to — but not including — the
# date twenty-four calendar months later".
PSYCHOMOTOR_WINDOW_MONTHS = 24

# --- Credential freshness at issue / license (PRD §3.5 / §3.8) ----------------
# "a cognitive pass delivered, or a psychomotor examination verified, more than
# twenty-four calendar months in the past" is stale; same for state exams.
CREDENTIAL_STALE_MONTHS = 24

# --- Certification lifecycle (PRD §3.5 / §3.7) --------------------------------
# "expires_on exactly twenty-four calendar months later, a lapse_deadline
# forty-eight calendar months beyond expiry".
CERTIFICATION_TERM_MONTHS = 24
LAPSE_DEADLINE_MONTHS = 48

# --- Recertification (PRD §3.6) -------------------------------------------------
# cycle window opens "twelve calendar months before the certification's current
# expires_on"; approval extends "twenty-four calendar months after the pinned
# cert_expires_on_at_creation"; the distributed cap is "the level's minimum for
# that component multiplied by one half and rounded up to the next whole hour".
RECERT_WINDOW_MONTHS = 12
RECERT_EXTENSION_MONTHS = 24
DISTRIBUTED_CAP_PCT = 0.5
CE_HOURS_INCREMENT = 0.5

# --- Audit sampling selector (PRD §3.6) ----------------------------------------
# "recert_seq is an exact multiple of three"; "within the sixty months before
# this submission"; "reaches at least twenty hours".
AUDIT_SEQ_MOD = 3
PRIOR_FAIL_LOOKBACK_MONTHS = 60
SINGLE_PROVIDER_FLAG_HOURS = 20

# --- Reentry tiers (PRD §3.7) ---------------------------------------------------
# "on or before the date twelve calendar months after expiry" -> TIER_CE_ONLY;
# "on or before the date twenty-four calendar months after expiry" ->
# TIER_REFRESHER; later is rejected. Equality belongs to the lower tier.
REENTRY_TIER1_MAX_LAPSE_MONTHS = 12
REENTRY_TIER2_MAX_LAPSE_MONTHS = 24

# --- Disciplinary due process (PRD §3.9) ----------------------------------------
# response window "thirty calendar days out" (inclusive); appeal deadline
# "thirty calendar days later" (inclusive); SUSPENSION_12M sets suspension_ends
# "twelve calendar months after finalized_at".
CASE_RESPONSE_WINDOW_DAYS = 30
CASE_APPEAL_WINDOW_DAYS = 30
SUSPENSION_12M_MONTHS = 12

# --- State licensure fees (PRD §3.1 / §3.8) -------------------------------------
# registry_share_bps "defaulting to 1500 — that is, fifteen percent"; share is
# rounded half up per fee line, then summed.
REGISTRY_SHARE_BPS_DEFAULT = 1500
BPS_DENOMINATOR = 10000

# --- Pagination (PRD §2.3) -------------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Canonical test data ---------------------------------------------------------
# The standard EMT level used across the design fixtures.
DEFAULT_LEVEL_PAYLOAD = {
    "code": "EMT",
    "display_name": "Emergency Medical Technician",
    "scope_summary": "BLS ambulance practice",
    "cognitive_cut_score": 0.66,
    "ce_total_hours": 40,
    "ce_national_min_hours": 20,
    "ce_local_min_hours": 10,
    "ce_individual_min_hours": 10,
    "hourly_model_total_hours": 40,
    "remedial_hours_required": 20,
    "refresher_hours_required": 24,
    "initial_application_fee_cents": 9800,
    "recert_application_fee_cents": 4500,
}

DEFAULT_POLICY_PAYLOAD = {
    "state_code": "WA",
    "adoption_mode": "NREMT_ACCEPTED",
    "accepted_level_codes": ["EMT"],
    "base_license_fee_cents": 9990,
    "national_verification_surcharge_cents": 9990,
}

# Canonical chain timeline (monotonic against the default clock):
#   completion 2026-09-01 -> window [09-02, 09-06] -> deliver 2026-09-03T12:00Z
#   -> psychomotor exam 2026-09-03 -> issue at 2026-09-04T00:00Z (expires
#   2028-09-04T00:00:00Z, lapse_deadline 2032-09-04T00:00:00Z).
DEFAULT_COMPLETION_DATE = "2026-09-01"
DEFAULT_SCHEDULED_START = "2026-09-02T00:00:00Z"
DEFAULT_SCHEDULED_END = "2026-09-06T00:00:00Z"
DEFAULT_DELIVERY_CLOCK = "2026-09-03T12:00:00Z"
DEFAULT_PSYCHOMOTOR_EXAM_DATE = "2026-09-03"
DEFAULT_ISSUE_CLOCK = "2026-09-04T00:00:00Z"
DEFAULT_RECERT_CLOCK = "2027-10-15T00:00:00Z"  # inside [2027-09-04, 2028-09-04]

DEFAULT_DIRECTOR_USER_ID = "dir-1"
DEFAULT_STATE_OFFICIAL_USER_ID = "so-1"
DEFAULT_ADMIN_USER_ID = "adm-1"
DEFAULT_HEARING_OFFICER_USER_ID = "ho-1"
DEFAULT_PROCTOR_USER_ID = "proctor-1"
