"""Corner coverage: participant registration defaults, listing, computed prescription flags,
and the read paths that expose a prescription's children.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    set_clock,
    register_participant,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
)

OPERATOR = TEST_USERS["network_operator_headers"]


def test_participant_creation_applies_every_declared_default(api):
    """PRD §3.1: "A newly registered participant starts at `UNCERTIFIED` with an empty
    `certification_tests_passed` list, reads `directory_listed` as false, reports an
    `open_route_attempt_count` of zero, and begins with `plan_deductible_met_cents` at zero."

    Design: Corner/entities/participant_create_applies_every_declared_default_and_starts_uncertified
    """
    set_clock()
    created = validate_success(
        api_client.create_participant(
            {"name": "Lakeshore Infusion Center", "participant_type": "PRESCRIBER_CLINIC",
             "npi": "4444444444"},
            OPERATOR,
        ),
        201,
    )

    assert created["certification_status"] == "UNCERTIFIED"
    assert created["certification_tests_passed"] == []
    assert created["directory_listed"] is False
    assert created["open_route_attempt_count"] == 0
    assert created["volume_billing_mode"] == "MONTHLY"
    assert created["fallback_channel"] == "FAX"
    assert created["fax_number"] is None
    assert created["plan_deductible_met_cents"] == 0
    assert created["plan_copay_cents"] == 1500
    assert created["version"] == 1
    assert created["id"] and created["created_at"] and created["updated_at"]


def test_reading_an_unregistered_participant_reports_the_not_found_error(api):
    """PRD §2.5: "Each path segment's identifier is resolved before the next is examined, and
    the first identifier that fails to resolve ends the request with the corresponding
    not-found error: `ERR_PARTICIPANT_NOT_FOUND` for a participant"

    Design: Corner/entities/participant_get_with_an_unknown_id_returns_participant_not_found
    """
    set_clock()
    response = api_client.get_participant(NON_EXISTENT_UUID, OPERATOR)
    validate_error(response, "ERR_PARTICIPANT_NOT_FOUND", expected_status=404)

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["data"]["message"], str) and body["data"]["message"].strip()


def test_participant_list_paginates_and_counts_the_whole_filtered_set(api):
    """PRD §2.3: "`total_count` reflects the size of the full filtered result set, not the
    size of the returned page."
    PRD §2.3: "The `limit` parameter caps how many items a page returns; it defaults to 10,
    must be at least 1, and must not exceed 100."

    Design: Corner/entities/participants_list_paginates_and_counts_the_whole_filtered_set
    """
    set_clock()
    register_participant("Riverbend Pharmacy", "PHARMACY", "2222222222")
    register_participant("Harborside Pharmacy", "PHARMACY", "5555555555")
    register_participant("Lakeside Pharmacy", "PHARMACY", "7777777777")
    register_participant("Northside Family Clinic", "PRESCRIBER_CLINIC", "1111111111")

    data, meta = validate_paginated(
        api_client.list_participants(OPERATOR, {"participant_type": "PHARMACY",
                                               "limit": 2, "offset": 0})
    )
    assert len(data) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    data, meta = validate_paginated(
        api_client.list_participants(OPERATOR, {"participant_type": "PHARMACY",
                                               "limit": 2, "offset": 2})
    )
    assert len(data) == 1
    assert meta["total_count"] == 3
    assert meta["has_more"] is False

    clinics, meta = validate_paginated(
        api_client.list_participants(OPERATOR, {"participant_type": "PRESCRIBER_CLINIC"})
    )
    assert len(clinics) == 1
    assert meta["total_count"] == 1

    everything, meta = validate_paginated(api_client.list_participants(OPERATOR))
    assert len(everything) == 4
    assert meta["limit"] == 10
    assert meta["offset"] == 0


def test_participant_registration_without_an_npi_is_a_bad_request(api):
    """PRD §2.9: "A malformed body, a missing required field, an unknown enum member, or a
    declared input that is not a recognized field of the request is refused with
    `ERR_INVALID_REQUEST` at HTTP 400."

    Design: Corner/entities/participant_create_missing_npi_returns_invalid_request
    """
    set_clock()
    response = api_client.create_participant(
        {"name": "Incomplete Clinic", "participant_type": "PRESCRIBER_CLINIC"}, OPERATOR
    )
    validate_error(response, "ERR_INVALID_REQUEST", expected_status=400)

    data, meta = validate_paginated(api_client.list_participants(OPERATOR))
    assert meta["total_count"] == 0
    assert data == []


def test_reusing_an_npi_for_the_same_type_is_refused_but_allowed_across_types(api):
    """PRD §2.5: "The pair of `participant_type` and `npi` is unique across the network, so
    registering a participant whose pair already exists is refused with
    `ERR_DUPLICATE_PARTICIPANT_NPI` at HTTP 409."

    Design: Corner/entities/participant_create_reusing_an_npi_for_the_same_type_returns_duplicate_npi
    """
    set_clock()
    register_participant("Riverbend Pharmacy", "PHARMACY", "2222222222")

    duplicate = api_client.create_participant(
        {"name": "Riverbend Pharmacy North", "participant_type": "PHARMACY",
         "npi": "2222222222"},
        OPERATOR,
    )
    validate_error(duplicate, "ERR_DUPLICATE_PARTICIPANT_NPI", expected_status=409)

    accepted = api_client.create_participant(
        {"name": "Riverbend Prescribers", "participant_type": "PRESCRIBER_CLINIC",
         "npi": "2222222222"},
        OPERATOR,
    )
    validate_success(accepted, 201)