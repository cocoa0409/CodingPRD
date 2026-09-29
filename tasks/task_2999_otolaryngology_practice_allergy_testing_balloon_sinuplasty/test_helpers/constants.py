"""Domain constants for the otolaryngology practice service.

Every literal in this module is transcribed from the PRD. Test code and fixture
code MUST import these symbols rather than retyping literals, so that a single
spelling mistake cannot silently diverge between two call sites.
"""

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_PRACTICE_ADMIN = "PracticeAdmin"
ROLE_OTOLARYNGOLOGIST = "Otolaryngologist"
ROLE_ALLERGY_NURSE = "AllergyNurse"
ROLE_AUDIOLOGIST = "Audiologist"
ROLE_STERILE_PROCESSING_TECH = "SterileProcessingTech"
ROLE_PAYER_LIAISON = "PayerLiaison"

ALL_ROLES = (
    ROLE_PRACTICE_ADMIN,
    ROLE_OTOLARYNGOLOGIST,
    ROLE_ALLERGY_NURSE,
    ROLE_AUDIOLOGIST,
    ROLE_STERILE_PROCESSING_TECH,
    ROLE_PAYER_LIAISON,
)

# A syntactically valid but undeclared role string, used to prove that a
# non-blank role outside the declared set is refused with ERR_ROLE_NOT_PERMITTED.
UNDECLARED_ROLE = "Receptionist"

# ---------------------------------------------------------------------------
# Acting identities.
#
# PRD 2.1: every role carries an opaque identity and no endpoint performs an
# ownership check against a resource primary key, so these strings are free
# choices. They matter only where the PRD compares two acting identifiers with
# each other (segregation of duties, reprocessing technician, booking
# physician), which is why every actor gets its own distinct value.
# ---------------------------------------------------------------------------
USER_ADMIN_1 = "u_admin_1"
USER_ADMIN_2 = "u_admin_2"
USER_ENT_1 = "u_ent_1"
USER_ENT_2 = "u_ent_2"
USER_NURSE_1 = "u_nurse_1"
USER_NURSE_2 = "u_nurse_2"
USER_AUD_1 = "u_aud_1"
USER_AUD_2 = "u_aud_2"
USER_TECH_1 = "u_tech_1"
USER_TECH_2 = "u_tech_2"
USER_LIAISON_1 = "u_liaison_1"
USER_LIAISON_2 = "u_liaison_2"
# Alternate opaque identifiers for the payer-liaison actor.
USER_PL_1 = "u_pl_1"
USER_PL_2 = "u_pl_2"

# ---------------------------------------------------------------------------
# The logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = "2026-08-01T00:00:00Z"
CLOCK_DEFAULT_DATE = "2026-08-01"

# ---------------------------------------------------------------------------
# Payer policy defaults (PRD 3.1)
# ---------------------------------------------------------------------------
POLICY_DEFAULTS = {
    "requires_prior_auth": True,
    "min_medical_management_days": 28,
    "requires_ct_within_months": 12,
    "min_documented_criteria": 3,
    "max_balloon_devices": 2,
    "covered_pct_bps": 8000,
    "allergy_serum_covered": True,
    "observation_floor_minutes": 20,
    "device_trial_days": 30,
    "restock_fee_bps": 1500,
    "restock_fee_floor_cents": 12500,
    "auth_validity_days": 90,
    "appliance_covered": True,
}

# ---------------------------------------------------------------------------
# Panels, methods and billing (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
PANEL_ENV_36 = "ENV_36"
PANEL_FOOD_24 = "FOOD_24"
PANEL_MOLD_12 = "MOLD_12"
PANEL_VENOM_5 = "VENOM_5"

ANTIGEN_COUNT_BY_PANEL = {
    PANEL_ENV_36: 36,
    PANEL_FOOD_24: 24,
    PANEL_MOLD_12: 12,
    PANEL_VENOM_5: 5,
}

METHOD_SKIN_PRICK = "SKIN_PRICK"
METHOD_INTRADERMAL = "INTRADERMAL"
METHOD_SERUM_IGE = "SERUM_IGE"

SKIN_METHODS = (METHOD_SKIN_PRICK, METHOD_INTRADERMAL)

UNIT_PRICE_CENTS_BY_METHOD = {
    METHOD_SKIN_PRICK: 1775,
    METHOD_INTRADERMAL: 2240,
    METHOD_SERUM_IGE: 3310,
}

TIER_FACTOR_SMALL = "1.0000"   # antigen_count <= 12
TIER_FACTOR_MEDIUM = "0.9250"  # antigen_count 13..30
TIER_FACTOR_LARGE = "0.8500"   # antigen_count >= 31

# Observation window bases in whole minutes (PRD 3.2)
OBSERVATION_BASE_SKIN_PRICK = 30
OBSERVATION_BASE_INTRADERMAL = 40
OBSERVATION_BASE_DOSE = 30
OBSERVATION_FLOOR_ELEVATED_RISK = 60
OBSERVATION_FLOOR_HIGH_STEP = 45
OBSERVATION_FLOOR_PHYSICIAN_PRESENT = 90
OBSERVATION_MINUTES_SERUM = 0

# Antihistamine washout (PRD 3.2)
WASHOUT_HOURS = 72

# ---------------------------------------------------------------------------
# Allergy test order status (PRD 3.2, 3.3)
# ---------------------------------------------------------------------------
ORDER_ORDERED = "ORDERED"
ORDER_ADMINISTERED = "ADMINISTERED"
ORDER_SERUM_PENDING = "SERUM_PENDING"
ORDER_READ = "READ"
ORDER_ABORTED = "ABORTED"

ABORT_REASON_DERMATOGRAPHISM = "DERMATOGRAPHISM_DETECTED"
ABORT_REASON_SYSTEMIC_REACTION = "SYSTEMIC_REACTION"

# ---------------------------------------------------------------------------
# Patient risk model (PRD 3.1)
# ---------------------------------------------------------------------------
RISK_BASE = 5
RISK_PER_PRIOR_REACTION = 15
RISK_PRIOR_REACTION_CAP = 3
RISK_SENSITIZED_CAP = 20
RISK_PEDIATRIC_BONUS = 8
RISK_PEDIATRIC_AGE_MONTHS = 72
RISK_NO_EPINEPHRINE_BONUS = 10
RISK_MIN = 0
RISK_MAX = 100

RISK_VARIANT_PROVISIONAL = "PROVISIONAL"
RISK_VARIANT_POST_REACTION = "POST_REACTION"

SUPERVISION_TIER_STANDARD = "STANDARD"
SUPERVISION_TIER_PHYSICIAN_PRESENT = "PHYSICIAN_PRESENT"

# Risk score at or above which the supervision tier becomes PHYSICIAN_PRESENT.
SUPERVISION_TIER_THRESHOLD = 60
# Risk score at or above which the observation window is escalated and the
# epinephrine gate applies.
RISK_SAFETY_THRESHOLD = 45

# Reaction decay factors keyed by the inclusive day band (PRD 3.1)
DECAY_FRESH = "1.00"   # <= 30 days
DECAY_MID = "0.60"     # 31..90 days
DECAY_STALE = "0.30"   # 91..180 days
DECAY_EXPIRED = "0.00"  # > 180 days
REACTION_EVENT_WEIGHT = 20

# ---------------------------------------------------------------------------
# Immunotherapy status (PRD 3.1, 3.5)
# ---------------------------------------------------------------------------
IMMUNO_STATUS_NONE = "NONE"
IMMUNO_STATUS_BUILD_UP = "BUILD_UP"
IMMUNO_STATUS_MAINTENANCE = "MAINTENANCE"
IMMUNO_STATUS_HELD = "HELD"

MAINTENANCE_STEP_THRESHOLD = 7  # step >= 7 is MAINTENANCE, <= 6 is BUILD_UP
MAX_ESCALATION_STEP = 12
MIN_ESCALATION_STEP = 1

# ---------------------------------------------------------------------------
# Vials and doses (PRD 3.5)
# ---------------------------------------------------------------------------
DILUTION_YELLOW = "YELLOW_1_10"
DILUTION_BLUE = "BLUE_1_100"
DILUTION_GREEN = "GREEN_1_1000"
DILUTION_SILVER = "SILVER_1_10000"

VIAL_MIXED = "MIXED"
VIAL_LABEL_VERIFIED = "LABEL_VERIFIED"
VIAL_IN_USE = "IN_USE"
VIAL_EXHAUSTED = "EXHAUSTED"
VIAL_DISCARDED = "DISCARDED"

DISCARD_REASON_BEYOND_USE_DATE = "BEYOND_USE_DATE"
DISCARD_REASON_CONTAMINATION = "CONTAMINATION"
DISCARD_REASON_SUPERSEDED = "SUPERSEDED"

VIAL_DEFAULT_VOLUME_ML = 5.00
VIAL_MIN_VOLUME_ML = 1.00
VIAL_MAX_VOLUME_ML = 10.00
VIAL_EXHAUSTION_THRESHOLD_ML = 0.05
VIAL_MAX_SHELF_DAYS = 365

DOSE_ADMINISTERED = "ADMINISTERED"
DOSE_CLEARED = "CLEARED"
DOSE_REACTION_HELD = "REACTION_HELD"
DOSE_VOIDED = "VOIDED"

# Doses whose volume counts toward volume_ml_dispensed_total (PRD 2.10)
DOSE_STATES_COUNTED_IN_LEDGER = (DOSE_ADMINISTERED, DOSE_CLEARED, DOSE_REACTION_HELD)

VOID_REASON_DRAWN_IN_ERROR = "DRAWN_IN_ERROR"
VOID_REASON_WRONG_VIAL = "WRONG_VIAL"
VOID_REASON_PATIENT_DEFERRED = "PATIENT_DEFERRED"
VOID_WINDOW_MINUTES = 15

# Dose volume in millilitres by effective escalation step (PRD 3.5)
DOSE_VOLUME_BY_STEP = {
    1: 0.05,
    2: 0.10,
    3: 0.20,
    4: 0.30,
    5: 0.40,
    6: 0.50,
    7: 0.05,
    8: 0.10,
    9: 0.20,
    10: 0.30,
    11: 0.40,
    12: 0.50,
}

# Required dilution by pre-rollback escalation step (PRD 3.5)
REQUIRED_DILUTION_BUILD_UP = DILUTION_BLUE     # step <= 6
REQUIRED_DILUTION_MAINTENANCE = DILUTION_YELLOW  # step >= 7

ROLLBACK_GAP_DAYS_BUILD_UP = 14
ROLLBACK_STEPS_BUILD_UP = 2
ROLLBACK_GAP_DAYS_MAINTENANCE = 28
ROLLBACK_STEPS_MAINTENANCE = 3
HIGH_STEP_OBSERVATION_THRESHOLD = 9

# ---------------------------------------------------------------------------
# Sinuplasty cases (PRD 3.6)
# ---------------------------------------------------------------------------
LATERALITY_LEFT = "LEFT"
LATERALITY_RIGHT = "RIGHT"
LATERALITY_BILATERAL = "BILATERAL"

SINUS_MAXILLARY = "MAXILLARY"
SINUS_FRONTAL = "FRONTAL"
SINUS_SPHENOID = "SPHENOID"

CASE_DRAFT = "DRAFT"
CASE_DOCUMENTED = "DOCUMENTED"
CASE_AUTH_SUBMITTED = "AUTH_SUBMITTED"
CASE_INFO_REQUESTED = "INFO_REQUESTED"
CASE_AUTHORIZED = "AUTHORIZED"
CASE_DENIED = "DENIED"
CASE_AUTH_EXPIRED = "AUTH_EXPIRED"
CASE_SCHEDULED = "SCHEDULED"
CASE_COMPLETED = "COMPLETED"

CANDIDACY_UNDETERMINED = "UNDETERMINED"
CANDIDACY_ELIGIBLE = "ELIGIBLE"
CANDIDACY_INELIGIBLE = "INELIGIBLE"

EVAL_VARIANT_POLICY_STRICT = "POLICY_STRICT"
EVAL_VARIANT_CLINICAL_BROAD = "CLINICAL_BROAD"

THERAPY_INCS = "INCS"
THERAPY_ABX = "ABX"
THERAPY_SALINE = "SALINE"
THERAPY_ORAL_STEROID = "ORAL_STEROID"

CRITERION_CT_OPACIFICATION = "CT_OPACIFICATION"
CRITERION_SNOT22_GE_20 = "SNOT22_GE_20"
CRITERION_FAILED_INCS = "FAILED_INCS"
CRITERION_FAILED_ABX = "FAILED_ABX"
CRITERION_FAILED_SALINE = "FAILED_SALINE"
CRITERION_ENDOSCOPY_FINDING = "ENDOSCOPY_FINDING"

DECISION_APPROVED = "APPROVED"
DECISION_DENIED = "DENIED"
DECISION_INFO_REQUESTED = "INFO_REQUESTED"

MAX_REVISION_ROUNDS = 2
CT_MONTH_DAYS = 30

CANDIDACY_EVALUATION_FIELDS = (
    "evaluation_variant",
    "criteria_met_count",
    "admissible_criteria_codes",
    "contiguous_management_days",
    "cumulative_management_days",
    "management_days_metric",
    "min_documented_criteria_required",
    "min_medical_management_days_required",
    "candidacy_status",
)

# ---------------------------------------------------------------------------
# Diagnostic studies and device dispenses (PRD 3.7)
# ---------------------------------------------------------------------------
STUDY_AUDIOMETRY = "AUDIOMETRY"
STUDY_SLEEP_HSAT = "SLEEP_HSAT"
STUDY_SLEEP_PSG = "SLEEP_PSG"
SLEEP_STUDY_TYPES = (STUDY_SLEEP_HSAT, STUDY_SLEEP_PSG)

STUDY_ORDERED = "ORDERED"
STUDY_PERFORMED = "PERFORMED"
STUDY_INTERPRETED = "INTERPRETED"

RECOMMENDATION_HEARING_AID = "HEARING_AID"
RECOMMENDATION_OBSERVATION = "OBSERVATION"
RECOMMENDATION_ORAL_APPLIANCE = "ORAL_APPLIANCE"
RECOMMENDATION_CPAP = "CPAP"

DEVICE_TYPE_HEARING_AID = "HEARING_AID"
DEVICE_TYPE_ORAL_APPLIANCE = "ORAL_APPLIANCE"

PTA_HEARING_AID_THRESHOLD = 40.0
AHI_OBSERVATION_CEILING = 5.0
AHI_APPLIANCE_CEILING = 30.0

EAR_LEFT = "LEFT"
EAR_RIGHT = "RIGHT"
EAR_BOTH = "BOTH"
EAR_NA = "NA"

FIT_FITTED = "FITTED"
FIT_ADJUSTED = "ADJUSTED"
FIT_FINALIZED = "FINALIZED"
FIT_RETURNED = "RETURNED"

BILLING_INVOICED = "INVOICED"
BILLING_REFUND_PENDING = "REFUND_PENDING"
BILLING_REFUNDED = "REFUNDED"
BILLING_RETAINED = "RETAINED"

RETURN_REASON_DISSATISFIED = "DISSATISFIED"
RETURN_REASON_POOR_FIT = "POOR_FIT"
RETURN_REASON_MEDICAL_CHANGE = "MEDICAL_CHANGE"

REFUND_VARIANT_IN_TRIAL = "IN_TRIAL"
REFUND_VARIANT_POST_TRIAL = "POST_TRIAL"

WEAR_CENTS_PER_DAY = 350
MAX_ADJUSTMENTS = 3

# ---------------------------------------------------------------------------
# Endoscopes and supply lots (PRD 3.8)
# ---------------------------------------------------------------------------
SCOPE_READY = "READY"
SCOPE_IN_USE = "IN_USE"
SCOPE_SOILED = "SOILED"
SCOPE_REPROCESSING = "REPROCESSING"
SCOPE_QUARANTINED = "QUARANTINED"
SCOPE_RETIRED = "RETIRED"

HLD_SHELF_LIFE_HOURS = 168
REPROCESSING_BUFFER_MINUTES = 45
MEC_TEST_CYCLE_INTERVAL = 10
MEC_FAILURE_RETIREMENT_THRESHOLD = 2

ITEM_TYPE_BALLOON_DEVICE = "BALLOON_DEVICE"
ITEM_TYPE_TYMPANOSTOMY_TUBE = "TYMPANOSTOMY_TUBE"
ITEM_TYPE_ALLERGEN_CONCENTRATE = "ALLERGEN_CONCENTRATE"
ITEM_TYPE_HEARING_AID = "HEARING_AID"
ITEM_TYPE_ORAL_APPLIANCE = "ORAL_APPLIANCE"

LOT_ACTIVE = "ACTIVE"
LOT_EXHAUSTED = "EXHAUSTED"
LOT_QUARANTINED = "QUARANTINED"

ADJUSTMENT_REASON_RECEIVE = "RECEIVE"
ADJUSTMENT_REASON_WRITE_OFF = "WRITE_OFF"
ADJUSTMENT_REASON_QUARANTINE = "QUARANTINE"

# ---------------------------------------------------------------------------
# Surgery-center blocks and procedure bookings (PRD 3.9)
# ---------------------------------------------------------------------------
BLOCK_OPEN = "OPEN"
BLOCK_FULL = "FULL"
BLOCK_CLOSED = "CLOSED"

BLOCK_FULL_UTILIZATION_BPS = 10000
BLOCK_DEFAULT_MAX_CONCURRENT_CASES = 2

PROCEDURE_BALLOON_SINUPLASTY = "BALLOON_SINUPLASTY"
PROCEDURE_DIAGNOSTIC_ENDOSCOPY = "DIAGNOSTIC_ENDOSCOPY"
PROCEDURE_TYMPANOSTOMY_TUBES = "TYMPANOSTOMY_TUBES"
PROCEDURE_TONSILLECTOMY = "TONSILLECTOMY"

VENUE_IN_OFFICE_SUITE = "IN_OFFICE_SUITE"
VENUE_SURGERY_CENTER = "SURGERY_CENTER"

BOOKING_SCHEDULED = "SCHEDULED"
BOOKING_IN_PROGRESS = "IN_PROGRESS"
BOOKING_COMPLETED = "COMPLETED"
BOOKING_CANCELLED = "CANCELLED"

CANCEL_REASON_PATIENT_REQUEST = "PATIENT_REQUEST"
CANCEL_REASON_CLINICAL_HOLD = "CLINICAL_HOLD"
CANCEL_REASON_SUPPLY_SHORTAGE = "SUPPLY_SHORTAGE"
CANCEL_REASON_SCOPE_UNAVAILABLE = "SCOPE_UNAVAILABLE"

PEDIATRIC_AGE_MONTHS_THRESHOLD = 36

# Lot item type required for each procedure type that consumes implants.
ITEM_TYPE_BY_PROCEDURE = {
    PROCEDURE_BALLOON_SINUPLASTY: ITEM_TYPE_BALLOON_DEVICE,
    PROCEDURE_TYMPANOSTOMY_TUBES: ITEM_TYPE_TYMPANOSTOMY_TUBE,
}

# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100


def make_label_text(mrn: str, dilution_code: str, expires_at: str) -> str:
    """Build a vial ``label_text`` exactly as PRD 3.5 requires.

    Three parts, two separators, no spaces: the patient's ``mrn``, then the
    ``dilution_code``, then the calendar date of ``expires_at`` in YYYY-MM-DD.
    Any other spelling fails the request-shape gate with ERR_INVALID_REQUEST,
    so every label in the suite is built through this one function.
    """
    return "{0}|{1}|{2}".format(mrn, dilution_code, expires_at[:10])


def mrn(number: int) -> str:
    """Build an ``mrn`` matching the PRD 2.8 pattern: ``MRN-`` plus five digits."""
    return "MRN-{0:05d}".format(number)


def scope_serial(number: int) -> str:
    """Build a ``serial_number`` matching PRD 2.8: ``SC-`` plus exactly four digits."""
    return "SC-{0:04d}".format(number)


def lot_number(number: int) -> str:
    """Build a ``lot_number`` matching PRD 2.8: ``LOT-`` plus exactly four digits."""
    return "LOT-{0:04d}".format(number)


def device_serial(prefix: str, number: int) -> str:
    """Build a ``device_serial`` matching PRD 2.8: two uppercase letters, six digits."""
    return "{0}{1:06d}".format(prefix, number)
