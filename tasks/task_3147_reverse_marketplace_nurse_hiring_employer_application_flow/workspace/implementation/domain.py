"""Domain helpers: timestamps, serialization, computed fields, cascades."""

import uuid
from datetime import datetime, date, timezone, timedelta

import db


def new_id() -> str:
    return str(uuid.uuid4())


def iso(dt: datetime) -> str:
    """Format a logical-clock datetime as ISO8601 UTC with 3 fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso() -> str:
    return iso(db.clock_now)


def today() -> date:
    return db.clock_now.date()


def parse_datetime(s):
    """Parse an ISO 8601 datetime string (with optional trailing Z)."""
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date(s):
    if not isinstance(s, str):
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def touch(entity):
    """Refresh updated_at and increment version on a versioned entity."""
    entity["updated_at"] = now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Serializers (shape the row for the wire)
# ---------------------------------------------------------------------------

NURSE_FIELDS = (
    "id", "full_name", "email", "home_state", "primary_specialty",
    "years_experience", "desired_shift", "desired_hourly_rate_cents",
    "max_commute_miles", "current_employer_name", "confidentiality_exclusions",
    "status", "license_verified", "active_application_count",
    "created_at", "updated_at", "version",
)

LV_FIELDS = (
    "id", "nurse_id", "license_number", "license_state", "expiry_date",
    "status", "rejection_reason", "created_at", "updated_at", "version",
)

CERT_FIELDS = ("id", "nurse_id", "cert_code", "expires_on", "created_at")

EMPLOYER_FIELDS = (
    "id", "legal_name", "facility_state", "fee_model", "subscription_tier",
    "sla_response_hours", "guarantee_days", "placement_fee_bps",
    "credit_balance_cents", "status", "created_at", "updated_at", "version",
)

REQ_FIELDS = (
    "id", "employer_id", "specialty", "unit_name", "required_certs",
    "facility_state", "distance_from_facility_miles", "shift",
    "offered_hourly_rate_cents", "openings_total", "openings_filled", "status",
    "created_at", "updated_at", "version",
)

MATCH_FIELDS = (
    "id", "nurse_id", "requisition_id", "match_score", "suppressed",
    "generated_at", "created_at",
)

APPLICATION_FIELDS = (
    "id", "requisition_id", "nurse_id", "employer_id",
    "proposed_hourly_rate_cents", "proposed_shift", "status",
    "response_deadline_at", "revision_count", "deadline_extended",
    "created_at", "updated_at", "version",
)

INTERVIEW_FIELDS = (
    "id", "application_id", "starts_at", "ends_at", "status",
    "scheduled_by_employer_at", "created_at", "updated_at", "version",
)

OFFER_FIELDS = (
    "id", "application_id", "offered_hourly_rate_cents", "start_date",
    "status", "offer_expires_at", "issued_at",
    "created_at", "updated_at", "version",
)

SCREENING_FIELDS = (
    "id", "application_id", "credential_status", "background_status",
    "overall_status", "created_at", "updated_at", "version",
)

DOC_FIELDS = (
    "id", "application_id", "doc_type", "status", "review_note",
    "created_at", "updated_at", "version",
)

PLACEMENT_FIELDS = (
    "id", "application_id", "requisition_id", "nurse_id", "employer_id",
    "hourly_rate_cents", "annualized_salary_cents", "start_date",
    "guarantee_ends_on", "status", "created_at", "updated_at", "version",
)

INVOICE_FIELDS = (
    "id", "employer_id", "placement_id", "invoice_kind", "amount_due_cents",
    "amount_credited_cents", "status", "created_at", "updated_at", "version",
)


def ser(row, fields):
    return {k: row.get(k) for k in fields}
