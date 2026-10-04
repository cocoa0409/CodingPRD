"""Corner coverage: response envelopes, pagination defaults, and fiscal errors."""

from test_helpers import (
    FIELD_OFFICER_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    enroll,
    list_invoices,
    make_beneficiary_headers,
    pay_invoice_payload,
    premium_determination_payload,
    register_beneficiary,
    set_clock,
    setup_billed_enrollment,
    setup_final_determination,
    validate_error,
    validate_paginated,
)


def test_list_endpoint_pagination_envelope_defaults(client):
    """PRD section 2.3: "The `limit` parameter specifies the maximum number of
    items to return; it defaults to 10 when omitted, with a minimum of 1 and a
    maximum of 100. The `offset` parameter specifies the number of items to
    skip and defaults to 0." PRD section 2.2: "Pagination-related fields in
    `meta` (`limit`, `offset`, `total_count`, `has_more`) are included for
    list endpoints."

    Design: Corner/endpoints/list_endpoint_pagination_envelope_defaults
    """
    beneficiary = register_beneficiary(client, date_of_birth="1961-12-14")
    set_clock(client, "2026-10-10T00:00:00Z")
    enroll(client, beneficiary, part="PART_B")
    enroll(client, beneficiary, part="PART_D")

    response = client.list_enrollments(
        beneficiary["id"], headers=make_beneficiary_headers(beneficiary["id"])
    )
    data, meta = validate_paginated(response)
    body = response.json()
    assert body["response_type"] == "array"
    assert len(data) == 2
    assert meta["limit"] == 10
    assert meta["offset"] == 0
    assert meta["total_count"] == 2
    assert meta["has_more"] is False
    assert isinstance(meta.get("api_request_id"), str) and meta["api_request_id"]


def test_error_response_envelope_shape(client):
    """PRD section 2.2: "The `meta` object for error responses contains only
    `api_request_id` and `api_request_timestamp`." PRD section 2.2: "The
    `error_id` is a unique, machine-readable string that identifies the
    specific error."

    Design: Corner/endpoints/error_response_envelope_shape
    """
    register_beneficiary(client, date_of_birth="1961-12-14")
    response = client.get_enrollment(
        NON_EXISTENT_UUID, headers=FIELD_OFFICER_HEADERS
    )
    error_data = validate_error(response, ApiErrorId.ERR_ENROLLMENT_NOT_FOUND)
    assert response.status_code == 404
    assert error_data["message"].strip(), "message must be a non-empty string"

    body = response.json()
    assert body["response_type"] == "error"
    assert isinstance(body["meta"].get("api_request_id"), str)
    assert body["meta"]["api_request_id"]


def test_invoice_pay_wrong_amount_rejected(client):
    """PRD section 3.7: "then the payment must equal the invoice's
    `outstanding_cents` exactly, neither partial nor overpaid, otherwise
    `ERR_PAYMENT_AMOUNT_MISMATCH`."

    Design: Corner/errors/invoice_pay_wrong_amount_rejected
    """
    beneficiary, _enrollment, invoice = setup_billed_enrollment(client)
    assert invoice["status"] == "ISSUED"
    assert invoice["amount_cents"] == 18500
    assert invoice["paid_cents"] == 0

    response = client.pay_invoice(
        invoice["id"],
        pay_invoice_payload(18000),
        headers=make_beneficiary_headers(beneficiary["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PAYMENT_AMOUNT_MISMATCH)

    reread = list_invoices(client, beneficiary)[0]
    assert reread["status"] == "ISSUED", "a rejected payment changes nothing"
    assert reread["paid_cents"] == 0
    assert reread["outstanding_cents"] == 18500


def test_duplicate_determination_same_year_part_rejected(client):
    """PRD section 3.5: "and finally that no non-`SUPERSEDED` determination
    already exists for the same triple (`ERR_DUPLICATE_DETERMINATION`) — at
    most one live determination exists per (beneficiary, coverage year,
    part)."

    Design: Corner/errors/duplicate_determination_same_year_part_rejected
    """
    beneficiary, _enrollment, determination = setup_final_determination(client)
    assert determination["status"] == "FINAL"

    response = client.create_premium_determination(
        premium_determination_payload(beneficiary["id"], 2027, "PART_B"),
        headers=FIELD_OFFICER_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_DETERMINATION)
