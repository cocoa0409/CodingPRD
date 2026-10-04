"""Path-resolution error catalogue: every parameterized resource resolves to its
own domain-specific 404."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_senior_adjudicator_headers,
    validate_error,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestNotFoundCatalog:
    def test_not_found_catalog_all_parameterized_resources(self, api):
        """PRD §2.11: "Paths that carry resource identifiers resolve them
        strictly left to right, and the first identifier that does not resolve
        rejects the whole request with the corresponding error: a missing worker
        yields `ERR_WORKER_NOT_FOUND` (404), a missing claim
        `ERR_CLAIM_NOT_FOUND` (404), a missing correction request
        `ERR_CORRECTION_NOT_FOUND` (404), a missing relationship
        `ERR_RELATIONSHIP_NOT_FOUND` (404), a missing overpayment case
        `ERR_OVERPAYMENT_NOT_FOUND` (404), and a missing payee case
        `ERR_PAYEE_CASE_NOT_FOUND` (404)."

        Design: Corner/errors/not_found_catalog_all_parameterized_resources
        """
        resp1 = api.get_claim("11111111-1111-4111-8111-111111111111", CS)
        validate_error(resp1, ApiErrorId.ERR_CLAIM_NOT_FOUND, 404)

        resp2 = api.request_evidence("22222222-2222-4222-8222-222222222222", CS)
        validate_error(resp2, ApiErrorId.ERR_CORRECTION_NOT_FOUND, 404)

        resp3 = api.verify_relationship("33333333-3333-4333-8333-333333333333", CS)
        validate_error(resp3, ApiErrorId.ERR_RELATIONSHIP_NOT_FOUND, 404)

        resp4 = api.begin_recovery("44444444-4444-4444-8444-444444444444", "FULL", CS)
        validate_error(resp4, ApiErrorId.ERR_OVERPAYMENT_NOT_FOUND, 404)

        resp5 = api.decide_payee_case(
            "55555555-5555-4555-8555-555555555555", "APPROVED",
            make_senior_adjudicator_headers("sen-1"),
        )
        validate_error(resp5, ApiErrorId.ERR_PAYEE_CASE_NOT_FOUND, 404)
