"""Difficulty queue A — scoring variants and pinned rounding."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    create_contribution,
    create_family,
    create_referral,
    create_stay_request,
    get_contribution,
    get_stay,
    get_stay_request,
    make_family_contact_headers,
    set_clock,
    setup_hospital_house,
    setup_waitlisted_request,
    validate_error,
    validate_success,
    verify_referral,
    offer_request,
    respond_request,
    check_in_request,
    HM,
)


def test_priority_score_provisional_vs_verified_diverge_at_verify(api):
    """PRD §2.8: "The provisional variant runs at request creation and reads the
    family's self-reported acuity; the result is stored on provisional_score. The
    verified variant runs when the linked referral becomes VERIFIED — either at
    creation if the referral was already verified, or later as part of the
    verification cascade — and reads the hospital-attested acuity_level from the
    referral; the result is stored on verified_score."

    Design: Difficulty/dual_variant_calc/priority_score_provisional_vs_verified_diverge
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    family = create_family(distance_miles=120)
    referral = create_referral(family["id"], hospital["id"], acuity_level="MODERATE")
    sr = create_stay_request(
        family, house["id"], referral["id"],
        expected_nights=15, self_reported_acuity="HIGH",
    )
    assert sr["verification_status"] == "UNVERIFIED"
    assert sr["verified_score"] is None
    assert sr["provisional_score"] == pytest.approx(100.00, abs=0.001), (
        f"60 band * 1.5 HIGH + 20 * 15/30 = 100.00 capped, got {sr['provisional_score']}"
    )

    verify_referral(referral["id"], decision="APPROVE")
    after = get_stay_request(sr["id"])
    assert after["verification_status"] == "VERIFICATION_OK"
    assert after["verified_score"] == pytest.approx(85.00, abs=0.001), (
        f"60 band * 1.25 MODERATE + 20 * 15/30 = 85.00, got {after['verified_score']}"
    )
    assert after["provisional_score"] == pytest.approx(100.00, abs=0.001)
    assert after["provisional_score"] != after["verified_score"]


def test_priority_score_provisional_vs_verified_diverge_values_differ(api):
    """PRD §2.8: "Because the two inputs can disagree, identical requests can
    carry different provisional and verified numbers."

    Design: Difficulty/dual_variant_calc/priority_score_provisional_vs_verified_diverge
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    family = create_family(distance_miles=120)
    referral = create_referral(family["id"], hospital["id"], acuity_level="MODERATE")
    sr = create_stay_request(
        family, house["id"], referral["id"],
        expected_nights=15, self_reported_acuity="HIGH",
    )
    verify_referral(referral["id"], decision="APPROVE")
    after = get_stay_request(sr["id"])
    assert after["provisional_score"] == pytest.approx(100.00, abs=0.001)
    assert after["verified_score"] == pytest.approx(85.00, abs=0.001)


def test_contribution_estimated_vs_settled_diverge_on_checkout(api):
    """PRD §3.6: "Fourth, every ContributionRequest on the stay whose status is
    OPEN or PARTIALLY_PAID is settled and forgiven: the system computes
    actual_nights as the calendar-day difference between actual_check_out_date
    and check_in_date, computes settled_amount_cents as per_night_cents
    multiplied by actual_nights, re-anchors requested_amount_cents to that
    settled value, sets forgiven_cents to the resulting outstanding_cents,
    zeroes outstanding_cents, and moves the request to FORGIVEN."

    Design: Difficulty/dual_variant_calc/contribution_estimated_vs_settled_diverge
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    family = create_family(distance_miles=120)
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house["id"], referral["id"], expected_nights=15)
    offered = offer_request(sr["id"], rooms[0]["id"])
    set_clock("2026-09-02T00:00:00Z")
    respond_request(sr["id"], family["id"], "ACCEPT")
    stay = check_in_request(sr["id"])
    cr = create_contribution(
        stay["id"], nightly_rate_cents=1005, planned_nights=10, hardship_tier="PARTIAL"
    )
    assert cr["per_night_cents"] == 503, "round_half_up(1005 * 0.5) = 503"
    assert cr["requested_amount_cents"] == 5030, "503 * 10 planned nights"

    set_clock("2026-09-09T00:00:00Z")
    out = validate_success(api.check_out_stay(stay["id"], HM))
    assert out["status"] == "CHECKED_OUT"
    assert out["actual_check_out_date"] == "2026-09-09"

    after = get_contribution(cr["id"])
    assert after["per_night_cents"] == 503
    assert after["settled_amount_cents"] == 3521, "503 * 7 actual nights"
    assert after["requested_amount_cents"] == 3521, "re-anchored from 5030"
    assert after["status"] == "FORGIVEN"
    assert after["forgiven_cents"] == 3521
    assert after["outstanding_cents"] == 0


def test_contribution_estimated_vs_settled_diverge_estimated_variant(api):
    """PRD §3.8: "The requested_amount_cents is then per_night_cents multiplied
    by planned_nights, computed at creation."
    PRD §2.12: "the per-night amount is rounded first, and only then multiplied
    by the number of nights."

    Design: Difficulty/dual_variant_calc/contribution_estimated_vs_settled_diverge
    """
    ctx = None
    from test_helpers import setup_active_stay
    ctx = setup_active_stay(check_in_clock="2026-09-02T00:00:00Z")
    cr = create_contribution(
        ctx["stay"]["id"], nightly_rate_cents=1005, planned_nights=10, hardship_tier="PARTIAL"
    )
    assert cr["per_night_cents"] == 503
    assert cr["requested_amount_cents"] == 5030, "estimated variant uses planned_nights"
    assert cr["settled_amount_cents"] is None, "settled variant null until check-out"
    assert cr["status"] == "OPEN"


def test_priority_score_nested_min_max_and_tiers_capped(api):
    """PRD §2.8: "Fourth, the raw score is the band value multiplied by the acuity
    multiplier, plus 20.0 times the stay-length factor; the raw score is capped at
    100.0. The final stored value is the capped raw score rounded to exactly 2
    decimal places using round-half-up."

    Design: Difficulty/combinatorial_formula/priority_score_nested_min_max_and_tiers
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    fam1 = create_family(family_name="Far", distance_miles=300)
    fam2 = create_family(family_name="Near", distance_miles=60)
    ref1 = create_referral(fam1["id"], hospital["id"], acuity_level="CRITICAL",
                           treating_unit="ICU", attending_clinician="Dr. Rao")
    ref2 = create_referral(fam2["id"], hospital["id"], acuity_level="LOW",
                           care_type="OUTPATIENT", treating_unit="Clinic",
                           attending_clinician="Dr. Rao")
    verify_referral(ref1["id"])
    verify_referral(ref2["id"])
    sr1 = create_stay_request(fam1, house["id"], ref1["id"],
                              expected_nights=40, self_reported_acuity="CRITICAL")
    sr2 = create_stay_request(fam2, house["id"], ref2["id"],
                              expected_nights=9, self_reported_acuity="LOW")
    got1 = get_stay_request(sr1["id"])
    got2 = get_stay_request(sr2["id"])
    assert got1["verified_score"] == pytest.approx(100.00, abs=0.001), (
        "raw 80*2.0 + 20*min(30,40)/30 = 180.00, capped by outer min to 100.00"
    )
    assert got2["verified_score"] == pytest.approx(46.00, abs=0.001), (
        "40*1.0 + 20*9/30 = 46.00, no cap engaged"
    )


def test_priority_score_stay_factor_cap_at_30_nights(api):
    """PRD §2.8: "Third, compute a stay-length factor by capping expected_nights
    at 30 nights and dividing by 30 — a request for 30 or more nights contributes
    a factor of exactly 1.0, while a request for 15 nights contributes 0.5."

    Design: Difficulty/combinatorial_formula/priority_score_nested_min_max_and_tiers
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    # 250 miles (band 80) / CRITICAL (2.0) -> 160 already over cap; nights 40 vs 30
    # both saturate the stay factor at 1.0, so both land at the 100 cap.
    fam_a = create_family(family_name="Thirty", distance_miles=60)
    fam_b = create_family(family_name="Forty", distance_miles=60)
    ref_a = create_referral(fam_a["id"], hospital["id"], acuity_level="LOW")
    ref_b = create_referral(fam_b["id"], hospital["id"], acuity_level="LOW")
    verify_referral(ref_a["id"])
    verify_referral(ref_b["id"])
    sr_a = create_stay_request(fam_a, house["id"], ref_a["id"],
                               expected_nights=30, self_reported_acuity="LOW")
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"],
                               expected_nights=40, self_reported_acuity="LOW")
    a = get_stay_request(sr_a["id"])
    b = get_stay_request(sr_b["id"])
    # 40*1.0 + 20*min(30,30)/30 = 60.00; 40*1.0 + 20*min(30,40)/30 = 60.00
    assert a["verified_score"] == pytest.approx(60.00, abs=0.001)
    assert b["verified_score"] == pytest.approx(60.00, abs=0.001), (
        "expected_nights above the 30-night cap must not raise the score"
    )


def test_contribution_per_night_rounding_order_pinned(api):
    """PRD §2.12: "Per-night rounding on contribution requests uses round-half-up
    to the nearest cent (so 502.5 rounds to 503), and the rounding is pinned: the
    per-night amount is rounded first, and only then multiplied by the number of
    nights. This pinned order is contract-bearing because the alternative order
    (multiply first, then round) can yield a different total."

    Design: Difficulty/combinatorial_formula/contribution_per_night_rounding_order_pinned
    """
    from test_helpers import setup_active_stay
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_stay(check_in_clock="2026-09-02T00:00:00Z")
    cr = create_contribution(
        ctx["stay"]["id"], nightly_rate_cents=1005, planned_nights=10, hardship_tier="PARTIAL"
    )
    set_clock("2026-09-09T00:00:00Z")
    validate_success(api.check_out_stay(ctx["stay"]["id"], HM))
    after = get_contribution(cr["id"])
    assert after["per_night_cents"] == 503, "round_half_up(1005 * 0.5) = 503"
    assert after["settled_amount_cents"] == 3521, (
        "503 * 7 = 3521; multiply-then-round would yield round_half_up(1005*0.5*7) = 3518"
    )


def test_contribution_per_night_rounding_half_cent_up(api):
    """PRD §2.12: "Per-night rounding on contribution requests uses round-half-up
    to the nearest cent (so 502.5 rounds to 503)".

    Design: Difficulty/combinatorial_formula/contribution_per_night_rounding_order_pinned
    """
    from test_helpers import setup_active_stay
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_stay(check_in_clock="2026-09-02T00:00:00Z")
    cr = create_contribution(
        ctx["stay"]["id"], nightly_rate_cents=1005, planned_nights=1, hardship_tier="PARTIAL"
    )
    assert cr["per_night_cents"] == 503, "502.5 rounds half-up to 503"
    assert cr["requested_amount_cents"] == 503


def test_assignment_sweep_expire_before_promote_evaluation_order(api):
    """PRD §3.12: "Step 1 expires stale offers: every stay request whose
    assignment_status is OFFERED and whose offer_expires_at is strictly before
    the current logical clock transitions back to WAITLISTED, releasing its room
    reservation. ... Step 3 snapshots capacity: the snapshot is the count of rooms
    that are AVAILABLE, occupied false, and unreserved after steps 1 and 2 have
    completed ... Step 4 promotes in the waitlist ranking order of §2.9".

    Design: Difficulty/combinatorial_formula/assignment_sweep_expire_before_promote_evaluation_order
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    room = rooms[0]
    fam_x = create_family(family_name="Exton", distance_miles=120)
    fam_y = create_family(family_name="York", distance_miles=150)
    ref_x = create_referral(fam_x["id"], hospital["id"], acuity_level="LOW",
                            treating_unit="Ward A", attending_clinician="Dr. Rao")
    ref_y = create_referral(fam_y["id"], hospital["id"], acuity_level="CRITICAL",
                            treating_unit="Ward B", attending_clinician="Dr. Rao")
    verify_referral(ref_x["id"])
    verify_referral(ref_y["id"])
    sr_x = create_stay_request(fam_x, house["id"], ref_x["id"],
                               expected_nights=5, self_reported_acuity="LOW")
    offer_request(sr_x["id"], room["id"])
    sr_y = create_stay_request(fam_y, house["id"], ref_y["id"],
                               expected_nights=30, self_reported_acuity="CRITICAL")

    set_clock("2026-09-04T00:00:00Z")
    result = validate_success(api.run_assignment_sweep(house["id"], HM))

    assert sr_x["id"] in result["expired_offer_ids"], "offer from 2026-09-01 expired after 48h"
    assert result["promoted_request_ids"] == [sr_y["id"]], (
        "Y promoted into the room X just freed — expire-before-promote ordering"
    )
    after_y = get_stay_request(sr_y["id"])
    assert after_y["verified_score"] == pytest.approx(100.00, abs=0.001), (
        "150 mi band 60 * CRITICAL 2.0 + 20 * min(30,30)/30 = 140.00 capped to 100.00"
    )
    assert after_y["assignment_status"] == "OFFERED"
    assert after_y["offered_room_id"] == room["id"]
    after_x = get_stay_request(sr_x["id"])
    assert after_x["assignment_status"] == "WAITLISTED"
    assert after_x["offered_room_id"] is None


def test_assignment_sweep_promoted_request_does_not_reenter_same_sweep(api):
    """PRD §3.12: "Offers made inside step 4 do not re-enter the same sweep's
    candidate set."

    Design: Difficulty/combinatorial_formula/assignment_sweep_expire_before_promote_evaluation_order
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    fam = create_family(distance_miles=150)
    ref = create_referral(fam["id"], hospital["id"], acuity_level="CRITICAL")
    verify_referral(ref["id"])
    sr = create_stay_request(fam, house["id"], ref["id"],
                             expected_nights=30, self_reported_acuity="CRITICAL")
    result = validate_success(api.run_assignment_sweep(house["id"], HM))
    assert result["promoted_request_ids"] == [sr["id"]]
    # The promoted offer is fresh (offer_expires_at = now + 48h); a request whose
    # offer was made inside the sweep is not also in expired_offer_ids.
    assert sr["id"] not in result["expired_offer_ids"]
    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "OFFERED"
    assert after["offered_room_id"] == rooms[0]["id"]
