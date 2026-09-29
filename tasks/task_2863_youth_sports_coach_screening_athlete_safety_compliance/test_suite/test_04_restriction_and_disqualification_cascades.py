"""The two cascades that run four hops deep from a single request.

Imposing an interim measure and adjudicating a disqualifying record both reach
four entity types synchronously.  One lands in reversible states and raises the
club's restriction; the other lands in terminal states and, by terminating the
placement, drops the club's restriction back to nothing.
"""

from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.assertions import assert_counters, assert_money_equals, assert_state
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_IMPOSE_HEADERS,
    OFFICER_INTAKE_HEADERS,
    SCREENING_VENDOR_HEADERS,
    TEST_USERS,
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


def _order(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    club = get_success_data(api.get_club(club_id, NGB_ADMIN_HEADERS))
    return get_success_data(
        api.order_screening(
            member_id,
            {"expedited": False, "expected_club_version": club["version"]},
            make_club_admin_headers(club_id),
        ),
        201,
    )


def _active_coach_at_open_club(
    api: ApiClient, full_name: str, email: str, dob: str, team_name: str
) -> Dict[str, Any]:
    """A compliant member holding one ACTIVE placement at an OPEN club."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": full_name,
                "email": email,
                "role_type": "VOLUNTEER",
                "has_minor_athlete_contact": False,
                "date_of_birth": dob,
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    order = _order(api, club["id"], member["id"])
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
    assignment = get_success_data(
        api.assign_training(
            {"member_id": member["id"], "course_code": "SS101", "due_at": "2026-09-01T00:00:00Z"},
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], admin))
    get_success_data(api.complete_training(assignment["id"], {"score": 93}, admin))

    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": team_name,
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-06-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    pinned = get_success_data(api.get_member(member["id"], NGB_ADMIN_HEADERS))
    placement = get_success_data(
        api.activate_coach_assignment(
            placement["id"], {"expected_member_version": pinned["version"]}, admin
        )
    )
    return {"club": club, "member": member, "placement": placement}


def _routed_case_against(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Center for SafeSport",
                "scope_categories": ["EMOTIONAL_MISCONDUCT"],
                "max_open_cases": 5,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.file_case(
            {
                "club_id": club_id,
                "reported_member_id": member_id,
                "allegation_category": "EMOTIONAL_MISCONDUCT",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "verbal conduct reported at a meet",
                "occurred_at": "2026-07-31T20:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    case = get_success_data(
        api.route_case(case["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS)
    )
    return case


def _impose_suspension(api: ApiClient, case_id: str, member_id: str) -> Dict[str, Any]:
    pinned = get_success_data(api.get_member(member_id, NGB_ADMIN_HEADERS))
    return validate_success(
        api.impose_interim_measure(
            case_id,
            {
                "member_id": member_id,
                "measure_kind": "TEMPORARY_SUSPENSION",
                "effective_from": "2026-08-01T00:00:00Z",
                "effective_to": "2026-09-05T00:00:00Z",
                "expected_member_version": pinned["version"],
            },
            OFFICER_IMPOSE_HEADERS,
        ),
        201,
    )


def test_imposing_a_suspension_restricts_the_member_and_suspends_the_placement(
    api: ApiClient,
) -> None:
    """Hops one to three land on the measure, the member and the coach placement.

    PRD 3.8 says:
    "Hop one creates the measure in status `ACTIVE` with `permanence` of `TEMPORARY` and `imposed_by_user_id` set from the acting `X-User-ID`, leaving `converted_by_user_id`, `lifted_at`, `lift_reason`, and `rationale` null."
    "Hop two rewrites the member: `contact_eligibility` becomes `RESTRICTED`, and when the `measure_kind` is `TEMPORARY_SUSPENSION` the membership dimension moves `ACTIVE → SUSPENDED`."
    "Hop three moves every coach placement that member holds in status `ACTIVE` to `SUSPENDED` with `suspended_reason` recorded as `INTERIM_MEASURE`."

    Design: Difficulty/transitive_cascade/interim_measure_four_hop_restriction_cascade
    """
    setup = _active_coach_at_open_club(
        api, "Lena Frost", "lena.frost@alpha.test", "1987-11-11", "Distance Group"
    )
    case = _routed_case_against(api, setup["club"]["id"], setup["member"]["id"])

    measure = _impose_suspension(api, case["id"], setup["member"]["id"])

    assert_state(measure, "status", "ACTIVE")
    assert_state(measure, "permanence", "TEMPORARY")
    assert measure["imposed_by_user_id"] == TEST_USERS["officer_impose"]["user_id"]
    assert measure["case_id"] == case["id"]

    member = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_state(member, "membership_status", "SUSPENDED")
    assert_state(member, "contact_eligibility", "RESTRICTED")
    assert_counters(member, active_assignment_count=0)

    placement = validate_success(
        api.get_coach_assignment(setup["placement"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(placement, "status", "SUSPENDED")
    assert_state(placement, "suspended_reason", "INTERIM_MEASURE")


def test_imposing_a_suspension_flips_the_club_posture_to_restricted(api: ApiClient) -> None:
    """Hop four re-derives the club that lost the placement, in the same request.

    PRD 3.8 says:
    "Hop four re-derives every club that lost a placement: `active_assignment_count` is decremented, `restricted_member_count` is incremented, and `compliance_posture` is re-derived — which is how one officer's action at one club can restrict a second club that shares the coach."
    The counter it moves is defined in PRD 2.9:
    "`restricted_member_count` counts the distinct members who hold a coach placement at this club in status `ACTIVE` or `SUSPENDED` and whose `contact_eligibility` is `RESTRICTED` or `PROHIBITED`."

    Design: Difficulty/transitive_cascade/interim_measure_four_hop_restriction_cascade
    """
    setup = _active_coach_at_open_club(
        api, "Lena Frost", "lena.frost@alpha.test", "1987-11-11", "Distance Group"
    )
    before = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(before, active_assignment_count=1, restricted_member_count=0)
    assert_state(before, "compliance_posture", "OPEN")

    case = _routed_case_against(api, setup["club"]["id"], setup["member"]["id"])
    _impose_suspension(api, case["id"], setup["member"]["id"])

    after = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(after, active_assignment_count=0, restricted_member_count=1)
    assert_state(after, "compliance_posture", "RESTRICTED")


def _flagged_second_order(api: ApiClient, club_id: str, member_id: str) -> Dict[str, Any]:
    """A second screening order whose vendor return found a record."""
    order = _order(api, club_id, member_id)
    get_success_data(
        api.post_screening_result(
            order["id"], {"vendor_disposition": "RECORD_FOUND"}, SCREENING_VENDOR_HEADERS
        )
    )
    return order


def _disqualify(api: ApiClient, order_id: str) -> Dict[str, Any]:
    return validate_success(
        api.adjudicate_screening_order(
            order_id,
            {
                "disposition": "DISQUALIFYING_RECORD",
                "rationale": "conviction appears on the disqualifying criteria list",
            },
            OFFICER_ADJUDICATOR_HEADERS,
        )
    )


def test_disqualifying_adjudication_terminates_the_placement_and_revokes_membership(
    api: ApiClient,
) -> None:
    """Every hop of this cascade lands in a terminal state, not a reversible one.

    PRD 3.3 says:
    "On `DISQUALIFYING_RECORD` the order becomes `ADJUDICATED` with `adjudicated_at` stamped and `expires_at` left null, the member's screening dimension moves `FLAGGED → DISQUALIFIED` with `screening_expires_at` cleared to null, and `contact_eligibility` is set to `PROHIBITED`."
    "The membership dimension then moves to `REVOKED` — from `ACTIVE` or from `LAPSED` alike."
    "Every coach placement that member holds in status `PENDING`, `ACTIVE`, or `SUSPENDED` moves to `TERMINATED` with `suspended_reason` recorded as `SCREENING_DISQUALIFICATION`."

    Design: Difficulty/transitive_cascade/disqualifying_adjudication_cascade_terminates_placements_and_clears_posture
    """
    setup = _active_coach_at_open_club(
        api, "Ollie Marsh", "ollie.marsh@alpha.test", "1986-12-12", "Sprint Group"
    )
    second = _flagged_second_order(api, setup["club"]["id"], setup["member"]["id"])

    order = _disqualify(api, second["id"])
    assert_state(order, "status", "ADJUDICATED")
    assert_state(order, "disposition", "DISQUALIFYING_RECORD")
    assert order["expires_at"] is None

    member = validate_success(api.get_member(setup["member"]["id"], NGB_ADMIN_HEADERS))
    assert_state(member, "screening_status", "DISQUALIFIED")
    assert_state(member, "membership_status", "REVOKED")
    assert_state(member, "contact_eligibility", "PROHIBITED")
    assert member["screening_expires_at"] is None

    placement = validate_success(
        api.get_coach_assignment(setup["placement"]["id"], NGB_ADMIN_HEADERS)
    )
    assert_state(placement, "status", "TERMINATED")
    assert_state(placement, "suspended_reason", "SCREENING_DISQUALIFICATION")


def test_terminated_placement_drops_out_of_the_restricted_count_so_posture_returns_to_open(
    api: ApiClient,
) -> None:
    """The flagged member restricted the club; disqualifying him releases it again.

    PRD 3.3 says:
    "For each club that lost an active placement, `active_assignment_count` is decremented, `restricted_member_count` is re-derived, and `compliance_posture` is re-derived."
    Because the placement is now `TERMINATED` it falls outside the counter PRD 2.9 defines:
    "`restricted_member_count` counts the distinct members who hold a coach placement at this club in status `ACTIVE` or `SUSPENDED` and whose `contact_eligibility` is `RESTRICTED` or `PROHIBITED`."
    PRD 2.12 adds:
    "A caller who reads a club immediately after disqualifying one of its coaches sees the club's counters and posture already reduced."

    Design: Difficulty/transitive_cascade/disqualifying_adjudication_cascade_terminates_placements_and_clears_posture
    """
    setup = _active_coach_at_open_club(
        api, "Ollie Marsh", "ollie.marsh@alpha.test", "1986-12-12", "Sprint Group"
    )
    second = _flagged_second_order(api, setup["club"]["id"], setup["member"]["id"])

    before = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_state(before, "compliance_posture", "RESTRICTED")
    assert_counters(before, restricted_member_count=1, active_assignment_count=1)
    assert_money_equals(before, "escrow_balance_cents", 495000)

    _disqualify(api, second["id"])

    after = validate_success(api.get_club(setup["club"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(after, restricted_member_count=0, active_assignment_count=0)
    assert_state(after, "compliance_posture", "OPEN")
    assert_money_equals(after, "escrow_balance_cents", 495000)
