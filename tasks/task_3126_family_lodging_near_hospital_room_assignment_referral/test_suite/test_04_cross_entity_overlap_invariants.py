"""Difficulty queue A — cross-entity state gating, overlap rules, conserved invariants."""
import pytest

from test_helpers import (
    HM,
    VC,
    ApiErrorId,
    create_care_space,
    create_certified_group,
    create_contribution,
    create_family,
    create_meal_shift,
    create_referral,
    create_stay_request,
    create_volunteer_group,
    get_contribution,
    get_house,
    get_room,
    get_stay,
    get_stay_request,
    make_family_contact_headers,
    make_hospital_referrer_headers,
    offer_request,
    record_pass_screening,
    respond_request,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    setup_offered_request,
    setup_waitlisted_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_referral,
    check_in_request,
)


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / offer_requires_room_available_pair_stayrequest_room
# ---------------------------------------------------------------------------

def test_offer_requires_room_available_pair_stayrequest_room(api):
    """PRD §3.4: "The room itself must have status equal to AVAILABLE, occupied
    equal to false, and must not be reserved by any other OFFERED request — any
    of these failures surfaces as ERR_ROOM_NOT_AVAILABLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/offer_requires_room_available_pair_stayrequest_room
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=2)
    room1, room2 = rooms
    validate_success(api.set_room_status(room2["id"], {"target_status": "MAINTENANCE"}, HM))

    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house["id"], referral["id"])

    resp = api.offer_stay_request(sr["id"], {"room_id": room2["id"]}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)

    ok = offer_request(sr["id"], room1["id"])
    assert ok["assignment_status"] == "OFFERED"
    assert ok["offered_room_id"] == room1["id"]

    room2_after = get_room(room2["id"])
    assert room2_after["status"] == "MAINTENANCE"
    assert room2_after["occupied"] is False


def test_offer_to_offline_room_rejected_room_not_available(api):
    """PRD §3.4: "The room itself must have status equal to AVAILABLE, occupied
    equal to false, and must not be reserved by any other OFFERED request — any
    of these failures surfaces as ERR_ROOM_NOT_AVAILABLE (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/offer_requires_room_available_pair_stayrequest_room
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=2)
    room1, room2 = rooms
    validate_success(api.set_room_status(room2["id"], {"target_status": "OFFLINE"}, HM))

    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house["id"], referral["id"])

    resp = api.offer_stay_request(sr["id"], {"room_id": room2["id"]}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)
    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "WAITLISTED"


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / meal_shift_claim_requires_certified_volunteer_group
# ---------------------------------------------------------------------------

def test_meal_shift_claim_requires_certified_volunteer_group(api):
    """PRD §3.9: "The named group's certification_status must not be UNCERTIFIED —
    otherwise ERR_FOOD_SAFETY_CERT_REQUIRED (HTTP 422). And the group's
    certified_until must be on or after the shift's shift_date — otherwise
    ERR_FOOD_SAFETY_CERT_EXPIRED (HTTP 422)."

    Design: Difficulty/cross_entity_state_dependency/meal_shift_claim_requires_certified_volunteer_group
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    shift1 = create_meal_shift(house["id"], shift_date="2026-09-08", meal_type="LUNCH")
    shift2 = create_meal_shift(house["id"], shift_date="2026-09-12", meal_type="DINNER")
    g_ok = create_certified_group(certified_until="2026-09-10")
    g_uncert = create_volunteer_group(group_name="New Volunteers", contact_email="new@vol.org")

    resp1 = api.claim_meal_shift(shift1["id"], {"volunteer_group_id": g_uncert["id"]}, VC)
    assert resp1.status_code == 422
    validate_error(resp1, ApiErrorId.ERR_FOOD_SAFETY_CERT_REQUIRED)

    claimed = validate_success(api.claim_meal_shift(shift1["id"], {"volunteer_group_id": g_ok["id"]}, VC))
    assert claimed["status"] == "CLAIMED"
    assert claimed["claimed_by_group_id"] == g_ok["id"]

    resp2 = api.claim_meal_shift(shift2["id"], {"volunteer_group_id": g_ok["id"]}, VC)
    assert resp2.status_code == 422
    validate_error(resp2, ApiErrorId.ERR_FOOD_SAFETY_CERT_EXPIRED)
    shifts, _ = validate_paginated(api.list_meal_shifts(house["id"], HM, params={"shift_date": "2026-09-12"}))
    assert shifts[0]["status"] == "OPEN"
    assert shifts[0]["claimed_by_group_id"] is None


def test_meal_shift_claim_certified_on_shift_date_boundary(api):
    """PRD §3.9: "And the group's certified_until must be on or after the shift's
    shift_date — otherwise ERR_FOOD_SAFETY_CERT_EXPIRED (HTTP 422)." On the shift
    date itself the certification is still valid.

    Design: Difficulty/cross_entity_state_dependency/meal_shift_claim_requires_certified_volunteer_group
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    shift = create_meal_shift(house["id"], shift_date="2026-09-08", meal_type="LUNCH")
    group = create_certified_group(certified_until="2026-09-08")
    claimed = validate_success(api.claim_meal_shift(shift["id"], {"volunteer_group_id": group["id"]}, VC))
    assert claimed["status"] == "CLAIMED"
    assert claimed["claimed_by_group_id"] == group["id"]


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / stay_extension_requires_verified_referral_pair_stay_referral
# ---------------------------------------------------------------------------

def _setup_transition_planned_stay_with_revoked_referral(api):
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay(request_overrides={"expected_nights": 15})
    stay = ctx["stay"]
    fam = ctx["family"]
    validate_success(api.request_extension(
        stay["id"], {"additional_nights": 5}, make_family_contact_headers(fam["id"])))
    planned = validate_success(api.review_stay(
        stay["id"],
        {"decision": "PLAN_TRANSITION",
         "transition_plan_notes": "Move to outpatient housing by 2026-09-20."},
        HM))
    assert planned["status"] == "TRANSITION_PLANNED"
    validate_success(api.revoke_referral(
        ctx["referral"]["id"], make_hospital_referrer_headers(ctx["hospital"]["id"])))
    return ctx


def test_stay_extension_requires_verified_referral_pair_stay_referral(api):
    """PRD §3.5: "The same APPROVE_EXTENSION decision applied to a
    TRANSITION_PLANNED stay requires approved_extension_count to be strictly less
    than 2 (else ERR_TRANSITION_PLAN_REQUIRED) and the originating referral to be
    VERIFIED (else ERR_REFERRAL_NOT_VERIFIED); on success, transition_plan_notes
    and review_reason are cleared and the stay returns to ACTIVE."
    PRD §3.2: "stays already in UNDER_REVIEW, TRANSITION_PLANNED, or
    RELOCATION_REQUIRED are left alone."

    Design: Difficulty/cross_entity_state_dependency/stay_extension_requires_verified_referral_pair_stay_referral
    """
    ctx = _setup_transition_planned_stay_with_revoked_referral(api)
    stay = ctx["stay"]

    after_revoke = get_stay(stay["id"])
    assert after_revoke["status"] == "TRANSITION_PLANNED", (
        "the revoke cascade left the TRANSITION_PLANNED stay untouched"
    )

    resp = api.review_stay(stay["id"], {"decision": "APPROVE_EXTENSION"}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_VERIFIED)

    final = get_stay(stay["id"])
    assert final["expected_check_out_date"] == stay["expected_check_out_date"]
    assert final["transition_plan_notes"] == "Move to outpatient housing by 2026-09-20."


def test_stay_extension_request_on_active_stay_requires_verified_referral(api):
    """PRD §3.5: "The referral that backs the originating stay request must still
    be VERIFIED — otherwise ERR_REFERRAL_NOT_VERIFIED."

    Design: Difficulty/cross_entity_state_dependency/stay_extension_requires_verified_referral_pair_stay_referral
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]
    validate_success(api.revoke_referral(
        ctx["referral"]["id"], make_hospital_referrer_headers(ctx["hospital"]["id"])))
    # Revocation moved the ACTIVE stay to UNDER_REVIEW; bring it back via DENY.
    under = get_stay(stay["id"])
    assert under["status"] == "UNDER_REVIEW"
    validate_success(api.review_stay(stay["id"], {"decision": "DENY_EXTENSION"}, HM))
    active = get_stay(stay["id"])
    assert active["status"] == "ACTIVE"

    resp = api.request_extension(
        stay["id"], {"additional_nights": 3}, make_family_contact_headers(fam["id"]))
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_VERIFIED)


# ---------------------------------------------------------------------------
# resource_temporal_overlap / room_half_open_interval_same_day_turnover
# ---------------------------------------------------------------------------

def test_room_half_open_interval_same_day_turnover(api):
    """PRD §2.10: "A room's occupancy is modeled as a half-open interval that
    begins on the stay's check_in_date and ends on the stay's
    actual_check_out_date. The half-open semantics mean a check-out on calendar
    date D frees the room for a check-in on the same date D — same-day turnover is
    explicitly allowed. Any offer, check-in, or relocation that targets a room
    whose occupied flag is currently true, or that is reserved by another OFFERED
    request, is rejected with ERR_ROOM_NOT_AVAILABLE (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/room_half_open_interval_same_day_turnover
    """
    set_clock("2026-09-02T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    room = rooms[0]
    fam_a = create_family(family_name="Alvarez", distance_miles=120)
    fam_b = create_family(family_name="Baker", distance_miles=150, home_city="Hilltown",
                          primary_contact_name="Bob Baker", child_patient_name="Kate Baker")
    ref_a = create_referral(fam_a["id"], hospital["id"], acuity_level="MODERATE")
    ref_b = create_referral(fam_b["id"], hospital["id"], acuity_level="HIGH",
                            treating_unit="Cardiology")
    verify_referral(ref_a["id"])
    verify_referral(ref_b["id"])
    sr_a = create_stay_request(fam_a, house["id"], ref_a["id"], expected_nights=3)
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"], expected_nights=5,
                               self_reported_acuity="HIGH")
    offer_request(sr_a["id"], room["id"])
    respond_request(sr_a["id"], fam_a["id"], "ACCEPT")
    stay_a = check_in_request(sr_a["id"])

    set_clock("2026-09-04T00:00:00Z")
    resp = api.offer_stay_request(sr_b["id"], {"room_id": room["id"]}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)

    set_clock("2026-09-05T00:00:00Z")
    validate_success(api.check_out_stay(stay_a["id"], HM))
    after_b = get_stay_request(sr_b["id"])
    assert after_b["assignment_status"] == "OFFERED", (
        "same-day turnover allowed: checkout cascade immediately re-offers"
    )
    assert after_b["offered_room_id"] == room["id"]


def test_same_day_turnover_check_in_after_checkout(api):
    """PRD §2.10: "The half-open semantics mean a check-out on calendar date D
    frees the room for a check-in on the same date D — same-day turnover is
    explicitly allowed."

    Design: Difficulty/resource_temporal_overlap/room_half_open_interval_same_day_turnover
    """
    set_clock("2026-09-02T00:00:00Z")
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    room = rooms[0]
    fam_a = create_family(family_name="Alvarez", distance_miles=120)
    fam_b = create_family(family_name="Baker", distance_miles=150, home_city="Hilltown",
                          primary_contact_name="Bob Baker", child_patient_name="Kate Baker")
    ref_a = create_referral(fam_a["id"], hospital["id"], acuity_level="MODERATE")
    ref_b = create_referral(fam_b["id"], hospital["id"], acuity_level="HIGH",
                            treating_unit="Cardiology")
    verify_referral(ref_a["id"])
    verify_referral(ref_b["id"])
    sr_a = create_stay_request(fam_a, house["id"], ref_a["id"], expected_nights=3)
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"], expected_nights=5,
                               self_reported_acuity="HIGH")
    offer_request(sr_a["id"], room["id"])
    respond_request(sr_a["id"], fam_a["id"], "ACCEPT")
    stay_a = check_in_request(sr_a["id"])

    set_clock("2026-09-05T00:00:00Z")
    validate_success(api.check_out_stay(stay_a["id"], HM))
    # Cascade offered the freed room to B on the same calendar day; B accepts and
    # checks in on the same day.
    after_b = get_stay_request(sr_b["id"])
    assert after_b["assignment_status"] == "OFFERED"
    respond_request(sr_b["id"], fam_b["id"], "ACCEPT")
    stay_b = check_in_request(sr_b["id"])
    assert stay_b["status"] == "ACTIVE"
    assert stay_b["check_in_date"] == "2026-09-05"
    assert stay_b["room_id"] == room["id"]


# ---------------------------------------------------------------------------
# resource_temporal_overlap / care_space_cleaning_buffer_blocks_adjacent_booking
# ---------------------------------------------------------------------------

def _setup_care_space_with_verified_family(api):
    from test_helpers import create_hospital
    hospital = create_hospital()
    cs = create_care_space(hospital["id"])
    fam = create_family()
    ref = create_referral(fam["id"], hospital["id"])
    verify_referral(ref["id"])
    return hospital, cs, fam


def test_care_space_cleaning_buffer_blocks_adjacent_booking(api):
    """PRD §3.10: "Every CONFIRMED booking blocks a window that begins at its
    start_at and ends 30 minutes after its end_at — a 30-minute cleaning buffer
    follows each booking. A new booking whose interval intersects any existing
    blocked window is rejected with ERR_CARE_SPACE_CONFLICT (HTTP 409) ...
    Adjacency at exactly the buffer's end is allowed — a new booking whose
    start_at equals the prior booking's end_at plus 30 minutes is accepted, while
    one starting even one minute earlier is rejected."

    Design: Difficulty/resource_temporal_overlap/care_space_cleaning_buffer_blocks_adjacent_booking
    """
    hospital, cs, fam = _setup_care_space_with_verified_family(api)
    bk1 = validate_success(
        api.create_care_space_booking(
            cs["id"],
            {"family_id": fam["id"], "start_at": "2026-09-03T09:00:00Z",
             "end_at": "2026-09-03T10:00:00Z", "party_size": 3},
            HM),
        expected_status=201,
    )
    assert bk1["status"] == "CONFIRMED"

    resp = api.create_care_space_booking(
        cs["id"],
        {"family_id": fam["id"], "start_at": "2026-09-03T10:15:00Z",
         "end_at": "2026-09-03T11:00:00Z", "party_size": 2},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_CARE_SPACE_CONFLICT)

    bk2 = validate_success(
        api.create_care_space_booking(
            cs["id"],
            {"family_id": fam["id"], "start_at": "2026-09-03T10:30:00Z",
             "end_at": "2026-09-03T11:30:00Z", "party_size": 2},
            make_family_contact_headers(fam["id"])),
        expected_status=201,
    )
    assert bk2["status"] == "CONFIRMED", "adjacency at the buffer end is allowed"

    bookings, _ = validate_paginated(api.list_care_space_bookings(cs["id"], HM))
    confirmed = [b for b in bookings if b["status"] == "CONFIRMED"]
    assert len(confirmed) == 2


def test_care_space_buffer_one_minute_early_rejected(api):
    """PRD §3.10: "Adjacency at exactly the buffer's end is allowed — a new
    booking whose start_at equals the prior booking's end_at plus 30 minutes is
    accepted, while one starting even one minute earlier is rejected."

    Design: Difficulty/resource_temporal_overlap/care_space_cleaning_buffer_blocks_adjacent_booking
    """
    hospital, cs, fam = _setup_care_space_with_verified_family(api)
    validate_success(
        api.create_care_space_booking(
            cs["id"],
            {"family_id": fam["id"], "start_at": "2026-09-03T09:00:00Z",
             "end_at": "2026-09-03T10:00:00Z", "party_size": 3},
            HM),
        expected_status=201,
    )
    resp = api.create_care_space_booking(
        cs["id"],
        {"family_id": fam["id"], "start_at": "2026-09-03T10:29:00Z",
         "end_at": "2026-09-03T11:30:00Z", "party_size": 2},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_CARE_SPACE_CONFLICT)


# ---------------------------------------------------------------------------
# compensating_invariant / room_census_conserved_across_checkin_checkout
# ---------------------------------------------------------------------------

def test_room_census_conserved_across_checkin_checkout(api):
    """PRD §2.7: "occupied_room_count is the number of rooms whose occupied flag
    is true. reserved_room_count is the number of rooms held by an OFFERED stay
    request ... available_room_count is the number of rooms whose status is
    AVAILABLE, whose occupied flag is false, and which are not currently reserved
    by any OFFERED request."

    Design: Difficulty/compensating_invariant/room_census_conserved_across_checkin_checkout
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_offered_request()
    house = ctx["house"]

    h_offered = get_house(house["id"])
    assert h_offered["reserved_room_count"] == 1
    assert h_offered["occupied_room_count"] == 0
    assert h_offered["available_room_count"] == 0

    respond_request(ctx["request"]["id"], ctx["family"]["id"], "ACCEPT")
    stay = check_in_request(ctx["request"]["id"])
    h_checked_in = get_house(house["id"])
    assert h_checked_in["occupied_room_count"] == 1
    assert h_checked_in["reserved_room_count"] == 0
    assert h_checked_in["available_room_count"] == 0
    assert h_checked_in["posture"] == "FULL"

    validate_success(api.check_out_stay(stay["id"], HM))
    h_checked_out = get_house(house["id"])
    assert h_checked_out["occupied_room_count"] == 0
    assert h_checked_out["reserved_room_count"] == 0
    assert h_checked_out["available_room_count"] == 1
    assert h_checked_out["posture"] == "OPEN", (
        "forward + compensating action restored the census exactly"
    )


def test_room_census_sum_invariant_at_each_step(api):
    """PRD §2.7: "The denominator is the count of the house's rooms whose status
    is AVAILABLE — note that an occupied room keeps status AVAILABLE while a stay
    occupies it, so occupied rooms remain in the denominator."

    Design: Difficulty/compensating_invariant/room_census_conserved_across_checkin_checkout
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_offered_request()
    house = ctx["house"]
    respond_request(ctx["request"]["id"], ctx["family"]["id"], "ACCEPT")
    stay = check_in_request(ctx["request"]["id"])
    h = get_house(house["id"])
    # One AVAILABLE-status room total; occupied + reserved + available == 1.
    assert h["occupied_room_count"] + h["reserved_room_count"] + h["available_room_count"] == 1
    validate_success(api.check_out_stay(stay["id"], HM))
    h2 = get_house(house["id"])
    assert h2["occupied_room_count"] + h2["reserved_room_count"] + h2["available_room_count"] == 1


# ---------------------------------------------------------------------------
# compensating_invariant / contribution_ledger_decomposition_conserved
# ---------------------------------------------------------------------------

def _setup_stay_with_two_contributions(api):
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_stay(check_in_clock="2026-09-02T00:00:00Z",
                            request_overrides={"expected_nights": 4})
    cr1 = create_contribution(ctx["stay"]["id"], nightly_rate_cents=2500,
                              planned_nights=4, hardship_tier="NONE")
    cr2 = create_contribution(ctx["stay"]["id"], nightly_rate_cents=1000,
                              planned_nights=4, hardship_tier="NONE")
    return ctx, cr1, cr2


def test_contribution_ledger_decomposition_conserved(api):
    """PRD §3.8: "A contribution request's ledger is a conserved quantity at all
    times: requested_amount_cents always equals the sum of paid_cents,
    waived_cents, forgiven_cents, and outstanding_cents. The check-out settle step
    re-anchors requested_amount_cents to settled_amount_cents before computing
    forgiven_cents, so the invariant holds across the settle too."

    Design: Difficulty/compensating_invariant/contribution_ledger_decomposition_conserved
    """
    ctx, cr1, cr2 = _setup_stay_with_two_contributions(api)
    fam = ctx["family"]
    stay = ctx["stay"]

    p1 = validate_success(api.record_payment(
        cr1["id"], {"amount_cents": 3000}, make_family_contact_headers(fam["id"])))
    assert p1["paid_cents"] == 3000
    assert p1["outstanding_cents"] == 7000, "10000 == 3000 + 0 + 0 + 7000"

    validate_success(api.record_payment(
        cr2["id"], {"amount_cents": 1000}, make_family_contact_headers(fam["id"])))
    waived = validate_success(api.waive_contribution_request(cr2["id"], HM))
    assert waived["status"] == "WAIVED"
    assert waived["paid_cents"] == 1000
    assert waived["waived_cents"] == 3000
    assert waived["outstanding_cents"] == 0, "4000 == 1000 + 3000 + 0 + 0"

    set_clock("2026-09-04T00:00:00Z")
    out = validate_success(api.check_out_stay(stay["id"], HM))
    assert out["status"] == "CHECKED_OUT", (
        "checkout succeeded despite the unpaid CR1 balance — contributions are "
        "never a condition of stay"
    )

    after1 = get_contribution(cr1["id"])
    assert after1["requested_amount_cents"] == 5000, "re-anchored to settled 2500*2"
    assert after1["settled_amount_cents"] == 5000
    assert after1["paid_cents"] == 3000
    assert after1["forgiven_cents"] == 2000
    assert after1["outstanding_cents"] == 0
    assert after1["status"] == "FORGIVEN", "5000 == 3000 + 0 + 2000 + 0"

    after2 = get_contribution(cr2["id"])
    assert after2["status"] == "WAIVED", "checkout leaves WAIVED requests untouched"
    assert after2["paid_cents"] == 1000
    assert after2["waived_cents"] == 3000
    assert after2["outstanding_cents"] == 0


def test_contribution_ledger_holds_after_each_compensating_step(api):
    """PRD §3.8: "A contribution request's ledger is a conserved quantity at all
    times: requested_amount_cents always equals the sum of paid_cents,
    waived_cents, forgiven_cents, and outstanding_cents."

    Design: Difficulty/compensating_invariant/contribution_ledger_decomposition_conserved
    """
    ctx, cr1, cr2 = _setup_stay_with_two_contributions(api)
    fam = ctx["family"]
    stay = ctx["stay"]

    def assert_invariant(cr_id):
        cr = get_contribution(cr_id)
        total = cr["paid_cents"] + cr["waived_cents"] + cr["forgiven_cents"] + cr["outstanding_cents"]
        assert cr["requested_amount_cents"] == total

    assert_invariant(cr1["id"])
    assert_invariant(cr2["id"])
    validate_success(api.record_payment(
        cr1["id"], {"amount_cents": 3000}, make_family_contact_headers(fam["id"])))
    assert_invariant(cr1["id"])
    validate_success(api.record_payment(
        cr2["id"], {"amount_cents": 1000}, make_family_contact_headers(fam["id"])))
    validate_success(api.waive_contribution_request(cr2["id"], HM))
    assert_invariant(cr2["id"])
    set_clock("2026-09-04T00:00:00Z")
    validate_success(api.check_out_stay(stay["id"], HM))
    assert_invariant(cr1["id"])
    assert_invariant(cr2["id"])
