"""Membership pricing constants and the two cancellation refund variants."""
from test_helpers import (
    api_client, validate_success, ApiErrorId, TEST_USERS,
    create_household_payload, set_clock, create_household_with_term,
    cancel_term_ok, get_household,
)

MSA = TEST_USERS["member_services_headers"]


def _two_three_year_households():
    """Households A and B with identical 3-year terms bought at the clock
    start (paid 4,320), then the clock advanced to 2026-11-15 so
    months_used == 3 for both."""
    set_clock()
    hh_a, term_a, _ = create_household_with_term(
        state_code="TX", term_years=3, primary_full_name="Ann Archer",
        primary_date_of_birth="1970-04-15")
    hh_b, term_b, _ = create_household_with_term(
        state_code="TX", term_years=3, primary_full_name="Bob Baker",
        primary_date_of_birth="1968-02-20")
    assert term_a["paid_cents"] == 4320
    assert term_b["paid_cents"] == 4320
    set_clock("2026-11-15T00:00:00Z")
    return hh_a, term_a, hh_b, term_b


def _two_one_year_households():
    """Households C and D with identical 1-year terms bought at the clock
    start (paid 1,600), clock advanced to 2026-11-15 (months_used == 3)."""
    set_clock()
    hh_c, term_c, _ = create_household_with_term(
        state_code="FL", term_years=1, primary_full_name="Eve Ellis",
        primary_date_of_birth="1960-01-30")
    hh_d, term_d, _ = create_household_with_term(
        state_code="FL", term_years=1, primary_full_name="Fred Fox",
        primary_date_of_birth="1958-05-12")
    assert term_c["paid_cents"] == 1600
    assert term_d["paid_cents"] == 1600
    set_clock("2026-11-15T00:00:00Z")
    return hh_c, term_c, hh_d, term_d


class TestRefundVariantDivergence:
    def test_voluntary_short_rate_clawback(self, api):
        """PRD §3.2: "Under `VOLUNTARY`, a short-rate clawback applies: the
        refund is the greater of zero and `paid_cents` minus `months_used`
        times 133 cents, where 133 is the undiscounted monthly basis — the
        base annual dues of 1,600 cents divided by twelve and rounded half up
        — so the multi-year discount is clawed back."

        Design: Difficulty/dual_variant_calc/refund_short_rate_vs_pro_rata_divergence
        """
        hh_a, term_a, _hh_b, _term_b = _two_three_year_households()
        resp = api.cancel_term(term_a["id"], {"reason": "VOLUNTARY"}, MSA)
        term = validate_success(resp)
        # months_used = 3 -> 4320 - 3*133 = 3921.
        assert term["status"] == "CANCELLED"
        assert term["refunded_cents"] == 3921
        assert get_household(hh_a["id"])["lifetime_refunded_cents"] == 3921

    def test_deceased_pro_rata_preserves_discount(self, api):
        """PRD §3.2: "Under `DECEASED`, the estate keeps the discount: the
        effective monthly rate is `paid_cents` divided by the term's total
        months and rounded half up, and the refund is the lesser of
        `paid_cents` and the remaining months multiplied by that rate."

        Design: Difficulty/dual_variant_calc/refund_short_rate_vs_pro_rata_divergence
        """
        hh_a, term_a, hh_b, term_b = _two_three_year_households()
        refund_a = cancel_term_ok(term_a["id"], "VOLUNTARY")["refunded_cents"]
        resp_b = api.cancel_term(term_b["id"], {"reason": "DECEASED"}, MSA)
        term_b_after = validate_success(resp_b)
        # effective monthly = round_half_up(4320/36) = 120; (36-3)*120 = 3960.
        assert term_b_after["refunded_cents"] == 3960
        # Identical terms, identical clock: the variants diverge by 39 cents.
        assert refund_a == 3921
        assert term_b_after["refunded_cents"] - refund_a == 39
        assert get_household(hh_b["id"])["lifetime_refunded_cents"] == 3960


class TestRefundRoundingOrderPinned:
    def test_deceased_one_year_refund_rounds_basis_first(self, api):
        """PRD §3.2: "A one-year term purchased at 1,600 cents and cancelled
        as `DECEASED` in its third calendar month, for example, refunds nine
        months at 133 cents — 1,197 cents — not the 1,200 cents that rounding
        only the final product would yield."

        Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned
        """
        _hh_c, term_c, _hh_d, _term_d = _two_one_year_households()
        resp = api.cancel_term(term_c["id"], {"reason": "DECEASED"}, MSA)
        term = validate_success(resp)
        assert term["refunded_cents"] == 1197

    def test_voluntary_one_year_refund_and_inversion(self, api):
        """PRD §3.2: "The rounding order is pinned in both variants — the
        per-month basis is rounded half up first and only then multiplied by
        whole months." PRD §3.2: "Under `VOLUNTARY`, a short-rate clawback
        applies: the refund is the greater of zero and `paid_cents` minus
        `months_used` times 133 cents".

        Design: Difficulty/combinatorial_formula/refund_rounding_order_pinned
        """
        _hh_c, term_c, _hh_d, term_d = _two_one_year_households()
        refund_c = cancel_term_ok(term_c["id"], "DECEASED")["refunded_cents"]
        resp_d = api.cancel_term(term_d["id"], {"reason": "VOLUNTARY"}, MSA)
        refund_d = validate_success(resp_d)["refunded_cents"]
        # 1600 - 3*133 = 1201; the pinned rounding order inverts the naive
        # variant ordering on identical 1-year terms (1197 < 1201).
        assert refund_d == 1201
        assert refund_c == 1197
        assert refund_c < refund_d


class TestInitialTermPricingConstants:
    def test_initial_purchase_prices_one_three_five_years(self, api):
        """PRD §3.1: "Annual base dues are 1,600 cents (sixteen dollars) per
        year." PRD §3.1: "Multi-year terms earn a discount of 0% for one year,
        10% for three years, or 20% for five years; a term created by the
        renewal batch adds a further 5 percentage points of loyalty discount."
        PRD §3.1: "A five-year initial purchase therefore costs 6,400 cents,
        and a five-year renewal costs 6,000 cents."

        Design: Corner/calculations/initial_term_pricing_constants
        """
        set_clock()
        hh_1, term_1, _ = create_household_with_term(
            state_code="IA", term_years=1, primary_full_name="Meg May",
            primary_date_of_birth="1970-01-01")
        hh_3, term_3, _ = create_household_with_term(
            state_code="IA", term_years=3, primary_full_name="Ned Nye",
            primary_date_of_birth="1970-01-01")
        hh_5, term_5, _ = create_household_with_term(
            state_code="IA", term_years=5, primary_full_name="Opal Orr",
            primary_date_of_birth="1970-01-01")
        assert term_1["paid_cents"] == 1600
        assert term_3["paid_cents"] == 4320
        assert term_5["paid_cents"] == 6400
        assert get_household(hh_5["id"])["lifetime_collected_cents"] == 6400
