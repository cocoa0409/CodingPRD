"""Request payload builders.

One builder per write endpoint, returning a valid body whose defaults any test
can override by keyword. Coordinates, radii, durations, budgets and basis-point
figures are emitted as JSON numbers of the declared type, never as strings, and
every instant is a full ISO 8601 UTC instant rather than a bare date.

The justification texts at the top are pinned to exact character counts because
the justification-length rule compares a trimmed character count against a
per-agency configured minimum.
"""

from typing import Any, Dict, Optional

from .constants import (
    ACTION_OPT_OUT,
    AUDIT_DECISION_CLEAR,
    CATEGORY_SAFETY_REPORT,
    DECLINE_OWNER_DECLINE,
    DECISION_UPHELD_PUBLISH,
    DUTY_ROLE_REQUESTER,
    ONBOARDING_DECISION_APPROVE,
    OPENED_REASON_RESIDENT_FLAGS,
    PURGE_OWNER_REVOCATION,
)

# ── Justification texts of known length ────────────────────────────────────

# 79 characters: one short of the default configured minimum of 80.
JUSTIFICATION_79 = (
    "Break-ins overnight on the 400 block; footage sought to identify a suspect car."
)
# 80 characters: exactly the default configured minimum.
JUSTIFICATION_80 = (
    "Break-ins overnight on the 400 block; footage sought to identify a suspect cars."
)
# 150 characters: comfortably over a minimum of 80, one short of a minimum of 200.
JUSTIFICATION_150 = (
    "Repeated vehicle break-ins reported overnight on the 400 block; footage sought "
    "to identify a suspect vehicle described by three separate complainants."
)
# 200 characters: exactly a configured minimum of 200.
JUSTIFICATION_200 = (
    "Repeated vehicle break-ins reported overnight on the 400 block; footage is "
    "sought to identify a suspect vehicle described by three separate complainants "
    "and to corroborate the incident timeline fully."
)

STATUTORY_BASIS = "Municipal Code 12.44"


def _payload(**fields: Any) -> Dict[str, Any]:
    """Drop the keys whose value was left unset, keeping explicit nulls."""
    return {key: value for key, value in fields.items() if value is not _UNSET}


class _Unset:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()


# ── Logical clock ──────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# ── Agency ─────────────────────────────────────────────────────────────────

def agency_payload(
    name: str = "Riverbend Police Department",
    jurisdiction_code: str = "RB-001",
    min_device_threshold: Any = _UNSET,
    max_open_requests: Any = _UNSET,
    period_request_quota: Any = _UNSET,
    post_share_retention_days: Any = _UNSET,
    justification_min_chars: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    """A registration body for a law-enforcement agency.

    Only the two required fields are sent unless a configuration knob is named,
    so the declared defaults stay observable.
    """
    payload = _payload(
        name=name,
        jurisdiction_code=jurisdiction_code,
        min_device_threshold=min_device_threshold,
        max_open_requests=max_open_requests,
        period_request_quota=period_request_quota,
        post_share_retention_days=post_share_retention_days,
        justification_min_chars=justification_min_chars,
    )
    payload.update(overrides)
    return payload


def onboarding_review_payload(
    decision: str = ONBOARDING_DECISION_APPROVE,
    reviewer_note: str = "Memorandum of understanding on file.",
    onboarding_agreement_version: Any = "MOU-2026.3",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        decision=decision,
        reviewer_note=reviewer_note,
        onboarding_agreement_version=onboarding_agreement_version,
    )
    payload.update(overrides)
    return payload


def status_change_payload(
    target_status: str,
    reason: str = "Audit finding pending resolution.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(target_status=target_status, reason=reason)
    payload.update(overrides)
    return payload


# ── Officer ────────────────────────────────────────────────────────────────

def officer_payload(
    agency_id: str,
    badge_number: str = "B-100",
    full_name: str = "Officer Vale",
    duty_role: Any = DUTY_ROLE_REQUESTER,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        agency_id=agency_id,
        badge_number=badge_number,
        full_name=full_name,
        duty_role=duty_role,
    )
    payload.update(overrides)
    return payload


# ── Resident ───────────────────────────────────────────────────────────────

def resident_payload(
    display_name: str = "Rowan Diaz",
    email: str = "rowan@example.test",
    home_x_m: int = 0,
    home_y_m: int = 10,
    alert_radius_m: Any = _UNSET,
    notification_budget_per_day: Any = _UNSET,
    notification_mute_enabled: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    """A resident self-registration body.

    Optional configuration is omitted unless named so the declared defaults
    stay observable.
    """
    payload = _payload(
        display_name=display_name,
        email=email,
        home_x_m=home_x_m,
        home_y_m=home_y_m,
        alert_radius_m=alert_radius_m,
        notification_budget_per_day=notification_budget_per_day,
        notification_mute_enabled=notification_mute_enabled,
    )
    payload.update(overrides)
    return payload


def alert_settings_payload(
    alert_radius_m: Any = _UNSET,
    notification_budget_per_day: Any = _UNSET,
    notification_mute_enabled: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    """A partial update over the three alert-configuration fields."""
    payload = _payload(
        alert_radius_m=alert_radius_m,
        notification_budget_per_day=notification_budget_per_day,
        notification_mute_enabled=notification_mute_enabled,
    )
    payload.update(overrides)
    return payload


def data_control_payload(
    action_type: str = ACTION_OPT_OUT,
    reason: Any = "Stepping back from requests.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(action_type=action_type, reason=reason)
    payload.update(overrides)
    return payload


# ── Device ─────────────────────────────────────────────────────────────────

def device_payload(
    owner_resident_id: str,
    label: str = "Front door camera",
    grid_x_m: int = 0,
    grid_y_m: int = 10,
    retention_window_days: Any = _UNSET,
    auto_decline_requests: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        owner_resident_id=owner_resident_id,
        label=label,
        grid_x_m=grid_x_m,
        grid_y_m=grid_y_m,
        retention_window_days=retention_window_days,
        auto_decline_requests=auto_decline_requests,
    )
    payload.update(overrides)
    return payload


def device_patch_payload(
    label: Any = _UNSET,
    retention_window_days: Any = _UNSET,
    auto_decline_requests: Any = _UNSET,
    status: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    """A partial update over the four updatable camera fields."""
    payload = _payload(
        label=label,
        retention_window_days=retention_window_days,
        auto_decline_requests=auto_decline_requests,
        status=status,
    )
    payload.update(overrides)
    return payload


# ── Canvass area ───────────────────────────────────────────────────────────

def request_area_payload(
    agency_id: str,
    center_x_m: int = 0,
    center_y_m: int = 0,
    radius_m: int = 500,
    window_start_utc: str = "2026-08-08T00:00:00Z",
    window_end_utc: str = "2026-08-08T06:00:00Z",
    area_label: Any = "400 Block",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        agency_id=agency_id,
        center_x_m=center_x_m,
        center_y_m=center_y_m,
        radius_m=radius_m,
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        area_label=area_label,
    )
    payload.update(overrides)
    return payload


# ── Video request ──────────────────────────────────────────────────────────

def video_request_payload(
    request_area_id: str,
    expected_request_area_version: int,
    case_number: str = "CASE-9001",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        request_area_id=request_area_id,
        case_number=case_number,
        expected_request_area_version=expected_request_area_version,
    )
    payload.update(overrides)
    return payload


def justification_payload(
    justification_text: str = JUSTIFICATION_150,
    statutory_basis: Any = STATUTORY_BASIS,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        justification_text=justification_text, statutory_basis=statutory_basis
    )
    payload.update(overrides)
    return payload


def withdraw_payload(
    reason: str = "Investigation closed without needing footage.", **overrides: Any
) -> Dict[str, Any]:
    payload = _payload(reason=reason)
    payload.update(overrides)
    return payload


def audit_review_payload(
    decision: str = AUDIT_DECISION_CLEAR,
    audit_note: Any = "Scope and statutory basis reviewed.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(decision=decision, audit_note=audit_note)
    payload.update(overrides)
    return payload


# ── Consent and footage ────────────────────────────────────────────────────

def share_payload(
    recorded_start_utc: str = "2026-08-08T01:00:00Z",
    duration_seconds: int = 1800,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        recorded_start_utc=recorded_start_utc, duration_seconds=duration_seconds
    )
    payload.update(overrides)
    return payload


def decline_payload(
    decline_reason: str = DECLINE_OWNER_DECLINE, **overrides: Any
) -> Dict[str, Any]:
    payload = _payload(decline_reason=decline_reason)
    payload.update(overrides)
    return payload


def purge_payload(
    purge_reason: str = PURGE_OWNER_REVOCATION, **overrides: Any
) -> Dict[str, Any]:
    payload = _payload(purge_reason=purge_reason)
    payload.update(overrides)
    return payload


# ── Community feed ─────────────────────────────────────────────────────────

def post_payload(
    author_resident_id: str,
    body: str = "Saw a delivery van idling by the corner for twenty minutes this evening.",
    category: str = CATEGORY_SAFETY_REPORT,
    post_x_m: int = 0,
    post_y_m: int = 0,
    parent_post_id: Any = _UNSET,
    alert_fanout_cap: Any = _UNSET,
    protected_class_term_count: Any = _UNSET,
    unverified_assertion_count: Any = _UNSET,
    location_profiling_count: Any = _UNSET,
    hostile_tone_count: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    """A neighbourhood post body.

    The four classifier signals are omitted unless named, so a post with no
    signals scores zero and publishes.
    """
    payload = _payload(
        author_resident_id=author_resident_id,
        body=body,
        category=category,
        post_x_m=post_x_m,
        post_y_m=post_y_m,
        parent_post_id=parent_post_id,
        alert_fanout_cap=alert_fanout_cap,
        protected_class_term_count=protected_class_term_count,
        unverified_assertion_count=unverified_assertion_count,
        location_profiling_count=location_profiling_count,
        hostile_tone_count=hostile_tone_count,
    )
    payload.update(overrides)
    return payload


def flag_payload(
    flag_reason: Any = "Reads as targeting a group rather than reporting an incident.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(flag_reason=flag_reason)
    payload.update(overrides)
    return payload


def revise_payload(
    body: str = "Rewritten to describe only what happened, with no reference to anyone's identity.",
    protected_class_term_count: Any = _UNSET,
    unverified_assertion_count: Any = _UNSET,
    location_profiling_count: Any = _UNSET,
    hostile_tone_count: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        body=body,
        protected_class_term_count=protected_class_term_count,
        unverified_assertion_count=unverified_assertion_count,
        location_profiling_count=location_profiling_count,
        hostile_tone_count=hostile_tone_count,
    )
    payload.update(overrides)
    return payload


# ── Moderation ─────────────────────────────────────────────────────────────

def moderation_case_payload(
    resident_post_id: str,
    expected_resident_post_version: int,
    opened_reason: str = OPENED_REASON_RESIDENT_FLAGS,
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        resident_post_id=resident_post_id,
        opened_reason=opened_reason,
        expected_resident_post_version=expected_resident_post_version,
    )
    payload.update(overrides)
    return payload


def decide_case_payload(
    decision: str = DECISION_UPHELD_PUBLISH,
    decision_note: Any = "Reviewed against the community standards.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(decision=decision, decision_note=decision_note)
    payload.update(overrides)
    return payload


# ── Transparency ───────────────────────────────────────────────────────────

def report_payload(
    agency_id: str,
    expected_agency_version: int,
    period_start_utc: str = "2026-08-01T00:00:00Z",
    period_end_utc: str = "2026-09-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(
        agency_id=agency_id,
        period_start_utc=period_start_utc,
        period_end_utc=period_end_utc,
        expected_agency_version=expected_agency_version,
    )
    payload.update(overrides)
    return payload


def certify_payload(
    certification_note: str = "Figures reconciled against the solicitation ledger.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload = _payload(certification_note=certification_note)
    payload.update(overrides)
    return payload


# ── Pagination and filters ─────────────────────────────────────────────────

def page(limit: Optional[int] = None, offset: Optional[int] = None, **filters: Any) -> Dict[str, Any]:
    """Query parameters for a collection read."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    params.update({k: v for k, v in filters.items() if v is not None})
    return params
