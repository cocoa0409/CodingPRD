"""Demand forecasting from service history and fleet size, and the criticality
classification that turns a forecast into a stocking decision."""

from test_helpers import (
    ApiErrorId, api_client, assert_forecast, assert_installed_unit, assert_part,
    classify_part, close_work_order, consume_line, add_part_line,
    create_forecast, create_work_order, read_part, set_clock, setup_catalogue,
    TEST_USERS, validate_error, validate_paginated, validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _history_scenario():
    """Four covered machines, 100 units on the shelf and three CLOSED work orders
    consuming 5, 5 and 4 units — two of them MACHINE_DOWN, one DEGRADED."""
    scenario = setup_catalogue(
        part_number="BND-1", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=3.0, max_stock_units=30, dealer_code="D-BND",
        model_code="EM-B10", serial_prefix="SN-B10", installed_units=4,
        qty_per_unit=5, stock_units=100,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),
                     ("VITAL", 0.55, 0.60, 0.30)))
    dealer_id = scenario["dealer"]["id"]
    jobs = [(0, "BREAKDOWN", "MACHINE_DOWN", 5),
            (1, "BREAKDOWN", "MACHINE_DOWN", 5),
            (2, "SCHEDULED_MAINTENANCE", "DEGRADED", 4)]
    for unit_index, work_type, priority, qty in jobs:
        wo = create_work_order(scenario["units"][unit_index]["id"], dealer_id,
                               work_type, priority)
        line = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], qty)
        consume_line(line["id"], dealer_id, qty)
        close_work_order(wo["id"], dealer_id)
    return scenario


def _boundary_window_scenario():
    """One line of 5 units consumed and its work order CLOSED at the default clock,
    then the clock advanced by exactly 365 days."""
    scenario = setup_catalogue(
        part_number="WIN-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=2.0, dealer_code="D-WIN", dealer_region="APAC",
        model_code="EM-C10", serial_prefix="SN-C10", qty_per_unit=5,
        stock_units=10, price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_id = scenario["dealer"]["id"]
    wo = create_work_order(scenario["unit"]["id"], dealer_id,
                           "SCHEDULED_MAINTENANCE", "PLANNED")
    line = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], 5)
    consume_line(line["id"], dealer_id, 5)
    close_work_order(wo["id"], dealer_id)
    set_clock("2027-08-01T00:00:00Z")
    return scenario


def test_work_order_closed_exactly_at_the_window_edge_is_excluded(api):
    """PRD 3.3: "The window opens strictly after the instant that is `lookback_days`
    before now and closes at and including now — a work order closed at exactly the
    instant `lookback_days` before now is **excluded**, while one closed at exactly the
    current instant is included."
    PRD 3.3: "When the requested `method` is `WORK_ORDER_HISTORY` and the qualifying
    consumed-line input set is empty, the service refuses to manufacture a zero
    forecast and rejects the request with `ERR_FORECAST_INPUT_EMPTY`."

    Design: Difficulty/boundary_precision_check/forecast_lookback_window_half_open_excludes_exact_boundary
    """
    scenario = _boundary_window_scenario()

    resp = api.create_forecast(
        scenario["part"]["id"],
        {"horizon_months": 12, "method": "WORK_ORDER_HISTORY", "lookback_days": 365},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_FORECAST_INPUT_EMPTY.value)

    _, meta = validate_paginated(api.list_forecasts(scenario["part"]["id"], PLANNER))
    assert meta["total_count"] == 0, "the rejected call must create no forecast"


def test_one_extra_lookback_day_includes_the_boundary_work_order(api):
    """PRD 3.3: "It considers only part lines whose part is the part being forecast,
    whose `line_status` is `CONSUMED`, whose parent work order has `status` `CLOSED`,
    and whose parent work order's `closed_at` falls inside a half-open window ending
    at the current logical instant."
    PRD 3.3: "Summing `qty_consumed` across that input set gives `wo_history_units`.
    Annualising it gives `annualized_wo_units`, which is `wo_history_units` multiplied
    by 365, divided by `lookback_days`, and rounded half up to two decimal places."
    PRD 3.3: "Whichever variant applies, `forecast_units` is the raw figure rounded
    **up** to the next whole unit, with that ceiling applied exactly once and only at
    the very end."

    Design: Difficulty/boundary_precision_check/forecast_lookback_window_half_open_excludes_exact_boundary
    """
    scenario = _boundary_window_scenario()

    forecast = validate_success(api.create_forecast(
        scenario["part"]["id"],
        {"horizon_months": 12, "method": "WORK_ORDER_HISTORY", "lookback_days": 366},
        PLANNER), 201)
    assert_forecast(forecast)
    assert forecast["wo_history_units"] == 5
    assert forecast["annualized_wo_units"] == 4.99
    assert forecast["forecast_units"] == 5
    assert forecast["forecast_status"] == "CURRENT"

    _, meta = validate_paginated(api.list_forecasts(scenario["part"]["id"], PLANNER))
    assert meta["total_count"] == 1


def test_criticality_score_of_exactly_seventy_bands_as_vital(api):
    """PRD 3.4: "The **demand component** is the forecast's `forecast_units`
    multiplied by two, capped so that it can never exceed 40 points however large the
    forecast grows."
    PRD 3.4: "When that set is empty the downtime component is 0; otherwise it is 30
    points multiplied by the fraction of those lines whose parent work order has
    `downtime_priority` `MACHINE_DOWN`, rounded half up to two decimal places."
    PRD 3.4: "The **lead-time component** is 20 points when the part's
    `lead_time_days` is 60 days or more, 12 points when it is at least 30 days but
    less than 60, and 5 points otherwise. The **coverage component** is 10 points when
    the forecast's `installed_base_units` is 4 or more, 6 points when it is at least 2
    but fewer than 4, and 2 points otherwise."
    PRD 3.4: "Banding is inclusive at both thresholds. A `criticality_score` of 70 or
    more makes the part `VITAL`; a score of at least 40 but below 70 makes it
    `ESSENTIAL`; anything below 40 makes it `DESIRABLE`. The boundary is exact — a
    score of exactly 70.00 is `VITAL`, and 69.99 is `ESSENTIAL`."

    Design: Difficulty/boundary_precision_check/criticality_score_exactly_seventy_is_vital
    """
    scenario = _history_scenario()
    forecast = validate_success(api.create_forecast(
        scenario["part"]["id"],
        {"horizon_months": 12, "method": "BLENDED", "lookback_days": 365},
        PLANNER), 201)
    assert forecast["annualized_wo_units"] == 14.00
    assert forecast["ib_rate_units"] == 4.00
    assert forecast["forecast_units"] == 10

    part = validate_success(api.classify_part(scenario["part"]["id"], PLANNER))
    assert_part(part)
    assert part["criticality_score"] == 70.00
    assert part["criticality_class"] == "VITAL"


def test_vital_classification_writes_buffer_sizing_and_reprices(api):
    """PRD 3.4: "`stocking_policy` is then decided with the zero-demand case taking
    precedence over the band. When the forecast's `forecast_units` is 0 the policy is
    `NO_STOCK` no matter what the score said. Otherwise a `VITAL` part gets
    `STOCK_TO_MAX`, an `ESSENTIAL` part gets `MIN_MAX`, and a `DESIRABLE` part gets
    `MAKE_TO_ORDER`."
    PRD 3.4: "`safety_stock_units` is daily demand multiplied by the part's
    `lead_time_days` and then by that service factor, with a ceiling applied once at
    the end of that product. `reorder_point_units` is `safety_stock_units` plus a
    second, separately ceilinged quantity: daily demand multiplied by
    `lead_time_days`, rounded up once."
    PRD 3.4: "`current_effective_uplift_pct` and `current_list_unit_price_cents` are
    recomputed against the active price rule for the **new** `criticality_class` — and
    if no active rule exists for that band, classification is refused with
    `ERR_PRICE_RULE_NOT_FOUND`."

    Design: Difficulty/boundary_precision_check/criticality_score_exactly_seventy_is_vital
    """
    scenario = _history_scenario()
    validate_success(api.create_forecast(
        scenario["part"]["id"],
        {"horizon_months": 12, "method": "BLENDED", "lookback_days": 365},
        PLANNER), 201)

    part = validate_success(api.classify_part(scenario["part"]["id"], PLANNER))
    assert part["stocking_policy"] == "STOCK_TO_MAX"
    assert part["safety_stock_units"] == 3
    assert part["reorder_point_units"] == 5
    assert part["current_effective_uplift_pct"] == 0.55
    assert part["current_list_unit_price_cents"] == 2066


def test_criticality_with_no_downtime_history_scores_essential(api):
    """PRD 3.4: "When that set is empty the downtime component is 0; otherwise it is
    30 points multiplied by the fraction of those lines whose parent work order has
    `downtime_priority` `MACHINE_DOWN`, rounded half up to two decimal places."
    PRD 3.4: "Banding is inclusive at both thresholds. A `criticality_score` of 70 or
    more makes the part `VITAL`; a score of at least 40 but below 70 makes it
    `ESSENTIAL`; anything below 40 makes it `DESIRABLE`."
    PRD 3.4: "A service factor is selected by band: 1.65 for `VITAL`, 1.28 for
    `ESSENTIAL`, and 0.84 for `DESIRABLE`."
    PRD 2.8: "Otherwise, if `reorder_point_units` is greater than zero and
    `available_units` is less than or equal to `reorder_point_units`, the status reads
    `BELOW_REORDER_POINT`."

    Design: Corner/calculations/criticality_with_empty_downtime_history_scores_essential
    """
    scenario = setup_catalogue(
        part_number="ESS-1", unit_cost_cents=1333, lead_time_days=60,
        weight_kg=1.0, max_stock_units=40, dealer_code="D-ESS",
        model_code="EM-P10", serial_prefix="SN-P10", installed_units=2,
        qty_per_unit=25, price_rules=(("ESSENTIAL", 0.35, 0.60, 0.20),))
    forecast = create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    assert forecast["installed_base_units"] == 2
    assert forecast["ib_rate_units"] == 10.00
    assert forecast["forecast_units"] == 10
    assert forecast["wo_history_units"] == 0

    part = classify_part(scenario["part"]["id"])
    assert part["criticality_score"] == 46.00
    assert part["criticality_class"] == "ESSENTIAL"
    assert part["stocking_policy"] == "MIN_MAX"
    assert part["safety_stock_units"] == 3
    assert part["reorder_point_units"] == 5
    assert part["current_effective_uplift_pct"] == 0.35
    assert part["current_list_unit_price_cents"] == 1800
    assert part["replenishment_status"] == "BELOW_REORDER_POINT"


def test_three_forecast_methods_diverge_on_identical_data(api):
    """PRD 3.3: "The `method` then selects which leg to believe. Under
    `WORK_ORDER_HISTORY` the raw annual figure is `annualized_wo_units` alone — the
    installed base is ignored entirely, so a part with heavy field consumption against
    a small fleet forecasts high. Under `INSTALLED_BASE_RATE` the raw figure is
    `ib_rate_units` alone — consumption history is ignored entirely, so a newly
    launched part with no closed work orders at all still forecasts a non-zero number.
    Under `BLENDED` the raw figure weights the history leg at sixty percent and the
    installed-base leg at the remaining forty percent, and that weighted sum is itself
    rounded half up to two decimal places; for identical inputs it always lands
    strictly between the two single-leg variants."
    PRD 3.3: "creating it moves any prior forecast for the same part and the same
    `horizon_months` to `forecast_status` `SUPERSEDED`, so exactly one current row
    exists per part-and-horizon pair."

    Design: Corner/calculations/forecast_three_methods_diverge_on_identical_data
    """
    scenario = setup_catalogue(
        part_number="FC3-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-FC3", model_code="EM-Q10",
        serial_prefix="SN-Q10", installed_units=4, qty_per_unit=5,
        stock_units=20, price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_id = scenario["dealer"]["id"]
    wo = create_work_order(scenario["unit"]["id"], dealer_id,
                           "SCHEDULED_MAINTENANCE", "PLANNED")
    line = add_part_line(wo["id"], dealer_id, scenario["part"]["id"], 14)
    consume_line(line["id"], dealer_id, 14)
    close_work_order(wo["id"], dealer_id)

    f_wo = create_forecast(scenario["part"]["id"], 12, "WORK_ORDER_HISTORY", 365)
    assert f_wo["wo_history_units"] == 14
    assert f_wo["annualized_wo_units"] == 14.00
    assert f_wo["forecast_units"] == 14

    f_ib = create_forecast(scenario["part"]["id"], 24, "INSTALLED_BASE_RATE", 365)
    assert f_ib["installed_base_units"] == 4
    assert f_ib["ib_rate_units"] == 4.00
    assert f_ib["forecast_units"] == 4

    f_bl = create_forecast(scenario["part"]["id"], 60, "BLENDED", 365)
    assert f_bl["forecast_units"] == 10

    rows, meta = validate_paginated(
        api.list_forecasts(scenario["part"]["id"], PLANNER))
    assert meta["total_count"] == 3
    for row in rows:
        assert row["forecast_status"] == "CURRENT", (
            "each horizon carries its own CURRENT row")


def test_forecast_excludes_consumed_lines_on_open_work_orders(api):
    """PRD 3.3: "It considers only part lines whose part is the part being forecast,
    whose `line_status` is `CONSUMED`, whose parent work order has `status` `CLOSED`,
    and whose parent work order's `closed_at` falls inside a half-open window ending
    at the current logical instant."
    PRD 3.6: "Closing matters beyond bookkeeping: it is exactly the moment at which
    the work order's `CONSUMED` lines become eligible inputs to the forecasting history
    leg described in section 3.3."

    Design: Corner/calculations/forecast_excludes_consumed_lines_on_open_work_orders
    """
    scenario = setup_catalogue(
        part_number="OPN-1", unit_cost_cents=1333, lead_time_days=30,
        weight_kg=1.0, dealer_code="D-OPN", model_code="EM-R10",
        serial_prefix="SN-R10", qty_per_unit=1, stock_units=20,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_id = scenario["dealer"]["id"]
    unit_id = scenario["unit"]["id"]

    wo_a = create_work_order(unit_id, dealer_id, "SCHEDULED_MAINTENANCE", "PLANNED")
    line_a = add_part_line(wo_a["id"], dealer_id, scenario["part"]["id"], 5)
    consume_line(line_a["id"], dealer_id, 5)
    close_work_order(wo_a["id"], dealer_id)

    wo_b = create_work_order(unit_id, dealer_id, "SCHEDULED_MAINTENANCE", "PLANNED")
    line_b = add_part_line(wo_b["id"], dealer_id, scenario["part"]["id"], 7)
    consume_line(line_b["id"], dealer_id, 7)

    forecast = create_forecast(scenario["part"]["id"], 12, "WORK_ORDER_HISTORY", 365)
    assert forecast["wo_history_units"] == 5, \
        "the 7 units on the still-OPEN work order must not enter the history leg"
    assert forecast["annualized_wo_units"] == 5.00
    assert forecast["forecast_units"] == 5

    still_open = validate_success(api.get_work_order(wo_b["id"], PLANNER))
    assert still_open["status"] == "OPEN"
    assert still_open["closed_at"] is None
    assert read_part(scenario["part"]["id"])["on_hand_units"] == 8


def test_decommissioning_a_machine_shrinks_the_installed_base(api):
    """PRD 3.1: "When a machine leaves service it is decommissioned: its `status`
    becomes `DECOMMISSIONED`, its `version` advances, and from that moment it stops
    counting toward the installed-base population of any forecast and toward any
    dealer's installed-unit standing in the allocation waterfall."
    PRD 3.3: "It considers installed units whose `status` is `ACTIVE` and whose
    `model_id` is covered by an `ACTIVE` applicability row for the part being forecast"
    PRD 3.1: "Installed machines can be listed and filtered by `model_id`, by
    `dealer_id` and by `status`."

    Design: Corner/endpoints/installed_unit_decommission_shrinks_the_installed_base
    """
    scenario = setup_catalogue(
        part_number="DEC-1", unit_cost_cents=100, lead_time_days=5,
        weight_kg=0.1, dealer_code="D-DEC", model_code="EM-AB1",
        serial_prefix="SN-AB1", installed_units=4, qty_per_unit=5,
        price_rules=())
    before = create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    assert before["installed_base_units"] == 4
    assert before["ib_rate_units"] == 4.00
    assert before["forecast_units"] == 4

    retired = validate_success(api.decommission_installed_unit(
        scenario["units"][0]["id"], ADMIN))
    assert_installed_unit(retired)
    assert retired["status"] == "DECOMMISSIONED"

    after = create_forecast(scenario["part"]["id"], 12, "INSTALLED_BASE_RATE")
    assert after["installed_base_units"] == 3
    assert after["ib_rate_units"] == 3.00
    assert after["forecast_units"] == 3

    rows, _ = validate_paginated(api.list_forecasts(
        scenario["part"]["id"], PLANNER, params={"limit": 100}))
    by_id = {r["id"]: r for r in rows}
    assert by_id[before["id"]]["forecast_status"] == "SUPERSEDED"
    assert by_id[after["id"]]["forecast_status"] == "CURRENT"

    _, meta_active = validate_paginated(api.list_installed_units(
        ADMIN, params={"model_id": scenario["model"]["id"], "status": "ACTIVE"}))
    assert meta_active["total_count"] == 3
