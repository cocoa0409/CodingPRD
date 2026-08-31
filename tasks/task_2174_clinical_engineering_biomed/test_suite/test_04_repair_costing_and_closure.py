"""Provisional and final repair costing, contract selection and the departmental debit."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assign_work_order,
    bootstrap_pump_campus,
    close_work_order,
    complete_repair,
    create_service_contract,
    create_vendor,
    department_version,
    intake_work_order,
    make_vendor_rep_headers,
    read_department,
    read_loaner_assignment,
    read_service_contract,
    read_work_order,
    return_loaner_assignment,
    set_clock,
    setup_pre_debit_tier_scene,
    setup_repair_with_parts_hold_ready_to_close,
    setup_vendor_repair_ready_to_close,
    setup_verified_repair_with_deployed_pool_loaner,
    validate_error,
    validate_paginated,
    validate_success,
    verify_work_order,
)


def test_vendor_labour_rounds_half_up_after_a_single_divide(api):
    """PRD §3.4: "The labour term is computed in a pinned order: multiply the cumulative
    `labor_minutes` by that rate, multiply the product by `shift_multiplier_applied`, **then**
    divide by 60, **then** round half up to whole cents — exactly one rounding, applied at the
    end."
    PRD §3.4: "For a vendor order, it is the labour figure plus the cumulative
    `parts_cost_cents` plus the vendor's `travel_flat_cents`, the flat trip charge being added
    exactly once regardless of how many passes the repair took."

    Design: Corner/calculations/vendor_labor_rounds_half_up_on_repeating_decimal
    """
    scene = bootstrap_pump_campus()
    vendor = create_vendor()
    set_clock("2026-08-02T10:00:00Z")
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Vendor firmware service")
    assign_work_order(order["id"], service_mode="VENDOR", vendor_id=vendor["id"],
                      headers=TEST_USERS["ce_manager_headers"])

    data = validate_success(
        api.complete_repair(order["id"], {"labor_minutes": 95, "parts_cost_cents": 0},
                            make_vendor_rep_headers(vendor["id"])),
        200,
    )
    assert float(data["shift_multiplier_applied"]) == 1.0
    assert data["estimated_cost_cents"] == 53292, (
        f"95 min at 18500 c/h is 29292 after one half-up rounding, plus 24000 travel; "
        f"got {data['estimated_cost_cents']}"
    )
    assert data["status"] == "REPAIR_COMPLETE"
    assert data["repaired_by_user_id"] == vendor["id"]


def test_active_repair_hours_exclude_the_parts_hold_span(api, ce_manager_headers):
    """PRD §3.4: "The loop may repeat any number of times, and the crucial property is that
    the `AWAITING_PARTS` spans are **excluded** from active repair time — a repair that waits
    three days for a part is not penalised for the wait."
    PRD §3.5: "The timing fields are finalised: `closed_at` is read from the logical clock;
    `active_repair_hours` is the total `active_repair_seconds` — the sum, in seconds, of every
    closed active-repair segment, `AWAITING_PARTS` spans excluded and each failed-verification
    segment included — divided by 3,600 and rounded half up to two decimal places, with the
    summation done in seconds and the rounding applied once at the end rather than per segment;
    `turnaround_hours` is the wall-clock span from `reported_at` to `closed_at` in seconds,
    divided by 3,600 and rounded half up to two decimal places; and `sla_met` is `true`
    exactly when `active_repair_hours` is less than or equal to `sla_hours`."

    Design: Corner/calculations/active_repair_hours_exclude_awaiting_parts_span
    """
    scene = setup_repair_with_parts_hold_ready_to_close()
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["work_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["active_repair_seconds"] == 13500, (
        f"2.5 h + 1.25 h of active repair is 13500 s, got {data['active_repair_seconds']}"
    )
    assert float(data["active_repair_hours"]) == 3.75
    assert float(data["turnaround_hours"]) == 28.00
    assert data["priority"] == "P1" and data["sla_hours"] == 4
    assert data["sla_met"] is True
    assert data["final_cost_cents"] == 33750
    assert data["department_charge_cents"] == 33750


def test_contract_outside_its_coverage_window_is_not_selected(api, ce_manager_headers):
    """PRD §3.5: "The candidate set is every service contract whose `device_model_id` equals
    the model of the order's device, whose `vendor_id` equals the order's `vendor_id`, whose
    `status` is `ACTIVE`, whose inclusive coverage interval contains the order's
    `repair_started_at` — that is, `coverage_start` is at or before `repair_started_at` and
    `coverage_end` is at or after it — and whose `covered_events_used` is strictly less than
    its `covered_event_cap`."
    PRD §3.5: "An empty candidate set is **not** an error: the order simply falls back to the
    list rate and its `service_contract_id` stays null."

    Design: Corner/calculations/contract_selection_ignores_contract_whose_window_ended
    """
    scene = setup_vendor_repair_ready_to_close(
        coverage_start="2026-01-01T00:00:00Z", coverage_end="2026-06-30T00:00:00Z",
        covered_event_cap=5, assign_clock="2026-08-02T10:00:00Z",
        labor_minutes=95, parts_cost_cents=0,
    )
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["work_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["service_contract_id"] is None
    assert data["estimated_cost_cents"] == 53292
    assert data["final_cost_cents"] == 53292, "An empty candidate set falls back to list rate"

    contract = read_service_contract(scene["contract"]["id"])
    assert contract["covered_events_used"] == 0
    assert contract["status"] == "ACTIVE"
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 53292


def test_contract_exhausts_at_its_cap_and_the_next_close_pays_list_rate(api, ce_manager_headers):
    """PRD §3.5: "A contract whose `covered_events_used` reaches its `covered_event_cap`
    auto-transitions `ACTIVE` → `EXHAUSTED` and leaves the candidate set for every later close."
    PRD §3.5: "When the order was performed in `VENDOR` mode and a covering contract was
    selected, `final_cost_cents` is that contract's flat `deductible_cents` — the whole
    list-rate figure is replaced, not discounted — and the contract's `covered_events_used`
    increases by 1."

    Design: Corner/state_machines/service_contract_auto_exhausts_when_cap_is_consumed
    """
    scene = setup_vendor_repair_ready_to_close(covered_event_cap=1,
                                               dept_budget=900_000_000,
                                               assign_clock="2026-08-03T21:00:00Z")
    first = close_work_order(scene["work_order"]["id"], scene["department"]["id"])
    assert first["final_cost_cents"] == 25000
    assert first["service_contract_id"] == scene["contract"]["id"]

    contract = read_service_contract(scene["contract"]["id"])
    assert contract["covered_events_used"] == 1
    assert contract["status"] == "EXHAUSTED"

    vendor_headers = make_vendor_rep_headers(scene["vendor"]["id"])
    second = intake_work_order(scene["device"]["id"],
                               problem_summary="Second vendor repair")
    assign_work_order(second["id"], service_mode="VENDOR", vendor_id=scene["vendor"]["id"],
                      headers=ce_manager_headers)
    complete_repair(second["id"], 95, 15000, headers=vendor_headers)
    verify_work_order(second["id"], "PASS")
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(second["id"], {"expected_department_version": version},
                             ce_manager_headers),
        200,
    )
    assert data["estimated_cost_cents"] == 82938
    assert data["final_cost_cents"] == 82938
    assert data["service_contract_id"] is None
    assert read_service_contract(scene["contract"]["id"])["covered_events_used"] == 1
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 107938


def test_a_deployed_loaner_blocks_the_close_until_it_is_returned(api, ce_manager_headers):
    """PRD §3.5: "Two further preconditions apply: the device under service must not be
    `QUARANTINED` (`ERR_DEVICE_QUARANTINED`), and no loaner assignment on this order may still
    be `DEPLOYED` — an outstanding loaner blocks closure with `ERR_INVALID_LOANER_STATE`,
    because the rental it may still be accruing has not been settled."
    PRD §3.6: "A `POOL` assignment costs nothing: its `rental_cost_cents` stays 0, because the
    pool consumes capacity rather than cash."

    Design: Corner/state_machines/work_order_close_blocked_while_loaner_still_deployed
    """
    scene = setup_verified_repair_with_deployed_pool_loaner()
    order_id = scene["work_order"]["id"]
    version = department_version(scene["department"]["id"])

    blocked = api.close_work_order(order_id, {"expected_department_version": version},
                                   ce_manager_headers)
    validate_error(blocked, ApiErrorId.ERR_INVALID_LOANER_STATE.value, 409)
    assert read_work_order(order_id)["status"] == "VERIFIED"
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 0

    set_clock("2026-08-04T09:00:00Z")
    return_loaner_assignment(scene["loaner"]["id"])
    assert read_loaner_assignment(scene["loaner"]["id"])["rental_cost_cents"] == 0

    data = validate_success(
        api.close_work_order(order_id,
                             {"expected_department_version":
                              department_version(scene["department"]["id"])},
                             ce_manager_headers),
        200,
    )
    assert data["status"] == "CLOSED"
    assert data["final_cost_cents"] == 9000
    assert data["department_charge_cents"] == 9000
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 9000


def test_complete_repair_writes_the_provisional_list_rate_estimate(api):
    """PRD §3.4: "Dividing by 60 first and rounding the intermediate product is a different
    rule and yields a different figure: 95 minutes at 18,500 cents per hour with a 1.5
    multiplier gives the exact rational two million six hundred thirty-six thousand two
    hundred fifty divided by sixty, which is 43,937.5 cents and rounds half up to 43,938."
    PRD §3.4: "`shift_multiplier_applied` is set to 1.5 when the UTC hour of
    `repair_started_at` is before 7 or is 19 or later — that is, when the repair began outside
    the twelve-hour day shift running from 07:00 up to but not including 19:00 — and to 1.0
    otherwise."

    Design: Difficulty/dual_variant_calc/work_order_estimate_vs_contract_adjusted_final_cost
    """
    scene = setup_vendor_repair_ready_to_close()
    order = read_work_order(scene["work_order"]["id"])

    assert float(order["shift_multiplier_applied"]) == 1.5, (
        "A 21:00 UTC assignment is outside the 07:00-19:00 day shift"
    )
    assert order["estimated_cost_cents"] == 82938, (
        f"43938 labour + 15000 parts + 24000 travel is 82938, got {order['estimated_cost_cents']}"
    )


def test_close_replaces_the_estimate_with_the_contract_deductible(api, ce_manager_headers):
    """PRD §3.5: "When the order was performed in `VENDOR` mode and a covering contract was
    selected, `final_cost_cents` is that contract's flat `deductible_cents` — the whole
    list-rate figure is replaced, not discounted — and the contract's `covered_events_used`
    increases by 1."
    PRD §3.5: "A contract-covered order is therefore the one case where `final_cost_cents` and
    `estimated_cost_cents` differ for the same inputs, and both figures remain readable on the
    order."

    Design: Difficulty/dual_variant_calc/work_order_estimate_vs_contract_adjusted_final_cost
    """
    scene = setup_vendor_repair_ready_to_close()
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["work_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["estimated_cost_cents"] == 82938
    assert data["final_cost_cents"] == 25000
    assert data["estimated_cost_cents"] != data["final_cost_cents"]
    assert data["service_contract_id"] == scene["contract"]["id"]


def test_contract_covered_close_consumes_one_event_and_debits_the_deductible(api,
                                                                            ce_manager_headers):
    """PRD §3.5: "The contract opens with `status` `ACTIVE` and `covered_events_used` at 0."
    PRD §3.5: "The result is `department_charge_cents`, and it is added to the department's
    `downtime_spend_cents`, whose new value is the pre-debit figure plus the charge."

    Design: Difficulty/dual_variant_calc/work_order_estimate_vs_contract_adjusted_final_cost
    """
    scene = setup_vendor_repair_ready_to_close()
    assert scene["contract"]["covered_events_used"] == 0
    assert scene["contract"]["status"] == "ACTIVE"

    close_work_order(scene["work_order"]["id"], scene["department"]["id"])

    contract = read_service_contract(scene["contract"]["id"])
    assert contract["covered_events_used"] == 1
    assert contract["status"] == "ACTIVE", "A cap of 2 is not yet exhausted after one event"

    order = read_work_order(scene["work_order"]["id"])
    assert order["department_charge_cents"] == 25000
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 25000


def test_first_close_is_tiered_at_t0_against_a_zero_pre_debit_spend(api, ce_manager_headers):
    """PRD §3.5: "Step two keys the overhead tier on that pre-debit figure: the tier is T0
    when the pre-debit spend multiplied by 100 is strictly less than `downtime_budget_cents`
    multiplied by 50; failing that it is T1 when the pre-debit spend multiplied by 100 is
    strictly less than `downtime_budget_cents` multiplied by 80; otherwise it is T2."
    PRD §3.5: "The overhead rate is zero percent at T0, five percent at T1 and twelve percent
    at T2."

    Design: Difficulty/combinatorial_formula/department_overhead_tier_keyed_on_pre_debit_spend
    """
    scene = setup_pre_debit_tier_scene()

    first = read_work_order(scene["first_order"]["id"])
    assert first["final_cost_cents"] == 500_000
    assert first["department_charge_cents"] == 500_000, (
        "A pre-debit spend of 0 against a 1,000,000-cent budget resolves to T0, no overhead"
    )
    assert read_department(scene["department"]["id"])["downtime_spend_cents"] == 500_000


def test_second_close_reads_the_tier_from_the_pre_debit_spend(api, ce_manager_headers):
    """PRD §3.5: "The **departmental debit** follows, in three ordered steps that must not be
    iterated to a fixed point. Step one captures the department's `downtime_spend_cents` as it
    stands *before* this close."
    PRD §3.5: "Step three assembles the charge: sum the `rental_cost_cents` of every loaner
    assignment on this order whose `status` is `RETURNED` — deployed ones have already blocked
    the close, and cancelled ones contribute nothing — then take `final_cost_cents` multiplied
    by one plus the overhead rate, round that half up to whole cents, and add the loaner total
    *after* the rounding."

    Design: Difficulty/combinatorial_formula/department_overhead_tier_keyed_on_pre_debit_spend
    """
    scene = setup_pre_debit_tier_scene()
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["second_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["final_cost_cents"] == 9000
    assert data["department_charge_cents"] == 9450, (
        f"A pre-debit spend of exactly 50% of the ceiling is tier T1, so 9000 * 1.05 = 9450; "
        f"got {data['department_charge_cents']}"
    )

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 509_450
    assert department["budget_state"] == "OPEN"


def test_touching_contract_coverage_intervals_collide(api, ce_manager_headers):
    """PRD §3.5: "Coverage for a given vendor-and-model pair may not be double-booked: if any
    other `ACTIVE` contract on the same `vendor_id` and `device_model_id` already covers a
    closed interval that intersects the requested one, the creation is rejected with
    `ERR_CONTRACT_COVERAGE_OVERLAP`."
    PRD §3.5: "Because both intervals are closed, two contracts that merely touch — one ending
    on the instant the next begins — **do** overlap, which is the opposite convention from
    loaner occupancy in §3.6."

    Design: Difficulty/resource_temporal_overlap/service_contract_closed_interval_touching_endpoints_conflict
    """
    vendor = create_vendor()
    scene = bootstrap_pump_campus()
    create_service_contract(vendor["id"], scene["model"]["id"],
                            coverage_start="2026-01-01T00:00:00Z",
                            coverage_end="2026-06-30T00:00:00Z")

    response = api.create_service_contract(
        {"vendor_id": vendor["id"], "device_model_id": scene["model"]["id"],
         "coverage_start": "2026-06-30T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "annual_premium_cents": 1_300_000, "deductible_cents": 20000,
         "covered_event_cap": 3},
        ce_manager_headers,
    )
    validate_error(response, ApiErrorId.ERR_CONTRACT_COVERAGE_OVERLAP.value, 409)


def test_a_contract_starting_the_next_day_is_accepted(api, ce_manager_headers):
    """PRD §3.5: "A `CEManager` creates one against a single vendor and a single catalogue
    model, supplying the `vendor_id`, the `device_model_id`, the coverage interval as
    `coverage_start` and `coverage_end` — both instants **inclusive**, with the end strictly
    after the start — the `annual_premium_cents`, the flat per-event `deductible_cents` that
    will replace list-rate cost whenever the contract covers a repair, and the
    `covered_event_cap`, the maximum number of repairs the contract absorbs, which must be at
    least 1."
    PRD §3.5: "The contract opens with `status` `ACTIVE` and `covered_events_used` at 0."

    Design: Difficulty/resource_temporal_overlap/service_contract_closed_interval_touching_endpoints_conflict
    """
    vendor = create_vendor()
    scene = bootstrap_pump_campus()
    create_service_contract(vendor["id"], scene["model"]["id"],
                            coverage_start="2026-01-01T00:00:00Z",
                            coverage_end="2026-06-30T00:00:00Z")

    response = api.create_service_contract(
        {"vendor_id": vendor["id"], "device_model_id": scene["model"]["id"],
         "coverage_start": "2026-07-01T00:00:00Z", "coverage_end": "2026-12-31T00:00:00Z",
         "annual_premium_cents": 1_300_000, "deductible_cents": 20000,
         "covered_event_cap": 3},
        ce_manager_headers,
    )
    data = validate_success(response, 201)
    assert data["status"] == "ACTIVE"
    assert data["covered_events_used"] == 0

    listed, meta = validate_paginated(
        api.list_service_contracts(ce_manager_headers,
                                   params={"vendor_id": vendor["id"],
                                           "device_model_id": scene["model"]["id"]})
    )
    assert len(listed) == 2, f"Expected exactly 2 contracts on the pair, got {len(listed)}"
    assert meta["total_count"] == 2
