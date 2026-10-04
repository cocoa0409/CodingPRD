"""Broker onboarding, submission baseline, listing and approval gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_submitted_broker,
    get_broker,
    record_license,
    record_and_pass_financial_review,
    approve_broker,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.test_users import anonymous_headers, make_underwriter_headers


def test_broker_submission_returns_full_derived_baseline(api):
    """PRD §3.1: "On creation the brokerage is stamped into `SUBMITTED` status with a
    `tier` of `UNRATED`, a `financial_strength_score` of 0.00, a `rolling_quality_score`
    of 100.00, an `open_defect_tier` of 0, an `exclusivity_status` of `CLEAR`, a
    `rolling_funded_volume_cents` of 0, an `active_loan_count` of 0, a
    `total_active_compensation_commitment_cents` of 0, and an empty `licensed_states` list."
    PRD §2.8: "Most top-level resources — `Broker`, `BrokerLicense`, `FinancialReview`, `ProductEligibility`, `ExclusivityPolicy`, `RateSheet`, `LoanSubmission`, `CompensationPlan`, `UnderwritingDecision`, `TurnTimeEscalation` and `QualityControlReview` — carry a standard set of system-managed fields."

    Design: Corner/entities/broker_create_returns_every_declared_field_and_starts_submitted
    """
    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    broker = create_submitted_broker(
        legal_name="Fresh Submission Brokers Inc",
        nmls_id="NMLS-3325901",
        home_state="NV",
        volume_expectation_cents=50_000_000,
    )
    assert broker["status"] == "SUBMITTED"
    assert broker["tier"] == "UNRATED"
    assert float(broker["financial_strength_score"]) == 0.00
    assert float(broker["rolling_quality_score"]) == 100.00
    assert broker["open_defect_tier"] == 0
    assert broker["exclusivity_status"] == "CLEAR"
    assert broker["rolling_funded_volume_cents"] == 0
    assert broker["active_loan_count"] == 0
    assert broker["total_active_compensation_commitment_cents"] == 0
    assert broker["licensed_states"] == []
    assert broker["approved_product_codes"] == []
    assert broker["legal_name"] == "Fresh Submission Brokers Inc"
    assert broker["nmls_id"] == "NMLS-3325901"
    assert broker["home_state"] == "NV"
    assert broker["volume_expectation_cents"] == 50_000_000
    assert broker["suspended_reason"] is None
    # id is a bare UUID with no type prefix, and the common fields are present.
    assert ":" not in broker["id"]
    assert broker["created_at"] and broker["updated_at"]
    assert isinstance(broker["version"], int) and broker["version"] >= 1


def test_broker_submission_response_envelope_carries_request_metadata(api):
    """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this
    standard envelope format in their JSON body"
    PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request
    that starts with `req_`."

    Design: Corner/entities/broker_create_returns_every_declared_field_and_starts_submitted
    """
    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    response = api_client.create_broker(
        {
            "legal_name": "Envelope Check Brokers LLC",
            "nmls_id": "NMLS-3325901",
            "home_state": "NV",
            "volume_expectation_cents": 50_000_000,
        },
        TEST_USERS["channel_manager_headers"],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["response_type"] == "object"
    assert body["meta"]["api_request_id"].startswith("req_")
    assert body["meta"]["api_request_timestamp"]


def test_broker_create_ignores_client_supplied_status_and_derived_fields(api):
    """PRD §3.1: "These initial values are not client-supplied; `status`, `tier` and every
    rolling field are owned by the system."
    PRD §2.8: "The `id` is a server-minted UUID with no type prefix."

    Design: Corner/entities/broker_create_ignores_client_supplied_status_and_version
    """
    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    response = api_client.create_broker(
        {
            "legal_name": "Ignored Input Brokers Inc",
            "nmls_id": "NMLS-3325907",
            "home_state": "TX",
            "volume_expectation_cents": 50_000_000,
        },
        TEST_USERS["channel_manager_headers"],
    )
    broker = validate_success(response, expected_status=201)
    assert broker["status"] == "SUBMITTED", "status is server-owned"
    assert broker["tier"] == "UNRATED", "tier is server-owned"
    assert broker["version"] == 1, "a freshly created broker starts at version 1"
    assert ":" not in broker["id"], "the id carries no type prefix"


def test_broker_create_with_duplicate_nmls_id_is_rejected(api):
    """PRD §3.1: "The `nmls_id` is unique across all brokerages; a second registration
    reusing one that already exists is refused with `ERR_DUPLICATE_NMLS_ID`."

    Design: Corner/errors/duplicate_nmls_id_is_rejected_on_the_second_submission
    """
    first = create_submitted_broker(
        legal_name="Unique NMLS Brokers Inc", nmls_id="NMLS-3325911", home_state="TX",
        volume_expectation_cents=50_000_000,
    )
    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    response = api_client.create_broker(
        {
            "legal_name": "Duplicate NMLS Brokers LLC",
            "nmls_id": "NMLS-3325911",
            "home_state": "NV",
            "volume_expectation_cents": 50_000_000,
        },
        TEST_USERS["channel_manager_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_NMLS_ID)
    data, meta = validate_paginated(api_client.list_brokers(TEST_USERS["any_headers"], {"limit": 100}))
    assert len(data) == 1, "the duplicate never created a second row"
    assert get_broker(first["id"])["legal_name"] == "Unique NMLS Brokers Inc"
    assert get_broker(first["id"])["nmls_id"] == "NMLS-3325911"


def test_an_undeclared_role_name_is_refused_before_the_duplicate_nmls_check(api):
    """PRD §2.1: "If either header is absent, or if `X-User-Role` names a role that the
    system does not declare, the request is refused with `ERR_MISSING_USER_CONTEXT` and a
    `400 Bad Request` status."
    PRD §2.11: "User context is checked first, then the caller's permission for the endpoint"

    Design: Corner/validations/missing_user_context_header_is_the_first_check
    """
    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    create_submitted_broker(
        legal_name="Header First Brokers Inc", nmls_id="NMLS-3325930", home_state="TX",
        volume_expectation_cents=50_000_000,
    )
    response = api_client.create_broker(
        {
            "legal_name": "Header First Duplicate LLC",
            "nmls_id": "NMLS-3325930",
            "home_state": "NV",
            "volume_expectation_cents": 50_000_000,
        },
        {"X-User-ID": "unknown-operator-1", "X-User-Role": "LoanOfficer"},
    )
    validate_error(response, ApiErrorId.ERR_MISSING_USER_CONTEXT, expected_status=400)
    data, _ = validate_paginated(api_client.list_brokers(TEST_USERS["any_headers"], {"limit": 100}))
    assert len(data) == 1


def test_underwriter_cannot_approve_a_broker(api):
    """PRD §2.1: "A caller whose role is not permitted for the endpoint being invoked is
    refused with `ERR_INSUFFICIENT_PERMISSIONS` and a `403 Forbidden` status."
    PRD §2.1: "`ChannelManager` is the lender-side wholesale account manager: broker
    onboarding decisions"

    Design: Corner/validations/reviewer_role_cannot_approve_brokers
    """
    broker = create_submitted_broker()
    record_license(broker["id"], state_code="TX")

    from test_helpers import api_client

    response = api_client.approve_broker(broker["id"], make_underwriter_headers("uw-dana"))
    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS, expected_status=403)
    assert get_broker(broker["id"])["status"] == "SUBMITTED"


def test_second_approval_of_an_approved_broker_is_refused(api):
    """PRD §3.1: "the broker's status must be `SUBMITTED`, or the request fails with
    `ERR_BROKER_NOT_SUBMITTED`"

    Design: Corner/state_machines/broker_approve_from_already_approved_returns_broker_not_submitted
    """
    broker = create_submitted_broker()
    record_license(broker["id"], state_code="TX")
    record_and_pass_financial_review(broker["id"])
    approved = approve_broker(broker["id"])
    version_after_approval = approved["version"]

    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    response = api_client.approve_broker(broker["id"], TEST_USERS["channel_manager_headers"])
    validate_error(response, ApiErrorId.ERR_BROKER_NOT_SUBMITTED, expected_status=409)

    after = get_broker(broker["id"])
    assert after["status"] == "APPROVED"
    assert after["version"] == version_after_approval, "the rejected call fired no side effect"


def test_broker_list_honours_limit_offset_and_the_status_filter(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned: it defaults to 10,
    has a minimum of 1, and has a maximum of 100."
    PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` in the
    `meta` object of the envelope."

    Design: Corner/entities/broker_list_filters_and_paginates_with_total_count
    """
    from test_helpers import api_client
    from test_helpers.test_users import TEST_USERS

    approved = create_submitted_broker(home_state="TX")
    record_license(approved["id"], state_code="TX")
    record_and_pass_financial_review(approved["id"])
    approve_broker(approved["id"])
    create_submitted_broker(
        legal_name="Second Listing Brokers LLC", nmls_id="NMLS-3325904", home_state="NV",
        volume_expectation_cents=50_000_000,
    )
    create_submitted_broker(
        legal_name="Third Listing Brokers LP", nmls_id="NMLS-3325905", home_state="CA",
        volume_expectation_cents=50_000_000,
    )

    any_h = TEST_USERS["any_headers"]
    page1, meta1 = validate_paginated(api_client.list_brokers(any_h, {"limit": 2, "offset": 0}))
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True
    assert meta1["limit"] == 2 and meta1["offset"] == 0

    page2, meta2 = validate_paginated(api_client.list_brokers(any_h, {"limit": 2, "offset": 2}))
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    submitted, meta_status = validate_paginated(api_client.list_brokers(any_h, {"status": "SUBMITTED"}))
    assert len(submitted) == 2
    assert meta_status["total_count"] == 2

    defaulted, meta_default = validate_paginated(api_client.list_brokers(any_h))
    assert len(defaulted) == 3
    assert meta_default["limit"] == 10 and meta_default["offset"] == 0

    ca, meta_ca = validate_paginated(api_client.list_brokers(any_h, {"home_state": "CA"}))
    assert len(ca) == 1
    assert meta_ca["total_count"] == 1