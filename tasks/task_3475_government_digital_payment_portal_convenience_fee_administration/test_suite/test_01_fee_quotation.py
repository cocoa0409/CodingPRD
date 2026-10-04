"""Checkout fee quotation: dual fee variants, gross-up, floor, cap, quote shape."""
from datetime import datetime, timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    activate_service,
    api_client,
    assert_fee_quote,
    assert_transaction,
    authorize,
    create_approved_authorization,
    create_quote,
    create_service,
    get_quote,
    get_transaction,
    make_payer_headers,
    set_clock,
    setup_cf_checkout,
    setup_open_card_quote,
    update_service,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]


def _parse(ts):
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    raise AssertionError(f"unparseable timestamp {ts!r}")


def _add_cf_service(agency_id, service_code, gl_code, fee_cap_cents):
    """A second CONVENIENCE_FEE service in the same agency with its own cap."""
    service = create_service(
        agency_id,
        service_code=service_code,
        name=f"Service {service_code}",
        fee_model="CONVENIENCE_FEE",
        allowed_methods=["CARD", "ECHECK", "WALLET"],
        min_amount_cents=100,
        max_amount_cents=1000000,
        gl_code=gl_code,
    )
    create_approved_authorization(service["id"], fee_cap_cents=fee_cap_cents)
    return activate_service(service["id"])


class TestDualVariantFee:
    def test_quoted_fee_assumes_consumer_credit_bucket(self, api):
        """PRD §3.4: "The QUOTED variant, computed at quote time, is
        disclosure-binding: for `CARD` it is always rated from the
        `CONSUMER_CREDIT` bucket — a conservative statutory disclosure
        regardless of the instrument later presented — while `ECHECK` and
        `WALLET` quotes are exact."

        Design: Difficulty/dual_variant_calc/convenience_fee_quoted_assumes_credit_final_uses_actual_bucket
        """
        ctx = setup_open_card_quote()  # card instrument is CONSUMER_DEBIT
        quote = ctx["quote"]
        assert_fee_quote(quote)
        # CONSUMER_CREDIT closed form: ceil((220*100000 + 30*10000) / (10000-220)) == 2281
        assert quote["quoted_fee_cents"] == 2281, (
            f"QUOTED fee must be rated CONSUMER_CREDIT regardless of the "
            f"instrument's DEBIT bucket, got {quote['quoted_fee_cents']}"
        )
        assert quote["payer_total_cents"] == 102281
        assert quote["statutory_authorization_id"] == ctx["authorization"]["id"]
        assert quote["disclosure_text_version"] == "D1"

    def test_authorize_charges_quoted_fee_and_accrues_final_variant(self, api):
        """PRD §3.4: "The FINAL variant, computed at authorization, is rated
        from the presented instrument's actual `card_cost_bucket` and is also
        the portal's processing-cost accrual for the transaction."

        Design: Difficulty/dual_variant_calc/convenience_fee_quoted_assumes_credit_final_uses_actual_bucket
        """
        ctx = setup_open_card_quote()
        resp = api_client.authorize_payment(
            {"quote_id": ctx["quote"]["id"], "instrument_id": ctx["card"]["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        txn = validate_success(resp, 201)
        assert_transaction(txn)
        assert txn["funds_status"] == "AUTHORIZED"
        assert txn["charged_fee_cents"] == 2281, "charged fee is the disclosure-binding QUOTED fee"
        # FINAL with the actual CONSUMER_DEBIT bucket: ceil((150*100000 + 25*10000) / (10000-150)) == 1549
        assert txn["final_fee_cents"] == 1549, (
            f"FINAL fee must use the instrument's actual bucket, got {txn['final_fee_cents']}"
        )
        assert txn["final_fee_cents"] != txn["charged_fee_cents"]
        assert txn["payer_total_cents"] == 102281
        quote_after = get_quote(ctx["quote"]["id"], ctx["payer"]["id"])
        assert quote_after["status"] == "CONSUMED"
        assert quote_after["quoted_fee_cents"] == 2281
        assert quote_after["disclosure_text_version"] == "D1"


class TestWalletGrossUp:
    def test_wallet_quote_fee_uses_closed_form_gross_up(self, api):
        """PRD §3.4: "The raw fee is the ceiling, rounded up to the next whole
        cent, of the quantity formed by the rate in basis points times
        `amount_cents` plus the fixed cents times 10000, all divided by 10000
        minus the rate in basis points."

        Design: Difficulty/combinatorial_formula/wallet_fee_gross_up_circular_closed_form
        """
        ctx = setup_cf_checkout(with_wallet=True)
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 20000, "WALLET")
        assert_fee_quote(quote)
        # ceil((180*20000 + 25*10000) / (10000-180)) == ceil(392.057...) == 393
        assert quote["quoted_fee_cents"] == 393, (
            f"closed-form gross-up must yield 393, got {quote['quoted_fee_cents']}"
        )
        assert quote["quoted_fee_cents"] != 385, "the naive non-grossed reading is wrong"
        assert quote["payer_total_cents"] == 20393

    def test_wallet_quote_pins_authorization_and_disclosure(self, api):
        """PRD §3.4: "For `CONVENIENCE_FEE` quotes it also records the covering
        authorization's `statutory_authorization_id` and copies its
        `disclosure_text_version`; both are null for `ABSORBED`."

        Design: Difficulty/combinatorial_formula/wallet_fee_gross_up_circular_closed_form
        """
        ctx = setup_cf_checkout(with_wallet=True)
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 20000, "WALLET")
        assert quote["statutory_authorization_id"] == ctx["authorization"]["id"]
        assert quote["disclosure_text_version"] == "D1"
        assert quote["status"] == "OPEN"
        assert quote["service_version_pinned"] == ctx["service"]["version"] == 2


class TestFeeFloorAndQuotedBucket:
    def test_min_fee_floor_binds_on_small_card_amount(self, api):
        """PRD §3.4: "Step three applies the floor: the fee is the greater of
        100 cents and the raw fee."

        Design: Difficulty/combinatorial_formula/fee_floor_bucket_tier_nested_min_max
        """
        ctx = setup_cf_checkout()
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 1000, "CARD")
        # QUOTED gross-up at CONSUMER_CREDIT: ceil((220*1000 + 30*10000) / 9780) == 54 -> floor 100
        assert quote["quoted_fee_cents"] == 100, (
            f"the 100-cent floor must bind over the grossed raw fee, got {quote['quoted_fee_cents']}"
        )
        assert quote["payer_total_cents"] == 1100
        assert quote["statutory_authorization_id"] == ctx["authorization"]["id"]

    def test_quoted_variant_ignores_instrument_commercial_bucket(self, api):
        """PRD §3.4: "The QUOTED variant, computed at quote time, is
        disclosure-binding: for `CARD` it is always rated from the
        `CONSUMER_CREDIT` bucket — a conservative statutory disclosure
        regardless of the instrument later presented — while `ECHECK` and
        `WALLET` quotes are exact."

        Design: Difficulty/combinatorial_formula/fee_floor_bucket_tier_nested_min_max
        """
        ctx = setup_cf_checkout(with_card=True, card_cost_bucket="COMMERCIAL")
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 100000, "CARD")
        # CONSUMER_CREDIT closed form == 2281 (never the COMMERCIAL 3023)
        assert quote["quoted_fee_cents"] == 2281, (
            f"QUOTED must assume CONSUMER_CREDIT even for a COMMERCIAL instrument, "
            f"got {quote['quoted_fee_cents']}"
        )
        assert quote["quoted_fee_cents"] <= 5000, "within the 5000 statutory cap, no clamping involved"
        assert quote["statutory_authorization_id"] == ctx["authorization"]["id"]


class TestStatutoryCapBoundary:
    def test_fee_exactly_at_statutory_cap_is_allowed(self, api):
        """PRD §3.4: "The fee is never clamped down to the cap — the cap is a
        hard stop — and a fee exactly equal to the cap is allowed."

        Design: Difficulty/boundary_precision_check/statutory_cap_exact_allowed_over_rejected
        """
        ctx = setup_cf_checkout()
        svc_b = _add_cf_service(ctx["agency"]["id"], "DL-RENEW-B", "4111", fee_cap_cents=2281)
        resp = api_client.create_fee_quote(
            {"service_id": svc_b["id"], "amount_cents": 100000, "method": "CARD"},
            make_payer_headers(ctx["payer"]["id"]),
        )
        quote = validate_success(resp, 201)
        assert quote["quoted_fee_cents"] == 2281, "fee exactly equal to the cap must be accepted"

    def test_fee_over_statutory_cap_rejected_not_clamped(self, api):
        """PRD §3.4: "Step four applies the statutory cap, checked only after
        the floor: if the floored fee exceeds the covering authorization's
        `fee_cap_cents`, the payment cannot proceed under `CONVENIENCE_FEE` and
        is rejected with `ERR_FEE_EXCEEDS_STATUTORY_CAP`."

        Design: Difficulty/boundary_precision_check/statutory_cap_exact_allowed_over_rejected
        """
        ctx = setup_cf_checkout()
        svc_b = _add_cf_service(ctx["agency"]["id"], "DL-RENEW-B", "4111", fee_cap_cents=2280)
        resp = api_client.create_fee_quote(
            {"service_id": svc_b["id"], "amount_cents": 100000, "method": "CARD"},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FEE_EXCEEDS_STATUTORY_CAP)
        listed, meta = validate_paginated(
            api_client.list_fee_quotes(PA, params={"service_id": svc_b["id"]})
        )
        assert listed == [], "the rejected quote must not persist a record clamped to the cap"


class TestEcheckFlatFee:
    def test_echeck_quote_flat_fee_exact(self, api):
        """PRD §3.4: "For `ECHECK` there is no gross-up: the raw fee is the
        flat 150 cents."

        Design: Corner/calculations/echeck_quote_flat_fee_exact
        """
        ctx = setup_cf_checkout(with_echeck=True)
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 50000, "ECHECK")
        assert quote["quoted_fee_cents"] == 150
        assert quote["payer_total_cents"] == 50150
        txn = authorize(quote["id"], ctx["echeck"]["id"], ctx["payer"]["id"])
        assert_transaction(txn)
        assert txn["charged_fee_cents"] == 150
        assert txn["final_fee_cents"] == 150, "QUOTED == FINAL for non-card methods"
        assert txn["payer_total_cents"] == 50150


class TestFeeQuoteShape:
    def test_fee_quote_carries_no_version_field(self, api):
        """PRD §2.5: "Four resource kinds are the exception:
        `ContractPricingTier`, `ComplianceAttestation`, `FeeQuote` and
        `SelfFundingLedgerEntry` carry only `id` and `created_at`, and both
        `updated_at` and `version` are absent from them."
        PRD §3.4: "expires_at` is the quote's `created_at` plus 30 minutes".

        Design: Corner/entities/feequote_carries_no_version_field_immutable
        """
        ctx = setup_open_card_quote()
        quote = get_quote(ctx["quote"]["id"], ctx["payer"]["id"])
        assert_fee_quote(quote)  # also requires version/updated_at to be absent
        assert "version" not in quote
        assert "updated_at" not in quote
        assert quote["status"] == "OPEN"
        assert _parse(quote["expires_at"]) - _parse(quote["created_at"]) == timedelta(minutes=30)


class TestQuoteGates:
    def test_amount_below_service_minimum_rejected(self, api):
        """PRD §3.4: "the amount must lie within the service's inclusive
        bounds from `min_amount_cents` through `max_amount_cents` — otherwise
        `ERR_AMOUNT_OUT_OF_RANGE`".

        Design: Corner/errors/err_amount_out_of_range
        """
        ctx = setup_cf_checkout()
        resp = api_client.create_fee_quote(
            {"service_id": ctx["service"]["id"], "amount_cents": 99, "method": "CARD"},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AMOUNT_OUT_OF_RANGE)
        # The bounds are inclusive: amount == min_amount_cents passes the range check.
        quote = create_quote(ctx["service"]["id"], ctx["payer"]["id"], 100, "CARD")
        assert quote["quoted_fee_cents"] == 100, "floor-priced small quote proves the range check passed"

    def test_quote_method_outside_allowed_methods_rejected(self, api):
        """PRD §3.4: "the method must be a member of the service's
        `allowed_methods` — otherwise `ERR_METHOD_NOT_ALLOWED`".

        Design: Corner/errors/err_method_not_allowed_on_quote
        """
        ctx = setup_cf_checkout()
        svc_card = create_service(
            ctx["agency"]["id"],
            service_code="CARD-ONLY",
            name="Card Only Counter Fee",
            fee_model="CONVENIENCE_FEE",
            allowed_methods=["CARD"],
            min_amount_cents=100,
            max_amount_cents=100000,
            gl_code="4131",
        )
        create_approved_authorization(svc_card["id"], fee_cap_cents=5000)
        svc_card = activate_service(svc_card["id"])
        resp = api_client.create_fee_quote(
            {"service_id": svc_card["id"], "amount_cents": 10000, "method": "ECHECK"},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_METHOD_NOT_ALLOWED)
        listed, _ = validate_paginated(
            api_client.list_fee_quotes(PA, params={"service_id": svc_card["id"]})
        )
        assert listed == []

    def test_authorize_at_exact_quote_expiry_rejected(self, api):
        """PRD §3.4: "authorization attempted at a logical clock equal to or
        later than `expires_at` fails with `ERR_QUOTE_EXPIRED`."

        Design: Corner/errors/err_quote_expired_at_exact_expiry
        """
        ctx = setup_open_card_quote()  # created at 2026-09-01T00:00:00Z
        set_clock("2026-09-01T00:30:00Z")  # exactly created_at + 30 minutes
        resp = api_client.authorize_payment(
            {"quote_id": ctx["quote"]["id"], "instrument_id": ctx["card"]["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_QUOTE_EXPIRED)
        # clock >= expires_at is expired: created_at 00:00 plus 30 minutes is exactly 00:30
        assert _parse(ctx["quote"]["expires_at"]) - _parse(ctx["quote"]["created_at"]) == timedelta(minutes=30)

    def test_authorize_after_repricing_rejected_stale_service_version(self, api):
        """PRD §3.4: "the service's current `version` must still equal the
        quote's `service_version_pinned` — a repriced service rejects
        authorization with `ERR_STALE_SERVICE_VERSION`."

        Design: Corner/errors/err_stale_service_version_on_authorize
        """
        ctx = setup_open_card_quote()
        assert ctx["quote"]["service_version_pinned"] == 2
        updated = update_service(
            ctx["service"]["id"],
            expected_service_version=ctx["service"]["version"],
            max_amount_cents=900000,
        )
        assert updated["version"] == 3
        resp = api_client.authorize_payment(
            {"quote_id": ctx["quote"]["id"], "instrument_id": ctx["card"]["id"]},
            make_payer_headers(ctx["payer"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SERVICE_VERSION)
        quote_after = get_quote(ctx["quote"]["id"], ctx["payer"]["id"])
        assert quote_after["status"] == "OPEN"
        assert quote_after["service_version_pinned"] == 2
