"""
Cascades that travel several entities deep inside one request.

Both scenarios here start from the same world — one active subsidised placement
holding three scheduled shifts, one approved supportive-services request, and one
deferred request waiting for money — and then knock over the first domino. The
chain has to run all the way to the deferral queue and settle before the response
returns.
"""

from test_helpers.assertions import (
    assert_int_field,
    assert_ledger_identity,
    assert_money_cents,
    assert_opening_seat_identity,
    validate_paginated,
    validate_unpaginated,
)
from test_helpers.constants import (
    CATEGORY_TOOLS,
    CATEGORY_TRANSIT_PASS,
    COMPLIANCE_COMPLIANT,
    COMPLIANCE_OUT_OF_COMPLIANCE,
    CONFLICT_WORK_AUTHORIZATION_SUSPENDED,
    DECISION_APPROVED,
    EMPLOYMENT_ACTIVE,
    EMPLOYMENT_SEPARATED,
    FUNDING_POSTURE_OPEN,
    FUNDING_POSTURE_RESTRICTED,
    OPENING_OPEN,
    POSTURE_OPEN,
    POSTURE_RESTRICTED,
    REQUEST_APPROVED,
    REQUEST_DEFERRED,
    SEPARATION_LAYOFF,
    SHIFT_CANCELLED,
    SHIFT_CONFLICTED,
    SHIFT_WORKED,
    STAGE_PLACED,
    STAGE_POST_RELEASE,
    WORK_AUTH_SUSPENDED,
)
from test_helpers import factories as f
from test_helpers.test_users import (
    CASE_MANAGER,
    EMPLOYER_LIAISON,
    FUNDER_ANALYST,
    PROGRAM_DIRECTOR,
    SUPERVISION_OFFICER,
)

SHIFT_INTERVALS = (
    ("2026-08-03T09:00:00.000Z", "2026-08-03T17:00:00.000Z"),
    ("2026-08-04T09:00:00.000Z", "2026-08-04T17:00:00.000Z"),
    ("2026-08-05T09:00:00.000Z", "2026-08-05T17:00:00.000Z"),
)


def _restricted_grant_with_a_deferred_queue(api, build):
    """
    A tight grant carrying one active placement, one approved request, and one
    request the shortage of funds pushed into the deferral queue.
    """
    grant = build.grant(authorized_cents=30000, per_participant_cap_cents=60000)
    participant = build.participant_released()
    case = build.case_authorized(participant["id"])
    partnership = build.partnership_active()
    opening = build.job_opening(partnership["id"])
    placement = build.placement_active(participant["id"], opening["id"], grant["id"])

    shifts = [build.work_shift(placement["id"], starts, ends) for starts, ends in SHIFT_INTERVALS]
    projected = validate_unpaginated(api.get_placement(placement["id"], CASE_MANAGER))
    assert_money_cents(projected, "projected_subsidy_cents", 22200)

    approved_request = build.support_request_approved(
        participant["id"],
        grant["id"],
        [f.line_item("Monthly transit pass", 2500, 2)],
        category=CATEGORY_TRANSIT_PASS,
    )
    assert_money_cents(approved_request, "total_charge_cents", 5000)
    assert approved_request["status"] == REQUEST_APPROVED

    restricted = validate_unpaginated(api.get_grant_ledger(grant["id"], FUNDER_ANALYST))
    assert_money_cents(restricted, "committed_cents", 27200)
    assert_money_cents(restricted, "available_cents", 2800)
    assert restricted["funding_posture"] == FUNDING_POSTURE_RESTRICTED

    deferred_request = build.support_request(
        participant["id"],
        grant["id"],
        [f.line_item("Hand tool set", 4000)],
        category=CATEGORY_TOOLS,
    )
    assert_money_cents(deferred_request, "total_charge_cents", 3400)
    deferred_request = validate_unpaginated(
        api.review_support_request(
            deferred_request["id"], f.review_payload(DECISION_APPROVED), PROGRAM_DIRECTOR
        )
    )
    assert deferred_request["status"] == REQUEST_DEFERRED
    assert deferred_request["deferred_at"] is not None
    assert deferred_request["promoted_at"] is None

    return {
        "grant": grant,
        "participant": participant,
        "case": case,
        "partnership": partnership,
        "opening": opening,
        "placement": placement,
        "shifts": shifts,
        "approved_request": approved_request,
        "deferred_request": deferred_request,
    }


def _separated_world(api, build, clock):
    """The same world after one shift is worked and the placement separates."""
    world = _restricted_grant_with_a_deferred_queue(api, build)
    clock.set("2026-08-03T18:00:00.000Z")
    worked = validate_unpaginated(
        api.set_work_shift_status(
            world["shifts"][0]["id"], f.shift_status_payload(SHIFT_WORKED), CASE_MANAGER
        )
    )
    assert worked["status"] == SHIFT_WORKED
    world["separated"] = validate_unpaginated(
        api.separate_placement(
            world["placement"]["id"],
            f.separation_payload(SEPARATION_LAYOFF, "2026-08-03"),
            EMPLOYER_LIAISON,
        )
    )
    return world


def test_separation_cancels_future_shifts_and_freezes_the_worked_subsidy(
    api, build, clock
):
    """
    Separation settles the placement's money in one request: the future shifts are
    cancelled, the projection collapses, and the worked figure becomes the
    disbursed one.

    PRD section 3.7: "`projected_subsidy_cents` recomputes to 0,
    `actual_subsidy_cents` is frozen at its current figure, and
    `disbursed_subsidy_cents` is set to that frozen `actual_subsidy_cents`."

    Design: Difficulty/transitive_cascade/separation_releases_subsidy_then_flips_posture_then_promotes_deferred
    """
    world = _separated_world(api, build, clock)
    separated = world["separated"]

    assert separated["employment_status"] == EMPLOYMENT_SEPARATED
    assert_money_cents(separated, "projected_subsidy_cents", 0)
    assert_money_cents(separated, "actual_subsidy_cents", 7400)
    assert_money_cents(separated, "disbursed_subsidy_cents", 7400)

    first, second, third = world["shifts"]
    assert (
        validate_unpaginated(api.get_work_shift(first["id"], CASE_MANAGER))["status"]
        == SHIFT_WORKED
    )
    for shift in (second, third):
        stored = validate_unpaginated(api.get_work_shift(shift["id"], CASE_MANAGER))
        assert stored["status"] == SHIFT_CANCELLED


def test_separation_releases_money_then_promotes_exactly_one_deferred_request(
    api, build, clock
):
    """
    The released commitment raises the balance, which runs the waterfall and
    promotes the queue head.

    PRD section 3.8: "If a head exists and its `total_charge_cents` is at most the
    grant's `available_cents`, promote that head from `DEFERRED` to `APPROVED`,
    stamp `promoted_at` from the logical clock, and add its `total_charge_cents` to
    `committed_cents`, then recompute the ledger and `funding_posture`."

    Design: Difficulty/transitive_cascade/separation_releases_subsidy_then_flips_posture_then_promotes_deferred
    """
    world = _separated_world(api, build, clock)

    promoted = validate_unpaginated(
        api.get_support_request(world["deferred_request"]["id"], CASE_MANAGER)
    )
    assert promoted["status"] == REQUEST_APPROVED
    assert promoted["promoted_at"] is not None
    still_approved = validate_unpaginated(
        api.get_support_request(world["approved_request"]["id"], CASE_MANAGER)
    )
    assert still_approved["status"] == REQUEST_APPROVED

    ledger = validate_unpaginated(api.get_grant_ledger(world["grant"]["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 8400)
    assert_money_cents(ledger, "disbursed_cents", 7400)
    assert_money_cents(ledger, "available_cents", 14200)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(ledger, "open_request_count", 0)
    assert_int_field(ledger, "deferred_request_count", 0)
    assert_ledger_identity(ledger)

    participant = validate_unpaginated(
        api.get_participant(world["participant"]["id"], CASE_MANAGER)
    )
    assert participant["stage"] == STAGE_POST_RELEASE
    assert participant["engagement_posture"] == POSTURE_OPEN

    opening = validate_unpaginated(api.get_job_opening(world["opening"]["id"], CASE_MANAGER))
    assert_int_field(opening, "filled_count", 0)
    assert_int_field(opening, "remaining_openings", 2)
    assert opening["status"] == OPENING_OPEN
    assert_opening_seat_identity(opening)

    partnership = validate_unpaginated(
        api.get_partnership(world["partnership"]["id"], EMPLOYER_LIAISON)
    )
    assert_int_field(partnership, "active_placement_count", 0)


def _authorization_suspended_world(api, build):
    """The same world after the officer withdraws work authorisation."""
    world = _restricted_grant_with_a_deferred_queue(api, build)
    world["case_after"] = validate_unpaginated(
        api.decide_work_authorization(
            world["case"]["id"],
            f.work_authorization_payload(WORK_AUTH_SUSPENDED),
            SUPERVISION_OFFICER,
        )
    )
    return world


def test_withdrawing_authorisation_conflicts_the_shifts_and_restricts_the_participant(
    api, build
):
    """
    One officer decision conflicts every future shift, which drives placement
    compliance, which drives the participant's posture.

    PRD section 3.3: "Suspension of authorisation, driven by a `decision` of
    `SUSPENDED` from `APPROVED`, produces exactly the same downstream chain as
    revocation, differing only in the `conflict_reason` written onto the affected
    shifts, which is `WORK_AUTHORIZATION_SUSPENDED` rather than
    `SUPERVISION_REVOKED`: future scheduled shifts on the participant's active
    placements become `CONFLICTED`, those placements become `OUT_OF_COMPLIANCE` and
    shed the conflicted shifts from `projected_subsidy_cents`, the participant
    becomes `RESTRICTED`, and the grant ledger re-runs — lowering
    `committed_cents`, raising `available_cents`, possibly flipping
    `funding_posture`, and possibly promoting one deferred request."

    Design: Difficulty/transitive_cascade/work_authorization_suspension_cascades_shifts_to_compliance_to_ledger
    """
    world = _authorization_suspended_world(api, build)

    case = world["case_after"]
    assert case["work_authorization_status"] == WORK_AUTH_SUSPENDED
    assert_int_field(case, "authorization_change_count", 2)

    for shift in world["shifts"]:
        stored = validate_unpaginated(api.get_work_shift(shift["id"], CASE_MANAGER))
        assert stored["status"] == SHIFT_CONFLICTED
        assert stored["conflict_reason"] == CONFLICT_WORK_AUTHORIZATION_SUSPENDED

    placement = validate_unpaginated(api.get_placement(world["placement"]["id"], CASE_MANAGER))
    assert placement["schedule_compliance"] == COMPLIANCE_OUT_OF_COMPLIANCE
    assert placement["employment_status"] == EMPLOYMENT_ACTIVE
    assert placement["schedule_compliance"] != COMPLIANCE_COMPLIANT
    assert_money_cents(placement, "projected_subsidy_cents", 0)
    assert_money_cents(placement, "actual_subsidy_cents", 0)
    assert_money_cents(placement, "disbursed_subsidy_cents", 0)

    participant = validate_unpaginated(
        api.get_participant(world["participant"]["id"], CASE_MANAGER)
    )
    assert participant["engagement_posture"] == POSTURE_RESTRICTED
    assert participant["stage"] == STAGE_PLACED


def test_the_released_projection_promotes_one_deferred_request_and_conserves_money(
    api, build
):
    """
    Shedding the conflicted shifts from the projection releases commitment, and the
    ledger identity holds across the whole chain.

    PRD section 2.9: "The grant ledger carries its own identity, stated in section
    3.8 and repeated here because it is the system's most important invariant: for
    every funder grant, `authorized_cents` equals `available_cents` plus
    `committed_cents` plus `disbursed_cents` after every write."

    Design: Difficulty/transitive_cascade/work_authorization_suspension_cascades_shifts_to_compliance_to_ledger
    """
    world = _authorization_suspended_world(api, build)

    ledger = validate_unpaginated(api.get_grant_ledger(world["grant"]["id"], FUNDER_ANALYST))
    assert_money_cents(ledger, "committed_cents", 8400)
    assert_money_cents(ledger, "disbursed_cents", 0)
    assert_money_cents(ledger, "available_cents", 21600)
    assert ledger["funding_posture"] == FUNDING_POSTURE_OPEN
    assert_int_field(ledger, "deferred_request_count", 0)
    assert_ledger_identity(ledger)

    promoted = validate_unpaginated(
        api.get_support_request(world["deferred_request"]["id"], CASE_MANAGER)
    )
    assert promoted["status"] == REQUEST_APPROVED
    assert promoted["promoted_at"] is not None

    rows, meta = validate_paginated(
        api.list_support_requests(CASE_MANAGER, f.page_params(grant_id=world["grant"]["id"]))
    )
    assert meta["total_count"] == 2
    assert {row["status"] for row in rows} == {REQUEST_APPROVED}
