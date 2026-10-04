"""Named composite worlds - multi-entity setups shared by several tests.

Each builds on the primitives in ``fixtures.py`` and returns a namespace of
freshly re-read entities.
"""

from types import SimpleNamespace
from typing import Any, Dict

from . import fixtures
from .api_client import ApiClient


def _two_match_world(api: ApiClient, activate_second_only: bool) -> SimpleNamespace:
    """Employer with a capacity-2 opening and two members' matches on it.

    mt1 stays PROPOSED (no plan is ever submitted for it). mt2 carries an
    approved plan and an installation approval. With activate_second_only the
    clock lands on the common start date so mt2 turns ACTIVE while mt1 stays
    PROPOSED; otherwise both matches are fully approved and both activate.
    """
    w = fixtures.setup_members_with_approved_applications(api, 2)
    eo = fixtures.setup_employer_with_opening(api, capacity=2)
    employer, opening = eo.employer, eo.opening

    mt1 = fixtures.propose_match(api, w.applications[0]["id"], opening["id"])
    mt2 = fixtures.propose_match(api, w.applications[1]["id"], opening["id"])
    fixtures.submit_plan(api, mt2["id"], employer["id"])
    fixtures.review_plan(api, mt2["id"], "APPROVE")
    fixtures.installation_decision(api, mt2["id"], "APPROVE")

    if not activate_second_only:
        fixtures.submit_plan(api, mt1["id"], employer["id"])
        fixtures.review_plan(api, mt1["id"], "APPROVE")
        fixtures.installation_decision(api, mt1["id"], "APPROVE")

    sweep = fixtures.set_clock(api, "2026-10-01T00:00:00Z")
    return SimpleNamespace(
        installation=w.installation,
        members=[fixtures.get_member(api, m["id"]) for m in w.members],
        applications=w.applications,
        employer=fixtures.get_employer(api, employer["id"]),
        opening=fixtures.get_opening(api, opening["id"]),
        match1=fixtures.get_match(api, mt1["id"]),
        match2=fixtures.get_match(api, mt2["id"]),
        sweep=sweep,
    )


def setup_cascade_world(api: ApiClient) -> SimpleNamespace:
    """One PROPOSED match (mt1) and one ACTIVE match (mt2) on the same opening,
    plus an OPEN compliance audit on the employer - the audit-sanction cascade
    stage. Clock sits at 2026-10-01."""
    ns = _two_match_world(api, activate_second_only=True)
    ns.audit = fixtures.open_audit(api, ns.employer["id"])
    return ns


def setup_two_active_matches(api: ApiClient) -> SimpleNamespace:
    """Two ACTIVE matches on the same capacity-2 opening (clock 2026-10-01) -
    the wage-violation cascade stage."""
    return _two_match_world(api, activate_second_only=False)


def setup_hiring_rate_world(api: ApiClient) -> SimpleNamespace:
    """Two COMPLETED matches on one opening (members separating 2027-01-15 and
    2027-01-20), one hired conversion on the first, clock parked at 2027-03-10.

    mtA [2026-10-01, 2026-10-31) completed 2026-10-31; mtB [2026-11-15,
    2026-12-15) completed 2026-12-15.
    """
    installation = fixtures.create_installation(api)
    member_a = fixtures.create_member(
        api, installation["id"], full_name="Alice Vega", separation_date="2027-01-15",
        skills=["LOGISTICS", "DRIVING"],
    )
    member_b = fixtures.create_member(
        api, installation["id"], full_name="Ben Cole", service_branch="NAVY",
        pay_grade="E6", separation_date="2027-01-20", skills=["LOGISTICS"],
    )
    app_a = fixtures.approve_application(api, fixtures.submit_application(api, member_a["id"])["id"])
    app_b = fixtures.approve_application(api, fixtures.submit_application(api, member_b["id"])["id"])
    employer = fixtures.create_authorized_employer(api)
    opening = fixtures.create_opening(api, employer["id"], capacity=2)

    def run_match(app_id: str, start: str, end: str, first_week: str) -> Dict[str, Any]:
        match = fixtures.propose_match(api, app_id, opening["id"], start, end)
        fixtures.submit_plan(api, match["id"], employer["id"])
        fixtures.review_plan(api, match["id"], "APPROVE")
        fixtures.installation_decision(api, match["id"], "APPROVE")
        fixtures.set_clock(api, f"{start}T00:00:00Z")
        fixtures.file_weekly_reports(
            api, match["id"], employer["id"], first_week, count=4, marks={0: {"achieved": ["O1"]}}
        )
        fixtures.set_clock(api, f"{end}T00:00:00Z")
        return fixtures.complete_match(api, match["id"])

    match_a = run_match(app_a["id"], "2026-10-01", "2026-10-31", "2026-10-01")
    match_b = run_match(app_b["id"], "2026-11-15", "2026-12-15", "2026-11-15")

    fixtures.set_clock(api, "2027-03-10T00:00:00Z")
    conversion = fixtures.record_conversion(
        api, match_a["id"], employer["id"], "2027-02-01", offer_made=True, offer_accepted=True
    )
    return SimpleNamespace(
        installation=installation,
        member_a=fixtures.get_member(api, member_a["id"]),
        member_b=fixtures.get_member(api, member_b["id"]),
        application_a=app_a,
        application_b=app_b,
        employer=fixtures.get_employer(api, employer["id"]),
        opening=fixtures.get_opening(api, opening["id"]),
        match_a=fixtures.get_match(api, match_a["id"]),
        match_b=fixtures.get_match(api, match_b["id"]),
        conversion=conversion,
    )
