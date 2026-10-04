"""Corner queue B — entity creation, retrieval, listing, envelope claims."""
import pytest

from test_helpers import (
    ADMIN,
    HM,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_family,
    assert_illness_screening,
    assert_room,
    create_family,
    create_referral,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_hospital_referrer_headers,
    record_pass_screening,
    set_clock,
    setup_active_stay,
    setup_hospital_house,
    validate_error,
    validate_paginated,
    validate_success,
    create_hospital,
)


def test_family_create_returns_defaults_and_system_fields(api):
    """PRD §2.4: "id is a server-minted UUID with no type prefix. created_at is an
    ISO 8601 UTC timestamp with three fractional digits marking when the resource
    was created. updated_at is an ISO 8601 UTC timestamp with three fractional
    digits marking the most recent modification. version is an integer that starts
    at 1 and increments by one on every mutation."
    PRD §2.2: "The api_request_id is a server-generated unique identifier for the
    request that starts with req_."

    Design: Corner/entities/family_create_returns_defaults_and_system_fields
    """
    resp = api.create_family(
        {"family_name": "Alvarez", "primary_contact_name": "Maria Alvarez",
         "home_city": "Riverton", "distance_miles": 120,
         "child_patient_name": "Nico Alvarez"},
        ADMIN,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert isinstance(body["meta"]["api_request_timestamp"], str)
    data = body["data"]
    assert_family(data)
    assert data["version"] == 1
    assert data["distance_miles"] == 120


def test_room_get_retrieval_round_trips_configuration(api):
    """PRD §2.2: "Unless otherwise noted, operations that create or modify a
    resource will return the created or updated resource object in the data
    field." PRD §3.4 (room state): a freshly added room has "status AVAILABLE" and
    occupied false per §2.7's derived counts.

    Design: Corner/entities/room_get_retrieval_round_trips_configuration
    """
    hospital, house, rooms = setup_hospital_house(num_rooms=1)
    room = rooms[0]
    got = validate_success(api.get_room(room["id"], HM))
    assert_room(got)
    assert got["room_number"] == "101"
    assert got["bed_count"] == 2
    assert got["occupancy_limit"] == 2
    assert got["status"] == "AVAILABLE"
    assert got["occupied"] is False
    assert got["house_id"] == house["id"]


def test_hospital_referrals_list_paginates_with_total_count(api):
    """PRD §2.3: "limit controls the maximum number of items returned and defaults
    to 10, with a minimum of 1 and a maximum of 100. offset controls the number of
    items skipped and defaults to 0. ... Paginated list responses carry limit,
    offset, total_count, and has_more in the meta object of the envelope."

    Design: Corner/entities/hospital_referrals_list_paginates_with_total_count
    """
    hospital = create_hospital()
    referrer = make_hospital_referrer_headers(hospital["id"])
    for name, dist, unit, care, acuity in (
        ("Aaa", 60, "Ward A", "INPATIENT", "LOW"),
        ("Bbb", 70, "Ward B", "OUTPATIENT", "LOW"),
        ("Ccc", 80, "Ward C", "INPATIENT", "HIGH"),
    ):
        fam = create_family(family_name=name, distance_miles=dist,
                            primary_contact_name=f"{name[0]} {name}",
                            child_patient_name=f"Kid {name}")
        create_referral(fam["id"], hospital["id"], treating_unit=unit,
                        care_type=care, acuity_level=acuity,
                        attending_clinician="Dr. Rao")

    page1, meta1 = validate_paginated(
        api.list_hospital_referrals(hospital["id"], referrer, params={"limit": 2, "offset": 0})
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_hospital_referrals(hospital["id"], referrer, params={"limit": 2, "offset": 2})
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    page_default, meta_default = validate_paginated(
        api.list_hospital_referrals(hospital["id"], referrer)
    )
    assert len(page_default) == 3
    assert meta_default["limit"] == 10
    assert meta_default["offset"] == 0


def test_referral_get_unknown_id_returns_not_found(api):
    """PRD §2.11: "For any endpoint whose path contains multiple resource
    identifiers, the server validates identifiers from left to right. The first
    identifier that does not resolve to an existing resource yields ERR_NOT_FOUND
    for that resource type."
    PRD §2.2 (error envelope): "The meta object for error responses contains only
    api_request_id and api_request_timestamp."

    Design: Corner/entities/referral_get_unknown_id_returns_not_found
    """
    resp = api.get_referral(NON_EXISTENT_UUID, HM)
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
    body = resp.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"]["api_request_id"], str)


def test_house_create_missing_name_rejected(api):
    """PRD §2.5: "First, request well-formedness: the body must contain all
    required fields, no unknown fields, and every field's type and enum value must
    be valid, otherwise the request is rejected with ERR_INVALID_REQUEST (HTTP
    400)."

    Design: Corner/entities/house_create_missing_name_rejected
    """
    hospital = create_hospital()
    resp = api.create_house(
        {"city": "Springfield", "associated_hospital_id": hospital["id"]}, ADMIN
    )
    assert resp.status_code == 400
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_stay_request_extra_field_rejected(api):
    """PRD §2.5: "First, request well-formedness: the body must contain all
    required fields, no unknown fields, and every field's type and enum value must
    be valid, otherwise the request is rejected with ERR_INVALID_REQUEST (HTTP
    400)." provisional_score is system-computed per §2.8 ("the result is stored on
    provisional_score"), not a client input.

    Design: Corner/entities/stay_request_extra_field_rejected
    """
    from test_helpers import create_stay_request, make_family_contact_headers
    hospital, house, _ = setup_hospital_house(num_rooms=1)
    family = create_family()
    referral = create_referral(family["id"], hospital["id"], acuity_level="LOW",
                               treating_unit="Ward A", attending_clinician="Dr. Rao")
    resp = api.create_stay_request(
        {
            "family_id": family["id"], "house_id": house["id"],
            "referral_id": referral["id"], "expected_nights": 5,
            "self_reported_acuity": "LOW",
            "expected_family_version": family["version"],
            "provisional_score": 99.99,
        },
        make_family_contact_headers(family["id"]),
    )
    assert resp.status_code == 400
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_illness_screening_immutable_event_without_version(api):
    """PRD §2.4: "The single exception is IllnessScreening, which is immutable
    after recording and therefore carries only id and created_at; both updated_at
    and version are absent from screening payloads."
    PRD §3.7: "The body carries temperature_tenths_c ... and an optional notes
    field defaulting to the empty string."

    Design: Corner/entities/illness_screening_immutable_event_without_version
    """
    ctx = setup_active_stay()
    stay = ctx["stay"]
    sc = validate_success(
        api.record_screening(stay["id"], {"temperature_tenths_c": 370, "symptom_count": 0}, HM),
        expected_status=201,
    )
    assert_illness_screening(sc)
    assert sc["notes"] == "", "default applied when omitted"
    assert sc["result"] == "PASS"
    assert is_iso8601_timestamp(sc["screened_at"])


def test_guest_on_unknown_stay_not_found(api):
    """PRD §2.11: "the server validates identifiers from left to right. The first
    identifier that does not resolve to an existing resource yields ERR_NOT_FOUND
    for that resource type, and no further path segments are validated."

    Design: Corner/entities/guest_on_unknown_stay_not_found
    """
    resp = api.register_guest(
        NON_EXISTENT_UUID,
        {"guest_name": "Uncle Ray", "relationship": "uncle", "is_overnight": True},
        HM,
    )
    assert resp.status_code == 404
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
