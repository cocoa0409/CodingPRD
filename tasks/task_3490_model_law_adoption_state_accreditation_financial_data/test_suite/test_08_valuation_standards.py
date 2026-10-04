"""Valuation standards: author/activator segregation, activation state guards,
version-line retirement, and the filing pipeline's pinned-version currency."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    factories,
    fixtures,
    make_actuary_headers,
    make_insurer_user_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

STAFF = TEST_USERS["association_staff_headers"]
AUTHOR = "actuary-1"
ACTIVATOR = "actuary-2"
THIRD_ACTUARY = "actuary-3"


class TestValuationStandards:
    def test_stale_pinned_standard_rejected_at_validate(self, api):
        """PRD §3.4: "The cited valuation standard code must resolve to some standard (`ERR_VALUATION_STANDARD_NOT_FOUND`, 404) and must have a currently `ACTIVE` version (`ERR_VALUATION_STANDARD_NOT_ACTIVE`, 422, checked after the expected-version check); the server pins that active version's label into the filing's `valuation_standard_version_label` at creation."
        PRD §3.4: "the pinned `valuation_standard_version_label` must still be the `ACTIVE` version of its code, otherwise `ERR_VALUATION_STANDARD_NOT_ACTIVE` (422)."
        PRD §3.5: "Retirement reaches into the filing pipeline — a filing pinned to the retired version label will fail validation with `ERR_VALUATION_STANDARD_NOT_ACTIVE` (§3.4)"

        Design: Corner/cross_cutting_layers/stale_pinned_standard_rejected_at_validate
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90093", state["code"])
        fixtures.create_active_standard(api, code="VM-88", version_label="v1")
        filing = fixtures.create_filing(
            api, insurer, valuation_standard_code="VM-88",
            reported_surplus_cents=1000, asset_risk_cents=100,
            underwriting_risk_cents=0, other_risk_cents=0,
        )
        assert filing["valuation_standard_version_label"] == "v1", (
            "the ACTIVE version at creation is pinned into the filing"
        )
        fixtures.submit_filing(api, filing)
        # A successor version retires v1 while the filing awaits validation.
        v2 = validate_success(
            api.create_valuation_standard(
                factories.valuation_standard_payload("VM-88", "v2", guidance_text="g2"),
                make_actuary_headers(AUTHOR),
            ),
            201,
        )
        validate_success(
            api.activate_valuation_standard(v2["id"], make_actuary_headers(ACTIVATOR))
        )
        resp = api.validate_filing(filing["id"], STAFF)
        validate_error(resp, ApiErrorId.ERR_VALUATION_STANDARD_NOT_ACTIVE)
        after = validate_success(api.get_filing(filing["id"], STAFF))
        assert after["status"] == "SUBMITTED", "a rejected validate changes nothing"
        assert fixtures.list_rbc_reports(api, filing["id"]) == []

    def test_standard_activate_twice_rejected(self, api):
        """PRD §3.5: "the standard must be in `DRAFT` (`ERR_STANDARD_NOT_DRAFT`, 409)"
        PRD §3.5: "Activation moves the standard from `DRAFT` to `ACTIVE`, increments its `version`, and cascades: any other standard with the same `code` that is currently `ACTIVE` becomes `RETIRED`."

        Design: Corner/errors/standard_activate_twice_rejected
        """
        drafted = validate_success(
            api.create_valuation_standard(
                factories.valuation_standard_payload("VM-89", "v1"),
                make_actuary_headers(AUTHOR),
            ),
            201,
        )
        activated = validate_success(
            api.activate_valuation_standard(
                drafted["id"], make_actuary_headers(ACTIVATOR)
            )
        )
        assert activated["status"] == "ACTIVE"
        resp = api.activate_valuation_standard(
            drafted["id"], make_actuary_headers(THIRD_ACTUARY)
        )
        validate_error(resp, ApiErrorId.ERR_STANDARD_NOT_DRAFT)

    def test_standard_self_activation_forbidden(self, api):
        """PRD §3.5: "Activation is also `Actuary` work, but never the author's own: the standard must be in `DRAFT` (`ERR_STANDARD_NOT_DRAFT`, 409) and — checked after that state gate — the caller's `X-User-ID` must differ from the standard's `author_user_id` (`ERR_SELF_ACTIVATION_FORBIDDEN`, 422)."
        PRD §2.1: "The server records it as `author_user_id` on each `ValuationStandard` the actuary drafts, and — as a segregation-of-duties control — refuses to let that same identifier activate the standard (§3.5)."

        Design: Corner/errors/standard_self_activation_forbidden
        """
        drafted = validate_success(
            api.create_valuation_standard(
                factories.valuation_standard_payload("VM-90", "v1"),
                make_actuary_headers(AUTHOR),
            ),
            201,
        )
        assert drafted["author_user_id"] == AUTHOR
        resp = api.activate_valuation_standard(
            drafted["id"], make_actuary_headers(AUTHOR)
        )
        validate_error(resp, ApiErrorId.ERR_SELF_ACTIVATION_FORBIDDEN)
        activated = validate_success(
            api.activate_valuation_standard(
                drafted["id"], make_actuary_headers(ACTIVATOR)
            )
        )
        assert activated["status"] == "ACTIVE"

    def test_filing_create_with_draft_standard_rejected(self, api):
        """PRD §3.4: "The cited valuation standard code must resolve to some standard (`ERR_VALUATION_STANDARD_NOT_FOUND`, 404) and must have a currently `ACTIVE` version (`ERR_VALUATION_STANDARD_NOT_ACTIVE`, 422, checked after the expected-version check)"

        Design: Corner/validations/filing_create_with_draft_standard_rejected
        """
        state = fixtures.create_state(api, code="CA")
        insurer = fixtures.create_insurer(api, "90086", state["code"])
        # VM-84 exists only as a DRAFT — never activated.
        validate_success(
            api.create_valuation_standard(
                factories.valuation_standard_payload("VM-84", "v1"),
                make_actuary_headers(AUTHOR),
            ),
            201,
        )
        resp = api.create_filing(
            factories.filing_payload(
                insurer["id"], insurer["version"],
                valuation_standard_code="VM-84",
                reported_surplus_cents=1000, asset_risk_cents=100,
                underwriting_risk_cents=0, other_risk_cents=0,
            ),
            make_insurer_user_headers(insurer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VALUATION_STANDARD_NOT_ACTIVE)
        filings, _meta = validate_paginated(api.list_filings(insurer["id"], STAFF))
        assert filings == [], "no filing may be created against a non-ACTIVE code"

    def test_rbac_actuary_standards_exclusive(self, api):
        """PRD §3.5: "An `Actuary` drafts a standard version with a `code` (for example VM-20), a `version_label` within that code line, and the actuarial `guidance_text`"
        PRD §2.1: "A request whose role is not listed on the target endpoint, or that fails the ownership rules below, is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Design: Corner/rbac/rbac_actuary_standards_exclusive
        """
        resp = api.create_valuation_standard(
            factories.valuation_standard_payload("VM-85", "v1"), STAFF
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
