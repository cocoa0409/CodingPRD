"""Request-payload builders.

Each builder emits exactly the field set its endpoint declares, omitting optional
fields unless the caller supplies them so that a test can exercise the declared
defaults. Money is always an integer number of cents, dates are ``YYYY-MM-DD``
strings and datetimes are UTC instants with three fractional digits, matching
PRD 2.5 and PRD 2.11.
"""

from typing import Any, Dict, List, Optional, Sequence

from .constants import (
    CLUSTER_HEALTH_SCIENCE,
    COURSE_ACTIVE,
    SEGMENT_POSTSECONDARY,
    SEGMENT_SECONDARY,
    TIER_NATIONAL,
)
from .types import JsonDict


def _compact(payload: JsonDict) -> JsonDict:
    """Drop the keys whose value the caller left unspecified."""
    return {key: value for key, value in payload.items() if value is not _UNSET}


class _Unset:
    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "<unset>"


_UNSET = _Unset()

#: Sentinel meaning "the caller left this optional field unspecified".
UNSET = _UNSET


# ---------------------------------------------------------------------------
# ProgramOfStudy (PRD 3.1, 3.2, 3.4)
# ---------------------------------------------------------------------------


def program_payload(
    cip_code: str,
    title: str = "Program Of Study",
    cluster: str = CLUSTER_HEALTH_SCIENCE,
    labor_market_data_asof: str = "2026-03-01",
) -> JsonDict:
    return {
        "cip_code": cip_code,
        "title": title,
        "cluster": cluster,
        "labor_market_data_asof": labor_market_data_asof,
    }


def program_patch(
    title: Any = _UNSET,
    cluster: Any = _UNSET,
    labor_market_data_asof: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "title": title,
            "cluster": cluster,
            "labor_market_data_asof": labor_market_data_asof,
        }
    )


def clna_advance_payload(to_phase: str, evidence_url: Any = _UNSET) -> JsonDict:
    return _compact({"to_phase": to_phase, "evidence_url": evidence_url})


def submit_payload(narrative_url: str = "https://district.example/narrative.pdf") -> JsonDict:
    return {"narrative_url": narrative_url}


def request_changes_payload(finding_codes: Sequence[str], note: Any = _UNSET) -> JsonDict:
    return _compact({"finding_codes": list(finding_codes), "note": note})


def state_approve_payload(approval_note: Any = _UNSET) -> JsonDict:
    return _compact({"approval_note": approval_note})


# ---------------------------------------------------------------------------
# SequenceCourse (PRD 3.1)
# ---------------------------------------------------------------------------


def course_payload(
    code: str,
    title: str,
    segment: str,
    position: int,
    credit_hours: float,
    articulated_credit_hours: Any = _UNSET,
    articulation_verified: Any = _UNSET,
    prerequisite_course_id: Any = _UNSET,
    status: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "code": code,
            "title": title,
            "segment": segment,
            "position": position,
            "credit_hours": credit_hours,
            "articulated_credit_hours": articulated_credit_hours,
            "articulation_verified": articulation_verified,
            "prerequisite_course_id": prerequisite_course_id,
            "status": status,
        }
    )


def secondary_course(
    code: str,
    position: int,
    credit_hours: float,
    title: Optional[str] = None,
    status: str = COURSE_ACTIVE,
    prerequisite_course_id: Any = _UNSET,
) -> JsonDict:
    return course_payload(
        code=code,
        title=title or f"Secondary Course {code}",
        segment=SEGMENT_SECONDARY,
        position=position,
        credit_hours=credit_hours,
        status=status,
        prerequisite_course_id=prerequisite_course_id,
    )


def postsecondary_course(
    code: str,
    position: int,
    credit_hours: float,
    articulated_credit_hours: float,
    articulation_verified: bool,
    title: Optional[str] = None,
    status: str = COURSE_ACTIVE,
    prerequisite_course_id: Any = _UNSET,
) -> JsonDict:
    return course_payload(
        code=code,
        title=title or f"Postsecondary Course {code}",
        segment=SEGMENT_POSTSECONDARY,
        position=position,
        credit_hours=credit_hours,
        articulated_credit_hours=articulated_credit_hours,
        articulation_verified=articulation_verified,
        status=status,
        prerequisite_course_id=prerequisite_course_id,
    )


def course_patch(
    status: Any = _UNSET,
    credit_hours: Any = _UNSET,
    articulated_credit_hours: Any = _UNSET,
    articulation_verified: Any = _UNSET,
    prerequisite_course_id: Any = _UNSET,
    position: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "status": status,
            "credit_hours": credit_hours,
            "articulated_credit_hours": articulated_credit_hours,
            "articulation_verified": articulation_verified,
            "prerequisite_course_id": prerequisite_course_id,
            "position": position,
        }
    )


# ---------------------------------------------------------------------------
# Credential and CredentialAttainment (PRD 3.1, 3.6)
# ---------------------------------------------------------------------------


def credential_payload(
    code: str,
    title: Optional[str] = None,
    tier: str = TIER_NATIONAL,
    exam_required: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "code": code,
            "title": title or f"Credential {code}",
            "tier": tier,
            "exam_required": exam_required,
        }
    )


def attainment_payload(
    credential_id: str,
    attained_on: str,
    verification_status: str,
    exam_score: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "credential_id": credential_id,
            "attained_on": attained_on,
            "verification_status": verification_status,
            "exam_score": exam_score,
        }
    )


# ---------------------------------------------------------------------------
# Student (PRD 3.6)
# ---------------------------------------------------------------------------


def student_payload(
    state_student_id: str,
    cohort_year: int,
    special_population_codes: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "state_student_id": state_student_id,
            "cohort_year": cohort_year,
            "special_population_codes": special_population_codes,
        }
    )


def credit_posting_payload(
    sequence_course_id: str, credit_delta: float, posted_on: str
) -> JsonDict:
    return {
        "sequence_course_id": sequence_course_id,
        "credit_delta": credit_delta,
        "posted_on": posted_on,
    }


def exit_payload(exited_on: str, exit_reason: str) -> JsonDict:
    return {"exited_on": exited_on, "exit_reason": exit_reason}


# ---------------------------------------------------------------------------
# AdvisoryCommittee, members and meetings (PRD 3.3)
# ---------------------------------------------------------------------------


def committee_payload(
    expected_program_of_study_version: int,
    name: str = "Program Advisory Committee",
    quorum_min_members: int = 3,
    employer_seat_min: int = 2,
) -> JsonDict:
    return {
        "name": name,
        "quorum_min_members": quorum_min_members,
        "employer_seat_min": employer_seat_min,
        "expected_program_of_study_version": expected_program_of_study_version,
    }


def member_payload(
    full_name: str,
    sector: str,
    seat_code: str,
    term_start_on: str = "2026-01-01",
    term_end_on: str = "2027-12-31",
    is_chair: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "full_name": full_name,
            "sector": sector,
            "seat_code": seat_code,
            "term_start_on": term_start_on,
            "term_end_on": term_end_on,
            "is_chair": is_chair,
        }
    )


def meeting_payload(agenda_kind: str, scheduled_for: str) -> JsonDict:
    return {"agenda_kind": agenda_kind, "scheduled_for": scheduled_for}


def minutes_payload(
    held_at: str,
    attendee_member_ids: Sequence[str],
    vote_yes: int,
    vote_no: int,
    minutes_url: str = "https://district.example/minutes.pdf",
    amendment_reason: Any = _UNSET,
) -> JsonDict:
    return _compact(
        {
            "held_at": held_at,
            "attendee_member_ids": list(attendee_member_ids),
            "vote_yes": vote_yes,
            "vote_no": vote_no,
            "minutes_url": minutes_url,
            "amendment_reason": amendment_reason,
        }
    )


# ---------------------------------------------------------------------------
# GrantAward and Expenditure (PRD 3.7)
# ---------------------------------------------------------------------------


def grant_payload(
    fiscal_year: int,
    allocation_cents: int,
    obligation_window_start: str = "2026-07-01",
    obligation_window_end: str = "2027-06-30",
) -> JsonDict:
    assert isinstance(allocation_cents, int) and not isinstance(allocation_cents, bool), (
        "allocation_cents must be an integer number of cents"
    )
    return {
        "fiscal_year": fiscal_year,
        "allocation_cents": allocation_cents,
        "obligation_window_start": obligation_window_start,
        "obligation_window_end": obligation_window_end,
    }


def expenditure_payload(
    pos_id: str,
    category: str,
    unit_cost_cents: int,
    quantity: int,
    expected_grant_award_version: int,
    service_period_start: str = "2026-09-01",
    service_period_end: str = "2026-09-30",
    description: str = "Charge against the federal award",
    asset_tag: Any = _UNSET,
) -> JsonDict:
    assert isinstance(unit_cost_cents, int) and not isinstance(unit_cost_cents, bool), (
        "unit_cost_cents must be an integer number of cents"
    )
    return _compact(
        {
            "pos_id": pos_id,
            "category": category,
            "description": description,
            "unit_cost_cents": unit_cost_cents,
            "quantity": quantity,
            "service_period_start": service_period_start,
            "service_period_end": service_period_end,
            "asset_tag": asset_tag,
            "expected_grant_award_version": expected_grant_award_version,
        }
    )


def certification_payload(decision: str, finding_code: Any = _UNSET) -> JsonDict:
    return _compact({"decision": decision, "finding_code": finding_code})


def obligate_payload(obligation_reference: str) -> JsonDict:
    return {"obligation_reference": obligation_reference}


def void_payload(void_reason: str) -> JsonDict:
    return {"void_reason": void_reason}


# ---------------------------------------------------------------------------
# Educator (PRD 3.5)
# ---------------------------------------------------------------------------


def educator_payload(
    full_name: str,
    certification_route: str,
    claimed_industry_hours: int,
    credential_expires_on: str = "2029-06-30",
) -> JsonDict:
    return {
        "full_name": full_name,
        "certification_route": certification_route,
        "claimed_industry_hours": claimed_industry_hours,
        "credential_expires_on": credential_expires_on,
    }


def verification_payload(verified_hours: int, verification_source: str) -> JsonDict:
    return {
        "verified_hours": verified_hours,
        "verification_source": verification_source,
    }


# ---------------------------------------------------------------------------
# PerformanceIndicator (PRD 3.8)
# ---------------------------------------------------------------------------


def indicator_payload(
    indicator_code: str,
    reporting_year: int,
    baseline_pct: float,
    cohort_year: int,
) -> JsonDict:
    return {
        "indicator_code": indicator_code,
        "reporting_year": reporting_year,
        "baseline_pct": baseline_pct,
        "cohort_year": cohort_year,
    }


def offer_payload(offered_level_pct: float, rationale: Any = _UNSET) -> JsonDict:
    return _compact({"offered_level_pct": offered_level_pct, "rationale": rationale})


def accept_level_payload(acceptance_note: Any = _UNSET) -> JsonDict:
    return _compact({"acceptance_note": acceptance_note})


def close_year_payload(closed_on: str) -> JsonDict:
    return {"closed_on": closed_on}


# ---------------------------------------------------------------------------
# ImprovementPlan (PRD 3.9)
# ---------------------------------------------------------------------------


def milestone(label: str, due_on: str) -> JsonDict:
    return {"label": label, "due_on": due_on}


def plan_payload(
    milestones: Sequence[JsonDict], funding_expenditure_id: Any = _UNSET
) -> JsonDict:
    return _compact(
        {
            "milestones": list(milestones),
            "funding_expenditure_id": funding_expenditure_id,
        }
    )


def three_milestones(
    prefix: str = "Milestone", due_dates: Optional[Sequence[str]] = None
) -> List[JsonDict]:
    dates = list(due_dates or ["2026-10-01", "2026-11-01", "2026-12-01"])
    return [milestone(f"{prefix} {n + 1}", date) for n, date in enumerate(dates)]


def plan_submit_payload(submission_note: Any = _UNSET) -> JsonDict:
    return _compact({"submission_note": submission_note})


def plan_return_payload(return_reason: str) -> JsonDict:
    return {"return_reason": return_reason}


def plan_accept_payload(acceptance_note: Any = _UNSET) -> JsonDict:
    return _compact({"acceptance_note": acceptance_note})


# ---------------------------------------------------------------------------
# Query parameters (PRD 2.3)
# ---------------------------------------------------------------------------


def page(limit: Any = _UNSET, offset: Any = _UNSET, **filters: Any) -> Dict[str, Any]:
    """Query parameters for a collection read."""
    params = _compact({"limit": limit, "offset": offset})
    params.update({key: value for key, value in filters.items() if value is not _UNSET})
    return params
