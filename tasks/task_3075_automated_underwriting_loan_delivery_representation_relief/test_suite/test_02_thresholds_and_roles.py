"""Eligibility thresholds, role gates, and header validation (PRD §2.1, §2.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_seller,
    create_servicer,
    set_clock,
    setup_counterparty_chain,
    make_seller_officer_headers,
    validate_error,
    validate_success,
    get_seller,
)

ADMIN = TEST_USERS["gse_admin_headers"]


class TestHeaderValidation:
    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header, or presenting a
        malformed one, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/missing_role_header_rejected
        """
        set_clock()
        resp = api.create_seller(
            {
                "legal_name": "No Header",
                "seller_number": "S-NH",
                "net_worth_cents": 500000000,
                "qc_defect_rate_bps": 100,
            },
            {"X-User-ID": "some-user", "X-User-Role": ""},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestApprovalThresholds:
    def test_seller_approve_below_net_worth_rejected(self, api):
        """PRD §2.4: "Both a seller and a servicer must report a
        `net_worth_cents` of at least 2,500,000 cents (that is, 25,000.00 in
        dollar terms); approval of an under-capitalized counterparty is
        rejected with `ERR_NET_WORTH_BELOW_MINIMUM`."

        Design: Corner/validations/seller_approve_below_net_worth_rejected
        """
        set_clock()
        thin = create_seller(legal_name="Thin Capital", seller_number="S-LOW",
                             net_worth_cents=2499999)
        ok = create_seller(legal_name="Just Enough", seller_number="S-OK",
                           net_worth_cents=2500000)
        resp = api.approve_seller(thin["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NET_WORTH_BELOW_MINIMUM)
        data = validate_success(api.approve_seller(ok["id"], ADMIN))
        assert data["status"] == "APPROVED"

    def test_seller_approve_above_qc_defect_rate_rejected(self, api):
        """PRD §2.4: "A seller must additionally present a
        `qc_defect_rate_bps` — its post-purchase quality-control defect rate
        expressed in basis points — of at most 150 basis points; exceeding that
        ceiling yields `ERR_QC_DEFECT_RATE_EXCEEDED`."

        Design: Corner/validations/seller_approve_above_qc_defect_rate_rejected
        """
        set_clock()
        sloppy = create_seller(legal_name="Sloppy QC", seller_number="S-QC1",
                               qc_defect_rate_bps=151)
        edge = create_seller(legal_name="Edge QC", seller_number="S-QC2",
                             qc_defect_rate_bps=150)
        resp = api.approve_seller(sloppy["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_QC_DEFECT_RATE_EXCEEDED)
        data = validate_success(api.approve_seller(edge["id"], ADMIN))
        assert data["status"] == "APPROVED"

    def test_servicer_approve_requires_satisfactory_rating(self, api):
        """PRD §2.4: "A servicer must instead present a `qc_rating` of
        `SATISFACTORY`; the ratings `NEEDS_IMPROVEMENT` and `UNSATISFACTORY`
        are both insufficient and produce `ERR_SERVICER_QC_RATING_INSUFFICIENT`."

        Design: Corner/validations/servicer_approve_requires_satisfactory_rating
        """
        set_clock()
        weak = create_servicer(legal_name="Weak Servicing", servicer_number="V-LOW",
                               qc_rating="NEEDS_IMPROVEMENT")
        resp = api.approve_servicer(weak["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_SERVICER_QC_RATING_INSUFFICIENT)
        assert api.get_servicer(weak["id"], ADMIN).json()["data"]["status"] == "PENDING_APPROVAL"


class TestRoleDenials:
    def test_seller_officer_cannot_approve_sellers(self, api):
        """PRD §4: "POST /gse/sellers/{sellerId}/approve — GseAdmin".
        PRD §2.1: "When a caller attempts an operation outside the permissions
        of their declared role, or fails an ownership check tied to their
        identity, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/roles/seller_officer_cannot_approve_sellers
        """
        set_clock()
        seller = create_seller()
        resp = api.approve_seller(seller["id"], make_seller_officer_headers(seller["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_seller(seller["id"])["status"] == "PENDING_APPROVAL"

    def test_get_endpoints_shared_across_all_roles(self, api):
        """PRD §2.1: "All roles may call every read endpoint; write
        permissions per endpoint are given in §4."

        Design: Corner/roles/get_endpoints_shared_across_all_roles
        """
        from test_helpers import create_draft_loan, make_servicer_officer_headers

        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-SH")
        role_headers = [
            ADMIN,
            make_seller_officer_headers(seller["id"]),
            TEST_USERS["underwriter_headers"],
            TEST_USERS["uw_engine_headers"],
            TEST_USERS["qc_auditor_headers"],
            make_servicer_officer_headers(servicer["id"]),
        ]
        for headers in role_headers:
            data = validate_success(api.get_loan(loan["id"], headers))
            assert data["id"] == loan["id"]
