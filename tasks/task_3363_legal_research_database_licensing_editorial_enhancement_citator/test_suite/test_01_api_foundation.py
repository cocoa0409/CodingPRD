"""API-wide contract: response envelope, authentication, role gate, identifier
resolution, request-shape validation and pagination defaults (PRD §2)."""
from test_helpers import (
    MISSING_UUID,
    ApiErrorId,
    account_payload,
    document_payload,
    flat_plan_payload,
    validate_error,
    validate_paginated,
)


def test_response_envelope_shape_success_and_error(api):
    """PRD §2.2: "The `response_type` is either "object" for a single resource or
    "array" for a list of resources."
    PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
    the specific error."

    Design: Corner/endpoints/response_envelope_shape_success_and_error
    """
    ok = api.create_account(
        account_payload(org_name="Env Co", account_type="CORPORATE"),
        headers={"X-User-ID": "lm-env", "X-User-Role": "LicensingManager"},
    )
    ok_body = ok.json()
    assert ok.status_code == 201
    assert ok_body["response_type"] == "object"
    assert "api_request_id" in ok_body["meta"]
    assert "api_request_timestamp" in ok_body["meta"]
    account_id = ok_body["data"]["id"]
    assert account_id

    err = api.get_subscription(MISSING_UUID, headers={"X-User-ID": "lm-env", "X-User-Role": "LicensingManager"})
    err_body = err.json()
    assert err_body["response_type"] == "error"
    assert err_body["data"]["error_id"] == "ERR_SUBSCRIPTION_NOT_FOUND"
    assert err_body["data"]["message"]


def test_missing_auth_headers_returns_401_unauthenticated(api):
    """PRD §2.1: "A request whose headers are missing, blank, or whose
    `X-User-Role` value is not one of the declared roles is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/missing_auth_headers_returns_401_unauthenticated
    """
    resp = api.create_account(
        account_payload(org_name="NoAuth Co", account_type="CORPORATE"),
        headers={},
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


def test_researcher_cannot_create_document_returns_403(api):
    """PRD §2.1: "Each endpoint admits a specific subset of these roles; a request
    whose role is not on that list is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/validations/researcher_cannot_create_document_returns_403
    """
    resp = api.create_document(
        document_payload(title="Forbidden", raw_citation_string="1 F.4th 99"),
        headers={"X-User-ID": MISSING_UUID, "X-User-Role": "Researcher"},
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)


def test_not_found_sweep_across_collections(api, attorney_editor_headers, billing_admin_headers,
                                            compliance_officer_headers, licensing_manager_headers):
    """PRD §2.9: "Only after the body is well-formed does the system resolve
    identifiers, in a fixed order: documents first (`ERR_DOCUMENT_NOT_FOUND`, which
    also covers entries of a publish payload's `references` list), then headnotes
    (`ERR_HEADNOTE_NOT_FOUND`), subscriptions (`ERR_SUBSCRIPTION_NOT_FOUND`),
    invoices (`ERR_INVOICE_NOT_FOUND`), users (`ERR_USER_NOT_FOUND`), removal
    orders (`ERR_ORDER_NOT_FOUND`), license agreements (`ERR_AGREEMENT_NOT_FOUND`),
    body-referenced plans (`ERR_PLAN_NOT_FOUND`), body-referenced accounts
    (`ERR_ACCOUNT_NOT_FOUND`), usage events (`ERR_USAGE_EVENT_NOT_FOUND`), and
    royalty statements (`ERR_STATEMENT_NOT_FOUND`)."

    Design: Corner/errors/not_found_sweep_across_collections
    """
    cases = [
        (api.get_headnote(MISSING_UUID, attorney_editor_headers), ApiErrorId.ERR_HEADNOTE_NOT_FOUND),
        (api.get_invoice(MISSING_UUID, billing_admin_headers), ApiErrorId.ERR_INVOICE_NOT_FOUND),
        (api.get_removal_order(MISSING_UUID, compliance_officer_headers), ApiErrorId.ERR_ORDER_NOT_FOUND),
        (api.get_license_agreement(MISSING_UUID, licensing_manager_headers), ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
        (api.get_user(MISSING_UUID, licensing_manager_headers), ApiErrorId.ERR_USER_NOT_FOUND),
        (api.get_usage_event(MISSING_UUID, billing_admin_headers), ApiErrorId.ERR_USAGE_EVENT_NOT_FOUND),
        (api.get_royalty_statement(MISSING_UUID, billing_admin_headers), ApiErrorId.ERR_STATEMENT_NOT_FOUND),
    ]
    for resp, error_id in cases:
        validate_error(resp, error_id, 404)


def test_document_not_found_returns_404(api, content_ingester_headers):
    """PRD §2.9: "Only after the body is well-formed does the system resolve
    identifiers, in a fixed order: documents first (`ERR_DOCUMENT_NOT_FOUND`, which
    also covers entries of a publish payload's `references` list), then headnotes
    (`ERR_HEADNOTE_NOT_FOUND`), subscriptions (`ERR_SUBSCRIPTION_NOT_FOUND`),
    invoices (`ERR_INVOICE_NOT_FOUND`), users (`ERR_USER_NOT_FOUND`), removal
    orders (`ERR_ORDER_NOT_FOUND`), license agreements (`ERR_AGREEMENT_NOT_FOUND`),
    body-referenced plans (`ERR_PLAN_NOT_FOUND`), body-referenced accounts
    (`ERR_ACCOUNT_NOT_FOUND`), usage events (`ERR_USAGE_EVENT_NOT_FOUND`), and
    royalty statements (`ERR_STATEMENT_NOT_FOUND`)."

    Design: Corner/entities/document_not_found_returns_404
    """
    resp = api.get_document(MISSING_UUID, content_ingester_headers)
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_FOUND, 404)


def test_document_create_missing_required_field_returns_400(api, content_ingester_headers):
    """PRD §2.9: "Request-shape validation (`ERR_INVALID_REQUEST`) follows, covering
    missing required fields, enum values outside their domain, malformed dates,
    inverted windows and periods, non-positive seat counts, duplicate emails, and
    metered events that pair the wrong fields."

    Design: Corner/entities/document_create_missing_required_field_returns_400
    """
    payload = document_payload(title="Missing Citation")
    payload.pop("raw_citation_string")
    resp = api.create_document(payload, content_ingester_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_plan_invalid_enum_value_returns_400(api, licensing_manager_headers):
    """PRD §2.9: "Request-shape validation (`ERR_INVALID_REQUEST`) follows, covering
    missing required fields, enum values outside their domain, malformed dates,
    inverted windows and periods, non-positive seat counts, duplicate emails, and
    metered events that pair the wrong fields."

    Design: Corner/entities/plan_invalid_enum_value_returns_400
    """
    payload = flat_plan_payload(name="Bad Plan", billing_model="WEEKLY")
    resp = api.create_plan(payload, licensing_manager_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_documents_list_pagination_defaults(api, content_ingester_headers, platform_admin_headers):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; it
    defaults to 10 when omitted, and any value below 1 or above 100 is out of range
    — the minimum is 1 and the maximum is 100."
    PRD §2.3: "The `meta` object of a list response carries four pagination fields:
    `limit`, `offset`, `total_count`, and `has_more`."

    Design: Corner/entities/documents_list_pagination_defaults
    """
    api.create_document(
        document_payload(title="Only v. One", raw_citation_string="2 N.Y.3d 5", jurisdiction_code="NY"),
        content_ingester_headers,
    )
    resp = api.list_documents(platform_admin_headers)
    assert resp.json()["response_type"] == "array"
    assert "api_request_id" in resp.json()["meta"]
    assert "api_request_timestamp" in resp.json()["meta"]
    data, meta = validate_paginated(resp)
    assert meta["limit"] == 10, f"default limit must be 10, got {meta['limit']}"
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert len(data) == 1
