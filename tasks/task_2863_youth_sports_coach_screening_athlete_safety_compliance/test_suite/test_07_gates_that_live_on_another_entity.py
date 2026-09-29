"""Operations whose gate is a state or counter belonging to a different entity.

Activating a coach placement is refused because of a row in the training table,
and routing a case is refused because of a counter on the investigating body that
a third case is holding down.  In both pairs the identical request succeeds once
the other entity moves.
"""

from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_success

from test_helpers.api_client import ApiClient
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_counters, assert_state
from test_helpers.constants import CLOCK_EPOCH
from test_helpers.test_users import (
    NGB_ADMIN_HEADERS,
    OFFICER_ADJUDICATOR_HEADERS,
    OFFICER_CLOSER_HEADERS,
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


def _cleared_untrained_head_coach_with_pending_placement(api: ApiClient) -> Dict[str, Any]:
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    get_success_data(api.publish_course(SS101, NGB_ADMIN_HEADERS), 201)
    member = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Dana Iqbal",
                "email": "dana.iqbal@alpha.test",
                "role_type": "HEAD_COACH",
                "has_minor_athlete_contact": False,
                "date_of_birth": "1986-03-03",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    order = get_success_data(
        api.order_screening(
            member["id"],
            {"expedited": False, "expected_club_version": club["version"]},
            admin,
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
    placement = get_success_data(
        api.create_coach_assignment(
            {
                "member_id": member["id"],
                "club_id": club["id"],
                "team_name": "Senior Sprint",
                "season_start": "2026-09-01T00:00:00Z",
                "season_end": "2027-05-31T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    current = get_success_data(api.get_member(member["id"], admin))
    return {"club": club, "member": current, "placement": placement, "admin": admin}


def test_placement_activation_is_refused_while_the_member_holds_no_completed_course(
    api: ApiClient,
) -> None:
    """The gate is a training row: creating the placement succeeds, activating it does not.

    PRD 3.6 says:
    "A new placement is written in status `PENDING`, with `activated_at`, `eligibility_snapshot_version`, and `suspended_reason` all null and `electronic_comm_authorized` false, and the club's `restricted_member_count` and `compliance_posture` are re-derived."
    PRD 3.4 says:
    "The platform first computes the member's training expiry under the audit-snapshot view — the earliest expiry among the courses required for the member's current `required_tier`, counting only `COMPLETED` assignments, exactly as §3.5 defines it."
    "If that expiry is null, meaning at least one required course has no qualifying completion at all, `training_status` is `NEVER`."
    PRD 2.8 places that gate at its eighteenth rule:
    "The subject member's `training_status` is `CURRENT` — otherwise `ERR_TRAINING_NOT_CURRENT`."

    Design: Difficulty/cross_entity_state_dependency/coach_assignment_activation_depends_on_member_training_dimension
    """
    setup = _cleared_untrained_head_coach_with_pending_placement(api)
    assert_state(setup["member"], "required_tier", "TIER_1")
    assert_state(setup["member"], "screening_status", "CLEARED")
    assert_state(setup["member"], "training_status", "NEVER")
    assert_state(setup["placement"], "status", "PENDING")

    response = api.activate_coach_assignment(
        setup["placement"]["id"],
        {"expected_member_version": setup["member"]["version"]},
        setup["admin"],
    )

    validate_error(response, ApiErrorId.TRAINING_NOT_CURRENT.value, 409)
    assert_state(
        validate_success(api.get_coach_assignment(setup["placement"]["id"], NGB_ADMIN_HEADERS)),
        "status",
        "PENDING",
    )


def test_completing_the_required_course_lets_the_same_activation_succeed(
    api: ApiClient,
) -> None:
    """The fix is a write to the training table, not to the placement or the member.

    PRD 3.4 says:
    "`contact_eligibility` is derived from three independent sources — the screening dimension, training currency, and any restriction in force — and its three clauses are evaluated top to bottom with the first match winning."
    PRD 3.6 says:
    "Activation moves the placement `PENDING → ACTIVE`, stamps `activated_at` from the clock, and pins `eligibility_snapshot_version` to the member's `version` at that instant — a durable record of exactly which eligibility view the club approved."

    Design: Difficulty/cross_entity_state_dependency/coach_assignment_activation_depends_on_member_training_dimension
    """
    setup = _cleared_untrained_head_coach_with_pending_placement(api)
    admin = setup["admin"]
    validate_error(
        api.activate_coach_assignment(
            setup["placement"]["id"],
            {"expected_member_version": setup["member"]["version"]},
            admin,
        ),
        ApiErrorId.TRAINING_NOT_CURRENT.value,
        409,
    )

    assignment = get_success_data(
        api.assign_training(
            {
                "member_id": setup["member"]["id"],
                "course_code": "SS101",
                "due_at": "2026-09-01T00:00:00Z",
            },
            admin,
        ),
        201,
    )
    get_success_data(api.start_training(assignment["id"], admin))
    get_success_data(api.complete_training(assignment["id"], {"score": 88}, admin))

    member = validate_success(api.get_member(setup["member"]["id"], admin))
    assert_state(member, "training_status", "CURRENT")
    assert_state(member, "contact_eligibility", "ELIGIBLE")

    placement = validate_success(
        api.activate_coach_assignment(
            setup["placement"]["id"], {"expected_member_version": member["version"]}, admin
        )
    )
    assert_state(placement, "status", "ACTIVE")
    assert placement["eligibility_snapshot_version"] == member["version"]


def _two_cases_and_a_body_with_room_for_one(api: ApiClient) -> Dict[str, Any]:
    """One body whose ceiling is a single case, one case routed into it, one waiting."""
    get_success_data(api.set_clock(CLOCK_EPOCH, NGB_ADMIN_HEADERS))
    club = get_success_data(api.charter_club(ALPHA_AQUATICS, NGB_ADMIN_HEADERS), 201)
    admin = make_club_admin_headers(club["id"])
    first = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Rae Donnelly",
                "email": "rae.donnelly@alpha.test",
                "role_type": "ASSISTANT_COACH",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1988-04-04",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    second = get_success_data(
        api.register_member(
            {
                "club_id": club["id"],
                "full_name": "Sol Vance",
                "email": "sol.vance@alpha.test",
                "role_type": "ASSISTANT_COACH",
                "has_minor_athlete_contact": True,
                "date_of_birth": "1989-05-05",
                "jurisdiction_codes": ["CA"],
            },
            admin,
        ),
        201,
    )
    body = get_success_data(
        api.register_investigating_body(
            {
                "name": "Center for SafeSport",
                "scope_categories": ["PHYSICAL_ABUSE"],
                "max_open_cases": 1,
                "intake_status": "ACCEPTING",
            },
            NGB_ADMIN_HEADERS,
        ),
        201,
    )
    case_one = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": first["id"],
                "allegation_category": "PHYSICAL_ABUSE",
                "reporter_kind": "MANDATORY_REPORTER",
                "narrative": "first report filed after a meet",
                "occurred_at": "2026-07-31T19:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    case_two = get_success_data(
        api.file_case(
            {
                "club_id": club["id"],
                "reported_member_id": second["id"],
                "allegation_category": "PHYSICAL_ABUSE",
                "reporter_kind": "PARENT",
                "narrative": "unrelated second report filed the same day",
                "occurred_at": "2026-07-31T21:00:00Z",
            },
            OFFICER_INTAKE_HEADERS,
        ),
        201,
    )
    routed = get_success_data(
        api.route_case(case_one["id"], {"investigating_body_id": body["id"]}, OFFICER_INTAKE_HEADERS)
    )
    return {"body": body, "case_one": routed, "case_two": case_two}


def test_routing_is_refused_while_the_body_sits_at_its_caseload_ceiling(api: ApiClient) -> None:
    """The blocking state is a counter on the body, held down by a different case.

    PRD 3.8 says:
    "An officer routes the case by naming an `investigating_body_id`, and three checks run in order: the case's `allegation_category` must appear in that body's `scope_categories`, else `ERR_BODY_SCOPE_MISMATCH`; the body's `intake_status` must be `ACCEPTING`, else `ERR_BODY_INTAKE_PAUSED`; and the body's `open_case_count` must be strictly below its `max_open_cases`, else `ERR_BODY_CASELOAD_EXCEEDED`."
    "Routing moves the case `INTAKE_REVIEW → ROUTED`, stamps `investigating_body_id` and `routed_at` from the clock, and increments both the body's `open_case_count` and its `version` by one."

    Design: Difficulty/cross_entity_state_dependency/case_routing_depends_on_investigating_body_caseload_counter
    """
    setup = _two_cases_and_a_body_with_room_for_one(api)
    assert_state(setup["case_one"], "status", "ROUTED")
    body = validate_success(api.get_investigating_body(setup["body"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(body, open_case_count=1, max_open_cases=1)

    response = api.route_case(
        setup["case_two"]["id"],
        {"investigating_body_id": setup["body"]["id"]},
        OFFICER_INTAKE_HEADERS,
    )

    validate_error(response, ApiErrorId.BODY_CASELOAD_EXCEEDED.value, 409)
    assert_state(
        validate_success(api.get_case(setup["case_two"]["id"], NGB_ADMIN_HEADERS)),
        "status",
        "INTAKE_REVIEW",
    )


def test_closing_the_first_case_frees_the_counter_so_the_same_routing_succeeds(
    api: ApiClient,
) -> None:
    """Closure decrements the very counter that refused the second routing.

    PRD 3.8 says:
    "On an `outcome` of `UNSUBSTANTIATED` the case moves `ROUTED → CLOSED_UNSUBSTANTIATED` and every effect is the inverse: `closed_at` is stamped and the body's `open_case_count` is decremented by one exactly as on the substantiated branch, but every measure against the reported member in status `ACTIVE` moves to `LIFTED` with `lifted_at` stamped from the clock and `lift_reason` recorded as `CASE_UNSUBSTANTIATED`."
    "Routing moves the case `INTAKE_REVIEW → ROUTED`, stamps `investigating_body_id` and `routed_at` from the clock, and increments both the body's `open_case_count` and its `version` by one."

    Design: Difficulty/cross_entity_state_dependency/case_routing_depends_on_investigating_body_caseload_counter
    """
    setup = _two_cases_and_a_body_with_room_for_one(api)
    validate_error(
        api.route_case(
            setup["case_two"]["id"],
            {"investigating_body_id": setup["body"]["id"]},
            OFFICER_INTAKE_HEADERS,
        ),
        ApiErrorId.BODY_CASELOAD_EXCEEDED.value,
        409,
    )

    closed = validate_success(
        api.close_case(
            setup["case_one"]["id"],
            {"closure_reason": "INVESTIGATION_COMPLETE", "outcome": "UNSUBSTANTIATED"},
            OFFICER_CLOSER_HEADERS,
        )
    )
    assert_state(closed, "status", "CLOSED_UNSUBSTANTIATED")
    freed = validate_success(api.get_investigating_body(setup["body"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(freed, open_case_count=0)

    routed = validate_success(
        api.route_case(
            setup["case_two"]["id"],
            {"investigating_body_id": setup["body"]["id"]},
            OFFICER_INTAKE_HEADERS,
        )
    )
    assert_state(routed, "status", "ROUTED")
    assert routed["investigating_body_id"] == setup["body"]["id"]
    refilled = validate_success(api.get_investigating_body(setup["body"]["id"], NGB_ADMIN_HEADERS))
    assert_counters(refilled, open_case_count=1)
