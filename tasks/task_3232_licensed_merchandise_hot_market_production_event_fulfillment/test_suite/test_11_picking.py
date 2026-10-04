"""Picking units from the shared pool."""
import pytest

from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers.fixtures import (
    FULFILLMENT,
    PLANNER,
    committed_run,
    create_design,
    create_licensor,
    create_order,
    create_run,
    get_order,
    get_run,
    pick_order,
    set_clock,
)


def test_a_pick_moves_the_order_and_advances_the_run_version(api):
    """PRD §3.5: "A successful pick adds its `quantity` to the order's
    `picked_qty`, moves `status` to `PICKED`, and increments the referenced run's
    `version` by exactly 1, refreshing the run's `updated_at`."

    Design: Corner/consistency_model/pick_response_carries_every_immediate_side_effect
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-15", quantity=20)
    version_before = setup["run"]["version"]

    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": version_before,
            "quantity": 20,
            "pick_remark": "pick-ap",
        },
        FULFILLMENT,
    )
    picked = validate_success(resp, expected_status=200)

    assert picked["status"] == "PICKED"
    assert picked["picked_qty"] == 20
    assert get_run(api, setup["run"]["id"])["version"] > version_before


def test_a_repeated_pick_remark_is_refused(api):
    """PRD §3.5: "`pick_remark` must differ from every remark already recorded on
    any prior pick of the same order, and a repeat is rejected with
    `ERR_PICK_REMARK_REUSED` (HTTP 409)."

    Design: Corner/state_machines/fulfillment_delivered_is_terminal
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-15", quantity=40)
    pick_order(api, order, setup["run"]["id"], 20, "pick-one")

    version = get_run(api, setup["run"]["id"])["version"]
    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": version,
            "quantity": 20,
            "pick_remark": "pick-one",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_PICK_REMARK_REUSED, expected_status=409)


def test_picking_more_than_the_reference_pool_holds_is_refused(api):
    """PRD §3.5: "The `quantity` must not exceed the available units of the
    reference pool, where that pool is measured by the requested quantity of the
    run's earliest shipment ordered by its `committed_at` stamp ... and a pick
    that exceeds it is rejected with `ERR_INVENTORY_INSUFFICIENT` (HTTP 409)."

    Design: Corner/state_machines/fulfillment_delivered_is_terminal
    """
    set_clock(api)
    setup = committed_run(api, base_qty=2000)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-16", quantity=20)
    version = get_run(api, setup["run"]["id"])["version"]

    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": version,
            "quantity": 25,
            "pick_remark": "pick-over",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVENTORY_INSUFFICIENT,
                   expected_status=409)


def test_a_stale_run_version_blocks_the_pick(api):
    """PRD §3.5: "The optimistic-concurrency check then compares
    `expected_production_order_version` against the referenced run's current
    `version` and rejects a mismatch with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/pick_with_stale_run_version_is_rejected
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    first = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-11", quantity=20)
    second = create_order(api, setup["run"], channel="ECOM",
                          destination_code="ECOM-ATL-12", quantity=20)

    version_before = setup["run"]["version"]
    pick_order(api, first, setup["run"]["id"], 20, "pick-aj1")

    resp = api.pick(
        second["id"],
        {
            "expected_production_order_version": version_before,
            "quantity": 20,
            "pick_remark": "pick-aj2",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    read = get_order(api, second["id"])
    assert read["status"] == "PLANNED"
    assert read["picked_qty"] == 0


def test_picking_a_distressed_order_is_refused(api):
    """PRD §3.5: "The order picks only from `PLANNED`."
    PRD §3.5: "picking units and then shipping them out of a run that is no
    longer `COMMITTED` or `PRINTING` is likewise `ERR_INVALID_STATE` (HTTP 409)"

    Design: Corner/errors/lot_exhausted_when_every_unit_is_already_moved
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-BOS-4", quantity=20)
    validate_success(
        api.distress(
            order["id"],
            {"distress_reason": "DEMAND_COLLAPSE", "destroy_mode": "DESTROY"},
            FULFILLMENT,
        ),
        expected_status=200,
    )
    version = get_run(api, setup["run"]["id"])["version"]

    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": version,
            "quantity": 5,
            "pick_remark": "pick-ad",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    read = get_order(api, order["id"])
    assert read["status"] == "DISTRESSED"
    assert read["picked_qty"] == 0


@pytest.mark.parametrize("quantity", [0, -3])
def test_a_non_positive_pick_quantity_is_a_shape_failure(api, quantity):
    """PRD §2.10: "a numeric field that must be strictly positive supplied as zero
    or negative"

    Design: Corner/entities/production_order_requires_design_id
    """
    set_clock(api)
    setup = committed_run(api, base_qty=40)
    order = create_order(api, setup["run"], channel="ECOM",
                         destination_code="ECOM-ATL-17", quantity=20)

    resp = api.pick(
        order["id"],
        {
            "expected_production_order_version": setup["run"]["version"],
            "quantity": quantity,
            "pick_remark": "pick-zero",
        },
        FULFILLMENT,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_a_run_whose_artwork_is_uncleared_stays_in_parallel_hold(api):
    """PRD §3.2: "Creating the run also requires that the referenced licensor
    exists and that the referenced design exists with an `APPROVED` clearance"
    PRD §3.3: "a design in `PENDING_LICENSOR_APPROVAL` or `APPROVAL_REJECTED`
    fails the request with `ERR_DESIGN_NOT_APPROVED` (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/fulfillment_pick_requires_approved_design
    """
    set_clock(api)
    licensor = create_licensor(api, name="NBL Xref 2", royalty_rate_pct=0.1)
    pending = create_design(api, licensor, team_code="ATL", garment_sku="CAP",
                            design_name="ATL Pending Cap", approve=False)
    cleared = create_design(api, licensor, team_code="BOS", garment_sku="CAP",
                            design_name="BOS Cleared Cap")
    assert pending["approval_state"] == "PENDING_LICENSOR_APPROVAL"

    cleared_run = create_run(api, licensor, cleared, team_code="BOS")
    validate_success(
        api.author_layers(
            cleared_run["id"],
            {
                "expected_production_order_version": cleared_run["version"],
                "layers": [{"design_id": cleared["id"], "print_type": "BASE",
                            "quantity": 20}],
            },
            PLANNER,
        ),
        expected_status=200,
    )

    # Artwork the licensor has not cleared cannot carry a run at all, so the
    # uncleared side of the pair is refused when the run is opened.
    resp = api.create_production_order(
        {
            "licensor_id": licensor["id"], "design_id": pending["id"],
            "team_code": "ATL", "trigger_type": "STANDARD",
            "expected_demand_qty": 5000, "unit_cost_cents": 900,
        },
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DESIGN_NOT_APPROVED)

    assert get_run(api, cleared_run["id"])["status"] == "COMMITTED"