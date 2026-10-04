"""Procurement contract price shape, close settlement variants, fill boundary,
terminal lockdown (PRD §3.2, §3.3)."""
from test_helpers import (
    api_client, ApiErrorId, TEST_USERS, validate_success, validate_error,
    validate_paginated, set_clock, make_mill, make_contract, make_lot,
    publish_index, get_contract,
)

PM = TEST_USERS["plant_manager_headers"]
PO = TEST_USERS["procurement_officer_headers"]


def test_contract_create_indexed_with_price_returns_contract_price_forbidden():
    """PRD §3.2: "a `FIXED` contract must carry a non-negative `contract_price_cents`
    and an `INDEXED` contract must not carry one — sending `contract_price_cents` on an
    indexed contract, or omitting it on a fixed one, is rejected with
    `ERR_CONTRACT_PRICE_FORBIDDEN` (HTTP 422)."

    Design: Corner/entities/procurement_contract_create_indexed_with_price_returns_contract_price_forbidden
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    resp = api_client.create_contract(
        mill["id"],
        {"supplier_name": "Confused Terms Inc", "grade_category": "HMS",
         "contract_type": "INDEXED", "contract_price_cents": 37000, "committed_tons": 50},
        PO,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRACT_PRICE_FORBIDDEN, 422)
    _rows, meta = validate_paginated(api_client.list_contracts(mill["id"], PO))
    assert meta["total_count"] == 0


def test_settlement_indexed_fifo_consumes_lots_oldest_first():
    """PRD §3.3: "The indexed variant is a chronological FIFO over the contract's lots
    (those in `RECEIVED`, `PARTIALLY_CONSUMED`, or `CONSUMED`): lots are sorted by
    `received_on` ascending, ties broken by the lot's `created_at` ascending, never by
    id. Walking that order, the rule takes from each lot the smaller of its `dry_tons`
    and the remaining settlement tonnage, prices that take at the `PUBLISHED` surcharge
    index for the mill, the contract's grade category, and the lot's receipt month (the
    first seven characters of `received_on`), rounds each lot's contribution half-up to
    whole cents, adds it to the running amount, and stops when the remaining tonnage
    reaches zero."
    PRD §3.3: "On close, `settlement_tons` becomes the smaller of `received_tons` and
    `committed_tons`"

    Design: Difficulty/dual_variant_calc/settlement_amount_indexed_fifo_vs_flat
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-08",
                  price_per_ton_cents=39000)
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=41000)
    resp = api_client.create_contract(
        mill["id"],
        {"supplier_name": "River Metals Recycling", "grade_category": "SHREDDED",
         "contract_type": "INDEXED", "committed_tons": 100},
        PO,
    )
    contract = validate_success(resp, 201)
    make_lot(mill["id"], contract["id"], received_on="2026-08-05", tons_received=30,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)
    make_lot(mill["id"], contract["id"], received_on="2026-08-20", tons_received=40,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)
    make_lot(mill["id"], contract["id"], received_on="2026-09-02", tons_received=20,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)

    closed = validate_success(api_client.close_contract(mill["id"], contract["id"], PO), 200)
    assert closed["status"] == "CLOSED"
    assert closed["settlement_tons"] == 90
    # 30*39000 + 40*39000 + 20*41000 (per-lot rounding is exact here)
    assert closed["settlement_amount_cents"] == 3_550_000
    # The FIXED flat variant at the cheapest month would be 90*39000 = 3,510,000.
    assert closed["settlement_amount_cents"] != 90 * 39000
    assert closed["version"] == 2


def test_settlement_fixed_flat_ignores_receipt_month_indices():
    """PRD §3.3: "The fixed variant is forward-looking and flat: the amount is
    `contract_price_cents` multiplied by `settlement_tons`, rounded half-up to whole
    cents — the contract price applies to every settled ton regardless of receipt
    month."

    Design: Difficulty/dual_variant_calc/settlement_amount_indexed_fifo_vs_flat
    """
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-08",
                  price_per_ton_cents=39000)
    publish_index(mill["id"], grade_category="SHREDDED", effective_month="2026-09",
                  price_per_ton_cents=41000)
    contract = make_contract(mill["id"], supplier_name="River Metals Recycling",
                             grade_category="SHREDDED", contract_type="FIXED",
                             contract_price_cents=39000, committed_tons=50)
    make_lot(mill["id"], contract["id"], received_on="2026-08-05", tons_received=30,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)
    make_lot(mill["id"], contract["id"], received_on="2026-09-02", tons_received=20,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)

    closed = validate_success(api_client.close_contract(mill["id"], contract["id"], PO), 200)
    assert closed["status"] == "CLOSED"
    assert closed["settlement_tons"] == 50
    # FIXED flat: 39000 * 50 — receipt-month indices play no part.
    assert closed["settlement_amount_cents"] == 1_950_000


def _setup_fill_boundary_contracts():
    """Two FIXED contracts committed 100t each: one with an 80t lot, one with 79t."""
    set_clock("2026-09-10T00:00:00Z")
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    c80 = make_contract(mill["id"], supplier_name="Exact Fill Recycling",
                        contract_price_cents=39000, committed_tons=100)
    make_lot(mill["id"], c80["id"], received_on="2026-09-03", tons_received=80,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)
    c79 = make_contract(mill["id"], supplier_name="Short Fill Recycling",
                        contract_price_cents=39000, committed_tons=100)
    make_lot(mill["id"], c79["id"], received_on="2026-09-03", tons_received=79,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)
    return mill, c80, c79


def test_contract_close_at_exactly_eighty_percent_fill_succeeds():
    """PRD §3.3: "Closing requires the contract still `OPEN` — otherwise
    `ERR_INVALID_STATE` — and requires `received_tons` to be at least 80 percent of
    `committed_tons`; a shortfall is rejected with `ERR_UNDER_DELIVERED` (HTTP 422).
    On close, `settlement_tons` becomes the smaller of `received_tons` and
    `committed_tons`"

    Design: Difficulty/boundary_precision_check/contract_underdelivered_fill_boundary
    """
    mill, c80, _c79 = _setup_fill_boundary_contracts()
    closed = validate_success(api_client.close_contract(mill["id"], c80["id"], PO), 200)
    assert closed["status"] == "CLOSED"
    assert closed["settlement_tons"] == 80
    assert closed["settlement_amount_cents"] == 3_120_000  # 80 * 39000


def test_contract_close_below_eighty_percent_fill_rejected():
    """PRD §3.3: "Closing requires the contract still `OPEN` — otherwise
    `ERR_INVALID_STATE` — and requires `received_tons` to be at least 80 percent of
    `committed_tons`; a shortfall is rejected with `ERR_UNDER_DELIVERED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/contract_underdelivered_fill_boundary
    """
    mill, _c80, c79 = _setup_fill_boundary_contracts()
    rejected = api_client.close_contract(mill["id"], c79["id"], PO)
    validate_error(rejected, ApiErrorId.ERR_UNDER_DELIVERED, 422)
    assert get_contract(mill["id"], c79["id"])["status"] == "OPEN"


def test_contract_terminal_close_lockdown():
    """PRD §3.3: "Closing requires the contract still `OPEN` — otherwise
    `ERR_INVALID_STATE` — and requires `received_tons` to be at least 80 percent of
    `committed_tons`"
    PRD §3.3: "the contract's status moves to `CLOSED` (terminal)"

    Design: Corner/state_machines/contract_terminal_close_lockdown
    """
    mill = make_mill(name="Gallatin Energy Mill", division="ENERGY")
    contract = make_contract(mill["id"], supplier_name="River Metals Recycling",
                             contract_price_cents=39000, committed_tons=10)
    make_lot(mill["id"], contract["id"], received_on="2026-09-03", tons_received=10,
             moisture_pct=0.0, cu_pct=0.001, mn_pct=0.004)
    closed = validate_success(api_client.close_contract(mill["id"], contract["id"], PO), 200)
    assert closed["settlement_amount_cents"] == 390_000  # 10 * 39000

    resp = api_client.close_contract(mill["id"], contract["id"], PO)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = get_contract(mill["id"], contract["id"])
    assert after["status"] == "CLOSED"
    assert after["settlement_amount_cents"] == 390_000
