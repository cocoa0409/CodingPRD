"""Container receipt, shelf waterfall and apportioned freight — the three-regime instance.

One received container's freight interacts with three different per-item bases, so the
same receipt produces a covered item, a queued-for-deletion item, and a cured item whose
loss is reported without being queued.
"""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    assert_item_cost_invariants,
    get_success_data,
    validate_error,
    validate_success,
    E,
    fixtures,
)



def _three_items_on_one_container(api):
    """A 125-cent point, one vendor and three items sharing a received container.

    The container carries 200 cents of freight over 80 allocable units, so the rate floors
    to 2 cents per unit. Each item then lands at its own base plus 2.
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    # The cure join is pinned on vendor AND price point AND status (PRD §3.4); a single
    # ACTIVE pack would therefore cure EVERY item resting on its price point. The cured
    # item must sit on a distinct price point so that only it is covered by the pack,
    # leaving the losing item on the pack-free point to queue for deletion review.
    cure_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25_EXCLUSIVE")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()

    # An ACTIVE exclusive pack aimed at the cure item's own price point cures it alone.
    fixtures.create_active_pack_program(vendor["id"], cure_point["id"])

    shared = {"unit_retail_cents": 125, "units_per_case": 4, "fixed_store_handling_cents": 6,
              "variable_store_cost_cents": 4, "sqft_per_unit": 0.1,
              "shelf_package_capacity": 4.0}
    covered = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3001", base_landed_cost_cents=105, **shared)
    losing = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="3002", base_landed_cost_cents=125, **shared)
    cured = fixtures.create_price_assigned_item(
        cure_point["id"], vendor["id"], sku="3003", base_landed_cost_cents=125, **shared)

    container, lines = fixtures.build_received_container(
        vendor["id"], store["id"],
        [
            {"item_id": covered["id"], "sequence": 1, "requested_units": 300},
            {"item_id": losing["id"], "sequence": 2, "requested_units": 200},
        ],
        total_freight_cents=200,
    )
    return {
        "price_point": price_point, "vendor": vendor, "store": store,
        "container": container, "lines": lines,
        "covered": covered, "losing": losing, "cured": cured,
    }


def test_one_receipt_produces_an_absorbed_a_queued_and_a_cured_item(api):
    """The same 2-cent freight rate drives three different item fates.

    PRD §3.2: "Every item receiving a pass-through from that container is then charged the same
    rate: its `applied_amount_cents` is its `base_landed_cost_cents` plus that one
    container-wide `freight_per_unit_cents`."
    PRD §3.4: "If no such pack exists, the item is pushed automatically from `COST_PENDING` into
    `DELETE_REVIEW` — this transition is reached from the landed-cost write's own side-effect
    chain and is never triggered by a direct client call."
    PRD §3.4: "If such a pack does exist, the item stays in `COST_PENDING` and the response
    reports the loss with `ERR_COST_EXCEEDS_PRICE_POINT` and HTTP 422, so the buying office sees
    the miss without the item being queued for deletion."
    PRD §3.3: "The first is `net_contribution_cents_per_unit`, a signed integer computed as the
    item's `unit_retail_cents` minus its `landed_cost_cents` minus its
    `variable_store_cost_cents`."

    Design: Difficulty/dual_variant_calc/freight_passthrough_three_regimes_same_freight
    """
    world = _three_items_on_one_container(api)
    container = world["container"]

    # The waterfall caps each line at the item's shelf: 300 and 200 both exceed 40 units,
    # so the container's allocable total is exactly 80 and the rate floors to 2 cents.
    assert [line["allocated_units"] for line in world["lines"]] == [40, 40]

    validate_success(
        api.apply_landed_cost(
            world["covered"]["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
             "container_id": container["id"]},
            BUYER_HEADERS,
        ),
        201,
    )
    validate_success(
        api.apply_landed_cost(
            world["losing"]["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 127,
             "container_id": container["id"]},
            BUYER_HEADERS,
        ),
        201,
    )
    cured_response = api.apply_landed_cost(
        world["cured"]["id"],
        {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 127,
         "container_id": container["id"]},
        BUYER_HEADERS,
    )
    validate_error(cured_response, E.ERR_COST_EXCEEDS_PRICE_POINT.value)

    covered = validate_success(api.get_item(world["covered"]["id"], ANALYST_HEADERS), 200)
    assert_item_cost_invariants(covered)
    assert covered["landed_cost_cents"] == 107
    assert covered["net_contribution_cents_per_unit"] == 14
    assert covered["break_even_units"] == 4
    assert covered["status"] == "COST_PENDING"

    losing = validate_success(api.get_item(world["losing"]["id"], ANALYST_HEADERS), 200)
    assert losing["landed_cost_cents"] == 127
    assert losing["net_contribution_cents_per_unit"] == -6
    assert losing["status"] == "DELETE_REVIEW"

    cured = validate_success(api.get_item(world["cured"]["id"], ANALYST_HEADERS), 200)
    assert cured["landed_cost_cents"] == 127
    assert cured["net_contribution_cents_per_unit"] == -6, (
        "the cured item carries the same loss as the queued one — the cure changes its fate, "
        "not its arithmetic"
    )
    assert cured["status"] == "COST_PENDING"


def test_the_same_receipt_is_refused_before_receipt_and_from_a_foreign_vendor(api):
    """Freight is gated on the container's receipt state and on its vendor.

    PRD §3.2: "The container must be in `RECEIVED`; a pass-through naming a container that is
    not is rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409."
    PRD §3.2: "The container must also belong to the same vendor the item is sourced from — the
    container's vendor must equal the item's sourcing vendor — and a mismatch is rejected with
    `ERR_CONTAINER_VENDOR_MISMATCH` and HTTP 409."
    PRD §3.2: "A vendor price change is subject to neither gate because it references no
    container."

    Design: Difficulty/dual_variant_calc/freight_passthrough_three_regimes_same_freight
    """
    world = _three_items_on_one_container(api)
    item_id = world["covered"]["id"]

    # A container from the item's own vendor that has only been discharged at the port.
    at_port = fixtures.create_container_at_port(world["vendor"]["id"], total_freight_cents=200)
    validate_error(
        api.apply_landed_cost(
            item_id,
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
             "container_id": at_port["id"]},
            BUYER_HEADERS,
        ),
        E.ERR_CONTAINER_NOT_RECEIVED.value,
    )

    # A container that has been received, but belongs to a different vendor.
    other_vendor = fixtures.create_vendor(vendor_name="Ho Chi Minh Plastics", country_of_origin="VN")
    foreign = fixtures.create_received_container(other_vendor["id"], total_freight_cents=200)
    validate_error(
        api.apply_landed_cost(
            item_id,
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
             "container_id": foreign["id"]},
            BUYER_HEADERS,
        ),
        E.ERR_CONTAINER_VENDOR_MISMATCH.value,
    )

    # Neither refusal wrote a cost row, and the vendor revision is not gated at all.
    assert get_success_data(api.list_item_landed_costs(item_id, ANALYST_HEADERS)) == []
    state = validate_success(api.get_item(item_id, ANALYST_HEADERS), 200)
    assert state["status"] == "PRICE_ASSIGNED"
    assert state["landed_cost_cents"] == 0