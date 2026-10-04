"""Corner queue B — calculation ordering, selectors, thresholds, rollups."""
from test_helpers import (
    ADMIN,
    HM,
    create_donation,
    create_family,
    create_referral,
    create_room,
    create_stay_request,
    get_house,
    get_stay,
    get_stay_request,
    offer_request,
    respond_request,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    validate_paginated,
    validate_success,
    verify_referral,
    check_in_request,
    create_hospital,
    create_house,
)


def test_waitlist_tie_break_waitlisted_since_then_created_at(api):
    """PRD §2.9: "Eligible requests are ranked by verified_score in descending
    order; ties are broken by waitlisted_since in ascending order so the
    longest-waiting request wins; any remaining tie is broken by created_at
    ascending."

    Design: Corner/calculations/waitlist_tie_break_waitlisted_since_then_created_at
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    room = rooms[0]
    fam_a = create_family(family_name="Alvarez", distance_miles=120)
    fam_b = create_family(family_name="Baker", distance_miles=120, home_city="Riverton",
                          primary_contact_name="Bob Baker", child_patient_name="Kate Baker")
    ref_a = create_referral(fam_a["id"], hospital["id"], acuity_level="MODERATE")
    ref_b = create_referral(fam_b["id"], hospital["id"], acuity_level="MODERATE")
    verify_referral(ref_a["id"])
    verify_referral(ref_b["id"])
    sr_a = create_stay_request(fam_a, house["id"], ref_a["id"], expected_nights=15)
    set_clock("2026-09-01T01:00:00Z")
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"], expected_nights=15)

    assert get_stay_request(sr_a["id"])["verified_score"] == 85.00
    assert get_stay_request(sr_b["id"])["verified_score"] == 85.00, "exact tie"

    result = validate_success(api.run_assignment_sweep(house["id"], HM))
    assert result["promoted_request_ids"] == [sr_a["id"]], (
        "earlier waitlisted_since wins the tie"
    )
    after_a = get_stay_request(sr_a["id"])
    assert after_a["assignment_status"] == "OFFERED"
    assert after_a["offered_room_id"] == room["id"]
    after_b = get_stay_request(sr_b["id"])
    assert after_b["assignment_status"] == "WAITLISTED"


def test_room_selector_prefers_smallest_bed_count(api):
    """PRD §2.9: "Among eligible rooms, the selector picks the one with the
    smallest bed_count; ties are broken by room_number in ascending lexicographic
    order."

    Design: Corner/calculations/room_selector_prefers_smallest_bed_count
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=0)
    r_big = create_room(house["id"], room_number="201", bed_count=4, occupancy_limit=4)
    r_small = create_room(house["id"], room_number="202", bed_count=2, occupancy_limit=2)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house["id"], referral["id"], expected_nights=15)

    validate_success(api.run_assignment_sweep(house["id"], HM))
    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "OFFERED"
    assert after["offered_room_id"] == r_small["id"], "bed_count ASC selector"

    big = validate_success(api.get_room(r_big["id"], HM))
    assert big["status"] == "AVAILABLE"
    house_after = get_house(house["id"])
    assert house_after["reserved_room_count"] == 1


def test_stay_review_threshold_boundary_20_vs_21_nights(api):
    """PRD §3.12: "For each, it computes nights_at_house as the whole calendar-day
    difference between the current logical date and the stay's check_in_date. When
    nights_at_house is at least 21, the stay transitions to UNDER_REVIEW with
    review_reason set to STAY_LENGTH. The boundary is exact: a stay at exactly 21
    nights is flagged, while a stay at 20 nights is not."

    Design: Corner/calculations/stay_review_threshold_boundary_20_vs_21_nights
    """
    # Default clock 2026-09-01; check in on that date.
    ctx = setup_active_stay(request_overrides={"expected_nights": 30})
    stay = ctx["stay"]
    house = ctx["house"]

    set_clock("2026-09-21T00:00:00Z")
    result20 = validate_success(api.run_stay_review_sweep(house["id"], HM))
    assert result20["flagged_stay_ids"] == [], "20 nights: not flagged"
    assert get_stay(stay["id"])["status"] == "ACTIVE"

    set_clock("2026-09-22T00:00:00Z")
    result21 = validate_success(api.run_stay_review_sweep(house["id"], HM))
    assert result21["flagged_stay_ids"] == [stay["id"]], "21 nights: flagged"
    after = get_stay(stay["id"])
    assert after["status"] == "UNDER_REVIEW"
    assert after["review_reason"] == "STAY_LENGTH"


def test_supply_rollup_sums_across_donations(api):
    """PRD §3.11: "The house's supply-inventory view aggregates across all
    donations of the house regardless of status: for each supply_category, on-hand
    is the sum of quantity_received minus quantity_distributed over every donation
    in that category, with DEPLETED donations naturally contributing 0."

    Design: Corner/calculations/supply_rollup_sums_across_donations
    """
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    don1 = create_donation(house["id"], donor_name="Rotary Club",
                           supply_category="HYGIENE_KIT", quantity_received=10)
    create_donation(house["id"], donor_name="Lions Club",
                    supply_category="HYGIENE_KIT", quantity_received=5)
    distributed = validate_success(
        api.distribute_in_kind_donation(don1["id"], {"quantity": 6}, HM)
    )
    assert distributed["status"] == "PARTIALLY_DISTRIBUTED"
    assert distributed["quantity_distributed"] == 6

    inv = validate_success(api.get_supply_inventory(house["id"], HM))
    assert inv["HYGIENE_KIT"] == 9, "10 + 5 - 6"
    assert inv["PANTRY_STAPLE"] == 0
    assert inv["CLEANING_SUPPLY"] == 0
    assert inv["BABY_SUPPLY"] == 0


def test_house_posture_threshold_bands(api):
    """PRD §2.7: "the house is FULL when the ratio equals exactly 1.0,
    NEAR_CAPACITY when the ratio is at least 0.9 but strictly less than 1.0, and
    OPEN when the ratio is strictly below 0.9. The 0.9 boundary is inclusive on
    the NEAR_CAPACITY side; the comparison is exact, with no rounding."

    Design: Corner/calculations/house_posture_threshold_bands
    """
    # Small house: 3 rooms, 1 occupied -> ratio 1/3 < 0.9 -> OPEN.
    hospital, house_s, rooms_s = setup_hospital_house(num_rooms=3)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house_s["id"], referral["id"], expected_nights=3)
    offer_request(sr["id"], rooms_s[0]["id"])
    respond_request(sr["id"], family["id"], "ACCEPT")
    check_in_request(sr["id"])

    h = get_house(house_s["id"])
    assert h["posture"] == "OPEN"
    assert h["occupied_room_count"] == 1, "ratio 1/3 < 0.9"
    assert h["available_room_count"] == 2
    assert h["reserved_room_count"] == 0
