"""Breadth coverage of the seasonal distribution plan: the eligibility filter that decides
who is in the ranking, the seasonal factor that sets each demand, and the waterfall that
hands out a finite pool.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import assert_amount, assert_int
from test_helpers.test_users import ADMIN_HEADERS, LOGISTICS_HEADERS


def _plan(api, plant_id, as_of_month, headers=LOGISTICS_HEADERS):
    return validate_success(
        api.get_distribution_plan(plant_id, headers, params={"as_of_month": as_of_month})
    )


def _entry(plan, customer_id):
    matches = [row for row in plan["allocations"] if row["customer_id"] == customer_id]
    assert len(matches) == 1, f"{customer_id} appears {len(matches)} times in allocations"
    return matches[0]


def _pool_of_454(api):
    """The canonical chain leaves a 574.72 tonne cement silo with 120.00 reserved, so the
    plan's pool is 454.72 and CU1 is the single eligible customer."""
    env = fx.certificate_chain(api)
    silo = validate_success(api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS))
    assert_amount(silo["available_tonnes"], 454.72, "available_tonnes")
    return env


# ---------------------------------------------------------------------------
# calculations: the waterfall exhausts the pool from the top down
# ---------------------------------------------------------------------------
def test_the_top_priority_customer_takes_the_whole_pool_before_the_next_one_is_served(api):
    """The remainder is carried down the ranking rather than shared out: CU1 takes all 454.72
    of its 5000.00 tonne demand and CU2 is still listed, with nothing allocated and its full
    2500.00 as shortfall — a pro-rata split would have reported roughly 303 and 151.

    PRD: "Finally the ranking is **walked** in order, carrying a running remainder that starts
    at the pool: each customer's `allocated_tonnes` is the smaller of its `demand_tonnes` and
    the remainder, rounded half up to two decimals; its `shortfall_tonnes` is its
    `demand_tonnes` minus that allocation, rounded half up to two decimals; and the remainder
    is then reduced by the allocation before the next customer is considered."

    Design: Corner/calculations/distribution_plan_fills_the_top_priority_bucket_first
    """
    env = _pool_of_454(api)
    cu2 = validate_success(
        api.create_customer(
            f.customer_payload(
                name="Prairie Concrete",
                contract_priority=5,
                contract_monthly_tonnes=2000.00,
            ),
            LOGISTICS_HEADERS,
        ),
        201,
    )

    plan = _plan(api, env["plant_id"], 8)
    assert plan["plant_id"] == env["plant_id"]
    assert_int(plan["as_of_month"], 8, "as_of_month")
    assert_amount(plan["seasonal_factor"], 1.25, "seasonal_factor")
    assert_amount(plan["available_pool_tonnes"], 454.72, "available_pool_tonnes")

    assert len(plan["allocations"]) == 2
    assert [row["customer_id"] for row in plan["allocations"]] == [
        env["customer"]["id"],
        cu2["id"],
    ]

    first = plan["allocations"][0]
    assert_int(first["contract_priority"], 10, "contract_priority")
    assert_amount(first["demand_tonnes"], 5000.00, "demand_tonnes")
    assert_amount(first["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(first["shortfall_tonnes"], 4545.28, "shortfall_tonnes")

    second = plan["allocations"][1]
    assert_int(second["contract_priority"], 5, "contract_priority")
    assert_amount(second["demand_tonnes"], 2500.00, "demand_tonnes")
    assert_amount(second["allocated_tonnes"], 0.00, "allocated_tonnes")
    assert_amount(second["shortfall_tonnes"], 2500.00, "shortfall_tonnes")

    assert_amount(plan["total_allocated_tonnes"], 454.72, "total_allocated_tonnes")
    assert_amount(plan["total_shortfall_tonnes"], 7045.28, "total_shortfall_tonnes")
    # The pool is exhausted exactly, never over-allocated.
    assert_amount(
        plan["total_allocated_tonnes"],
        plan["available_pool_tonnes"],
        "total_allocated_tonnes",
    )


def test_the_plan_is_a_pure_read_that_leaves_nothing_behind(api):
    """Asking twice returns the identical body, and no row the plan looked at has moved: a
    handler that recorded allocations would move the silo or the customer version.

    PRD: "The read is pure: it computes a plan and persists nothing."

    Design: Corner/calculations/distribution_plan_fills_the_top_priority_bucket_first
    """
    env = _pool_of_454(api)
    customer_before = validate_success(
        api.get_customer(env["customer"]["id"], LOGISTICS_HEADERS)
    )
    silo_before = validate_success(
        api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS)
    )

    first = _plan(api, env["plant_id"], 8)
    second = _plan(api, env["plant_id"], 8)
    assert first == second

    customer_after = validate_success(
        api.get_customer(env["customer"]["id"], LOGISTICS_HEADERS)
    )
    assert customer_after["version"] == customer_before["version"]
    assert_amount(
        customer_after["open_reserved_tonnes"], 120.00, "open_reserved_tonnes"
    )

    silo_after = validate_success(
        api.get_silo(env["cement_silo"]["id"], LOGISTICS_HEADERS)
    )
    assert silo_after["version"] == silo_before["version"]
    assert_amount(silo_after["available_tonnes"], 454.72, "available_tonnes")


# ---------------------------------------------------------------------------
# calculations: three independent eligibility filters
# ---------------------------------------------------------------------------
def _three_ineligible_rivals(api):
    """Three higher-priority customers, each disqualified by a different one of the three
    eligibility conditions."""
    env = _pool_of_454(api)

    held = validate_success(
        api.create_customer(
            f.customer_payload(
                name="Prairie Concrete",
                contract_priority=99,
                contract_monthly_tonnes=2000.00,
            ),
            LOGISTICS_HEADERS,
        ),
        201,
    )
    on_hold = validate_success(
        api.patch_customer(held["id"], {"credit_hold": True}, LOGISTICS_HEADERS)
    )
    assert on_hold["credit_hold"] is True
    assert on_hold["contract_state"] == "ACTIVE"

    away = validate_success(
        api.create_customer(
            f.customer_payload(
                name="Desert Mix",
                region_code="US-SW",
                contract_priority=98,
                contract_monthly_tonnes=1000.00,
            ),
            LOGISTICS_HEADERS,
        ),
        201,
    )

    suspended = validate_success(
        api.create_customer(
            f.customer_payload(
                name="Lakeside Precast",
                contract_priority=97,
                contract_monthly_tonnes=900.00,
            ),
            LOGISTICS_HEADERS,
        ),
        201,
    )
    stopped = validate_success(
        api.patch_customer(
            suspended["id"], {"contract_state": "SUSPENDED"}, LOGISTICS_HEADERS
        )
    )
    assert stopped["contract_state"] == "SUSPENDED"

    return env, held, away, suspended


def test_a_held_an_absent_and_a_suspended_customer_are_all_left_out_of_the_ranking(api):
    """Their priorities of 99, 98 and 97 all outrank CU1's 10, and none of them sees a tonne:
    an implementation that filtered on `contract_state` alone would have starved the payer.

    PRD: "Eligibility is strict: only customers whose `contract_state` is `ACTIVE`, whose
    `credit_hold` is false, and whose `region_code` equals the plant's `region_code` are
    considered."

    Design: Corner/calculations/distribution_plan_excludes_suspended_held_and_out_of_region_customers
    """
    env, held, away, suspended = _three_ineligible_rivals(api)

    plan = _plan(api, env["plant_id"], 8, ADMIN_HEADERS)
    assert len(plan["allocations"]) == 1

    only = plan["allocations"][0]
    assert only["customer_id"] == env["customer"]["id"]
    assert_amount(only["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(only["shortfall_tonnes"], 4545.28, "shortfall_tonnes")

    listed = [row["customer_id"] for row in plan["allocations"]]
    for excluded in (held["id"], away["id"], suspended["id"]):
        assert excluded not in listed

    assert_amount(plan["total_allocated_tonnes"], 454.72, "total_allocated_tonnes")
    assert_amount(plan["total_shortfall_tonnes"], 4545.28, "total_shortfall_tonnes")


def test_clearing_the_credit_hold_puts_that_customer_back_at_the_head_of_the_ranking(api):
    """Eligibility is re-evaluated on every call, so the moment the hold is lifted the
    priority-99 customer takes the whole pool and CU1 drops to nothing.

    PRD: "The eligible customers are then **ranked** by `contract_priority` descending, then by
    `contract_monthly_tonnes` descending, then by `created_at` ascending; a row's `id` is never
    used as a tie-break."

    Design: Corner/calculations/distribution_plan_excludes_suspended_held_and_out_of_region_customers
    """
    env, held, _away, _suspended = _three_ineligible_rivals(api)

    cleared = validate_success(
        api.patch_customer(held["id"], {"credit_hold": False}, LOGISTICS_HEADERS)
    )
    assert cleared["credit_hold"] is False

    plan = _plan(api, env["plant_id"], 8)
    assert [row["customer_id"] for row in plan["allocations"]] == [
        held["id"],
        env["customer"]["id"],
    ]

    winner = _entry(plan, held["id"])
    assert_int(winner["contract_priority"], 99, "contract_priority")
    assert_amount(winner["demand_tonnes"], 2500.00, "demand_tonnes")
    assert_amount(winner["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(winner["shortfall_tonnes"], 2045.28, "shortfall_tonnes")

    starved = _entry(plan, env["customer"]["id"])
    assert_amount(starved["demand_tonnes"], 5000.00, "demand_tonnes")
    assert_amount(starved["allocated_tonnes"], 0.00, "allocated_tonnes")
    assert_amount(starved["shortfall_tonnes"], 5000.00, "shortfall_tonnes")

    assert_amount(plan["total_allocated_tonnes"], 454.72, "total_allocated_tonnes")
    assert_amount(plan["total_shortfall_tonnes"], 7045.28, "total_shortfall_tonnes")


# ---------------------------------------------------------------------------
# calculations: the three-way seasonal factor lookup
# ---------------------------------------------------------------------------
def test_the_seasonal_factor_is_a_three_way_lookup_driven_by_the_plants_own_peak_months(api):
    """August is one of the plant's declared peak months so it scales demand by 1.25, January
    falls to the off-season 0.70, and March gets the plain 1.00 — and none of the three moves
    the supply side.

    PRD: "The **seasonal factor**, reported as `seasonal_factor`, is chosen by testing peak
    season *first*: the factor is 1.25 when `as_of_month` appears in the plant's
    `peak_season_months`; failing that, it is 0.70 when `as_of_month` is December, January or
    February; and it is 1.00 otherwise."

    Design: Corner/calculations/seasonal_factors_come_from_the_declared_constants
    """
    env = _pool_of_454(api)
    plant = validate_success(api.get_plant(env["plant_id"], LOGISTICS_HEADERS))
    assert plant["peak_season_months"] == [5, 6, 7, 8, 9]

    winter = _plan(api, env["plant_id"], 1)
    assert_amount(winter["seasonal_factor"], 0.70, "seasonal_factor")
    winter_entry = _entry(winter, env["customer"]["id"])
    assert_amount(winter_entry["demand_tonnes"], 2800.00, "demand_tonnes")
    assert_amount(winter_entry["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(winter_entry["shortfall_tonnes"], 2345.28, "shortfall_tonnes")

    shoulder = _plan(api, env["plant_id"], 3)
    assert_amount(shoulder["seasonal_factor"], 1.00, "seasonal_factor")
    shoulder_entry = _entry(shoulder, env["customer"]["id"])
    assert_amount(shoulder_entry["demand_tonnes"], 4000.00, "demand_tonnes")
    assert_amount(shoulder_entry["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(shoulder_entry["shortfall_tonnes"], 3545.28, "shortfall_tonnes")

    peak = _plan(api, env["plant_id"], 5)
    assert_amount(peak["seasonal_factor"], 1.25, "seasonal_factor")
    peak_entry = _entry(peak, env["customer"]["id"])
    assert_amount(peak_entry["demand_tonnes"], 5000.00, "demand_tonnes")
    assert_amount(peak_entry["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(peak_entry["shortfall_tonnes"], 4545.28, "shortfall_tonnes")

    # Seasonality moves demand, never supply.
    for plan in (winter, shoulder, peak):
        assert_amount(plan["available_pool_tonnes"], 454.72, "available_pool_tonnes")
        assert_amount(plan["total_allocated_tonnes"], 454.72, "total_allocated_tonnes")


def test_a_month_outside_the_calendar_is_refused(api):
    """0 and 13 are not months, and the plan endpoint rejects them as shape errors rather than
    clamping them into the lookup.

    PRD: "A `PlantAdmin` or `LogisticsPlanner` asks the plant for a plan for a given
    `as_of_month`, an integer from 1 to 12 inclusive — anything else is refused with
    `ERR_INVALID_REQUEST`."

    Design: Corner/calculations/seasonal_factors_come_from_the_declared_constants
    """
    env = _pool_of_454(api)

    for month in (0, 13):
        validate_error(
            api.get_distribution_plan(
                env["plant_id"], LOGISTICS_HEADERS, params={"as_of_month": month}
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    still_works = _plan(api, env["plant_id"], 12)
    assert_amount(still_works["seasonal_factor"], 0.70, "seasonal_factor")
