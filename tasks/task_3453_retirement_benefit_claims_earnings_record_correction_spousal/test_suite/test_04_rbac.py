"""Role-based access control: role exclusivity, entity-backed ownership, and
authentication of missing headers."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_relationship,
    create_worker,
    file_claim,
    make_claimant_headers,
    make_senior_adjudicator_headers,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestRoleExclusivity:
    def test_rbac_employer_cannot_approve_claim(self, api, employer_headers):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §2.1: "A claims specialist is the field-office, first-instance
        adjudicator: worker intake, pension recording, death reporting, evidence
        requests, first-instance approvals and denials of corrections and claims,
        relationship verification, overpayment case creation, recovery initiation,
        and payee-case creation."

        Design: Corner/rbac/rbac_employer_cannot_approve_claim
        """
        worker = create_worker(full_name="Rbac One")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")

        resp = api.approve_claim(claim["id"], employer_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"

    def test_rbac_claimant_cannot_verify_relationship(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §3.3: "A `ClaimsSpecialist` verifies an `ASSERTED` relationship —
        `ASSERTED → VERIFIED` — stamping `verified_at` with the logical clock."

        Design: Corner/rbac/rbac_claimant_cannot_verify_relationship
        """
        w1 = create_worker(full_name="Rbac Two")
        w2 = create_worker(full_name="Rbac Three")
        rel = create_relationship(w1["id"], w2["id"], "CURRENT_SPOUSE", "2000-01-01")

        resp = api.verify_relationship(rel["id"], make_claimant_headers(w2["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        rels = validate_success(api.list_worker_relationships(w1["id"], CS))
        assert rels[0]["status"] == "ASSERTED"

    def test_rbac_senior_adjudicator_cannot_deny_claim(self, api):
        """PRD §2.1: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_UNAUTHORIZED_ROLE` (403)."
        PRD §2.1: "The senior adjudicator is the second-instance decision maker:
        reopening denied claims and corrections, deciding waiver requests, and
        deciding payee determinations."

        Design: Corner/rbac/rbac_senior_adjudicator_cannot_deny_claim
        """
        worker = create_worker(full_name="Rbac Four")
        claim = file_claim(worker["id"], "RETIREMENT", "2026-06")

        resp = api.deny_claim(claim["id"], "overreach", make_senior_adjudicator_headers("sen-1"))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

        unchanged = validate_success(api.get_claim(claim["id"], CS))
        assert unchanged["status"] == "FILED"


class TestOwnershipAndAuthentication:
    def test_rbac_claimant_cannot_read_other_workers_record(self, api, claims_specialist_headers):
        """PRD §2.1: "Concretely, a `Claimant` may only touch the `Worker` record
        whose `id` equals `X-User-ID`, a `BenefitClaim` whose `worker_id` equals
        it, a `CorrectionRequest` whose `worker_id` equals it, and payment,
        overpayment, or payee-case resources belonging to such a claim. A mismatch
        is rejected with `ERR_FORBIDDEN_OWNERSHIP` (403)."

        Design: Corner/rbac/rbac_claimant_cannot_read_other_workers_record
        """
        w1 = create_worker(full_name="Rbac Five")
        w2 = create_worker(full_name="Rbac Six")

        resp = api.get_worker(w2["id"], make_claimant_headers(w1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNERSHIP, 403)

        own = validate_success(api.get_worker(w2["id"], make_claimant_headers(w2["id"])))
        assert own["id"] == w2["id"]
        staff = validate_success(api.get_worker(w2["id"], claims_specialist_headers))
        assert staff["id"] == w2["id"]

    def test_rbac_missing_auth_headers_returns_401(self, api, claims_specialist_headers):
        """PRD §2.1: "A request with missing or malformed headers, or an
        unrecognized role, is rejected with `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/rbac_missing_auth_headers_returns_401
        """
        worker = create_worker(full_name="Rbac Seven")

        resp = api.get_worker(worker["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)
