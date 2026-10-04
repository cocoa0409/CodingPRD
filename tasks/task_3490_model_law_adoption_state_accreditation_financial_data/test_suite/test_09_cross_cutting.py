"""Cross-cutting concerns: authentication, path resolution, the list envelope,
registry uniqueness, request shape, and entity-backed ownership."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_system_timestamp,
    factories,
    fixtures,
    headers_without_identity,
    make_actuary_headers,
    make_insurer_user_headers,
    make_review_team_lead_headers,
    make_state_regulator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]


class TestCrossCutting:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request with a missing header, an undeclared role name, or — for the entity-backed roles below — an `X-User-ID` that does not name an existing instance of that entity is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_model_act(
            factories.model_act_payload(model_code="MDL-830", version_label="v1"),
            headers_without_identity(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_not_found_sweep(self, api):
        """PRD §2.8: "path identifiers resolve left to right, each with its own not-found error (404): `ERR_MODEL_ACT_NOT_FOUND`, `ERR_EXPOSURE_DRAFT_NOT_FOUND`, `ERR_STATE_NOT_FOUND`, `ERR_ADOPTION_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND`, `ERR_INSURER_NOT_FOUND`, `ERR_FILING_NOT_FOUND`, `ERR_PRODUCER_NOT_FOUND`, `ERR_LICENSE_NOT_FOUND`, `ERR_MARKET_CONDUCT_CALL_NOT_FOUND`, and `ERR_VALUATION_STANDARD_NOT_FOUND`."

        Design: Corner/endpoints/not_found_sweep
        """
        state = fixtures.create_state(api, code="CA")
        missing = NON_EXISTENT_UUID
        checks = [
            (api.get_model_act(missing, STAFF), ApiErrorId.ERR_MODEL_ACT_NOT_FOUND),
            (api.get_state(missing, STAFF), ApiErrorId.ERR_STATE_NOT_FOUND),
            (api.get_insurer(missing, STAFF), ApiErrorId.ERR_INSURER_NOT_FOUND),
            (api.get_filing(missing, STAFF), ApiErrorId.ERR_FILING_NOT_FOUND),
            (api.get_producer(missing, STAFF), ApiErrorId.ERR_PRODUCER_NOT_FOUND),
            (
                api.get_market_conduct_call(missing, STAFF),
                ApiErrorId.ERR_MARKET_CONDUCT_CALL_NOT_FOUND,
            ),
            (
                api.close_exposure_draft(missing, STAFF),
                ApiErrorId.ERR_EXPOSURE_DRAFT_NOT_FOUND,
            ),
            (
                api.issue_findings(
                    missing, factories.findings_payload(1, 1),
                    make_review_team_lead_headers("lead-1"),
                ),
                ApiErrorId.ERR_REVIEW_NOT_FOUND,
            ),
            (
                api.certify_adoption(
                    missing, factories.certify_payload("SUBSTANTIALLY_SIMILAR"), STAFF
                ),
                ApiErrorId.ERR_ADOPTION_NOT_FOUND,
            ),
            (
                api.issue_license(
                    missing, make_state_regulator_headers(state["id"])
                ),
                ApiErrorId.ERR_LICENSE_NOT_FOUND,
            ),
            (
                api.activate_valuation_standard(
                    missing, make_actuary_headers("actuary-9")
                ),
                ApiErrorId.ERR_VALUATION_STANDARD_NOT_FOUND,
            ),
        ]
        for resp, error_id in checks:
            validate_error(resp, error_id)

    def test_list_envelope_and_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10, with a minimum of 1 and a maximum of 100; `offset` defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries `limit`, `offset`, `total_count`, and `has_more` in addition to the standard request fields."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier for the request that starts with `req_`."
        PRD §2.2: "The `api_request_timestamp` is a server-generated ISO 8601 UTC timestamp with three fractional digits."

        Design: Corner/endpoints/list_envelope_and_pagination_defaults
        """
        act = fixtures.create_model_act(api, model_code="MDL-840", version_label="v1")
        data, meta = validate_paginated(api.list_ballots(act["id"], STAFF))
        assert data == []
        assert meta["total_count"] == 0
        assert meta["has_more"] is False
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert_system_timestamp(
            meta.get("api_request_timestamp"), "meta.api_request_timestamp"
        )

    def test_duplicate_key_sweep(self, api):
        """PRD §2.7: "Five uniqueness rules guard the registries, each rejected with HTTP 409 and its own error identifier: the pair (`model_code`, `version_label`) on a model act (`ERR_DUPLICATE_MODEL_ACT`); `naic_code` on an insurer (`ERR_DUPLICATE_NAIC_CODE`); `npn` on a producer (`ERR_DUPLICATE_NPN`); the pair (`code`, `version_label`) on a valuation standard (`ERR_DUPLICATE_STANDARD_VERSION`); and `call_code` on a market conduct call (`ERR_DUPLICATE_CALL_CODE`)."

        Design: Corner/entities/duplicate_key_sweep
        """
        state = fixtures.create_state(api, code="CA")
        fixtures.create_model_act(api, model_code="MDL-900", version_label="v1")
        fixtures.create_insurer(api, "90090", state["code"])
        fixtures.create_producer(api, npn="P-90", home_state_code="CA")
        validate_success(
            api.create_valuation_standard(
                factories.valuation_standard_payload("VM-90", "v1"),
                make_actuary_headers("actuary-1"),
            ),
            201,
        )
        fixtures.create_call(api, state, call_code="MC-900")
        resp = api.create_model_act(
            factories.model_act_payload(model_code="MDL-900", version_label="v1"),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MODEL_ACT)
        resp = api.create_insurer(
            factories.insurer_payload("90090", state["code"], name="B"), STAFF
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NAIC_CODE)
        resp = api.create_producer(
            factories.producer_payload("P-90", full_name="Q"), STAFF
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NPN)
        resp = api.create_valuation_standard(
            factories.valuation_standard_payload("VM-90", "v1", guidance_text="g2"),
            make_actuary_headers("actuary-1"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_STANDARD_VERSION)
        resp = api.create_market_conduct_call(
            factories.call_payload(call_code="MC-900", topic="t2"),
            make_state_regulator_headers(state["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CALL_CODE)

    def test_insurer_create_missing_name_returns_invalid_request(self, api):
        """PRD §2.8: "required fields are present, enum values are valid, integer amounts are at least zero (`direct_premium_cents` must be strictly positive), every window's end is strictly after its start, and findings or self-assessment totals are at least 1 with the compliant count between 0 and that total; any violation is `ERR_INVALID_REQUEST` (400)."
        PRD §3.4: "An insurer enters the system when `AssociationStaff` registers it with a unique `naic_code`, a legal `name`, and a `domicile_state_code` that must match the `code` of an already-registered state"

        Design: Corner/entities/insurer_create_missing_name_returns_invalid_request
        """
        state = fixtures.create_state(api, code="CA")
        resp = api.create_insurer(
            factories.insurer_payload("90080", state["code"], name=factories.DROP),
            STAFF,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_rbac_insurer_cannot_file_for_other_insurer(self, api):
        """PRD §3.4: "An `InsurerUser` creates a draft filing with `insurer_id` — which must equal the caller's `X-User-ID` (`ERR_FORBIDDEN`)"
        PRD §2.8: "**Authorization and ownership** — the role must be listed on the endpoint and the ownership comparisons of §2.1 must hold; failures carry `ERR_FORBIDDEN` (403)." is stage 2, ahead of the stage-7 expected-version checks.

        Design: Corner/rbac/rbac_insurer_cannot_file_for_other_insurer
        """
        state = fixtures.create_state(api, code="CA")
        ins_a = fixtures.create_insurer(api, "90090", state["code"])
        ins_b = fixtures.create_insurer(api, "90091", state["code"])
        fixtures.create_active_standard(api, code="VM-86", version_label="v1")
        resp = api.create_filing(
            factories.filing_payload(
                ins_b["id"], ins_b["version"], valuation_standard_code="VM-86",
                reported_surplus_cents=1000, asset_risk_cents=100,
                underwriting_risk_cents=0, other_risk_cents=0,
            ),
            make_insurer_user_headers(ins_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        filings, _meta = validate_paginated(api.list_filings(ins_b["id"], STAFF))
        assert filings == [], "no filing may be created for another insurer"
