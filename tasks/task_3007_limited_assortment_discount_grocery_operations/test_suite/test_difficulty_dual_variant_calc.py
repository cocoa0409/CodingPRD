"""Dual-variant calculations: the register-shift scan rate and the refund rule.

Two calculations each declare two variants that diverge on identical inputs:
the provisional scan rate ignores voids while the final deducts them, and the
guarantee refund pays exactly double the standard refund.
"""

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import CUSTOMER_SERVICE_HEADERS, fixtures
from test_helpers.factories import claim_payload, scan_payload
from test_helpers.test_users import make_store_manager_headers


def _open_shift_at(api, opened_at="2026-09-01T08:00:00Z"):
    world = fixtures.store_with_cashier(api)
    shift = fixtures.open_shift(api, world["store"], world["cashier"], opened_at=opened_at)
    world["shift"] = shift
    return world


def test_scan_rate_provisional_ignores_voids_final_deducts(api):
    """Provisional 1000.0 with voids ignored vs final 960.0 with the void penalty.

    PRD §3.7: "Each batch increments `items_scanned` and `voids` accordingly and recomputes the provisional rate: `items_scanned` multiplied by 3600 and divided by the number of seconds elapsed since `started_at` (with a denominator of at least 1 second), rounded half-up to 2 decimal places."
    PRD §3.7: "Closing a shift — a `StoreManager` action restricted to the manager's own store — moves it `OPEN → CLOSED`, stamps `closed_at` from the logical clock, and computes the final variant exactly once: the count of scanned items minus 2 per void, multiplied by 3600 and divided by the shift's full duration in seconds (again with a denominator of at least 1), rounded half-up to 2 decimal places, stored as `final_scan_rate`."

    Design: Difficulty/dual_variant_calc/scan_rate_provisional_vs_final_diverge
    """
    world = _open_shift_at(api)
    store, cashier, shift = world["store"], world["cashier"], world["shift"]

    fixtures.set_clock(api, "2026-09-01T08:30:00Z")
    scanned = validate_success(
        api.scan_shift(shift["id"], scan_payload(items_count=500, voids_count=10), world["cashier_headers"])
    )
    assert scanned["provisional_scan_rate"] == 1000.0, (
        f"provisional rate must be 500*3600/1800 = 1000.0, got {scanned['provisional_scan_rate']}"
    )

    closed = validate_success(api.close_shift(shift["id"], make_store_manager_headers(store["id"])))
    assert closed["final_scan_rate"] == 960.0, (
        f"final rate must be (500-2*10)*3600/1800 = 960.0, got {closed['final_scan_rate']}"
    )
    assert closed["compliance"] == "BELOW_STANDARD", (
        f"960.0 < 1000 must be BELOW_STANDARD, got {closed['compliance']}"
    )
    assert closed["provisional_scan_rate"] != closed["final_scan_rate"]


def test_scan_rate_provisional_matches_final_when_no_voids_and_same_duration(api):
    """With zero voids and a frozen duration, provisional and final agree.

    PRD §3.7: "The provisional variant ignores voids and diverges from the final figure whenever voids exist or the shift keeps running; it is a live dashboard number, not the standard of record."

    Design: Difficulty/dual_variant_calc/scan_rate_provisional_vs_final_diverge
    """
    world = _open_shift_at(api)
    store, shift = world["store"], world["shift"]

    fixtures.set_clock(api, "2026-09-01T08:30:00Z")
    scanned = validate_success(
        api.scan_shift(shift["id"], scan_payload(items_count=500), world["cashier_headers"])
    )
    assert scanned["provisional_scan_rate"] == 1000.0

    closed = validate_success(api.close_shift(shift["id"], make_store_manager_headers(store["id"])))
    assert closed["final_scan_rate"] == 1000.0, (
        f"no voids: final must equal provisional at 1000.0, got {closed['final_scan_rate']}"
    )
    assert closed["compliance"] == "COMPLIANT"


def _approve_refund(api, store_id: str, product_id: str, reason: str) -> int:
    claim = fixtures.claim_under_review(
        api, product_id, store_id, quantity=3, unit_price_cents=349, reason=reason
    )
    approved = validate_success(api.approve_claim(claim["id"], CUSTOMER_SERVICE_HEADERS))
    return approved["refund_amount_cents"]


def test_double_refund_guarantee_pays_exactly_twice_standard(api):
    """Identical inputs: DAMAGED refunds 1047, QUALITY_DEFECT refunds 2094.

    PRD §3.9: "Approval moves it `UNDER_REVIEW → APPROVED` and prices the refund: for a `QUALITY_DEFECT` claim the `refund_amount_cents` is the `unit_price_cents` multiplied by the `quantity` and doubled, rounded half-up to whole cents; for `DAMAGED` or `OTHER` the same inputs are refunded at face value, identically rounded. Identical inputs under the guarantee reason therefore yield exactly double the standard refund."

    Design: Difficulty/dual_variant_calc/double_refund_standard_vs_guarantee_diverge
    """
    world = fixtures.claims_world(api)
    product_id, store_id = world["product"]["id"], world["store"]["id"]

    standard = _approve_refund(api, store_id, product_id, "DAMAGED")
    guarantee = _approve_refund(api, store_id, product_id, "QUALITY_DEFECT")

    assert standard == 1047, f"349*3*1.0 must be 1047, got {standard}"
    assert guarantee == 2094, f"349*3*2.0 must be 2094, got {guarantee}"
    assert guarantee == 2 * standard, "guarantee must be exactly double the standard refund"


def test_double_refund_other_reason_pays_face_value(api):
    """OTHER is a standard-variant reason: face value, not doubled.

    PRD §3.9: "Approval moves it `UNDER_REVIEW → APPROVED` and prices the refund: for a `QUALITY_DEFECT` claim the `refund_amount_cents` is the `unit_price_cents` multiplied by the `quantity` and doubled, rounded half-up to whole cents; for `DAMAGED` or `OTHER` the same inputs are refunded at face value, identically rounded."

    Design: Difficulty/dual_variant_calc/double_refund_standard_vs_guarantee_diverge
    """
    world = fixtures.claims_world(api)
    refund = _approve_refund(api, world["store"]["id"], world["product"]["id"], "OTHER")
    assert refund == 1047, f"OTHER refunds at face value: 349*3 = 1047, got {refund}"
