"""The work-order concurrency guard and immediate visibility of derived values."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import ERR_STALE_WORK_ORDER_VERSION
from test_helpers.fixtures import Plant, build_plant


def test_the_same_work_order_version_works_once_and_is_stale_immediately_after(api):
    """One behind is refused, the observed value schedules, and a replay is refused.

    PRD 2.8: "Because scheduling supersedes any test already scheduled on that work
    order — a legitimate re-test — and advances the work order's `version`, a request
    whose `expected_work_order_version` does not equal the work order's current
    `version` is rejected with `ERR_STALE_WORK_ORDER_VERSION` (HTTP 412), on the
    grounds that the caller has not observed the schedule it would be discarding."

    Design: Corner/cross_cutting_complexity_layers/scheduling_a_test_under_a_stale_work_order_version_is_rejected_twice_over
    """
    plant = build_plant(api, "assembled")
    work_order = plant.get_work_order()
    cell = plant.cell
    observed_version = work_order["version"]
    assert work_order["build_status"] == "ASSEMBLED"
    assert cell["max_concurrent_kw"] == 20.0

    one_behind = api.create_performance_test(
        F.performance_test_payload(
            work_order["id"], cell["id"], observed_version - 1, dyno_draw_kw=8.0
        ),
        U.TEST_ENGINEER,
    )

    validate_error(one_behind, ERR_STALE_WORK_ORDER_VERSION, 412)
    _none_yet, empty_meta = validate_paginated(api.list_performance_tests(U.PLANT_ADMIN))
    assert empty_meta["total_count"] == 0
    assert plant.get_work_order()["version"] == observed_version

    first = validate_success(
        api.create_performance_test(
            F.performance_test_payload(
                work_order["id"], cell["id"], observed_version, dyno_draw_kw=8.0
            ),
            U.TEST_ENGINEER,
        ),
        201,
    )

    assert first["status"] == "SCHEDULED"
    assert first["requires_requalification"] is False
    A.assert_rounded_to(
        plant.get_cell()["peak_reserved_kw"], 8.0, 1, "peak_reserved_kw"
    )
    assert plant.get_work_order()["version"] == observed_version + 1

    replayed = api.create_performance_test(
        F.performance_test_payload(
            work_order["id"],
            cell["id"],
            observed_version,
            dyno_draw_kw=8.0,
            test_method="IEEE_112_B_DYNAMOMETER",
        ),
        U.TEST_ENGINEER,
    )

    validate_error(replayed, ERR_STALE_WORK_ORDER_VERSION, 412)
    assert plant.get_test(first)["status"] == "SCHEDULED"
    reread_version = plant.get_work_order()["version"]
    assert reread_version == observed_version + 1

    second = validate_success(
        api.create_performance_test(
            F.performance_test_payload(
                work_order["id"],
                cell["id"],
                reread_version,
                dyno_draw_kw=8.0,
                test_method="IEEE_112_B_DYNAMOMETER",
            ),
            U.TEST_ENGINEER,
        ),
        201,
    )

    assert second["status"] == "SCHEDULED"
    assert second["test_method"] == "IEEE_112_B_DYNAMOMETER"
    assert plant.get_test(first)["status"] == "SUPERSEDED"
    A.assert_rounded_to(
        plant.get_cell()["peak_reserved_kw"], 8.0, 1, "peak_reserved_kw"
    )
    _tests, test_meta = validate_paginated(
        api.list_performance_tests(
            U.PLANT_ADMIN, {"work_order_id": work_order["id"]}
        )
    )
    assert test_meta["total_count"] == 2
    assert plant.get_work_order()["version"] == reread_version + 1


def test_a_write_and_the_read_that_follows_it_agree_on_every_derived_value(api):
    """The confirm promise, the debited allowance and the cost roll-up need no settling.

    PRD 3.4: "On success the recomputed `promised_lead_time_days` and
    `promised_ship_date` are stored as the binding promise, `confirmed_at` is set to
    the current logical-clock instant, and the distributor's allowance ledger is
    debited: `units_outstanding` rises by the order's `quantity` and
    `stock_allowance_remaining_units` falls by the same amount, with the
    distributor's `version` advancing by 1."

    PRD 3.5: "Cost is computed at creation and recomputed whenever
    `rework_reject_count` changes."

    Design: Corner/consistency_model/every_mutation_is_visible_in_its_own_response_and_in_an_immediate_read
    """
    design_payload = F.motor_design_payload()
    plant = Plant(api)
    distributor = plant.add_distributor()
    plant.released_design(design_payload)
    order = plant.add_order()
    assert distributor["committed_annual_units"] == 500
    assert distributor["stock_allowance_remaining_units"] == 500
    assert order["status"] == "DRAFT"
    assert order["quantity"] == 12

    confirmed = validate_success(
        api.confirm_customer_order(
            order["id"], F.confirm_order_payload(), U.PRODUCTION_PLANNER
        ),
        200,
    )
    read_back = validate_success(
        api.get_customer_order(order["id"], U.PRODUCTION_PLANNER), 200
    )
    ledger = validate_success(
        api.get_distributor(distributor["id"], U.PRODUCTION_PLANNER), 200
    )

    assert confirmed["promised_lead_time_days"] == 29
    assert confirmed["promised_ship_date"] == "2026-08-30"
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["confirmed_at"] is not None
    assert confirmed["confirmed_at"] == F.CLOCK_START
    assert read_back == confirmed
    assert read_back["promised_lead_time_days"] == confirmed["promised_lead_time_days"]
    assert read_back["promised_ship_date"] == confirmed["promised_ship_date"]
    assert ledger["units_outstanding"] == 12
    assert ledger["stock_allowance_remaining_units"] == 488

    created = plant.add_work_order(unit_count=12)
    stored = plant.get_work_order()
    summary = plant.get_cost_summary()

    assert created["standard_cost_cents"] == 2351712
    assert created["direct_cost_cents"] == 1795200
    assert created["overhead_band"] == "COMPLEX"
    assert created["actual_cost_cents"] == 2351712
    assert created["cost_variance_cents"] == 0
    A.assert_cost_rollup(created, design_payload, 12)
    assert stored == created
    assert stored["standard_cost_cents"] == created["standard_cost_cents"]
    assert summary["standard_cost_cents"] == created["standard_cost_cents"]
    assert summary["standard_cost_cents"] == 2351712
    assert summary["unit_standard_cost_cents"] == 195976
    assert created["build_status"] == "RELEASED"
    assert created["certification_status"] == "PENDING"
    assert created["design_pin_stale"] is False
    assert plant.get_order()["status"] == "IN_PRODUCTION"
