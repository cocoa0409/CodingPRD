"""Refurbishment scheduling: bay capacity, bay state and the re-scheduling path."""

from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import (
    ADMIN,
    BAY_CLEANING,
    BAY_REPAIR,
    STORE_ST_02,
    TECH1,
    TECH2,
    api_client,
    assert_instant,
    assert_null,
    assert_pagination_meta,
    assert_refurb_bay,
    create_refurb_bay,
    create_refurb_bay_payload,
    create_refurb_order_payload,
    create_refurb_task_payload,
    create_store_location,
    fetch_refurb_order,
    fetch_unit,
    patch_customer,
    qc_decision_payload,
    schedule_refurb_order,
    setup_accepted_trade_in,
    setup_estate,
    start_refurb_order,
    submit_refurb_qc,
    take_bay_out_of_service,
    validate_error,
    validate_paginated,
    validate_success,
)

WINDOW_08_0845 = ("2026-08-01T08:00:00Z", "2026-08-01T08:45:00Z")
WINDOW_1100_1230 = ("2026-08-01T11:00:00Z", "2026-08-01T12:30:00Z")
WINDOW_1130_1300 = ("2026-08-01T11:30:00Z", "2026-08-01T13:00:00Z")


def _estate_with_one_cleaning_bay():
    return setup_estate(bays=(BAY_CLEANING,))


def _two_units_at_one_store(estate):
    """Two accepted in-store trade-ins for the same participant, two INTAKE units."""
    first = setup_accepted_trade_in(estate)
    second = setup_accepted_trade_in(
        estate, customer=first["customer"], item_mass_grams=1300
    )
    return first["unit"], second["unit"]


def _refused_booking(unit, bay, window):
    """A create attempt that quotes the unit's currently observed version."""
    return api_client.create_refurb_order(
        create_refurb_order_payload(
            unit["id"], bay["id"], window[0], window[1], unit["version"]
        ),
        TECH1,
    )


def test_a_bay_window_that_touches_or_nearly_touches_an_existing_one_conflicts():
    """The interval is closed and inflated by the sanitation buffer.

    PRD §3.5: "And the requested window must not conflict with any other
    non-terminal order in the same bay."
    PRD §3.5: "Two windows conflict either when they overlap as closed
    intervals, endpoints included, or when the gap between them is less than a
    full hour, because the platform enforces a sixty-minute sanitation buffer
    between consecutive jobs in the same bay; a conflict is
    `ERR_BAY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/refurb_bay_window_conflict_uses_closed_interval_plus_sanitation_buffer
    """
    estate = _estate_with_one_cleaning_bay()
    bay = estate["bay"]
    first_unit, second_unit = _two_units_at_one_store(estate)

    booked = schedule_refurb_order(first_unit, bay)
    assert booked["status"] == "SCHEDULED"

    # 11:00 is the existing window's own end instant: closed, so it collides.
    validate_error(
        _refused_booking(second_unit, bay, WINDOW_1100_1230),
        "ERR_BAY_WINDOW_CONFLICT",
        409,
    )

    # A 30-minute gap is inside the sixty-minute sanitation buffer.
    validate_error(
        _refused_booking(second_unit, bay, WINDOW_1130_1300),
        "ERR_BAY_WINDOW_CONFLICT",
        409,
    )

    rows, meta = validate_paginated(
        api_client.list_refurb_orders(TECH1, {"refurb_bay_id": bay["id"]})
    )
    assert_pagination_meta(meta, 1)
    assert rows[0]["id"] == booked["id"]


def test_the_sanitation_buffer_guards_the_earlier_side_and_clears_at_sixty_minutes():
    """The tightest legal booking is exactly one hour clear of the neighbour.

    PRD §3.5: "Two windows conflict either when they overlap as closed
    intervals, endpoints included, or when the gap between them is less than a
    full hour, because the platform enforces a sixty-minute sanitation buffer
    between consecutive jobs in the same bay; a conflict is
    `ERR_BAY_WINDOW_CONFLICT`."
    PRD §3.5: "A newly scheduled order enters `SCHEDULED` with `rework_count`,
    `logged_cost_minor` and `viability_ratio_bp` all at 0,
    `performed_by_user_id`, `qc_by_user_id` and `viability_override_reason` all
    null."

    Design: Difficulty/resource_temporal_overlap/refurb_bay_window_conflict_uses_closed_interval_plus_sanitation_buffer
    """
    estate = _estate_with_one_cleaning_bay()
    bay = estate["bay"]
    first_unit, second_unit = _two_units_at_one_store(estate)

    schedule_refurb_order(first_unit, bay)

    # 08:45 sits only fifteen minutes before the 09:00 start.
    validate_error(
        _refused_booking(second_unit, bay, WINDOW_08_0845),
        "ERR_BAY_WINDOW_CONFLICT",
        409,
    )

    # 12:00 is exactly sixty minutes after the 11:00 end, which clears.
    accepted = schedule_refurb_order(
        second_unit, bay, ("2026-08-01T12:00:00Z", "2026-08-01T14:00:00Z")
    )
    assert accepted["status"] == "SCHEDULED"
    assert_instant(accepted["window_start_at"], "2026-08-01T12:00:00Z", "window_start_at")

    # The accepted create quoted the same expected version the refusals did,
    # so the three refusals consumed no concurrency token.
    _, meta = validate_paginated(
        api_client.list_refurb_orders(TECH1, {"refurb_bay_id": bay["id"]})
    )
    assert_pagination_meta(meta, 2)


def test_scheduling_is_refused_while_the_booked_bay_is_out_of_service():
    """The bay's own state gates a create on a different entity.

    PRD §3.5: "The bay must be `AVAILABLE`, otherwise
    `ERR_BAY_OUT_OF_SERVICE`."
    PRD §3.1: "A bay's `status` begins `AVAILABLE` and may be flipped to
    `OUT_OF_SERVICE`; a bay out of service cannot be booked, which surfaces as
    `ERR_BAY_OUT_OF_SERVICE`."
    PRD §3.5: "Scheduling does **not** move the unit out of `INTAKE`; it only
    books capacity."

    Design: Difficulty/cross_entity_state_dependency/refurb_scheduling_blocked_by_out_of_service_bay_state
    """
    estate = _estate_with_one_cleaning_bay()
    bay = estate["bay"]
    assert bay["status"] == "AVAILABLE"
    assert_refurb_bay(bay)
    unit = setup_accepted_trade_in(estate)["unit"]
    assert unit["lifecycle_state"] == "INTAKE"

    withdrawn = take_bay_out_of_service(bay["id"])
    assert withdrawn["status"] == "OUT_OF_SERVICE"

    validate_error(
        _refused_booking(unit, bay, ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")),
        "ERR_BAY_OUT_OF_SERVICE",
        409,
    )

    # The refused create neither bumped the unit's version nor moved it.
    after = fetch_unit(unit["id"])
    assert after["version"] == unit["version"]
    assert after["lifecycle_state"] == "INTAKE"

    _, meta = validate_paginated(
        api_client.list_refurb_orders(TECH1, {"refurb_bay_id": bay["id"]})
    )
    assert_pagination_meta(meta, 0)


def test_returning_the_bay_to_service_admits_the_identical_booking():
    """The blocked create consumed nothing, so the same body then succeeds.

    PRD §3.1: "A bay's `status` begins `AVAILABLE` and may be flipped to
    `OUT_OF_SERVICE`; a bay out of service cannot be booked, which surfaces as
    `ERR_BAY_OUT_OF_SERVICE`."
    PRD §2.8: "If that value does not equal the unit's current `version`, the
    create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD §3.5: "Scheduling does **not** move the unit out of `INTAKE`; it only
    books capacity."

    Design: Difficulty/cross_entity_state_dependency/refurb_scheduling_blocked_by_out_of_service_bay_state
    """
    estate = _estate_with_one_cleaning_bay()
    bay = estate["bay"]
    unit = setup_accepted_trade_in(estate)["unit"]

    take_bay_out_of_service(bay["id"])
    validate_error(
        _refused_booking(unit, bay, ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")),
        "ERR_BAY_OUT_OF_SERVICE",
        409,
    )

    restored = validate_success(
        api_client.patch_refurb_bay(bay["id"], {"status": "AVAILABLE"}, ADMIN)
    )
    assert restored["status"] == "AVAILABLE"

    # Same window, same expected_resale_unit_version as the refused attempt.
    order = schedule_refurb_order(unit, bay)
    assert order["status"] == "SCHEDULED"
    assert order["refurb_bay_id"] == bay["id"]

    _, meta = validate_paginated(
        api_client.list_refurb_orders(TECH1, {"refurb_bay_id": bay["id"]})
    )
    assert_pagination_meta(meta, 1)


def test_a_second_create_supersedes_the_first_order_and_locks_it_out():
    """Re-scheduling is a create, and the displaced order becomes terminal.

    PRD §3.5: "And it has one further consequence: any other order still sitting
    in `SCHEDULED` for the same unit is moved to `SUPERSEDED`, its own version is
    incremented, and the bay window it had booked is released and stops
    participating in overlap detection."
    PRD §3.5: "Starting an order whose status is neither `SCHEDULED` nor
    `QC_FAILED` is `ERR_REFURB_ORDER_NOT_STARTABLE`."
    PRD §3.5: "Submitting for quality control is again exclusive to a
    `RefurbTechnician` and moves the order from `IN_PROGRESS` to `QC_PENDING`;
    any other starting status is `ERR_REFURB_ORDER_NOT_QC_SUBMITTABLE`."
    PRD §3.5: "Effort is captured as **immutable task lines**, appended only by
    a `RefurbTechnician` and only while the order is `IN_PROGRESS`; logging
    against an order in any other status is `ERR_REFURB_ORDER_NOT_LOGGABLE`."
    PRD §3.5: "`COMPLETED`, `SALVAGED` and `SUPERSEDED` are all terminal for a
    refurbishment order."

    Design: Corner/state_machines/superseded_refurb_order_is_terminal_and_releases_its_bay_window
    """
    estate = _estate_with_one_cleaning_bay()
    bay = estate["bay"]
    unit = setup_accepted_trade_in(estate)["unit"]

    first = schedule_refurb_order(unit, bay)
    assert first["status"] == "SCHEDULED"

    # The create writes the unit, so the re-schedule quotes the fresh version.
    second = schedule_refurb_order(
        fetch_unit(unit["id"]), bay, ("2026-08-01T13:00:00Z", "2026-08-01T15:00:00Z")
    )
    assert second["status"] == "SCHEDULED"

    displaced = fetch_refurb_order(first["id"])
    assert displaced["status"] == "SUPERSEDED"
    assert displaced["version"] == first["version"] + 1

    validate_error(
        api_client.start_refurb_order(first["id"], TECH1),
        "ERR_REFURB_ORDER_NOT_STARTABLE",
        409,
    )
    validate_error(
        api_client.submit_refurb_order_qc(first["id"], TECH1),
        "ERR_REFURB_ORDER_NOT_QC_SUBMITTABLE",
        409,
    )
    validate_error(
        api_client.create_refurb_task(
            first["id"], create_refurb_task_payload("CLEANING", 10, 0), TECH1
        ),
        "ERR_REFURB_ORDER_NOT_LOGGABLE",
        409,
    )

    started = start_refurb_order(second["id"])
    assert started["status"] == "IN_PROGRESS"
    assert started["performed_by_user_id"] == "tech-001"
    assert fetch_unit(unit["id"])["lifecycle_state"] == "IN_REFURB"

    _, meta = validate_paginated(
        api_client.list_refurb_orders(
            TECH1, {"refurb_bay_id": bay["id"], "status": "SUPERSEDED"}
        )
    )
    assert_pagination_meta(meta, 1)


def test_a_stale_unit_version_refuses_the_create_and_supersedes_nothing():
    """The check exists precisely to stop a silent bay cancellation.

    PRD §2.8: "**Scheduling a refurbishment order** requires
    `expected_resale_unit_version` in the request body, carrying the `version` of
    the target resale unit as the client last observed it."
    PRD §2.8: "If that value does not equal the unit's current `version`, the
    create is rejected with `ERR_STALE_UNIT_VERSION` (HTTP 412)."
    PRD §2.8: "Without the check, a caller working from a stale view of the unit
    would cancel a bay booking it had never seen."
    PRD §3.5: "It does, however, increment the unit's version — which is
    precisely why the expected-version input exists."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_unit_version_blocks_a_silent_refurb_order_supersession
    """
    estate = setup_estate(bays=(BAY_CLEANING, BAY_REPAIR))
    first_bay, second_bay = estate["bays"]
    scenario = setup_accepted_trade_in(estate)
    unit = scenario["unit"]
    assert unit["lifecycle_state"] == "INTAKE"

    first = schedule_refurb_order(unit, first_bay)
    assert first["status"] == "SCHEDULED"
    version_after_schedule = fetch_unit(unit["id"])["version"]
    assert version_after_schedule == unit["version"] + 1

    # Quote a number that belongs to a different row entirely.
    wrong_version = patch_customer(
        scenario["customer"]["id"], {"loyalty_tier": "STANDARD"}
    )["version"]
    assert wrong_version != version_after_schedule

    validate_error(
        api_client.create_refurb_order(
            create_refurb_order_payload(
                unit["id"],
                second_bay["id"],
                "2026-08-01T09:00:00Z",
                "2026-08-01T11:00:00Z",
                wrong_version,
            ),
            TECH1,
        ),
        "ERR_STALE_UNIT_VERSION",
        412,
    )

    # The refused create superseded nothing.
    assert fetch_refurb_order(first["id"])["status"] == "SCHEDULED"

    observed_before_second = fetch_unit(unit["id"])
    second = schedule_refurb_order(
        observed_before_second,
        second_bay,
        ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z"),
    )
    assert second["status"] == "SCHEDULED"
    assert second["refurb_bay_id"] == second_bay["id"]

    displaced = fetch_refurb_order(first["id"])
    assert displaced["status"] == "SUPERSEDED"
    assert displaced["version"] == first["version"] + 1

    started = start_refurb_order(second["id"])
    assert started["status"] == "IN_PROGRESS"
    after_start = fetch_unit(unit["id"])
    assert after_start["lifecycle_state"] == "IN_REFURB"
    assert after_start["version"] > observed_before_second["version"]


def test_refurb_order_creation_accepts_only_its_five_declared_inputs():
    """Every counter and operator stamp on a new order is server-assigned.

    PRD §3.5: "The request names the unit through `resale_unit_id`, books a bay
    through `refurb_bay_id`, delimits the booking with `window_start_at` and
    `window_end_at`, and — as §2.8 requires — carries
    `expected_resale_unit_version`."
    PRD §3.5: "A newly scheduled order enters `SCHEDULED` with `rework_count`,
    `logged_cost_minor` and `viability_ratio_bp` all at 0,
    `performed_by_user_id`, `qc_by_user_id` and `viability_override_reason` all
    null."
    PRD §2.6: "Most resources — customers, condition-tier policies,
    brand-currency policies, store locations, refurbishment bays, channels,
    trade-ins, brand-currency grants, resale units, refurbishment orders,
    markdown campaigns, resale orders and diversion reports — additionally carry
    `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the
    row, and `version`, an integer that is initialized to 1 when the row is
    created and incremented by exactly one on every mutation."

    Design: Corner/entities/refurb_order_system_fields_are_not_client_settable
    """
    estate = _estate_with_one_cleaning_bay()
    unit = setup_accepted_trade_in(estate)["unit"]

    order = schedule_refurb_order(unit, estate["bay"])

    assert order["status"] == "SCHEDULED"
    assert order["rework_count"] == 0
    assert order["logged_cost_minor"] == 0
    assert order["viability_ratio_bp"] == 0
    assert_null(order["performed_by_user_id"], "performed_by_user_id")
    assert_null(order["qc_by_user_id"], "qc_by_user_id")
    assert_null(order["viability_override_reason"], "viability_override_reason")
    assert order["version"] == 1
    assert_instant(order["created_at"], "2026-08-01T00:00:00Z", "created_at")


def test_a_refurb_bay_is_created_only_under_an_existing_parent_store():
    """The nested route takes the parent from the path and scopes its listing.

    PRD §3.1: "Inside a store, a `ProgramAdmin` adds refurbishment bays; a bay
    takes its `store_location_id` from the store segment of the creation path
    rather than from the body, and carries a `code` that must be non-empty and
    unique within its own store."
    PRD §2.11: "A request for the bays of a store that does not exist reports the
    store's absence and never looks for a bay."
    PRD §3.1: "Bays within a store may be listed with optional filters on
    `bay_type` and `status` alongside the usual `limit` and `offset`."

    Design: Corner/entities/refurb_bay_requires_an_existing_parent_store_location
    """
    store_a = create_store_location()
    store_b = create_store_location(STORE_ST_02)

    validate_error(
        api_client.create_refurb_bay(
            NON_EXISTENT_UUID,
            create_refurb_bay_payload(code="BAY-X", bay_type="CLEANING"),
            ADMIN,
        ),
        "ERR_STORE_LOCATION_NOT_FOUND",
        404,
    )

    bay = create_refurb_bay(store_a["id"], BAY_CLEANING)
    assert_refurb_bay(bay)
    assert bay["store_location_id"] == store_a["id"]
    assert bay["status"] == "AVAILABLE"
    assert bay["bay_type"] == "CLEANING"

    rows, meta = validate_paginated(api_client.list_refurb_bays(store_a["id"], ADMIN))
    assert_pagination_meta(meta, 1)
    assert rows[0]["id"] == bay["id"]

    # The sub-resource route is parent-scoped, so the other store sees nothing.
    other_rows, other_meta = validate_paginated(
        api_client.list_refurb_bays(store_b["id"], ADMIN, {"bay_type": "CLEANING"})
    )
    assert_pagination_meta(other_meta, 0)
    assert other_rows == []


def test_bay_ownership_qc_sequencing_and_override_authority_all_refuse():
    """Four distinct refurbishment refusals, each reachable in its own right.

    PRD §3.5: "The bay must also belong to the very store that took physical
    custody of this unit's trade-in — booking a bay in some other store is
    `ERR_BAY_STORE_MISMATCH`."
    PRD §3.5: "The order must be `QC_PENDING`, otherwise
    `ERR_REFURB_ORDER_NOT_QC_DECIDABLE`."
    PRD §3.5: "Supplying `viability_override_reason` as a `RefurbTechnician` or a
    `MerchandisingManager` is refused with `ERR_OVERRIDE_ROLE_REQUIRED` — the
    override authority is the `ProgramAdmin`'s alone and cannot be borrowed."
    PRD §3.5: "The unit must still be in `INTAKE`; scheduling against a unit that
    has moved on is `ERR_UNIT_NOT_SCHEDULABLE`."
    PRD §3.5: "A pass moves the order to `COMPLETED`, bumps its version and
    releases the bay window."

    Design: Corner/errors/refurb_scheduling_and_qc_sequence_errors_are_triggerable
    """
    estate = _estate_with_one_cleaning_bay()
    home_bay = estate["bay"]
    other_store = create_store_location(STORE_ST_02)
    foreign_bay = create_refurb_bay(other_store["id"], BAY_CLEANING, code="BAY-X")

    unit = setup_accepted_trade_in(estate)["unit"]

    # The custody store is ST-01, so a ST-02 bay is refused outright.
    validate_error(
        _refused_booking(
            unit, foreign_bay, ("2026-08-01T09:00:00Z", "2026-08-01T11:00:00Z")
        ),
        "ERR_BAY_STORE_MISMATCH",
        409,
    )

    order = schedule_refurb_order(unit, home_bay)
    assert order["status"] == "SCHEDULED"

    # Only a QC_PENDING order can be decided.
    validate_error(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), ADMIN),
        "ERR_REFURB_ORDER_NOT_QC_DECIDABLE",
        409,
    )

    start_refurb_order(order["id"])
    submitted = submit_refurb_qc(order["id"])
    assert submitted["status"] == "QC_PENDING"
    # No task lines were logged, so the order is comfortably inside the cap.
    assert submitted["logged_cost_minor"] == 0
    assert submitted["viability_ratio_bp"] == 0

    # A technician may not borrow the override authority even when it is moot.
    # TECH2 signs, because TECH1 performed the work and §2.11 puts the
    # segregation-of-duties gate ahead of the override-privilege check.
    validate_error(
        api_client.decide_refurb_order_qc(
            order["id"],
            qc_decision_payload("PASS", "flagship refit approved verbally"),
            TECH2,
        ),
        "ERR_OVERRIDE_ROLE_REQUIRED",
        403,
    )
    assert fetch_refurb_order(order["id"])["status"] == "QC_PENDING"

    passed = validate_success(
        api_client.decide_refurb_order_qc(order["id"], qc_decision_payload("PASS"), ADMIN)
    )
    assert passed["status"] == "COMPLETED"
    assert_null(passed["viability_override_reason"], "viability_override_reason")

    ready = fetch_unit(unit["id"])
    assert ready["lifecycle_state"] == "READY"

    # Scheduling needs INTAKE, and the fresh version rules out an OCC failure.
    validate_error(
        _refused_booking(ready, home_bay, ("2026-08-02T09:00:00Z", "2026-08-02T11:00:00Z")),
        "ERR_UNIT_NOT_SCHEDULABLE",
        409,
    )
