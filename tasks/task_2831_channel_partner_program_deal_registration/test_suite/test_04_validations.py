"""Guard clauses: the conditional certification gate, partner-type eligibility, credit-memo
bounds, the special-pricing validity instant, and three points where the rejection order
decides which of two live violations is reported."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_certification,
    create_account,
    create_and_invoice_order,
    create_partner,
    create_spr,
    credit_memo_payload,
    draft_registration,
    make_partner_headers,
    read_account,
    read_invoice,
    read_partner,
    read_registration,
    seed_protected_account,
    set_clock,
    submit_registration,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestConditionalAndTypeGates:
    def test_the_platform_suite_gate_fires_on_the_product_line_and_not_on_the_credit_total(
        self, api
    ):
        """PRD §3.1: "A partner must hold at least 2 enablement credits before any registration of
        theirs can be submitted. A registration whose `product_line` is `PLATFORM_SUITE` demands
        more: at least 6 credits, **and** at least one certification record in `ACTIVE` whose
        `track` is `TECH_EXPERT`. Failing either form of the requirement is
        `ERR_CERTIFICATION_REQUIREMENT_NOT_MET`."

        Design: Corner/validations/platform_suite_certification_gate_is_conditional_on_product_line
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        for engineer in ("Iva Sorel", "Jae Kim", "Gia Nolan"):
            add_certification(partner["id"], engineer_name=engineer, track="TECH_ASSOCIATE")
        account = create_account()

        gated = read_partner(partner["id"])
        assert gated["cert_credit_total"] == 6, "three associate records, six credits"
        rows, _ = validate_paginated(
            api.list_partner_certifications(partner["id"], ANALYST)
        )
        assert [row["track"] for row in rows] == ["TECH_ASSOCIATE"] * 3
        assert all(row["status"] == "ACTIVE" for row in rows)

        platform = draft_registration(
            partner["id"], account["id"], product_line="PLATFORM_SUITE"
        )
        analytics = draft_registration(
            partner["id"], account["id"], product_line="ANALYTICS_ADDON"
        )

        validate_error(
            api.submit_deal_registration(platform["id"], make_partner_headers(partner["id"])),
            ApiErrorId.ERR_CERTIFICATION_REQUIREMENT_NOT_MET.value,
            422,
        )
        refused = read_registration(platform["id"])
        assert refused["status"] == "DRAFT"
        assert refused["submitted_at"] is None

        accepted = validate_success(
            api.submit_deal_registration(analytics["id"], make_partner_headers(partner["id"]))
        )
        assert accepted["status"] == "SUBMITTED"
        assert accepted["submitted_at"] == "2026-03-01T00:00:00.000Z"

        assert read_account(account["id"])["coverage_state"] == "OPEN_CHANNEL", (
            "a submit protects nothing; only an approval does"
        )

    def test_a_reseller_is_refused_a_stocking_order_and_priced_without_the_allowance(self, api):
        """PRD §3.6: "A `STOCKING` order is accepted only for a partner whose `partner_type` is
        `DISTRIBUTOR`; giving a `RESELLER` a stocking order is `ERR_PARTNER_TYPE_NOT_ELIGIBLE`."
        PRD §2.8: "An order with `order_type` of `STOCKING` is accepted only when the partner's
        `partner_type` is `DISTRIBUTOR`; a `RESELLER` may place `DROP_SHIP` orders only."

        Design: Corner/validations/stocking_order_type_rejected_for_a_reseller_partner
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")

        validate_error(
            api.create_order_invoice(
                {
                    "partner_id": partner["id"],
                    "order_type": "STOCKING",
                    "list_amount_cents": 1000000,
                },
                ANALYST,
            ),
            ApiErrorId.ERR_PARTNER_TYPE_NOT_ELIGIBLE.value,
            422,
        )
        rows, meta = validate_paginated(
            api.list_order_invoices(ANALYST, params={"partner_id": partner["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

        priced = validate_success(
            api.create_order_invoice(
                {
                    "partner_id": partner["id"],
                    "order_type": "DROP_SHIP",
                    "list_amount_cents": 1000000,
                },
                ANALYST,
            ),
            201,
        )
        assert priced["margin_pct"] == pytest.approx(0.1000, abs=1e-9), (
            "a DROP_SHIP order earns no part of the 0.02 stocking allowance"
        )
        assert priced["invoice_amount_cents"] == 900000
        assert priced["status"] == "PENDING"
        assert read_partner(partner["id"])["trailing_revenue_cents"] == 0

    def test_a_credit_memo_is_refused_at_zero_and_at_the_whole_invoice_but_taken_between(
        self, api
    ):
        """PRD §3.6: "The credit must be strictly greater than 0 and strictly less than the order's
        **current** `invoice_amount_cents`, or `ERR_CREDIT_EXCEEDS_INVOICE`."
        PRD §2.8: "Checks are evaluated in the ascending priority order below, and the first failing
        check wins." — with "20. **Margin ceiling.** The resolved margin implied by a special-pricing
        grant or by a credit memo stays at or below the partner tier's margin ceiling — otherwise
        `ERR_MARGIN_CEILING_EXCEEDED` (422)" sitting strictly above "21. **Credit size.**
        `credit_memo_cents` is strictly greater than 0 and strictly less than the invoice's current
        `invoice_amount_cents` — otherwise `ERR_CREDIT_EXCEEDS_INVOICE` (422)".  So the two refused
        boundaries do not report the same error: a credit of 0 leaves the resolved margin untouched
        at 0.1000, clears the ceiling, and is caught by the credit-size check; a credit of the whole
        invoice drives the resolved margin to 1.0000, which breaches the REGISTERED ceiling of 0.18
        first and is therefore reported as `ERR_MARGIN_CEILING_EXCEEDED`.
        PRD §3.6: "On success the order moves `INVOICED → CREDITED`: `credit_memo_cents` records the
        credit, `invoice_amount_cents` is reduced by it, `margin_value_cents` is re-derived as
        `list_amount_cents` minus the new `invoice_amount_cents`, `margin_pct` is re-derived as
        `margin_value_cents` divided by `list_amount_cents` rounded half-up to four decimal places,
        `credit_reason` is recorded, the partner's `trailing_revenue_cents` is recomputed, and the
        order's `version` advances by 1."

        Design: Corner/validations/credit_memo_bounds_are_strict_at_both_ends
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        order = create_and_invoice_order(
            partner["id"], order_type="DROP_SHIP", list_amount_cents=1_000_000
        )
        assert order["invoice_amount_cents"] == 900000
        assert order["margin_value_cents"] == 100000

        for refused_credit, expected_error in (
            (0, ApiErrorId.ERR_CREDIT_EXCEEDS_INVOICE.value),
            (900000, ApiErrorId.ERR_MARGIN_CEILING_EXCEEDED.value),
        ):
            validate_error(
                api.issue_credit_memo(
                    order["id"], credit_memo_payload(refused_credit), ANALYST
                ),
                expected_error,
                422,
            )

        untouched = read_invoice(order["id"])
        assert untouched["status"] == "INVOICED"
        assert untouched["credit_memo_cents"] == 0
        assert untouched["invoice_amount_cents"] == 900000
        assert untouched["credit_reason"] is None

        credited = validate_success(
            api.issue_credit_memo(order["id"], credit_memo_payload(1000), ANALYST)
        )
        assert credited["status"] == "CREDITED"
        assert credited["credit_memo_cents"] == 1000
        assert credited["invoice_amount_cents"] == 899000
        assert credited["margin_value_cents"] == 101000
        assert credited["margin_pct"] == pytest.approx(0.1010, abs=1e-9)
        assert credited["list_amount_cents"] == 1000000, "a credit never touches the list amount"
        assert read_partner(partner["id"])["trailing_revenue_cents"] == 899000


class TestTemporalAndOrderingGates:
    def test_a_special_pricing_decision_at_exactly_the_expiry_instant_is_refused(self, api):
        """PRD §3.6: "The new request is stored with `status` `SUBMITTED`,
        `approved_extra_margin_pct` null, `decided_by_user_id` null, and an `expires_at` set to the
        earlier of the registration's `exclusivity_end_at` and the current logical instant plus 30
        days — the request confers no uplift at or after that instant."
        PRD §3.6: "`APPROVE` moves the request `SUBMITTED → APPROVED`, requires the current logical
        instant to be strictly before `expires_at` (otherwise `ERR_EXCLUSIVITY_WINDOW_EXPIRED`),
        requires that the base margin for the partner's `tier` plus the full in-window registration
        uplift of 0.06 plus `requested_extra_margin_pct` stays at or below the tier's margin ceiling
        (otherwise `ERR_MARGIN_CEILING_EXCEEDED`), and sets `approved_extra_margin_pct` equal to
        `requested_extra_margin_pct`."

        Design: Corner/validations/special_pricing_decision_at_the_expiry_instant_is_rejected
        """
        seed = seed_protected_account(clock="2026-04-01T00:00:00.000Z")
        registration = seed["incumbent_registration"]
        assert registration["exclusivity_end_at"] == "2026-05-01T00:00:00.000Z"
        version_before_request = read_registration(registration["id"])["version"]

        set_clock("2026-04-02T00:00:00.000Z")
        request = create_spr(
            registration["id"],
            seed["incumbent"]["id"],
            requested_extra_margin_pct=0.03,
            expected_registration_version=version_before_request,
        )
        assert request["expires_at"] == "2026-05-01T00:00:00.000Z", (
            "clamped by the exclusivity window, not by the later 30-day validity instant"
        )
        assert read_registration(registration["id"])["version"] == version_before_request + 1

        set_clock("2026-05-01T00:00:00.000Z")
        validate_error(
            api.decide_special_pricing_request(
                request["id"], {"decision": "APPROVE"}, DIRECTOR
            ),
            ApiErrorId.ERR_EXCLUSIVITY_WINDOW_EXPIRED.value,
            409,
        )

        refused = validate_success(api.get_special_pricing_request(request["id"], ANALYST))
        assert refused["status"] == "SUBMITTED"
        assert refused["approved_extra_margin_pct"] is None
        assert refused["decided_by_user_id"] is None
        assert read_registration(registration["id"])["version"] == version_before_request + 1, (
            "the refused decision advanced nothing on the registration"
        )

    def test_a_missing_account_outranks_the_missing_required_field_on_the_same_create(self, api):
        """PRD §2.8: "When a single request would fail more than one check, exactly one error is
        returned, and which one is fully determined. Checks are evaluated in the ascending priority
        order below, and the first failing check wins."
        PRD §2.8: "Path identifiers are resolved strictly left to right, and only then are body
        foreign keys resolved in the order they are declared."

        Design: Corner/validations/existence_outranks_shape_when_account_missing_required_field
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Gia Nolan", track="TECH_ASSOCIATE")

        response = api.create_deal_registration(
            {
                "partner_id": partner["id"],
                "account_id": NON_EXISTENT_UUID,
                "product_line": "ANALYTICS_ADDON",
                "expected_close_date": "2026-08-31T00:00:00.000Z",
            },
            make_partner_headers(partner["id"]),
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "the envelope carries a non-empty human-readable message"
        )

        rows, meta = validate_paginated(
            api.list_deal_registrations(ANALYST, params={"partner_id": partner["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_an_unauthorised_role_is_refused_before_the_fabricated_path_id_is_resolved(self, api):
        """PRD §2.8: "The acting role appears in the endpoint's authorised-role list — otherwise
        `ERR_UNAUTHORIZED` (403). Applies to every endpoint."
        PRD §3.3: "Submitting moves the registration `DRAFT → SUBMITTED`, and only the owning
        partner may do it."

        Design: Corner/validations/submit_by_unauthorized_role_returns_4xx_before_not_found
        """
        set_clock("2026-03-01T00:00:00.000Z")

        response = api.submit_deal_registration(NON_EXISTENT_UUID, DIRECTOR)
        validate_error(response, ApiErrorId.ERR_UNAUTHORIZED.value, 403)

        body = response.json()
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}, (
            "an authorisation refusal leaks no domain payload"
        )
        assert body["data"]["error_id"] != ApiErrorId.ERR_REGISTRATION_NOT_FOUND.value, (
            "authorisation sits above existence, so the fabricated id is never resolved"
        )

    def test_the_second_twin_registration_is_refused_while_the_first_is_merely_submitted(
        self, api
    ):
        """PRD §3.3: "No other registration of the **same** partner on the same account and product
        line may be in `SUBMITTED`, `UNDER_REVIEW`, `CHANGES_REQUESTED` or `CONFLICT_HELD`, or
        `ERR_DUPLICATE_REGISTRATION`."

        Design: Corner/validations/duplicate_registration_blocked_on_the_second_submit
        """
        set_clock("2026-03-01T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Gia Nolan", track="TECH_ASSOCIATE")
        account = create_account()

        first = draft_registration(partner["id"], account["id"], product_line="ANALYTICS_ADDON")
        second = draft_registration(
            partner["id"],
            account["id"],
            product_line="ANALYTICS_ADDON",
            expected_amount_cents=700_000,
        )

        submitted = submit_registration(first["id"], partner["id"])
        assert submitted["status"] == "SUBMITTED"
        assert submitted["submitted_at"] == "2026-03-01T00:00:00.000Z"

        validate_error(
            api.submit_deal_registration(second["id"], make_partner_headers(partner["id"])),
            ApiErrorId.ERR_DUPLICATE_REGISTRATION.value,
            409,
        )

        refused = read_registration(second["id"])
        assert refused["status"] == "DRAFT"
        assert refused["submitted_at"] is None
        assert refused["revision_round"] == 0
        assert read_account(account["id"])["coverage_state"] == "OPEN_CHANNEL"
