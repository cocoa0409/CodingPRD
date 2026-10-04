"""Participant registration, participant state lockdown, pagination, and the
authentication gate — PRD §2.1, §2.2, §2.3, §2.4, §2.10, §3.1.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_bookkeeping_timestamp,
    assert_envelope_api_request_timestamp,
    assert_participant,
    create_participant,
    create_participant_payload,
    set_clock,
    transition_participant,
    validate_create_success,
    validate_error,
    validate_paginated,
)


def test_participant_create_returns_defaults(api, admin_headers):
    """PRD §3.1: "A new participant begins life in `ONBOARDING` status and is
    not yet operational."
    PRD §3.1: "Until the participant's first settlement accrual,
    `current_period` is null; the monthly reset behavior is defined with the
    settlement run in §3.6."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §4: "Operations that create a new resource return `201 Created`"

    Design: Corner/entities/participant_create_returns_defaults
    """
    set_clock("2026-09-01T09:00:00Z")
    resp = api.create_participant(
        create_participant_payload(
            legal_name="First Originating Bank",
            participant_type="ODFI",
            routing_number="111000025",
        ),
        admin_headers,
    )
    participant = validate_create_success(resp)
    body = resp.json()
    assert body["response_type"] == "object"
    assert isinstance(body["meta"]["api_request_id"], str)
    assert body["meta"]["api_request_id"].startswith("req_")
    assert_envelope_api_request_timestamp(resp)

    assert_participant(participant)
    assert participant["status"] == "ONBOARDING"
    assert participant["version"] == 1
    assert participant["current_period"] is None
    assert participant["current_period_fees_cents"] == 0
    assert participant["id"]
    assert_bookkeeping_timestamp(participant["created_at"], "created_at")
    assert_bookkeeping_timestamp(participant["updated_at"], "updated_at")


def test_participant_get_not_found(api, admin_headers):
    """PRD §2.10: "the server validates the existence of each identifier in
    strict left-to-right order and rejects the request immediately with
    `ERR_NOT_FOUND` (HTTP 404) at the first identifier that does not resolve to
    an existing resource."

    Design: Corner/entities/participant_get_not_found
    """
    resp = api.get_participant(NON_EXISTENT_UUID, admin_headers)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


def test_participants_list_pagination_total_count(api, auditor_headers):
    """PRD §2.3: "Paginated list responses carry the fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the response
    envelope."

    Design: Corner/entities/participants_list_pagination_total_count
    """
    create_participant(legal_name="Bank One", participant_type="ODFI", routing_number="111000025")
    create_participant(legal_name="Bank Two", participant_type="RDFI", routing_number="222000039")
    create_participant(legal_name="Bank Three", participant_type="BOTH", routing_number="333000041")

    resp1 = api.list_participants(auditor_headers, params={"limit": 2, "offset": 0})
    page1, meta1 = validate_paginated(resp1)
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    resp2 = api.list_participants(auditor_headers, params={"limit": 2, "offset": 2})
    page2, meta2 = validate_paginated(resp2)
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False


def test_participant_create_missing_routing_number_rejected(api, admin_headers):
    """PRD §2.8: "Request shape: required fields present, enum values in range,
    and field-level constraints such as a positive `amount_cents`, parseable
    dates, an `effective_date` strictly after the creation date, an
    `effective_until` that is null or strictly after `effective_from`, an
    `end_date` no earlier than `start_date`, and a positive
    `exposure_limit_cents` (`ERR_INVALID_REQUEST`)."
    PRD §2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`."

    Design: Corner/entities/participant_create_missing_routing_number_rejected
    """
    resp = api.create_participant(
        {"legal_name": "No Routing Bank", "participant_type": "ODFI"},
        admin_headers,
    )
    error = validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
    assert isinstance(error["message"], str) and error["message"].strip()
    body = resp.json()
    assert body["response_type"] == "error"
    assert body["meta"]["api_request_id"]


def test_participant_create_invalid_enum_rejected(api, admin_headers):
    """PRD §3.1: "its `participant_type` — one of `ODFI` for an originating-side
    institution, `RDFI` for a receiving-side institution, or `BOTH` for an
    institution operating on both sides"
    PRD §2.8: "Request shape: required fields present, enum values in range,
    and field-level constraints such as a positive `amount_cents`, parseable
    dates, an `effective_date` strictly after the creation date, an
    `effective_until` that is null or strictly after `effective_from`, an
    `end_date` no earlier than `start_date`, and a positive
    `exposure_limit_cents` (`ERR_INVALID_REQUEST`)."

    Design: Corner/entities/participant_create_invalid_enum_rejected
    """
    resp = api.create_participant(
        {
            "legal_name": "Bad Enum Bank",
            "participant_type": "BANK",
            "routing_number": "444000017",
        },
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_participant_create_duplicate_routing_number_rejected(api, admin_headers):
    """PRD §3.1: "Registering a participant with a routing number already in use
    is rejected with `ERR_DUPLICATE_RESOURCE`."

    Design: Corner/entities/participant_create_duplicate_routing_number_rejected
    """
    create_participant(legal_name="Bank One", participant_type="ODFI", routing_number="111000025")
    resp = api.create_participant(
        create_participant_payload(
            legal_name="Bank Two", participant_type="RDFI", routing_number="111000025"
        ),
        admin_headers,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE)


def test_participant_terminated_rejects_further_transition(api, admin_headers):
    """PRD §3.1: "Termination is reachable from either `ACTIVE` or `SUSPENDED`
    and is permanent — `TERMINATED` is a terminal state — and it cascades to
    the participant's originators as described in §3.2."
    PRD §2.8: "State-machine legality of the requested transition — the target
    entity must be in a state that permits it (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/participant_terminated_rejects_further_transition
    """
    participant = create_participant(
        legal_name="Bank One", participant_type="ODFI", routing_number="111000025"
    )
    transition_participant(participant["id"], "ACTIVE")
    transition_participant(participant["id"], "TERMINATED")

    resp = api.transition_participant(participant["id"], {"to_state": "ACTIVE"}, admin_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    after = api.get_participant(participant["id"], admin_headers)
    assert after.json()["data"]["status"] == "TERMINATED"


def test_list_endpoint_applies_default_limit_10(api, auditor_headers):
    """PRD §2.3: "The `limit` parameter specifies the maximum number of items to
    return; it defaults to 10 when omitted, accepts a minimum of 1, and is
    capped at a maximum of 100."
    PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."

    Design: Corner/endpoints/list_endpoint_applies_default_limit_10
    """
    for i in range(12):
        create_participant(
            legal_name=f"Bank {i + 1:02d}",
            participant_type="ODFI",
            routing_number=f"111000{i + 11:03d}"[:9].ljust(9, "0"),
        )

    resp = api.list_participants(auditor_headers)
    data, meta = validate_paginated(resp)
    assert len(data) == 10
    assert meta["limit"] == 10
    assert meta["total_count"] == 12
    assert meta["has_more"] is True
    assert resp.json()["response_type"] == "array"
    assert resp.json()["meta"]["api_request_id"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "A request that arrives without these headers, or whose
    declared role is not one of these four, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_unauthenticated
    """
    resp = api.list_participants(None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_server_default_clock_is_2026_09_01(api, admin_headers):
    """This test deliberately never calls the clock endpoint: the created
    participant's created_at must read the pinned startup instant.

    PRD §2.4: "At server startup the logical clock reads exactly
    `2026-09-01T00:00:00Z`, and it never falls back to wall-clock time on its
    own; it advances only when explicitly set."

    Design: Corner/complexity_layers/server_default_clock_is_2026_09_01
    """
    resp = api.create_participant(
        create_participant_payload(
            legal_name="Bank One", participant_type="ODFI", routing_number="111000025"
        ),
        admin_headers,
    )
    participant = validate_create_success(resp)
    assert participant["created_at"].startswith("2026-09-01T00:00:00"), (
        f"created_at must read the startup logical clock, got {participant['created_at']!r}"
    )
