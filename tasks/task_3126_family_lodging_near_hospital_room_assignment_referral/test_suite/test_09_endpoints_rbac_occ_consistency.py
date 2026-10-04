"""Corner queue B — endpoint behaviors, error envelope, authn, RBAC, OCC, consistency."""
import pytest

from test_helpers import (
    ADMIN,
    HM,
    VC,
    ApiErrorId,
    build_user_headers,
    create_contribution,
    create_family,
    create_hospital,
    create_referral,
    create_stay_request,
    get_family,
    get_stay_request,
    make_family_contact_headers,
    make_hospital_referrer_headers,
    offer_request,
    respond_request,
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


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def test_clock_defaults_to_2026_09_01_and_sets(api):
    """PRD §2.4: "All date and datetime reasoning in the system runs against a
    logical clock, not the host's wall clock. Before any client call adjusts it,
    the logical clock reads exactly 2026-09-01T00:00:00Z. A ProgramAdmin-only
    test-driving capability advances the logical clock to a supplied to_iso8601
    instant and echoes the resulting current_utc value; once advanced, the clock
    never falls back to wall-clock time".

    Design: Corner/endpoints/clock_defaults_to_2026_09_01_and_sets
    """
    hospital = create_hospital()
    h1 = validate_success(
        api.create_house({"name": "Oak House", "city": "Springfield",
                          "associated_hospital_id": hospital["id"]}, ADMIN),
        expected_status=201,
    )
    assert h1["created_at"] == "2026-09-01T00:00:00.000Z", (
        "default logical clock, not wall-clock"
    )

    set_clock("2026-09-10T12:00:00Z")
    h2 = validate_success(
        api.create_house({"name": "Maple House", "city": "Springfield",
                          "associated_hospital_id": hospital["id"]}, ADMIN),
        expected_status=201,
    )
    assert h2["created_at"] == "2026-09-10T12:00:00.000Z", "set clock honored"


def test_sweep_with_empty_waitlist_is_noop(api):
    """PRD §2.9: "An empty candidate set is not an error — the promotion simply
    does nothing." PRD §3.12: "The response reports expired_offer_ids,
    expired_referral_ids, and promoted_request_ids — each a list of resource id
    strings."

    Design: Corner/endpoints/sweep_with_empty_waitlist_is_noop
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    result = validate_success(api.run_assignment_sweep(house["id"], HM))
    assert result["promoted_request_ids"] == []
    assert result["expired_offer_ids"] == []
    assert result["expired_referral_ids"] == []
    house_after = validate_success(api.get_house(house["id"], HM))
    assert house_after["available_room_count"] == 1, "unchanged"


def test_checkin_response_carries_stay_computed_dates(api):
    """PRD §3.4: "On success a new Stay is created in ACTIVE status:
    stay_request_id points back to the originating request, family_id is copied
    from the request, room_id is the offered room, check_in_date is the current
    logical calendar date in YYYY-MM-DD form, and expected_check_out_date is
    check_in_date plus the request's expected_nights. The request itself
    transitions from ACCEPTED to FULFILLED ... The new stay is returned with HTTP
    201."

    Design: Corner/endpoints/checkin_response_carries_stay_computed_dates
    """
    set_clock("2026-09-02T00:00:00Z")
    ctx = setup_offered_request(request_overrides={"expected_nights": 4})
    respond_request(ctx["request"]["id"], ctx["family"]["id"], "ACCEPT")

    resp = api.check_in_stay_request(ctx["request"]["id"], HM)
    stay = validate_success(resp, expected_status=201)
    assert stay["check_in_date"] == "2026-09-02"
    assert stay["expected_check_out_date"] == "2026-09-06"
    assert stay["room_id"] == ctx["room"]["id"]
    assert stay["status"] == "ACTIVE"
    assert stay["approved_extension_count"] == 0

    after = get_stay_request(ctx["request"]["id"])
    assert after["assignment_status"] == "FULFILLED"


def test_fk_reverse_reachability_subresources(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §2.3: "Endpoints that return lists of resources are paginated" —
    each parent-scoped list returns exactly the children carrying that parent's
    foreign key.

    Design: Corner/endpoints/fk_reverse_reachability_subresources
    """
    ctx = setup_active_stay()
    cr = create_contribution(ctx["stay"]["id"], nightly_rate_cents=2500,
                             planned_nights=3, hardship_tier="NONE")

    rooms, _ = validate_paginated(api.list_rooms(ctx["house"]["id"], HM))
    assert [r["id"] for r in rooms] == [ctx["room"]["id"]]

    requests, _ = validate_paginated(
        api.list_family_stay_requests(
            ctx["family"]["id"], make_family_contact_headers(ctx["family"]["id"]))
    )
    assert [r["id"] for r in requests] == [ctx["request"]["id"]]

    crs, _ = validate_paginated(
        api.list_contribution_requests(
            ctx["stay"]["id"], make_family_contact_headers(ctx["family"]["id"]))
    )
    assert [c["id"] for c in crs] == [cr["id"]]
    assert crs[0]["requested_amount_cents"] == 7500


# ---------------------------------------------------------------------------
# errors (auth envelope)
# ---------------------------------------------------------------------------

def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role value, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_unauthenticated
    """
    hospital = create_hospital()
    resp = api.get_hospital(hospital["id"], headers={})
    assert resp.status_code == 401
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_unknown_role_unauthenticated(api):
    """PRD §2.1: "A request missing either header, or carrying an unrecognized
    role value, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

    Design: Corner/errors/unknown_role_unauthenticated
    """
    hospital = create_hospital()
    resp = api.get_hospital(
        hospital["id"], headers=build_user_headers("someone", "SuperUser")
    )
    assert resp.status_code == 401
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ---------------------------------------------------------------------------
# rbac
# ---------------------------------------------------------------------------

def test_referral_creator_cannot_verify_own_referral(api):
    """PRD §2.1: "Segregation of duties is enforced on referral verification: the
    X-User-ID verifying a referral must differ from the referral's recorded
    created_by_user_id. A verifier who created the referral is rejected with
    ERR_SEGREGATION_OF_DUTIES (HTTP 403)."
    PRD §3.1: "the server stamps verified_by_user_id with the verifier's identity,
    sets verified_at to the current logical clock, and computes valid_until as
    verified_at plus 30 days."

    Design: Corner/rbac/referral_creator_cannot_verify_own_referral
    """
    hospital = create_hospital()
    family = create_family()
    ref = create_referral(family["id"], hospital["id"],
                          creator_headers=build_user_headers("pa-1", "ProgramAdmin"))

    resp = api.verify_referral(ref["id"], {"decision": "APPROVE"},
                               build_user_headers("pa-1", "ProgramAdmin"))
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    verified = validate_success(api.verify_referral(
        ref["id"], {"decision": "APPROVE"}, build_user_headers("pa-2", "ProgramAdmin")))
    assert verified["status"] == "VERIFIED"
    assert verified["verified_by_user_id"] == "pa-2"
    assert verified["valid_until"] == "2026-10-01T00:00:00.000Z", (
        "verified_at + 30 days at the default clock"
    )


def test_family_contact_cannot_act_on_other_family(api):
    """PRD §3.3: "The creating caller — a FamilyContact acting for their own
    family (so family_id must equal X-User-ID, otherwise ERR_FORBIDDEN), a
    HouseManager, or a ProgramAdmin".

    Design: Corner/rbac/family_contact_cannot_act_on_other_family
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    fam_a = create_family(family_name="Alvarez", distance_miles=120)
    fam_b = create_family(family_name="Baker", distance_miles=150, home_city="Hilltown",
                          primary_contact_name="Bob Baker", child_patient_name="Kate Baker")
    ref = create_referral(fam_a["id"], hospital["id"])
    verify_referral(ref["id"])

    resp = api.create_stay_request(
        {"family_id": fam_a["id"], "house_id": house["id"], "referral_id": ref["id"],
         "expected_nights": 3, "self_reported_acuity": "MODERATE",
         "expected_family_version": fam_b["version"]},
        make_family_contact_headers(fam_b["id"]),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_hospital_referrer_cannot_create_for_other_hospital(api):
    """PRD §2.1: "When X-User-Role is HospitalReferrer, X-User-ID is the id of the
    acting Hospital; a HospitalReferrer issuing a Referral must pass a
    hospital_id equal to their own X-User-ID".
    PRD §2.1: "A request whose role is recognized but is not permitted for the
    target endpoint, or whose entity-backed ownership check fails, is rejected
    with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/hospital_referrer_cannot_create_for_other_hospital
    """
    hosp1 = create_hospital()
    hosp2 = create_hospital(name="St. Mary's")
    fam = create_family()
    resp = api.create_referral(
        {"family_id": fam["id"], "hospital_id": hosp2["id"],
         "treating_unit": "Oncology", "care_type": "INPATIENT",
         "acuity_level": "MODERATE", "attending_clinician": "Dr. Patel"},
        make_hospital_referrer_headers(hosp1["id"]),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_volunteer_coordinator_cannot_verify_referral(api):
    """PRD §4: "POST /api/referrals/{id}/verify | House-side verification decision
    (APPROVE or DECLINE) | HouseManager, ProgramAdmin". PRD §2.1: "A request whose
    role is recognized but is not permitted for the target endpoint ... is
    rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/volunteer_coordinator_cannot_verify_referral
    """
    hospital = create_hospital()
    family = create_family()
    ref = create_referral(family["id"], hospital["id"])
    resp = api.verify_referral(ref["id"], {"decision": "APPROVE"}, VC)
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    after = validate_success(api.get_referral(ref["id"], HM))
    assert after["status"] == "PENDING"


def test_family_contact_cannot_create_house(api):
    """PRD §4: "POST /api/houses | Create a lodging house | ProgramAdmin". PRD
    §2.1: "A request whose role is recognized but is not permitted for the target
    endpoint ... is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/rbac/family_contact_cannot_create_house
    """
    hospital = create_hospital()
    resp = api.create_house(
        {"name": "Rogue House", "city": "Springfield",
         "associated_hospital_id": hospital["id"]},
        build_user_headers("some-family-id", "FamilyContact"),
    )
    assert resp.status_code == 403
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


# ---------------------------------------------------------------------------
# cross_cutting_complexity_layers
# ---------------------------------------------------------------------------

def test_stay_request_create_stale_family_version_rejected(api):
    """PRD §2.6: "Creating a stay request requires the body to include
    expected_family_version matching the target Family's current version. Creating
    a stay request legitimately supersedes the family's prior WAITLISTED or
    OFFERED requests and increments Family.version, so a writer holding a stale
    family view must be rejected with ERR_STALE_VERSION (HTTP 412) rather than
    silently superseding state it never observed."

    Design: Corner/cross_cutting_complexity_layers/stay_request_create_stale_family_version_rejected
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    family = create_family()
    fam_v1 = family["version"]
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr1 = create_stay_request(family, house["id"], referral["id"], expected_nights=3)

    fam_v2 = get_family(family["id"])["version"]

    stale = api.create_stay_request(
        {"family_id": family["id"], "house_id": house["id"], "referral_id": referral["id"],
         "expected_nights": 5, "self_reported_acuity": "HIGH",
         "expected_family_version": fam_v1},
        make_family_contact_headers(family["id"]),
    )
    assert stale.status_code == 412
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = validate_success(
        api.create_stay_request(
            {"family_id": family["id"], "house_id": house["id"], "referral_id": referral["id"],
             "expected_nights": 5, "self_reported_acuity": "HIGH",
             "expected_family_version": fam_v2},
            make_family_contact_headers(family["id"]),
        ),
        expected_status=201,
    )
    assert fresh["assignment_status"] == "WAITLISTED"
    assert fresh["expected_nights"] == 5

    sr1_after = get_stay_request(sr1["id"])
    assert sr1_after["assignment_status"] == "CANCELLED"
    assert sr1_after["superseded_by_request_id"] == fresh["id"]
    assert get_family(family["id"])["version"] == 3, "two successful creates"


def test_offer_respond_stale_version_rejected(api):
    """PRD §2.6: "Responding to an offer requires the body to include
    expected_stay_request_version matching the StayRequest's current version.
    Offering, score recomputation, or a prior response each advance
    StayRequest.version, so a stale response is refused with ERR_STALE_VERSION
    (HTTP 412) before any state evaluation runs."

    Design: Corner/cross_cutting_complexity_layers/offer_respond_stale_version_rejected
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr = create_stay_request(family, house["id"], referral["id"], expected_nights=3)
    sr_v_pre = sr["version"]
    offered = offer_request(sr["id"], rooms[0]["id"])
    sr_v_post = offered["version"]
    assert sr_v_post == sr_v_pre + 1

    stale = api.respond_stay_request(
        sr["id"], {"decision": "ACCEPT", "expected_stay_request_version": sr_v_pre},
        make_family_contact_headers(family["id"]),
    )
    assert stale.status_code == 412
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

    fresh = validate_success(
        api.respond_stay_request(
            sr["id"], {"decision": "ACCEPT", "expected_stay_request_version": sr_v_post},
            make_family_contact_headers(family["id"]),
        )
    )
    assert fresh["assignment_status"] == "ACCEPTED"
    assert fresh["version"] == sr_v_post + 1


def test_version_increments_on_every_mutation(api):
    """PRD §2.4: "version is an integer that starts at 1 and increments by one on
    every mutation."
    PRD §3.3: "The family's version is incremented by 1 to reflect the
    supersession".

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_every_mutation
    """
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    family = create_family()
    assert family["version"] == 1
    referral = create_referral(family["id"], hospital["id"])
    verify_referral(referral["id"])
    sr1 = create_stay_request(family, house["id"], referral["id"], expected_nights=3)
    assert get_family(family["id"])["version"] == 2, "after the first create"

    sr2 = create_stay_request(family, house["id"], referral["id"], expected_nights=4,
                              self_reported_acuity="LOW")
    assert get_family(family["id"])["version"] == 3, "after the second create"
    assert get_stay_request(sr1["id"])["assignment_status"] == "CANCELLED"


# ---------------------------------------------------------------------------
# consistency_model
# ---------------------------------------------------------------------------

def test_mutations_visible_immediately_in_same_response(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." — the respond response body itself shows the post-mutation state.

    Design: Corner/consistency_model/mutations_visible_immediately_in_same_response
    """
    ctx = setup_offered_request()
    sr = ctx["request"]
    fam = ctx["family"]

    resp = api.respond_stay_request(
        sr["id"], {"decision": "ACCEPT", "expected_stay_request_version": sr["version"]},
        make_family_contact_headers(fam["id"]),
    )
    data = validate_success(resp)
    assert data["assignment_status"] == "ACCEPTED", (
        "the respond response body already shows ACCEPTED"
    )

    after = get_stay_request(sr["id"])
    assert after["assignment_status"] == "ACCEPTED"
    assert after["offered_room_id"] == ctx["room"]["id"]
