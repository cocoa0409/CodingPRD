"""Corner queue B — validation violations and their exact error ids."""
import pytest

from test_helpers import (
    HM,
    ApiErrorId,
    create_care_space,
    create_donation,
    create_family,
    create_house,
    create_meal_shift,
    create_referral,
    create_stay_request,
    get_contribution,
    get_stay,
    get_stay_request,
    make_family_contact_headers,
    record_pass_screening,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    setup_offered_request,
    setup_waitlisted_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_referral,
    create_hospital,
    create_contribution,
)


def test_overpayment_rejected(api):
    """PRD §3.8: "The amount_cents may not exceed the request's outstanding_cents
    — otherwise ERR_OVERPAYMENT (HTTP 422)."

    Design: Corner/validations/overpayment_rejected
    """
    ctx = setup_active_stay(request_overrides={"expected_nights": 4})
    cr = create_contribution(ctx["stay"]["id"], nightly_rate_cents=2500,
                             planned_nights=4, hardship_tier="NONE")
    assert cr["requested_amount_cents"] == 10000

    resp = api.record_payment(
        cr["id"], {"amount_cents": 10001}, make_family_contact_headers(ctx["family"]["id"])
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_OVERPAYMENT)

    after = get_contribution(cr["id"])
    assert after["paid_cents"] == 0
    assert after["outstanding_cents"] == 10000, "no partial application"


def test_booking_invalid_date_range_rejected(api):
    """PRD §3.10: "end_at must be strictly after start_at — otherwise
    ERR_INVALID_DATE_RANGE."

    Design: Corner/validations/booking_invalid_date_range_rejected
    """
    hospital = create_hospital()
    cs = create_care_space(hospital["id"])
    fam = create_family()
    ref = create_referral(fam["id"], hospital["id"])
    verify_referral(ref["id"])

    resp = api.create_care_space_booking(
        cs["id"],
        {"family_id": fam["id"], "start_at": "2026-09-03T10:00:00Z",
         "end_at": "2026-09-03T10:00:00Z", "party_size": 2},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE)


def test_duplicate_meal_shift_rejected(api):
    """PRD §3.9: "At most one meal shift may exist per (house, shift_date,
    meal_type) triple; a second scheduling against the same triple is rejected
    with ERR_DUPLICATE_MEAL_SHIFT (HTTP 409)."

    Design: Corner/validations/duplicate_meal_shift_rejected
    """
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    create_meal_shift(house["id"], shift_date="2026-09-08", meal_type="LUNCH",
                      servings_planned=20)

    resp = api.create_meal_shift(
        house["id"], {"shift_date": "2026-09-08", "meal_type": "LUNCH",
                      "servings_planned": 15}, HM
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MEAL_SHIFT)

    ok = validate_success(
        api.create_meal_shift(
            house["id"], {"shift_date": "2026-09-08", "meal_type": "DINNER",
                          "servings_planned": 15}, HM
        ),
        expected_status=201,
    )
    assert ok["meal_type"] == "DINNER"


def test_offer_unverified_request_rejected(api):
    """PRD §3.4: "The request must currently be WAITLISTED (otherwise
    ERR_INVALID_STATE) and VERIFICATION_OK (otherwise ERR_REFERRAL_NOT_VERIFIED,
    HTTP 409)."

    Design: Corner/validations/offer_unverified_request_rejected
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"])  # left PENDING
    sr = create_stay_request(family, house["id"], referral["id"])
    assert sr["verification_status"] == "UNVERIFIED"

    resp = api.offer_stay_request(sr["id"], {"room_id": rooms[0]["id"]}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_REFERRAL_NOT_VERIFIED)

    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "WAITLISTED"
    assert after["offered_room_id"] is None


def test_distribute_from_depleted_donation_rejected(api):
    """PRD §3.11: "The donation must currently be RECEIVED or
    PARTIALLY_DISTRIBUTED — a distribution against a DEPLETED donation is rejected
    with ERR_DONATION_DEPLETED (HTTP 409)."

    Design: Corner/validations/distribute_from_depleted_donation_rejected
    """
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    don = create_donation(house["id"], supply_category="PANTRY_STAPLE", quantity_received=4)
    depleted = validate_success(
        api.distribute_in_kind_donation(don["id"], {"quantity": 4}, HM)
    )
    assert depleted["status"] == "DEPLETED"

    resp = api.distribute_in_kind_donation(don["id"], {"quantity": 1}, HM)
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_DONATION_DEPLETED)

    donations, _ = validate_paginated(api.list_in_kind_donations(house["id"], HM))
    target = [d for d in donations if d["id"] == don["id"]][0]
    assert target["quantity_distributed"] == 4


def test_distribute_more_than_remaining_rejected(api):
    """PRD §3.11: "The requested quantity may not exceed the donation's remaining
    units, computed as quantity_received minus quantity_distributed — otherwise
    ERR_INSUFFICIENT_SUPPLY (HTTP 422)." and "when it consumes exactly the
    remaining units, quantity_distributed becomes equal to quantity_received and
    the donation moves to DEPLETED."

    Design: Corner/validations/distribute_more_than_remaining_rejected
    """
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    don = create_donation(house["id"], donor_name="Lions Club",
                          supply_category="BABY_SUPPLY", quantity_received=5)

    resp = api.distribute_in_kind_donation(don["id"], {"quantity": 6}, HM)
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_SUPPLY)

    ok = validate_success(api.distribute_in_kind_donation(don["id"], {"quantity": 5}, HM))
    assert ok["status"] == "DEPLETED"
    assert ok["quantity_distributed"] == 5


def test_duplicate_active_referral_rejected(api):
    """PRD §3.1: "At any time, at most one non-terminal referral — that is, one in
    PENDING or VERIFIED status — may exist for a given (family, hospital) pair; a
    second issuance against the same pair is rejected with
    ERR_DUPLICATE_ACTIVE_REFERRAL (HTTP 409)."

    Design: Corner/validations/duplicate_active_referral_rejected
    """
    from test_helpers import make_hospital_referrer_headers
    hospital = create_hospital()
    family = create_family()
    referrer = make_hospital_referrer_headers(hospital["id"])
    ref1 = create_referral(family["id"], hospital["id"])
    assert ref1["status"] == "PENDING"

    resp = api.create_referral(
        {"family_id": family["id"], "hospital_id": hospital["id"],
         "treating_unit": "Oncology", "care_type": "INPATIENT",
         "acuity_level": "HIGH", "attending_clinician": "Dr. Lee"},
        referrer,
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_REFERRAL)

    # After the first is DECLINED (terminal), a fresh referral for the pair succeeds.
    validate_success(api.verify_referral(
        ref1["id"], {"decision": "DECLINE", "notes": "Insufficient treatment detail."}, HM
    ))
    ref2 = validate_success(
        api.create_referral(
            {"family_id": family["id"], "hospital_id": hospital["id"],
             "treating_unit": "Oncology", "care_type": "INPATIENT",
             "acuity_level": "HIGH", "attending_clinician": "Dr. Lee"},
            referrer,
        ),
        expected_status=201,
    )
    assert ref2["status"] == "PENDING"


def test_referral_family_mismatch_rejected(api):
    """PRD §3.3: "The named referral must belong to the same family — otherwise
    ERR_REFERRAL_FAMILY_MISMATCH (HTTP 422)."

    Design: Corner/validations/referral_family_mismatch_rejected
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    fam_a = create_family(family_name="Alvarez", distance_miles=120)
    fam_b = create_family(family_name="Baker", distance_miles=150, home_city="Hilltown",
                          primary_contact_name="Bob Baker", child_patient_name="Kate Baker")
    ref = create_referral(fam_a["id"], hospital["id"])
    verify_referral(ref["id"])

    resp = api.create_stay_request(
        {"family_id": fam_b["id"], "house_id": house["id"], "referral_id": ref["id"],
         "expected_nights": 5, "self_reported_acuity": "HIGH",
         "expected_family_version": fam_b["version"]},
        make_family_contact_headers(fam_b["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_REFERRAL_FAMILY_MISMATCH)

    requests, _ = validate_paginated(
        api.list_family_stay_requests(fam_b["id"], make_family_contact_headers(fam_b["id"]))
    )
    assert requests == []


def test_extension_limit_requires_transition_plan(api):
    """PRD §3.5: "The stay's approved_extension_count must be strictly less than 2
    — otherwise ERR_TRANSITION_PLAN_REQUIRED (HTTP 409), signalling that the
    family has exhausted routine extensions and a transition plan must be put in
    place first."

    Design: Corner/validations/extension_limit_requires_transition_plan
    """
    # Default clock 2026-09-01; expected 10 nights -> checkout 2026-09-11,
    # then +3 +3 -> 2026-09-17.
    ctx = setup_active_stay(request_overrides={"expected_nights": 10})
    stay = ctx["stay"]
    fam = ctx["family"]

    for _ in range(2):
        validate_success(api.request_extension(
            stay["id"], {"additional_nights": 3}, make_family_contact_headers(fam["id"])))
        validate_success(api.review_stay(stay["id"], {"decision": "APPROVE_EXTENSION"}, HM))

    resp = api.request_extension(
        stay["id"], {"additional_nights": 2}, make_family_contact_headers(fam["id"]))
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_TRANSITION_PLAN_REQUIRED)

    after = get_stay(stay["id"])
    assert after["approved_extension_count"] == 2
    assert after["expected_check_out_date"] == "2026-09-17", "2026-09-01 + 10 + 3 + 3"
    assert after["status"] == "ACTIVE"


def test_screening_not_cleared_blocks_guest(api):
    """PRD §3.7: "The registration is also gated on same-day illness screening
    clearance: a screening must exist for the stay whose screened_at calendar date
    equals the current logical date and whose result is PASS; otherwise the
    registration is rejected with ERR_SCREENING_NOT_CLEARED (HTTP 422)."

    Design: Corner/validations/screening_not_cleared_blocks_guest
    """
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]

    resp = api.register_guest(
        stay["id"],
        {"guest_name": "Aunt May", "relationship": "aunt", "is_overnight": True},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)

    guests, _ = validate_paginated(api.list_guests(stay["id"], HM))
    assert guests == []


def test_yesterday_screening_does_not_clear_today(api):
    """PRD §3.7: "a screening must exist for the stay whose screened_at calendar
    date equals the current logical date and whose result is PASS; otherwise the
    registration is rejected with ERR_SCREENING_NOT_CLEARED (HTTP 422)."

    Design: Corner/validations/yesterday_screening_does_not_clear_today
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay(request_overrides={"expected_nights": 5})
    stay = ctx["stay"]
    fam = ctx["family"]
    record_pass_screening(stay["id"])  # PASS on 2026-09-02

    set_clock("2026-09-03T00:00:00Z")
    resp = api.register_guest(
        stay["id"],
        {"guest_name": "Aunt May", "relationship": "aunt", "is_overnight": True},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_SCREENING_NOT_CLEARED)


def test_offer_expired_cannot_be_accepted(api):
    """PRD §3.4: "The request must currently be OFFERED — otherwise
    ERR_INVALID_STATE — and its offer_expires_at must be at or after the current
    logical clock, otherwise the response is rejected with ERR_OFFER_EXPIRED (HTTP
    409)."

    Design: Corner/validations/offer_expired_cannot_be_accepted
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_offered_request()
    sr = ctx["request"]
    fam = ctx["family"]

    set_clock("2026-09-04T00:00:00Z")  # past the 48h offer TTL
    resp = api.respond_stay_request(
        sr["id"],
        {"decision": "ACCEPT", "expected_stay_request_version": sr["version"]},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_OFFER_EXPIRED)

    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "OFFERED", (
        "expiry is lazy; no sweep has run in this test"
    )


def test_complete_shift_without_attestation_rejected(api):
    """PRD §3.9: "food_safety_attested must be exactly true — otherwise
    ERR_FOOD_SAFETY_ATTESTATION_REQUIRED (HTTP 422)."

    Design: Corner/validations/complete_shift_without_attestation_rejected
    """
    from test_helpers import VC, create_certified_group
    hospital, house, _ = setup_hospital_house(num_rooms=0)
    shift = create_meal_shift(house["id"], shift_date="2026-09-08", meal_type="LUNCH")
    group = create_certified_group(certified_until="2026-09-10")
    validate_success(api.claim_meal_shift(shift["id"], {"volunteer_group_id": group["id"]}, VC))

    resp = api.complete_meal_shift(
        shift["id"], {"servings_served": 18, "food_safety_attested": False}, VC
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_FOOD_SAFETY_ATTESTATION_REQUIRED)

    shifts, _ = validate_paginated(api.list_meal_shifts(house["id"], HM))
    assert shifts[0]["status"] == "CLAIMED"


def test_care_space_capacity_exceeded_rejected(api):
    """PRD §3.10: "party_size may not exceed the space's capacity — otherwise
    ERR_CAPACITY_EXCEEDED (HTTP 422)."

    Design: Corner/validations/care_space_capacity_exceeded_rejected
    """
    hospital = create_hospital()
    cs = create_care_space(hospital["id"], space_name="Mobile Unit 1",
                           space_type="MOBILE_CARE_UNIT", capacity=2)
    fam = create_family()
    ref = create_referral(fam["id"], hospital["id"])
    verify_referral(ref["id"])

    resp = api.create_care_space_booking(
        cs["id"],
        {"family_id": fam["id"], "start_at": "2026-09-03T09:00:00Z",
         "end_at": "2026-09-03T10:00:00Z", "party_size": 3},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    ok = validate_success(
        api.create_care_space_booking(
            cs["id"],
            {"family_id": fam["id"], "start_at": "2026-09-03T09:00:00Z",
             "end_at": "2026-09-03T10:00:00Z", "party_size": 2},
            make_family_contact_headers(fam["id"]),
        ),
        expected_status=201,
    )
    assert ok["status"] == "CONFIRMED", "party_size == capacity succeeds"


def test_room_house_mismatch_rejected(api):
    """PRD §3.4: "The target room_id must belong to the same house as the
    request's house_id — otherwise ERR_ROOM_HOUSE_MISMATCH (HTTP 422)."

    Design: Corner/validations/room_house_mismatch_rejected
    """
    from test_helpers import create_room
    hospital = create_hospital()
    house_a = create_house(hospital["id"], name="Oak House")
    house_b = create_house(hospital["id"], name="Maple House")
    room_b = create_room(house_b["id"], room_number="201")

    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house_a["id"], referral["id"])

    resp = api.offer_stay_request(sr["id"], {"room_id": room_b["id"]}, HM)
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_ROOM_HOUSE_MISMATCH)

    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "WAITLISTED"
