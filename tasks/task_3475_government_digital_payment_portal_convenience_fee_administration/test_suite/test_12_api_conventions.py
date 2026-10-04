"""API-wide conventions: envelope shapes, pagination, filters, caller-context
and role checks, existence ordering, resource-specific 404s, service OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    build_user_headers,
    create_agency,
    create_agency_payload,
    create_authorization,
    create_service,
    get_service,
    make_agency_admin_headers,
    make_compliance_auditor_headers,
    make_payer_headers,
    pay,
    register_payer,
    set_clock,
    setup_active_agency,
    setup_cf_checkout,
    update_service,
    update_service_payload,
    validate_error,
    validate_paginated,
    validate_success,
    void_transaction,
)

PA = TEST_USERS["platform_admin_headers"]
TO = TEST_USERS["treasury_officer_headers"]
AA_LEAD = make_agency_admin_headers("aa-lead")


class TestPagination:
    def _two_authorized_txns(self):
        ctx = setup_cf_checkout(with_card=True)
        first = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], 100000, "CARD")
        # move the clock so created_at order is strict (created_at reads the logical clock)
        set_clock("2026-09-01T00:01:00Z")
        second = pay(ctx["service"]["id"], ctx["payer"]["id"], ctx["card"]["id"], 20000, "CARD")
        return ctx, first["transaction"], second["transaction"]

    def test_transactions_list_paginates_with_limit_offset(self, api):
        """PRD §2.3: "All list endpoints paginate through two query
        parameters: `limit`, defaulting to 10 with a minimum of 1 and a
        maximum of 100, and `offset`, defaulting to 0. The `meta` envelope of
        a list response carries `limit`, `offset`, `total_count` and
        `has_more`. Unless a list endpoint states otherwise, entries are
        returned in `created_at` ascending order."

        Design: Corner/entities/transactions_list_paginates_with_limit_offset
        """
        ctx, txn1, txn2 = self._two_authorized_txns()
        page1, meta1 = validate_paginated(
            api_client.list_transactions(
                PA, params={"payer_id": ctx["payer"]["id"], "limit": 1, "offset": 0}
            )
        )
        assert [row["id"] for row in page1] == [txn1["id"]]
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert meta1["limit"] == 1
        assert meta1["offset"] == 0
        page2, meta2 = validate_paginated(
            api_client.list_transactions(
                PA, params={"payer_id": ctx["payer"]["id"], "limit": 1, "offset": 1}
            )
        )
        assert [row["id"] for row in page2] == [txn2["id"]]
        assert meta2["has_more"] is False
        assert meta2["offset"] == 1

    def test_transactions_list_filter_by_funds_status(self, api):
        """PRD §3.4: "Transactions can be listed with optional `agency_id`,
        `service_id`, `payer_id`, `instrument_id`, `quote_id`,
        `current_batch_id` and `funds_status` filters alongside the standard
        `limit` and `offset` pagination."

        Design: Corner/endpoints/transactions_list_filter_by_funds_status
        """
        ctx, txn1, txn2 = self._two_authorized_txns()
        void_transaction(txn1["id"])
        voided, _ = validate_paginated(
            api_client.list_transactions(
                PA, params={"payer_id": ctx["payer"]["id"], "funds_status": "VOIDED"}
            )
        )
        assert [row["id"] for row in voided] == [txn1["id"]]
        live, _ = validate_paginated(
            api_client.list_transactions(
                PA, params={"payer_id": ctx["payer"]["id"], "funds_status": "AUTHORIZED"}
            )
        )
        assert [row["id"] for row in live] == [txn2["id"]]
        both, meta = validate_paginated(
            api_client.list_transactions(PA, params={"payer_id": ctx["payer"]["id"]})
        )
        assert [row["id"] for row in both] == [txn1["id"], txn2["id"]]
        assert meta["total_count"] == 2


class TestErrorEnvelope:
    def test_error_envelope_shape_on_failures(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format" — with "The `meta` object for error
        responses contains only `api_request_id` and
        `api_request_timestamp`."

        Design: Corner/endpoints/error_envelope_shape_on_failures
        """
        set_clock()
        agency = create_agency()
        resp_404 = api_client.get_agency("00000000-0000-4000-8000-0000000000ff", PA)
        validate_error(resp_404, ApiErrorId.ERR_AGENCY_NOT_FOUND)
        resp_409 = api_client.suspend_agency(agency["id"], PA)  # ONBOARDING cannot suspend
        validate_error(resp_409, ApiErrorId.ERR_INVALID_STATE)
        for resp in (resp_404, resp_409):
            body = resp.json()
            assert body["response_type"] == "error"
            assert isinstance(body["data"]["error_id"], str)
            assert body["data"]["message"].strip()
            assert isinstance(body["meta"]["api_request_id"], str)
            assert isinstance(body["meta"]["api_request_timestamp"], str)


class TestCallerContextAndRoles:
    def test_call_with_unknown_role_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying an
        `X-User-Role` value that is not one of the declared roles, is
        rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT` (HTTP 400)."

        Design: Corner/validations/call_with_unknown_role_returns_unauthenticated
        """
        set_clock()
        resp = api_client.create_agency(
            create_agency_payload(
                legal_name="Ghost Agency", agency_type="STATE", default_fee_model="ABSORBED"
            ),
            build_user_headers("root-1", "SuperUser"),
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT)

    def test_compliance_auditor_cannot_create_agency(self, api):
        """PRD §2.1: "`ComplianceAuditor` — files compliance attestations and
        is otherwise read-only across agency, service, authorization,
        attestation and ledger surfaces."
        PRD §2.1: "Once the caller context is established, the caller's role
        must appear in the target endpoint's authorized role list, or the
        request is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/compliance_auditor_cannot_create_agency
        """
        set_clock()
        resp = api_client.create_agency(
            create_agency_payload(
                legal_name="Auditor's Agency", agency_type="STATE", default_fee_model="ABSORBED"
            ),
            make_compliance_auditor_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_agency_admin_cannot_approve_authorization(self, api):
        """PRD §3.2: "Approval by a `PlatformAdmin` requires the parent
        service to exist and not be `DEACTIVATED`, otherwise
        `ERR_INVALID_STATE`".
        PRD §2.1: "the caller's role must appear in the target endpoint's
        authorized role list, or the request is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/agency_admin_cannot_approve_authorization
        """
        built = setup_active_agency()
        service = create_service(built["agency"]["id"])
        authorization = create_authorization(service["id"])
        assert authorization["status"] == "DRAFT"
        resp = api_client.approve_statutory_authorization(authorization["id"], AA_LEAD)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        rows, _ = validate_paginated(
            api_client.list_statutory_authorizations(service["id"], PA)
        )
        assert rows[0]["status"] == "DRAFT", "a forbidden approval changes nothing"


class TestExistenceOrdering:
    def test_authorize_body_fks_checked_in_declared_input_order(self, api):
        """PRD §2.8: "Path identifiers resolve first, left to right, then
        body foreign keys in the endpoint's declared input order."
        PRD §3.4: "the payer supplies `quote_id` and `instrument_id`".

        Design: Corner/validations/authorize_body_fks_checked_in_declared_input_order
        """
        set_clock()
        payer = register_payer()
        resp = api_client.authorize_payment(
            {
                "quote_id": "00000000-0000-4000-8000-000000000001",
                "instrument_id": "00000000-0000-4000-8000-000000000002",
            },
            make_payer_headers(payer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_NOT_FOUND)  # quote_id is the first declared input

    def test_unknown_ids_return_resource_specific_not_found(self, api):
        """PRD §2.8: "Each unresolved reference reports its own resource's
        not-found error, all HTTP 404: `ERR_AGENCY_NOT_FOUND`,
        `ERR_SERVICE_NOT_FOUND`, `ERR_PAYER_NOT_FOUND`,
        `ERR_INSTRUMENT_NOT_FOUND`, `ERR_QUOTE_NOT_FOUND`,
        `ERR_TRANSACTION_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`,
        `ERR_ACCOUNT_NOT_FOUND`, `ERR_AUTHORIZATION_NOT_FOUND`,
        `ERR_REFUND_NOT_FOUND`, `ERR_CHARGEBACK_NOT_FOUND` or
        `ERR_EXCEPTION_NOT_FOUND`."

        Design: Corner/errors/unknown_ids_return_resource_specific_not_found
        """
        set_clock()
        u = lambda n: f"00000000-0000-4000-8000-0000000000{n:02x}"
        cases = [
            (api_client.get_service(u(0xA1), PA), ApiErrorId.ERR_SERVICE_NOT_FOUND),
            (api_client.get_settlement_batch(u(0xA2), PA), ApiErrorId.ERR_BATCH_NOT_FOUND),
            (
                api_client.verify_settlement_account(u(0xA3), {"outcome": "SUCCESS"}, TO),
                ApiErrorId.ERR_ACCOUNT_NOT_FOUND,
            ),
            (
                api_client.approve_statutory_authorization(u(0xA4), PA),
                ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND,
            ),
            (
                api_client.decide_refund(u(0xA5), {"decision": "APPROVE"}, AA_LEAD),
                ApiErrorId.ERR_REFUND_NOT_FOUND,
            ),
            (
                api_client.contest_chargeback(u(0xA6), {"evidence_note": "ghost"}, AA_LEAD),
                ApiErrorId.ERR_CHARGEBACK_NOT_FOUND,
            ),
            (
                api_client.resolve_reconciliation_exception(
                    u(0xA7), {"resolution_note": "ghost"}, PA
                ),
                ApiErrorId.ERR_EXCEPTION_NOT_FOUND,
            ),
            (api_client.get_payer(u(0xA8), PA), ApiErrorId.ERR_PAYER_NOT_FOUND),
        ]
        for resp, expected in cases:
            validate_error(resp, expected)


class TestServiceOcc:
    def test_occ_put_service_stale_version_returns_412(self, api):
        """PRD §2.7: "Updating a service's pricing fields requires the
        non-optional input field `expected_service_version`, matching the
        service's current `version`; a mismatch is likewise rejected with
        `ERR_STALE_VERSION` (HTTP 412), protecting the caller from editing a
        stale copy of the pricing configuration."

        Design: Corner/cross_cutting/occ_put_service_stale_version_returns_412
        """
        ctx = setup_cf_checkout(with_payer=False)
        service = ctx["service"]  # version 2 after activation
        updated = update_service(
            service["id"], service["version"], max_amount_cents=900000
        )
        assert updated["version"] == 3
        assert updated["max_amount_cents"] == 900000
        resp = api_client.update_service(
            service["id"],
            update_service_payload(service["version"], max_amount_cents=800000),
            AA_LEAD,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_service(service["id"])
        assert after["version"] == 3
        assert after["max_amount_cents"] == 900000, "the rejected replay changed nothing"
