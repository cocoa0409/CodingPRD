"""Facility closures and their cascades: posture derivation, program
cancellation, permit suspension/reinstatement, and the conservation of
committed visitor days across a suspend/reinstate pair.
"""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error,
    create_unit, create_final_determination, create_active_permit,
    get_permit, create_closure, activate_closure, lift_closure,
    get_unit_posture, get_program, get_assignment,
    setup_closure_cascade_scenario, create_program,
    create_program_payload,
)

BIO = TEST_USERS["biologist_headers"]
VC = TEST_USERS["volunteer_coordinator_headers"]


def test_unit_visitor_days_suspend_reinstate_conserves_count(api):
    """PRD §3.1: "Two invariants are pinned. A suspension followed by its
    matching reinstatement — the same closure, lifted — leaves the tally
    unchanged. And a payment followed by a closure activation that suspends
    the permit returns the unit to its pre-payment value."

    Design: Difficulty/compensating_invariant/unit_visitor_days_suspend_reinstate_conserves_count
    """
    unit = create_unit()
    det = create_final_determination(use_type="RESEARCH")
    permit = create_active_permit(unit["id"], det["id"], applicant_ref="app-1",
                                  crew_size=5)
    closure = create_closure(
        unit["id"], closure_type="MIGRATION", scope="FULL",
        start_date="2026-10-09", end_date="2026-10-20")
    pre = get_unit_posture(unit["id"])
    assert pre["committed_visitor_days"] == 15, (
        f"crew 5 x 3 days must commit 15 visitor-days, "
        f"got {pre['committed_visitor_days']}")
    activate_closure(closure["id"])
    mid_permit = get_permit(permit["id"])
    assert mid_permit["status"] == "SUSPENDED"
    mid = get_unit_posture(unit["id"])
    assert mid["committed_visitor_days"] == 0, (
        "suspension must release the permit's visitor days")
    lift_closure(closure["id"])
    post_permit = get_permit(permit["id"])
    assert post_permit["status"] == "ACTIVE", (
        "end_date 2026-10-12 is on or after the clock date, so the permit "
        "must reinstate to ACTIVE")
    post = get_unit_posture(unit["id"])
    assert post["committed_visitor_days"] == 15, (
        f"suspend + matching reinstate must conserve the tally at 15, "
        f"got {post['committed_visitor_days']}")


def test_closure_lift_from_scheduled_rejected(api):
    """PRD §3.5: "Lifting moves an `ACTIVE` closure to `LIFTED`, the terminal
    state, and runs the reverse half."
    PRD §2.6: "5. **State preconditions** — the invoked transition's
    from-state holds; terminal states reject every transition
    (`ERR_INVALID_STATE`, 409)."

    Design: Corner/state_machines/closure_lift_from_scheduled_rejected
    """
    unit = create_unit()
    closure = create_closure(
        unit["id"], closure_type="MIGRATION", scope="FULL",
        start_date="2026-10-09", end_date="2026-10-20")
    assert closure["status"] == "SCHEDULED"
    resp = api_client.lift_closure(closure["id"], BIO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_trails_only_closure_cancels_program_but_leaves_permits_active(api):
    """PRD §3.5: "Then, regardless of scope, every interpretive program on the
    unit still `SCHEDULED` whose `program_date` falls within the closure's
    inclusive window is cancelled, moving to `CANCELLED`, and every volunteer
    assignment still `ACTIVE` on each cancelled program is released to
    `RELEASED`."
    PRD §3.3: "Note that trails-only closures never suspend permits at all —
    only the full scope does."
    PRD §2.11: "Otherwise, if any `ACTIVE` closure has scope `TRAILS_ONLY`,
    the posture is `RESTRICTED`."

    Design: Corner/state_machines/trails_only_closure_cancels_program_but_leaves_permits_active
    """
    ctx = setup_closure_cascade_scenario(closure_scope="TRAILS_ONLY")
    activate_closure(ctx["closure"]["id"])
    program = get_program(ctx["unit"]["id"], ctx["program"]["id"])
    assert program["status"] == "CANCELLED"
    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "RELEASED"
    permit = get_permit(ctx["permit"]["id"])
    assert permit["status"] == "ACTIVE", (
        "a TRAILS_ONLY closure must not suspend permits")
    posture = get_unit_posture(ctx["unit"]["id"])
    assert posture["access_posture"] == "RESTRICTED"
    assert posture["committed_visitor_days"] == 4, (
        f"visitor days must be untouched by a trails-only closure, "
        f"got {posture['committed_visitor_days']}")


def test_lifted_closure_does_not_restore_cancelled_program(api):
    """PRD §3.5: "Programs are the deliberate exception: a program cancelled
    by the activation is not restored by the lift — cancellation is
    permanent, and the program stays `CANCELLED`."

    Design: Corner/state_machines/lifted_closure_does_not_restore_cancelled_program
    """
    ctx = setup_closure_cascade_scenario(closure_scope="FULL")
    activate_closure(ctx["closure"]["id"])
    lift_closure(ctx["closure"]["id"])
    program = get_program(ctx["unit"]["id"], ctx["program"]["id"])
    assert program["status"] == "CANCELLED", (
        "a cancelled program is permanent and must not be restored by lift")
    permit = get_permit(ctx["permit"]["id"])
    assert permit["status"] == "ACTIVE", (
        "the suspended permit's window still extends past the clock date, "
        "so it must reinstate to ACTIVE")


def test_full_closure_cascade_end_to_end(api):
    """PRD §3.5: "Then, regardless of scope, every interpretive program on the
    unit still `SCHEDULED` whose `program_date` falls within the closure's
    inclusive window is cancelled, moving to `CANCELLED`, and every volunteer
    assignment still `ACTIVE` on each cancelled program is released to
    `RELEASED`. Finally, when and only when the scope is `FULL`, every permit
    on the unit in `ACTIVE` status whose authorized window intersects the
    closure window is suspended to `SUSPENDED`, stamped with
    `suspended_by_closure_id` set to this closure's `id`, and each suspension
    releases that permit's visitor days from the unit's
    `committed_visitor_days`."

    Design: Corner/complexity_layers/full_closure_cascade_end_to_end
    """
    ctx = setup_closure_cascade_scenario(closure_scope="FULL")
    activate_closure(ctx["closure"]["id"])
    program = get_program(ctx["unit"]["id"], ctx["program"]["id"])
    assert program["status"] == "CANCELLED"
    assignment = get_assignment(ctx["assignment"]["id"])
    assert assignment["status"] == "RELEASED"
    permit = get_permit(ctx["permit"]["id"])
    assert permit["status"] == "SUSPENDED"
    assert permit["suspended_by_closure_id"] == ctx["closure"]["id"], (
        "the suspending closure's id must be stamped onto the permit")
    posture = get_unit_posture(ctx["unit"]["id"])
    assert posture["access_posture"] == "CLOSED"
    assert posture["committed_visitor_days"] == 0
    assert posture["active_closure_count"] == 1


def test_full_posture_blocks_program_but_trails_only_allows(api):
    """PRD §2.11: "Posture gates two operations: scheduling an interpretive
    program is rejected with `ERR_POSTURE_CLOSED` when the chosen program
    date intersects the window of an `ACTIVE` full-scope closure on the same
    unit — a date-scoped check, not a point-in-time read — and starting a
    treatment is rejected with `ERR_POSTURE_CLOSED` when the unit's posture
    at the current clock date is `CLOSED`, meaning an active full-scope
    closure covers that date."

    Design: Corner/validations/full_posture_blocks_program_but_trails_only_allows
    """
    unit_a = create_unit(name="Unit A", habitat_type="WETLAND", acreage=100)
    unit_b = create_unit(name="Unit B", habitat_type="FOREST", acreage=100)
    closure_a = create_closure(
        unit_a["id"], closure_type="MIGRATION", scope="FULL",
        start_date="2026-10-01", end_date="2026-10-31")
    closure_b = create_closure(
        unit_b["id"], closure_type="MIGRATION", scope="TRAILS_ONLY",
        start_date="2026-10-01", end_date="2026-10-31")
    activate_closure(closure_a["id"])
    activate_closure(closure_b["id"])
    blocked = api_client.create_program(
        unit_a["id"],
        create_program_payload(
            title="Walk A", program_date="2026-10-05",
            min_volunteers=1, max_volunteers=3),
        VC)
    validate_error(blocked, ApiErrorId.ERR_POSTURE_CLOSED)
    allowed = create_program(
        unit_b["id"], title="Walk B", program_date="2026-10-05",
        min_volunteers=1, max_volunteers=3)
    assert allowed["status"] == "SCHEDULED", (
        "the same date under an ACTIVE TRAILS_ONLY closure must not be "
        "blocked by the posture gate")
