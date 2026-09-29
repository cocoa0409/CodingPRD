"""Breadth over the uniqueness keys and the calendar windows: which tuple makes a
row a duplicate, which neighbouring tuple is still free, and where the horizon and
the logical clock close a window that was open a moment earlier.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import (
    accuracy_record_payload,
    demand_forecast_payload,
    supply_plan_payload,
)
from test_helpers.fixtures import (
    ADMIN,
    LEAD,
    PLANNER,
    SUPPLY,
    advance_cycle_to,
    build_supply_plan,
    create_capacity_block,
    create_customer,
    create_cycle,
    create_family,
    create_forecast,
    create_item,
    create_promotion,
    post_accuracy_record,
    read_cycle,
    read_family,
    read_forecast,
    read_promotion,
    set_clock,
    transition_cycle,
)


def test_a_second_line_for_the_same_quadruple_is_refused_but_a_new_month_is_free():
    """The uniqueness key is the whole quadruple, so repeating the month is a
    duplicate while moving one month along the same horizon is an ordinary create,
    and the refused attempt leaves the original line's numbers alone.

    PRD: "The line's subject is fixed by `cycle_id`, `item_id`, `customer_id` and
    `month`, and at most one line may exist for that quadruple — a second attempt
    is rejected with `ERR_DUPLICATE_FORECAST`."

    Design: Corner/validations/duplicate_forecast_for_same_cycle_item_customer_month_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(
        cycle_code="CY-DUP",
        horizon_start_month="2026-09",
        horizon_end_month="2026-10",
        financial_commitment_cents=0,
    )

    first = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-09", level_units=1000
    )
    assert first["baseline_units"] == 1000

    duplicate = api_client.create_demand_forecast(
        demand_forecast_payload(
            cycle["id"], item["id"], customer["id"], month="2026-09", level_units=700
        ),
        PLANNER,
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_FORECAST.value, 409)

    untouched = read_forecast(first["id"])
    assert untouched["level_units"] == 1000
    assert untouched["baseline_units"] == 1000
    assert untouched["version"] == first["version"]

    neighbour = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-10", level_units=700
    )
    assert neighbour["month"] == "2026-10"
    assert neighbour["baseline_units"] == 700

    listing = api_client.list_demand_forecasts(
        PLANNER, params={"cycle_id": cycle["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
    assert meta["total_count"] != 3
    assert len(rows) == 2


def test_a_second_plan_for_a_planned_pair_is_refused_and_the_money_is_not_doubled():
    """One non-stale plan per cycle-and-item pair is the whole rule, and because the
    refused create writes nothing the cycle's plan value stays at one plan's worth
    rather than twice it.

    PRD: "at most one plan may exist per cycle-and-item pair in a status other than
    `STALE`, so a second create while a `PLANNED`, `RATIONED` or `COMMITTED` plan
    exists is rejected with `ERR_SUPPLY_PLAN_EXISTS`."

    Design: Corner/validations/supply_plan_create_second_non_stale_plan_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    create_capacity_block(family["id"], available_hours=14)
    cycle = create_cycle(cycle_code="CY-ONEPLAN", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    transition_cycle(cycle["id"], "SUPPLY_REVIEW")

    plan = build_supply_plan(cycle["id"], item["id"])
    assert plan["status"] == "PLANNED"
    assert plan["gross_requirement_units"] == 1000
    assert plan["constrained_units"] == 1330

    second = api_client.create_supply_plan(
        supply_plan_payload(cycle["id"], item["id"]), SUPPLY
    )
    validate_error(second, ApiErrorId.ERR_SUPPLY_PLAN_EXISTS.value, 409)

    listing = api_client.list_supply_plans(
        SUPPLY, params={"cycle_id": cycle["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == plan["id"]

    reread = read_cycle(cycle["id"])
    assert reread["plan_value_cents"] == 1330000
    assert reread["plan_value_cents"] != 2660000


def test_a_second_actual_for_the_same_triple_is_refused_even_from_another_role():
    """The uniqueness key ignores who is posting, so a different authorised identity
    hits the same wall, and the family's rolling error still reflects exactly one
    scored record.

    PRD: "At most one record may exist for that triple, and a second attempt is
    rejected with `ERR_DUPLICATE_ACCURACY_RECORD`."

    Design: Corner/validations/duplicate_accuracy_record_for_same_triple_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(cycle_code="CY-ONEREC", financial_commitment_cents=0)
    create_forecast(cycle["id"], item["id"], customer["id"], level_units=1000)
    advance_cycle_to(cycle["id"], "PUBLISHED")

    record = post_accuracy_record(cycle["id"], item["id"], customer["id"], 900)
    assert record["forecast_units_snapshot"] == 1000
    assert record["signed_error_units"] == 100
    assert record["abs_error_units"] == 100
    assert float(record["ape_pct"]) == 11.11

    repeat = api_client.create_accuracy_record(
        accuracy_record_payload(cycle["id"], item["id"], customer["id"], 400), ADMIN
    )
    validate_error(repeat, ApiErrorId.ERR_DUPLICATE_ACCURACY_RECORD.value, 409)

    listing = api_client.list_accuracy_records(
        ADMIN, params={"cycle_id": cycle["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["actual_units"] == 900

    rolled = read_family(family["id"])
    assert rolled["scored_record_count"] == 1
    assert float(rolled["rolling_wmape_pct"]) == 11.11


def test_a_month_on_either_side_of_the_horizon_is_refused_and_the_last_month_is_not():
    """The horizon is closed at both ends, so the month after it and the month
    before it are both out while the final month itself is an ordinary create.

    PRD: "The forecast `month` must fall inside the cycle's horizon, at or after
    `horizon_start_month` and at or before `horizon_end_month`; a month outside
    that span is rejected with `ERR_MONTH_OUTSIDE_HORIZON`."

    Design: Corner/validations/forecast_month_outside_cycle_horizon_rejected
    """
    family = create_family()
    item = create_item(family["id"])
    customer = create_customer()
    cycle = create_cycle(
        cycle_code="CY-HORIZON",
        horizon_start_month="2026-09",
        horizon_end_month="2026-11",
        financial_commitment_cents=0,
    )

    past_the_end = api_client.create_demand_forecast(
        demand_forecast_payload(
            cycle["id"], item["id"], customer["id"], month="2026-12", level_units=1000
        ),
        PLANNER,
    )
    validate_error(past_the_end, ApiErrorId.ERR_MONTH_OUTSIDE_HORIZON.value, 422)

    before_the_start = api_client.create_demand_forecast(
        demand_forecast_payload(
            cycle["id"], item["id"], customer["id"], month="2026-08", level_units=1000
        ),
        PLANNER,
    )
    validate_error(before_the_start, ApiErrorId.ERR_MONTH_OUTSIDE_HORIZON.value, 422)

    last_month = create_forecast(
        cycle["id"], item["id"], customer["id"], month="2026-11", level_units=1000
    )
    assert last_month["month"] == "2026-11"
    assert last_month["baseline_units"] == 1000
    assert last_month["status"] == "BASELINE"

    listing = api_client.list_demand_forecasts(
        PLANNER, params={"cycle_id": cycle["id"], "limit": 100}
    )
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert len(rows) == 1


def test_moving_the_clock_forward_closes_a_window_that_approved_a_moment_earlier():
    """The frozen-horizon test is against the logical clock rather than against any
    stored date, so a September window that approves in August is refused once the
    clock stands in September.

    PRD: "the promotion's horizon must still be open: `start_month` must be
    strictly later than the current logical month, so a promotion starting in the
    current logical month or any earlier month is rejected with
    `ERR_PROMOTION_HORIZON_FROZEN`."

    Design: Corner/validations/promotion_approve_in_current_logical_month_returns_horizon_frozen
    """
    family = create_family()
    item = create_item(family["id"])
    customer_a = create_customer(customer_code="CUST-A", name="Alpha Grocery")
    customer_b = create_customer(
        customer_code="CUST-B", name="Beta Club", channel="CLUB", priority_rank=4
    )

    current_month = create_promotion(
        item["id"], customer_a["id"], start_month="2026-08", end_month="2026-08"
    )
    validate_error(
        api_client.approve_promotion(current_month["id"], LEAD, {}),
        ApiErrorId.ERR_PROMOTION_HORIZON_FROZEN.value,
        422,
    )
    assert read_promotion(current_month["id"])["status"] == "DRAFT"

    next_month = create_promotion(
        item["id"], customer_a["id"], start_month="2026-09", end_month="2026-09"
    )
    approved = validate_success(
        api_client.approve_promotion(next_month["id"], LEAD, {}), 200
    )
    assert approved["status"] == "APPROVED"

    moved = set_clock("2026-09-15T00:00:00Z")
    assert moved["current_utc"].startswith("2026-09-15T00:00:00")

    too_late = create_promotion(
        item["id"], customer_b["id"], start_month="2026-09", end_month="2026-09"
    )
    error = validate_error(
        api_client.approve_promotion(too_late["id"], LEAD, {}),
        ApiErrorId.ERR_PROMOTION_HORIZON_FROZEN.value,
        422,
    )
    assert error["error_id"] != ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP.value
    assert read_promotion(too_late["id"])["status"] == "DRAFT"
