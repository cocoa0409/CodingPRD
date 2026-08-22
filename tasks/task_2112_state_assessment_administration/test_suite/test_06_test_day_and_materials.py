"""Test day: moving booklets into the room, opening it, and the conservation
invariant the custody chain replay must preserve."""
from test_helpers import (
    ApiErrorId,
    TEST_CALENDAR,
    assert_lot_conservation,
    create_custody_event_payload,
    create_transition_payload,
    deliver_lot_to_school,
    make_officer_headers,
    make_proctor_headers,
    make_school_coordinator_headers,
    move_session,
    read_custody_event,
    read_lot,
    read_session,
    receipt,
    session_checkout,
    set_clock,
    setup_program,
    setup_program_with_certified_proctor,
    setup_staffed_session,
    transfer_to_school,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_room_with_too_few_booklets_out_cannot_open(api):
    """PRD §3.6: "And the room must be materially ready: the count of booklets
    currently out to the session, meaning `materials_checked_out` minus
    `materials_checked_in`, must be at least the number of registrations on the
    session whose `attendance_status` is not `WITHDRAWN`, failing with
    `ERR_INSUFFICIENT_MATERIALS`."

    Design: Difficulty/cross_entity_state_dependency/session_activation_depends_on_material_lot_checkout_state
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0013", school_code="MH-01", lot_code="LOT-L1",
        seal_start=1600)
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 10},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"}])
    session = built["session"]
    session_checkout(ctx["lot"]["id"], ctx["proctor"]["id"], session["id"], 1)
    set_clock(TEST_CALENDAR["SESSION_START"])

    response = api.transition_session(
        session["id"], create_transition_payload("ACTIVE"),
        make_proctor_headers(ctx["proctor"]["id"]))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_MATERIALS.value, 422)

    unchanged = read_session(session["id"])
    assert unchanged["status"] == "SCHEDULED"
    assert unchanged["opened_at"] is None
    assert unchanged["materials_checked_out"] == 1


def test_a_second_checkout_supplies_the_room_and_lets_it_open(api):
    """PRD §3.6: "While a session is still `SCHEDULED`, its assigned proctor
    checks booklets out of the school's holding by recording a
    `SESSION_CHECKOUT` naming that session, which raises the session's
    `materials_checked_out` by the quantity moved and may not draw more than the
    lot's `quantity_at_school` currently holds."
    PRD §3.5: "A `SESSION_CHECKOUT` subtracts from the school bucket and adds to
    the sessions bucket. A `SESSION_CHECKIN` subtracts from the sessions bucket
    and adds back to the school bucket."
    PRD §3.6: "On success the `status` becomes `ACTIVE`, `opened_at` is stamped
    from the logical clock, and the session's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/session_activation_depends_on_material_lot_checkout_state
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0013", school_code="MH-01", lot_code="LOT-L1",
        seal_start=1600)
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 10},
                  {"student_state_id": "S00000002", "grade": 10,
                   "guardian_email": "g2@fam.example"}])
    session = built["session"]
    session_checkout(ctx["lot"]["id"], ctx["proctor"]["id"], session["id"], 1)
    set_clock(TEST_CALENDAR["SESSION_START"])
    session_checkout(ctx["lot"]["id"], ctx["proctor"]["id"], session["id"], 1)

    supplied = read_session(session["id"])
    assert supplied["materials_checked_out"] == 2
    lot = read_lot(ctx["lot"]["id"])
    assert lot["quantity_in_sessions"] == 2
    assert lot["quantity_at_school"] == 8
    assert_lot_conservation(lot)

    opened = validate_success(api.transition_session(
        session["id"], create_transition_payload("ACTIVE"),
        make_proctor_headers(ctx["proctor"]["id"])))
    assert opened["status"] == "ACTIVE"
    assert opened["opened_at"] == "2026-09-08T09:00:00.000Z"


def test_checkout_moves_booklets_without_changing_the_conserved_total(api):
    """PRD §3.5: "A `SESSION_CHECKOUT` subtracts from the school bucket and adds
    to the sessions bucket. A `SESSION_CHECKIN` subtracts from the sessions
    bucket and adds back to the school bucket."
    PRD §3.5: "After each entry is applied, that entry's `chain_balance_after`
    is stamped with the sum of all four buckets at that moment. Because every
    movement only relocates booklets, that sum is a conserved quantity: it
    equals the lot's `quantity_shipped` after every entry, forward or
    compensating, and any implementation in which it drifts has a defect."

    Design: Difficulty/compensating_invariant/session_checkin_restores_lot_booklet_conservation_exactly
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0017", school_code="QH-01", lot_code="LOT-Q1",
        lot_quantity=20, seal_start=2200)
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 10}])

    checkout = validate_success(api.create_custody_event(
        ctx["lot"]["id"],
        create_custody_event_payload("SESSION_CHECKOUT", 6,
                                     session_id=built["session"]["id"]),
        make_proctor_headers(ctx["proctor"]["id"])), expected_status=201)

    assert checkout["chain_balance_after"] == 20, (
        "the conserved total still equals quantity_shipped after the checkout")
    assert checkout["from_holder_type"] == "SCHOOL"
    assert checkout["to_holder_type"] == "SESSION"

    lot = read_lot(ctx["lot"]["id"])
    assert lot["quantity_at_school"] == 14
    assert lot["quantity_in_sessions"] == 6
    assert_lot_conservation(lot)


def test_checkin_restores_the_school_bucket_exactly(api):
    """PRD §3.5: "After each entry is applied, that entry's `chain_balance_after`
    is stamped with the sum of all four buckets at that moment. Because every
    movement only relocates booklets, that sum is a conserved quantity: it
    equals the lot's `quantity_shipped` after every entry, forward or
    compensating, and any implementation in which it drifts has a defect."
    PRD §3.5: "Everything else on the entry is server-derived and never
    client-supplied: the `sequence_no` as a one-based position within this lot's
    chain, the `previous_event_id` pointing at the immediately preceding entry
    on the same lot (null for the lot's first entry), the `from_holder_type` and
    `to_holder_type` naming which bucket the booklets left and entered, the
    `actor_user_id` and `actor_role` taken from the request headers, the
    `occurred_at` instant taken from the logical clock, and the
    `chain_balance_after` described below."
    PRD §3.5: "A `SESSION_CHECKOUT` and a `SESSION_CHECKIN`, both recorded by
    the assigned proctor, shuttle booklets between the `SCHOOL` and `SESSION`
    holders; they leave the lot's status where it was, a self-loop written
    `IN_DISTRIBUTION → IN_DISTRIBUTION`, because the interesting movement lives
    in the bucket counters rather than in the status field."

    Design: Difficulty/compensating_invariant/session_checkin_restores_lot_booklet_conservation_exactly
    """
    ctx = setup_program_with_certified_proctor(
        district_code="NG-0017", school_code="QH-01", lot_code="LOT-Q1",
        lot_quantity=20, seal_start=2200)
    deliver_lot_to_school(ctx)
    built = setup_staffed_session(
        ctx, room_code="R101", seat_capacity=25,
        students=[{"student_state_id": "S00000001", "grade": 10}])
    session = built["session"]
    checkout = session_checkout(ctx["lot"]["id"], ctx["proctor"]["id"],
                                session["id"], 6)
    set_clock(TEST_CALENDAR["SESSION_START"])
    move_session(session["id"], "ACTIVE", proctor_id=ctx["proctor"]["id"])

    checkin = validate_success(api.create_custody_event(
        ctx["lot"]["id"],
        create_custody_event_payload("SESSION_CHECKIN", 6,
                                     session_id=session["id"]),
        make_proctor_headers(ctx["proctor"]["id"])), expected_status=201)

    assert checkin["chain_balance_after"] == 20
    assert checkin["sequence_no"] == 4, (
        "receipt, transfer, checkout and check-in are entries 1 through 4")
    assert checkin["previous_event_id"] == checkout["id"]
    assert checkin["from_holder_type"] == "SESSION"
    assert checkin["to_holder_type"] == "SCHOOL"

    lot = read_lot(ctx["lot"]["id"])
    assert lot["quantity_at_district"] == 0
    assert lot["quantity_at_school"] == 20, "every booklet is back at the school"
    assert lot["quantity_in_sessions"] == 0
    assert lot["quantity_destroyed"] == 0
    assert lot["status"] == "IN_DISTRIBUTION", "the shuttle is a status self-loop"
    assert_lot_conservation(lot)

    settled = read_session(session["id"])
    assert settled["materials_checked_out"] == 6
    assert settled["materials_checked_in"] == 6


def test_partial_return_is_refused_until_the_school_bucket_empties(api):
    """PRD §3.5: "A `RETURN_TO_DISTRICT`, recorded by a school coordinator,
    moves booklets from `SCHOOL` back to `DISTRICT` and drives
    `IN_DISTRIBUTION → RETURNED_PENDING`, but only under three conditions:
    `quantity_in_sessions` must already be 0, the `quantity` returned may not
    exceed `quantity_at_school`, and the return must empty the school bucket
    completely — a partial return that would leave any booklets at the school is
    refused, so the status only advances when the school is genuinely clear."
    PRD §3.5: "Chain continuity asks whether the submitted `event_type` is legal
    for the lot's current status and whether its required predecessor exists: a
    transfer to a school before any receipt, a second receipt on a lot that
    already has one, a checkout against a session that is not `SCHEDULED`, a
    check-in against a session with no open checkout, a return while booklets
    are still out in sessions or one that would leave booklets at the school,
    and a destruction before the lot reached `RETURNED_PENDING` all fail here
    with `ERR_CUSTODY_CHAIN_BROKEN`."

    Design: Corner/state_machines/partial_material_return_leaves_lot_in_distribution
    """
    ctx = setup_program(district_code="NG-1014", school_code="AS-01",
                        lot_code="LOT-Y2", seal_start=3200,
                        open_the_window=False)
    deliver_lot_to_school(ctx)

    partial = api.create_custody_event(
        ctx["lot"]["id"], create_custody_event_payload("RETURN_TO_DISTRICT", 6),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(partial, ApiErrorId.ERR_CUSTODY_CHAIN_BROKEN.value, 422)

    held = read_lot(ctx["lot"]["id"])
    assert held["status"] == "IN_DISTRIBUTION"
    assert held["quantity_at_school"] == 10

    data, meta = validate_paginated(api.list_custody_events(
        make_officer_headers(), params={"material_lot_id": ctx["lot"]["id"]}))
    assert meta["total_count"] == 2, "the refused movement writes no entry"

    full = validate_success(api.create_custody_event(
        ctx["lot"]["id"], create_custody_event_payload("RETURN_TO_DISTRICT", 10),
        make_school_coordinator_headers(ctx["school"]["id"])),
        expected_status=201)
    assert full["sequence_no"] == 3

    cleared = read_lot(ctx["lot"]["id"])
    assert cleared["status"] == "RETURNED_PENDING"
    assert cleared["quantity_at_school"] == 0
    assert cleared["quantity_at_district"] == 10


def test_transfer_before_any_receipt_breaks_the_chain(api):
    """PRD §3.5: "Chain continuity asks whether the submitted `event_type` is
    legal for the lot's current status and whether its required predecessor
    exists: a transfer to a school before any receipt, a second receipt on a lot
    that already has one, a checkout against a session that is not `SCHEDULED`,
    a check-in against a session with no open checkout, a return while booklets
    are still out in sessions or one that would leave booklets at the school,
    and a destruction before the lot reached `RETURNED_PENDING` all fail here
    with `ERR_CUSTODY_CHAIN_BROKEN`."
    PRD §3.5: "A `TRANSFER_TO_SCHOOL`, recorded by a school coordinator whose
    school belongs to the lot's district, moves booklets from `DISTRICT` to
    `SCHOOL` and drives `RECEIVED → IN_DISTRIBUTION`."

    Design: Corner/state_machines/transfer_before_receipt_breaks_the_custody_chain
    """
    ctx = setup_program(district_code="NG-1015", school_code="BW-01",
                        lot_code="LOT-Y3", seal_start=3300,
                        open_the_window=False)

    response = api.create_custody_event(
        ctx["lot"]["id"], create_custody_event_payload("TRANSFER_TO_SCHOOL", 10),
        make_school_coordinator_headers(ctx["school"]["id"]))
    validate_error(response, ApiErrorId.ERR_CUSTODY_CHAIN_BROKEN.value, 422)

    untouched = read_lot(ctx["lot"]["id"])
    assert untouched["status"] == "SHIPPED"
    assert untouched["quantity_at_district"] == 0

    data, meta = validate_paginated(api.list_custody_events(
        make_officer_headers(), params={"material_lot_id": ctx["lot"]["id"]}))
    assert meta["total_count"] == 0, "no custody row may be written"


def test_custody_list_returns_the_chain_in_sequence_order(api):
    """PRD §2.3: "Custody events may be narrowed by `material_lot_id`,
    `session_id`, `previous_event_id`, and `event_type`, and are returned in
    ascending custody sequence within a lot."
    PRD §3.5: "Everything else on the entry is server-derived and never
    client-supplied: the `sequence_no` as a one-based position within this lot's
    chain, the `previous_event_id` pointing at the immediately preceding entry
    on the same lot (null for the lot's first entry), the `from_holder_type` and
    `to_holder_type` naming which bucket the booklets left and entered, the
    `actor_user_id` and `actor_role` taken from the request headers, the
    `occurred_at` instant taken from the logical clock, and the
    `chain_balance_after` described below."

    Design: Corner/endpoints/custody_event_list_returns_the_chain_in_sequence_order
    """
    ctx = setup_program(district_code="NG-1035", school_code="VB-01",
                        lot_code="LOT-U1", seal_start=5200,
                        open_the_window=False, max_concurrent_seats=40)
    first = receipt(ctx["lot"]["id"], ctx["district"]["id"], 10)
    second = transfer_to_school(ctx["lot"]["id"], ctx["school"]["id"], 10)

    data, meta = validate_paginated(api.list_custody_events(
        make_school_coordinator_headers(ctx["school"]["id"]),
        params={"material_lot_id": ctx["lot"]["id"]}))

    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert data[0]["id"] == first["id"], "the chain is ordered by sequence_no"
    assert data[1]["id"] == second["id"]

    linked = read_custody_event(second["id"])
    assert linked["sequence_no"] == 2
    assert linked["previous_event_id"] == first["id"]
    assert linked["from_holder_type"] == "DISTRICT"
    assert linked["to_holder_type"] == "SCHOOL"
    assert linked["actor_role"] == "SchoolTestCoordinator"
    assert linked["actor_user_id"] == ctx["school"]["id"]
