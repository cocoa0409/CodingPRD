"""Resident registration, jurisdiction verification, slot geometry at booking,
the supersession guard and the declared-mass ledger."""

from test_helpers import (
    ANONYMOUS,
    CLERK,
    EXPLOSIVE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_appointment,
    assert_kg,
    assert_resident,
    book_appointment,
    create_appointment_payload,
    create_program,
    create_resident_payload,
    make_resident_headers,
    read_appointment,
    read_event,
    read_resident,
    register_resident,
    setup_canon,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_get_resident_with_unknown_id_returns_resident_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_resident_with_unknown_id_returns_resident_not_found
    """
    response = api.get_resident(NON_EXISTENT_UUID, CLERK)
    validate_error(response, ApiErrorId.ERR_RESIDENT_NOT_FOUND, 404)


def test_get_appointment_with_unknown_id_returns_appointment_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_appointment_with_unknown_id_returns_appointment_not_found
    """
    response = api.get_appointment(NON_EXISTENT_UUID, CLERK)
    validate_error(response, ApiErrorId.ERR_APPOINTMENT_NOT_FOUND, 404)


def test_verification_outside_the_eligible_jurisdictions_is_a_successful_transition(api):
    """PRD §3.5: "Both doors produce a resident in `PENDING_VERIFICATION` with a
    `version` of 1, a null `verified_jurisdiction_code`, and zeroed ledgers:
    `annual_quantity_reserved_kg`, `annual_quantity_settled_kg`,
    `no_show_strike_count` and `completed_visit_count` all start at zero."
    PRD §3.5: "When the verified code is a member of the program's
    `eligible_jurisdiction_codes`, the resident becomes `ELIGIBLE`; when it is not,
    the resident becomes `INELIGIBLE_OUT_OF_JURISDICTION`."

    Design: Corner/state_machines/resident_verify_outside_jurisdiction_sets_ineligible
    """
    program = create_program()
    created = validate_success(
        api.create_resident(
            create_resident_payload(program["id"], full_name="Cara Lin", street_address="77 Pine Street"),
            ANONYMOUS,
        ),
        201,
    )
    assert_resident(created)
    assert created["eligibility_status"] == "PENDING_VERIFICATION"

    response = api.resident_eligibility_action(
        created["id"], {"action": "VERIFY", "verified_jurisdiction_code": "WY-CHY"}, CLERK
    )
    verified = validate_success(response, 200)

    assert verified["eligibility_status"] == "INELIGIBLE_OUT_OF_JURISDICTION"
    assert verified["verified_jurisdiction_code"] == "WY-CHY"
    assert verified["annual_quantity_reserved_kg"] == 0


def test_declaring_a_prohibited_category_is_turned_away_at_the_desk(api):
    """PRD §3.5: "One further screen runs at booking time: no identifier in
    `declared_category_ids` may name a material category whose `acceptance_policy` is
    `REJECTED_ALWAYS`. A resident who tells the front desk they are bringing
    explosives is turned away at the desk rather than at the gate, with
    `ERR_PROHIBITED_MATERIAL_DECLARED`."

    Design: Corner/validations/booking_with_prohibited_declared_category_returns_error
    """
    ctx = setup_canon(12, category=EXPLOSIVE)

    response = api.create_appointment(
        create_appointment_payload(
            ctx["event_id"],
            ctx["resident_id"],
            ctx["resident"]["version"],
            [ctx["category_id"]],
            declared_total_kg=3.0,
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_PROHIBITED_MATERIAL_DECLARED, 422)

    _, meta = validate_paginated(
        api.list_appointments(CLERK, params={"event_id": ctx["event_id"]})
    )
    assert meta["total_count"] == 0
    assert read_resident(ctx["resident_id"])["version"] == ctx["resident"]["version"]


def test_arrival_slot_off_the_quarter_hour_grid_is_refused(api):
    """PRD §3.5: "And the slot must be aligned to a fifteen-minute boundary measured
    **from `window_start_utc`**, not from the top of the hour: the offset in minutes
    from the window's start must be an exact multiple of fifteen, with zero seconds
    and zero milliseconds, or the request is refused with `ERR_SLOT_NOT_ALIGNED`."

    Design: Corner/validations/booking_with_unaligned_slot_returns_slot_not_aligned
    """
    ctx = setup_canon(12)

    response = api.create_appointment(
        create_appointment_payload(
            ctx["event_id"],
            ctx["resident_id"],
            ctx["resident"]["version"],
            [ctx["category_id"]],
            slot_start_utc="2026-09-12T09:07:00.000Z",
            declared_total_kg=8.0,
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_NOT_ALIGNED, 422)

    _, meta = validate_paginated(
        api.list_appointments(CLERK, params={"event_id": ctx["event_id"]})
    )
    assert meta["total_count"] == 0


def test_arrival_slot_at_the_closing_instant_falls_outside_the_window(api):
    """PRD §3.5: "The `slot_start_utc` must lie inside the **half-open** event
    window — at or after `window_start_utc` and strictly before `window_end_utc`, so a
    slot booked at the closing instant is refused with
    `ERR_SLOT_OUTSIDE_EVENT_WINDOW`."

    Design: Corner/validations/booking_after_window_end_returns_slot_outside_event_window
    """
    ctx = setup_canon(12)

    response = api.create_appointment(
        create_appointment_payload(
            ctx["event_id"],
            ctx["resident_id"],
            ctx["resident"]["version"],
            [ctx["category_id"]],
            slot_start_utc="2026-09-12T20:00:00.000Z",
            declared_total_kg=8.0,
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_SLOT_OUTSIDE_EVENT_WINDOW, 422)

    _, meta = validate_paginated(
        api.list_appointments(CLERK, params={"event_id": ctx["event_id"]})
    )
    assert meta["total_count"] == 0


def test_resident_may_not_act_on_another_residents_appointment(api):
    """PRD §2.1: "A `Resident` may book an appointment only for their own
    `resident_id`, and may act on an appointment only when that appointment's
    `resident_id` equals their `X-User-ID`. A mismatch is rejected with
    `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

    Design: Corner/roles/resident_cannot_cancel_another_residents_appointment
    """
    ctx = setup_canon(12)
    owner = ctx["resident"]
    appointment = book_appointment(
        ctx["event_id"],
        owner,
        [ctx["category_id"]],
        headers=make_resident_headers(owner["id"]),
        declared_total_kg=8.0,
    )

    intruder = register_resident(
        ctx["program_id"], full_name="Ben Ortiz", claimed_jurisdiction_code="CO-DEN"
    )

    response = api.appointment_transition(
        appointment["id"],
        {"action": "CANCEL", "cancel_reason": "RESIDENT_REQUEST"},
        make_resident_headers(intruder["id"]),
    )
    validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, 403)

    after = read_appointment(appointment["id"])
    assert after["status"] == "REQUESTED"
    assert after["cancel_reason"] is None


def test_booking_on_a_stale_resident_version_is_rejected_before_supersession(api):
    """PRD §2.7: "To prevent that, an appointment-creation request must carry
    `expected_resident_version` as a required, non-optional field whose value is the
    `version` of the target `Resident` row as the client last observed it. If that
    value does not equal the resident's current `version`, the request is rejected
    with `ERR_STALE_VERSION` at HTTP 412 and nothing is written."

    Design: Corner/cross_cutting_complexity_layers/appointment_create_with_stale_resident_version_returns_stale_version
    """
    ctx = setup_canon(12)
    stale_version = ctx["resident"]["version"]
    first = book_appointment(
        ctx["event_id"], ctx["resident"], [ctx["category_id"]], declared_total_kg=8.0
    )

    response = api.create_appointment(
        create_appointment_payload(
            ctx["event_id"],
            ctx["resident_id"],
            stale_version,
            [ctx["category_id"]],
            slot_start_utc="2026-09-12T09:15:00.000Z",
            declared_total_kg=9.0,
        ),
        CLERK,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION, 412)

    unchanged = read_appointment(first["id"])
    assert unchanged["status"] == "REQUESTED", "The prior booking was not superseded"
    assert unchanged["cancel_reason"] is None
    _, meta = validate_paginated(
        api.list_appointments(CLERK, params={"resident_id": ctx["resident_id"]})
    )
    assert meta["total_count"] == 1


def test_confirming_a_booking_reserves_exactly_the_declared_mass(api):
    """PRD §3.5: "On success the appointment's `reserved_kg` is set to its
    `declared_total_kg`, the resident's `annual_quantity_reserved_kg` rises by
    `declared_total_kg`, the event's `reserved_slot_count` rises by one and its
    `projected_cost_per_participant_cents` is recomputed, and the program's posture is
    recomputed."
    PRD §3.5: "`annual_quantity_reserved_kg` is the **declared** ledger: it is the
    sum of `declared_total_kg` across the resident's appointments whose status is
    `CONFIRMED`, `CHECKED_IN` or `UNLOADING`, rounded half up to three decimal
    places."

    Design: Difficulty/compensating_invariant/appointment_cancel_restores_resident_reserved_mass
    """
    ctx = setup_canon(13)
    assert ctx["resident"]["annual_quantity_reserved_kg"] == 0

    confirmed = validate_success(
        api.appointment_transition(ctx["appointment_id"], {"action": "CONFIRM"}, CLERK), 200
    )
    assert_appointment(confirmed)
    assert confirmed["status"] == "CONFIRMED"
    assert_kg(confirmed["reserved_kg"], 18.5, "reserved_kg")
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"],
        18.5,
        "annual_quantity_reserved_kg",
    )
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 1


def test_cancelling_a_confirmed_booking_gives_the_mass_back_with_no_drift(api):
    """PRD §3.5: "Cancelling from `CONFIRMED` is the compensating action for
    confirmation and must undo it in full: `reserved_kg` falls to zero, the resident's
    `annual_quantity_reserved_kg` falls by `declared_total_kg`, the event's
    `reserved_slot_count` falls by one with `projected_cost_per_participant_cents`
    recomputed, and the program's posture is recomputed."
    PRD §3.5: "`annual_quantity_settled_kg` is the **weighed** ledger: it is the sum
    of `net_weight_kg` across every dropoff line belonging to any of the resident's
    appointments whose `disposition` resolved to `ACCEPTED`, rounded half up to three
    decimal places."

    Design: Difficulty/compensating_invariant/appointment_cancel_restores_resident_reserved_mass
    """
    ctx = setup_canon(14)
    assert_kg(
        read_resident(ctx["resident_id"])["annual_quantity_reserved_kg"],
        18.5,
        "annual_quantity_reserved_kg after confirmation",
    )

    cancelled = validate_success(
        api.appointment_transition(
            ctx["appointment_id"],
            {"action": "CANCEL", "cancel_reason": "RESIDENT_REQUEST"},
            CLERK,
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "RESIDENT_REQUEST"
    assert_kg(cancelled["reserved_kg"], 0.0, "reserved_kg")

    resident = read_resident(ctx["resident_id"])
    assert_kg(resident["annual_quantity_reserved_kg"], 0.0, "annual_quantity_reserved_kg")
    assert_kg(resident["annual_quantity_settled_kg"], 0.0, "annual_quantity_settled_kg")
    assert read_event(ctx["event_id"])["reserved_slot_count"] == 0
