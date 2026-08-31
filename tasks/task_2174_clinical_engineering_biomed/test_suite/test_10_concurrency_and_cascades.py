"""Stale-version guards, the fiscal threshold cascade and immediate consistency."""

from test_helpers import (
    ApiErrorId,
    assert_timestamp_equals,
    close_work_order,
    create_loaner_assignment,
    department_version,
    read_department,
    read_device,
    read_facility,
    read_work_order,
    setup_close_debit_cascade_scene,
    setup_immediate_consistency_scene,
    setup_two_pool_units_awaiting_selection,
    setup_two_verified_repairs_same_department,
    setup_verified_in_house_repair,
    validate_error,
    validate_paginated,
    validate_success,
    work_order_version,
)


def test_a_stale_work_order_version_blocks_a_second_loaner_create(api, ce_manager_headers):
    """PRD §2.7: "Creating a loaner assignment requires a non-optional
    `expected_work_order_version` field carrying the client's last observed `version` of the
    covered `WorkOrder`. If that value does not equal the work order's current `version`, the
    creation is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412)."
    PRD §2.7: "A second loaner legitimately supersedes the coverage recorded by the first, so
    no state precondition blocks the write; the stale-version check is what makes the outcome
    deterministic, ensuring a client never records coverage against a work order whose state it
    has not observed."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_work_order_version_rejects_second_loaner_create
    """
    scene = setup_two_pool_units_awaiting_selection()
    order_id = scene["work_order"]["id"]
    observed_version = scene["work_order"]["version"]
    create_loaner_assignment(order_id, expected_version=observed_version,
                             loaner_device_id=scene["pool_device"]["id"],
                             start_at="2026-08-01T00:00:00Z", end_at="2026-08-05T00:00:00Z")

    stale = api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL",
         "loaner_device_id": scene["pool_device_two"]["id"],
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-05T00:00:00Z",
         "expected_work_order_version": observed_version},
        ce_manager_headers,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_WORK_ORDER_VERSION.value, 412)
    assert read_device(scene["pool_device_two"]["id"])["operational_state"] == "IN_SERVICE"

    fresh_version = work_order_version(order_id)
    assert fresh_version == observed_version + 1, (
        "The first loaner create must have bumped the work order's version by exactly 1"
    )

    retry = api.create_loaner_assignment(
        {"work_order_id": order_id, "source": "POOL",
         "loaner_device_id": scene["pool_device_two"]["id"],
         "start_at": "2026-08-01T00:00:00Z", "end_at": "2026-08-05T00:00:00Z",
         "expected_work_order_version": fresh_version},
        ce_manager_headers,
    )
    data = validate_success(retry, 201)
    assert data["status"] == "DEPLOYED"
    assert read_device(scene["pool_device_two"]["id"])["operational_state"] == "ON_LOAN"

    listed, meta = validate_paginated(
        api.list_loaner_assignments(ce_manager_headers, params={"work_order_id": order_id})
    )
    assert len(listed) == 2, f"Expected 2 assignments on the order, got {len(listed)}"
    assert meta["total_count"] == 2


def test_a_stale_department_version_blocks_the_second_close(api, ce_manager_headers):
    """PRD §2.7: "Closing a work order requires a non-optional `expected_department_version`
    field carrying the client's last observed `version` of the charged `Department`. If that
    value does not equal the department's current `version`, the close is rejected with
    `ERR_STALE_DEPARTMENT_VERSION` (HTTP 412)."
    PRD §2.7: "The reason is fiscal rather than cosmetic: the overhead tier applied at close is
    keyed on the department's pre-debit spend, so a close computed against a superseded spend
    figure would charge the wrong overhead."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_department_version_rejects_second_close
    """
    scene = setup_two_verified_repairs_same_department()
    department_id = scene["department"]["id"]
    observed_version = department_version(department_id)
    close_work_order(scene["first_order"]["id"], department_id,
                     expected_version=observed_version)

    stale = api.close_work_order(scene["second_order"]["id"],
                                 {"expected_department_version": observed_version},
                                 ce_manager_headers)
    validate_error(stale, ApiErrorId.ERR_STALE_DEPARTMENT_VERSION.value, 412)
    assert read_work_order(scene["second_order"]["id"])["status"] == "VERIFIED"
    assert read_department(department_id)["downtime_spend_cents"] == 9000

    retry = validate_success(
        api.close_work_order(scene["second_order"]["id"],
                             {"expected_department_version":
                              department_version(department_id)},
                             ce_manager_headers),
        200,
    )
    assert retry["status"] == "CLOSED"
    assert retry["department_charge_cents"] == 9000, (
        "A pre-debit spend of 9000 against a 5,000,000-cent ceiling is still tier T0"
    )
    assert read_department(department_id)["downtime_spend_cents"] == 18000


def test_budget_state_turns_to_warning_at_exactly_eighty_percent(api, ce_manager_headers):
    """PRD §2.9: "From the two, the system derives `budget_state`: it is `ON_HOLD` when
    `downtime_spend_cents` has reached or passed `downtime_budget_cents`; otherwise it is
    `WARNING` when `downtime_spend_cents` multiplied by 100 has reached or passed
    `downtime_budget_cents` multiplied by 80 — that is, when spending stands at eighty percent
    of the ceiling or above; otherwise it is `OPEN`."
    PRD §3.5: "That debit cascades twice more. The department's `budget_state` is re-derived
    from the **post**-debit spend by the rule in §2.9, so a close can move a department `OPEN`
    → `WARNING` or straight to `ON_HOLD`."

    Design: Corner/cross_cutting_complexity_layers/department_budget_state_flips_to_warning_at_exactly_eighty_percent
    """
    scene = setup_verified_in_house_repair(dept_budget=100_000, labor_minutes=400,
                                           parts_cost_cents=20000,
                                           assign_clock="2026-08-02T09:00:00Z",
                                           dept_name="Endoscopy", dept_code="CC-6100")
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["work_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["final_cost_cents"] == 80000
    assert data["department_charge_cents"] == 80000, (
        "A pre-debit spend of 0 resolves to tier T0, so no overhead is added"
    )

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 80000
    assert department["budget_state"] == "WARNING", (
        "Exactly eighty percent of the ceiling is WARNING, not OPEN"
    )

    facility = read_facility(scene["facility"]["id"])
    assert facility["departments_on_hold_count"] == 0
    assert facility["ce_posture"] == "NORMAL"


def test_the_close_response_already_carries_every_settled_figure(api, ce_manager_headers):
    """PRD §3.5: "The timing fields are finalised: `closed_at` is read from the logical clock;
    `active_repair_hours` is the total `active_repair_seconds` — the sum, in seconds, of every
    closed active-repair segment, `AWAITING_PARTS` spans excluded and each failed-verification
    segment included — divided by 3,600 and rounded half up to two decimal places, with the
    summation done in seconds and the rounding applied once at the end rather than per segment;
    `turnaround_hours` is the wall-clock span from `reported_at` to `closed_at` in seconds,
    divided by 3,600 and rounded half up to two decimal places; and `sla_met` is `true` exactly
    when `active_repair_hours` is less than or equal to `sla_hours`."
    PRD §3.5: "The device's `lifetime_maintenance_cost_cents` grows by this order's
    `final_cost_cents`, and its `replacement_priority_score` is recomputed on the new burden."

    Design: Corner/consistency_model/close_response_carries_every_cascade_effect_immediately
    """
    scene = setup_immediate_consistency_scene()
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["work_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["status"] == "CLOSED"
    assert data["final_cost_cents"] == 9000
    assert data["department_charge_cents"] == 9000
    assert float(data["active_repair_hours"]) == 1.00
    assert float(data["turnaround_hours"]) == 4.00
    assert data["sla_met"] is True
    assert_timestamp_equals(data["closed_at"], "2026-08-02T12:00:00Z", "closed_at")

    device = read_device(scene["device"]["id"])
    assert device["lifetime_maintenance_cost_cents"] == 9000
    assert device["operational_state"] == "IN_SERVICE"

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 9000
    assert department["budget_state"] == "OPEN"


def test_the_close_debit_flips_the_department_to_on_hold(api, ce_manager_headers):
    """PRD §3.5: "Step two keys the overhead tier on that pre-debit figure: the tier is T0 when
    the pre-debit spend multiplied by 100 is strictly less than `downtime_budget_cents`
    multiplied by 50; failing that it is T1 when the pre-debit spend multiplied by 100 is
    strictly less than `downtime_budget_cents` multiplied by 80; otherwise it is T2."
    PRD §3.5: "That debit cascades twice more. The department's `budget_state` is re-derived
    from the **post**-debit spend by the rule in §2.9, so a close can move a department `OPEN`
    → `WARNING` or straight to `ON_HOLD`."

    Design: Difficulty/transitive_cascade/close_debit_cascade_reaches_facility_posture_three_hops
    """
    scene = setup_close_debit_cascade_scene()
    version = department_version(scene["department"]["id"])

    data = validate_success(
        api.close_work_order(scene["second_order"]["id"],
                             {"expected_department_version": version}, ce_manager_headers),
        200,
    )
    assert data["final_cost_cents"] == 60000
    assert data["department_charge_cents"] == 63000, (
        f"A pre-debit spend of 60000 of a 100000 ceiling is tier T1, so 60000 * 1.05 = 63000; "
        f"got {data['department_charge_cents']}"
    )

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 123000
    assert department["budget_state"] == "ON_HOLD"


def test_the_on_hold_department_escalates_the_campus_posture(api, ce_manager_headers):
    """PRD §3.5: "When a department enters `ON_HOLD`, the campus `departments_on_hold_count`
    increments by 1; and when that count moves from 0 to 1 while `ce_posture` is `NORMAL`, the
    posture escalates to `HEIGHTENED`."
    PRD §2.10: "Several operations in this system mutate more than one row. When they do, every
    touched row has its `updated_at` refreshed and its `version` incremented by 1 — the cascade
    target as much as the addressed resource."

    Design: Difficulty/transitive_cascade/close_debit_cascade_reaches_facility_posture_three_hops
    """
    scene = setup_close_debit_cascade_scene()
    close_work_order(scene["second_order"]["id"], scene["department"]["id"])

    facility = read_facility(scene["facility"]["id"])
    assert facility["departments_on_hold_count"] == 1
    assert facility["ce_posture"] == "HEIGHTENED"


def test_the_first_close_alone_leaves_the_campus_untouched(api, ce_manager_headers):
    """PRD §3.5: "The result is `department_charge_cents`, and it is added to the department's
    `downtime_spend_cents`, whose new value is the pre-debit figure plus the charge."
    PRD §2.9: "New campuses open at `NORMAL`."

    Design: Difficulty/transitive_cascade/close_debit_cascade_reaches_facility_posture_three_hops
    """
    scene = setup_close_debit_cascade_scene()

    department = read_department(scene["department"]["id"])
    assert department["downtime_spend_cents"] == 60000
    assert department["budget_state"] == "OPEN"

    facility = read_facility(scene["facility"]["id"])
    assert facility["ce_posture"] == "NORMAL"
    assert facility["departments_on_hold_count"] == 0
