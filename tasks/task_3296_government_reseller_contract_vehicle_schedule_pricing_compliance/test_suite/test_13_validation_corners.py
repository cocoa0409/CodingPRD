"""Corner coverage: validations — auth presence, order lines, FKs, periods, SoD."""
from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    ApiErrorId,
    create_active_agreement,
    create_price_modification_payload,
    create_sales_report,
    set_clock,
    setup_active_chain,
    validate_error,
    validate_success,
)

CM = TEST_USERS["contracts_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
FIN = TEST_USERS["finance_ops_headers"]
OPS = TEST_USERS["reseller_ops_headers"]


class TestMissingAuthHeaders:
    def test_no_headers_rejected_401(self, api):
        """PRD §2.1: "When either header is missing or malformed, the request
        is rejected with ERR_MISSING_AUTH_HEADERS (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_401
        """
        resp = api.list_manufacturers(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH_HEADERS)


class TestOrderLineSanity:
    def test_qty_zero_rejected(self, api):
        """PRD §3.6: "Every SKU must appear on that pinned list and every
        quantity must be positive, otherwise creation fails with
        ERR_ORDER_LINE_INVALID."

        Design: Corner/validations/order_lines_qty_zero_rejected
        """
        _, _, vehicle, price_list = setup_active_chain()
        resp = api.create_order(
            {"vehicle_id": vehicle["id"], "price_list_id": price_list["id"],
             "buyer_tier": "FEDERAL", "lines": [{"sku": "SW-1", "qty": 0}]},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_LINE_INVALID)


class TestBodyFkNotFound:
    def test_order_create_unknown_vehicle_fk(self, api):
        """PRD §2.9: "Identifiers supplied inside a request body (foreign keys
        such as vehicle_id, price_list_id, teaming_id, order_id, or
        agreement_id) are validated after path parameters; an unresolvable
        body foreign key yields ERR_FK_NOT_FOUND (HTTP 404)."

        Design: Corner/validations/fk_not_found_on_order_create
        """
        resp = api.create_order(
            {"vehicle_id": NON_EXISTENT_UUID, "price_list_id": NON_EXISTENT_UUID,
             "buyer_tier": "FEDERAL", "lines": [{"sku": "SW-1", "qty": 1}]},
            OPS,
        )
        validate_error(resp, ApiErrorId.ERR_FK_NOT_FOUND)


class TestPeriodNotClosed:
    def test_finalize_open_period_rejected(self, api):
        """PRD §3.8: "Finalization moves a DRAFT report to FINALIZED and is
        permitted only after the logical clock has moved past the period's end
        (otherwise ERR_PERIOD_NOT_CLOSED)."

        Design: Corner/validations/period_not_closed_finalize_rejected
        """
        set_clock("2026-10-15T00:00:00Z")
        _, agreement = create_active_agreement()
        report = create_sales_report(agreement["id"], period_label="2026-10")
        resp = api.finalize_sales_report(report["id"], FIN)
        validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED)


class TestPriceModificationSod:
    def test_proposer_cannot_approve_own_modification(self, api):
        """PRD §3.4: "Approval is performed by a ComplianceOfficer whose
        X-User-ID must differ from the proposer's — otherwise the approval is
        rejected with ERR_SOD_VIOLATION."
        PRD §2.1: "Segregation-of-duties checks (for example, comparing the
        X-User-ID of a price-modification approver against the X-User-ID
        recorded at proposal time) compare operator identifiers to operator
        identifiers, never to entity primary keys."

        Design: Corner/validations/sod_price_modification_creator_cannot_approve
        """
        from test_helpers import build_user_headers

        _, _, _, price_list = setup_active_chain()
        pl = validate_success(api.get_price_list(price_list["id"], CM))
        proposer_headers = build_user_headers("cm-user-1", "ContractsManager")
        resp = api.create_price_modification(
            create_price_modification_payload(
                price_list["id"], pl["version"], new_offered_price_cents=9000,
            ),
            proposer_headers,
        )
        modification = validate_success(resp, expected_status=201)
        same_operator = build_user_headers("cm-user-1", "ComplianceOfficer")
        resp = api.approve_price_modification(modification["id"], same_operator)
        validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION)
