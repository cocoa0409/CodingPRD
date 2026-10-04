"""Corner queue B — state machine lifecycle claims."""
from test_helpers import (
    HM,
    VC,
    ApiErrorId,
    create_certified_group,
    create_family,
    create_meal_shift,
    create_referral,
    get_house,
    get_referral,
    get_room,
    get_stay,
    get_stay_request,
    make_hospital_referrer_headers,
    offer_request,
    record_pass_screening,
    register_guest,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    setup_offered_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_referral,
    check_in_request,
)


def test_referral_initial_state_pending(api):
    """PRD §3.1: "The new referral lands in PENDING status, and the server records
    the caller's X-User-ID on created_by_user_id."
    PRD §3.1: "on success the referral transitions to VERIFIED, the server stamps
    verified_by_user_id with the verifier's identity, sets verified_at to the
    current logical clock, and computes valid_until as verified_at plus 30 days" —
    so before verification those fields are null.

    Design: Corner/state_machines/referral_initial_state_pending
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    assert referral["status"] == "PENDING"
    assert referral["verified_at"] is None
    assert referral["valid_until"] is None
    assert referral["created_by_user_id"] == hospital["id"]


def test_verify_revoked_referral_rejected(api):
    """PRD §3.1: "When decision is APPROVE, the referral must currently be
    PENDING — otherwise ERR_INVALID_STATE".
    PRD §3.2: "The referral itself lands in REVOKED."

    Design: Corner/state_machines/verify_revoked_referral_rejected
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    validate_success(
        api.revoke_referral(referral["id"], make_hospital_referrer_headers(hospital["id"]))
    )
    resp = api.verify_referral(referral["id"], {"decision": "APPROVE"}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    after = get_referral(referral["id"])
    assert after["status"] == "REVOKED"


def test_cancel_fulfilled_request_rejected(api):
    """PRD §3.4: "Cancellation of a stay request is permitted while the request is
    WAITLISTED or OFFERED and moves it to CANCELLED." A FULFILLED request is
    outside the permitted from-states, so §2.5's state gate applies: "Fifth,
    state-machine eligibility: the target resource must be in a from-state that
    permits the requested transition, with ERR_INVALID_STATE (HTTP 409)".

    Design: Corner/state_machines/cancel_fulfilled_request_rejected
    """
    ctx = setup_active_stay()
    sr = ctx["request"]
    stay = ctx["stay"]
    assert sr["assignment_status"] == "FULFILLED"

    resp = api.cancel_stay_request(sr["id"], HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after_sr = get_stay_request(sr["id"])
    assert after_sr["assignment_status"] == "FULFILLED"
    after_stay = get_stay(stay["id"])
    assert after_stay["status"] == "ACTIVE"


def test_room_maintenance_cycle_roundtrip(api):
    """PRD §2.7: "When the denominator is zero, the posture is FULL." and
    "available_room_count is the number of rooms whose status is AVAILABLE, whose
    occupied flag is false, and which are not currently reserved by any OFFERED
    request" — a MAINTENANCE room is no longer AVAILABLE so the count falls and
    recovers as the room cycles back.

    Design: Corner/state_machines/room_maintenance_cycle_roundtrip
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    room = rooms[0]

    maintained = validate_success(
        api.set_room_status(room["id"], {"target_status": "MAINTENANCE"}, HM)
    )
    assert maintained["status"] == "MAINTENANCE"
    house_mid = get_house(house["id"])
    assert house_mid["available_room_count"] == 0
    assert house_mid["posture"] == "FULL", "no AVAILABLE rooms"

    restored = validate_success(
        api.set_room_status(room["id"], {"target_status": "AVAILABLE"}, HM)
    )
    assert restored["status"] == "AVAILABLE"
    house_after = get_house(house["id"])
    assert house_after["available_room_count"] == 1
    assert house_after["posture"] == "OPEN"


def test_meal_shift_claimed_to_open_cycle(api):
    """PRD §3.9: "Cancelling a CLAIMED shift moves it back to OPEN and clears
    claimed_by_group_id, releasing the group."

    Design: Corner/state_machines/meal_shift_claimed_to_open_cycle
    """
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    shift = create_meal_shift(house["id"], shift_date="2026-09-08", meal_type="LUNCH")
    g1 = create_certified_group(certified_until="2026-09-10")
    g2 = create_certified_group(certified_until="2026-09-10",
                                group_name="Lions Cooks", contact_email="cooks@lions.org")
    validate_success(api.claim_meal_shift(shift["id"], {"volunteer_group_id": g1["id"]}, VC))

    released = validate_success(api.cancel_meal_shift(shift["id"], VC))
    assert released["status"] == "OPEN"
    assert released["claimed_by_group_id"] is None

    reclaimed = validate_success(api.claim_meal_shift(shift["id"], {"volunteer_group_id": g2["id"]}, VC))
    assert reclaimed["status"] == "CLAIMED"
    assert reclaimed["claimed_by_group_id"] == g2["id"]


def test_checkout_departs_registered_guests(api):
    """PRD §3.6: "Third, every GuestRegistration on the stay whose status is
    REGISTERED flips to DEPARTED."

    Design: Corner/state_machines/checkout_departs_registered_guests
    """
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]
    record_pass_screening(stay["id"])
    guest = register_guest(stay["id"], family_id=fam["id"], guest_name="Aunt May",
                           relationship="aunt", is_overnight=True)
    assert guest["status"] == "REGISTERED"

    out = validate_success(api.check_out_stay(stay["id"], HM))
    assert out["status"] == "CHECKED_OUT"

    guests, _ = validate_paginated(api.list_guests(stay["id"], HM))
    by_id = {g["id"]: g for g in guests}
    assert by_id[guest["id"]]["status"] == "DEPARTED", "cascade down"
    registered, _ = validate_paginated(
        api.list_guests(stay["id"], HM, params={"status": "REGISTERED"})
    )
    assert registered == []


def test_second_offer_same_room_rejected(api):
    """PRD §3.4: "The room itself must have status equal to AVAILABLE, occupied
    equal to false, and must not be reserved by any other OFFERED request — any of
    these failures surfaces as ERR_ROOM_NOT_AVAILABLE (HTTP 409)."
    PRD §2.7: "reserved_room_count is the number of rooms held by an OFFERED stay
    request".

    Design: Corner/state_machines/second_offer_same_room_rejected
    """
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
    from test_helpers import create_stay_request
    sr_a = create_stay_request(fam_a, house["id"], ref_a["id"], expected_nights=3)
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"], expected_nights=5,
                               self_reported_acuity="HIGH")
    offer_request(sr_a["id"], room["id"])

    resp = api.offer_stay_request(sr_b["id"], {"room_id": room["id"]}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_ROOM_NOT_AVAILABLE)

    after_b = get_stay_request(sr_b["id"])
    assert after_b["assignment_status"] == "WAITLISTED"
    assert after_b["offered_room_id"] is None
    house_after = get_house(house["id"])
    assert house_after["reserved_room_count"] == 1
