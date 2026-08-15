"""Response envelope, client/carrier/invoice intake shape rules, and reads.

Covers the PRD §2.2 envelope contract, §3.1 client defaults, §2.7/§2.8
not-found handling, §3.3 intake shape rules, §2.3 pagination, and
read-after-write visibility of materialized invoice lines.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    assert_invoice,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    create_client,
    create_invoice,
    set_clock,
    setup_standard_chain,
)

UNKNOWN_CARRIER_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestEnvelopeShape:
    def test_success_envelope_carries_meta_object_and_data(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" with `meta`,
        `response_type`, and `data`; "The `api_request_id` is a server-generated
        unique identifier for the request that starts with `req_`."

        Design: Corner/endpoints/envelope_shape_success_and_error
        """
        set_clock()
        res = api.create_client(
            {"name": "Acme", "home_country": "US", "home_currency": "USD"}, ADMIN
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])
        assert body["data"]["name"] == "Acme"

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" with `response_type` "error" and `data`
        carrying `error_id` and `message`; PRD §2.8: "**Existence.** Path
        identifiers are resolved left to right, and request-body references are
        checked for existence and same-client membership; failures yield
        `ERR_NOT_FOUND`."

        Design: Corner/endpoints/envelope_shape_success_and_error
        """
        set_clock()
        res = api.get_carrier(UNKNOWN_CARRIER_ID, ADMIN)
        error = validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)
        assert res.json()["response_type"] == "error"
        assert error["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(error["message"], str) and error["message"].strip()


class TestClientCreate:
    def test_client_create_applies_audit_policy_defaults(self, api):
        """PRD §3.1: "`audit_tolerance_minor` (default 500) is the absolute
        variance, in home-currency minor units, up to which an invoice's audit
        variance auto-clears; `audit_tolerance_pct_bp` (default 200) is the same
        tolerance expressed in basis points of the rated total; and
        `dispute_window_days` (default 30) is the number of days an audit
        exception may remain unresolved before the system expires it."
        PRD §3.1: "A new account starts in `ONBOARDING`."

        Design: Corner/entities/client_create_applies_defaults
        """
        set_clock()
        client = create_client(name="Acme", home_country="US", home_currency="USD")
        assert client["audit_tolerance_minor"] == 500
        assert client["audit_tolerance_pct_bp"] == 200
        assert client["dispute_window_days"] == 30
        assert client["status"] == "ONBOARDING"
        assert is_iso8601_timestamp(client["created_at"])


class TestExistence:
    def test_get_unknown_carrier_returns_not_found(self, api):
        """PRD §2.7: "the server validates the identifiers strictly left to
        right: the first identifier that does not correspond to an existing
        resource is answered with `ERR_NOT_FOUND` (HTTP 404)".

        Design: Corner/entities/carrier_get_not_found_returns_404
        """
        set_clock()
        res = api.get_carrier(UNKNOWN_CARRIER_ID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


class TestInvoiceIntakeShape:
    def test_missing_invoice_number_is_invalid_request(self, api):
        """PRD §2.8: "Request-shape failures — a malformed body, a missing
        required field, an unknown field, or an invalid enum value — are
        rejected as `ERR_INVALID_REQUEST` (HTTP 400) and are reported before
        any state-evaluation failure is surfaced."

        The `invoice_number` is not among the optional intake fields of PRD
        §3.3, so omitting it is a missing-required-field rejection.

        Design: Corner/entities/invoice_create_missing_required_returns_invalid_request
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 100,
                "lines": [{"charge_code": "OTHER", "billed_amount_minor": 100}],
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)

    def test_billed_total_must_equal_sum_of_lines(self, api):
        """PRD §3.3: "`billed_total_minor` must equal the sum of the lines'
        billed amounts (`ERR_AMOUNT_MISMATCH`)".

        Design: Corner/validations/amount_mismatch_between_total_and_lines_rejected
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_number": "INV-X",
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 100,
                "lines": [{"charge_code": "OTHER", "billed_amount_minor": 150}],
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_AMOUNT_MISMATCH, expected_status=422)

    def test_zero_amount_line_is_invalid(self, api):
        """PRD §3.3: "amounts must be positive where a positive amount is
        required (`ERR_AMOUNT_INVALID`)".

        Design: Corner/validations/amount_invalid_zero_line_rejected
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_number": "INV-X",
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 0,
                "lines": [{"charge_code": "OTHER", "billed_amount_minor": 0}],
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_AMOUNT_INVALID, expected_status=422)


class TestShipmentIntakeShape:
    def test_unknown_mode_enum_is_invalid_request(self, api):
        """PRD §3.3: "the `mode` (one of `PARCEL`, `LTL`, `FTL`, `AIR`,
        `OCEAN`)"; PRD §2.8: "a malformed body, a missing required field, an
        unknown field, or an invalid enum value — are rejected as
        `ERR_INVALID_REQUEST` (HTTP 400)".

        Design: Corner/entities/shipment_create_invalid_enum_returns_invalid_request
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_shipment(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "pro_number": "PRO-1",
                "ship_date": "2026-08-02",
                "origin_country": "US",
                "dest_country": "CA",
                "mode": "SPACESHIP",
                "actual_weight_kg": 10,
            },
            ANALYST,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


class TestInvoiceListing:
    def test_pagination_envelope_limit_offset_total_has_more(self, api):
        """PRD §2.3: "`limit` caps the number of returned items; it defaults to
        10, with a minimum of 1 and a maximum of 100. `offset` skips a number of
        items from the start of the result set and defaults to 0." and "The
        `meta` object of list responses carries the pagination fields `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/invoice_list_pagination_defaults
        """
        chain = setup_standard_chain(with_contract=False)
        for number, amount in (("INV-A", 100), ("INV-B", 200), ("INV-C", 300)):
            create_invoice(
                chain["client"]["id"],
                chain["carrier"]["id"],
                invoice_number=number,
                billed_total_minor=amount,
                lines=[{"charge_code": "OTHER", "billed_amount_minor": amount}],
            )
        page1, meta1 = validate_paginated(
            api.list_invoices(ADMIN, params={"client_id": chain["client"]["id"],
                                             "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(
            api.list_invoices(ADMIN, params={"client_id": chain["client"]["id"],
                                             "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["has_more"] is False


class TestReadAfterWrite:
    def test_create_response_and_followup_read_are_immediately_consistent(self, api):
        """PRD §3.3: "On acceptance, each entry of `lines` materializes as an
        invoice-line row of the invoice, and the invoice is born with its two
        parallel status dimensions: `audit_status` `RECEIVED` and
        `payment_status` `UNPAID`."

        Design: Corner/consistency_model/immediate_consistency_read_after_write
        """
        chain = setup_standard_chain(with_contract=False)
        res = api.create_invoice(
            chain["client"]["id"],
            {
                "carrier_id": chain["carrier"]["id"],
                "invoice_number": "INV-1",
                "invoice_date": "2026-08-03",
                "currency": "USD",
                "billed_total_minor": 300,
                "lines": [
                    {"charge_code": "BASE_FREIGHT", "billed_amount_minor": 100},
                    {"charge_code": "FUEL_SURCHARGE", "billed_amount_minor": 100},
                    {"charge_code": "OTHER", "billed_amount_minor": 100},
                ],
            },
            ANALYST,
        )
        created = validate_success(res, 201)
        assert_invoice(created)
        assert created["audit_status"] == "RECEIVED"
        assert created["payment_status"] == "UNPAID"
        lines = validate_success(api.list_lines_of_invoice(created["id"], ADMIN))
        assert len(lines) == 3
        assert {line["charge_code"] for line in lines} == {
            "BASE_FREIGHT", "FUEL_SURCHARGE", "OTHER",
        }
        assert {line["invoice_id"] for line in lines} == {created["id"]}
