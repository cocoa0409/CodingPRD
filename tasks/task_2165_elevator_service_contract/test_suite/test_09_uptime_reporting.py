"""Per-car uptime: interval merging, the planned/unplanned split and both variants."""
from test_helpers import (
    AUGUST_2026_PERIOD_MINUTES,
    add_window,
    assert_uptime_report,
    read_callback,
    read_car,
    read_window,
    report_callback,
    run_callback_cycle,
    set_clock,
    setup_program,
    validate_success,
)


def _uptime(api, program, car_id, period_month="2026-08"):
    return validate_success(
        api.get_uptime_report(car_id, period_month, program.manager_headers)
    )


def test_the_two_uptime_variants_diverge_on_the_same_stored_rows(api):
    """PRD §3.7: "The **exclusive** variant, reported as `uptime_pct_exclusive`,
    divides `available_minutes` by `period_minutes` reduced by
    `planned_downtime_minutes` and multiplies by 100; because scheduled downtime is
    removed from the denominator, a planned modernization outage never depresses
    this number. The **inclusive** variant, reported as `uptime_pct_inclusive`,
    divides `available_minutes` by the full `period_minutes` and multiplies by 100;
    here planned outages depress uptime exactly as unplanned ones do. Both are
    rounded half up to 2 decimal places."

    Design: Difficulty/dual_variant_calc/uptime_exclusive_vs_inclusive_diverge_on_same_car
    """
    program = setup_program(
        ["CAR-A"],
        building_name="Harborview Tower",
        building_address="1 Harbor St",
        monthly_base_fee_cents=500_000,
        term_end_date="2026-12-31",
    )
    car_id = program.car_id()
    add_window(program, car_id, "2026-08-10T08:00:00Z", "2026-08-12T08:00:00Z", "REPAIR")
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-05T09:00:00Z",
        arrived_at="2026-08-05T15:00:00Z",
        callback_type="MALFUNCTION",
        out_of_service=True,
        resolution_note="door operator reset",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    report = _uptime(api, program, car_id)
    assert_uptime_report(report)
    assert report["uptime_pct_exclusive"] == 99.14
    assert report["uptime_pct_inclusive"] == 92.74
    assert report["uptime_pct_exclusive"] != report["uptime_pct_inclusive"], (
        "the two variants must diverge once planned downtime exists"
    )


def test_planned_and_unplanned_minutes_are_reported_side_by_side(api):
    """PRD §3.7: "The period runs from the first instant of that month at
    00:00:00.000 UTC, inclusive, up to the first instant of the following month at
    00:00:00.000 UTC, exclusive; `period_minutes` is the count of whole minutes in
    that half-open span — 1,440 minutes for each whole day the month contains."
    PRD §3.7: "`available_minutes` is then `period_minutes` less
    `planned_downtime_minutes` less `unplanned_outage_minutes`, and from it the two
    uptime variants are derived."
    PRD §3.5: "The car's `scheduled_downtime_minutes` is, at all times, the sum of
    `duration_minutes` over that car's windows whose `status` is `SCHEDULED` or
    `COMPLETED`."

    Design: Difficulty/dual_variant_calc/uptime_exclusive_vs_inclusive_diverge_on_same_car
    """
    program = setup_program(
        ["CAR-A"],
        building_name="Harborview Tower",
        building_address="1 Harbor St",
        monthly_base_fee_cents=500_000,
        term_end_date="2026-12-31",
    )
    car_id = program.car_id()
    add_window(program, car_id, "2026-08-10T08:00:00Z", "2026-08-12T08:00:00Z", "REPAIR")
    run_callback_cycle(
        program,
        car_id,
        reported_at="2026-08-05T09:00:00Z",
        arrived_at="2026-08-05T15:00:00Z",
        callback_type="MALFUNCTION",
        out_of_service=True,
        resolution_note="door operator reset",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    report = _uptime(api, program, car_id)
    assert report["period_minutes"] == AUGUST_2026_PERIOD_MINUTES
    assert report["period_minutes"] == 44_640
    assert report["planned_downtime_minutes"] == 2_880
    assert report["unplanned_outage_minutes"] == 360
    assert report["available_minutes"] == 41_400
    assert read_car(car_id)["scheduled_downtime_minutes"] == 2_880


def test_a_car_with_no_outages_reports_exactly_one_hundred_percent(api):
    """PRD §3.7: "The **exclusive** variant, reported as `uptime_pct_exclusive`,
    divides `available_minutes` by `period_minutes` reduced by
    `planned_downtime_minutes` and multiplies by 100; because scheduled downtime is
    removed from the denominator, a planned modernization outage never depresses
    this number. The **inclusive** variant, reported as `uptime_pct_inclusive`,
    divides `available_minutes` by the full `period_minutes` and multiplies by 100;
    here planned outages depress uptime exactly as unplanned ones do. Both are
    rounded half up to 2 decimal places."

    Design: Difficulty/boundary_precision_check/uptime_report_on_empty_outage_set_returns_exact_hundred
    """
    program = setup_program(
        ["CAR-X1"],
        building_name="Xi Studio",
        building_address="14 Xi Ave",
        building_manager_user_id="bm-x",
        contractor_user_id="sc-x",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    report = validate_success(
        api.get_uptime_report(program.car_id(), "2026-08", program.admin_headers)
    )
    assert_uptime_report(report)
    assert report["uptime_pct_exclusive"] == 100.00
    assert report["uptime_pct_inclusive"] == 100.00


def test_empty_interval_sets_leave_the_whole_period_available(api):
    """PRD §3.7: "`available_minutes` is then `period_minutes` less
    `planned_downtime_minutes` less `unplanned_outage_minutes`, and from it the two
    uptime variants are derived."
    PRD §3.7: "The report always returns **both** variants side by side regardless of
    scope, together with `car_id`, `period_month`, `period_minutes`,
    `unplanned_outage_minutes`, `planned_downtime_minutes`, `available_minutes`, and
    `outage_interval_count` — the number of merged unplanned intervals that produced
    `unplanned_outage_minutes`."

    Design: Difficulty/boundary_precision_check/uptime_report_on_empty_outage_set_returns_exact_hundred
    """
    program = setup_program(
        ["CAR-X1"],
        building_name="Xi Studio",
        building_address="14 Xi Ave",
        building_manager_user_id="bm-x",
        contractor_user_id="sc-x",
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    report = validate_success(
        api.get_uptime_report(program.car_id(), "2026-08", program.admin_headers)
    )
    assert report["car_id"] == program.car_id()
    assert report["period_month"] == "2026-08"
    assert report["period_minutes"] == 44_640
    assert report["unplanned_outage_minutes"] == 0
    assert report["planned_downtime_minutes"] == 0
    assert report["available_minutes"] == 44_640
    assert report["outage_interval_count"] == 0
    assert read_car(program.car_id())["scheduled_downtime_minutes"] == 0


def test_overlapping_unplanned_intervals_are_counted_exactly_once(api):
    """PRD §3.7: "Those intervals are then **union-merged** — sorted by interval start
    ascending and, for equal starts, by interval end ascending, then coalesced so
    that a minute covered by two of them is counted exactly once — and the total
    merged length in whole minutes is `unplanned_outage_minutes`."
    PRD §3.7: "Each cleared callback on the car that was reported with
    `out_of_service` true contributes the span from its `reported_at` up to but not
    including its `cleared_at`."
    PRD §3.3: "`response_minutes` is the number of whole minutes elapsed from
    `reported_at` to `arrived_at`."

    Design: Corner/calculations/uptime_counts_overlapping_unplanned_intervals_only_once
    """
    program = setup_program(
        ["CAR-K1"],
        building_name="Calc One",
        building_address="1 Calc St",
        building_manager_user_id="bm-k1",
        contractor_user_id="sc-k1",
    )
    car_id = program.car_id()

    set_clock("2026-08-05T09:00:00Z", program.admin_headers)
    first = report_callback(program, car_id, callback_type="MALFUNCTION", out_of_service=True)
    set_clock("2026-08-05T13:00:00Z", program.admin_headers)
    second = report_callback(program, car_id, callback_type="MALFUNCTION", out_of_service=True)

    set_clock("2026-08-05T15:00:00Z", program.admin_headers)
    validate_success(api.arrive_callback(first["id"], program.contractor_headers))
    validate_success(
        api.clear_callback(
            first["id"], program.contractor_headers, {"resolution_note": "first fault cleared"}
        )
    )
    set_clock("2026-08-05T17:00:00Z", program.admin_headers)
    validate_success(api.arrive_callback(second["id"], program.contractor_headers))
    validate_success(
        api.clear_callback(
            second["id"], program.contractor_headers, {"resolution_note": "second fault cleared"}
        )
    )
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    assert read_callback(first["id"])["response_minutes"] == 360
    assert read_callback(second["id"])["response_minutes"] == 240

    report = validate_success(
        api.get_uptime_report(car_id, "2026-08", program.admin_headers)
    )
    assert_uptime_report(report)
    assert report["unplanned_outage_minutes"] == 480, (
        "the two overlapping spans merge into [09:00, 17:00)"
    )
    assert report["unplanned_outage_minutes"] != 600, (
        "naively summing 360 and 240 double-counts the overlap"
    )
    assert report["planned_downtime_minutes"] == 0
    assert report["outage_interval_count"] == 1
    assert report["uptime_pct_inclusive"] == 98.92
    assert report["uptime_pct_exclusive"] == 98.92
    assert read_car(car_id)["availability_state"] == "IN_SERVICE"


def test_a_cancelled_window_contributes_no_planned_downtime(api):
    """PRD §3.7: "The **planned** family has one source: every downtime window on the
    car whose `status` is `SCHEDULED` or `COMPLETED` contributes the span from its
    `window_start` up to but not including its `window_end`. Windows in `CANCELLED`
    or `RESCHEDULE_REQUIRED` contribute nothing."
    PRD §3.5: "This is a conserved quantity: cancelling a `SCHEDULED` window
    subtracts exactly its `duration_minutes` and restores the pre-creation figure
    exactly, while a window that has already moved to `RESCHEDULE_REQUIRED` had its
    minutes removed at that moment and its later cancellation therefore leaves the
    total unchanged."

    Design: Corner/calculations/uptime_ignores_a_cancelled_downtime_window
    """
    program = setup_program(
        ["CAR-K2"],
        building_name="Calc Two",
        building_address="2 Calc St",
        building_manager_user_id="bm-k2",
        contractor_user_id="sc-k2",
    )
    car_id = program.car_id()
    window = add_window(
        program, car_id, "2026-08-10T08:00:00Z", "2026-08-12T08:00:00Z", "REPAIR"
    )
    validate_success(api.cancel_downtime_window(window["id"], program.admin_headers))
    set_clock("2026-09-01T00:00:00Z", program.admin_headers)

    assert read_window(window["id"])["status"] == "CANCELLED"

    report = validate_success(
        api.get_uptime_report(car_id, "2026-08", program.admin_headers)
    )
    assert report["planned_downtime_minutes"] == 0
    assert report["uptime_pct_exclusive"] == 100.00
    assert report["uptime_pct_inclusive"] == 100.00
    assert read_car(car_id)["scheduled_downtime_minutes"] == 0
