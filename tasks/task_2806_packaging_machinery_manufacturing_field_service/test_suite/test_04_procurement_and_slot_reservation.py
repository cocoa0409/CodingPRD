"""Long-lead procurement and the reservation of a build slot.

Slots cannot be booked optimistically: purchase orders must be out, the promised
dates bound the earliest start, the line must build the right family, and the
reservation carries an optimistic-concurrency token against the order.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    PLANNER,
    ApiErrorId,
    api_client,
    assert_build_slot,
    assert_long_lead_component,
    create_build_slot_payload,
    move_clock,
    read_line,
    read_order,
    read_slot,
    seed_component,
    seed_production_line,
    setup_engineered_order,
    setup_reference_data,
)


def test_a_first_pass_slot_takes_the_requested_days_and_ends_on_the_first_free_day():
    """With no rework charged the slot length equals the request, and the interval
    is half-open so the end date is the first day the line is free again.

    PRD: "`end_date` is the `start_date` advanced by `slot_days` days, and the
    occupied interval is **half-open**: the `end_date` is the first free day and is
    not itself occupied."

    Design: Corner/calculations/slot_days_and_end_date_correct_with_zero_rework
    """
    env = setup_engineered_order(setup_reference_data(line={}))

    data = validate_success(
        api_client.create_build_slot(
            create_build_slot_payload(
                env["order"]["id"],
                env["line"]["id"],
                read_order(env["order"]["id"])["version"],
                start_date="2026-08-03",
                requested_slot_days=12,
            ),
            PLANNER,
        ),
        201,
    )

    assert data["slot_days"] == 12
    assert data["end_date"] == "2026-08-15"
    assert data["status"] == "RESERVED"
    assert data["superseded_by_slot_id"] is None
    assert_build_slot(data)
    assert read_line(env["line"]["id"])["committed_slot_days"] == 12


def test_releasing_a_purchase_order_promises_the_part_a_lead_time_after_the_clock():
    """The promised date is stamped from the logical clock at release plus the
    quoted lead time, counted as plain calendar days across the month boundary.

    PRD: "The release stamps `po_released_on` with the logical clock's UTC date and
    sets `promised_date` to that date plus `lead_time_days` days."

    Design: Corner/calculations/component_promised_date_equals_po_release_plus_lead_time
    """
    env = setup_engineered_order()
    env = seed_component(env, part_number="SERVO-3KW", lead_time_days=45)

    data = validate_success(
        api_client.release_po_long_lead_component(env["component"]["id"], PLANNER)
    )

    assert data["status"] == "ON_ORDER"
    assert data["po_released_on"] == "2026-08-01"
    assert data["promised_date"] == "2026-09-15"
    assert data["lead_time_days"] == 45
    assert_long_lead_component(data)


def test_releasing_the_same_purchase_order_twice_does_not_restamp_the_promise():
    """Release has no edge out of ON_ORDER, so the refused replay leaves both
    procurement dates exactly as the first release wrote them.

    PRD: "A transition requested from the wrong starting state is rejected with
    `ERR_INVALID_COMPONENT_STATE`."

    Design: Corner/errors/long_lead_component_release_po_twice_returns_409_invalid_component_state
    """
    env = setup_engineered_order()
    env = seed_component(env, part_number="SERVO-DRV-9", lead_time_days=45)
    validate_success(api_client.release_po_long_lead_component(env["component"]["id"], PLANNER))

    response = api_client.release_po_long_lead_component(env["component"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_INVALID_COMPONENT_STATE.value, 409)
    after = validate_success(
        api_client.get_long_lead_component(env["component"]["id"], PLANNER)
    )
    assert after["status"] == "ON_ORDER"
    assert after["po_released_on"] == "2026-08-01"
    assert after["promised_date"] == "2026-09-15"


def test_a_part_cannot_be_booked_in_before_its_promised_date_arrives():
    """Receipt waits for the logical clock to reach the promise, and once the clock
    is moved to that exact date the identical receipt is accepted.

    PRD: "Booking the part into the factory moves the line from `ON_ORDER` to
    `RECEIVED` and increments its `version` by 1, but only once the logical clock's
    UTC date has reached the `promised_date`; an early receipt is refused with
    `ERR_COMPONENT_NOT_DUE`, and the comparison is inclusive, so receipt exactly on
    the promised date is accepted."

    Design: Corner/errors/long_lead_component_receive_before_promised_date_returns_422_not_due
    """
    env = setup_engineered_order()
    env = seed_component(env, part_number="SERVO-DRV-9", lead_time_days=45)
    validate_success(api_client.release_po_long_lead_component(env["component"]["id"], PLANNER))

    response = api_client.receive_long_lead_component(env["component"]["id"], PLANNER)

    validate_error(response, ApiErrorId.ERR_COMPONENT_NOT_DUE.value, 422)
    assert (
        validate_success(api_client.get_long_lead_component(env["component"]["id"], PLANNER))[
            "status"
        ]
        == "ON_ORDER"
    )
    move_clock("2026-09-15T00:00:00Z")
    received = validate_success(
        api_client.receive_long_lead_component(env["component"]["id"], PLANNER)
    )
    assert received["status"] == "RECEIVED"


def test_a_start_date_exactly_on_the_earliest_permissible_start_is_accepted():
    """The earliest-start comparison is inclusive, so a build may begin on the very
    day the last promised part is due.

    PRD: "A `start_date` earlier than that is refused with
    `ERR_SLOT_BEFORE_COMPONENTS`, and the comparison is inclusive, so a start date
    exactly equal to the earliest permissible start is accepted."

    Design: Corner/validations/build_slot_start_date_exactly_on_earliest_start_is_accepted
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    env = seed_component(env, part_number="SERVO-3KW", lead_time_days=10)
    promised = validate_success(
        api_client.release_po_long_lead_component(env["component"]["id"], PLANNER)
    )["promised_date"]
    assert promised == "2026-08-11"
    move_clock("2026-08-11T00:00:00Z")
    received = validate_success(
        api_client.receive_long_lead_component(env["component"]["id"], PLANNER)
    )
    assert received["status"] == "RECEIVED"

    data = validate_success(
        api_client.create_build_slot(
            create_build_slot_payload(
                env["order"]["id"],
                env["line"]["id"],
                read_order(env["order"]["id"])["version"],
                start_date="2026-08-11",
                requested_slot_days=10,
            ),
            PLANNER,
        ),
        201,
    )

    assert data["start_date"] == "2026-08-11"
    assert data["slot_days"] == 10
    assert data["end_date"] == "2026-08-21"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 10


def test_a_reservation_is_visible_on_the_line_ledger_in_the_very_next_request():
    """The reservation's effect on the committed-days ledger needs no settling
    step: the create response already carries the derived interval and the next
    read of the line agrees with it.

    PRD: "The line's `committed_slot_days` is then re-derived — the new slot enters
    the committed set and the superseded one leaves it."

    Design: Corner/consistency_model/build_slot_create_is_immediately_visible_on_line_read
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    validate_success(
        api_client.commercial_advance_machine_order(env["order"]["id"], "PO_RECEIVED", ADMIN)
    )

    data = validate_success(
        api_client.create_build_slot(
            create_build_slot_payload(
                env["order"]["id"],
                env["line"]["id"],
                read_order(env["order"]["id"])["version"],
                start_date="2026-08-06",
                requested_slot_days=20,
            ),
            PLANNER,
        ),
        201,
    )

    assert data["status"] == "RESERVED"
    assert data["slot_days"] == 20
    assert data["end_date"] == "2026-08-26"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20
    assert read_slot(data["id"])["status"] == "RESERVED"


def test_a_reservation_pinned_to_a_superseded_order_version_is_rejected():
    """The money-track advance bumped the order's version, so the planner's token
    is stale, nothing is booked, and the retry with the refreshed token succeeds.

    PRD: "If that value does not equal the order's current `version`, the
    reservation is rejected with `ERR_STALE_ORDER_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/build_slot_create_with_stale_order_version_returns_412
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    stale_version = read_order(env["order"]["id"])["version"]
    validate_success(
        api_client.commercial_advance_machine_order(env["order"]["id"], "PO_RECEIVED", ADMIN)
    )
    payload = create_build_slot_payload(
        env["order"]["id"],
        env["line"]["id"],
        stale_version,
        start_date="2026-08-06",
        requested_slot_days=20,
    )

    response = api_client.create_build_slot(payload, PLANNER)

    validate_error(response, ApiErrorId.ERR_STALE_ORDER_VERSION.value, 412)
    fresh_version = read_order(env["order"]["id"])["version"]
    assert fresh_version == stale_version + 1
    assert read_line(env["line"]["id"])["committed_slot_days"] == 0
    _, meta = validate_paginated(
        api_client.list_build_slots(PLANNER, params={"machine_order_id": env["order"]["id"]})
    )
    assert meta["total_count"] == 0
    payload["expected_machine_order_version"] = fresh_version
    validate_success(api_client.create_build_slot(payload, PLANNER), 201)


def test_one_unreleased_purchase_order_blocks_slotting_altogether():
    """A single procurement line still sitting in planning stops the reservation
    even though the line is open, the family matches and capacity is free.

    PRD: "No procurement line of the order may still be `PLANNED` — every purchase
    order must already be out — and a lingering planned line is refused with
    `ERR_COMPONENT_PO_NOT_RELEASED`."

    Design: Corner/errors/build_slot_create_with_planned_component_returns_409_po_not_released
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    env = seed_component(env, part_number="SERVO-DRV-9", lead_time_days=45)

    response = api_client.create_build_slot(
        create_build_slot_payload(
            env["order"]["id"],
            env["line"]["id"],
            read_order(env["order"]["id"])["version"],
            start_date="2026-10-01",
            requested_slot_days=20,
        ),
        PLANNER,
    )

    validate_error(response, ApiErrorId.ERR_COMPONENT_PO_NOT_RELEASED.value, 409)
    assert (
        validate_success(api_client.get_long_lead_component(env["component"]["id"], PLANNER))[
            "status"
        ]
        == "PLANNED"
    )
    assert read_line(env["line"]["id"])["committed_slot_days"] == 0


def test_a_capper_line_cannot_be_booked_for_a_filler_machine():
    """The line builds exactly one machine family, so a family mismatch is refused
    even when every other reservation guard is satisfied.

    PRD: "The order must be `ENGINEERED` (`ERR_ORDER_NOT_ENGINEERED`), the line
    must be `OPEN`, and the line's `machine_family` must equal the machine family of
    the order's model, or the reservation is refused with
    `ERR_LINE_FAMILY_MISMATCH`."

    Design: Corner/errors/build_slot_create_on_capper_line_returns_422_line_family_mismatch
    """
    env = setup_engineered_order()
    capper_line = seed_production_line(line_code="LINE-C", machine_family="CAPPER")

    response = api_client.create_build_slot(
        create_build_slot_payload(
            env["order"]["id"],
            capper_line["id"],
            read_order(env["order"]["id"])["version"],
            start_date="2026-08-06",
            requested_slot_days=20,
        ),
        PLANNER,
    )

    validate_error(response, ApiErrorId.ERR_LINE_FAMILY_MISMATCH.value, 422)
    assert read_line(capper_line["id"])["committed_slot_days"] == 0
    _, meta = validate_paginated(
        api_client.list_build_slots(PLANNER, params={"machine_order_id": env["order"]["id"]})
    )
    assert meta["total_count"] == 0


def test_component_read_with_unknown_id_reports_the_component_not_found_code():
    """The procurement read reports the component's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/long_lead_component_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_long_lead_component(
        "66666666-6666-4666-8666-666666666666", PLANNER
    )

    validate_error(response, ApiErrorId.ERR_COMPONENT_NOT_FOUND.value, 404)


def test_slot_read_with_unknown_id_reports_the_slot_not_found_code():
    """The schedule read reports the slot's own miss code.

    PRD: "Each miss reports that entity's own not-found code:
    `ERR_CUSTOMER_NOT_FOUND`, `ERR_MACHINE_MODEL_NOT_FOUND`,
    `ERR_PRODUCT_TRIAL_NOT_FOUND`, `ERR_MACHINE_ORDER_NOT_FOUND`,
    `ERR_PRODUCTION_LINE_NOT_FOUND`, `ERR_BUILD_SLOT_NOT_FOUND`,
    `ERR_COMPONENT_NOT_FOUND`, `ERR_ACCEPTANCE_TEST_NOT_FOUND`,
    `ERR_INSTALLED_MACHINE_NOT_FOUND`, `ERR_FORMAT_KIT_NOT_FOUND`,
    `ERR_SERVICE_CONTRACT_NOT_FOUND`, `ERR_FIELD_ENGINEER_NOT_FOUND`,
    `ERR_PM_VISIT_NOT_FOUND`, `ERR_WARRANTY_CLAIM_NOT_FOUND`,
    `ERR_CLAIM_LINE_NOT_FOUND`, `ERR_STOCKING_RECOMMENDATION_NOT_FOUND` — each
    with HTTP 404."

    Design: Corner/errors/build_slot_get_unknown_id_returns_404_not_found
    """
    response = api_client.get_build_slot("55555555-5555-4555-8555-555555555555", PLANNER)

    validate_error(response, ApiErrorId.ERR_BUILD_SLOT_NOT_FOUND.value, 404)
