"""Loaner pool selection, occupancy geometry and rental billing."""

from test_helpers import (
    ApiErrorId,
    assert_loaner_assignment,
    assert_timestamp_equals,
    assign_work_order,
    bootstrap_monitor_campus,
    bootstrap_monitor_campus_with_pool,
    count_available_pool_units,
    create_device,
    create_loaner_assignment,
    intake_work_order,
    read_device,
    read_loaner_assignment,
    read_work_order,
    return_loaner_assignment,
    set_clock,
    set_security_state,
    setup_networked_pool_unit_unassessed,
    setup_pool_unit_after_one_returned_occupancy,
    setup_quarantined_pool_unit_scene,
    setup_rental_loaner_on_critical_unit,
    setup_two_pool_units_awaiting_selection,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_version,
)
from test_helpers.factories import MONITOR_UNIT


def test_returning_an_already_returned_loaner_is_rejected(api, ce_manager_headers):
    """PRD §3.6: "Return is accepted only from `DEPLOYED`; anything else reports
    `ERR_INVALID_LOANER_STATE`."
    PRD §3.6: "The system stamps `returned_at` from the logical clock and derives
    `billable_days` as the elapsed seconds from `start_at` to `returned_at` divided by 86,400
    and rounded **up** to a whole number, with a floor of 1 — any return, however prompt,
    bills at least one day."

    Design: Corner/state_machines/loaner_return_twice_returns_invalid_loaner_state
    """
    scene = bootstrap_monitor_campus_with_pool()
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Battery will not hold charge")
    assigned = assign_work_order(order["id"])
    loaner = create_loaner_assignment(order["id"], expected_version=assigned["version"],
                                      loaner_device_id=scene["pool_device"]["id"])
    set_clock("2026-08-04T00:00:00Z")
    return_loaner_assignment(loaner["id"])

    response = api.return_loaner_assignment(loaner["id"], ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_LOANER_STATE.value, 409)

    after = read_loaner_assignment(loaner["id"])
    assert after["status"] == "RETURNED"
    assert after["billable_days"] == 3
    assert read_device(scene["pool_device"]["id"])["operational_state"] == "IN_SERVICE"


def test_naming_a_unit_outside_the_pool_is_rejected(api, ce_manager_headers):
    """PRD §3.6: "First, the named unit must have `is_loaner_pool` set to `true`, must sit at
    the same `facility_id` as the downed unit, and must be on the same `device_model_id`; and
    a `RENTAL`-sourced assignment must not name a `loaner_device_id` at all, since a rental
    unit is external and has no inventory row. Any of those failures yields
    `ERR_LOANER_NOT_IN_POOL`."

    Design: Corner/validations/loaner_named_device_outside_pool_returns_not_in_pool
    """
    scene = bootstrap_monitor_campus()
    spare = create_device(scene["facility"]["id"], scene["department"]["id"],
                          scene["model"]["id"], MONITOR_UNIT,
                          serial_number="SN-2009", acquisition_date="2023-01-10",
                          acquisition_cost_cents=1_450_000, condition_score=2)
    order = intake_work_order(scene["device"]["id"], problem_summary="Waveform artefact")
    assigned = assign_work_order(order["id"])

    response = api.create_loaner_assignment(
        {"work_order_id": order["id"], "source": "POOL", "loaner_device_id": spare["id"],
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": assigned["version"]},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_LOANER_NOT_IN_POOL.value, 422)

    after_spare = read_device(spare["id"])
    assert after_spare["operational_state"] == "IN_SERVICE"
    assert after_spare["is_loaner_pool"] is False
    assert read_work_order(order["id"])["loaner_status"] == "NONE"


def test_networked_pool_unit_needs_a_cleared_security_state(api, ce_manager_headers):
    """PRD §3.6: "Second, when the named unit's catalogue model has `is_network_connected` set
    to `true`, that unit's `security_state` must be `ASSESSED_OK` or `REMEDIATED`; anything
    else yields `ERR_LOANER_SECURITY_INELIGIBLE` — an unassessed networked pump does not go to
    a bedside as a substitute."
    PRD §3.6: "A `POOL` assignment, however selected, moves the lending unit `IN_SERVICE` →
    `ON_LOAN`."

    Design: Corner/validations/loaner_network_connected_model_requires_security_clearance
    """
    scene = setup_networked_pool_unit_unassessed()
    order_id = scene["work_order"]["id"]
    pool_id = scene["pool_device"]["id"]

    blocked = api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL", "loaner_device_id": pool_id,
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": scene["work_order"]["version"]},
        ce_manager_headers,
    )
    validate_error(blocked, ApiErrorId.ERR_LOANER_SECURITY_INELIGIBLE.value, 422)
    assert read_device(pool_id)["operational_state"] == "IN_SERVICE"

    set_security_state(pool_id, "ASSESSED_OK")
    response = api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL", "loaner_device_id": pool_id,
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": work_order_version(order_id)},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert_loaner_assignment(data)
    assert data["status"] == "DEPLOYED"
    assert read_device(pool_id)["operational_state"] == "ON_LOAN"
    assert read_work_order(order_id)["loaner_status"] == "COVERED"


def test_an_empty_candidate_pool_is_reported_rather_than_silently_uncovered(api,
                                                                           ce_manager_headers):
    """PRD §3.6: "When the filter admits nobody, the request is rejected with
    `ERR_NO_LOANER_AVAILABLE` — the hospital would rather be told it has no spare than be given
    an ineligible one."

    Design: Corner/validations/loaner_empty_candidate_pool_returns_no_loaner_available
    """
    scene = bootstrap_monitor_campus()
    order = intake_work_order(scene["device"]["id"], problem_summary="No spare available")
    assigned = assign_work_order(order["id"])

    response = api.create_loaner_assignment(
        {"work_order_id": order["id"], "source": "POOL",
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": assigned["version"]},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_NO_LOANER_AVAILABLE.value, 409)

    assert read_work_order(order["id"])["loaner_status"] == "NONE"
    listed, _ = validate_paginated(
        api.list_loaner_assignments(ce_manager_headers,
                                    params={"work_order_id": order["id"]})
    )
    assert listed == [], "A rejected loaner create must not persist an assignment"


def test_a_unit_already_on_loan_is_unavailable_even_for_a_disjoint_interval(api,
                                                                           ce_manager_headers):
    """PRD §3.6: "Third, the named unit's `operational_state` must be `IN_SERVICE` and its
    `recall_hold` must be `false`, failing which the response is `ERR_LOANER_UNAVAILABLE`."
    PRD §2.11: "On loaner creation, six loaner-specific checks fire in the sequence pool
    membership, cyber eligibility, availability, occupancy overlap, empty candidate set, budget
    hold — so a unit that is both outside the pool and already occupied reports
    `ERR_LOANER_NOT_IN_POOL`, not the interval conflict."

    Design: Corner/validations/loaner_named_unit_already_on_loan_returns_unavailable
    """
    scene = bootstrap_monitor_campus_with_pool()
    second_device = create_device(scene["facility"]["id"], scene["department"]["id"],
                                  scene["model"]["id"], MONITOR_UNIT,
                                  serial_number="SN-2004")
    order_a = intake_work_order(scene["device"]["id"], problem_summary="Fault on unit A")
    assigned_a = assign_work_order(order_a["id"])
    loaner_a = create_loaner_assignment(order_a["id"], expected_version=assigned_a["version"],
                                        loaner_device_id=scene["pool_device"]["id"],
                                        start_at="2026-08-01T00:00:00Z",
                                        end_at="2026-08-05T00:00:00Z")
    order_b = intake_work_order(second_device["id"], problem_summary="Fault on unit B")
    assigned_b = assign_work_order(order_b["id"])

    response = api.create_loaner_assignment(
        {"work_order_id": order_b["id"], "source": "POOL",
         "loaner_device_id": scene["pool_device"]["id"],
         "start_at": "2026-08-10T00:00:00Z", "end_at": "2026-08-12T00:00:00Z",
         "expected_work_order_version": assigned_b["version"]},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_LOANER_UNAVAILABLE.value, 409)

    assert read_device(scene["pool_device"]["id"])["operational_state"] == "ON_LOAN"
    assert read_loaner_assignment(loaner_a["id"])["status"] == "DEPLOYED"
    assert read_work_order(order_b["id"])["loaner_status"] == "NONE"


def test_rental_return_rounds_each_billable_day_before_summing(api, ce_manager_headers):
    """PRD §3.6: "The total is then accumulated over the billable days in a pinned order: for
    each day, numbered 1 through `billable_days`, take the base daily charge multiplied by one
    plus the surcharge rate; if that day's number is greater than 7, multiply the result by one
    minus a long-term discount of ten percent; round that day's charge half up to whole cents;
    and add it to the running total."
    PRD §3.6: "Rounding happens **per day, before summation** — summing the exact per-day
    rationals and rounding once at the end is the wrong order and produces a different cent
    figure."

    Design: Difficulty/combinatorial_formula/loaner_rental_rounds_each_day_before_summing
    """
    scene = setup_rental_loaner_on_critical_unit()
    set_clock("2026-08-11T00:00:00Z")

    data = validate_success(
        api.return_loaner_assignment(scene["loaner"]["id"], ce_manager_headers), 200
    )
    assert_loaner_assignment(data)
    assert data["status"] == "RETURNED"
    assert data["billable_days"] == 10
    assert data["rental_cost_cents"] == 295037, (
        f"Seven days at 30416 plus three discounted days at 27375 is 295037; "
        f"got {data['rental_cost_cents']}"
    )
    assert data["rental_cost_cents"] != 295038, (
        "295038 is the figure produced by summing exact rationals and rounding once"
    )


def test_rental_surcharge_is_read_from_the_downed_unit(api, ce_manager_headers):
    """PRD §3.6: "A risk surcharge is read from the **downed** unit's `risk_class`, never from
    the substitute's: twenty-five percent for a `CRITICAL` unit, fifteen percent for a `HIGH`
    unit, five percent for a `MEDIUM` unit and nothing for a `LOW` one."
    PRD §3.6: "The base daily charge is 24,333 cents."

    Design: Difficulty/combinatorial_formula/loaner_rental_rounds_each_day_before_summing
    """
    scene = setup_rental_loaner_on_critical_unit()
    assert read_device(scene["device"]["id"])["risk_class"] == "CRITICAL"
    set_clock("2026-08-11T00:00:00Z")

    return_loaner_assignment(scene["loaner"]["id"])
    loaner = read_loaner_assignment(scene["loaner"]["id"])

    # 24333 * 1.25 = 30416.25 -> 30416 per undiscounted day.
    assert loaner["rental_cost_cents"] == 295037
    assert loaner["billable_days"] == 10


def test_a_quarantined_pool_unit_cannot_be_lent_out(api, ce_manager_headers):
    """PRD §2.11: "Quarantine safety — `ERR_DEVICE_QUARANTINED` (HTTP 422) when the device
    under service is quarantined, and, on loaner creation, when the named loaner unit's
    `security_state` is `VULNERABLE` or `QUARANTINED`. This guards PM completion, loaner
    creation and work-order close."

    Design: Difficulty/cross_entity_state_dependency/loaner_creation_gated_by_pool_device_security_state
    """
    scene = setup_quarantined_pool_unit_scene()

    response = api.create_loaner_assignment(
        {"work_order_id": scene["work_order"]["id"], "source": "POOL",
         "loaner_device_id": scene["pool_device"]["id"],
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": scene["work_order"]["version"]},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_DEVICE_QUARANTINED.value, 422)

    pool = read_device(scene["pool_device"]["id"])
    assert pool["security_state"] == "QUARANTINED"
    assert pool["operational_state"] == "DOWN"


def test_a_rejected_loaner_leaves_the_order_uncovered(api, ce_manager_headers):
    """PRD §3.6: "The assignment is created with `status` `DEPLOYED`, `returned_at` null,
    `billable_days` 0 and `rental_cost_cents` 0, the covered order's `loaner_status` becomes
    `COVERED`, and the order's `version` increments by 1."
    PRD §3.8: "A device whose `operational_state` is `IN_SERVICE` or `ON_LOAN` is taken to
    `DOWN`."

    Design: Difficulty/cross_entity_state_dependency/loaner_creation_gated_by_pool_device_security_state
    """
    scene = setup_quarantined_pool_unit_scene()
    order_id = scene["work_order"]["id"]

    api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL",
         "loaner_device_id": scene["pool_device"]["id"],
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": scene["work_order"]["version"]},
        ce_manager_headers,
    )

    assert read_work_order(order_id)["loaner_status"] == "NONE"
    listed, meta = validate_paginated(
        api.list_loaner_assignments(ce_manager_headers, params={"work_order_id": order_id})
    )
    assert listed == [], "No assignment may be recorded for a rejected loaner request"
    assert meta["total_count"] == 0


def test_an_assignment_starting_at_the_prior_return_instant_is_accepted(api, ce_manager_headers):
    """PRD §3.6: "**Occupancy is half-open.** The requested interval runs from `start_at` up
    to but not including `end_at`, and each existing assignment on the same loaner unit whose
    `status` is `DEPLOYED` or `RETURNED` occupies the interval from its own `start_at` up to
    but not including its `returned_at` if it has one, or its `end_at` if it has not."
    PRD §3.6: "Two intervals that merely touch — one ending exactly where the next begins — do
    **not** overlap."

    Design: Difficulty/resource_temporal_overlap/loaner_half_open_interval_adjacency_versus_overlap
    """
    scene = setup_pool_unit_after_one_returned_occupancy()
    order_id = scene["work_order"]["id"]

    response = api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL",
         "loaner_device_id": scene["pool_device"]["id"],
         "start_at": "2026-08-05T08:00:00Z", "end_at": "2026-08-07T08:00:00Z",
         "expected_work_order_version": work_order_version(order_id)},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert data["status"] == "DEPLOYED"


def test_an_assignment_starting_inside_a_prior_occupancy_conflicts(api, ce_manager_headers):
    """PRD §3.6: "A genuine intersection is rejected with `ERR_LOANER_INTERVAL_CONFLICT`."
    PRD §3.6: "**Occupancy is half-open.** The requested interval runs from `start_at` up to
    but not including `end_at`, and each existing assignment on the same loaner unit whose
    `status` is `DEPLOYED` or `RETURNED` occupies the interval from its own `start_at` up to
    but not including its `returned_at` if it has one, or its `end_at` if it has not."

    Design: Difficulty/resource_temporal_overlap/loaner_half_open_interval_adjacency_versus_overlap
    """
    scene = setup_pool_unit_after_one_returned_occupancy()
    order_id = scene["work_order"]["id"]
    pool_id = scene["pool_device"]["id"]

    second = create_loaner_assignment(order_id, expected_version=work_order_version(order_id),
                                      loaner_device_id=pool_id,
                                      start_at="2026-08-05T08:00:00Z",
                                      end_at="2026-08-07T08:00:00Z")
    set_clock("2026-08-07T08:00:00Z")
    return_loaner_assignment(second["id"])

    response = api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL", "loaner_device_id": pool_id,
         "start_at": "2026-08-04T00:00:00Z", "end_at": "2026-08-06T00:00:00Z",
         "expected_work_order_version": work_order_version(order_id)},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_LOANER_INTERVAL_CONFLICT.value, 409)

    listed, meta = validate_paginated(
        api.list_loaner_assignments(ce_manager_headers,
                                    params={"loaner_device_id": pool_id})
    )
    assert len(listed) == 2, f"Expected exactly 2 recorded occupancies, got {len(listed)}"
    assert meta["total_count"] == 2
    assert read_device(pool_id)["operational_state"] == "IN_SERVICE"


def test_a_returned_pool_occupancy_ends_at_its_return_instant(api, ce_manager_headers):
    """PRD §3.6: "The system stamps `returned_at` from the logical clock and derives
    `billable_days` as the elapsed seconds from `start_at` to `returned_at` divided by 86,400
    and rounded **up** to a whole number, with a floor of 1 — any return, however prompt, bills
    at least one day."
    PRD §3.6: "A `POOL` assignment costs nothing: its `rental_cost_cents` stays 0, because the
    pool consumes capacity rather than cash."

    Design: Difficulty/resource_temporal_overlap/loaner_half_open_interval_adjacency_versus_overlap
    """
    scene = setup_pool_unit_after_one_returned_occupancy()
    first = read_loaner_assignment(scene["first_loaner"]["id"])

    assert_timestamp_equals(first["returned_at"], "2026-08-05T08:00:00Z", "returned_at")
    assert first["billable_days"] == 4
    assert first["rental_cost_cents"] == 0


def test_pool_selection_follows_the_pinned_condition_score_ranking(api, ce_manager_headers):
    """PRD §3.6: "Surviving candidates are ranked by ascending `condition_score`, then by
    ascending `utilization_hours`, then — as the final, exhaustive tie-break — by ascending
    `created_at`, compared at millisecond resolution."
    PRD §3.6: "The first candidate is taken; the unit's random `id` never participates in the
    choice."

    Design: Difficulty/compensating_invariant/loaner_return_restores_pool_available_unit_count
    """
    scene = setup_two_pool_units_awaiting_selection()

    response = api.create_loaner_assignment(
        {"work_order_id": scene["work_order"]["id"], "source": "POOL",
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-08T00:00:00Z",
         "expected_work_order_version": scene["work_order"]["version"]},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert data["loaner_device_id"] == scene["pool_device"]["id"], (
        "The condition-2 unit outranks the condition-4 unit"
    )
    assert data["loaner_device_id"] != scene["pool_device_two"]["id"]


def test_deploying_a_pool_unit_consumes_one_unit_of_capacity(api, ce_manager_headers):
    """PRD §3.6: "A `POOL` assignment, however selected, moves the lending unit `IN_SERVICE` →
    `ON_LOAN`."
    PRD §3.2: "Inventory can be listed and narrowed by `facility_id`, `department_id`,
    `device_model_id`, either state dimension via `operational_state` or `security_state`, by
    `risk_class`, or by `is_loaner_pool` membership."

    Design: Difficulty/compensating_invariant/loaner_return_restores_pool_available_unit_count
    """
    scene = setup_two_pool_units_awaiting_selection()
    assert count_available_pool_units(scene["facility"]["id"]) == 2

    create_loaner_assignment(scene["work_order"]["id"],
                             expected_version=scene["work_order"]["version"])

    assert read_device(scene["pool_device"]["id"])["operational_state"] == "ON_LOAN"
    assert count_available_pool_units(scene["facility"]["id"]) == 1


def test_returning_a_pool_unit_restores_capacity_without_moving_money(api, ce_manager_headers):
    """PRD §3.6: "The assignment moves to `RETURNED`, a `POOL` unit goes `ON_LOAN` →
    `IN_SERVICE`, restoring the pool's available-unit count, and the covered order's
    `loaner_status` stays `COVERED`."
    PRD §3.6: "A `POOL` assignment costs nothing: its `rental_cost_cents` stays 0, because the
    pool consumes capacity rather than cash."

    Design: Difficulty/compensating_invariant/loaner_return_restores_pool_available_unit_count
    """
    from test_helpers import read_department

    scene = setup_two_pool_units_awaiting_selection()
    loaner = create_loaner_assignment(scene["work_order"]["id"],
                                      expected_version=scene["work_order"]["version"])
    set_clock("2026-08-04T00:00:00Z")

    data = validate_success(
        api.return_loaner_assignment(loaner["id"], ce_manager_headers), 200
    )
    assert data["status"] == "RETURNED"
    assert data["billable_days"] == 3
    assert data["rental_cost_cents"] == 0

    assert read_device(scene["pool_device"]["id"])["operational_state"] == "IN_SERVICE"
    assert count_available_pool_units(scene["facility"]["id"]) == 2, (
        "The return must restore the pre-assignment available-unit count"
    )
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 0
