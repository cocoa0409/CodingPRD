"""Difficulty queue: PRO_RATA waterfall vs FIFO shortage allocation."""
from test_helpers import (
    get_lot, get_order, make_customer, make_customer_headers, place_order,
    setup_lot_in_distribution, validate_success,
)


def _setup_shortage(api, allocation_policy, program_code, material_code):
    """Lot (12 produced, 4 qc -> 8 usable) IN_DISTRIBUTION under the given
    policy; O_BIG (GENERAL) qty 7 -> ALLOCATED 7, then three qty-4 orders from
    FEDERAL / ACCREDITED_LAB / GENERAL customers sharing the last unit."""
    ctx = setup_lot_in_distribution(
        total=12, material_code=material_code, allocation_policy=allocation_policy,
        program_overrides={"program_code": program_code})
    lot_id = ctx["lot"]["id"]
    c_big = make_customer(name="Big General", tier="GENERAL")
    c_f = make_customer(name="Fed Agency", tier="FEDERAL")
    c_a = make_customer(name="Acc Lab", tier="ACCREDITED_LAB")
    c_g = make_customer(name="Small General", tier="GENERAL")
    o_big = place_order(lot_id, c_big["id"], 7)
    o_f = place_order(lot_id, c_f["id"], 4)
    o_a = place_order(lot_id, c_a["id"], 4)
    o_g = place_order(lot_id, c_g["id"], 4)
    assert o_big["status"] == "ALLOCATED" and o_big["allocated_quantity"] == 7
    assert o_f["allocated_quantity"] == 1 and o_f["status"] == "BACKORDERED"
    assert o_a["allocated_quantity"] == 0 and o_a["status"] == "BACKORDERED"
    assert o_g["allocated_quantity"] == 0 and o_g["status"] == "BACKORDERED"
    released = validate_success(
        api.transition_sales_order(o_big["id"], {"to": "BACKORDERED"},
                                   make_customer_headers(c_big["id"])))
    assert released["status"] == "BACKORDERED"
    return {"ctx": ctx, "o_big": o_big, "o_f": o_f, "o_a": o_a, "o_g": o_g}


def test_pro_rata_weighted_shares(api):
    """PRD §3.5: "each candidate's weight comes from its customer's tier —
    `FEDERAL` weighs 3, `ACCREDITED_LAB` 2, `GENERAL` 1 — and each candidate's
    share is the smaller of its open need and the pool multiplied by its weight
    times its open need, divided by the sum over all candidates of weight times
    open need, that product rounded down to whole units; the leftover pool after
    shares are applied is then dealt out one unit at a time, cycling candidates
    ordered by weight descending, then `created_at` ascending, then `quantity`
    ascending".

    Design: Difficulty/combinatorial_formula/pro_rata_allocation_waterfall
    """
    st = _setup_shortage(api, "PRO_RATA", "NIST-RM-03", "SRM-D")
    o_f = get_order(st["o_f"]["id"])
    o_a = get_order(st["o_a"]["id"])
    o_g = get_order(st["o_g"]["id"])
    assert o_f["allocated_quantity"] == 4 and o_f["status"] == "ALLOCATED"
    assert o_a["allocated_quantity"] == 3 and o_a["status"] == "BACKORDERED"
    assert o_g["allocated_quantity"] == 1 and o_g["status"] == "BACKORDERED"


def test_pro_rata_releaser_excluded_and_lot_counters(api):
    """PRD §3.5: "a sweep triggered by an order release excludes the released
    order itself from candidacy in that run".
    PRD §3.2: "its `units_available` always derives as the produced total minus
    those three counters."

    Design: Difficulty/combinatorial_formula/pro_rata_allocation_waterfall
    """
    st = _setup_shortage(api, "PRO_RATA", "NIST-RM-03B", "SRM-D2")
    o_big = get_order(st["o_big"]["id"])
    assert o_big["allocated_quantity"] == 0
    assert o_big["status"] == "BACKORDERED"
    lot = get_lot(st["ctx"]["lot"]["id"])
    assert lot["units_reserved"] == 8
    assert lot["units_available"] == 0


def test_fifo_allocation_contrast(api):
    """PRD §3.5: "Under `FIFO`, candidates are visited in `created_at` ascending
    order with ties broken by `quantity` ascending — orders tied on both are
    interchangeable — and each takes the smaller of its open need and the
    remaining pool until the pool is exhausted or candidates run out."
    PRD §3.5: "a sweep triggered by an order release excludes the released order
    itself from candidacy in that run".

    Design: Corner/calculations/fifo_allocation_contrast
    """
    st = _setup_shortage(api, "FIFO", "NIST-RM-C22", "SRM-C22")
    o_f = get_order(st["o_f"]["id"])
    o_a = get_order(st["o_a"]["id"])
    o_g = get_order(st["o_g"]["id"])
    o_big = get_order(st["o_big"]["id"])
    assert o_f["allocated_quantity"] == 4 and o_f["status"] == "ALLOCATED"
    assert o_a["allocated_quantity"] == 4 and o_a["status"] == "ALLOCATED"
    assert o_g["allocated_quantity"] == 0 and o_g["status"] == "BACKORDERED"
    assert o_big["allocated_quantity"] == 0 and o_big["status"] == "BACKORDERED"
    lot = get_lot(st["ctx"]["lot"]["id"])
    assert lot["units_reserved"] == 8
    assert lot["units_available"] == 0
