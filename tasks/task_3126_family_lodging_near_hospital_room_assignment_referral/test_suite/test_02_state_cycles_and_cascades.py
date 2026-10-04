"""Difficulty queue A — cyclic state machines and transitive cascades."""
import pytest

from test_helpers import (
    HM,
    create_family,
    create_referral,
    create_stay_request,
    get_house,
    get_referral,
    get_room,
    get_stay,
    get_stay_request,
    make_family_contact_headers,
    make_hospital_referrer_headers,
    offer_request,
    respond_request,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    setup_offered_request,
    setup_waitlisted_request,
    validate_success,
    verify_referral,
    check_in_request,
)


def test_offer_decline_rewaitlists_cycle(api):
    """PRD §3.4: "When decision is DECLINE, the request transitions from OFFERED
    back to WAITLISTED, its offered_room_id and offer_expires_at are cleared, its
    waitlisted_since is restamped, the room reservation is released without an
    immediate re-offer, and version increments by 1."

    Design: Difficulty/non_linear_state_machine/stay_request_offer_decline_rewaitlists_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_offered_request()
    sr = ctx["request"]
    room = ctx["room"]
    house = ctx["house"]

    set_clock("2026-09-01T12:00:00Z")
    after = respond_request(sr["id"], ctx["family"]["id"], "DECLINE")
    assert after["assignment_status"] == "WAITLISTED", "cycle: OFFERED -> WAITLISTED"
    assert after["offered_room_id"] is None
    assert after["offer_expires_at"] is None
    assert after["waitlisted_since"] == "2026-09-01T12:00:00.000Z", (
        "refreshed from the creation-time value 2026-09-01T00:00:00Z, proving the "
        "loop re-entered WAITLISTED"
    )
    room_after = get_room(room["id"])
    assert room_after["occupied"] is False
    house_after = get_house(house["id"])
    assert house_after["reserved_room_count"] == 0, "room reservable again"


def test_offer_decline_allows_second_offer_cycle(api):
    """PRD §3.4: "The request must currently be WAITLISTED (otherwise
    ERR_INVALID_STATE) and VERIFICATION_OK ... On success the request transitions
    from WAITLISTED to OFFERED."

    Design: Difficulty/non_linear_state_machine/stay_request_offer_decline_rewaitlists_cycle
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_offered_request()
    sr = ctx["request"]
    room = ctx["room"]
    respond_request(sr["id"], ctx["family"]["id"], "DECLINE")
    # Re-offered after the decline — the loop is live, not terminal.
    reoffered = offer_request(sr["id"], room["id"])
    assert reoffered["assignment_status"] == "OFFERED"
    assert reoffered["offered_room_id"] == room["id"]


def test_stay_extension_review_and_transition_plan_loop(api):
    """PRD §3.5: "When decision is PLAN_TRANSITION on an UNDER_REVIEW stay, the
    call must carry transition_plan_notes — otherwise ERR_INVALID_REQUEST — and
    on success the stay moves to TRANSITION_PLANNED with the notes recorded and
    pending_extension_nights cleared."
    PRD §3.5: "The same APPROVE_EXTENSION decision applied to a TRANSITION_PLANNED
    stay requires approved_extension_count to be strictly less than 2 ... on
    success, transition_plan_notes and review_reason are cleared and the stay
    returns to ACTIVE."

    Design: Difficulty/non_linear_state_machine/stay_extension_review_and_transition_plan_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_stay(check_in_clock="2026-09-02T00:00:00Z")
    stay = ctx["stay"]
    fam = ctx["family"]

    under_review = validate_success(
        api.request_extension(stay["id"], {"additional_nights": 7},
                              make_family_contact_headers(fam["id"]))
    )
    assert under_review["status"] == "UNDER_REVIEW"
    assert under_review["pending_extension_nights"] == 7
    assert under_review["review_reason"] == "EXTENSION_REQUEST"

    planned = validate_success(
        api.review_stay(stay["id"], {
            "decision": "PLAN_TRANSITION",
            "transition_plan_notes": "Move to outpatient housing near clinic by 2026-09-20.",
        }, HM)
    )
    assert planned["status"] == "TRANSITION_PLANNED"
    assert planned["transition_plan_notes"] == (
        "Move to outpatient housing near clinic by 2026-09-20."
    )

    resumed = validate_success(
        api.review_stay(stay["id"], {"decision": "APPROVE_EXTENSION"}, HM)
    )
    assert resumed["status"] == "ACTIVE", "loop TRANSITION_PLANNED -> ACTIVE"
    assert resumed["transition_plan_notes"] is None


def test_stay_under_review_approve_extension_returns_active(api):
    """PRD §3.5: "When decision is APPROVE_EXTENSION and the stay is UNDER_REVIEW,
    the stay's review_reason must be EXTENSION_REQUEST — otherwise
    ERR_INVALID_STATE — and on success expected_check_out_date is advanced by
    pending_extension_nights, approved_extension_count is incremented by 1,
    pending_extension_nights and review_reason are cleared, and the stay returns
    to ACTIVE."

    Design: Difficulty/non_linear_state_machine/stay_extension_review_and_transition_plan_loop
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_stay(check_in_clock="2026-09-02T00:00:00Z",
                            request_overrides={"expected_nights": 15})
    stay = ctx["stay"]
    fam = ctx["family"]
    assert stay["expected_check_out_date"] == "2026-09-17"

    validate_success(
        api.request_extension(stay["id"], {"additional_nights": 7},
                              make_family_contact_headers(fam["id"]))
    )
    resumed = validate_success(
        api.review_stay(stay["id"], {"decision": "APPROVE_EXTENSION"}, HM)
    )
    assert resumed["status"] == "ACTIVE"
    assert resumed["approved_extension_count"] == 1
    assert resumed["expected_check_out_date"] == "2026-09-24", "2026-09-17 + 7 nights"
    assert resumed["pending_extension_nights"] is None
    assert resumed["review_reason"] is None


def test_referral_revocation_cascades_offer_rescission_and_reoffer(api):
    """PRD §3.2: "Hop 1 flips every linked stay request whose verification_status
    is VERIFICATION_OK to VERIFICATION_FAILED. Hop 2 takes the subset of those
    requests whose assignment_status is OFFERED and rescinds the offer: each moves
    back to WAITLISTED, its offered_room_id is cleared, its offer_expires_at is
    cleared, its waitlisted_since is restamped to the current logical clock, and
    the room reservation is released. Hop 3 immediately re-offers each room freed
    by hop 2 to the highest-ranked eligible waitlisted request at that house,
    applying the ranking and room-selection rules of §2.9".

    Design: Difficulty/transitive_cascade/referral_revocation_cascades_offer_rescission_and_reoffer
    """
    set_clock("2026-09-01T00:00:00Z")
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
    sr_a = create_stay_request(fam_a, house["id"], ref_a["id"], expected_nights=15)
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"], expected_nights=10,
                               self_reported_acuity="HIGH")
    offer_request(sr_a["id"], room["id"])

    revoked = validate_success(
        api.revoke_referral(ref_a["id"], make_hospital_referrer_headers(hospital["id"]))
    )
    assert revoked["status"] == "REVOKED"

    after_a = get_stay_request(sr_a["id"])
    assert after_a["verification_status"] == "VERIFICATION_FAILED", "hop 1"
    assert after_a["assignment_status"] == "WAITLISTED", "hop 2: offer rescinded"
    assert after_a["offered_room_id"] is None

    after_b = get_stay_request(sr_b["id"])
    assert after_b["assignment_status"] == "OFFERED", "hop 3: freed room re-offered to B"
    assert after_b["offered_room_id"] == room["id"]
    assert after_b["verified_score"] == pytest.approx(96.67, abs=0.001), (
        "60 band * 1.5 HIGH + 20 * 10/30 = 96.666.. -> 96.67"
    )


def test_referral_revocation_flags_active_stay_under_review(api):
    """PRD §3.2: "Independently of the stay-request cascade, any Stay whose chain
    back to this referral is intact and whose status is exactly ACTIVE is moved to
    UNDER_REVIEW with review_reason set to REFERRAL_REVOKED; stays already in
    UNDER_REVIEW, TRANSITION_PLANNED, or RELOCATION_REQUIRED are left alone."

    Design: Difficulty/transitive_cascade/referral_revocation_cascades_offer_rescission_and_reoffer
    """
    set_clock("2026-09-01T00:00:00Z")
    ctx = setup_active_stay()
    revoked = validate_success(
        api.revoke_referral(ctx["referral"]["id"],
                            make_hospital_referrer_headers(ctx["hospital"]["id"]))
    )
    assert revoked["status"] == "REVOKED"
    stay = get_stay(ctx["stay"]["id"])
    assert stay["status"] == "UNDER_REVIEW"
    assert stay["review_reason"] == "REFERRAL_REVOKED"


def test_checkout_cascades_room_release_and_promotion(api):
    """PRD §3.6: "First, the stay's room has its occupied flag cleared ... Second,
    the freed room triggers an immediate promotion at the house: the
    highest-ranked eligible waitlisted request per §2.9 transitions from
    WAITLISTED to OFFERED, holding this room, with offered_room_id set and
    offer_expires_at restamped to the clock plus 48 hours; when no request is
    eligible the room simply becomes available."

    Design: Difficulty/transitive_cascade/checkout_cascades_room_release_and_promotion
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
    sr_b = create_stay_request(fam_b, house["id"], ref_b["id"], expected_nights=30,
                               self_reported_acuity="HIGH")
    offer_request(sr_a["id"], room["id"])
    respond_request(sr_a["id"], fam_a["id"], "ACCEPT")
    stay_a = check_in_request(sr_a["id"])

    set_clock("2026-09-05T00:00:00Z")
    out = validate_success(api.check_out_stay(stay_a["id"], HM))
    assert out["status"] == "CHECKED_OUT"
    assert out["actual_check_out_date"] == "2026-09-05"

    room_after = get_room(room["id"])
    assert room_after["occupied"] is False, "hop 1: room released"
    after_b = get_stay_request(sr_b["id"])
    assert after_b["assignment_status"] == "OFFERED", "hop 2: promotion"
    assert after_b["offered_room_id"] == room["id"]
    assert after_b["verified_score"] == pytest.approx(100.00, abs=0.001), (
        "60 * 1.5 + 20 * min(30,30)/30 = 110 capped to 100.00"
    )


def test_checkout_promotion_noop_when_no_eligible_request(api):
    """PRD §3.6: "when no request is eligible the room simply becomes available."
    PRD §2.9: "An empty candidate set is not an error — the promotion simply does
    nothing."

    Design: Difficulty/transitive_cascade/checkout_cascades_room_release_and_promotion
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    house = ctx["house"]
    room = ctx["room"]
    set_clock("2026-09-05T00:00:00Z")
    out = validate_success(api.check_out_stay(ctx["stay"]["id"], HM))
    assert out["status"] == "CHECKED_OUT"
    room_after = get_room(room["id"])
    assert room_after["occupied"] is False
    house_after = get_house(house["id"])
    assert house_after["available_room_count"] == 1
    assert house_after["reserved_room_count"] == 0
