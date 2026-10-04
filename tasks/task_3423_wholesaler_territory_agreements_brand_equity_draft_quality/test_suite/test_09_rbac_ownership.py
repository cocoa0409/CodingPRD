"""RBAC segregation of duties and WholesalerPrincipal ownership checks."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_territory_payload,
    make_account,
    make_review,
    make_territory,
    make_transfer,
    make_wholesaler,
    make_wholesaler_headers,
    setup_awarded_territory,
    setup_qualified_transfer,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


class TestHeaderContext:
    def test_missing_auth_header_returns_400(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
        identifying the acting user, and `X-User-Role`, naming their
        operational capacity."
        PRD §2.1: "A request whose headers are missing or empty, or whose role
        value is not one of these four, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_auth_header_returns_400
        """
        resp = api.create_territory(
            create_territory_payload(name="Headerless Territory",
                                     state_code="TX"),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestSegregationOfDuties:
    def test_brewer_compliance_cannot_create_territory(
        self, api, compliance_headers
    ):
        """PRD §2.1: "Beyond authentication, each endpoint admits a fixed list
        of roles; a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
        PRD §2.1: "`BrewerCompliance` — the manufacturer's regulatory and
        compliance office, deliberately segregated from `BrewerAdmin`'s
        creation powers"

        Design: Corner/rbac/brewer_compliance_cannot_create_territory
        """
        resp = api.create_territory(
            create_territory_payload(name="Forbidden Territory",
                                     state_code="TX"),
            compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    def test_brewer_admin_cannot_decide_transfer(self, api, admin_headers):
        """PRD §2.1: "`BrewerCompliance` — the manufacturer's regulatory and
        compliance office, deliberately segregated from `BrewerAdmin`'s
        creation powers: transfer qualification reviews and decisions, and
        corrective-plan activation and resolution."
        PRD §2.1: "a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/brewer_admin_cannot_decide_transfer
        """
        env = setup_qualified_transfer(rofr=False, buyer_scores=80)
        transfer = env["transfer"]
        assert transfer["status"] == "QUALIFIED"

        resp = api.transfer_decision(transfer["id"], {"decision": "APPROVE"},
                                     admin_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        listed, _ = validate_paginated(
            api.list_agreement_transfers(env["agreement"]["id"], admin_headers))
        assert listed[0]["status"] == "QUALIFIED", "the forbidden call changed nothing"

    def test_draft_auditor_cannot_issue_pos_grants(self, api, auditor_headers):
        """PRD §2.1: "`DraftAuditor` — a field quality auditor who records
        draft-quality audits and holds no commercial powers."
        PRD §2.1: "a caller whose role is not on that list is rejected with
        `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

        Design: Corner/rbac/draft_auditor_cannot_issue_pos_grants
        """
        _, wholesaler, _ = setup_awarded_territory(
            territory_name="Audit Territory")
        account = make_account(wholesaler["id"], name="Audit Bar")

        resp = api.create_pos_grant(
            {"account_id": account["id"],
             "item_description": "auditor-issued neon", "value_cents": 500},
            auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

        rows, _ = validate_paginated(
            api.list_account_pos_grants(account["id"], ADMIN))
        assert rows == []


class TestOwnership:
    def test_non_seller_transfer_create_returns_not_resource_owner(self, api):
        """PRD §3.3: "A distributorship changes hands through a transfer
        application, initiated by the seller: a `WholesalerPrincipal` whose
        `X-User-ID` equals the wholesaler currently named on the agreement —
        anyone else is rejected with `ERR_NOT_RESOURCE_OWNER`."

        Design: Corner/validations/non_seller_transfer_create_returns_not_resource_owner
        """
        _, owner, agreement = setup_awarded_territory(
            territory_name="Owner Territory A",
            wholesaler_overrides={"financial_capacity_score": 70,
                                  "warehouse_capacity_score": 70,
                                  "market_coverage_score": 70})
        _, other, _ = setup_awarded_territory(
            territory_name="Owner Territory B",
            wholesaler_overrides={"financial_capacity_score": 70,
                                  "warehouse_capacity_score": 70,
                                  "market_coverage_score": 70})
        buyer = make_wholesaler(legal_name="Owner Buyer",
                                financial_capacity_score=80,
                                warehouse_capacity_score=80,
                                market_coverage_score=80)

        resp = api.create_transfer(
            {"agreement_id": agreement["id"], "buyer_wholesaler_id": buyer["id"],
             "purchase_price_cents": 900_000},
            make_wholesaler_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        listed, _ = validate_paginated(
            api.list_agreement_transfers(agreement["id"], ADMIN))
        assert listed == []

    def test_wholesaler_principal_cannot_acknowledge_others_review(self, api):
        """PRD §3.8: "The reviewed wholesaler then responds. The caller's
        `X-User-ID` must equal the review's `wholesaler_id`, else
        `ERR_NOT_RESOURCE_OWNER`."
        PRD §2.1: "ownership checks compare the governing wholesaler field of
        the resource being acted upon to `X-User-ID`, and a mismatch is
        rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/wholesaler_principal_cannot_acknowledge_others_review
        """
        _, wr1, _ = setup_awarded_territory(territory_name="Review Territory 1")
        _, wr2, _ = setup_awarded_territory(territory_name="Review Territory 2")
        review = make_review(wr1["id"], period_year=2026, period_quarter="Q3",
                             distribution_pct=90, share_pct=50)

        resp = api.review_response(review["id"], {"action": "ACKNOWLEDGE"},
                                   make_wholesaler_headers(wr2["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER)

        listed, _ = validate_paginated(
            api.list_wholesaler_reviews(wr1["id"], ADMIN))
        assert listed[0]["status"] == "PUBLISHED", "the review is unmoved"


class TestExistence:
    def test_decision_on_unknown_transfer_returns_404(
        self, api, compliance_headers
    ):
        """PRD §2.9: "Every identifier referenced in a request path or body —
        territory, wholesaler, agreement, transfer application, allocation
        event, retail account, performance review, corrective plan, POS grant,
        or promotion program — must name an existing resource; an unresolvable
        reference is rejected with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/decision_on_unknown_transfer_returns_404
        """
        resp = api.transfer_decision(NON_EXISTENT_UUID, {"decision": "APPROVE"},
                                     compliance_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
