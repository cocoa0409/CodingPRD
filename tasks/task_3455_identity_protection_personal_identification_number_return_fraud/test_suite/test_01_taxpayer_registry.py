"""Taxpayer registry, response envelope, and list pagination tests.

Covers PRD section 3.1 registration defaults and uniqueness, section 2.9
resource-specific 404s, section 2.2 envelope shapes, and section 2.3
pagination metadata.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    assert_envelope_meta,
    assert_taxpayer,
    create_active_config,
    create_taxpayer,
    create_taxpayer_payload,
    file_passing_return,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
ANALYST = TEST_USERS["fraud_analyst_headers"]


def test_taxpayer_create_applies_defaults(api):
    """PRD section 3.1: "an optional `prior_year_refund_cents` recording the
    refund claimed on the prior year's accepted return (an integer no smaller
    than 0, defaulting to 0, and later fed into refund-delta scoring), and an
    optional `pin_delivery_channel` preference of `POSTAL_MAIL` or
    `ONLINE_ACCOUNT` that defaults to `POSTAL_MAIL`."
    PRD section 3.1: "A newly registered taxpayer has `status` `ACTIVE` and
    `ip_pin_enrollment` `NOT_ENROLLED`; both flags are system-managed."
    PRD section 2.5: "The `version` is an integer that starts at its initial
    value on creation and increments by 1 on every mutation of the resource,
    including mutations caused by cascade side effects".

    Design: Corner/entities/taxpayer_create_applies_defaults
    """
    resp = api.create_taxpayer(
        create_taxpayer_payload(tin="100000110", full_name="De Fault"), ADMIN
    )
    data = validate_success(resp, 201)
    assert_taxpayer(data)
    assert data["prior_year_refund_cents"] == 0
    assert data["pin_delivery_channel"] == "POSTAL_MAIL"
    assert data["status"] == "ACTIVE"
    assert data["ip_pin_enrollment"] == "NOT_ENROLLED"
    assert data["version"] == 1


def test_taxpayer_create_missing_required_tin(api):
    """PRD section 2.8 check 14: "Required fields present, enum values inside
    their declared sets, well-formed dates and TINs (a `tin` is exactly 9
    digits), appointment `end_at` strictly after `start_at`, `tax_year` equal
    to 2026 unless an operation states otherwise, and integers within range —
    violations yield `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/taxpayer_create_missing_required_tin
    """
    resp = api.create_taxpayer(
        {"full_name": "No Tin", "date_of_birth": "1990-01-01"}, ADMIN
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_taxpayer_duplicate_tin_rejected(api):
    """PRD section 3.1: "a `tin` (exactly 9 digits, unique across all
    taxpayers — a duplicate is rejected with `ERR_DUPLICATE_TIN`)".

    Design: Corner/entities/taxpayer_duplicate_tin_rejected
    """
    first = api.create_taxpayer(
        create_taxpayer_payload(tin="100000111", full_name="First Tin"), ADMIN
    )
    validate_success(first, 201)
    second = api.create_taxpayer(
        create_taxpayer_payload(tin="100000111", full_name="Second Tin"), ADMIN
    )
    validate_error(second, ApiErrorId.ERR_DUPLICATE_TIN)


def test_taxpayer_get_not_found_returns_404(api):
    """PRD section 2.9: "Each resource type has its own not-found error:
    `ERR_TAXPAYER_NOT_FOUND`, `ERR_RETURN_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`,
    `ERR_CASE_NOT_FOUND`, `ERR_CONFLICT_NOT_FOUND`, `ERR_PREPARER_NOT_FOUND`,
    `ERR_ALERT_NOT_FOUND`, `ERR_OFFICE_NOT_FOUND`, `ERR_DISBURSEMENT_NOT_FOUND`,
    `ERR_CONFIG_NOT_FOUND`, `ERR_HOLD_NOT_FOUND`, and
    `ERR_ADVOCATE_CASE_NOT_FOUND`, all HTTP 404."

    Design: Corner/entities/taxpayer_get_not_found_returns_404
    """
    resp = api.get_taxpayer(NON_EXISTENT_UUID, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TAXPAYER_NOT_FOUND)


def test_response_envelope_success_and_error_shape(api):
    """PRD section 2.2: "The `response_type` is either "object" for a single
    resource or "array" for a list of resources."
    PRD section 2.2: "The `error_id` is a unique, machine-readable string that
    identifies the specific error."
    PRD section 2.2: "The `message` provides a human-readable explanation of
    what went wrong."

    Design: Corner/endpoints/response_envelope_success_and_error_shape
    """
    created = create_taxpayer(tin="100000160", full_name="Env Elope")
    ok_resp = api.get_taxpayer(created["id"], ADMIN)
    ok_data = validate_success(ok_resp, 200)
    ok_body = ok_resp.json()
    assert ok_body["response_type"] == "object"
    assert_envelope_meta(ok_body["meta"])
    assert ok_data["id"] == created["id"]

    err_resp = api.get_taxpayer(NON_EXISTENT_UUID, ADMIN)
    err_data = validate_error(err_resp, ApiErrorId.ERR_TAXPAYER_NOT_FOUND)
    assert err_resp.json()["response_type"] == "error"
    assert isinstance(err_data["message"], str) and err_data["message"]


def test_return_list_pagination_limit_one(api):
    """PRD section 2.3: "The `limit` parameter caps the number of items
    returned: it defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD section 2.3: "Paginated list responses carry `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/entities/return_list_pagination_limit_one
    """
    create_active_config(model_version="MV-PG")
    file_passing_return(claimed_refund_cents=1000, bank_product="NONE")
    file_passing_return(claimed_refund_cents=2000, bank_product="NONE")

    rows, meta = validate_paginated(api.list_tax_returns(ANALYST, params={"limit": 1}))
    assert len(rows) == 1, f"limit=1 must return exactly 1 row, got {len(rows)}"
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert meta["limit"] == 1
    assert meta["offset"] == 0
