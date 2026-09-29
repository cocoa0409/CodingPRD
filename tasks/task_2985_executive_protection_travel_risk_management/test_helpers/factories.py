"""Request payload builders.

Every builder returns a plain dict and applies ``overrides`` last, so a caller
can replace or remove any declared field.  Money and hour figures are emitted as
JSON numbers, instants as full ISO-8601 UTC instants with a ``Z`` suffix, and
version fields as integers.
"""

from .constants import (
    ADVANCE_OUTCOME_COMPLETE,
    ADVISORY_EFFECTIVE_AT,
    CERT_FAR_FUTURE,
    CHECK_IN_SCHEDULED,
    COUNTRY_PT,
    COUNTRY_US,
    DEFAULT_ANNUAL_BUDGET_CENTS,
    DETAIL_AGENT,
    INCIDENT_MEDICAL,
    ITEM_ROUTE_SURVEY,
    LEG_ARRIVE_AT,
    LEG_DEPART_AT,
    POLICY_EFFECTIVE_FROM,
    POLICY_EFFECTIVE_TO,
    POLICY_MEDICAL_EVAC,
    PURPOSE_BUSINESS_TRAVEL,
    RATE_ANALYST_CENTS,
    STAFF_ROLE_ANALYST,
    SURVEY_COMPLETE,
    TIER_3,
    TRIP_DEPART_AT,
    TRIP_RETURN_AT,
    VENDOR_GROUND_SECURITY,
    VERIFY_OUTCOME_VERIFY,
)

_UNSET = object()


def _build(base, overrides):
    """Apply overrides once; a value of ``None`` drops the field entirely."""
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v is not _UNSET}


# ------------------------------------------------------------------ clock
def clock_payload(current_utc, **overrides):
    return _build({"current_utc": current_utc}, overrides)


# --------------------------------------------------------- security staff
def staff_payload(
    full_name="Ana Analyst",
    staff_role=STAFF_ROLE_ANALYST,
    certification_expires_at=CERT_FAR_FUTURE,
    hourly_rate_cents=RATE_ANALYST_CENTS,
    **overrides,
):
    return _build(
        {
            "full_name": full_name,
            "staff_role": staff_role,
            "certification_expires_at": certification_expires_at,
            "hourly_rate_cents": int(hourly_rate_cents),
        },
        overrides,
    )


# -------------------------------------------------------------- executive
def executive_payload(
    full_name="Eve Exec",
    tier=TIER_3,
    role_title="CEO",
    base_country_code=COUNTRY_US,
    annual_security_budget_cents=DEFAULT_ANNUAL_BUDGET_CENTS,
    **overrides,
):
    return _build(
        {
            "full_name": full_name,
            "tier": tier,
            "role_title": role_title,
            "base_country_code": base_country_code,
            "annual_security_budget_cents": int(annual_security_budget_cents),
        },
        overrides,
    )


def consent_payload(**overrides):
    """Consent revision: send only the fields the caller names."""
    return _build({}, overrides)


def residential_survey_payload(
    survey_outcome=SURVEY_COMPLETE, residential_component=10.0, **overrides
):
    return _build(
        {
            "survey_outcome": survey_outcome,
            "residential_component": residential_component,
        },
        overrides,
    )


def exposure_signal_payload(signal_type, severity, observed_at, **overrides):
    return _build(
        {
            "signal_type": signal_type,
            "severity": int(severity),
            "observed_at": observed_at,
        },
        overrides,
    )


# ------------------------------------------------------ insurance policies
def insurance_policy_payload(
    executive_id,
    policy_type=POLICY_MEDICAL_EVAC,
    coverage_cents=500_000_000,
    effective_from=POLICY_EFFECTIVE_FROM,
    effective_to=POLICY_EFFECTIVE_TO,
    **overrides,
):
    return _build(
        {
            "executive_id": executive_id,
            "policy_type": policy_type,
            "coverage_cents": int(coverage_cents),
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        overrides,
    )


def policy_verify_payload(
    outcome=VERIFY_OUTCOME_VERIFY, verification_note="binder on file", **overrides
):
    return _build(
        {"outcome": outcome, "verification_note": verification_note}, overrides
    )


# ---------------------------------------------------- destination ratings
def destination_rating_payload(
    country_code=COUNTRY_PT,
    crime_index=10.0,
    political_instability_index=8.0,
    medical_infrastructure_index=90.0,
    natural_hazard_index=12.0,
    advisory_effective_at=ADVISORY_EFFECTIVE_AT,
    **overrides,
):
    return _build(
        {
            "country_code": country_code,
            "crime_index": crime_index,
            "political_instability_index": political_instability_index,
            "medical_infrastructure_index": medical_infrastructure_index,
            "natural_hazard_index": natural_hazard_index,
            "advisory_effective_at": advisory_effective_at,
        },
        overrides,
    )


def destination_rating_patch_payload(**overrides):
    """Advisory revision: any subset of the six revisable fields."""
    return _build({}, overrides)


# -------------------------------------------------------- risk assessments
def risk_assessment_payload(
    executive_id, authored_by_staff_id, threat_monitoring_score=20.0, **overrides
):
    return _build(
        {
            "executive_id": executive_id,
            "authored_by_staff_id": authored_by_staff_id,
            "threat_monitoring_score": threat_monitoring_score,
        },
        overrides,
    )


def assessment_review_payload(outcome, **overrides):
    return _build({"outcome": outcome}, overrides)


# ------------------------------------------------------------------- trips
def trip_payload(
    executive_id,
    created_by_staff_id,
    risk_assessment_id,
    trip_purpose=PURPOSE_BUSINESS_TRAVEL,
    primary_destination_country_code=COUNTRY_PT,
    depart_at=TRIP_DEPART_AT,
    return_at=TRIP_RETURN_AT,
    **overrides,
):
    return _build(
        {
            "executive_id": executive_id,
            "created_by_staff_id": created_by_staff_id,
            "risk_assessment_id": risk_assessment_id,
            "trip_purpose": trip_purpose,
            "primary_destination_country_code": primary_destination_country_code,
            "depart_at": depart_at,
            "return_at": return_at,
        },
        overrides,
    )


def trip_leg_payload(
    sequence_no=1,
    destination_country_code=COUNTRY_PT,
    arrive_at=LEG_ARRIVE_AT,
    depart_at=LEG_DEPART_AT,
    **overrides,
):
    return _build(
        {
            "sequence_no": int(sequence_no),
            "destination_country_code": destination_country_code,
            "arrive_at": arrive_at,
            "depart_at": depart_at,
        },
        overrides,
    )


def advance_progress_payload(
    item_type=ITEM_ROUTE_SURVEY, outcome=ADVANCE_OUTCOME_COMPLETE, **overrides
):
    return _build({"item_type": item_type, "outcome": outcome}, overrides)


def trip_decision_payload(decision, **overrides):
    return _build({"decision": decision}, overrides)


def check_in_payload(kind=CHECK_IN_SCHEDULED, **overrides):
    return _build({"kind": kind}, overrides)


def incident_payload(
    affected_leg_sequence_no=1,
    incident_type=INCIDENT_MEDICAL,
    severity=3,
    narrative="principal reported acute chest pain at the venue",
    **overrides,
):
    return _build(
        {
            "affected_leg_sequence_no": int(affected_leg_sequence_no),
            "incident_type": incident_type,
            "severity": int(severity),
            "narrative": narrative,
        },
        overrides,
    )


def triage_payload(response_track, **overrides):
    return _build({"response_track": response_track}, overrides)


def resolve_payload(**overrides):
    return _build({}, overrides)


# ------------------------------------------------------ detail assignments
def detail_assignment_payload(
    trip_leg_id,
    staff_id,
    expected_trip_leg_version,
    role_on_detail=DETAIL_AGENT,
    starts_at=LEG_ARRIVE_AT,
    ends_at=LEG_DEPART_AT,
    **overrides,
):
    return _build(
        {
            "trip_leg_id": trip_leg_id,
            "staff_id": staff_id,
            "role_on_detail": role_on_detail,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "expected_trip_leg_version": int(expected_trip_leg_version),
        },
        overrides,
    )


def release_payload(actual_ends_at, **overrides):
    return _build({"actual_ends_at": actual_ends_at}, overrides)


# ----------------------------------------------------------------- vendors
def vendor_payload(
    vendor_name="Guarda Atlantica",
    vendor_type=VENDOR_GROUND_SECURITY,
    country_code=COUNTRY_PT,
    max_concurrent_engagements=2,
    sla_response_minutes=45,
    hourly_rate_cents=10_000,
    retainer_cents=50_000,
    **overrides,
):
    return _build(
        {
            "vendor_name": vendor_name,
            "vendor_type": vendor_type,
            "country_code": country_code,
            "max_concurrent_engagements": int(max_concurrent_engagements),
            "sla_response_minutes": int(sla_response_minutes),
            "hourly_rate_cents": int(hourly_rate_cents),
            "retainer_cents": int(retainer_cents),
        },
        overrides,
    )


def vendor_suspend_payload(suspension_reason="licence lapsed", **overrides):
    return _build({"suspension_reason": suspension_reason}, overrides)


def vendor_engagement_payload(
    vendor_id,
    trip_leg_id,
    engagement_purpose,
    starts_at,
    ends_at,
    expected_vendor_version,
    **overrides,
):
    return _build(
        {
            "vendor_id": vendor_id,
            "trip_leg_id": trip_leg_id,
            "engagement_purpose": engagement_purpose,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "expected_vendor_version": int(expected_vendor_version),
        },
        overrides,
    )


# A sentinel a caller passes to drop an optional field from a payload.
OMIT = _UNSET
