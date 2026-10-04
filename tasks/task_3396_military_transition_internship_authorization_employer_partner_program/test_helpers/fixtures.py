"""Composite setup helpers.

The harness restarts the API server before every test, so each fixture builds
its preconditions from scratch through the public API. Setup calls use the
lenient ``get_success_data`` validator so a broken precondition surfaces as a
clear "Setup step failed" error at the exact call that failed.

The workhorse is ``setup_match``: it builds the standard pipeline
(installation -> member -> approved application -> authorized employer ->
opening -> match) and then walks the match to the requested stage.
"""

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Sequence

from prd_bench_local_runner.testing import get_success_data

from . import factories
from .api_client import ApiClient
from .test_users import (
    PROGRAM_OFFICE_HEADERS,
    TRANSITION_COUNSELOR_HEADERS,
    make_employer_rep_headers,
    make_installation_authority_headers,
    make_service_member_headers,
    make_unit_commander_headers,
)

DEFAULT_SEPARATION = factories.DEFAULT_SEPARATION_DATE
DEFAULT_START = factories.DEFAULT_MATCH_START
DEFAULT_END = factories.DEFAULT_MATCH_END


# ── Primitive steps ──────────────────────────────────────────────────────────


def set_clock(api: ApiClient, to_iso8601: str) -> Dict[str, Any]:
    """Move the logical clock; returns the sweep counters payload."""
    return get_success_data(api.set_clock(factories.clock_payload(to_iso8601), PROGRAM_OFFICE_HEADERS))


def create_installation(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_installation(factories.create_installation_payload(**overrides), PROGRAM_OFFICE_HEADERS),
        201,
    )


def create_member(api: ApiClient, installation_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_service_member(
            factories.create_service_member_payload(home_installation_id=installation_id, **overrides),
            TRANSITION_COUNSELOR_HEADERS,
        ),
        201,
    )


def get_member(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_service_member(member_id, PROGRAM_OFFICE_HEADERS))


def patch_member(api: ApiClient, member_id: str, **fields: Any) -> Dict[str, Any]:
    """PATCH a member under OCC, reading the current version first."""
    current = get_member(api, member_id)
    payload = {"expected_service_member_version": current["version"]}
    payload.update(fields)
    return get_success_data(api.patch_service_member(member_id, payload, TRANSITION_COUNSELOR_HEADERS))


def tap_advance(api: ApiClient, member_id: str, target_stage: str) -> Dict[str, Any]:
    return get_success_data(
        api.tap_advance(member_id, {"target_stage": target_stage}, TRANSITION_COUNSELOR_HEADERS)
    )


def create_employer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_employer(factories.create_employer_payload(**overrides), PROGRAM_OFFICE_HEADERS),
        201,
    )


def get_employer(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_employer(employer_id, PROGRAM_OFFICE_HEADERS))


def authorize_employer(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return get_success_data(api.authorize_employer(employer_id, PROGRAM_OFFICE_HEADERS))


def create_authorized_employer(api: ApiClient, **overrides: Any) -> Dict[str, Any]:
    employer = create_employer(api, **overrides)
    return authorize_employer(api, employer["id"])


def review_employer(api: ApiClient, employer_id: str, outcome: str, notes: Optional[str] = None) -> Dict[str, Any]:
    return get_success_data(
        api.periodic_review(employer_id, factories.periodic_review_payload(outcome, notes), PROGRAM_OFFICE_HEADERS)
    )


def create_opening(api: ApiClient, employer_id: str, **overrides: Any) -> Dict[str, Any]:
    return get_success_data(
        api.create_opening(
            factories.create_opening_payload(employer_id, **overrides),
            make_employer_rep_headers(employer_id),
        ),
        201,
    )


def get_opening(api: ApiClient, opening_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_opening(opening_id, PROGRAM_OFFICE_HEADERS))


def submit_application(api: ApiClient, member_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_application(
            factories.create_application_payload(member_id),
            make_service_member_headers(member_id),
        ),
        201,
    )


def get_application(api: ApiClient, application_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_application(application_id, PROGRAM_OFFICE_HEADERS))


def commander_decision(
    api: ApiClient, application_id: str, decision: str, commander_id: str = "cmd-1", reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.commander_decision(
            application_id,
            factories.commander_decision_payload(decision, reason),
            make_unit_commander_headers(commander_id),
        )
    )


def approve_application(api: ApiClient, application_id: str, commander_id: str = "cmd-1") -> Dict[str, Any]:
    return commander_decision(api, application_id, "APPROVE", commander_id=commander_id)


def deny_application(
    api: ApiClient, application_id: str, reason: str = "Manning requirements", commander_id: str = "cmd-1"
) -> Dict[str, Any]:
    return commander_decision(api, application_id, "DENY", commander_id=commander_id, reason=reason)


def appeal_application(
    api: ApiClient, application_id: str, member_id: str, appeal_reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.appeal_application(
            application_id,
            factories.appeal_payload(appeal_reason),
            make_service_member_headers(member_id),
        )
    )


def adjudicate_appeal(
    api: ApiClient, application_id: str, outcome: str, authority_id: str = "auth-1", reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.adjudicate_appeal(
            application_id,
            factories.adjudicate_payload(outcome, reason),
            make_installation_authority_headers(authority_id),
        )
    )


def propose_match(
    api: ApiClient,
    application_id: str,
    opening_id: str,
    start_date: str = DEFAULT_START,
    end_date: str = DEFAULT_END,
    employer_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Propose a match, re-reading the opening so the OCC version is fresh."""
    opening = get_opening(api, opening_id)
    owner = employer_id or opening["employer_id"]
    payload = factories.create_match_payload(
        application_id, opening_id, opening["version"], start_date, end_date
    )
    return get_success_data(api.create_match(payload, make_employer_rep_headers(owner)), 201)


def get_match(api: ApiClient, match_id: str) -> Dict[str, Any]:
    return get_success_data(api.get_match(match_id, PROGRAM_OFFICE_HEADERS))


def submit_plan(
    api: ApiClient,
    match_id: str,
    employer_id: str,
    objectives: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return get_success_data(
        api.submit_plan(
            match_id,
            factories.submit_plan_payload(objectives, **overrides),
            make_employer_rep_headers(employer_id),
        )
    )


def review_plan(
    api: ApiClient, match_id: str, outcome: str, authority_id: str = "auth-1", feedback: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.review_plan(
            match_id,
            factories.review_plan_payload(outcome, feedback),
            make_installation_authority_headers(authority_id),
        )
    )


def installation_decision(
    api: ApiClient, match_id: str, decision: str, authority_id: str = "auth-1", reason: Optional[str] = None
) -> Dict[str, Any]:
    return get_success_data(
        api.installation_decision(
            match_id,
            factories.installation_decision_payload(decision, reason),
            make_installation_authority_headers(authority_id),
        )
    )


def terminate_match(
    api: ApiClient,
    match_id: str,
    reason: str = "VOLUNTARY",
    as_employer_id: Optional[str] = None,
    authority_id: str = "auth-1",
) -> Dict[str, Any]:
    headers = (
        make_employer_rep_headers(as_employer_id)
        if as_employer_id is not None
        else make_installation_authority_headers(authority_id)
    )
    return get_success_data(api.terminate_match(match_id, factories.terminate_payload(reason), headers))


def complete_match(api: ApiClient, match_id: str, authority_id: str = "auth-1") -> Dict[str, Any]:
    return get_success_data(api.complete_match(match_id, make_installation_authority_headers(authority_id)))


def file_report(
    api: ApiClient,
    match_id: str,
    employer_id: str,
    week_start_date: str,
    achieved: Optional[Sequence[str]] = None,
    excused: Optional[Sequence[str]] = None,
    hours_supervised: int = 8,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_supervision_report(
            factories.supervision_report_payload(
                match_id,
                week_start_date,
                objectives_achieved=list(achieved) if achieved else None,
                objectives_excused=list(excused) if excused else None,
                hours_supervised=hours_supervised,
            ),
            make_employer_rep_headers(employer_id),
        ),
        201,
    )


def file_weekly_reports(
    api: ApiClient,
    match_id: str,
    employer_id: str,
    first_week_start: str,
    count: int = 4,
    marks: Optional[Dict[int, Dict[str, Sequence[str]]]] = None,
) -> List[Dict[str, Any]]:
    """File ``count`` weekly reports at 7-day spacing from ``first_week_start``.

    ``marks`` maps a week index to {"achieved": [...], "excused": [...]}.
    """
    anchor = date.fromisoformat(first_week_start)
    filed = []
    for i in range(count):
        mark = (marks or {}).get(i, {})
        filed.append(
            file_report(
                api,
                match_id,
                employer_id,
                (anchor + timedelta(days=7 * i)).isoformat(),
                achieved=mark.get("achieved"),
                excused=mark.get("excused"),
            )
        )
    return filed


def post_wage_record(
    api: ApiClient,
    match_id: str,
    employer_id: str,
    period_start_date: str,
    period_end_date: str,
    amount_cents: int,
    memo: Optional[str] = None,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_wage_record(
            factories.wage_record_payload(match_id, period_start_date, period_end_date, amount_cents, memo=memo),
            make_employer_rep_headers(employer_id),
        ),
        201,
    )


def open_audit(api: ApiClient, employer_id: str) -> Dict[str, Any]:
    return get_success_data(
        api.create_audit(factories.create_audit_payload(employer_id), PROGRAM_OFFICE_HEADERS),
        201,
    )


def close_audit(api: ApiClient, audit_id: str, findings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    return get_success_data(
        api.close_audit(audit_id, factories.close_audit_payload(findings), PROGRAM_OFFICE_HEADERS)
    )


def record_conversion(
    api: ApiClient,
    match_id: str,
    employer_id: str,
    conversion_date: str,
    offer_made: bool,
    offer_accepted: bool,
) -> Dict[str, Any]:
    return get_success_data(
        api.create_conversion_record(
            factories.conversion_record_payload(match_id, conversion_date, offer_made, offer_accepted),
            make_employer_rep_headers(employer_id),
        ),
        201,
    )


# ── Composite pipelines ──────────────────────────────────────────────────────


def setup_employer_with_opening(
    api: ApiClient,
    capacity: int = 1,
    opening_overrides: Optional[Dict[str, Any]] = None,
    employer_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    employer = create_authorized_employer(api, **(employer_overrides or {}))
    opening = create_opening(api, employer["id"], capacity=capacity, **(opening_overrides or {}))
    return SimpleNamespace(employer=employer, opening=opening)


def setup_member_with_application(
    api: ApiClient,
    installation_id: Optional[str] = None,
    approve: bool = True,
    member_overrides: Optional[Dict[str, Any]] = None,
    installation_overrides: Optional[Dict[str, Any]] = None,
    commander_id: str = "cmd-1",
) -> SimpleNamespace:
    installation = (
        create_installation(api, **(installation_overrides or {})) if installation_id is None else None
    )
    iid = installation["id"] if installation is not None else installation_id
    member = create_member(api, iid, **(member_overrides or {}))
    application = submit_application(api, member["id"])
    if approve:
        application = approve_application(api, application["id"], commander_id=commander_id)
    return SimpleNamespace(installation=installation, member=member, application=application)


def setup_members_with_approved_applications(
    api: ApiClient,
    count: int,
    separation_date: str = DEFAULT_SEPARATION,
    skills: Sequence[str] = ("LOGISTICS",),
    names: Optional[Sequence[str]] = None,
    installation_overrides: Optional[Dict[str, Any]] = None,
) -> SimpleNamespace:
    installation = create_installation(api, **(installation_overrides or {}))
    default_names = ["Alice Vega", "Ben Cole", "Cara Diaz", "Dan Ely", "Eve Fox", "Gus Hale"]
    members = []
    applications = []
    for i in range(count):
        member = create_member(
            api,
            installation["id"],
            full_name=(names[i] if names else default_names[i]),
            separation_date=separation_date,
            skills=list(skills),
        )
        application = approve_application(api, submit_application(api, member["id"])["id"])
        members.append(member)
        applications.append(application)
    return SimpleNamespace(installation=installation, members=members, applications=applications)


def setup_match(
    api: ApiClient,
    advance_to: str = "proposed",
    member_overrides: Optional[Dict[str, Any]] = None,
    installation_overrides: Optional[Dict[str, Any]] = None,
    employer_overrides: Optional[Dict[str, Any]] = None,
    opening_overrides: Optional[Dict[str, Any]] = None,
    start_date: str = DEFAULT_START,
    end_date: str = DEFAULT_END,
    objectives: Optional[List[Dict[str, Any]]] = None,
    authority_id: str = "auth-1",
) -> SimpleNamespace:
    """Standard pipeline with the match walked to ``advance_to``:
    proposed -> plan_submitted -> plan_approved -> installation_approved -> active.
    Returned entities are re-read fresh at the end."""
    w = setup_member_with_application(
        api, member_overrides=member_overrides, installation_overrides=installation_overrides
    )
    eo = setup_employer_with_opening(
        api, opening_overrides=opening_overrides, employer_overrides=employer_overrides
    )
    match = propose_match(api, w.application["id"], eo.opening["id"], start_date, end_date)
    stages = ["proposed", "plan_submitted", "plan_approved", "installation_approved", "active"]
    target = stages.index(advance_to)
    if target >= 1:
        match = submit_plan(api, match["id"], eo.employer["id"], objectives)
    if target >= 2:
        match = review_plan(api, match["id"], "APPROVE", authority_id=authority_id)
    if target >= 3:
        match = installation_decision(api, match["id"], "APPROVE", authority_id=authority_id)
    if target >= 4:
        set_clock(api, f"{start_date}T00:00:00Z")
    return SimpleNamespace(
        installation=w.installation,
        member=get_member(api, w.member["id"]),
        application=get_application(api, w.application["id"]),
        employer=get_employer(api, eo.employer["id"]),
        opening=get_opening(api, eo.opening["id"]),
        match=get_match(api, match["id"]),
    )


def setup_ready_to_complete(
    api: ApiClient,
    start_date: str = DEFAULT_START,
    end_date: str = DEFAULT_END,
    objectives: Optional[List[Dict[str, Any]]] = None,
    report_count: int = 4,
    marks: Optional[Dict[int, Dict[str, Sequence[str]]]] = None,
    clock_to: Optional[str] = None,
    **setup_kwargs: Any,
) -> SimpleNamespace:
    """An ACTIVE match with ``report_count`` weekly reports filed and the clock
    moved to ``clock_to`` (defaults to the match end date). The match is ready
    for a completion attempt."""
    ns = setup_match(
        api,
        advance_to="active",
        start_date=start_date,
        end_date=end_date,
        objectives=objectives,
        **setup_kwargs,
    )
    if report_count:
        file_weekly_reports(
            api, ns.match["id"], ns.employer["id"], start_date, count=report_count, marks=marks
        )
    set_clock(api, clock_to or f"{end_date}T00:00:00Z")
    ns.match = get_match(api, ns.match["id"])
    ns.member = get_member(api, ns.member["id"])
    ns.opening = get_opening(api, ns.opening["id"])
    return ns


def setup_completed_match(
    api: ApiClient,
    objectives: Optional[List[Dict[str, Any]]] = None,
    marks: Optional[Dict[int, Dict[str, Sequence[str]]]] = None,
    authority_id: str = "auth-1",
    **setup_kwargs: Any,
) -> SimpleNamespace:
    """A match carried all the way to COMPLETED on the default 30-day window
    (one 10-hour objective achieved in week 1, four weekly reports)."""
    ns = setup_ready_to_complete(api, objectives=objectives, marks=marks or {0: {"achieved": ["O1"]}}, **setup_kwargs)
    ns.match = complete_match(api, ns.match["id"], authority_id=authority_id)
    ns.member = get_member(api, ns.member["id"])
    ns.opening = get_opening(api, ns.opening["id"])
    return ns
