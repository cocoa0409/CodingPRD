"""
Request payload factories.

Each builder returns a plain dict carrying exactly the declared input fields for
its endpoint, with keyword overrides for the field under test. Money is always
an integer number of cents and service quantities are always whole 15-minute
units, so no factory ever emits a float or a string for either.

Optional fields are omitted unless supplied, so that a factory never
accidentally exercises a default the test did not intend. Pass ``None``
explicitly only where a test means to send a JSON null.
"""

from typing import Any, Dict, List, Optional

from .constants import ALL_DOMAINS

_OMIT = object()


def _compact(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop keys whose value is the internal omission sentinel."""
    return {k: v for k, v in payload.items() if v is not _OMIT}


# ─── Logical clock ────────────────────────────────────────────────────

def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ─── Child ────────────────────────────────────────────────────────────

def child_payload(
    first_name: str = "Ada",
    last_name: str = "Nolan",
    date_of_birth: str = "2024-06-15",
    county_code: str = "CNT_A",
    primary_language: str = "EN",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "first_name": first_name,
        "last_name": last_name,
        "date_of_birth": date_of_birth,
        "county_code": county_code,
        "primary_language": primary_language,
    }
    payload.update(overrides)
    return payload


# ─── Service coordinator ──────────────────────────────────────────────

def coordinator_payload(
    full_name: str = "Dana Reyes",
    county_code: str = "CNT_A",
    language_codes: Optional[List[str]] = None,
    max_weighted_caseload_points: float = 12.00,
    status: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "full_name": full_name,
        "county_code": county_code,
        "language_codes": list(language_codes) if language_codes else ["EN"],
        "max_weighted_caseload_points": max_weighted_caseload_points,
        "status": status,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Referral ─────────────────────────────────────────────────────────

def referral_payload(
    child_id: str,
    primary_referral_source: str = "PHYSICIAN",
    referral_received_date: str = "2026-03-02",
    county_code: str = "CNT_A",
    presenting_concern: str = (
        "Expressive language delay noted at the 20-month well-child visit"
    ),
    interpreter_required: Any = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "child_id": child_id,
        "primary_referral_source": primary_referral_source,
        "referral_received_date": referral_received_date,
        "county_code": county_code,
        "presenting_concern": presenting_concern,
        "interpreter_required": interpreter_required,
    }
    payload.update(overrides)
    return _compact(payload)


def assign_coordinator_payload(coordinator_id: Any = _OMIT, **overrides: Any) -> Dict[str, Any]:
    """Omitting ``coordinator_id`` requests the deterministic auto-selection."""
    payload = {"coordinator_id": coordinator_id}
    payload.update(overrides)
    return _compact(payload)


def eligibility_determination_payload(
    is_eligible: bool = True,
    determination_date: str = "2026-03-20",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {"is_eligible": is_eligible, "determination_date": determination_date}
    payload.update(overrides)
    return payload


def entry_outcomes_payload(
    measurement_date: str = "2026-03-20",
    rating_social: int = 3,
    rating_knowledge: int = 4,
    rating_needs: int = 3,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "measurement_date": measurement_date,
        "rating_social": rating_social,
        "rating_knowledge": rating_knowledge,
        "rating_needs": rating_needs,
    }
    payload.update(overrides)
    return payload


def exit_payload(
    exit_date: str,
    exit_reason: str = "REACHED_AGE_THREE",
    exit_rating_social: Any = _OMIT,
    exit_rating_knowledge: Any = _OMIT,
    exit_rating_needs: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "exit_date": exit_date,
        "exit_reason": exit_reason,
        "exit_rating_social": exit_rating_social,
        "exit_rating_knowledge": exit_rating_knowledge,
        "exit_rating_needs": exit_rating_needs,
    }
    payload.update(overrides)
    return _compact(payload)


def contact_log_payload(
    contact_date: str,
    contact_method: str = "HOME_VISIT",
    contact_type: str = "MONTHLY_CHECK_IN",
    summary: str = (
        "Reviewed routines and confirmed the therapy schedule with the family."
    ),
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "contact_date": contact_date,
        "contact_method": contact_method,
        "contact_type": contact_type,
        "summary": summary,
    }
    payload.update(overrides)
    return payload


# ─── Assessment ───────────────────────────────────────────────────────

def assessment_payload(
    referral_id: str,
    assessment_type: str = "INITIAL_EVALUATION",
    scheduled_date: str = "2026-03-10",
    setting_code: str = "HOME",
    natural_environment_justification: Any = _OMIT,
    domains_assessed: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    if domains_assessed is _OMIT and assessment_type == "INITIAL_EVALUATION":
        domains_assessed = list(ALL_DOMAINS)
    payload = {
        "referral_id": referral_id,
        "assessment_type": assessment_type,
        "scheduled_date": scheduled_date,
        "setting_code": setting_code,
        "natural_environment_justification": natural_environment_justification,
        "domains_assessed": domains_assessed,
    }
    payload.update(overrides)
    return _compact(payload)


def complete_assessment_payload(
    completion_date: str,
    eligibility_recommendation: str = "ELIGIBLE",
    family_unavailable_days: Any = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "completion_date": completion_date,
        "eligibility_recommendation": eligibility_recommendation,
        "family_unavailable_days": family_unavailable_days,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Plan and service lines ───────────────────────────────────────────

def ifsp_payload(
    referral_id: str,
    authoring_coordinator_id: str,
    expected_referral_version: int,
    ifsp_type: str = "INITIAL",
    meeting_date: str = "2026-03-20",
    supersedes_ifsp_id: Any = _OMIT,
    natural_environment_justification: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "referral_id": referral_id,
        "ifsp_type": ifsp_type,
        "meeting_date": meeting_date,
        "authoring_coordinator_id": authoring_coordinator_id,
        "expected_referral_version": expected_referral_version,
        "supersedes_ifsp_id": supersedes_ifsp_id,
        "natural_environment_justification": natural_environment_justification,
    }
    payload.update(overrides)
    return _compact(payload)


def consent_payload(
    consent_scope: str = "FULL",
    consent_signed_date: str = "2026-03-20",
    declined_service_ids: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "consent_scope": consent_scope,
        "consent_signed_date": consent_signed_date,
        "declined_service_ids": declined_service_ids,
    }
    payload.update(overrides)
    return _compact(payload)


def ifsp_service_payload(
    ifsp_id: str,
    service_type: str = "SPEECH_THERAPY",
    setting_code: str = "HOME",
    frequency_per_month: int = 4,
    units_per_session: int = 2,
    unit_rate_cents: int = 6500,
    planned_units_total: int = 96,
    natural_environment_justification: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "ifsp_id": ifsp_id,
        "service_type": service_type,
        "setting_code": setting_code,
        "frequency_per_month": frequency_per_month,
        "units_per_session": units_per_session,
        "unit_rate_cents": unit_rate_cents,
        "planned_units_total": planned_units_total,
        "natural_environment_justification": natural_environment_justification,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Provider network ─────────────────────────────────────────────────

def provider_payload(
    agency_name: str = "Riverbend Therapy",
    qualified_service_types: Optional[List[str]] = None,
    credential_expiry_date: str = "2027-06-30",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "agency_name": agency_name,
        "qualified_service_types": (
            list(qualified_service_types)
            if qualified_service_types
            else ["SPEECH_THERAPY"]
        ),
        "credential_expiry_date": credential_expiry_date,
    }
    payload.update(overrides)
    return payload


def suspend_provider_payload(
    suspension_reason_code: str = "QUALITY_CONCERN",
    effective_date: str = "2026-04-06",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "suspension_reason_code": suspension_reason_code,
        "effective_date": effective_date,
    }
    payload.update(overrides)
    return payload


def authorization_payload(
    ifsp_service_id: str,
    provider_id: str,
    start_date: str = "2026-03-21",
    end_date: str = "2026-04-30",
    authorized_units: int = 24,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "ifsp_service_id": ifsp_service_id,
        "provider_id": provider_id,
        "start_date": start_date,
        "end_date": end_date,
        "authorized_units": authorized_units,
    }
    payload.update(overrides)
    return payload


def revoke_authorization_payload(
    revocation_reason_code: str = "ADMIN_CORRECTION", **overrides: Any
) -> Dict[str, Any]:
    payload = {"revocation_reason_code": revocation_reason_code}
    payload.update(overrides)
    return payload


# ─── Visits ───────────────────────────────────────────────────────────

def visit_payload(
    provider_authorization_id: str,
    scheduled_start: str,
    scheduled_end: str,
    setting_code: str = "HOME",
    makeup_for_visit_id: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "provider_authorization_id": provider_authorization_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "setting_code": setting_code,
        "makeup_for_visit_id": makeup_for_visit_id,
    }
    payload.update(overrides)
    return _compact(payload)


def document_visit_payload(
    visit_status: str = "DELIVERED",
    actual_units: Any = _OMIT,
    actual_start: Any = _OMIT,
    actual_end: Any = _OMIT,
    session_note: Any = (
        "Parent coaching on requesting during play routines."
    ),
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "visit_status": visit_status,
        "actual_units": actual_units,
        "actual_start": actual_start,
        "actual_end": actual_end,
        "session_note": session_note,
    }
    payload.update(overrides)
    return _compact(payload)


def void_visit_payload(
    void_reason_code: str = "DOCUMENTATION_ERROR", **overrides: Any
) -> Dict[str, Any]:
    payload = {"void_reason_code": void_reason_code}
    payload.update(overrides)
    return payload


# ─── Family cost participation ────────────────────────────────────────

def cost_share_payload(
    referral_id: str,
    effective_month: str = "2026-03",
    household_size: int = 4,
    declared_annual_gross_income_cents: int = 12_000_000,
    insurance_use_consent: bool = False,
    insurance_policy_id: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "referral_id": referral_id,
        "effective_month": effective_month,
        "household_size": household_size,
        "declared_annual_gross_income_cents": declared_annual_gross_income_cents,
        "insurance_use_consent": insurance_use_consent,
        "insurance_policy_id": insurance_policy_id,
    }
    payload.update(overrides)
    return _compact(payload)


def finalize_cost_share_payload(
    verified_annual_gross_income_cents: int,
    verification_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "verified_annual_gross_income_cents": verified_annual_gross_income_cents,
        "verification_date": verification_date,
    }
    payload.update(overrides)
    return payload


def waive_payload(
    waive_amount_cents: int,
    waiver_reason_code: str = "HARDSHIP",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "waive_amount_cents": waive_amount_cents,
        "waiver_reason_code": waiver_reason_code,
    }
    payload.update(overrides)
    return payload


def insurance_consent_payload(
    insurance_use_consent: bool = True,
    insurance_policy_id: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "insurance_use_consent": insurance_use_consent,
        "insurance_policy_id": insurance_policy_id,
    }
    payload.update(overrides)
    return _compact(payload)


# ─── Transition planning ──────────────────────────────────────────────

def transition_plan_payload(
    ifsp_id: str,
    target_conference_date: str,
    conference_held_date: Any = _OMIT,
    transition_steps_count: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "ifsp_id": ifsp_id,
        "target_conference_date": target_conference_date,
        "conference_held_date": conference_held_date,
        "transition_steps_count": transition_steps_count,
    }
    payload.update(overrides)
    return _compact(payload)


def notify_lea_payload(
    notification_date: str,
    family_opt_out: bool = False,
    lea_code: Any = _OMIT,
    opt_out_signed_date: Any = _OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = {
        "notification_date": notification_date,
        "family_opt_out": family_opt_out,
        "lea_code": lea_code,
        "opt_out_signed_date": opt_out_signed_date,
    }
    payload.update(overrides)
    return _compact(payload)
