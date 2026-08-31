"""Lab-packing weighed lines into compatibility-segregated drums, the container
estimate, sealing against budget authority and the compensating unseal."""

from test_helpers import (
    CONTRACTOR,
    CONTRACTOR_USER_ID,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_kg,
    assert_packed_container,
    container_action,
    create_event,
    open_container,
    read_container,
    read_dropoff_line,
    read_event,
    read_program,
    setup_canon,
    validate_error,
    validate_success,
)


def test_get_container_with_unknown_id_returns_container_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_container_with_unknown_id_returns_container_not_found
    """
    response = api.get_container(NON_EXISTENT_UUID, CONTRACTOR)
    validate_error(response, ApiErrorId.ERR_CONTAINER_NOT_FOUND, 404)


def test_packing_a_line_that_will_not_fit_is_refused(api):
    """PRD §3.8: "And the container must have room: its current `net_weight_kg` plus
    the line's `net_weight_kg` must be no greater than its `capacity_kg`, or the
    request is refused with `ERR_CONTAINER_CAPACITY_EXCEEDED`. A line that lands
    exactly on capacity is accepted."

    Design: Corner/validations/pack_line_into_undersized_container_returns_capacity_exceeded
    """
    ctx = setup_canon(19, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    assert ctx["lines"][0]["disposition"] == "ACCEPTED"
    container = open_container(
        ctx["event_id"], container_code="TINY-A1", capacity_kg=1.0
    )

    response = api.pack_line(
        container["id"], {"dropoff_line_id": ctx["lines"][0]["id"]}, CONTRACTOR
    )
    validate_error(response, ApiErrorId.ERR_CONTAINER_CAPACITY_EXCEEDED, 422)

    after = read_container(container["id"])
    assert after["line_count"] == 0
    assert_kg(after["net_weight_kg"], 0.0, "net_weight_kg")
    assert read_dropoff_line(ctx["lines"][0]["id"])["container_id"] is None


def test_a_line_can_only_be_drummed_once(api):
    """PRD §3.8: "The line must be unpacked and accepted — its `container_id` still
    null and its `disposition` exactly `ACCEPTED` — or the request is refused with
    `ERR_LINE_ALREADY_PACKED`, which is therefore also the code a rejected or
    referred-out line earns when someone tries to drum it."
    PRD §3.8: "On success the line's `container_id` is set and the container's
    `line_count`, `net_weight_kg` and `estimated_disposal_cost_cents` are recomputed,
    with the container's `version` incrementing by one."

    Design: Corner/validations/pack_same_line_twice_returns_line_already_packed
    """
    ctx = setup_canon(24, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    first_container = ctx["container"]
    assert first_container["line_count"] == 1
    assert_kg(first_container["net_weight_kg"], 1.5, "net_weight_kg")
    assert first_container["estimated_disposal_cost_cents"] == 233

    second_container = open_container(ctx["event_id"], container_code="DRUM-A2")
    response = api.pack_line(
        second_container["id"], {"dropoff_line_id": ctx["lines"][0]["id"]}, CONTRACTOR
    )
    validate_error(response, ApiErrorId.ERR_LINE_ALREADY_PACKED, 409)

    after = read_container(second_container["id"])
    assert after["line_count"] == 0
    assert_kg(after["net_weight_kg"], 0.0, "net_weight_kg")
    assert read_dropoff_line(ctx["lines"][0]["id"])["container_id"] == first_container["id"]


def test_packing_a_line_from_another_event_is_refused(api):
    """PRD §3.8: "The appointment behind the line must belong to the same event as
    the container, or the request is refused with `ERR_CONTAINER_EVENT_MISMATCH`."

    Design: Corner/validations/pack_line_from_another_event_returns_container_event_mismatch
    """
    ctx = setup_canon(19, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    other_event = create_event(
        ctx["program_id"],
        ctx["site_id"],
        window_start_utc="2026-10-10T08:00:00.000Z",
        window_end_utc="2026-10-10T20:00:00.000Z",
    )
    foreign_container = open_container(
        other_event["id"], container_code="DRUM-T2", compatibility_class="TOXIC"
    )

    response = api.pack_line(
        foreign_container["id"], {"dropoff_line_id": ctx["lines"][0]["id"]}, CONTRACTOR
    )
    validate_error(response, ApiErrorId.ERR_CONTAINER_EVENT_MISMATCH, 409)

    assert read_dropoff_line(ctx["lines"][0]["id"])["container_id"] is None
    assert read_container(foreign_container["id"])["line_count"] == 0


def test_sealing_beyond_the_budget_authority_is_refused_with_payment_required(api):
    """PRD §3.8: "It requires that the container holds at least one line, that the
    program is not frozen, and that the program can afford it — the sum of
    `budget_encumbered_cents`, `budget_in_transit_cents`, `budget_spent_cents` and
    this container's `estimated_disposal_cost_cents` must be no greater than the
    program's `budget_cents`, or the request is refused with
    `ERR_PROGRAM_BUDGET_EXCEEDED` at HTTP 402."

    Design: Corner/validations/seal_container_over_program_budget_returns_payment_required
    """
    ctx = setup_canon(
        24,
        program={"name": "Shoestring HHW Program", "budget_cents": 100},
        line_weights=(1.5,),
        appointment={"declared_total_kg": 6.0},
    )
    assert ctx["container"]["estimated_disposal_cost_cents"] == 233

    response = api.container_transition(
        ctx["container_id"], {"action": "SEAL"}, CONTRACTOR
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_BUDGET_EXCEEDED, 402)

    container = read_container(ctx["container_id"])
    assert container["status"] == "OPEN"
    assert container["sealed_by_user_id"] is None

    program = read_program(ctx["program_id"])
    assert program["budget_encumbered_cents"] == 0
    assert program["posture"] == "OPEN"


def test_unsealing_returns_the_encumbrance_with_zero_drift(api):
    """PRD §3.8: "On success `sealed_by_user_id` is stamped from the acting
    contractor's `X-User-ID`, the container's `estimated_disposal_cost_cents` is added
    to the program's `budget_encumbered_cents`, and the program's posture is
    recomputed."
    PRD §3.8: "Unsealing moves `SEALED → OPEN` and is its compensating action. It is
    permitted only while the container's `manifest_id` is null — a drum already listed
    on a manifest cannot be reopened. On success `sealed_by_user_id` is cleared to null
    and the container's `estimated_disposal_cost_cents` is subtracted from
    `budget_encumbered_cents`, with the posture recomputed."

    Design: Corner/state_machines/unseal_container_returns_budget_encumbrance
    """
    ctx = setup_canon(24, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    assert ctx["container"]["estimated_disposal_cost_cents"] == 233

    sealed = validate_success(
        api.container_transition(ctx["container_id"], {"action": "SEAL"}, CONTRACTOR), 200
    )
    assert_packed_container(sealed)
    assert sealed["status"] == "SEALED"
    assert sealed["sealed_by_user_id"] == CONTRACTOR_USER_ID
    assert read_program(ctx["program_id"])["budget_encumbered_cents"] == 233

    unsealed = container_action(ctx["container_id"], "UNSEAL")
    assert unsealed["status"] == "OPEN"
    assert unsealed["sealed_by_user_id"] is None
    assert unsealed["line_count"] == 1
    assert_kg(unsealed["net_weight_kg"], 1.5, "net_weight_kg")

    assert read_program(ctx["program_id"])["budget_encumbered_cents"] == 0
    assert read_dropoff_line(ctx["lines"][0]["id"])["container_id"] == ctx["container_id"]


def test_incompatible_class_is_reported_ahead_of_the_cross_event_mismatch(api):
    """PRD §3.8: "The line's material category must carry the same
    `compatibility_class` as the container, or the request is refused with
    `ERR_INCOMPATIBLE_MATERIAL_CLASS` — acid never goes in the flammables drum."
    PRD §2.5: "Compatibility class match when packing a line — otherwise
    `ERR_INCOMPATIBLE_MATERIAL_CLASS` (HTTP 422)."
    PRD §2.5: "Same-event referential integrity for packing and manifesting —
    otherwise `ERR_CONTAINER_EVENT_MISMATCH` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_incompatible_cross_event_pack
    """
    ctx = setup_canon(19, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    assert ctx["lines"][0]["disposition"] == "ACCEPTED"
    other_event = create_event(
        ctx["program_id"],
        ctx["site_id"],
        window_start_utc="2026-10-10T08:00:00.000Z",
        window_end_utc="2026-10-10T20:00:00.000Z",
    )
    flammables_drum = open_container(
        other_event["id"], container_code="DRUM-F1", compatibility_class="FLAMMABLE",
        capacity_kg=100.0,
    )

    response = api.pack_line(
        flammables_drum["id"], {"dropoff_line_id": ctx["lines"][0]["id"]}, CONTRACTOR
    )
    validate_error(response, ApiErrorId.ERR_INCOMPATIBLE_MATERIAL_CLASS, 422)


def test_the_pre_empted_cross_event_pack_writes_nothing(api):
    """PRD §2.5: "The rules below are evaluated in ascending priority order and the
    **first** rule that fails decides the response; no later rule is consulted, and no
    partial write occurs."
    PRD §3.8: "On success the line's `container_id` is set and the container's
    `line_count`, `net_weight_kg` and `estimated_disposal_cost_cents` are recomputed,
    with the container's `version` incrementing by one."

    Design: Difficulty/priority_pair_validation_conflict/safety_beats_referential_on_incompatible_cross_event_pack
    """
    ctx = setup_canon(19, line_weights=(1.5,), appointment={"declared_total_kg": 6.0})
    other_event = create_event(
        ctx["program_id"],
        ctx["site_id"],
        window_start_utc="2026-10-10T08:00:00.000Z",
        window_end_utc="2026-10-10T20:00:00.000Z",
    )
    flammables_drum = open_container(
        other_event["id"], container_code="DRUM-F1", compatibility_class="FLAMMABLE",
        capacity_kg=100.0,
    )

    response = api.pack_line(
        flammables_drum["id"], {"dropoff_line_id": ctx["lines"][0]["id"]}, CONTRACTOR
    )
    validate_error(response, ApiErrorId.ERR_INCOMPATIBLE_MATERIAL_CLASS, 422)

    assert read_dropoff_line(ctx["lines"][0]["id"])["container_id"] is None
    drum = read_container(flammables_drum["id"])
    assert drum["line_count"] == 0
    assert_kg(drum["net_weight_kg"], 0.0, "net_weight_kg")
    assert read_event(other_event["id"])["lifecycle_status"] == "PLANNED"
