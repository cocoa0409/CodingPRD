"""Feed procurement, hedging, receipt costing (FIFO, hedge-first), the mill
receiving aggregate-capacity rule, and the dual ACTUAL/STANDARD batch cost.
"""

import pytest

from test_helpers import (
    ADMIN,
    PROCUREMENT,
    api_client,
    create_complex,
    create_feed_batch_payload,
    create_feed_contract,
    hedge_feed_contract,
    make_complex_manager_headers,
    receive_feed,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


def _setup_dual_contract_complex(api):
    """'Mill West' with the hedged CORN contract (200t, receipts 120+80) and
    the unhedged SOYBEAN_MEAL contract (100t) both FILLED; clock 2026-09-05."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill West", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    corn = create_feed_contract(
        complex_["id"], commodity="CORN", total_tons=200,
        basis_cents_per_ton=2_000, spot_reference_cents_per_ton=17_000,
        delivery_start="2026-09-01T00:00:00Z",
        delivery_end="2026-10-01T00:00:00Z",
    )
    hedge_feed_contract(corn["id"], 100, 16_000)
    set_clock("2026-09-02T00:00:00Z")
    receive_feed(corn["id"], 120, 17_500)
    set_clock("2026-09-03T00:00:00Z")
    receive_feed(corn["id"], 80, 18_000)
    soy = create_feed_contract(
        complex_["id"], commodity="SOYBEAN_MEAL", total_tons=100,
        basis_cents_per_ton=3_000, spot_reference_cents_per_ton=34_000,
        delivery_start="2026-09-01T00:00:00Z",
        delivery_end="2026-09-15T00:00:00Z",
    )
    set_clock("2026-09-04T00:00:00Z")
    receive_feed(soy["id"], 100, 35_000)
    set_clock("2026-09-05T00:00:00Z")
    return complex_, corn, soy


def test_feed_batch_actual_and_standard_costs_diverge(api):
    """The same batch carries the FIFO-weighted ACTUAL figure and the
    constant STANDARD figure side by side.

    PRD §3.8: "`blended_cost_cents_per_ton` is the ton-weighted sum of the
    consumed contracts' `average_received_cost_cents_per_ton` — each contract
    weighted by the tons drawn from it, corn and soy contributions summed —
    divided by the total tons consumed, rounded half up to a whole cent per
    ton. From it, `actual_cost_per_dozen_cents` multiplies by four pounds of
    feed per dozen and divides by the two thousand pounds in a ton, rounded
    half up to two decimal places. `standard_cost_per_dozen_cents` instead
    uses the budgeted constant blend — sixty percent corn at 18,000 cents per
    ton and forty percent soybean meal at 36,000 cents per ton, a constant
    25,200 cents per ton — through the same conversion, yielding a constant
    50.40 cents per dozen regardless of market moves."

    Design: Difficulty/dual_variant_calc/feed_batch_actual_fifo_vs_standard_budget
    """
    complex_, _, _ = _setup_dual_contract_complex(api)

    batch = validate_success(
        api.create_feed_batch(
            complex_["id"],
            create_feed_batch_payload(
                program="CONVENTIONAL", corn_tons=60, soybean_tons=40
            ),
            make_complex_manager_headers(complex_["id"]),
        ),
        201,
    )
    # (60 * 18950 + 40 * 38000) / 100 = 26570, half-up to a whole cent/ton.
    assert batch["blended_cost_cents_per_ton"] == 26_570
    # 26570 * 4.0 / 2000 = 53.14 (half-up to two decimals).
    assert batch["actual_cost_per_dozen_cents"] == pytest.approx(53.14, abs=0.001)
    # The budgeted constant blend never moves.
    assert batch["standard_cost_per_dozen_cents"] == pytest.approx(50.40, abs=0.001)
    assert batch["tons_produced"] == 100


def test_feed_receipts_accumulate_hedge_first_and_credit_pools(api):
    """Hedged tons price the earliest receipts at futures+basis; the
    remainder prices at spot+basis; pools are credited and consumed.

    PRD §3.8: "Costing honors the hedge first: the hedged share of the
    receipt — the smaller of `tons` and the not-yet-applied hedge balance —
    prices at `hedge_futures_cents_per_ton` plus `basis_cents_per_ton`, and
    the remainder prices at the receipt's spot plus basis; the hedge applies
    to the earliest receipts first."
    PRD §3.8: "The matching complex pool — commodity crossed with the organic
    flag — gains the tons".

    Design: Difficulty/dual_variant_calc/feed_batch_actual_fifo_vs_standard_budget
    """
    complex_, corn, _ = _setup_dual_contract_complex(api)

    # 100 hedged tons at 18000 + 20 at 19500 = 2190000; then 80 at 20000.
    # total 3790000 over 200 tons -> 18950 half-up.
    rows, _ = validate_paginated(
        api.list_feed_contracts(
            complex_["id"],
            make_complex_manager_headers(complex_["id"]),
            params={"commodity": "CORN"},
        )
    )
    contract = rows[0]
    assert contract["id"] == corn["id"]
    assert contract["status"] == "FILLED"
    assert contract["received_tons"] == 200
    assert contract["hedged_applied_tons"] == 100
    assert contract["average_received_cost_cents_per_ton"] == 18_950
    assert contract["total_cost_cents"] == 3_790_000

    # Consume 60 corn + 40 soy; pools drop to 140 and 60.
    validate_success(
        api.create_feed_batch(
            complex_["id"],
            create_feed_batch_payload(
                program="CONVENTIONAL", corn_tons=60, soybean_tons=40
            ),
            make_complex_manager_headers(complex_["id"]),
        ),
        201,
    )
    complex_after = validate_success(api.get_complex(complex_["id"], ADMIN))
    assert complex_after["corn_inventory_tons"] == 140
    assert complex_after["soy_inventory_tons"] == 60


def test_feed_fifo_hedge_consumed_by_earliest_receipts(api):
    """The 100 hedged tons price the FIRST receipt; the running average after
    120 tons is 18250.

    PRD §3.8: "Costing honors the hedge first: the hedged share of the
    receipt — the smaller of `tons` and the not-yet-applied hedge balance —
    prices at `hedge_futures_cents_per_ton` plus `basis_cents_per_ton`, and
    the remainder prices at the receipt's spot plus basis; the hedge applies
    to the earliest receipts first. The receipt's cost accumulates into
    `total_cost_cents`, `hedged_applied_tons` and `received_tons` advance,
    and `average_received_cost_cents_per_ton` becomes `total_cost_cents`
    divided by `received_tons` rounded half up to a whole cent (it stays null
    until the first receipt)."

    Design: Corner/calculations/feed_fifo_hedge_consumed_by_earliest_receipts
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill West", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    contract = create_feed_contract(
        complex_["id"], commodity="CORN", total_tons=200,
        basis_cents_per_ton=2_000, spot_reference_cents_per_ton=17_000,
        delivery_start="2026-09-01T00:00:00Z",
        delivery_end="2026-10-01T00:00:00Z",
    )
    hedge_feed_contract(contract["id"], 100, 16_000)
    set_clock("2026-09-02T00:00:00Z")
    receive_feed(contract["id"], 120, 17_500)

    rows, meta = validate_paginated(
        api.list_feed_contracts(complex_["id"], PROCUREMENT,
                                params={"commodity": "CORN"})
    )
    assert meta["total_count"] == 1
    after = rows[0]
    # 100 hedged at 16000+2000 plus 20 at 17500+2000 = 2190000 / 120.
    assert after["average_received_cost_cents_per_ton"] == 18_250
    assert after["hedged_applied_tons"] == 100
    assert after["received_tons"] == 120
    assert after["status"] == "PARTIALLY_RECEIVED"


def test_feed_contract_partial_receipts_then_filled(api):
    """OPEN -> PARTIALLY_RECEIVED -> FILLED across 40 then 60 tons.

    PRD §3.8: "Status tracks fill: a partial receipt moves `OPEN` to
    `PARTIALLY_RECEIVED`, a single full receipt moves `OPEN` straight to
    `FILLED`, further partials keep `PARTIALLY_RECEIVED`, and the receipt
    that exactly completes the balance lands `FILLED`."
    PRD §3.8: "The matching complex pool — commodity crossed with the organic
    flag — gains the tons".

    Design: Corner/state_machines/feed_contract_partial_receipts_then_filled
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill West", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    contract = create_feed_contract(complex_["id"], total_tons=100)

    first = receive_feed(contract["id"], 40, 17_500)
    assert first["status"] == "PARTIALLY_RECEIVED"
    assert first["received_tons"] == 40

    second = receive_feed(contract["id"], 60, 17_500)
    assert second["status"] == "FILLED"
    assert second["received_tons"] == 100
    # All receipts at 17500 + 2000 basis.
    assert second["average_received_cost_cents_per_ton"] == 19_500

    complex_after = validate_success(
        api.get_complex(complex_["id"], ADMIN)
    )
    assert complex_after["corn_inventory_tons"] == 100


def test_receive_outside_delivery_window_rejected(api):
    """The delivery window is half-open: before delivery_start and at exactly
    delivery_end are both rejected.

    PRD §3.8: "Receipts arrive inside the delivery window (outside it is
    `ERR_OUTSIDE_DELIVERY_WINDOW`)" and the window runs "from
    `delivery_start` (inclusive) to `delivery_end` (exclusive)".

    Design: Corner/validations/receive_outside_delivery_window_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill West", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    contract = create_feed_contract(
        complex_["id"], total_tons=100,
        delivery_start="2026-09-10T00:00:00Z",
        delivery_end="2026-09-20T00:00:00Z",
    )

    validate_error(
        api.receive_feed_contract(
            contract["id"], {"tons": 10, "spot_cents_per_ton": 17_500},
            PROCUREMENT,
        ),
        ERR.ERR_OUTSIDE_DELIVERY_WINDOW,
    )

    set_clock("2026-09-20T00:00:00Z")  # exactly delivery_end: excluded
    validate_error(
        api.receive_feed_contract(
            contract["id"], {"tons": 10, "spot_cents_per_ton": 17_500},
            PROCUREMENT,
        ),
        ERR.ERR_OUTSIDE_DELIVERY_WINDOW,
    )

    rows, _ = validate_paginated(
        api.list_feed_contracts(complex_["id"], PROCUREMENT)
    )
    assert rows[0]["received_tons"] == 0
    assert rows[0]["status"] == "OPEN"


def test_receive_and_hedge_bounds_enforced(api):
    """hedged_tons beyond total_tons, receipt tons beyond the remaining
    balance, and hedging after the first receipt are all rejected.

    PRD §3.8: "While a contract is `OPEN` — hedging later is
    `ERR_INVALID_STATE` — the buyer may lock a single hedge: `hedged_tons` up
    to `total_tons` (more is `ERR_HEDGE_EXCEEDS_CONTRACT`)".
    PRD §3.8: "Receipts arrive inside the delivery window ... with a `tons`
    quantity of at least one and no more than the remaining undelivered
    balance (more is `ERR_RECEIVE_EXCEEDS_CONTRACT`)".

    Design: Corner/validations/receive_and_hedge_bounds_enforced
    """
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill West", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    contract = create_feed_contract(complex_["id"], total_tons=100)

    validate_error(
        api.hedge_feed_contract(
            contract["id"],
            {"hedged_tons": 150, "hedge_futures_cents_per_ton": 16_000},
            PROCUREMENT,
        ),
        ERR.ERR_HEDGE_EXCEEDS_CONTRACT,
    )
    validate_error(
        api.receive_feed_contract(
            contract["id"], {"tons": 101, "spot_cents_per_ton": 17_500},
            PROCUREMENT,
        ),
        ERR.ERR_RECEIVE_EXCEEDS_CONTRACT,
    )

    partial = receive_feed(contract["id"], 10, 17_500)
    assert partial["status"] == "PARTIALLY_RECEIVED"

    # Hedging is legal only while OPEN.
    validate_error(
        api.hedge_feed_contract(
            contract["id"],
            {"hedged_tons": 50, "hedge_futures_cents_per_ton": 16_000},
            PROCUREMENT,
        ),
        ERR.ERR_INVALID_STATE,
    )


def _setup_mill_central(api):
    """Mill Central (100 tons/day) with the overlapping C1/C2 contracts."""
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill Central", mill_receiving_tons_per_day=100
    )
    c1 = create_feed_contract(
        complex_["id"], commodity="CORN", total_tons=350,
        basis_cents_per_ton=2_000, spot_reference_cents_per_ton=17_000,
        delivery_start="2026-09-01T00:00:00Z",
        delivery_end="2026-09-08T00:00:00Z",
    )
    c2 = create_feed_contract(
        complex_["id"], commodity="SOYBEAN_MEAL", total_tons=280,
        basis_cents_per_ton=3_000, spot_reference_cents_per_ton=34_000,
        delivery_start="2026-09-04T00:00:00Z",
        delivery_end="2026-09-11T00:00:00Z",
    )
    return complex_, c1, c2


def test_mill_receiving_accepts_overlapping_windows_within_capacity(api):
    """Overlapping delivery windows are allowed while the aggregate daily
    load stays within the mill's receiving capacity.

    PRD §3.8: "Each contract is treated as spreading evenly across its window
    — its daily receiving load is its `total_tons` divided by the window's
    length in days, rounded up — and on every calendar day of a new
    contract's window, the sum of daily loads over all of the complex's
    contracts in `OPEN` or `PARTIALLY_RECEIVED` covering that day, including
    the new contract itself, must stay within the complex's
    `mill_receiving_tons_per_day`. Exceeding it on any single day is
    `ERR_MILL_RECEIVING_CAPACITY_EXCEEDED`; overlapping windows that fit are
    fine."

    Design: Difficulty/resource_temporal_overlap/mill_receiving_aggregate_daily_capacity
    """
    complex_, c1, c2 = _setup_mill_central(api)
    # C1: ceil(350/7) = 50/day; C2: ceil(280/7) = 40/day; overlap peak 90.
    assert c1["status"] == "OPEN" and c2["status"] == "OPEN"
    rows, meta = validate_paginated(
        api.list_feed_contracts(complex_["id"], PROCUREMENT)
    )
    assert meta["total_count"] == 2


def test_mill_receiving_rejects_the_contract_that_exceeds_capacity(api):
    """The third contract's window pushes the peak day to 50+40+30 = 120 >
    100 tons/day and is rejected.

    PRD §3.8: "Exceeding it on any single day is
    `ERR_MILL_RECEIVING_CAPACITY_EXCEEDED`; overlapping windows that fit are
    fine."

    Design: Difficulty/resource_temporal_overlap/mill_receiving_aggregate_daily_capacity
    """
    complex_, _, _ = _setup_mill_central(api)

    response = api.create_feed_contract(
        {
            "complex_id": complex_["id"],
            "commodity": "CORN",
            "total_tons": 210,
            "basis_cents_per_ton": 2_100,
            "spot_reference_cents_per_ton": 17_100,
            "delivery_start": "2026-09-05T00:00:00Z",
            "delivery_end": "2026-09-12T00:00:00Z",
        },
        PROCUREMENT,
    )
    validate_error(response, ERR.ERR_MILL_RECEIVING_CAPACITY_EXCEEDED)
    rows, meta = validate_paginated(
        api.list_feed_contracts(complex_["id"], PROCUREMENT)
    )
    assert meta["total_count"] == 2


def _setup_complex_with_nonorganic_corn(api, tons=100):
    set_clock("2026-09-01T00:00:00Z")
    complex_ = create_complex(
        name="Mill West", region_code="WEST", mill_receiving_tons_per_day=1000
    )
    contract = create_feed_contract(complex_["id"], total_tons=tons)
    receive_feed(contract["id"], tons, 17_500)
    return complex_


def test_organic_batch_cannot_draw_nonorganic_pool(api):
    """An ORGANIC batch with a full non-organic pool but empty organic pool
    is an organic-integrity failure, reported before generic sufficiency.

    PRD §3.8: "Pool discipline is strict: an `ORGANIC` batch consumes only
    the organic pools, and an organic shortfall is
    `ERR_ORGANIC_INPUTS_REQUIRED` even when the non-organic pool is full —
    this organic-integrity check is evaluated before the generic inventory
    check".

    Design: Corner/validations/organic_batch_cannot_draw_nonorganic_pool
    """
    complex_ = _setup_complex_with_nonorganic_corn(api)

    response = api.create_feed_batch(
        complex_["id"],
        {"program": "ORGANIC", "corn_tons": 10, "soybean_tons": 0},
        make_complex_manager_headers(complex_["id"]),
    )
    error = validate_error(response, ERR.ERR_ORGANIC_INPUTS_REQUIRED)
    assert error["error_id"] != ERR.ERR_INSUFFICIENT_FEED_INVENTORY.value
    complex_after = validate_success(api.get_complex(complex_["id"], ADMIN))
    assert complex_after["corn_inventory_tons"] == 100


def test_batch_beyond_pool_returns_insufficient_feed_inventory(api):
    """A CONVENTIONAL batch demanding more than the non-organic pool holds is
    rejected and decrements nothing.

    PRD §3.8: "a `CONVENTIONAL` or `CAGE_FREE` batch drawing on the
    non-organic pools reports a shortfall as `ERR_INSUFFICIENT_FEED_INVENTORY`".

    Design: Corner/validations/batch_beyond_pool_returns_insufficient_feed_inventory
    """
    complex_ = _setup_complex_with_nonorganic_corn(api)

    response = api.create_feed_batch(
        complex_["id"],
        {"program": "CONVENTIONAL", "corn_tons": 150, "soybean_tons": 0},
        make_complex_manager_headers(complex_["id"]),
    )
    validate_error(response, ERR.ERR_INSUFFICIENT_FEED_INVENTORY)
    complex_after = validate_success(api.get_complex(complex_["id"], ADMIN))
    assert complex_after["corn_inventory_tons"] == 100
    rows, meta = validate_paginated(
        api.list_feed_batches(
            complex_["id"], make_complex_manager_headers(complex_["id"])
        )
    )
    assert rows == [] and meta["total_count"] == 0

