"""Difficulty tests (queue A): dual-variant calculations and combinatorial
referral ranking."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, get_success_data,
    create_shop, create_published_requirement, attest, open_cycle,
    certify_shop, certify_shop_with_auditor, create_technician, create_order,
    add_part, sm,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
AUD1 = TEST_USERS["auditor_headers"]
AUD2 = TEST_USERS["auditor2_headers"]
DEALER = TEST_USERS["dealer_headers"]


def _ratio_order(api):
    """Four part lines on one order: 2 OE-class (80000 cents total), 1
    aftermarket clip line (2000), 1 recycled (20000) -> by_count 0.5,
    by_cost 80000/102000 = 0.7843."""
    shop = create_shop(legal_name="Ratio Body Works", state_code="CA", zip_code="90001",
                       latitude=34.05, longitude=-118.24)
    # §3.5: creating a repair order requires CERTIFIED or PROBATION posture.
    certify_shop(shop["id"])
    tech = create_technician(shop["id"], full_name="Pat Panel")
    order = create_order(shop["id"], tech["id"], vin="1HGCV1F34LA000001",
                         estimate_total_cents=100000)
    add_part(order["id"], shop["id"], part_number="BMP-100", part_class="OE",
             unit_cost_cents=50000, quantity=1)
    add_part(order["id"], shop["id"], part_number="FND-200", part_class="OE_SURPLUS",
             unit_cost_cents=30000, quantity=1)
    add_part(order["id"], shop["id"], part_number="CLP-9", part_class="AFTERMARKET",
             unit_cost_cents=500, quantity=4,
             alternative_justification="consumer declined OE clips; consent ref C-11")
    add_part(order["id"], shop["id"], part_number="LMP-77", part_class="RECYCLED",
             unit_cost_cents=20000, quantity=1,
             alternative_justification="like-kind-quality lamp per insurer; consent ref C-12")
    return shop, order


def test_oe_parts_ratio_count_vs_cost_divergence(api):
    """PRD §3.6: "The by-count ratio, oe_parts_ratio_by_count, is the number
    of active OE-class lines divided by the number of all active lines — each
    line weighs equally, so a cheap aftermarket clip drags the ratio exactly
    as much as an expensive aftermarket bumper; this is the variant the
    audit's OE-usage expectation check reads. The by-cost ratio,
    oe_parts_ratio_by_cost, divides the sum of unit_cost_cents times quantity
    over OE-class active lines by the same sum over all active lines —
    cost-weighted, so expensive OE parts can mask many cheap non-OE lines,
    and identical input data yields different ratios under the two variants".
    PRD §3.6: "Both ratios are rounded to 4 decimal places round-half-up".

    Design: Difficulty/dual_variant_calc/oe_parts_ratio_count_vs_cost_divergence
    """
    shop, order = _ratio_order(api)
    fetched = validate_success(api.get_repair_order(order["id"], sm(shop["id"])))
    assert fetched["oe_parts_ratio_by_count"] == pytest.approx(0.5, abs=1e-9)
    assert fetched["oe_parts_ratio_by_cost"] == pytest.approx(0.7843, abs=1e-9)
    assert fetched["oe_parts_ratio_by_count"] != fetched["oe_parts_ratio_by_cost"]


def test_oe_parts_ratio_recomputed_on_mutation(api):
    """PRD §3.6: "Two OE-usage ratios are recomputed on every line create and
    every removal, over the order's ACTIVE lines only, with OE and OE_SURPLUS
    counting as original equipment."

    Design: Difficulty/dual_variant_calc/oe_parts_ratio_count_vs_cost_divergence
    """
    shop, order = _ratio_order(api)
    lines, _ = validate_paginated(api.list_part_lines(order["id"], sm(shop["id"])))
    recycled = [l for l in lines if l["part_class"] == "RECYCLED"][0]
    validate_success(api.delete_part_line(order["id"], recycled["id"], sm(shop["id"])))
    fetched = validate_success(api.get_repair_order(order["id"], sm(shop["id"])))
    # 2 of 3 active lines are OE-class; cost 80000 / 82000 = 0.9756
    assert fetched["oe_parts_ratio_by_count"] == pytest.approx(2 / 3, abs=1e-4)
    assert fetched["oe_parts_ratio_by_cost"] == pytest.approx(0.9756, abs=1e-4)


def test_compliance_score_live_vs_audit_snapshot_divergence(api):
    """PRD §2.7: "The same formula, evaluated exactly once at cycle close and
    never recomputed afterwards, is frozen onto the cycle as
    audit_snapshot_score. The two variants deliberately diverge after any
    post-close mutation: the snapshot is the historical record of what the
    auditor saw, while the live score tracks the shop's present posture."
    PRD §3.2: "A category with zero published effective rows scores 100.0;
    otherwise the category score is 100.0 times the satisfied count divided
    by the total count."

    Design: Difficulty/dual_variant_calc/compliance_score_live_vs_audit_snapshot_divergence
    """
    shop = create_shop(legal_name="Snapshot Collision", state_code="OH", zip_code="43215",
                       latitude=39.96, longitude=-82.99)
    req = create_published_requirement(
        requirement_code="EQ-SNAP-01", category="EQUIPMENT",
        description="Snap gauge set", severity_if_failed="MINOR",
        effective_from="2026-09-01T00:00:00Z")
    # A second attested EQUIPMENT row keeps the category denominator at 2
    # after the revision below, so the live score falls to
    # 30*(1/2) + 30 + 15 + 25 = 85.0 per §3.2 while the snapshot stays 100.0.
    req2 = create_published_requirement(
        requirement_code="EQ-SNAP-01B", category="EQUIPMENT",
        description="Torque wrench", severity_if_failed="MINOR",
        effective_from="2026-09-01T00:00:00Z")
    attest(shop["id"], req["id"])
    attest(shop["id"], req2["id"])
    cycle = certify_shop(shop["id"], scheduled_start="2026-09-02T09:00:00Z",
                         scheduled_end="2026-09-02T17:00:00Z",
                         begin_at="2026-09-02T10:00:00Z")
    get_success_data(api.publish_revision(
        req["id"],
        {"description": "Snap gauge set v2", "severity_if_failed": "MINOR",
         "effective_from": "2026-09-02T10:00:00Z"},
        ADMIN))

    cycle_now = validate_success(api.get_cycle(cycle["id"], AUD1))
    assert cycle_now["audit_snapshot_score"] == pytest.approx(100.0, abs=1e-9)
    shop_now = validate_success(api.get_shop(shop["id"], AUD1))
    assert shop_now["live_compliance_score"] == pytest.approx(85.0, abs=1e-9)
    assert cycle_now["audit_snapshot_score"] != shop_now["live_compliance_score"]


def test_compliance_score_snapshot_stable_under_further_mutation(api):
    """PRD §2.7: "evaluated exactly once at cycle close and never recomputed
    afterwards, is frozen onto the cycle as audit_snapshot_score."

    Design: Difficulty/dual_variant_calc/compliance_score_live_vs_audit_snapshot_divergence
    """
    shop = create_shop(legal_name="Snapshot Collision 2", state_code="OH", zip_code="43216",
                       latitude=39.96, longitude=-82.99)
    req = create_published_requirement(
        requirement_code="EQ-SNAP-02", category="EQUIPMENT",
        description="Snap gauge set", severity_if_failed="MINOR",
        effective_from="2026-09-01T00:00:00Z")
    attest(shop["id"], req["id"])
    cycle = certify_shop(shop["id"], scheduled_start="2026-09-02T09:00:00Z",
                         scheduled_end="2026-09-02T17:00:00Z",
                         begin_at="2026-09-02T10:00:00Z")
    # Retire the only requirement: the pinned attestation lapses, and with no
    # PUBLISHED effective rows left the EQUIPMENT category returns to the
    # vacuous 100.0 per §3.2 — the live score recovers while the snapshot
    # frozen at close is never recomputed.
    get_success_data(api.retire_requirement(req["id"], ADMIN))
    first = validate_success(api.get_cycle(cycle["id"], AUD1))
    shop_now = validate_success(api.get_shop(shop["id"], AUD1))
    assert shop_now["live_compliance_score"] == pytest.approx(100.0, abs=1e-9)
    second = validate_success(api.get_cycle(cycle["id"], AUD1))
    assert first["audit_snapshot_score"] == second["audit_snapshot_score"] == pytest.approx(100.0, abs=1e-9)


def _setup_two_certified_shops_same_location(api):
    """LOW shop: live score 85.0; HIGH shop: live score 100.0. Both
    CERTIFIED at identical coordinates.

    The gap is produced through a PRD-listed recompute trigger (the
    publish-revision cascade). Both shops attest two published, effective
    EQUIPMENT rows (EQ-RANK-01, EQ-RANK-02) and certify at 100.0. A revision
    of EQ-RANK-01, effective at the current logical clock, supersedes it and
    lapses both shops' pinned attestations: each shop then satisfies 1 of 2
    published effective rows, so per §3.2 the score is 30*(1/2)+30+15+25 =
    85.0. HIGH then attests the new revision, restoring 100.0; LOW does not
    and stays at 85.0.
    """
    low = create_shop(legal_name="Low Compliance Body", state_code="CA", zip_code="90001",
                      latitude=34.05, longitude=-118.24)
    high = create_shop(legal_name="High Compliance Body", state_code="CA", zip_code="90001",
                       latitude=34.05, longitude=-118.24)
    req = create_published_requirement(
        requirement_code="EQ-RANK-01", category="EQUIPMENT",
        description="Rivet gun", severity_if_failed="MINOR",
        effective_from="2026-09-01T00:00:00Z")
    req2 = create_published_requirement(
        requirement_code="EQ-RANK-02", category="EQUIPMENT",
        description="Panel bond adhesive", severity_if_failed="MINOR",
        effective_from="2026-09-01T00:00:00Z")
    attest(low["id"], req["id"])
    attest(low["id"], req2["id"])
    attest(high["id"], req["id"])
    attest(high["id"], req2["id"])
    certify_shop(low["id"], scheduled_start="2026-09-01T01:00:00Z",
                 scheduled_end="2026-09-01T09:00:00Z", begin_at="2026-09-01T02:00:00Z")
    certify_shop_with_auditor(high["id"], AUD2, scheduled_start="2026-09-01T10:00:00Z",
                              scheduled_end="2026-09-01T18:00:00Z", begin_at="2026-09-01T11:00:00Z")
    # Revision cascade (a PRD-listed recompute trigger) lapses both shops'
    # EQ-RANK-01 attestations: both fall to 85.0. HIGH then attests the new
    # revision and recovers to 100.0; LOW stays at 85.0.
    rev = validate_success(api.publish_revision(
        req["id"],
        {"description": "Rivet gun v2", "severity_if_failed": "MINOR",
         "effective_from": "2026-09-01T11:00:00Z"},
        ADMIN), 201)
    attest(high["id"], rev["id"])
    return low, high


def test_referral_ranking_three_factor_nonlinear(api):
    """PRD §3.8: "Each candidate is scored as 0.6 times (1 minus the distance
    in miles divided by 25), plus 0.3 times (the shop's live_compliance_score
    divided by 100.0), plus 0.1 times (1 minus the capped load fraction, where
    the capped load fraction is the smaller of pending_referral_count and 20,
    divided by 20) ... A successful route moves the referral UNROUTED →
    ROUTED, stamps routed_at with the logical clock, records the winner as
    routed_shop_id, and increments that shop's pending_referral_count."

    Design: Difficulty/combinatorial_formula/referral_ranking_three_factor_nonlinear
    """
    low, high = _setup_two_certified_shops_same_location(api)
    ref = validate_success(api.create_referral(
        {"consumer_zip": "90001", "source_type": "CONSUMER_DIRECT",
         "source_reference": "WEB", "vin": "1HGCV1F34LA000002"}, DEALER), 201)
    assert ref["status"] == "ROUTED"
    assert ref["routed_shop_id"] == high["id"]
    high_now = validate_success(api.get_shop(high["id"], ADMIN))
    low_now = validate_success(api.get_shop(low["id"], ADMIN))
    assert high_now["pending_referral_count"] == 1
    assert low_now["pending_referral_count"] == 0
    assert low_now["live_compliance_score"] == pytest.approx(85.0, abs=1e-9)
    assert high_now["live_compliance_score"] == pytest.approx(100.0, abs=1e-9)


def test_referral_ranking_load_term_drag(api):
    """PRD §3.8: "plus 0.1 times (1 minus the capped load fraction, where the
    capped load fraction is the smaller of pending_referral_count and 20,
    divided by 20)". Each pending referral costs the leader 0.005 of score;
    once the accumulated drag exceeds the 0.045 compliance gap (with the
    9-pending tie breaking to the higher live score per §3.8), the next
    referral flips to the other shop.

    Design: Difficulty/combinatorial_formula/referral_ranking_three_factor_nonlinear
    """
    low, high = _setup_two_certified_shops_same_location(api)
    for i in range(10):
        ref = validate_success(api.create_referral(
            {"consumer_zip": "90001", "source_type": "CONSUMER_DIRECT",
             "source_reference": "WEB", "vin": f"1HGCV1F34LA{900 + i:06d}"}, DEALER), 201)
        assert ref["routed_shop_id"] == high["id"], (
            f"referral {i + 1} should still route to the high-compliance shop "
            "(at 9 pending the scores tie at 0.955 and the live-score "
            "tie-break keeps the leader)")
    eleventh = validate_success(api.create_referral(
        {"consumer_zip": "90001", "source_type": "CONSUMER_DIRECT",
         "source_reference": "WEB", "vin": "1HGCV1F34LA000911"}, DEALER), 201)
    assert eleventh["routed_shop_id"] == low["id"], (
        "after 10 pending referrals the load drag (0.05) exceeds the 0.045 "
        "compliance gap, flipping the routing")
