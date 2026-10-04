"""Cross-entity state gates: a payment's validity depends on the live state
of the agency, its attestation, and the quote — with the validation ladder
deciding which failure surfaces first."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_card_instrument,
    api_client,
    create_quote,
    get_agency,
    get_quote,
    get_service,
    make_payer_headers,
    register_payer,
    set_clock,
    setup_cf_checkout,
    setup_open_card_quote,
    suspend_agency,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
)

PA = TEST_USERS["platform_admin_headers"]


class TestAuthorizeComplianceGateOrdering:
    def _lapsed_compliance_setup(self):
        """Agency activated while its attestation is CURRENT; the clock then
        advances past expiry, and the quote (30-minute TTL) is expired too."""
        ctx = setup_cf_checkout(
            attestation_issued_at="2026-08-15T00:00:00Z",
            attestation_expires_at="2026-09-15T00:00:00Z",
        )
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 100000, "CARD")
        payer2 = register_payer(full_name="Sam Sub", email="sam@example.com", billing_zip="73104")
        foreign_card = add_card_instrument(payer2["id"])
        set_clock("2026-09-16T00:00:00Z")  # attestation EXPIRED; quote past its TTL
        return ctx, quote, foreign_card

    def test_authorize_with_lapsed_attestation_reports_compliance(self, api):
        """PRD §2.9: "a `PCI_DSS_AOC` attestation whose computed status is
        `CURRENT` at the logical clock is required to activate the agency, to
        quote a checkout, and to authorize a payment."
        PRD §2.8: "When a single request would fail several checks, the
        checks are evaluated in a fixed priority order and the request
        reports the error of the check with the lowest priority number."

        Design: Difficulty/priority_pair_validation_conflict/authorize_expired_attestation_beats_foreign_instrument
        """
        ctx, quote, foreign_card = self._lapsed_compliance_setup()
        resp = api_client.authorize_payment(
            {"quote_id": quote["id"], "instrument_id": foreign_card["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        # priority 6 (compliance) beats both the temporal (9) and ownership (10) failures
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_LAPSED)

    def test_failed_authorize_leaves_quote_open_and_no_transaction(self, api):
        """PRD §3.4: "the agency's `PCI_DSS_AOC` attestation must be
        `CURRENT` at the logical clock — otherwise `ERR_COMPLIANCE_LAPSED`".

        Design: Difficulty/priority_pair_validation_conflict/authorize_expired_attestation_beats_foreign_instrument
        """
        ctx, quote, foreign_card = self._lapsed_compliance_setup()
        resp = api_client.authorize_payment(
            {"quote_id": quote["id"], "instrument_id": foreign_card["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_LAPSED)
        rows, _ = validate_paginated(
            api_client.list_transactions(PA, params={"quote_id": quote["id"]})
        )
        assert rows == [], "a rejected authorize creates no transaction"
        assert get_quote(quote["id"], ctx["payer"]["id"])["status"] == "OPEN"


class TestQuoteComplianceGateOrdering:
    def _lapsed_agency(self):
        ctx = setup_cf_checkout(
            attestation_issued_at="2026-08-15T00:00:00Z",
            attestation_expires_at="2026-09-15T00:00:00Z",
        )
        set_clock("2026-09-16T00:00:00Z")
        return ctx

    def test_quote_create_with_lapsed_attestation_beats_amount_range(self, api):
        """PRD §3.4: "Quotation is gated on every side: the service must be
        `ACTIVE`, its agency must be `ACTIVE` — otherwise
        `ERR_AGENCY_NOT_ACTIVE` — the agency must hold a `CURRENT`
        `PCI_DSS_AOC` attestation at the logical clock — otherwise
        `ERR_COMPLIANCE_LAPSED` — the amount must lie within the service's
        inclusive bounds from `min_amount_cents` through `max_amount_cents` —
        otherwise `ERR_AMOUNT_OUT_OF_RANGE`".
        PRD §2.8: "When a single request would fail several checks, the
        checks are evaluated in a fixed priority order and the request
        reports the error of the check with the lowest priority number."

        Design: Difficulty/priority_pair_validation_conflict/quote_expired_attestation_beats_amount_range
        """
        ctx = self._lapsed_agency()
        resp = api_client.create_fee_quote(
            {"service_id": ctx["service"]["id"], "amount_cents": 50, "method": "CARD"},
            make_payer_headers(ctx["payer"]["id"]),
        )
        # 50 < min_amount_cents 100 too, but compliance (priority 6) ranks above fiscal (11)
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_LAPSED)

    def test_lapsed_attestation_quote_persists_nothing(self, api):
        """PRD §2.9: "a `PCI_DSS_AOC` attestation whose computed status is
        `CURRENT` at the logical clock is required to activate the agency, to
        quote a checkout, and to authorize a payment."

        Design: Difficulty/priority_pair_validation_conflict/quote_expired_attestation_beats_amount_range
        """
        ctx = self._lapsed_agency()
        resp = api_client.create_fee_quote(
            {"service_id": ctx["service"]["id"], "amount_cents": 50, "method": "CARD"},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_COMPLIANCE_LAPSED)
        rows, _ = validate_paginated(
            api_client.list_fee_quotes(PA, params={"service_id": ctx["service"]["id"]})
        )
        assert rows == []


class TestAuthorizeAgainstSuspendedAgency:
    def test_authorize_against_suspended_agency_fails_state_gate(self, api):
        """PRD §2.8: "The target resource must be in a state that permits the
        operation: `ERR_AGENCY_NOT_ACTIVE` for agency-gated operations".
        PRD §2.8: "`ERR_INVALID_STATE` for any other impermissible state —
        including authorizing a quote that is already `CONSUMED` or `VOIDED`".

        Design: Difficulty/cross_entity_state_dependency/authorize_blocked_when_agency_suspended
        """
        ctx = setup_open_card_quote()
        suspend_agency(ctx["agency"]["id"])  # cascade voids the OPEN quote
        resp = api_client.authorize_payment(
            {"quote_id": ctx["quote"]["id"], "instrument_id": ctx["card"]["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        # PRD does not rank the agency gate against the voided-quote gate (both
        # sit at the state-permission rung); either error is faithful.
        assert resp.status_code == 409
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_AGENCY_NOT_ACTIVE, ApiErrorId.ERR_INVALID_STATE]
        )
        rows, _ = validate_paginated(
            api_client.list_transactions(PA, params={"quote_id": ctx["quote"]["id"]})
        )
        assert rows == []

    def test_suspend_cascades_make_quote_unusable(self, api):
        """PRD §3.1: "Suspending an `ACTIVE` agency cascades downward in two
        links. First, every service of the agency in `ACTIVE` status moves to
        `DEACTIVATED`; second, for each service so deactivated, every fee
        quote of that service still `OPEN` moves to `VOIDED`."

        Design: Difficulty/cross_entity_state_dependency/authorize_blocked_when_agency_suspended
        """
        ctx = setup_open_card_quote()
        suspend_agency(ctx["agency"]["id"])
        assert get_agency(ctx["agency"]["id"])["status"] == "SUSPENDED"
        assert get_service(ctx["service"]["id"])["status"] == "DEACTIVATED"
        assert get_quote(ctx["quote"]["id"])["status"] == "VOIDED", (
            "the transaction's validity depends on a different entity's live state"
        )
