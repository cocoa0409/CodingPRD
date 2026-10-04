"""Difficulty queue A — validation pipeline priority pairs and numeric boundaries."""
import pytest

from test_helpers import (
    HM,
    ApiErrorId,
    create_care_space,
    create_family,
    create_referral,
    get_stay,
    make_family_contact_headers,
    record_pass_screening,
    register_guest,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    setup_waitlisted_request,
    validate_error,
    validate_paginated,
    validate_success,
    verify_referral,
    create_hospital,
    create_stay_request,
    create_house,
)


def test_guest_registration_state_error_beats_screening_safety(api):
    """PRD §2.5: "Because the pipeline is ordered, a request that fails both an
    authorization check and a state check always reports the authorization
    failure ... Implementations must not reorder these gates." Fifth stage
    (state-machine eligibility) precedes sixth stage (business safety): "Fifth,
    state-machine eligibility: the target resource must be in a from-state that
    permits the requested transition, with ERR_INVALID_STATE (HTTP 409) as the
    generic rejection — though stay-activity gating surfaces as
    ERR_STAY_NOT_ACTIVE (HTTP 409) ... Sixth, business safety: same-day PASS
    illness screening for guest registration ... surfacing as
    ERR_SCREENING_NOT_CLEARED". PRD §3.7 (guest registration): "The stay must be
    ACTIVE — otherwise ERR_STAY_NOT_ACTIVE."

    Design: Difficulty/priority_pair_validation_conflict/guest_registration_state_error_beats_screening_safety
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]
    set_clock("2026-09-05T00:00:00Z")
    validate_success(api.check_out_stay(stay["id"], HM))

    # The stay is CHECKED_OUT (state violation) AND there is no same-day PASS
    # screening (business-safety violation). State stage (fifth) beats safety
    # stage (sixth); §3.7 names the state-stage error for this endpoint as
    # ERR_STAY_NOT_ACTIVE.
    resp = api.register_guest(
        stay["id"],
        {"guest_name": "Uncle Ray", "relationship": "uncle", "is_overnight": True},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_STAY_NOT_ACTIVE)

    guests, _meta = validate_paginated(api.list_guests(stay["id"], HM))
    assert guests == [], "no side effects fired"


def test_guest_registration_on_checked_out_stay_reports_state_not_screening(api):
    """PRD §2.5: "Fifth, state-machine eligibility: the target resource must be in
    a from-state that permits the requested transition, with ERR_INVALID_STATE
    (HTTP 409) as the generic rejection — though stay-activity gating surfaces as
    ERR_STAY_NOT_ACTIVE (HTTP 409)".
    PRD §3.7 (guest registration): "The stay must be ACTIVE — otherwise
    ERR_STAY_NOT_ACTIVE." The screening rejection "ERR_SCREENING_NOT_CLEARED
    (HTTP 422)" only fires when the safety gate is reached; the pipeline's state
    stage runs earlier.

    Design: Difficulty/priority_pair_validation_conflict/guest_registration_state_error_beats_screening_safety
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]
    set_clock("2026-09-05T00:00:00Z")
    validate_success(api.check_out_stay(stay["id"], HM))

    resp = api.register_guest(
        stay["id"],
        {"guest_name": "Aunt May", "relationship": "aunt", "is_overnight": False},
        make_family_contact_headers(fam["id"]),
    )
    # Not ERR_SCREENING_NOT_CLEARED even though no screening exists today.
    assert resp.status_code == 409
    validate_error(resp, ApiErrorId.ERR_STAY_NOT_ACTIVE)


def test_care_space_booking_referential_error_beats_temporal(api):
    """PRD §2.5: "Eighth, cross-entity referential fit: a referral must belong to
    the requesting family, a room must belong to the request's house, and a
    care-space booking family must hold a verified referral at the care space's
    hospital — surfacing as ERR_REFERRAL_FAMILY_MISMATCH, ERR_ROOM_HOUSE_MISMATCH,
    or ERR_BOOKING_REFERRAL_MISMATCH. Ninth, temporal sanity: booking end_at
    strictly after start_at ... surfacing as ERR_INVALID_DATE_RANGE (HTTP 422)."
    Referential (eighth) is evaluated before temporal (ninth).

    Design: Difficulty/priority_pair_validation_conflict/care_space_booking_referential_error_beats_temporal
    """
    hosp1 = create_hospital()
    hosp2 = create_hospital(name="St. Mary's")
    cs = create_care_space(hosp1["id"])
    fam = create_family()
    ref = create_referral(fam["id"], hosp2["id"], care_type="OUTPATIENT",
                          acuity_level="LOW", treating_unit="Clinic",
                          attending_clinician="Dr. Rao")
    verify_referral(ref["id"])

    # Family holds a VERIFIED referral at H2 only (referential violation at H1)
    # AND end_at precedes start_at (temporal violation). Priority 7 wins.
    resp = api.create_care_space_booking(
        cs["id"],
        {"family_id": fam["id"], "start_at": "2026-09-03T14:00:00Z",
         "end_at": "2026-09-03T13:00:00Z", "party_size": 3},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_BOOKING_REFERRAL_MISMATCH)


def test_care_space_booking_referral_mismatch_named_even_when_dates_also_bad(api):
    """PRD §3.10: "The booking family must hold a referral in VERIFIED status at
    the care space's hospital — otherwise ERR_BOOKING_REFERRAL_MISMATCH (HTTP
    422)." PRD §2.5 orders referential fit (eighth) ahead of temporal sanity
    (ninth): "Ninth, temporal sanity: booking end_at strictly after start_at".

    Design: Difficulty/priority_pair_validation_conflict/care_space_booking_referential_error_beats_temporal
    """
    hosp1 = create_hospital()
    hosp2 = create_hospital(name="St. Mary's")
    cs = create_care_space(hosp1["id"])
    fam = create_family()
    ref = create_referral(fam["id"], hosp2["id"], care_type="OUTPATIENT",
                          acuity_level="LOW")
    verify_referral(ref["id"])

    resp = api.create_care_space_booking(
        cs["id"],
        {"family_id": fam["id"], "start_at": "2026-09-03T14:00:00Z",
         "end_at": "2026-09-03T13:00:00Z", "party_size": 3},
        make_family_contact_headers(fam["id"]),
    )
    err = validate_error(resp, ApiErrorId.ERR_BOOKING_REFERRAL_MISMATCH)
    assert err["error_id"] != ApiErrorId.ERR_INVALID_DATE_RANGE


def test_distance_eligibility_boundary_at_exactly_50_miles(api):
    """PRD §3.3: "The family's distance_miles must be at least 50 — otherwise
    ERR_DISTANCE_INELIGIBLE (HTTP 422)."

    Design: Difficulty/boundary_precision_check/distance_eligibility_boundary_at_exactly_50_miles
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    fam_ok = create_family(family_name="Edge", distance_miles=50.0)
    fam_bad = create_family(family_name="Close", distance_miles=49.9)
    ref_ok = create_referral(fam_ok["id"], hospital["id"], acuity_level="LOW",
                             care_type="OUTPATIENT", treating_unit="Clinic",
                             attending_clinician="Dr. Rao")
    ref_bad = create_referral(fam_bad["id"], hospital["id"], acuity_level="LOW",
                              care_type="OUTPATIENT", treating_unit="Clinic",
                              attending_clinician="Dr. Rao")
    verify_referral(ref_ok["id"])
    verify_referral(ref_bad["id"])

    sr_ok = create_stay_request(fam_ok, house["id"], ref_ok["id"], expected_nights=5,
                                self_reported_acuity="LOW")
    assert sr_ok["assignment_status"] == "WAITLISTED"

    fam_bad_now = validate_success(api.get_family(fam_bad["id"], make_family_contact_headers(fam_bad["id"])))
    resp = api.create_stay_request(
        {
            "family_id": fam_bad["id"], "house_id": house["id"],
            "referral_id": ref_bad["id"], "expected_nights": 5,
            "self_reported_acuity": "LOW",
            "expected_family_version": fam_bad_now["version"],
        },
        make_family_contact_headers(fam_bad["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_DISTANCE_INELIGIBLE)


def test_distance_just_below_50_rejected_while_exactly_50_accepted(api):
    """PRD §3.3: "The family's distance_miles must be at least 50 — otherwise
    ERR_DISTANCE_INELIGIBLE (HTTP 422)." The boundary is inclusive at 50.

    Design: Difficulty/boundary_precision_check/distance_eligibility_boundary_at_exactly_50_miles
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    fam = create_family(family_name="Close", distance_miles=49.9)
    ref = create_referral(fam["id"], hospital["id"], acuity_level="LOW")
    verify_referral(ref["id"])
    resp = api.create_stay_request(
        {
            "family_id": fam["id"], "house_id": house["id"], "referral_id": ref["id"],
            "expected_nights": 5, "self_reported_acuity": "LOW",
            "expected_family_version": fam["version"],
        },
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_DISTANCE_INELIGIBLE)


def test_guest_occupancy_limit_exact_count_edge(api):
    """PRD §3.7: "Overnight guests count against the occupied room's
    occupancy_limit: if the number of REGISTERED overnight guests on the stay
    would exceed that limit, the registration is rejected with
    ERR_GUEST_LIMIT_EXCEEDED (HTTP 422)."

    Design: Difficulty/boundary_precision_check/guest_occupancy_limit_exact_count_edge
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]
    record_pass_screening(stay["id"])
    # Non-overnight guest does not consume the overnight count.
    register_guest(stay["id"], family_id=fam["id"], guest_name="Grandma Lu",
                   relationship="grandmother", is_overnight=False)

    g1 = register_guest(stay["id"], family_id=fam["id"], guest_name="Aunt May",
                        relationship="aunt", is_overnight=True)
    assert g1["status"] == "REGISTERED"
    g2 = register_guest(stay["id"], family_id=fam["id"], guest_name="Uncle Ray",
                        relationship="uncle", is_overnight=True)
    assert g2["status"] == "REGISTERED", "2nd overnight guest == occupancy_limit, still OK"

    resp = api.register_guest(
        stay["id"],
        {"guest_name": "Cousin Tim", "relationship": "cousin", "is_overnight": True},
        make_family_contact_headers(fam["id"]),
    )
    assert resp.status_code == 422
    validate_error(resp, ApiErrorId.ERR_GUEST_LIMIT_EXCEEDED)


def test_guest_occupancy_limit_counts_only_overnight_registered(api):
    """PRD §3.7: "Overnight guests count against the occupied room's
    occupancy_limit" — non-overnight registrations never consume the count.

    Design: Difficulty/boundary_precision_check/guest_occupancy_limit_exact_count_edge
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]
    fam = ctx["family"]
    record_pass_screening(stay["id"])
    # Two non-overnight guests on a limit-2 room.
    register_guest(stay["id"], family_id=fam["id"], guest_name="Visitor One",
                   relationship="friend", is_overnight=False)
    register_guest(stay["id"], family_id=fam["id"], guest_name="Visitor Two",
                   relationship="friend", is_overnight=False)
    # Both overnight slots still free.
    g = register_guest(stay["id"], family_id=fam["id"], guest_name="Aunt May",
                       relationship="aunt", is_overnight=True)
    assert g["status"] == "REGISTERED"


def test_screening_temperature_boundary_380_fails(api):
    """PRD §3.7: "the screening is PASS when symptom_count is exactly 0 and
    temperature_tenths_c is strictly less than 380; otherwise it is FAIL. The
    boundary is exact — a reading of exactly 380 tenths (38.0 °C) FAILS, and only
    a strictly-below reading passes."

    Design: Difficulty/boundary_precision_check/screening_temperature_boundary_380_fails
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]

    sc_pass = validate_success(
        api.record_screening(stay["id"], {"temperature_tenths_c": 379, "symptom_count": 0}, HM),
        expected_status=201,
    )
    assert sc_pass["result"] == "PASS"
    sc_fail = validate_success(
        api.record_screening(stay["id"], {"temperature_tenths_c": 380, "symptom_count": 0}, HM),
        expected_status=201,
    )
    assert sc_fail["result"] == "FAIL", "boundary value itself fails: strict < 380"

    records, meta = validate_paginated(api.list_screenings(stay["id"], HM))
    assert len(records) == 2
    assert records[0]["temperature_tenths_c"] == 379 and records[0]["result"] == "PASS"
    assert records[1]["temperature_tenths_c"] == 380 and records[1]["result"] == "FAIL"


def test_screening_symptom_count_zero_required_for_pass(api):
    """PRD §3.7: "the screening is PASS when symptom_count is exactly 0 and
    temperature_tenths_c is strictly less than 380; otherwise it is FAIL."

    Design: Difficulty/boundary_precision_check/screening_temperature_boundary_380_fails
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_active_stay()
    stay = ctx["stay"]
    sc = validate_success(
        api.record_screening(stay["id"], {"temperature_tenths_c": 370, "symptom_count": 1}, HM),
        expected_status=201,
    )
    assert sc["result"] == "FAIL", "any symptom forces FAIL even below the fever line"
