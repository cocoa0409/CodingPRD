"""Interchange rate qualification, scope preference, fallback, and quoting."""
from test_helpers import (
    ApiErrorId,
    create_interchange_rate_payload,
    create_published_rate,
    get_success_data,
    set_clock,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

PA = TEST_USERS["pricing_analyst_headers"]


def _publish(api, **kwargs):
    return create_published_rate(**kwargs)


class TestQuoteQualificationFallback:
    def _setup_rate_table(self, api):
        """GLOBAL/STANDARD 400bp+50c (eff 09-01), EU/STANDARD 500bp+100c
        (eff 09-02), EU/ENHANCED 700bp+120c (eff 09-03); clock at 09-10."""
        r_gs = _publish(api, merchant_category="5411",
                        transaction_type="CARD_NOT_PRESENT",
                        data_quality_tier="STANDARD", rate_basis_points=400,
                        fixed_fee_cents=50, region_scope="GLOBAL",
                        effective_from="2026-09-01T00:00:00Z")
        r_es = _publish(api, merchant_category="5411",
                        transaction_type="CARD_NOT_PRESENT",
                        data_quality_tier="STANDARD", rate_basis_points=500,
                        fixed_fee_cents=100, region_scope="EU",
                        effective_from="2026-09-02T00:00:00Z")
        r_ee = _publish(api, merchant_category="5411",
                        transaction_type="CARD_NOT_PRESENT",
                        data_quality_tier="ENHANCED", rate_basis_points=700,
                        fixed_fee_cents=120, region_scope="EU",
                        effective_from="2026-09-03T00:00:00Z")
        set_clock("2026-09-10T00:00:00Z")
        return r_gs, r_es, r_ee

    def test_quote_premium_qualified_eu_falls_back_to_regional_enhanced(self, api):
        """PRD §3.7: "Data quality qualification is derived, not declared: a
        request supplying both `token` and `avs_match` qualifies for
        `PREMIUM`; one supplying `avs_match` alone qualifies for `ENHANCED`;
        anything else qualifies for `STANDARD`."
        PRD §3.7: "Within the candidate set, a row scoped to the request's
        region is preferred over a `GLOBAL` row; among remaining ties the row
        with the latest `effective_from` wins".
        PRD §3.7: "When no row matches the qualified tier, the lookup falls
        back downward tier by tier — `PREMIUM` to `ENHANCED` to `STANDARD`".

        Design: Difficulty/combinatorial_formula/interchange_quote_qualification_scope_fallback
        """
        _, _, r_ee = self._setup_rate_table(api)
        res = api.quote_interchange(
            {"mcc": "5411", "transaction_type": "CARD_NOT_PRESENT",
             "region": "EU", "amount_cents": 100000, "token": "tok_1",
             "avs_match": True}, PA)
        data = validate_success(res)
        assert data["qualified_tier"] == "ENHANCED", \
            "the response reports the qualified_tier actually used: no PREMIUM row exists, so the fallback lands on the EU ENHANCED row"
        assert data["fee_cents"] == 7120, \
            "PREMIUM-qualified EU quote falls back to the EU ENHANCED row: 100000*700/10000 + 120"
        assert data["applied_rate_id"] == r_ee["id"]
        assert data["rate_basis_points"] == 700

    def test_quote_tokenless_eu_selects_regional_standard(self, api):
        """PRD §3.7: "anything else qualifies for `STANDARD`."
        PRD §3.7: "Within the candidate set, a row scoped to the request's
        region is preferred over a `GLOBAL` row".

        Design: Difficulty/combinatorial_formula/interchange_quote_qualification_scope_fallback
        """
        self._setup_rate_table(api)
        res = api.quote_interchange(
            {"mcc": "5411", "transaction_type": "CARD_NOT_PRESENT",
             "region": "EU", "amount_cents": 100000}, PA)
        data = validate_success(res)
        assert data["qualified_tier"] == "STANDARD"
        assert data["fee_cents"] == 5100, \
            "the EU STANDARD row wins over GLOBAL: 100000*500/10000 + 100"

    def test_quote_premium_qualified_na_falls_back_to_global_standard(self, api):
        """PRD §3.7: "When no row matches the qualified tier, the lookup falls
        back downward tier by tier — `PREMIUM` to `ENHANCED` to `STANDARD` —
        and if no row matches at any tier, the quote is rejected with
        `ERR_RATE_NOT_FOUND`."

        Design: Difficulty/combinatorial_formula/interchange_quote_qualification_scope_fallback
        """
        self._setup_rate_table(api)
        res = api.quote_interchange(
            {"mcc": "5411", "transaction_type": "CARD_NOT_PRESENT",
             "region": "NA", "amount_cents": 100000, "token": "tok_1",
             "avs_match": True}, PA)
        data = validate_success(res)
        assert data["qualified_tier"] == "STANDARD", \
            "the response reports the qualified_tier actually used: fallback lands on the GLOBAL STANDARD row"
        assert data["fee_cents"] == 4050, \
            "no NA-scoped row exists, so the GLOBAL STANDARD row applies: 100000*400/10000 + 50"


class TestQuotePrecisionAndVariants:
    def test_interchange_fee_floor_precision(self, api):
        """PRD §3.7: "The fee itself is the `amount_cents` multiplied by the
        winning row's `rate_basis_points`, divided by ten thousand, with the
        fractional remainder discarded, then increased by the row's
        `fixed_fee_cents`."
        PRD §2.9: "Interchange fee computation truncates the percentage
        component to a whole cent — the amount in cents multiplied by the rate
        in basis points, divided by ten thousand, with the fractional
        remainder discarded — and only then adds the fixed fee".

        Design: Corner/calculations/interchange_fee_floor_precision
        """
        _publish(api, merchant_category="5999", transaction_type="CARD_PRESENT",
                 data_quality_tier="STANDARD", rate_basis_points=150,
                 fixed_fee_cents=10, region_scope="GLOBAL",
                 effective_from="2026-09-01T00:00:00Z")
        res = api.quote_interchange(
            {"mcc": "5999", "transaction_type": "CARD_PRESENT", "region": "NA",
             "amount_cents": 333}, PA)
        data = validate_success(res)
        # floor(333 * 150 / 10000) = floor(4.995) = 4, plus fixed 10 = 14.
        assert data["fee_cents"] == 14

    def test_interchange_as_of_replays_earlier_rate(self, api):
        """PRD §3.7: "Supplying `as_of` replays which rate row was effective
        at that past timestamp — selection runs on rows whose `effective_from`
        is at or before `as_of` — whereas omitting it evaluates against the
        current logical time; the two modes can select different rows and
        produce different fees for otherwise identical payloads."

        Design: Corner/calculations/interchange_as_of_replays_earlier_rate
        """
        r1 = _publish(api, merchant_category="5411",
                      transaction_type="ECOM_TOKENIZED",
                      data_quality_tier="STANDARD", rate_basis_points=100,
                      fixed_fee_cents=50, region_scope="GLOBAL",
                      effective_from="2026-09-01T00:00:00Z")
        r2 = _publish(api, merchant_category="5411",
                      transaction_type="ECOM_TOKENIZED",
                      data_quality_tier="STANDARD", rate_basis_points=200,
                      fixed_fee_cents=50, region_scope="GLOBAL",
                      effective_from="2026-09-10T00:00:00Z")
        set_clock("2026-09-15T00:00:00Z")

        res = api.quote_interchange(
            {"mcc": "5411", "transaction_type": "ECOM_TOKENIZED",
             "region": "NA", "amount_cents": 100000,
             "as_of": "2026-09-05T00:00:00Z"}, PA)
        data = validate_success(res)
        assert data["fee_cents"] == 1050
        assert data["applied_rate_id"] == r1["id"]

        res = api.quote_interchange(
            {"mcc": "5411", "transaction_type": "ECOM_TOKENIZED",
             "region": "NA", "amount_cents": 100000}, PA)
        data = validate_success(res)
        assert data["fee_cents"] == 2050
        assert data["applied_rate_id"] == r2["id"]

    def test_quote_rate_not_found_when_no_tier_matches(self, api):
        """PRD §3.7: "When no row matches the qualified tier, the lookup falls
        back downward tier by tier — `PREMIUM` to `ENHANCED` to `STANDARD` —
        and if no row matches at any tier, the quote is rejected with
        `ERR_RATE_NOT_FOUND`."

        Design: Corner/endpoints/quote_rate_not_found_when_no_tier_matches
        """
        # Only a DRAFT rate exists for this mcc — nothing published.
        api.create_interchange_rate(
            create_interchange_rate_payload(merchant_category="0001",
                                            transaction_type="CARD_PRESENT"),
            PA)
        res = api.quote_interchange(
            {"mcc": "0001", "transaction_type": "CARD_PRESENT", "region": "NA",
             "amount_cents": 1000}, PA)
        validate_error(res, ApiErrorId.ERR_RATE_NOT_FOUND)
