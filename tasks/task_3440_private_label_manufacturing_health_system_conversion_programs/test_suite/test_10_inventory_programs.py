"""Inventory programs: position constraints, stock events, reorder suggestion."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_inventory_program,
    create_agreement,
    create_facility,
    create_inventory_program,
    create_inventory_program_payload,
    create_product,
    find_position,
    get_inventory_program,
    place_order,
    record_stock_event,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def test_program_create_par_violation_422(api):
    """PRD §3.9: "a `reorder_point` of 0 or more that must not exceed its
    `par_level` — a position whose reorder point sits above its par level
    rejects the creation with `ERR_PAR_LEVEL_VIOLATION` (HTTP 422)".

    Design: Corner/entities/inventory_program_create_par_violation_rejected
    """
    facility = create_facility()
    product = create_product(sku="IP-1")
    resp = api.create_inventory_program(
        create_inventory_program_payload(
            facility["id"],
            [{"product_id": product["id"], "par_level": 10, "reorder_point": 20,
              "on_hand": 5}],
            program_type="CRASH_CART",
        ),
        headers=ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_PAR_LEVEL_VIOLATION.value, 422)


def test_duplicate_program_position_409(api):
    """PRD §3.9: "no `product_id` may repeat within the `positions` array
    (`ERR_DUPLICATE_POSITION`, HTTP 409)".

    Design: Corner/validations/duplicate_program_position_rejected
    """
    facility = create_facility()
    product = create_product(sku="DP-P1")
    resp = api.create_inventory_program(
        create_inventory_program_payload(
            facility["id"],
            [
                {"product_id": product["id"], "par_level": 10,
                 "reorder_point": 5, "on_hand": 8},
                {"product_id": product["id"], "par_level": 20,
                 "reorder_point": 6, "on_hand": 3},
            ],
            program_type="OR_CORE",
        ),
        headers=ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_POSITION.value, 409)


def test_stock_negative_422(api):
    """PRD §3.9: "the event applies the delta to the position's `on_hand`, which
    may never go negative — an adjustment that would drive it below 0 is
    rejected with `ERR_STOCK_INSUFFICIENT` (HTTP 422)".

    Design: Corner/validations/stock_negative_rejected
    """
    facility = create_facility()
    product = create_product(sku="SN-1")
    program = create_inventory_program(
        facility["id"],
        [{"product_id": product["id"], "par_level": 100, "reorder_point": 10,
          "on_hand": 50}],
        program_type="CRASH_CART",
    )
    resp = api.record_stock_event(
        program["id"],
        {"product_id": product["id"], "quantity_delta": -60, "event_type": "ISSUE"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_STOCK_INSUFFICIENT.value, 422)
    reread = get_inventory_program(program["id"])
    assert find_position(reread, product["id"])["on_hand"] == 50


def test_stock_event_unknown_position_422(api):
    """PRD §3.9: "The program must hold a position for that product, otherwise
    `ERR_POSITION_NOT_FOUND` (HTTP 422)". PRD §2.9: "a `product_id` that names
    a real catalog product but for which the targeted program holds no position
    is not a 404 — the call is rejected with `ERR_POSITION_NOT_FOUND`
    (HTTP 422)".

    Design: Corner/validations/stock_event_unknown_position_rejected
    """
    facility = create_facility()
    positioned = create_product(sku="UP-X")
    unpositioned = create_product(sku="UP-Y")
    program = create_inventory_program(
        facility["id"],
        [{"product_id": positioned["id"], "par_level": 100, "reorder_point": 10,
          "on_hand": 50}],
        program_type="CRASH_CART",
    )
    resp = api.record_stock_event(
        program["id"],
        {"product_id": unpositioned["id"], "quantity_delta": 10,
         "event_type": "RECEIPT"},
        ADMIN,
    )
    validate_error(resp, ApiErrorId.ERR_POSITION_NOT_FOUND.value, 422)


def test_reorder_suggestion_deducts_pipeline(api):
    """PRD §3.9: "First, the open pipeline for the position's product: the sum,
    over the facility's agreement's orders in `PLACED` or `PARTIALLY_SHIPPED`
    status, of each line's ordered quantity minus shipped quantity for that
    product" and "otherwise it is the raw need minus the open pipeline, floored
    at 0, and — only when that floored value is greater than 0 — rounded up to
    the next multiple of the product's `order_multiple`, with 0 staying 0."
    max(0, 100-20-30) = 50, rounded up to a multiple of 6 -> 54.

    Design: Corner/calculations/reorder_suggestion_deducts_pipeline
    """
    facility = create_facility()
    product = create_product(sku="RS-1", order_multiple=6, each_price_cents=10)
    agreement = create_agreement(facility["id"], committed_fill_rate_pct=90.0)
    program = create_inventory_program(
        facility["id"],
        [{"product_id": product["id"], "par_level": 100, "reorder_point": 25,
          "on_hand": 20}],
    )
    place_order(
        agreement["id"], facility["id"],
        [{"product_id": product["id"], "ordered_qty": 30}],
    )
    reread = get_inventory_program(program["id"])
    position = find_position(reread, product["id"])
    assert position["reorder_status"] == "DUE"  # 20 <= 25
    assert position["suggested_order_qty"] == 54


def test_reorder_point_inclusive_boundary(api):
    """PRD §3.9: "`reorder_status` is `CRITICAL` when `on_hand` is exactly 0;
    otherwise `DUE` when `on_hand` is at or below the `reorder_point` — a
    position sitting exactly at its reorder point is already `DUE`; otherwise
    `OK`." PA lands exactly on its reorder point (DUE); PB sits one above (OK).

    Design: Difficulty/boundary_precision_check/reorder_point_inclusive_boundary_and_zero_critical
    """
    facility = create_facility()
    pa = create_product(sku="IA-1", each_price_cents=10)
    pb = create_product(sku="IB-1", each_price_cents=10)
    pc = create_product(sku="IC-1", each_price_cents=10)
    program = create_inventory_program(
        facility["id"],
        [
            {"product_id": pa["id"], "par_level": 50, "reorder_point": 25,
             "on_hand": 30},
            {"product_id": pb["id"], "par_level": 50, "reorder_point": 25,
             "on_hand": 26},
            {"product_id": pc["id"], "par_level": 10, "reorder_point": 5,
             "on_hand": 5},
        ],
        program_type="CRASH_CART",
    )
    record_stock_event(program["id"], pa["id"], -5, "ISSUE")  # 30 -> 25
    reread = get_inventory_program(program["id"])
    pos_a = find_position(reread, pa["id"])
    assert pos_a["on_hand"] == 25
    assert pos_a["reorder_status"] == "DUE"  # inclusive: on_hand == reorder_point
    assert pos_a["suggested_order_qty"] == 25
    pos_b = find_position(reread, pb["id"])
    assert pos_b["on_hand"] == 26
    assert pos_b["reorder_status"] == "OK"
    assert pos_b["suggested_order_qty"] == 24


def test_reorder_zero_on_hand_critical(api):
    """PRD §3.9: "`reorder_status` is `CRITICAL` when `on_hand` is exactly 0" —
    a five-unit ISSUE against on_hand 5 drives the position to 0, and the raw
    need (par 10 - 0) with an empty pipeline suggests the full 10.

    Design: Difficulty/boundary_precision_check/reorder_point_inclusive_boundary_and_zero_critical
    """
    facility = create_facility()
    pc = create_product(sku="IC-9", each_price_cents=10)
    program = create_inventory_program(
        facility["id"],
        [{"product_id": pc["id"], "par_level": 10, "reorder_point": 5,
          "on_hand": 5}],
        program_type="CRASH_CART",
    )
    updated = record_stock_event(program["id"], pc["id"], -5, "ISSUE")
    assert_inventory_program(updated)
    pos = find_position(updated, pc["id"])
    assert pos["on_hand"] == 0
    assert pos["reorder_status"] == "CRITICAL"
    assert pos["suggested_order_qty"] == 10


def test_stock_issue_receipt_pair_conserves(api):
    """PRD §3.9: "Stock moves are recorded as events by a `SupplyChainAdmin`: a
    `product_id`, a signed `quantity_delta`, and an `event_type` of `RECEIPT`,
    `ISSUE`, or `CYCLE_COUNT_ADJUST`." PRD §3.9: "The program must hold a
    position for that product, otherwise `ERR_POSITION_NOT_FOUND` (HTTP 422),
    and the event applies the delta to the position's `on_hand`, which may never
    go negative — an adjustment that would drive it below 0 is rejected with
    `ERR_STOCK_INSUFFICIENT` (HTTP 422)." A -30 ISSUE paired with a +30 RECEIPT
    restores on_hand exactly: 50 -> 20 -> 50.

    Design: Difficulty/compensating_invariant/stock_issue_receipt_pair_conserves_on_hand
    """
    facility = create_facility()
    product = create_product(sku="KX-1", each_price_cents=10)
    program = create_inventory_program(
        facility["id"],
        [{"product_id": product["id"], "par_level": 100, "reorder_point": 10,
          "on_hand": 50}],
        program_type="OR_CORE",
    )
    after_issue = record_stock_event(program["id"], product["id"], -30, "ISSUE")
    assert find_position(after_issue, product["id"])["on_hand"] == 20
    after_pair = record_stock_event(program["id"], product["id"], 30, "RECEIPT")
    assert find_position(after_pair, product["id"])["on_hand"] == 50


def test_stock_adjust_pair_conserves(api):
    """PRD §3.9: "the event applies the delta to the position's `on_hand`" —
    the conserved quantity satisfies on_hand == initial + sum(quantity_delta)
    with zero drift across the full ISSUE/RECEIPT and ADJUST/ADJUST sequence:
    50 == 50 + (-30 + 30) + (-5 + 5).

    Design: Difficulty/compensating_invariant/stock_issue_receipt_pair_conserves_on_hand
    """
    facility = create_facility()
    product = create_product(sku="KX-2", each_price_cents=10)
    program = create_inventory_program(
        facility["id"],
        [{"product_id": product["id"], "par_level": 100, "reorder_point": 10,
          "on_hand": 50}],
        program_type="OR_CORE",
    )
    record_stock_event(program["id"], product["id"], -30, "ISSUE")
    record_stock_event(program["id"], product["id"], 30, "RECEIPT")
    after_adj_down = record_stock_event(
        program["id"], product["id"], -5, "CYCLE_COUNT_ADJUST"
    )
    assert find_position(after_adj_down, product["id"])["on_hand"] == 45
    final = record_stock_event(program["id"], product["id"], 5, "CYCLE_COUNT_ADJUST")
    assert find_position(final, product["id"])["on_hand"] == 50
    reread = get_inventory_program(program["id"])
    assert find_position(reread, product["id"])["on_hand"] == 50
