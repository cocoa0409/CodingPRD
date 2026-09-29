"""State machines that are not a single line.

A member carries two lifecycle dimensions on one row, and an intake case forks
into two closure branches whose side effects share nothing.  These tests observe
the intermediate combined states that a linear implementation cannot produce.
"""

from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_counters, assert_state
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_CLOSER_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    SCREENING_VENDOR_HEADERS,
    make_club_admin_headers,
)

ALPHA_AQUATICS = {
    "name": "Alpha Aquatics",
    "state_code": "CA",
    "roster_size_attested": 3,
    "minor_athlete_program": True,
    "initial_escrow_cents": 500000,
}
SS101 = {
    "code": "SS101",
    "title": "Abuse Prevention Core",
    "validity_days": 365,
    "delivery_mode": "ONLINE",
    "required_for_tiers": ["TIER_1", "TIER_2", "TIER_3"],
    "pass_score": 80,
}


def _club_with_course(api: ApiClient) -> Dict[str, Any]:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    return club


def _register(api: ApiClient, club_id: str, full_name: str, email: str, dob: str) -> Dict[str, Any]:
    return get_success_data(
        api.register_member(
            {
                "club_id": club_id,
                "full_name": full_name,
                "email": email,
                "role_type": "VOLUNTEER",
                "has_minor_athlete_contact": False,
                "date_of_birth": dob,
                "jurisdiction_codes": ["CA"],
            },
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _clear(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    club = get_success_data(api.get_club(club_id, NGB_ADMIN_HEADERS))
    order = get_success_data(
        api.order_screening(
            member_id,
            {"expedited": False, "expected_club_version": club["version"]},
            make_club_admin_headers(club_id),
        ),
        201,
    )
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order["id"],
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )
    return order


def _complete_course(api: ApiClient, club_id: str, member_id: str, score: int) -> Dict[str, Any]:
    admin = make_club_admin_headers(club_id)
    assignment = get_success_data(
        api.assign_training(
            {"member_id": member_id, "course_code": "SS101", "due_at": "2026-09-01T00:00:00Z"},
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], admin))
    return get_success_data(api.complete_training(assignment["id"], {"score": score}, admin))


def test_screening_dimension_clears_while_the_membership_dimension_stays_pending(
    api: ApiClient,
) -> None:
    """The combined state (CLEARED, PENDING) is reachable and observable.

    PRD 3.1 says:
    "These two status dimensions live on the same member row and advance on entirely different triggers; neither is a function of the other."
    With training never completed the bubble-up cannot fire, and PRD 3.4 leaves the
    member restricted because
    "Otherwise the value is `RESTRICTED` when any interim measure against the member stands in status `ACTIVE`, or when the screening dimension is `UNSCREENED`, `SCREENING_ORDERED`, `FLAGGED`, or `EXPIRED`, or when `training_status` is `NEVER` or `LAPSED`."

    Design: Difficulty/non_linear_state_machine/member_screening_and_membership_dimensions_advance_independently
    """
    club = _club_with_course(api)
    member = _register(api, club["id"], "Remy Sato", "remy.sato@alpha.test", "1994-09-09")

    assert_state(member, "screening_status", "UNSCREENED")
    assert_state(member, "membership_status", "PENDING")

    club_now = get_success_data(api.get_club(club["id"], NGB_ADMIN_HEADERS))
    get_success_data(
        api.order_screening(
            member["id"],
            {"expedited": False, "expected_club_version": club_now["version"]},
            make_club_admin_headers(club["id"]),
        ),
        201,
    )
    ordered = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_state(ordered, "screening_status", "SCREENING_ORDERED")
    assert_state(ordered, "membership_status", "PENDING")

    order_id = validate_success(
        api.list_member_screening_orders(member["id"], NGB_ADMIN_HEADERS)
    )[0]["id"]
    get_success_data(
        api.post_screening_result(
            order_id, {"vendor_disposition": "NO_RECORD"}, SCREENING_VENDOR_HEADERS
        )
    )
    get_success_data(
        api.adjudicate_screening_order(
            order_id,
            {"disposition": "CLEAR", "rationale": "registry return carried no records"},
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )

    cleared = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_state(cleared, "screening_status", "CLEARED")
    assert_state(cleared, "membership_status", "PENDING")
    assert_state(cleared, "training_status", "NEVER")
    assert_state(cleared, "contact_eligibility", "RESTRICTED")


def test_training_completion_bubbles_membership_to_active_leaving_screening_cleared(
    api: ApiClient,
) -> None:
    """Completing the required course advances membership only, not screening.

    PRD 3.4 says:
    "The membership dimension advances `PENDING → ACTIVE` by itself, with no caller asking for it, and it does so on exactly two occasions: inside a screening adjudication and inside a training completion."
    and lists the four conditions:
    "All four of the following must hold at that moment — the member's `membership_status` is still `PENDING`, the `screening_status` is `CLEARED`, the `training_status` is `CURRENT`, and no interim measure against that member stands in status `ACTIVE` or `PERMANENT`."

    Design: Difficulty/non_linear_state_machine/member_screening_and_membership_dimensions_advance_independently
    """
    club = _club_with_course(api)
    member = _register(api, club["id"], "Remy Sato", "remy.sato@alpha.test", "1994-09-09")
    _clear(api, club["id"], member["id"])
    _complete_course(api, club["id"], member["id"], 88)

    final = validate_success(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    assert_state(final, "screening_status", "CLEARED")
    assert_state(final, "membership_status", "ACTIVE")
    assert_state(final, "training_status", "CURRENT")
    assert_state(final, "contact_eligibility", "ELIGIBLE")
    assert final["eligible_through"] == "2027-08-01T00:00:00.000Z"


def _two_cases_on_one_suspended_coach(api: ApiClient) -> Dict[str, Any]:
    """A ROUTED case with an ACTIVE suspension plus a second case still in intake."""
    club = _club_with_course(api)
    admin = make_club_admin_headers(club["id"])
    member = _register(api, club["id"], "Ira Blaine", "ira.blaine@alpha.test", "1989-01-15")
    _clear(api, club["id"], member["id"])
    _complete_course(api, club["id"], member["id"], 91)

    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": "Junior Squad",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-06-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    current = get_success_data(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    get_success_data(
        api.activate_coach_assignment(
            placement["id"], {"expected_member_version": current["version"]}, admin
        )
    )

    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Center for SafeSport",
                "scope_categories": ["PHYSICAL_ABUSE", "POLICY_VIOLATION"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    routed = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "PHYSICAL_ABUSE",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "poolside physical contact reported by a parent",
                "occurred_at": "2026-07-31T18:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    get_success_data(
        api.route_case(
            routed["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS
        )
    )
    pinned = get_success_data(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    measure = get_success_data(
        api.impose_interim_measure(
            routed["id"],
            {
                "member_id": member["id"],
                "measure_kind": "TEMPORARY_SUSPENSION",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-05T00:00:00Z",
                "expected_member_version": pinned["version"],
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )
    intake = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": member["id"],
                "allegation_category": "POLICY_VIOLATION",
                "reporter_kind": "PARENT",
                "narrative": "same incident re-reported by a second parent",
                "occurred_at": "2026-07-31T18:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    return {
        "club": club,
        "member": member,
        "placement": placement,
        "body": body,
        "routed_case": routed,
        "intake_case": intake,
        "measure": measure,
    }


def test_administrative_closure_from_intake_review_leaves_every_other_row_alone(
    api: ApiClient,
) -> None:
    """Closing the duplicate report moves no counter and lifts no restriction.

    PRD 3.8 says:
    "An officer closes an unrouted case with a `closure_reason` of either `NO_JURISDICTION` or `DUPLICATE_REPORT` and no `outcome` at all; the case moves `INTAKE_REVIEW → CLOSED_ADMINISTRATIVE` with `closed_at` stamped."
    and
    "Administrative closure touches nothing else: no investigating body's `open_case_count` moves, because the case was never routed, and any interim measure imposed during intake survives the closure untouched."

    Design: Difficulty/non_linear_state_machine/case_administrative_closure_and_routed_closure_have_disjoint_side_effect_sets
    """
    setup = _two_cases_on_one_suspended_coach(api)

    closed = validate_success(
        api.close_case(
            setup["intake_case"]["id"],
            {"closure_reason": "DUPLICATE_REPORT"},
            OFFICER_CLOSER_HEADERS,
        )
    )

    assert_state(closed, "status", "CLOSED_ADMINISTRATIVE")
    assert closed["outcome"] is None
    assert closed["investigating_body_id"] is None

    body = validate_success(api.get_investigating_body(setup["body"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(body, open_case_count=1)

    measure = validate_success(
        api.get_interim_measure(setup["measure"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(measure, "status", "ACTIVE")

    member = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_state(member, "membership_status", "SUSPENDED")
    assert_state(member, "contact_eligibility", "RESTRICTED")


def test_unsubstantiated_closure_from_routed_reverses_the_whole_restriction(
    api: ApiClient,
) -> None:
    """The routed branch decrements the caseload, lifts the measure and restores the placement.

    PRD 3.8 says:
    "On an `outcome` of `UNSUBSTANTIATED` the case moves `ROUTED → CLOSED_UNSUBSTANTIATED` and every effect is the inverse: `closed_at` is stamped and the body's `open_case_count` is decremented by one exactly as on the substantiated branch, but every measure against the reported member in status `ACTIVE` moves to `LIFTED` with `lifted_at` stamped from the clock and `lift_reason` recorded as `CASE_UNSUBSTANTIATED`."
    and
    "Every placement of that member in status `SUSPENDED` whose `suspended_reason` is `INTERIM_MEASURE` returns to `ACTIVE`, restoring each club's `active_assignment_count`, and `restricted_member_count` and `compliance_posture` are re-derived for every affected club."

    Design: Difficulty/non_linear_state_machine/case_administrative_closure_and_routed_closure_have_disjoint_side_effect_sets
    """
    setup = _two_cases_on_one_suspended_coach(api)
    get_success_data(
        api.close_case(
            setup["intake_case"]["id"],
            {"closure_reason": "DUPLICATE_REPORT"},
            OFFICER_CLOSER_HEADERS,
        )
    )

    closed = validate_success(
        api.close_case(
            setup["routed_case"]["id"],
            {"closure_reason": "INVESTIGATION_COMPLETE", "outcome": "UNSUBSTANTIATED"},
            OFFICER_CLOSER_HEADERS,
        )
    )

    assert_state(closed, "status", "CLOSED_UNSUBSTANTIATED")

    body = validate_success(api.get_investigating_body(setup["body"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(body, open_case_count=0)

    measure = validate_success(
        api.get_interim_measure(setup["measure"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(measure, "status", "LIFTED")

    placement = validate_success(
        api.get_coach_assignment(setup["placement"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(placement, "status", "ACTIVE")

    member = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_state(member, "membership_status", "ACTIVE")
    assert_state(member, "contact_eligibility", "ELIGIBLE")

    club = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(club, active_assignment_count=1, restricted_member_count=0)
    assert_state(club, "compliance_posture", "OPEN")
