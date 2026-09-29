"""Breadth coverage of the declared consistency model: every change is visible in the response of the
request that caused it. Derived read surfaces move on the very next request rather than on a schedule,
and action endpoints hand back the whole updated row instead of an acknowledgement to be followed up
with a read.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_amount,
    assert_instant_equals,
    assert_int,
    assert_intensity,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    LOGISTICS_HEADERS,
    OPERATOR_HEADERS,
)


# ---------------------------------------------------------------------------
# consistency: the plan and the plant aggregate move on the next request
# ---------------------------------------------------------------------------
def test_the_distribution_plan_reflects_a_reservation_one_request_later(api):
    """The plan is computed from the silo pool, so reserving 120.00 tonnes drops the pool by exactly
    that much on the very next request — no refresh step, no settling interval — and voiding the order
    restores the pre-order figure to the cent. The plant read taken in between shows the conserved
    quantity: the reservation moved availability, not mass.

    PRD: "The **pool**, reported as `available_pool_tonnes`, is the sum of `available_tonnes` across
    the plant's silos whose `material_kind` is `CEMENT` and whose `status` is `OPEN`, rounded half up
    to two decimals."

    Design: Corner/consistency model/aggregates_and_plans_reflect_the_write_that_just_happened
    """
    fx.reset_clock(api)
    env = fx.qualified_cement_environment(api)
    customer = fx.create_customer(api)
    certificate = fx.create_issued_certificate(
        api, env["batch"]["id"], customer["id"], env["batch"]["cement_tonnes"]
    )

    before = validate_success(
        api.get_distribution_plan(
            env["plant_id"], LOGISTICS_HEADERS, params={"as_of_month": 8}
        )
    )
    assert_amount(before["available_pool_tonnes"], 574.72, "available_pool_tonnes")
    assert_amount(before["seasonal_factor"], 1.25, "seasonal_factor")
    assert len(before["allocations"]) == 1
    allocation = before["allocations"][0]
    assert allocation["customer_id"] == customer["id"]
    assert_amount(allocation["demand_tonnes"], 5000.00, "demand_tonnes")
    assert_amount(allocation["allocated_tonnes"], 574.72, "allocated_tonnes")
    assert_amount(allocation["shortfall_tonnes"], 4425.28, "shortfall_tonnes")

    order = validate_success(
        api.create_loadout_order(
            f.loadout_order_payload(
                customer["id"],
                env["cement_silo"]["id"],
                certificate["id"],
                certificate["version"],
                tonnes=120.00,
            ),
            LOGISTICS_HEADERS,
        ),
        201,
    )
    assert order["status"] == "RESERVED"

    after = validate_success(
        api.get_distribution_plan(
            env["plant_id"], LOGISTICS_HEADERS, params={"as_of_month": 8}
        )
    )
    assert_amount(after["available_pool_tonnes"], 454.72, "available_pool_tonnes")
    reduced = after["allocations"][0]
    assert_amount(reduced["allocated_tonnes"], 454.72, "allocated_tonnes")
    assert_amount(reduced["shortfall_tonnes"], 4545.28, "shortfall_tonnes")
    assert_amount(after["total_allocated_tonnes"], 454.72, "total_allocated_tonnes")

    plant = validate_success(api.get_plant(env["plant_id"], ADMIN_HEADERS))
    assert_amount(
        plant["cement_tonne_balance_tonnes"], 574.72, "cement_tonne_balance_tonnes"
    )

    voided = validate_success(
        api.void_loadout_order(
            order["id"], {"void_reason": "CUSTOMER_CANCELLED"}, LOGISTICS_HEADERS
        )
    )
    assert voided["status"] == "VOIDED"

    restored = validate_success(
        api.get_distribution_plan(
            env["plant_id"], LOGISTICS_HEADERS, params={"as_of_month": 8}
        )
    )
    assert_amount(restored["available_pool_tonnes"], 574.72, "available_pool_tonnes")
    assert_amount(
        restored["allocations"][0]["allocated_tonnes"], 574.72, "allocated_tonnes"
    )


# ---------------------------------------------------------------------------
# consistency: an action hands back the whole row, not an acknowledgement
# ---------------------------------------------------------------------------
def test_each_run_action_returns_the_whole_row_a_following_read_repeats(api):
    """The birth of the run already carries every computed field — both state dimensions, the empty
    charge array, a zeroed energy figure and the scheduled hours — rather than a bare identifier. Each
    action after that returns the recomputed row, and the read that follows it comes back identical
    field for field, so nothing settles between the two requests.

    PRD: "The run is born with `process_state` at `SCHEDULED`, `quality_state` at `PENDING_LAB` and an
    empty `fuel_charges` array."

    Design: Corner/consistency model/every_write_returns_the_full_updated_row_in_the_same_response
    """
    fx.reset_clock(api)
    env = fx.plant_environment(api)
    design = fx.create_approved_design(api, env["plant_id"], env["materials"])
    pile = fx.create_sealed_pile(
        api, env["plant_id"], design["id"], env["materials"]
    )

    created = validate_success(
        api.create_kiln_run(
            f.kiln_run_payload(
                env["kiln"]["id"], pile["id"], env["clinker_silo"]["id"]
            ),
            OPERATOR_HEADERS,
        ),
        201,
    )
    run_id = created["id"]
    assert created["process_state"] == "SCHEDULED"
    assert created["quality_state"] == "PENDING_LAB"
    assert created["fuel_charges"] == []
    assert_amount(created["gross_energy_gj"], 0.00, "gross_energy_gj")
    assert_amount(created["scheduled_hours"], 12.00, "scheduled_hours")
    assert_int(created["version"], 1, "version")

    lit = validate_success(api.light_kiln_run(run_id, OPERATOR_HEADERS))
    assert lit["process_state"] == "BURNING"
    assert_instant_equals(lit["lit_at"], "2026-08-01T00:00:00.000Z", "lit_at")
    assert validate_success(api.get_kiln_run(run_id, OPERATOR_HEADERS)) == lit, (
        "the read that follows the action repeats it field for field"
    )

    charged = validate_success(
        api.charge_fuel(
            run_id,
            f.fuel_charge_payload(env["fuels"]["gas"]["id"], 45.00),
            OPERATOR_HEADERS,
        )
    )
    assert len(charged["fuel_charges"]) == 1
    assert_amount(charged["fuel_charges"][0]["energy_gj"], 2160.00, "energy_gj")
    assert_amount(charged["gross_energy_gj"], 2160.00, "gross_energy_gj")
    assert_amount(
        charged["provisional_clinker_tonnes"], 600.00, "provisional_clinker_tonnes"
    )
    assert_amount(
        charged["effective_shc_gj_per_tonne"], 3.70, "effective_shc_gj_per_tonne"
    )
    assert_amount(charged["clinker_tonnes"], 583.78, "clinker_tonnes")
    assert_amount(charged["nox_emitted_kg"], 216.00, "nox_emitted_kg")
    assert_intensity(
        charged["nox_intensity_kg_per_tonne"], 0.370, "nox_intensity_kg_per_tonne"
    )
    assert validate_success(api.get_kiln_run(run_id, OPERATOR_HEADERS)) == charged, (
        "the charge response is already the settled row"
    )
