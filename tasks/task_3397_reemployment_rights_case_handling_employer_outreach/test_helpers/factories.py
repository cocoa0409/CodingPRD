"""Request payload builders.

Each builder returns a valid body for one write endpoint, with sensible
defaults that any test can override by keyword. Optional fields declared with
a null default in the PRD (``end_date``, ``notice_given_at``,
``application_submitted_at``, ``excuse_claimed``, ``excuse_category``,
``employer_affiliation_id``, ``term_months``, ``reason``, ``counter_text``,
``info_request_note``) are omitted from the body when left at ``None`` so the
server's own default handling is what gets exercised; pass an explicit value
(including an explicit null via ``include_nulls``) to send the key.
"""

from typing import Any, Dict, Optional


def _put_optional(payload: Dict[str, Any], key: str, value: Any, include_nulls: bool) -> None:
    if value is not None or include_nulls:
        payload[key] = value


# ── Logical clock ──────────────────────────────────────────────────────────

def clock_payload(to_iso8601: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload


# ── Registrations ──────────────────────────────────────────────────────────

def member_payload(
    full_name: str = "Rae Torres",
    email: str = "rae@example.com",
    branch: str = "ARMY",
    component: str = "ARMY_RESERVE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "email": email,
        "branch": branch,
        "component": component,
    }
    payload.update(overrides)
    return payload


def employer_payload(
    legal_name: str = "Cascade Outfitters Inc",
    sector: str = "RETAIL",
    size_tier: str = "MEDIUM",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name,
        "sector": sector,
        "size_tier": size_tier,
    }
    payload.update(overrides)
    return payload


def ombudsman_payload(
    full_name: str = "Ada Weiss",
    email: str = "ada@example.com",
    employer_affiliation_id: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"full_name": full_name, "email": email}
    _put_optional(payload, "employer_affiliation_id", employer_affiliation_id, include_nulls)
    payload.update(overrides)
    return payload


# ── Service record ─────────────────────────────────────────────────────────

def service_period_payload(
    member_id: str,
    employer_id: str,
    start_date: str = "2026-01-01T00:00:00Z",
    orders_type: str = "DRILL",
    end_date: Optional[str] = None,
    notice_given_at: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "employer_id": employer_id,
        "start_date": start_date,
        "orders_type": orders_type,
    }
    _put_optional(payload, "end_date", end_date, include_nulls)
    _put_optional(payload, "notice_given_at", notice_given_at, include_nulls)
    payload.update(overrides)
    return payload


# ── Cases ──────────────────────────────────────────────────────────────────

def case_payload(
    member_id: str,
    employer_id: str,
    issue_type: str = "REEMPLOYMENT",
    description: str = "Refused reinstatement after active duty",
    application_submitted_at: Optional[str] = None,
    excuse_claimed: Optional[bool] = None,
    excuse_category: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "member_id": member_id,
        "employer_id": employer_id,
        "issue_type": issue_type,
        "description": description,
    }
    _put_optional(payload, "application_submitted_at", application_submitted_at, include_nulls)
    _put_optional(payload, "excuse_claimed", excuse_claimed, include_nulls)
    _put_optional(payload, "excuse_category", excuse_category, include_nulls)
    payload.update(overrides)
    return payload


def assign_payload(
    ombudsman_id: str,
    expected_case_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ombudsman_id": ombudsman_id,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def case_state_payload(
    to_status: str,
    reason: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    _put_optional(payload, "reason", reason, include_nulls)
    payload.update(overrides)
    return payload


def eligibility_analysis_payload(
    variant: str = "STRICT",
    expected_case_version: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "variant": variant,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


# ── Mediation ──────────────────────────────────────────────────────────────

def mediation_round_payload(
    case_id: str,
    proposal_text: str = "Reinstate at prior role with back pay.",
    addressed_to: str = "EMPLOYER",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "proposal_text": proposal_text,
        "addressed_to": addressed_to,
    }
    payload.update(overrides)
    return payload


def round_response_payload(
    response: str,
    counter_text: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"response": response}
    _put_optional(payload, "counter_text", counter_text, include_nulls)
    payload.update(overrides)
    return payload


def case_note_payload(
    case_id: str,
    note_type: str = "CONTACT",
    body: str = "Employer contacted about the pending proposal.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "note_type": note_type,
        "body": body,
    }
    payload.update(overrides)
    return payload


# ── Benefits ───────────────────────────────────────────────────────────────

def benefit_assessment_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"case_id": case_id}
    payload.update(overrides)
    return payload


# ── Referrals ──────────────────────────────────────────────────────────────

def referral_payload(
    case_id: str,
    agency: str = "DOL_VETS",
    summary: str = "Informal resolution failed; statutory violation alleged.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "agency": agency,
        "summary": summary,
    }
    payload.update(overrides)
    return payload


def referral_state_payload(
    to_status: str,
    info_request_note: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    _put_optional(payload, "info_request_note", info_request_note, include_nulls)
    payload.update(overrides)
    return payload


# ── Statements of support ──────────────────────────────────────────────────

def statement_payload(
    employer_id: str,
    signer_name: str = "J. Ho",
    signer_title: str = "CEO",
    term_months: Optional[int] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "signer_name": signer_name,
        "signer_title": signer_title,
    }
    _put_optional(payload, "term_months", term_months, include_nulls)
    payload.update(overrides)
    return payload


def statement_state_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


# ── Recognition awards ─────────────────────────────────────────────────────

def award_payload(
    employer_id: str,
    tier: str = "BRONZE",
    rationale: str = "Clean informal resolutions and a signed statement.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "tier": tier,
        "rationale": rationale,
    }
    payload.update(overrides)
    return payload


def award_state_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


# ── Outreach events ────────────────────────────────────────────────────────

def event_payload(
    title: str = "Employer Rights Briefing",
    venue: str = "Hall-A",
    starts_at: str = "2026-10-10T10:00:00Z",
    ends_at: str = "2026-10-10T12:00:00Z",
    topic: str = "RIGHTS_OVERVIEW",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "title": title,
        "venue": venue,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "topic": topic,
    }
    payload.update(overrides)
    return payload


def event_state_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


# ── Training records ───────────────────────────────────────────────────────

def training_record_payload(
    ombudsman_id: str,
    module_code: str = "CORE_LAW",
    hours: float = 8,
    exam_score: int = 90,
    completed_on: str = "2026-08-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ombudsman_id": ombudsman_id,
        "module_code": module_code,
        "hours": hours,
        "exam_score": exam_score,
        "completed_on": completed_on,
    }
    payload.update(overrides)
    return payload


def ombudsman_state_payload(
    to_status: str,
    reason: Optional[str] = None,
    include_nulls: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    _put_optional(payload, "reason", reason, include_nulls)
    payload.update(overrides)
    return payload
