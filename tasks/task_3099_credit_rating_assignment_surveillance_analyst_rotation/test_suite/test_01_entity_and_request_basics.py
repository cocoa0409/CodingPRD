"""Entity creation, retrieval, listing and request-intake basics."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_rated_entity,
    assert_engagement_letter,
    assert_rating_request,
    assert_same_instant,
    methodology_payload,
    rated_entity_payload,
    engagement_letter_payload,
    rating_request_payload,
    TEST_USERS,
    fixtures,
)

EM = TEST_USERS["engagement_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]


def test_registered_issuer_returns_every_declared_field_and_starts_normal(api):
    """PRD §2.5: "A `RatedEntity` is registered once and its `current_grade` stays
    null until its first `PUBLISHED` decision records a grade, at which point
    `first_rated_at` is stamped."
    PRD §2.5: "its `solicitation_status` defaults to `SOLICITED` while
    `surveillance_posture` defaults to `NORMAL`."

    Design: Corner/entities/rated_entity_create_returns_every_declared_field_and_starts_normal
    """
    methodology = get_success_data(api_client.create_methodology(methodology_payload(), CO))
    get_success_data(api_client.publish_methodology(methodology["id"], CO))

    response = api_client.create_rated_entity(
        rated_entity_payload(methodology["id"], legal_name="Romeo Logistics SpA", domicile_country="IT"),
        EM,
    )
    entity = validate_success(response, 201)
    assert_rated_entity(entity)
    assert entity["legal_name"] == "Romeo Logistics SpA"
    # PRD §3.7 declares revenue_band's three values (LARGE/MID/SMALL) but never
    # names a server-side default for an omitted one, so the test cannot pin a
    # concrete value here — only that the server returns a declared member.
    assert entity["revenue_band"] in ("LARGE", "MID", "SMALL")
    assert entity["solicitation_status"] == "SOLICITED"
    assert entity["surveillance_posture"] == "NORMAL"
    assert entity["current_grade"] is None
    assert entity["first_rated_at"] is None
    assert entity["version"] == 1


def test_engagement_letter_get_roundtrips_its_fee_configuration(api):
    """PRD §3.1: "the letter is created in `DRAFT`."
    PRD §3.1: "It also carries `cooling_off_end_at`, `fee_credited_cents` and
    `fee_reversed_cents`; the credited and reversed totals begin at zero and
    move only as requests against the engagement are opened, returned, or
    terminated."

    Design: Corner/entities/engagement_letter_get_roundtrips_immutable_fee_fields
    """
    methodology = get_success_data(api_client.create_methodology(methodology_payload(), CO))
    get_success_data(api_client.publish_methodology(methodology["id"], CO))
    entity = get_success_data(api_client.create_rated_entity(
        rated_entity_payload(methodology["id"], legal_name="Sierra Pharma Inc", revenue_band="LARGE"), EM))
    letter = get_success_data(api_client.create_engagement_letter(
        engagement_letter_payload(entity["id"], fee_amount_cents=7500000,
                                  fee_structure="MILESTONE", fee_payer_is_issuer=False), EM))

    response = api_client.get_engagement_letter(letter["id"], EM)
    fetched = validate_success(response, 200)
    assert_engagement_letter(fetched)
    assert fetched["fee_amount_cents"] == 7500000
    assert fetched["fee_structure"] == "MILESTONE"
    assert fetched["fee_payer_is_issuer"] is False
    assert fetched["fee_credited_cents"] == 0
    assert fetched["fee_reversed_cents"] == 0
    assert fetched["cooling_off_end_at"] is None
    assert fetched["status"] == "DRAFT"


def test_request_list_reports_total_count_across_pages(api):
    """PRD §2.3: "`limit` caps the number of records returned and defaults to
    10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "The `meta` block of a list response carries `limit`, `offset`,
    `total_count` and `has_more`."

    Design: Corner/entities/rating_requests_list_paginates_and_reports_total_count
    """
    entity, engagement, requests = fixtures.setup_engagement_with_requests(
        ["SENIOR_UNSECURED", "SUBORDINATED", "REVOLVER"]
    )
    assert len(requests) == 3

    page_one = api_client.list_rating_requests(
        EM, {"engagement_letter_id": engagement["id"], "limit": 2, "offset": 0}
    )
    rows, meta = validate_paginated(page_one)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["has_more"] is True

    page_two = api_client.list_rating_requests(
        EM, {"engagement_letter_id": engagement["id"], "limit": 2, "offset": 2}
    )
    rows_two, meta_two = validate_paginated(page_two)
    assert len(rows_two) == 1
    assert meta_two["has_more"] is False

    unpaged = api_client.list_rating_requests(EM, {"engagement_letter_id": engagement["id"]})
    rows_all, meta_all = validate_paginated(unpaged)
    assert len(rows_all) == 3
    assert meta_all["limit"] == 10


def test_unknown_rated_entity_id_returns_resource_not_found(api):
    """PRD §2.4: "If any identifier in the path fails to resolve to a row, the
    request is rejected with `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/rated_entity_get_with_unknown_id_returns_resource_not_found
    """
    response = api_client.get_rated_entity(NON_EXISTENT_UUID, EM)
    validate_error(response, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)


def test_request_intake_without_engagement_letter_id_is_rejected(api):
    """PRD §3.2: "A rating request is submitted under an engagement by supplying
    the `engagement_letter_id`, the `rated_entity_id`, the `instrument_type`,
    the `instrument_notional_cents`, and the `requested_rating_scale`."
    PRD §2.1: "when either header is missing or malformed the request is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/entities/rating_request_missing_engagement_letter_id_is_rejected
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    payload = rating_request_payload(engagement["id"], entity["id"])
    del payload["engagement_letter_id"]

    response = api_client.create_rating_request(payload, EM)
    assert response.status_code == 400, (
        f"a malformed intake must be rejected before persistence, got {response.status_code}"
    )
    body = response.json()
    assert body.get("response_type") == "error"
    assert body["data"]["error_id"] == ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER

    listing = api_client.list_rating_requests(EM, {"rated_entity_id": entity["id"]})
    rows, meta = validate_paginated(listing)
    assert meta["total_count"] == 0, "no orphan request may be created"


def test_request_allocation_and_received_at_are_server_assigned(api):
    """PRD §3.2: "The `received_at` timestamp is stamped by the server, and the
    request starts in `SUBMITTED`."
    PRD §3.2: "The allocation is also capped: it may never push the engagement's
    `fee_credited_cents` above its `fee_amount_cents`."

    Design: Corner/entities/rating_request_allocated_fee_id_and_created_at_are_system_sourced
    """
    entity, engagement, methodology = fixtures.setup_rated_entity_with_active_engagement()
    request = fixtures.create_request(engagement["id"], entity["id"])
    assert_rating_request(request)
    assert request["allocated_fee_cents"] == 0, "allocation is written only by the screening computation"
    assert request["request_status"] == "SUBMITTED"
    assert_same_instant(request["received_at"], "2026-12-15T00:00:00Z", "received_at")