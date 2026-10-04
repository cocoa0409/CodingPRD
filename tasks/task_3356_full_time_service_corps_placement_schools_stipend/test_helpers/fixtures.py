"""Composite fixtures that walk the public API to a wanted state.

Every test starts against an empty deployment (the harness restarts the
server per test), so each test builds the world it needs from scratch through
the API only. These helpers do that walking and return the resource bodies
the test then asserts against.

Organisation, simplest to most far-reaching:

  Tier 1  state progression: clock, site, school chain, recruitment pipeline,
          member activation
  Tier 2  entity hierarchy: teams, assignments, deployment, students
  Tier 3  lifecycle shortcuts: hour logging + verification, payment schedule /
          approve / pay, member exit
  Tier 4  accumulation: verified-hour accumulators for boundary targets
  Tier 5  composite worlds: the deployed-team world most workflows need

Setup calls use the lenient success reader, so a failure inside a fixture is
reported as a setup failure rather than as a confusing assertion error.
"""

from typing import Any, Dict, List, Optional, Sequence, Tuple

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import ApiClient
from .constants import BASE_CLOCK, SERVICE_YEAR_START
from .test_users import (
    PROGRAM_MANAGER_HEADERS,
    SITE_DIRECTOR_HEADERS,
    STIPEND_ADMIN_1_HEADERS,
    STIPEND_ADMIN_2_HEADERS,
    make_applicant_headers,
    make_corps_member_headers,
    make_school_liaison_headers,
)


# ═══ Tier 1: state progression ═════════════════════════════════════════════

def set_clock(api: ApiClient, to_iso8601: str = BASE_CLOCK) -> Dict[str, Any]:
    """Move the logical clock and return what the write reported."""
    return get_success_data(api.set_clock(f.clock_payload(to_iso8601), SITE_DIRECTOR_HEADERS))


def create_site(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    """Create a site (begins in SETUP) and return it."""
    return get_success_data(api.create_site(f.site_payload(**overrides), SITE_DIRECTOR_HEADERS))


def activate_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.transition_site(site_id, {"to_status": "ACTIVE"}, SITE_DIRECTOR_HEADERS))


def create_active_site(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    site = create_site(api, **overrides)
    return activate_site(api, site["id"])


def create_school(api: ApiClient, site_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a school (both dimensions DRAFT) and return it."""
    return get_success_data(api.create_school(f.school_payload(site_id, **overrides), SITE_DIRECTOR_HEADERS))


def sign_data_sharing(api: ApiClient, school_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_school(
            school_id,
            {"to_status": "SIGNED", "dimension": "DATA_SHARING"},
            make_school_liaison_headers(school_id),
        )
    )


def sign_agreement(api: ApiClient, school_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_school(
            school_id,
            {"to_status": "SIGNED", "dimension": "AGREEMENT"},
            make_school_liaison_headers(school_id),
        )
    )


def activate_agreement(api: ApiClient, school_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_school(
            school_id,
            {"to_status": "ACTIVE", "dimension": "AGREEMENT"},
            SITE_DIRECTOR_HEADERS,
        )
    )


def create_active_school(api: ApiClient, site_id: str, **overrides: Any) -> Dict[str, Any]:
    """School carried DRAFT -> (data sharing SIGNED) -> SIGNED -> ACTIVE."""
    school = create_school(api, site_id, **overrides)
    sign_data_sharing(api, school["id"])
    sign_agreement(api, school["id"])
    return activate_agreement(api, school["id"])


def submit_application(api: ApiClient, site_id: str, applicant_id: str = "app-jordan", **overrides: Any) -> Dict[str, Any]:
    """Submit an application (lands SUBMITTED) and return it."""
    return get_success_data(
        api.create_application(
            f.application_payload(site_id, **overrides),
            make_applicant_headers(applicant_id),
        )
    )


def advance_application(api: ApiClient, application_id: str, to_status: str, headers: Dict[str, str], **extra: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(extra)
    return get_success_data(api.transition_application(application_id, payload, headers))


def enroll_member(api: ApiClient, site_id: str, applicant_id: str = "app-jordan", **overrides: Any) -> Dict[str, Any]:
    """Run the full pipeline to ENROLLED and return the new member record.

    Requires the site to be ACTIVE. The member begins with service_status
    ENROLLED, stipend_status NOT_STARTED, award_status NOT_EARNED.
    """
    application = submit_application(api, site_id, applicant_id, **overrides)
    advance_application(api, application["id"], "SCREEN", PROGRAM_MANAGER_HEADERS)
    advance_application(api, application["id"], "INTERVIEWED", PROGRAM_MANAGER_HEADERS)
    advance_application(api, application["id"], "OFFERED", PROGRAM_MANAGER_HEADERS)
    advance_application(api, application["id"], "ACCEPTED", make_applicant_headers(applicant_id))
    enrolled = advance_application(api, application["id"], "ENROLLED", PROGRAM_MANAGER_HEADERS)
    member_id = enrolled["enrolled_member_id"]
    return get_success_data(api.get_member(member_id, PROGRAM_MANAGER_HEADERS))


def transition_member_service(api: ApiClient, member_id: str, to_status: str) -> Dict[str, Any]:
    return get_success_data(
        api.transition_member(member_id, {"to_status": to_status, "dimension": "SERVICE"}, PROGRAM_MANAGER_HEADERS)
    )


def activate_member_service(api: ApiClient, member_id: str) -> Dict[str, Any]:
    """ENROLLED -> ACTIVE; cascades stipend_status NOT_STARTED -> ACTIVE."""
    return transition_member_service(api, member_id, "ACTIVE")


def suspend_member_service(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return transition_member_service(api, member_id, "SUSPENDED")


def create_active_member(api: ApiClient, site_id: str, applicant_id: str = "app-jordan", **overrides: Any) -> Dict[str, Any]:
    """Enroll a member and activate service (stipend dimension follows)."""
    member = enroll_member(api, site_id, applicant_id, **overrides)
    return activate_member_service(api, member["id"])


# ═══ Tier 2: entity hierarchy ══════════════════════════════════════════════

def create_team(api: ApiClient, school_id: str, **overrides: Any) -> Dict[str, Any]:
    """Create a team (FORMING; freezes the school's team size)."""
    return get_success_data(api.create_team(f.team_payload(school_id, **overrides), SITE_DIRECTOR_HEADERS))


def get_team(api: ApiClient, team_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_team(team_id, PROGRAM_MANAGER_HEADERS))


def assign_member(
    api: ApiClient,
    team_id: str,
    member_id: str,
    start_date: str = SERVICE_YEAR_START,
    **overrides: Any,
) -> Dict[str, Any]:
    """Create an ACTIVE assignment, reading the team's version fresh for OCC."""
    team = get_team(api, team_id)
    return get_success_data(
        api.create_assignment(
            team_id,
            f.assignment_payload(member_id, team["version"], start_date=start_date, **overrides),
            PROGRAM_MANAGER_HEADERS,
        )
    )


def deploy_team(api: ApiClient, team_id: str) -> Dict[str, Any]:
    return get_success_data(api.transition_team(team_id, {"to_status": "DEPLOYED"}, SITE_DIRECTOR_HEADERS))


def end_assignment(api: ApiClient, assignment_id: str, end_date: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if end_date is not None:
        payload["end_date"] = end_date
    return get_success_data(api.end_assignment(assignment_id, payload, PROGRAM_MANAGER_HEADERS))


def create_student(api: ApiClient, school_id: str, external_student_ref: str = "S01", **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_student(f.student_payload(school_id, external_student_ref, **overrides), PROGRAM_MANAGER_HEADERS)
    )


def assign_caseload(api: ApiClient, student_id: str, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.caseload_student(student_id, {"action": "ASSIGN", "corps_member_id": member_id}, PROGRAM_MANAGER_HEADERS)
    )


def unassign_caseload(api: ApiClient, student_id: str) -> Dict[str, Any]:
    return get_success_data(api.caseload_student(student_id, {"action": "UNASSIGN"}, PROGRAM_MANAGER_HEADERS))


def post_metrics(api: ApiClient, student_id: str, current_attendance_pct: float) -> Dict[str, Any]:
    return get_success_data(
        api.post_student_metrics(student_id, {"current_attendance_pct": current_attendance_pct}, PROGRAM_MANAGER_HEADERS)
    )


# ═══ Tier 3: lifecycle shortcuts ═══════════════════════════════════════════

def log_pending_entry(
    api: ApiClient,
    member_id: str,
    service_date: str,
    hours: float,
    category: str = "DIRECT_SERVICE",
    **overrides: Any,
) -> Dict[str, Any]:
    """Log an hour entry (lands PENDING) as the member themself."""
    return get_success_data(
        api.create_hour_entry(
            f.hour_entry_payload(member_id, service_date, hours, category=category, **overrides),
            make_corps_member_headers(member_id),
        )
    )


def review_entry(api: ApiClient, entry_id: str, decision: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return get_success_data(api.review_hour_entry(entry_id, payload, PROGRAM_MANAGER_HEADERS))


def log_verified_hours(
    api: ApiClient,
    member_id: str,
    specs: Sequence[Tuple[str, float, str]],
    verify_clock: str,
) -> List[Dict[str, Any]]:
    """Log and verify a batch of hour entries.

    ``specs`` is a list of ``(service_date, hours, category)`` triples. The
    clock is set once to ``verify_clock`` first, so every service date must be
    on or before it and inside the 30-day verification window at review time.
    Returns the verified entry bodies.
    """
    set_clock(api, verify_clock)
    verified: List[Dict[str, Any]] = []
    for service_date, hours, category in specs:
        entry = log_pending_entry(api, member_id, service_date, hours, category)
        verified.append(review_entry(api, entry["id"], "VERIFY"))
    return verified


def schedule_payment(
    api: ApiClient,
    member_id: str,
    period_start: str = "2026-09-01",
    period_end: str = "2026-09-14",
    creator_headers: Dict[str, str] = STIPEND_ADMIN_1_HEADERS,
) -> Dict[str, Any]:
    """Schedule a stipend payment (SCHEDULED; provisional base computed)."""
    return get_success_data(
        api.create_stipend_payment(member_id, f.stipend_payment_payload(period_start, period_end), creator_headers)
    )


def approve_payment(
    api: ApiClient,
    payment_id: str,
    approver_headers: Dict[str, str] = STIPEND_ADMIN_2_HEADERS,
    deduction_cents: int = 0,
) -> Dict[str, Any]:
    """Approve a SCHEDULED payment (computes the final variant)."""
    return get_success_data(
        api.transition_stipend_payment(
            payment_id, {"to_status": "APPROVED", "deduction_cents": deduction_cents}, approver_headers
        )
    )


def pay_payment(api: ApiClient, payment_id: str, headers: Dict[str, str] = STIPEND_ADMIN_2_HEADERS) -> Dict[str, Any]:
    return get_success_data(api.transition_stipend_payment(payment_id, {"to_status": "PAID"}, headers))


def get_member(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_member(member_id, PROGRAM_MANAGER_HEADERS))


def get_site(api: ApiClient, site_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_site(site_id, SITE_DIRECTOR_HEADERS))


def exit_member(api: ApiClient, member_id: str, exit_type: str, exit_date: Optional[str] = None) -> Dict[str, Any]:
    """Exit a member, reading the version fresh first so OCC always passes."""
    member = get_member(api, member_id)
    payload: Dict[str, Any] = {"expected_member_version": member["version"], "exit_type": exit_type}
    if exit_date is not None:
        payload["exit_date"] = exit_date
    return get_success_data(api.exit_member(member_id, payload, PROGRAM_MANAGER_HEADERS))


def create_evaluation_report(api: ApiClient, school_id: str, **overrides: Any) -> Dict[str, Any]:
    """Draft an evaluation report; metrics snapshot at creation."""
    return get_success_data(
        api.create_evaluation_report(f.evaluation_report_payload(school_id, **overrides), PROGRAM_MANAGER_HEADERS)
    )


# ═══ Tier 4: accumulation / threshold targeting ════════════════════════════

def accumulate_verified_hours(
    api: ApiClient,
    member_id: str,
    days: Sequence[str],
    hours_per_day: float = 12.0,
    category: str = "DIRECT_SERVICE",
    verify_clock: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Verify ``hours_per_day`` on each date in ``days``.

    ``verify_clock`` defaults to the day after the last service date, keeping
    every entry inside the 30-day verification window.
    """
    specs = [(d, hours_per_day, category) for d in days]
    clock = verify_clock or _day_after(days[-1])
    return log_verified_hours(api, member_id, specs, clock)


def _day_after(iso_date: str) -> str:
    """Next calendar date as an ISO instant at midnight UTC."""
    import datetime as _dt

    day = _dt.date.fromisoformat(iso_date) + _dt.timedelta(days=1)
    return f"{day.isoformat()}T00:00:00Z"


def clock_instant(iso_date: str) -> str:
    """Midnight UTC instant for a calendar date."""
    return f"{iso_date}T00:00:00Z"


# ═══ Tier 5: composite worlds ══════════════════════════════════════════════

def setup_deployed_world(
    api: ApiClient,
    applicant_id: str = "app-jordan",
    member_name: str = "Jordan Rivers",
    team_overrides: Optional[Dict[str, Any]] = None,
    school_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """The canonical full world: site ACTIVE, school ACTIVE, one team
    DEPLOYED with the member's ACTIVE assignment.

    Returns {"site", "school", "team", "member", "assignment"}.
    """
    site = create_active_site(api)
    school = create_active_school(api, site["id"], **(school_overrides or {}))
    team = create_team(api, school["id"], **(team_overrides or {}))
    member = create_active_member(api, site["id"], applicant_id, full_name=member_name)
    assignment = assign_member(api, team["id"], member["id"])
    team = deploy_team(api, team["id"])
    return {"site": site, "school": school, "team": team, "member": member, "assignment": assignment}


def add_active_member(api: ApiClient, site_id: str, applicant_id: str, full_name: str, **overrides: Any) -> Dict[str, Any]:
    """A second (or later) ACTIVE member on an existing ACTIVE site."""
    return create_active_member(api, site_id, applicant_id, full_name=full_name, **overrides)
