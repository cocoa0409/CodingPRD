"""Corner cases of the validation priority ladder: auth, path existence, body
foreign keys, partner scope, segregation of duties and optimistic concurrency."""
from test_helpers import (
    CO,
    NON_EXISTENT_UUID,
    PO,
    ApiErrorId,
    api_client,
    build_user_headers,
    create_complaint_payload,
    create_diligence_review_payload,
    create_marketing_review_payload,
    create_partner,
    get_success_data,
    read_partner,
    validate_error,
    validate_paginated,
    validate_success,
)

NO_HEADERS = {}
EMPTY_ID = {"X-User-ID": "", "X-User-Role": "ProgramOfficer"}
UNKNOWN_ROLE = {"X-User-ID": "someone", "X-User-Role": "SuperUser"}


class TestAuthLadder:
    def test_the_header_ladder_answers_before_the_path_id_is_ever_resolved(self):
        """**Rank 1 — Authentication headers (all endpoints).** Both `X-User-Role` and `X-User-ID`
        are present and non-empty, else `ERR_MISSING_AUTH_HEADERS` (401). **Rank 8 — Path existence
        (every endpoint with a path id).** Path ids are resolved **left to right**, and the first
        segment that names no existing row determines the error.

        Design: Corner/validations/the_auth_header_ladder_rejects_missing_headers_and_unknown_roles_before_any_path_lookup
        """
        missing = NON_EXISTENT_UUID
        validate_error(
            api_client.go_live(missing, {}, NO_HEADERS),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS,
            401,
        )
        validate_error(
            api_client.go_live(missing, {}, EMPTY_ID),
            ApiErrorId.ERR_MISSING_AUTH_HEADERS,
            401,
        )
        validate_error(
            api_client.go_live(missing, {}, UNKNOWN_ROLE),
            ApiErrorId.ERR_UNKNOWN_ROLE,
            401,
        )
        validate_error(
            api_client.go_live(missing, {}, CO),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )
        validate_error(
            api_client.go_live(missing, {}, PO),
            ApiErrorId.ERR_PARTNER_NOT_FOUND,
            404,
        )


class TestBodyForeignKeyPrecedence:
    def test_body_foreign_keys_resolve_before_the_schema_and_in_declaration_order(self):
        """**Rank 10 — Body foreign-key existence.** Every foreign-key id supplied in a request body
        must name an existing row, resolved in this declaration order: `partner_id` first, then
        `agreement_id`, then `custody_account_id`, then `parent_partner_id`. **Rank 18 — Request
        schema (all endpoints).** All required body fields are present.

        Design: Corner/validations/body_foreign_key_existence_outranks_schema_validation_and_is_checked_in_declaration_order
        """
        partner = create_partner(legal_name="Marchwood Pay Inc")

        validate_error(
            api_client.decide_diligence_review(
                NON_EXISTENT_UUID, {"outcome": "NOT_A_REAL_OUTCOME"}, CO
            ),
            ApiErrorId.ERR_REVIEW_NOT_FOUND,
            404,
        )

        headless = create_complaint_payload(NON_EXISTENT_UUID)
        headless.pop("narrative")
        validate_error(
            api_client.create_complaint(headless, PO),
            ApiErrorId.ERR_PARTNER_NOT_FOUND,
            404,
        )

        both_unknown = create_marketing_review_payload(NON_EXISTENT_UUID, NON_EXISTENT_UUID)
        validate_error(
            api_client.create_marketing_review(both_unknown, PO),
            ApiErrorId.ERR_PARTNER_NOT_FOUND,
            404,
        )

        schema_only = create_complaint_payload(partner["id"])
        schema_only.pop("narrative")
        validate_error(
            api_client.create_complaint(schema_only, PO),
            ApiErrorId.ERR_VALIDATION,
            422,
        )


class TestPartnerScopePrecedence:
    def test_partner_scope_sits_below_role_authorisation_and_above_the_schema(self):
        """**Rank 12 — Partner scope.** As described in §2.1, a `FintechPartner` may only touch its
        own rows, else `ERR_PARTNER_SCOPE_VIOLATION` (403). The scope check guards
        `POST /oversight/partners/{id}/account-census`, `POST /oversight/marketing-reviews`,
        `POST /oversight/marketing-reviews/{id}/resubmit`, `POST /oversight/settlement-batches`,
        `POST /oversight/ledger-entries`, `POST /oversight/complaints`, and every GET endpoint that
        returns partner-scoped rows.

        Design: Corner/validations/the_fintech_partner_scope_check_sits_between_role_permission_and_schema_validation
        """
        first = create_partner(legal_name="Bellweather Pay Inc")
        second = create_partner(legal_name="Cloverfield Pay Inc")
        as_first = build_user_headers(first["id"], "FintechPartner")

        validate_error(
            api_client.go_live(first["id"], {}, as_first),
            ApiErrorId.ERR_ROLE_NOT_PERMITTED,
            403,
        )

        cross_and_malformed = create_complaint_payload(second["id"], channel="TELEGRAM")
        validate_error(
            api_client.create_complaint(cross_and_malformed, as_first),
            ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION,
            403,
        )

        validate_error(
            api_client.report_account_census(
                second["id"],
                {"end_user_account_count": 250_000, "as_of_date": "2026-08-01T00:00:00Z"},
                as_first,
            ),
            ApiErrorId.ERR_PARTNER_SCOPE_VIOLATION,
            403,
        )

        own = validate_success(
            api_client.report_account_census(
                first["id"],
                {"end_user_account_count": 250_000, "as_of_date": "2026-08-01T00:00:00Z"},
                as_first,
            ),
            200,
        )
        assert own["end_user_account_count"] == 250_000
        assert own["version"] == 2
        assert own["complaint_rate_bps"] == 0


class TestSegregationOfDutiesPrecedence:
    def test_the_same_human_wearing_both_roles_is_refused_before_the_score_floors(self):
        """**Rank 14 — Segregation of duties.** As described in §2.9, else
        `ERR_SEGREGATION_OF_DUTIES` (403). It guards exactly four endpoints:
        `POST /oversight/agreements/{id}/risk-decision`,
        `POST /oversight/diligence-reviews/{id}/decide`,
        `POST /oversight/marketing-reviews/{id}/decide` and
        `POST /oversight/wind-down-plans/{id}/decide`.

        Design: Corner/validations/segregation_of_duties_is_evaluated_before_the_state_guard_and_before_the_score_floors
        """
        dual_as_officer = build_user_headers("dual_brett", "ProgramOfficer")
        dual_as_compliance = build_user_headers("dual_brett", "ComplianceOfficer")
        partner = create_partner(legal_name="Ridgeback Pay Inc")

        review = get_success_data(
            api_client.create_diligence_review(
                create_diligence_review_payload(
                    partner["id"], partner["version"], compliance_capability_score=40
                ),
                dual_as_officer,
            )
        )
        submitted = get_success_data(
            api_client.submit_diligence_review(review["id"], {}, dual_as_officer)
        )
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_by_user_id"] == "dual_brett"

        validate_error(
            api_client.decide_diligence_review(
                review["id"], {"outcome": "PASSED"}, dual_as_compliance
            ),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES,
            403,
        )
        validate_error(
            api_client.decide_diligence_review(review["id"], {"outcome": "PASSED"}, CO),
            ApiErrorId.ERR_COMPLIANCE_CAPABILITY_FLOOR,
            422,
        )
        untouched = get_success_data(api_client.get_diligence_review(review["id"], CO))
        assert untouched["status"] == "SUBMITTED", "a refused decision performs no write"
        assert untouched["version"] == submitted["version"]

        failed = get_success_data(
            api_client.decide_diligence_review(review["id"], {"outcome": "FAILED"}, CO)
        )
        assert failed["status"] == "FAILED", "the floors gate only the PASSED outcome"
        assert failed["decided_by_user_id"] == "co_1"


class TestOptimisticConcurrencyPrecedence:
    def test_the_stale_version_check_sits_below_the_schema_and_above_the_terminal_guard(self):
        """A mismatch is rejected with `ERR_STALE_PARTNER_VERSION` (HTTP 412). **Rank 32 — Partner
        terminality.** No `DiligenceReview`, `ProgramAgreement`, `MarketingReview`,
        `SettlementBatch`, `LedgerEntry`, `Complaint`, `TransactionMonitoringAlert` or
        `WindDownPlan` may be created for a partner whose `status` is `DILIGENCE_FAILED` or
        `TERMINATED`, else `ERR_PARTNER_TERMINAL` (409).

        Design: Corner/validations/occ_version_checks_rank_below_schema_validation_but_above_every_state_guard
        """
        partner = create_partner(legal_name="Hollowmere Pay Inc")
        stale_version = partner["version"]

        first = get_success_data(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner["id"], stale_version), PO
            )
        )
        get_success_data(api_client.submit_diligence_review(first["id"], {}, PO))
        decided = get_success_data(
            api_client.decide_diligence_review(first["id"], {"outcome": "FAILED"}, CO)
        )
        assert decided["status"] == "FAILED"
        failed_partner = read_partner(partner["id"])
        assert failed_partner["status"] == "DILIGENCE_FAILED"
        assert failed_partner["version"] > stale_version, "the cascade wrote the partner row"

        malformed = create_diligence_review_payload(
            partner["id"], stale_version, business_model_score=999
        )
        validate_error(
            api_client.create_diligence_review(malformed, PO), ApiErrorId.ERR_VALIDATION, 422
        )
        validate_error(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner["id"], stale_version), PO
            ),
            ApiErrorId.ERR_STALE_PARTNER_VERSION,
            412,
        )
        validate_error(
            api_client.create_diligence_review(
                create_diligence_review_payload(partner["id"], failed_partner["version"]), PO
            ),
            ApiErrorId.ERR_PARTNER_TERMINAL,
            409,
        )

        rows, meta = validate_paginated(
            api_client.list_diligence_reviews(PO, {"partner_id": partner["id"]})
        )
        assert meta["total_count"] == 1, "none of the three refusals created a row"
        assert rows[0]["id"] == first["id"]
