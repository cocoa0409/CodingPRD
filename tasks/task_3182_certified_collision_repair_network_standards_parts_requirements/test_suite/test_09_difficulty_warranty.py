"""Difficulty tests (queue A): warranty reserve accrual pinned evaluation
order and the compensating zero-drift invariant."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_certified_shop, create_technician, order_in_qc, order_completed,
    order_warranty_active, record_step, sm,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]


def _adas_order_with_two_reworks(api, shop, tech, vin):
    """ADAS order driven ESTIMATE -> ... -> QC with rework_count == 2, then
    completed via the CALIBRATION path (POST_SCAN then ADAS calibration step
    after it)."""
    order = order_in_qc(shop["id"], tech["id"], vin=vin, estimate_total_cents=200000,
                        vehicle_model_year=2020)
    oid = order["id"]
    get_success_data(api.fail_qc(oid, sm(shop["id"])))
    get_success_data(api.submit_qc(oid, sm(shop["id"])))
    get_success_data(api.fail_qc(oid, sm(shop["id"])))
    get_success_data(api.submit_qc(oid, sm(shop["id"])))
    record_step(oid, "POST_SCAN", tech["id"], "2026-09-03T06:00:00Z", "PASS", shop["id"],
                scan_report_uri="s3://scans/post1.json")
    record_step(oid, "ADAS_CALIBRATION_STATIC", tech["id"], "2026-09-03T07:00:00Z", "PASS", shop["id"])
    # First pass-qc: QC -> CALIBRATION; second: CALIBRATION -> COMPLETE.
    get_success_data(api.pass_qc(oid, sm(shop["id"])))
    get_success_data(api.pass_qc(oid, sm(shop["id"])))
    return get_success_data(api.get_repair_order(oid, sm(shop["id"])))


def test_warranty_accrual_pinned_evaluation_order(api):
    """PRD §3.7: "The accrual is computed from the transitioning order alone,
    in a pinned evaluation order. First, a marginal tiered rate is applied to
    the order's estimate_total_cents: 3.0% on the first 100,000 cents, 2.0% on
    the portion above 100,000 up to and including 500,000 cents, and 1.0% on
    the portion above 500,000 cents ... Second, the tiered amount is
    multiplied by 1.5 when the order is ADAS-equipped, or by 1.0 otherwise.
    Third, the result is rounded half-up to whole cents. Fourth and last, a
    flat penalty of 500 cents per rework loop (rework_count) is added.
    Rounding before adding the penalty is mandatory — evaluating in any other
    order produces different cents." and "Twenty-four hours after
    completed_at, if no warranty claim has been filed against the order, the
    clock sweep moves the order COMPLETE → WARRANTY_ACTIVE, and at that moment
    the shop's warranty_reserve_cents is increased by the order's reserve
    accrual."

    Design: Difficulty/combinatorial_formula/warranty_accrual_pinned_evaluation_order
    """
    shop, _cycle = create_certified_shop(
        legal_name="Accrual Collision", state_code="TX", zip_code="75001",
        latitude=32.77, longitude=-96.79)
    tech = create_technician(shop["id"], full_name="Sam Fix")
    get_success_data(api.set_clock("2026-09-03T00:00:00Z", ADMIN))
    order = _adas_order_with_two_reworks(api, shop, tech, "2HGFC2F59LH500003")
    assert order["rework_count"] == 2

    get_success_data(api.set_clock("2026-09-04T08:00:00Z", ADMIN))
    order_now = validate_success(api.get_repair_order(order["id"], ADMIN))
    assert order_now["status"] == "WARRANTY_ACTIVE"
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    # tiered base: 100000*0.03 + 100000*0.02 = 5000; x1.5 = 7500 (rounded);
    # + 2*500 rework penalty = 8500
    assert shop_now["warranty_reserve_cents"] == 8500


def test_warranty_accrual_tiers_marginal(api):
    """PRD §3.7: "3.0% on the first 100,000 cents, 2.0% on the portion above
    100,000 up to and including 500,000 cents, and 1.0% on the portion above
    500,000 cents — each tier's rate applies only to the base falling within
    that tier's band."

    Design: Difficulty/combinatorial_formula/warranty_accrual_pinned_evaluation_order
    """
    shop, _cycle = create_certified_shop(
        TEST_USERS["auditor2_headers"],
        legal_name="Tier Collision", state_code="TX", zip_code="75002",
        latitude=32.77, longitude=-96.79)
    tech = create_technician(shop["id"], full_name="Tier Base")
    # Non-ADAS (2015), estimate 600000, no reworks:
    # 100000*3% + 400000*2% + 100000*1% = 3000+8000+1000 = 12000
    order = order_warranty_active(
        shop["id"], tech["id"], vin="1HGCV1F34LA000040", estimate_total_cents=600000,
        advance_to="2026-09-02T06:00:00Z")
    assert order["status"] == "WARRANTY_ACTIVE"
    shop_now = validate_success(api.get_shop(shop["id"], ADMIN))
    assert shop_now["warranty_reserve_cents"] == 12000


def test_warranty_reserve_roundtrip_zero_drift(api):
    """PRD §3.7: "when the sweep finds the logical clock past the end of the
    warranty window with no claim of the order in FILED, UNDER_REVIEW, or
    ESCALATED, the order moves WARRANTY_ACTIVE → CLOSED and the unreleased
    remainder of its accrual is subtracted back out of the shop's reserve —
    the compensating release that makes a claim-free repair net-zero on the
    ledger."

    Design: Difficulty/compensating_invariant/warranty_reserve_roundtrip_zero_drift
    """
    shop, _cycle = create_certified_shop(
        legal_name="Reserve Body", state_code="NM", zip_code="87101",
        latitude=35.08, longitude=-106.65)
    tech = create_technician(shop["id"], full_name="Re Serve")
    # Non-ADAS 2015, estimate 200000, no reworks -> accrual 5000.
    order = order_completed(shop["id"], tech["id"], vin="1HGCV1F34LA000012",
                            estimate_total_cents=200000)
    get_success_data(api.set_clock("2026-09-02T06:00:00Z", ADMIN))
    mid = validate_success(api.get_shop(shop["id"], ADMIN))
    order_mid = validate_success(api.get_repair_order(order["id"], ADMIN))
    assert order_mid["status"] == "WARRANTY_ACTIVE"
    assert mid["warranty_reserve_cents"] == 5000

    get_success_data(api.set_clock("2027-09-02T06:00:00Z", ADMIN))
    order_now = validate_success(api.get_repair_order(order["id"], ADMIN))
    assert order_now["status"] == "CLOSED"
    final = validate_success(api.get_shop(shop["id"], ADMIN))
    assert final["warranty_reserve_cents"] == 0


def test_warranty_reserve_two_orders_accumulate_then_release(api):
    """PRD §2.11: "Accrual is added when a repair order enters its
    warranty-active period ... and the unreleased remainder for an order is
    subtracted back out when the order closes — a compensating invariant
    meaning a repair with no accepted claims nets zero drift on the reserve."

    Design: Difficulty/compensating_invariant/warranty_reserve_roundtrip_zero_drift
    """
    shop, _cycle = create_certified_shop(
        TEST_USERS["auditor2_headers"],
        legal_name="Reserve Body 2", state_code="NM", zip_code="87102",
        latitude=35.08, longitude=-106.65)
    tech = create_technician(shop["id"], full_name="Two Orders")
    o1 = order_completed(shop["id"], tech["id"], vin="1HGCV1F34LA000041",
                         estimate_total_cents=100000)
    o2 = order_completed(shop["id"], tech["id"], vin="1HGCV1F34LA000042",
                         estimate_total_cents=100000)
    get_success_data(api.set_clock("2026-09-02T06:00:00Z", ADMIN))
    mid = validate_success(api.get_shop(shop["id"], ADMIN))
    # 100000 * 3% = 3000 per order
    assert mid["warranty_reserve_cents"] == 6000
    get_success_data(api.set_clock("2027-09-02T06:00:00Z", ADMIN))
    final = validate_success(api.get_shop(shop["id"], ADMIN))
    assert final["warranty_reserve_cents"] == 0
    for o in (o1, o2):
        assert validate_success(api.get_repair_order(o["id"], ADMIN))["status"] == "CLOSED"
