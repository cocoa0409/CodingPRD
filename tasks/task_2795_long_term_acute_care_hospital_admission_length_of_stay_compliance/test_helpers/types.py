"""
The vocabulary of the long-term acute care admission and length-of-stay service.

Every literal a request may carry or a response may return lives here as a named
constant, so a test says `ReferralStatus.CRITERIA_MET` rather than repeating a bare
string that a typo could silently turn into a passing comparison against `None`.

The `*_FIELDS` tuples record the field list each entity declares, which is what the
shape tests compare a response against. Two entities — `DrgRateEntry` and `IdtNote` —
carry only `id` and `created_at` of the common properties: they are immutable, so they
have neither `updated_at` nor `version`. That distinction is expressed by
`COMMON_FIELDS` versus `IMMUTABLE_COMMON_FIELDS` rather than by a comment.
"""

from typing import Any, Dict, List, Optional, Tuple

try:  # pragma: no cover - the typing backport only matters on very old runtimes
    from typing import TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import TypedDict  # type: ignore

Json = Dict[str, Any]


# ── Callers ──────────────────────────────────────────
class UserRole:
    """The five roles named in the specification, spelled exactly as sent."""

    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    UTILIZATION_REVIEW_NURSE = "UtilizationReviewNurse"
    ATTENDING_PHYSICIAN = "AttendingPhysician"
    REVENUE_INTEGRITY_ANALYST = "RevenueIntegrityAnalyst"

    ALL = (
        COMPLIANCE_OFFICER,
        INTAKE_COORDINATOR,
        UTILIZATION_REVIEW_NURSE,
        ATTENDING_PHYSICIAN,
        REVENUE_INTEGRITY_ANALYST,
    )


# The actor recorded when a cascade, rather than an operator, wrote a row.
SYSTEM_ACTOR = "SYSTEM"


# ── Reference data ───────────────────────────────────
class HospitalType:
    ACUTE_CARE = "ACUTE_CARE"
    CRITICAL_ACCESS = "CRITICAL_ACCESS"


class MonitoringState:
    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    BREACHED = "BREACHED"


class Payer:
    MEDICARE_FFS = "MEDICARE_FFS"
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    COMMERCIAL = "COMMERCIAL"


class Specialty:
    PULMONOLOGY = "PULMONOLOGY"
    INFECTIOUS_DISEASE = "INFECTIOUS_DISEASE"
    WOUND_CARE = "WOUND_CARE"
    INTERNAL_MEDICINE = "INTERNAL_MEDICINE"


class CredentialStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CriteriaSetStatus:
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PeriodStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ── Referral intake ─────────────────────────────────
class ReferralStatus:
    RECEIVED = "RECEIVED"
    INFO_REQUESTED = "INFO_REQUESTED"
    CRITERIA_MET = "CRITERIA_MET"
    CRITERIA_NOT_MET = "CRITERIA_NOT_MET"
    ADMITTED = "ADMITTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class QualifyingTrack:
    NONE = "NONE"
    PMV = "PMV"
    COMPLEX_WOUND = "COMPLEX_WOUND"


# The five screening inputs whose absence drives `missing_fields`.
SCREENING_INPUT_FIELDS: Tuple[str, ...] = (
    "vent_hours_at_referral",
    "icu_days_at_referral",
    "wound_stage",
    "wound_count",
    "prior_acute_discharge_at",
)


# ── The stay, on both of its dimensions ─────────────
class ClinicalStatus:
    ADMITTED = "ADMITTED"
    INTERRUPTED = "INTERRUPTED"
    DISCHARGED = "DISCHARGED"
    RECOMBINED = "RECOMBINED"


class PaymentReviewStatus:
    PENDING = "PENDING"
    PRICED = "PRICED"
    FINALIZED = "FINALIZED"


class DischargeDisposition:
    HOME = "HOME"
    HOME_HEALTH = "HOME_HEALTH"
    SNF = "SNF"
    IRF = "IRF"
    ACUTE_TRANSFER = "ACUTE_TRANSFER"
    EXPIRED = "EXPIRED"
    # Reserved for the system: a client may not supply it.
    INTERRUPTION_EXPIRED = "INTERRUPTION_EXPIRED"

    CLIENT_SUPPLIABLE = (HOME, HOME_HEALTH, SNF, IRF, ACUTE_TRANSFER, EXPIRED)


# ── Ventilator weaning ──────────────────────────────
class WeaningPlanStatus:
    SBT_TRIAL = "SBT_TRIAL"
    PROGRESSING = "PROGRESSING"
    REGRESSED = "REGRESSED"
    LIBERATED = "LIBERATED"
    VENT_DEPENDENT = "VENT_DEPENDENT"


class SbtOutcome:
    TOLERATED = "TOLERATED"
    FAILED = "FAILED"


class WeaningCloseOutcome:
    LIBERATED = "LIBERATED"
    VENT_DEPENDENT = "VENT_DEPENDENT"


class Discipline:
    PHYSICIAN = "PHYSICIAN"
    NURSING = "NURSING"
    RESPIRATORY_THERAPY = "RESPIRATORY_THERAPY"
    CASE_MANAGEMENT = "CASE_MANAGEMENT"
    NUTRITION = "NUTRITION"
    PT_OT = "PT_OT"

    ALL = (PHYSICIAN, NURSING, RESPIRATORY_THERAPY, CASE_MANAGEMENT, NUTRITION, PT_OT)


# ── Interruptions ───────────────────────────────────
class InterruptionDestination:
    ACUTE_CARE = "ACUTE_CARE"
    IRF = "IRF"
    SNF = "SNF"
    HOME = "HOME"


class InterruptionStatus:
    OPEN = "OPEN"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"


# ── Payment ─────────────────────────────────────────
class PaymentVariant:
    STANDARD_LTCH_PPS = "STANDARD_LTCH_PPS"
    SITE_NEUTRAL = "SITE_NEUTRAL"


class DeterminationStatus:
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    VOIDED = "VOIDED"


class VoidReason:
    """The two reasons the system writes itself; anything else is operator text."""

    SUPERSEDED = "SUPERSEDED"
    RECOMBINED = "RECOMBINED"


# ── Denial risk ─────────────────────────────────────
class ReviewStatus:
    OPEN = "OPEN"
    QUERIES_ISSUED = "QUERIES_ISSUED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class ReviewOutcome:
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


class RiskBand:
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class QueryType:
    VENT_WEANING_RATIONALE = "VENT_WEANING_RATIONALE"
    WOUND_STAGING = "WOUND_STAGING"
    IDT_PARTICIPATION = "IDT_PARTICIPATION"
    SITE_NEUTRAL_JUSTIFICATION = "SITE_NEUTRAL_JUSTIFICATION"


class QueryStatus:
    ISSUED = "ISSUED"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


# ── The common properties ───────────────────────────
# Every entity carries these four, except the two immutable ones below.
COMMON_FIELDS: Tuple[str, ...] = ("id", "created_at", "updated_at", "version")

# `DrgRateEntry` and `IdtNote` are immutable, so they carry no `updated_at` and no
# `version` at all — those keys are absent, not null.
IMMUTABLE_COMMON_FIELDS: Tuple[str, ...] = ("id", "created_at")

# The entities that use the reduced set.
IMMUTABLE_ENTITIES: Tuple[str, ...] = ("DrgRateEntry", "IdtNote")


# ── Declared field lists, entity by entity ──────────
REFERRING_HOSPITAL_FIELDS: Tuple[str, ...] = (
    "name",
    "npi",
    "hospital_type",
    "is_colocated",
    "threshold_pct",
    "admissions_in_period",
    "share_pct",
    "monitoring_state",
)

COST_REPORTING_PERIOD_FIELDS: Tuple[str, ...] = (
    "period_label",
    "start_date",
    "end_date",
    "status",
    "total_admissions",
    "total_payment_cents",
    "final_determination_count",
    "closed_at",
)

PATIENT_FIELDS: Tuple[str, ...] = (
    "mrn",
    "full_name",
    "birth_date",
    "primary_payer",
    "open_referral_count",
)

PHYSICIAN_FIELDS: Tuple[str, ...] = ("npi", "full_name", "specialty", "credential_status")

ADMISSION_CRITERIA_SET_FIELDS: Tuple[str, ...] = (
    "label",
    "effective_from",
    "pmv_min_vent_hours",
    "pmv_min_icu_days",
    "wound_min_stage",
    "wound_min_count",
    "status",
)

DRG_RATE_FIELDS: Tuple[str, ...] = (
    "drg_code",
    "relative_weight",
    "alos_days",
    "standard_federal_rate_cents",
    "ipps_comparable_per_diem_cents",
    "ipps_comparable_full_cents",
)

REFERRAL_FIELDS: Tuple[str, ...] = (
    "patient_id",
    "referring_hospital_id",
    "drg_rate_id",
    "pinned_criteria_set_id",
    "vent_hours_at_referral",
    "icu_days_at_referral",
    "wound_stage",
    "wound_count",
    "prior_acute_discharge_at",
    "data_complete",
    "missing_fields",
    "qualifying_track",
    "status",
    "screened_count",
)

STAY_FIELDS: Tuple[str, ...] = (
    "patient_id",
    "referral_id",
    "cost_reporting_period_id",
    "interrupted_parent_stay_id",
    "admitted_at",
    "discharged_at",
    "resumed_at",
    "clinical_status",
    "payment_review_status",
    "carried_los_days",
    "interruption_days_total",
    "interruption_count",
    "covered_los_days",
    "sso_threshold_days",
    "short_stay_outlier_applied",
    "discharge_payment_pct",
    "discharge_disposition",
    "estimated_cost_cents",
    "counts_toward_admission_threshold",
    "admitted_with_override",
    "override_reason",
)

WEANING_PLAN_FIELDS: Tuple[str, ...] = (
    "stay_id",
    "closed_by_physician_id",
    "protocol_label",
    "vent_hours_total",
    "current_step",
    "sbt_attempt_count",
    "consecutive_failed_sbt",
    "max_tolerated_sbt_hours",
    "liberation_eligible",
    "last_progression_at",
    "status",
    "closed_at",
)

IDT_NOTE_FIELDS: Tuple[str, ...] = (
    "stay_id",
    "discipline",
    "note_text",
    "goals_documented",
    "documented_at",
    "week_index",
)

INTERRUPTION_EVENT_FIELDS: Tuple[str, ...] = (
    "stay_id",
    "destination",
    "left_at",
    "returned_at",
    "window_days",
    "interruption_days",
    "within_window",
    "status",
)

PAYMENT_DETERMINATION_FIELDS: Tuple[str, ...] = (
    "stay_id",
    "payment_variant",
    "drg_code_used",
    "relative_weight_used",
    "alos_days_used",
    "ipps_per_diem_used_cents",
    "ipps_full_used_cents",
    "covered_los_days_used",
    "full_standard_amount_cents",
    "standard_variant_amount_cents",
    "site_neutral_variant_amount_cents",
    "base_payment_cents",
    "outlier_payment_cents",
    "total_payment_cents",
    "discharge_payment_pct",
    "short_stay_outlier_applied",
    "status",
    "priced_by_user_id",
    "finalized_by_user_id",
    "recalculation_reason",
    "void_reason",
)

DENIAL_RISK_REVIEW_FIELDS: Tuple[str, ...] = (
    "stay_id",
    "as_documented_score",
    "query_adjusted_score",
    "effective_score",
    "risk_band",
    "missing_discipline_count",
    "answered_query_count",
    "status",
    "opened_by_user_id",
    "resolved_by_user_id",
    "resolution_note",
)

DOCUMENTATION_QUERY_FIELDS: Tuple[str, ...] = (
    "denial_risk_review_id",
    "stay_id",
    "answered_by_physician_id",
    "query_type",
    "prompt_text",
    "response_text",
    "issued_at",
    "due_at",
    "answered_at",
    "status",
    "issued_by_user_id",
    "closed_by_user_id",
)

ENTITY_FIELDS: Dict[str, Tuple[str, ...]] = {
    "ReferringHospital": REFERRING_HOSPITAL_FIELDS,
    "CostReportingPeriod": COST_REPORTING_PERIOD_FIELDS,
    "Patient": PATIENT_FIELDS,
    "Physician": PHYSICIAN_FIELDS,
    "AdmissionCriteriaSet": ADMISSION_CRITERIA_SET_FIELDS,
    "DrgRateEntry": DRG_RATE_FIELDS,
    "Referral": REFERRAL_FIELDS,
    "Stay": STAY_FIELDS,
    "WeaningPlan": WEANING_PLAN_FIELDS,
    "IdtNote": IDT_NOTE_FIELDS,
    "InterruptionEvent": INTERRUPTION_EVENT_FIELDS,
    "PaymentDetermination": PAYMENT_DETERMINATION_FIELDS,
    "DenialRiskReview": DENIAL_RISK_REVIEW_FIELDS,
    "DocumentationQuery": DOCUMENTATION_QUERY_FIELDS,
}


def expected_keys(entity: str) -> Tuple[str, ...]:
    """The full key set a read of this entity is expected to expose."""
    common = (
        IMMUTABLE_COMMON_FIELDS if entity in IMMUTABLE_ENTITIES else COMMON_FIELDS
    )
    return tuple(common) + ENTITY_FIELDS[entity]
