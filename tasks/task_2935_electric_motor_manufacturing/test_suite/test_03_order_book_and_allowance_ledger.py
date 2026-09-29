"""The commercial order book: the allowance ledger and the cancellation cascade."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_DESIGN_NOT_RELEASED,
    ERR_STOCK_ALLOWANCE_EXCEEDED,
)


def _plant_in_production(plant):
    """A confirmed 12-unit order with a work order, an impregnated stator and a
    machined rotor on the shop floor."""
    plant.add_distributor()
    plant.add_oven()
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    plant.add_stator()
    plant.impregnate_stator()
    plant.add_rotor()
    plant.form_cage()
    plant.machine_rotor()
    return plant


def test_order_cancellation_scraps_the_work_order_and_both_subassemblies(plant):
    """One cancel call walks order to work order to stator and rotor.

    PRD 3.4: "In the second hop, caused by the first, each of those newly
    cancelled work orders has its subassemblies written off: every stator build
    on it whose status is neither `REJECTED` nor `SCRAPPED` moves to `SCRAPPED`,
    then every rotor build on it whose status is neither `REJECTED` nor
    `SCRAPPED` moves to `SCRAPPED`, then every assembly record on it in `BUILT`
    status moves to `SCRAPPED`."

    Design: Difficulty/transitive_cascade/order_cancel_cascades_to_workorder_stator_and_oven_ledger
    """
    _plant_in_production(plant)
    assert plant.get_order()["status"] == "IN_PRODUCTION"

    cancelled = plant.cancel_order()

    assert cancelled["status"] == "CANCELLED"
    work_order = plant.get_work_order()
    assert work_order["build_status"] == "CANCELLED"
    assert work_order["certification_status"] == "PENDING"
    assert plant.get_stator()["status"] == "SCRAPPED"
    assert plant.get_rotor()["status"] == "SCRAPPED"
    assert work_order["rework_reject_count"] == 0


def test_order_cancellation_releases_the_oven_minutes_and_credits_the_allowance(plant):
    """The fourth level of the cascade is a ledger, not a status.

    PRD 3.4: "In the third hop, caused by the second, every curing oven that was
    holding one of those now-scrapped stator builds has its `booked_minutes`
    recomputed, because a scrapped build has left the counted status set, and
    that oven's `version` is incremented."

    Design: Difficulty/transitive_cascade/order_cancel_cascades_to_workorder_stator_and_oven_ledger
    """
    _plant_in_production(plant)
    oven_before = plant.get_oven()
    assert oven_before["booked_minutes"] == 240
    distributor_before = plant.get_distributor()
    assert distributor_before["units_outstanding"] == 12
    assert distributor_before["stock_allowance_remaining_units"] == 488

    plant.cancel_order()

    oven_after = plant.get_oven()
    assert oven_after["booked_minutes"] == 0
    assert oven_after["version"] > oven_before["version"]
    distributor_after = plant.get_distributor()
    assert distributor_after["units_outstanding"] == 0
    assert distributor_after["stock_allowance_remaining_units"] == 500
    scrapped = plant.get_stator()
    assert scrapped["oven_id"] == plant.oven["id"]
    assert scrapped["impregnation_minutes"] == 240


def test_design_not_released_outranks_the_stock_allowance_ceiling_on_confirm(
    api, plant
):
    """A reopened design masks a quantity that already exceeds the allowance.

    PRD 2.11: "Cross-entity referential rules are next, in this order: design
    release status (`ERR_DESIGN_NOT_RELEASED`), stocking enrolment
    (`ERR_STOCKING_PROGRAM_NOT_ENROLLED`), rotor construction match
    (`ERR_ROTOR_CONSTRUCTION_MISMATCH`), insulation-system match
    (`ERR_INSULATION_SYSTEM_MISMATCH`), rotor bar-count match
    (`ERR_ROTOR_BAR_COUNT_MISMATCH`) and jurisdiction match
    (`ERR_JURISDICTION_MISMATCH`)."

    Design: Difficulty/priority_pair_validation_conflict/design_not_released_outranks_stock_allowance_exceeded_on_confirm
    """
    plant.add_distributor(committed_annual_units=10)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    order = plant.add_order(quantity=12, requested_ship_date="2026-12-01")
    plant.open_revision()

    refused = api.confirm_customer_order(order["id"], {}, U.PRODUCTION_PLANNER)

    validate_error(refused, ERR_DESIGN_NOT_RELEASED, 409)
    assert refused.json()["data"]["error_id"] != ERR_STOCK_ALLOWANCE_EXCEEDED
    stored = plant.get_order(order)
    assert stored["status"] == "DRAFT"
    assert stored["confirmed_at"] is None
    distributor = plant.get_distributor()
    assert distributor["units_outstanding"] == 0
    assert distributor["stock_allowance_remaining_units"] == 10


def test_re_releasing_the_design_exposes_the_masked_allowance_rejection(api, plant):
    """With the referential rule satisfied, the quota rule finally speaks.

    PRD 3.4: "Lastly, `quantity` must be no greater than the distributor's
    `stock_allowance_remaining_units` — a quantity exactly equal to the
    remainder is allowed, one unit more is refused with
    `ERR_STOCK_ALLOWANCE_EXCEEDED` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/design_not_released_outranks_stock_allowance_exceeded_on_confirm
    """
    plant.add_distributor(committed_annual_units=10)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    order = plant.add_order(quantity=12, requested_ship_date="2026-12-01")
    plant.open_revision()
    validate_error(
        api.confirm_customer_order(order["id"], {}, U.PRODUCTION_PLANNER),
        ERR_DESIGN_NOT_RELEASED,
        409,
    )
    plant.submit_design()
    rereleased = plant.decide_design("APPROVE")
    assert rereleased["status"] == "RELEASED"
    assert rereleased["revision_index"] == 1

    refused = api.confirm_customer_order(order["id"], {}, U.PRODUCTION_PLANNER)

    validate_error(refused, ERR_STOCK_ALLOWANCE_EXCEEDED, 422)
    stored = plant.get_order(order)
    assert stored["status"] == "DRAFT"
    assert stored["confirmed_at"] is None
    distributor = plant.get_distributor()
    assert distributor["units_outstanding"] == 0
    assert distributor["stock_allowance_remaining_units"] == 10


def _assert_allowance_identity(distributor, committed, outstanding):
    """Outstanding plus remaining always equals the committed volume."""
    assert distributor["committed_annual_units"] == committed
    assert distributor["units_outstanding"] == outstanding
    assert distributor["stock_allowance_remaining_units"] == committed - outstanding
    assert (
        distributor["units_outstanding"]
        + distributor["stock_allowance_remaining_units"]
        == distributor["committed_annual_units"]
    )


def test_allowance_is_conserved_across_confirm_cancel_confirm(api, plant):
    """A cancelled confirmation leaves the ledger exactly where it started.

    PRD 2.10: "A distributor's `units_outstanding` and
    `stock_allowance_remaining_units` always satisfy the identity that
    outstanding units plus remaining allowance equals `committed_annual_units`.
    Confirming an order debits the allowance; cancelling or fulfilling the same
    order credits back exactly the same quantity."

    Design: Difficulty/compensating_invariant/distributor_allowance_conserved_across_confirm_cancel_confirm_to_the_exact_limit
    """
    plant.add_distributor(committed_annual_units=20)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    first = plant.add_order(quantity=12)
    second = plant.add_order(quantity=12)
    _assert_allowance_identity(plant.get_distributor(), 20, 0)

    plant.confirm_order(first)
    _assert_allowance_identity(plant.get_distributor(), 20, 12)
    blocked = api.confirm_customer_order(second["id"], {}, U.PRODUCTION_PLANNER)
    validate_error(blocked, ERR_STOCK_ALLOWANCE_EXCEEDED, 422)
    _assert_allowance_identity(plant.get_distributor(), 20, 12)

    cancelled = plant.cancel_order(first)

    assert cancelled["status"] == "CANCELLED"
    _assert_allowance_identity(plant.get_distributor(), 20, 0)
    confirmed = plant.confirm_order(second)
    assert confirmed["status"] == "CONFIRMED"
    _assert_allowance_identity(plant.get_distributor(), 20, 12)


def test_confirming_the_exact_remaining_allowance_is_accepted_and_one_more_is_not(
    api, plant
):
    """Eight units against a remainder of eight pass; the next single unit fails.

    PRD 3.4: "Lastly, `quantity` must be no greater than the distributor's
    `stock_allowance_remaining_units` — a quantity exactly equal to the
    remainder is allowed, one unit more is refused with
    `ERR_STOCK_ALLOWANCE_EXCEEDED` (HTTP 422)."

    Design: Difficulty/compensating_invariant/distributor_allowance_conserved_across_confirm_cancel_confirm_to_the_exact_limit
    """
    plant.add_distributor(committed_annual_units=20)
    plant.add_design(F.motor_design_payload())
    plant.release_design()
    plant.confirm_order(plant.add_order(quantity=12))
    exact = plant.add_order(quantity=8)
    one_more = plant.add_order(quantity=1)

    filled = plant.confirm_order(exact)

    assert filled["status"] == "CONFIRMED"
    assert filled["confirmed_at"] == F.CLOCK_START
    _assert_allowance_identity(plant.get_distributor(), 20, 20)
    refused = api.confirm_customer_order(one_more["id"], {}, U.PRODUCTION_PLANNER)
    validate_error(refused, ERR_STOCK_ALLOWANCE_EXCEEDED, 422)
    assert plant.get_order(one_more)["status"] == "DRAFT"
    _assert_allowance_identity(plant.get_distributor(), 20, 20)
