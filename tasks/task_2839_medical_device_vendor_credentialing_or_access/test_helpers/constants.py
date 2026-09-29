"""Domain constants and pure derivations for the Vendor Credentialing & OR Access API.

Every value here is transcribed from the PRD under test: the global numeric
constants of sections 2.6, 3.4, 3.7, 3.8 and 3.9, the enumerated domains of
section 3, and the small pure calculations the PRD pins (tray surcharge,
delivery lead, per-tray late charge, late fee cap, score deductions).

The helpers are deliberately literal re-implementations of the PRD prose so a
test can state an expected integer without hand-computing it inline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

API_PREFIX = "/vendor-access"

# ── Section 2.4: the logical clock ────────────────────────────────────────────
LOGICAL_CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00Z"

# ── Section 2.1: roles ────────────────────────────────────────────────────────
ROLE_VENDOR_ADMIN = "VendorAdmin"
ROLE_VENDOR_REP_USER = "VendorRepUser"
ROLE_CREDENTIALING_OFFICER = "CredentialingOfficer"
ROLE_OR_COORDINATOR = "ORCoordinator"
ROLE_CLINICAL_SPONSOR = "ClinicalSponsor"
ROLE_VALUE_ANALYSIS_APPROVER = "ValueAnalysisApprover"
ROLE_STERILE_PROCESSING_TECH = "SterileProcessingTech"
ROLE_COMPLIANCE_ADMIN = "ComplianceAdmin"

ALL_ROLES = (
    ROLE_CREDENTIALING_OFFICER,
    ROLE_COMPLIANCE_ADMIN,
    ROLE_OR_COORDINATOR,
    ROLE_STERILE_PROCESSING_TECH,
    ROLE_VENDOR_ADMIN,
    ROLE_VENDOR_REP_USER,
    ROLE_CLINICAL_SPONSOR,
    ROLE_VALUE_ANALYSIS_APPROVER,
)

# ── Section 3.2: credentials ──────────────────────────────────────────────────
CREDENTIAL_TYPE_INFLUENZA = "IMMUNIZATION_INFLUENZA"
CREDENTIAL_TYPE_MMR = "IMMUNIZATION_MMR"
CREDENTIAL_TYPE_BLOODBORNE = "TRAINING_BLOODBORNE_PATHOGENS"
CREDENTIAL_TYPE_OR_PROTOCOL = "TRAINING_OR_PROTOCOL"
CREDENTIAL_TYPE_BACKGROUND = "BACKGROUND_CHECK"
CREDENTIAL_TYPE_COI = "COI_GIFT_ATTESTATION"

ALL_CREDENTIAL_TYPES = (
    CREDENTIAL_TYPE_INFLUENZA,
    CREDENTIAL_TYPE_MMR,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_OR_PROTOCOL,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_COI,
)

# Only four of the six gate site access.
GATING_CREDENTIAL_TYPES = (
    CREDENTIAL_TYPE_INFLUENZA,
    CREDENTIAL_TYPE_BLOODBORNE,
    CREDENTIAL_TYPE_BACKGROUND,
    CREDENTIAL_TYPE_COI,
)

CREDENTIAL_STATUSES = (
    "PENDING_VERIFICATION",
    "VERIFIED",
    "EXPIRING_SOON",
    "EXPIRED",
    "REJECTED",
)

EXPIRY_WARNING_DAYS = 14

# ── Section 3.1 / 3.2: representative lifecycle ───────────────────────────────
ACCESS_STATUS_PENDING = "PENDING_CREDENTIALING"
ACCESS_STATUS_CREDENTIALED = "CREDENTIALED"
ACCESS_STATUS_SUSPENDED = "SUSPENDED"
ACCESS_STATUS_REVOKED = "REVOKED"

POSTURE_INCOMPLETE = "INCOMPLETE"
POSTURE_LAPSED = "LAPSED"
POSTURE_EXPIRING_SOON = "EXPIRING_SOON"
POSTURE_COMPLIANT = "COMPLIANT"

SUSPENSION_REASON_NONE = "NONE"
SUSPENSION_REASON_CREDENTIAL_LAPSED = "CREDENTIAL_LAPSED"
SUSPENSION_REASON_INCIDENT = "INCIDENT_SUBSTANTIATED"

# ── Section 3.3: surgical cases ───────────────────────────────────────────────
CASE_STATUS_SCHEDULED = "SCHEDULED"
CASE_STATUS_RESCHEDULED = "RESCHEDULED"
CASE_STATUS_CANCELLED = "CANCELLED"

RESTRICTION_STANDARD = "STANDARD"
RESTRICTION_RESTRICTED = "RESTRICTED"

COVERAGE_NOT_REQUIRED = "NOT_REQUIRED"
COVERAGE_UNCOVERED = "UNCOVERED"
COVERAGE_AT_RISK = "AT_RISK"
COVERAGE_COVERED = "COVERED"

READINESS_NOT_APPLICABLE = "NOT_APPLICABLE"
READINESS_PENDING = "PENDING"
READINESS_BLOCKED = "BLOCKED"
READINESS_READY = "READY"

# ── Section 3.4: authorizations ───────────────────────────────────────────────
AUTH_STATUS_REQUESTED = "REQUESTED"
AUTH_STATUS_APPROVED = "APPROVED"
AUTH_STATUS_DENIED = "DENIED"
AUTH_STATUS_REVOKED = "REVOKED"

REQUESTED_ROLE_IMPLANT_SUPPORT = "IMPLANT_SUPPORT"
REQUESTED_ROLE_TECHNICAL_SUPPORT = "TECHNICAL_SUPPORT"
REQUESTED_ROLE_OBSERVATION = "OBSERVATION"

REVOKED_REASON_NONE = "NONE"
REVOKED_REASON_REP_SUSPENDED = "REP_SUSPENDED"
REVOKED_REASON_REP_REVOKED = "REP_REVOKED"
REVOKED_REASON_CASE_CANCELLED = "CASE_CANCELLED"
REVOKED_REASON_COORDINATOR_WITHDRAWN = "COORDINATOR_WITHDRAWN"
REVOKED_REASON_MANUAL = "MANUAL"

DEFAULT_BADGE_LEAD_MINUTES = 60
DEFAULT_BADGE_GRACE_MINUTES = 30
DEFAULT_RESTRICTED_ESCORT_REQUIRED = True

BASE_QUOTA = 4
QUOTA_HARD_MULTIPLIER = Decimal("1.5")

# ── Section 3.5: kiosk check-ins ──────────────────────────────────────────────
BADGE_STATUS_ISSUED = "ISSUED"
BADGE_STATUS_CHECKED_OUT = "CHECKED_OUT"
BADGE_STATUS_EXPIRED = "EXPIRED"
BADGE_STATUS_VOIDED = "VOIDED"

ESCORT_NOT_REQUIRED = "ESCORT_NOT_REQUIRED"
ESCORT_PENDING = "ESCORT_PENDING"
ESCORT_ATTACHED = "ESCORT_ATTACHED"
ESCORT_RELEASED = "ESCORT_RELEASED"

# ── Section 3.6: product introduction requests ────────────────────────────────
PIR_STATUS_DRAFT = "DRAFT"
PIR_STATUS_CLINICAL_REVIEW = "CLINICAL_REVIEW"
PIR_STATUS_VALUE_ANALYSIS_REVIEW = "VALUE_ANALYSIS_REVIEW"
PIR_STATUS_CHANGES_REQUESTED = "CHANGES_REQUESTED"
PIR_STATUS_APPROVED = "APPROVED"
PIR_STATUS_REJECTED = "REJECTED"

MAX_REVISION_ROUNDS = 2
APPROVAL_VALIDITY_DAYS = 365

PRODUCT_STATUS_ACTIVE = "ACTIVE"
PRODUCT_STATUS_SUSPENDED = "SUSPENDED"
PRODUCT_STATUS_EXPIRED = "EXPIRED"

SUSPENDED_REASON_NONE = "NONE"
SUSPENDED_REASON_INCIDENT = "INCIDENT_SUBSTANTIATED"
SUSPENDED_REASON_APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
SUSPENDED_REASON_SUPERSEDED = "SUPERSEDED"

# ── Section 3.7: loaner sets ──────────────────────────────────────────────────
LOANER_STATUS_EXPECTED = "EXPECTED"
LOANER_STATUS_DELIVERED_ON_TIME = "DELIVERED_ON_TIME"
LOANER_STATUS_DELIVERED_LATE = "DELIVERED_LATE"
LOANER_STATUS_REJECTED_LATE = "REJECTED_LATE"
LOANER_STATUS_HELD = "HELD"
LOANER_STATUS_RELEASED = "RELEASED_TO_OR"

FEE_STATUS_NONE = "NONE"
FEE_STATUS_WAIVED = "WAIVED"
FEE_STATUS_ASSESSED = "ASSESSED"
FEE_STATUS_REVERSED = "REVERSED"

COMPLEXITY_SIMPLE = "SIMPLE"
COMPLEXITY_COMPLEX = "COMPLEX"
COMPLEXITY_IMPLANT_SPECIALTY = "IMPLANT_SPECIALTY"

COMPLEXITY_HOURS = {
    COMPLEXITY_SIMPLE: 2,
    COMPLEXITY_COMPLEX: 6,
    COMPLEXITY_IMPLANT_SPECIALTY: 10,
}

COMPLEXITY_FEE_MULTIPLIER = {
    COMPLEXITY_SIMPLE: Decimal("1.0"),
    COMPLEXITY_COMPLEX: Decimal("1.35"),
    COMPLEXITY_IMPLANT_SPECIALTY: Decimal("1.75"),
}

IMPLANT_MIN_LEAD_HOURS = 24
HARD_REJECT_GRACE_MINUTES = 120
PER_TRAY_BASE_RATE_CENTS_PER_MINUTE = Decimal("2.5")
LATE_FEE_CAP_CENTS = 250000
FEE_HOLD_THRESHOLD_CENTS = 100000
SPD_BAY_BUFFER_MINUTES = 30

# ── Section 3.8: incidents and scoring ────────────────────────────────────────
INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE = "UNAPPROVED_PRODUCT_USE"
INCIDENT_TYPE_UNBADGED_ACCESS = "UNBADGED_ACCESS"
INCIDENT_TYPE_LOANER_LATE_DELIVERY = "LOANER_LATE_DELIVERY"
INCIDENT_TYPE_GIFT_POLICY_VIOLATION = "GIFT_POLICY_VIOLATION"

INCIDENT_TYPES = (
    INCIDENT_TYPE_UNAPPROVED_PRODUCT_USE,
    INCIDENT_TYPE_UNBADGED_ACCESS,
    INCIDENT_TYPE_LOANER_LATE_DELIVERY,
    INCIDENT_TYPE_GIFT_POLICY_VIOLATION,
)

SEVERITY_MINOR = "MINOR"
SEVERITY_MAJOR = "MAJOR"
SEVERITY_CRITICAL = "CRITICAL"

INCIDENT_STATUS_REPORTED = "REPORTED"
INCIDENT_STATUS_UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
INCIDENT_STATUS_SUBSTANTIATED = "SUBSTANTIATED"
INCIDENT_STATUS_UNSUBSTANTIATED = "UNSUBSTANTIATED"
INCIDENT_STATUS_CLOSED = "CLOSED"

OUTCOME_NONE = "NONE"
OUTCOME_SUBSTANTIATED = "SUBSTANTIATED"
OUTCOME_UNSUBSTANTIATED = "UNSUBSTANTIATED"

BASE_SCORE = 100
SCORE_FLOOR = 0
SCORE_CEILING = 100

SEVERITY_WEIGHT = {
    SEVERITY_MINOR: 3,
    SEVERITY_MAJOR: 8,
    SEVERITY_CRITICAL: 20,
}
W_LATE_DELIVERY = 5
W_LAPSED_REP = 6
W_UTILIZATION_OVERAGE = 12

TIER_PLATINUM = "TIER_PLATINUM"
TIER_STANDARD = "TIER_STANDARD"
TIER_PROBATION = "TIER_PROBATION"

TIER_PLATINUM_MIN_SCORE = 90
TIER_STANDARD_MIN_SCORE = 70

TIER_STEP = {
    TIER_PLATINUM: Decimal("1.5"),
    TIER_STANDARD: Decimal("1.0"),
    TIER_PROBATION: Decimal("0.4"),
}

STATUS_IN_GOOD_STANDING = "IN_GOOD_STANDING"
STATUS_WATCH = "WATCH"
STATUS_PROBATION = "PROBATION"
STATUS_BARRED = "BARRED"

INCIDENT_CLOSE_DAYS = 30

# ── Section 3.9: appeals and sweeps ───────────────────────────────────────────
APPEAL_STATUS_SUBMITTED = "SUBMITTED"
APPEAL_STATUS_UPHELD = "UPHELD"
APPEAL_STATUS_OVERTURNED = "OVERTURNED"

APPEAL_WINDOW_DAYS = 14

SWEEP_COUNTER_FIELDS = (
    "credentials_expired_count",
    "credentials_warned_count",
    "reps_suspended_count",
    "reps_reinstated_count",
    "authorizations_revoked_count",
    "badges_voided_count",
    "badges_expired_count",
    "approvals_expired_count",
    "incidents_closed_count",
    "vendors_rescored_count",
)


# ── Pure instant arithmetic ───────────────────────────────────────────────────
def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant, tolerating a Z suffix and 0-6 fractions."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def format_instant(moment: datetime) -> str:
    """Emit an instant in the second-resolution ISO 8601 UTC form tests use."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def shift_instant(
    value: str,
    days: int = 0,
    hours: int = 0,
    minutes: int = 0,
    seconds: int = 0,
) -> str:
    """Shift an ISO 8601 instant by a whole offset and re-emit it."""
    moment = parse_instant(value) + timedelta(
        days=days, hours=hours, minutes=minutes, seconds=seconds
    )
    return format_instant(moment)


def minutes_between(earlier: str, later: str) -> int:
    """Whole minutes from earlier to later, truncated toward zero, floored at 0."""
    delta = parse_instant(later) - parse_instant(earlier)
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return 0
    return total_seconds // 60


# ── Pure domain calculations (PRD sections 3.4, 3.7, 3.8, 3.9) ────────────────
def round_half_up(value: Decimal, places: int = 0) -> Decimal:
    """Round half up to the given number of decimal places."""
    exponent = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exponent, rounding=ROUND_HALF_UP)


def tray_surcharge_hours(tray_count: int) -> int:
    """At most four trays adds nothing, five through twelve adds one, thirteen or more adds two."""
    if tray_count <= 4:
        return 0
    if tray_count <= 12:
        return 1
    return 2


def loaner_lead_hours(
    spd_turnaround_hours: int,
    reprocessing_complexity: str,
    tray_count: int,
    implant_required: bool,
) -> int:
    """Turnaround plus complexity allowance plus tray surcharge, floored at 24 h on an implant case."""
    turnaround = (
        spd_turnaround_hours
        + COMPLEXITY_HOURS[reprocessing_complexity]
        + tray_surcharge_hours(tray_count)
    )
    floor_hours = IMPLANT_MIN_LEAD_HOURS if implant_required else 0
    return max(turnaround, floor_hours)


def loaner_deadline(
    basis_instant: str,
    spd_turnaround_hours: int,
    reprocessing_complexity: str,
    tray_count: int,
    implant_required: bool,
) -> str:
    """The basis instant with the whole-hour lead time subtracted."""
    lead = loaner_lead_hours(
        spd_turnaround_hours, reprocessing_complexity, tray_count, implant_required
    )
    return shift_instant(basis_instant, hours=-lead)


def per_tray_late_charge_cents(late_minutes: int, reprocessing_complexity: str) -> int:
    """Late minutes times the base rate times the complexity multiplier, rounded half up first."""
    raw = (
        Decimal(late_minutes)
        * PER_TRAY_BASE_RATE_CENTS_PER_MINUTE
        * COMPLEXITY_FEE_MULTIPLIER[reprocessing_complexity]
    )
    return int(round_half_up(raw))


def late_fee_cents(
    late_minutes: int, tray_count: int, reprocessing_complexity: str
) -> int:
    """Per-tray charge rounded before multiplying by the tray count, then capped."""
    per_tray = per_tray_late_charge_cents(late_minutes, reprocessing_complexity)
    raw_fee = per_tray * tray_count
    return min(raw_fee, LATE_FEE_CAP_CENTS)


def expected_fee_status(late_minutes: int, tray_count: int) -> str:
    """NONE with no lateness, otherwise WAIVED with no trays, otherwise ASSESSED."""
    if late_minutes == 0:
        return FEE_STATUS_NONE
    if tray_count == 0:
        return FEE_STATUS_WAIVED
    return FEE_STATUS_ASSESSED


def delivery_branch(late_minutes: int) -> str:
    """The three-way receipt fork, decided purely on the current-basis late minutes."""
    if late_minutes == 0:
        return LOANER_STATUS_DELIVERED_ON_TIME
    if late_minutes <= HARD_REJECT_GRACE_MINUTES:
        return LOANER_STATUS_DELIVERED_LATE
    return LOANER_STATUS_REJECTED_LATE


def quota_hard_cap(access_quota_in_effect: int) -> int:
    """The quota multiplied by one and a half, rounded down to a whole number."""
    return int(
        (Decimal(access_quota_in_effect) * QUOTA_HARD_MULTIPLIER).to_integral_value(
            rounding="ROUND_FLOOR"
        )
    )


def compliance_score(
    incident_weights: "list[int] | tuple[int, ...]" = (),
    late_delivery_count: int = 0,
    lapsed_rep_count: int = 0,
    over_utilized: bool = False,
) -> int:
    """Four penalties subtracted from a base of 100, clamped once at the end."""
    total = (
        sum(incident_weights)
        + W_LATE_DELIVERY * late_delivery_count
        + W_LAPSED_REP * lapsed_rep_count
        + (W_UTILIZATION_OVERAGE if over_utilized else 0)
    )
    return max(SCORE_FLOOR, min(SCORE_CEILING, BASE_SCORE - total))


def scorecard_tier(adjudicated_score: int) -> str:
    """Platinum at 90 or above, standard at 70 or above, probation otherwise."""
    if adjudicated_score >= TIER_PLATINUM_MIN_SCORE:
        return TIER_PLATINUM
    if adjudicated_score >= TIER_STANDARD_MIN_SCORE:
        return TIER_STANDARD
    return TIER_PROBATION


def compliance_status(adjudicated_score: int) -> str:
    """Barred below 40, probation below 70, watch below 85, in good standing at 85 or above."""
    if adjudicated_score < 40:
        return STATUS_BARRED
    if adjudicated_score < 70:
        return STATUS_PROBATION
    if adjudicated_score < 85:
        return STATUS_WATCH
    return STATUS_IN_GOOD_STANDING


def next_quota(pre_sweep_quota: int, tier: str) -> int:
    """The larger of one and the floor of the pre-sweep quota times the tier step."""
    stepped = (Decimal(pre_sweep_quota) * TIER_STEP[tier]).to_integral_value(
        rounding="ROUND_FLOOR"
    )
    return max(1, int(stepped))


def utilization_ratio(authorizations_used_epoch: int, quota_in_effect: int) -> float:
    """Used authorizations over the pre-sweep quota, rounded half up to four places."""
    ratio = Decimal(authorizations_used_epoch) / Decimal(quota_in_effect)
    return float(round_half_up(ratio, 4))


def badge_serial(facility_code: str, ordinal: int) -> str:
    """The facility code, a hyphen, then a four-digit zero-padded per-facility counter."""
    return f"{facility_code}-{ordinal:04d}"
