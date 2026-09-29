"""Composable setup for the SafeSport compliance suite.

The helpers here build the state a test needs through the public API only, and
every one of them re-reads the resources it touched so a caller always gets the
current ``version``.  Setup steps use ``get_success_data`` rather than
``validate_success`` so that a broken precondition surfaces as a readable setup
failure instead of an envelope assertion.

Nothing in this module asserts a rule under test; the assertions live in the
test files.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .test_users import (
    NGB_ADMIN_HEADERS,
    OFFICER_INTAKE_HEADERS,
    SCREENING_VENDOR_HEADERS,
    COMPLIANCE_AUDITOR_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    make_club_admin_headers,
    make_member_headers,
)


# ----------------------------------------------------------------------
# Tier 1: the client and the logical clock
# ----------------------------------------------------------------------
@pytest.fixture
def api() -> ApiClient:
    """A client bound to the server under test."""
    return ApiClient()


def set_clock(api: ApiClient, instant: str) -> Dict[str, Any]:
    """Move the server's logical clock to ``instant`` (PRD 2.5)."""
    return get_success_data(api.set_clock(instant, NGB_ADMIN_HEADERS))


# ----------------------------------------------------------------------
# Tier 2: clubs
# ----------------------------------------------------------------------
def create_club(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Charter a club with governing-body staff (PRD 3.1)."""
    return get_success_data(
        api.charter_club(f.club_payload(**overrides), NGB_ADMIN_HEADERS), 201
    )


def read_club(api: ApiClient, club_id: str) -> Dict[str, Any]:
    """Re-read a club so the caller sees its current version and posture."""
    return get_success_data(api.get_club(club_id, NGB_ADMIN_HEADERS))


def fund_escrow(api: ApiClient, club_id: str, amount_cents: int) -> Dict[str, Any]:
    """Add screening escrow to a club (PRD 3.1)."""
    return get_success_data(
        api.fund_escrow(
            club_id, f.escrow_funding_payload(amount_cents), NGB_ADMIN_HEADERS
        )
    )


@pytest.fixture
def club(api: ApiClient) -> Dict[str, Any]:
    """A chartered club with a funded escrow and a minor-athlete program."""
    return create_club(api)


@pytest.fixture
def other_club(api: ApiClient) -> Dict[str, Any]:
    """A second chartered club, used to observe club-scope boundaries."""
    return create_club(api, name="Lakeside Community Sports", state_code="WA")


# ----------------------------------------------------------------------
# Tier 3: members
# ----------------------------------------------------------------------
def create_member(api: ApiClient, club_id: str, **overrides: Any) -> Dict[str, Any]:
    """Register a coach or volunteer at ``club_id`` (PRD 3.1)."""
    return get_success_data(
        api.register_member(
            f.member_payload(club_id, **overrides), make_club_admin_headers(club_id)
        ),
        201,
    )


def read_member(api: ApiClient, member_id: str) -> Dict[str, Any]:
    """Re-read a member so the caller sees the current version and derived fields."""
    return get_success_data(api.get_member(member_id, NGB_ADMIN_HEADERS))


@pytest.fixture
def member(api: ApiClient, club: Dict[str, Any]) -> Dict[str, Any]:
    """A freshly registered volunteer: UNSCREENED, PENDING, NEVER, RESTRICTED."""
    return create_member(api, club["id"])


# ----------------------------------------------------------------------
# Tier 4: screening
# ----------------------------------------------------------------------
def order_screening(
    api: ApiClient, club_id: str, member_id: str, expedited: bool = False, **overrides: Any
) -> Dict[str, Any]:
    """Order a screen, pinning the club's current version (PRD 3.2)."""
    club = read_club(api, club_id)
    payload = f.screening_order_payload(club["version"], expedited, **overrides)
    return get_success_data(
        api.order_screening(member_id, payload, make_club_admin_headers(club_id)), 201
    )


def return_vendor_result(
    api: ApiClient, order_id: str, vendor_disposition: str = "NO_RECORD"
) -> Dict[str, Any]:
    """Post the vendor's raw return against an ORDERED screen (PRD 3.3)."""
    return get_success_data(
        api.post_screening_result(
            order_id, f.vendor_result_payload(vendor_disposition), SCREENING_VENDOR_HEADERS
        )
    )


def adjudicate(
    api: ApiClient,
    order_id: str,
    disposition: str = "CLEAR",
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Adjudicate a returned screen against the disqualifying criteria (PRD 3.3)."""
    return get_success_data(
        api.adjudicate_screening_order(
            order_id,
            f.adjudication_payload(disposition),
            headers or OFFICER_ADJUDICATOR_HEADERS,
        )
    )


def clear_screening(
    api: ApiClient, club_id: str, member_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a member's screening dimension all the way to CLEARED (PRD 3.2, PRD 3.3).

    Returns the adjudicated order and the re-read member.
    """
    order = order_screening(api, club_id, member_id)
    return_vendor_result(api, order["id"], "NO_RECORD")
    order = adjudicate(api, order["id"], "CLEAR")
    return order, read_member(api, member_id)


def flag_and_record_screening(
    api: ApiClient, club_id: str, member_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Take a member through FLAGGED to CLEARED on a non-disqualifying record."""
    order = order_screening(api, club_id, member_id)
    return_vendor_result(api, order["id"], "RECORD_FOUND")
    order = adjudicate(api, order["id"], "NON_DISQUALIFYING_RECORD")
    return order, read_member(api, member_id)


def disqualify(
    api: ApiClient, club_id: str, member_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Drive a member to the terminal DISQUALIFIED screening state (PRD 3.3)."""
    order = order_screening(api, club_id, member_id)
    return_vendor_result(api, order["id"], "RECORD_FOUND")
    order = adjudicate(api, order["id"], "DISQUALIFYING_RECORD")
    return order, read_member(api, member_id)


# ----------------------------------------------------------------------
# Tier 4: training
# ----------------------------------------------------------------------
def publish_course(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Publish an abuse-prevention course (PRD 3.4)."""
    return get_success_data(
        api.publish_course(f.course_payload(**overrides), NGB_ADMIN_HEADERS), 201
    )


def assign_training(
    api: ApiClient, member_id: str, course_code: str, club_id: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    """Assign a published course to a member with a deadline (PRD 3.4)."""
    headers = make_club_admin_headers(club_id) if club_id else NGB_ADMIN_HEADERS
    return get_success_data(
        api.assign_training(
            f.training_assignment_payload(member_id, course_code, **overrides), headers
        ),
        201,
    )


def start_training(api: ApiClient, assignment_id: str, member_id: str) -> Dict[str, Any]:
    """The member starts their own assignment (PRD 3.4)."""
    return get_success_data(
        api.start_training(assignment_id, make_member_headers(member_id))
    )


def complete_training(
    api: ApiClient, assignment_id: str, member_id: str, score: int = 95
) -> Dict[str, Any]:
    """The member completes their own assignment with a passing score (PRD 3.4)."""
    return get_success_data(
        api.complete_training(
            assignment_id, f.training_completion_payload(score), make_member_headers(member_id)
        )
    )


def make_training_current(
    api: ApiClient,
    member_id: str,
    club_id: str,
    course: Optional[Dict[str, Any]] = None,
    **assignment_overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Give a member a completed required course so training_status is CURRENT.

    Returns the completed assignment and the course it was written against.
    """
    course = course or publish_course(api)
    assignment = assign_training(
        api, member_id, course["code"], club_id, **assignment_overrides
    )
    start_training(api, assignment["id"], member_id)
    assignment = complete_training(api, assignment["id"], member_id)
    return assignment, course


def make_eligible_member(
    api: ApiClient, club_id: str, course: Optional[Dict[str, Any]] = None, **member_overrides: Any
) -> Dict[str, Any]:
    """Register a member and drive them to CLEARED, CURRENT, ACTIVE, ELIGIBLE.

    This is the state PRD 3.4 calls the ``PENDING -> ACTIVE`` bubble-up: screening
    cleared, training current, and no restriction in force.
    """
    member = create_member(api, club_id, **member_overrides)
    clear_screening(api, club_id, member["id"])
    make_training_current(api, member["id"], club_id, course)
    return read_member(api, member["id"])


@pytest.fixture
def course(api: ApiClient) -> Dict[str, Any]:
    """A published course required for every screening tier."""
    return publish_course(api)


@pytest.fixture
def eligible_member(api: ApiClient, club: Dict[str, Any]) -> Dict[str, Any]:
    """A member whose contact_eligibility derives to ELIGIBLE."""
    return make_eligible_member(api, club["id"])


# ----------------------------------------------------------------------
# Tier 4: placements, travel and lodging
# ----------------------------------------------------------------------
def create_placement(
    api: ApiClient, member_id: str, club_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create a PENDING coach placement (PRD 3.6)."""
    return get_success_data(
        api.create_coach_assignment(
            f.coach_assignment_payload(member_id, club_id, **overrides),
            make_club_admin_headers(club_id),
        ),
        201,
    )


def activate_placement(
    api: ApiClient, placement_id: str, club_id: str, member_id: str
) -> Dict[str, Any]:
    """Activate a placement, pinning the member's current version (PRD 3.6)."""
    member = read_member(api, member_id)
    return get_success_data(
        api.activate_coach_assignment(
            placement_id,
            f.activation_payload(member["version"]),
            make_club_admin_headers(club_id),
        )
    )


def make_active_placement(
    api: ApiClient, member_id: str, club_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Create and immediately activate a placement for an eligible member."""
    placement = create_placement(api, member_id, club_id, **overrides)
    return activate_placement(api, placement["id"], club_id, member_id)


def book_adult_stay(
    api: ApiClient, club_id: str, member_id: str, **overrides: Any
) -> Dict[str, Any]:
    """Book a bed for an adult member (PRD 3.7)."""
    return get_success_data(
        api.book_room_stay(
            club_id,
            f.adult_room_stay_payload(member_id, **overrides),
            make_club_admin_headers(club_id),
        ),
        201,
    )


def book_minor_stay(api: ApiClient, club_id: str, **overrides: Any) -> Dict[str, Any]:
    """Book a bed for a minor athlete (PRD 3.7)."""
    return get_success_data(
        api.book_room_stay(
            club_id, f.minor_room_stay_payload(**overrides), make_club_admin_headers(club_id)
        ),
        201,
    )


# ----------------------------------------------------------------------
# Tier 5: cases, investigating bodies and interim measures
# ----------------------------------------------------------------------
def register_body(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Register an independent investigating body (PRD 3.8)."""
    return get_success_data(
        api.register_investigating_body(
            f.investigating_body_payload(**overrides), NGB_ADMIN_HEADERS
        ),
        201,
    )


def file_case(
    api: ApiClient,
    club_id: str,
    member_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """File an incident report under the mandatory-reporting obligation (PRD 3.8)."""
    return get_success_data(
        api.file_case(
            f.case_payload(club_id, member_id, **overrides),
            headers or OFFICER_INTAKE_HEADERS,
        ),
        201,
    )


def route_case(
    api: ApiClient,
    case_id: str,
    body_id: str,
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """Route an intake case to the body with jurisdiction (PRD 3.8)."""
    return get_success_data(
        api.route_case(case_id, f.route_payload(body_id), headers or OFFICER_INTAKE_HEADERS)
    )


def make_routed_case(
    api: ApiClient,
    club_id: str,
    member_id: str,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[Dict[str, Any]] = None,
    **overrides: Any,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """File and route a case in one step; returns the case and its body."""
    body = body or register_body(api)
    case = file_case(api, club_id, member_id, headers, **overrides)
    case = route_case(api, case["id"], body["id"], headers)
    return case, body


def impose_measure(
    api: ApiClient,
    case_id: str,
    member_id: str,
    headers: Optional[Dict[str, str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Impose an interim measure, pinning the member's current version (PRD 3.8)."""
    member = read_member(api, member_id)
    return get_success_data(
        api.impose_interim_measure(
            case_id,
            f.interim_measure_payload(member_id, member["version"], **overrides),
            headers or OFFICER_INTAKE_HEADERS,
        ),
        201,
    )


@pytest.fixture
def investigating_body(api: ApiClient) -> Dict[str, Any]:
    """A body accepting every allegation category with room for five open cases."""
    return register_body(api)


# ----------------------------------------------------------------------
# Tier 5: compliance audits and findings
# ----------------------------------------------------------------------
def open_audit(
    api: ApiClient,
    club_id: str,
    sampled_member_ids: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Open a compliance audit over a club (PRD 3.9)."""
    return get_success_data(
        api.open_club_audit(
            f.club_audit_payload(club_id, sampled_member_ids, **overrides),
            COMPLIANCE_AUDITOR_HEADERS,
        ),
        201,
    )


def write_finding(api: ApiClient, audit_id: str, **overrides: Any) -> Dict[str, Any]:
    """Write a finding against an audit still in SAMPLED (PRD 3.9)."""
    return get_success_data(
        api.write_finding(audit_id, f.finding_payload(**overrides), COMPLIANCE_AUDITOR_HEADERS),
        201,
    )


def finalize_audit(api: ApiClient, audit_id: str) -> Dict[str, Any]:
    """Finalize an audit, computing its compliance score (PRD 3.9)."""
    return get_success_data(
        api.finalize_club_audit(audit_id, {}, COMPLIANCE_AUDITOR_HEADERS)
    )


def decide_finding(
    api: ApiClient,
    finding_id: str,
    decision: str,
    headers: Dict[str, str],
    note: str = "Corrective action attached.",
) -> Dict[str, Any]:
    """Record a decision on a finding (PRD 3.9)."""
    return get_success_data(
        api.decide_finding(
            finding_id, f.finding_decision_payload(decision, note), headers
        )
    )


def close_audit(api: ApiClient, audit_id: str, resolution: str) -> Dict[str, Any]:
    """Close a finalized audit clean or with a sanction (PRD 3.9)."""
    return get_success_data(
        api.close_club_audit(
            audit_id, f.audit_closure_payload(resolution), COMPLIANCE_AUDITOR_HEADERS
        )
    )


def freeze_club_with_critical_finding(
    api: ApiClient, club_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Write one CRITICAL finding so the club's posture derives to FROZEN (PRD 2.9).

    Returns the audit and the re-read club.
    """
    audit = open_audit(api, club_id)
    write_finding(api, audit["id"], severity="CRITICAL")
    return audit, read_club(api, club_id)


def restrict_club_with_three_findings(
    api: ApiClient, club_id: str
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Write three non-critical open findings so the posture derives to RESTRICTED (PRD 2.9)."""
    audit = open_audit(api, club_id)
    for _ in range(3):
        write_finding(api, audit["id"], severity="MINOR")
    return audit, read_club(api, club_id)
