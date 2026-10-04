"""Underwriting projection tests: dual variants, rounding order, yield basis."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_listing_payload,
    create_underwriting_report_payload,
    get_success_data,
    make_buyer_headers,
    make_seller_headers,
    setup_buyer,
    setup_draft_listing,
    setup_seller,
    validate_success,
)


class TestUnderwritingNoiVariants:
    def test_base_variant_noi_on_non_confidential_listing(self, api):
        """PRD §3.5: "Under the BASE variant (the listing is not confidential):
        gross scheduled rent is `rent_estimate_cents` multiplied by 12; the vacancy
        allowance is gross multiplied by `vacancy_rate_bps` and divided by 10000,
        floored to integer cents; the operating-expense allowance is the
        post-vacancy remainder (gross minus the vacancy allowance) multiplied by
        `opex_rate_bps` and divided by 10000, floored to integer cents; and
        `projected_noi_cents` is gross minus the vacancy allowance minus the
        operating-expense allowance."

        Design: Difficulty/dual_variant_calc/underwriting_noi_base_vs_redacted_variant
        """
        seller = setup_seller()
        buyer = setup_buyer(buyer_state="CA")
        listing = setup_draft_listing(
            seller, address_line="1 Oak St", asking_price_cents=24_000_000,
            seller_asks_confidential=False,
        )
        resp = api.create_underwriting_report(
            listing["id"],
            create_underwriting_report_payload(
                buyer["id"], rent_estimate_cents=200_000, vacancy_rate_bps=500, opex_rate_bps=4000
            ),
            make_buyer_headers(buyer["id"]),
        )
        report = validate_success(resp, expected_status=201)
        # gross=2400000; vac=floor(2400000*0.05)=120000; opex=floor(2280000*0.4)=912000
        assert report["disclosure_limited"] is False
        assert report["projected_noi_cents"] == 1_368_000

    def test_redacted_variant_noi_on_confidential_listing(self, api):
        """PRD §3.5: "Under the REDACTED variant (the listing is confidential, so
        tenant history is withheld and a vacancy risk uplift applies): the vacancy
        line instead multiplies gross by the sum of `vacancy_rate_bps` and a
        300-basis-point uplift, divided by 10000 and floored, before the same
        operating-expense and subtraction steps follow on that higher vacancy base."

        Design: Difficulty/dual_variant_calc/underwriting_noi_base_vs_redacted_variant
        """
        seller = setup_seller()
        buyer = setup_buyer(buyer_state="CA")
        listing = setup_draft_listing(
            seller, address_line="2 Pine St", asking_price_cents=24_000_000,
            seller_asks_confidential=True,
        )
        resp = api.create_underwriting_report(
            listing["id"],
            create_underwriting_report_payload(
                buyer["id"], rent_estimate_cents=200_000, vacancy_rate_bps=500, opex_rate_bps=4000
            ),
            make_buyer_headers(buyer["id"]),
        )
        report = validate_success(resp, expected_status=201)
        # vac=floor(2400000*0.08)=192000; opex=floor(2208000*0.4)=883200
        assert report["disclosure_limited"] is True
        assert report["projected_noi_cents"] == 1_324_800


class TestNoiNestedRoundingOrder:
    def test_noi_rounding_order_floors_per_line(self, api):
        """PRD §3.5: "The rounding order is pinned in both variants — floor
        vacancy first, floor operating expense on the post-vacancy base second,
        subtract last — and flooring only the final total is forbidden because
        it produces different cents."

        Design: Difficulty/combinatorial_formula/projected_noi_nested_rounding_order
        """
        seller = setup_seller()
        buyer = setup_buyer()
        listing = setup_draft_listing(
            seller, address_line="3 Elm St", asking_price_cents=24_000_000,
            seller_asks_confidential=False,
        )
        resp = api.create_underwriting_report(
            listing["id"],
            create_underwriting_report_payload(
                buyer["id"], rent_estimate_cents=199_999, vacancy_rate_bps=333, opex_rate_bps=3333
            ),
            make_buyer_headers(buyer["id"]),
        )
        report = validate_success(resp, expected_status=201)
        # gross=2399988; vac=floor(2399988*333/10000)=79919; opex=floor(2320069*3333/10000)=773278
        assert report["projected_noi_cents"] == 1_546_791

    def test_yield_after_noi_on_single_price_basis(self, api):
        """PRD §3.5: "The yield is `projected_noi_cents` multiplied by 10000 and
        divided by the price basis, floored to integer basis points."

        Design: Difficulty/combinatorial_formula/projected_noi_nested_rounding_order
        """
        seller = setup_seller()
        buyer = setup_buyer()
        listing = setup_draft_listing(
            seller, address_line="3 Elm St", asking_price_cents=24_000_000,
            seller_asks_confidential=False,
        )
        resp = api.create_underwriting_report(
            listing["id"],
            create_underwriting_report_payload(
                buyer["id"], rent_estimate_cents=199_999, vacancy_rate_bps=333, opex_rate_bps=3333
            ),
            make_buyer_headers(buyer["id"]),
        )
        report = validate_success(resp, expected_status=201)
        # floor(1546791*10000/24000000) = floor(644.496...) = 644
        assert report["projected_noi_cents"] == 1_546_791
        assert report["projected_yield_bps"] == 644


class TestPortfolioYieldBasis:
    def test_portfolio_yield_uses_bulk_price_basis(self, api):
        """PRD §3.5: "Projected yield, `projected_yield_bps`, is then computed
        against a price basis: the listing's `asking_price_cents` when
        `listing_kind` is `SINGLE`, or the listing's `bulk_price_cents` when
        `listing_kind` is `PORTFOLIO`."

        Design: Corner/calculations/projected_yield_uses_portfolio_bulk_basis
        """
        seller = setup_seller()
        buyer = setup_buyer()
        listing = setup_draft_listing(
            seller,
            address_line="20 Portfolio Pkwy",
            asking_price_cents=50_000_000,
            listing_kind="PORTFOLIO",
            bulk_price_cents=40_000_000,
            seller_asks_confidential=False,
        )
        resp = api.create_underwriting_report(
            listing["id"],
            create_underwriting_report_payload(
                buyer["id"], rent_estimate_cents=200_000, vacancy_rate_bps=500, opex_rate_bps=4000
            ),
            make_buyer_headers(buyer["id"]),
        )
        report = validate_success(resp, expected_status=201)
        assert report["projected_noi_cents"] == 1_368_000
        # floor(1368000*10000/40000000) = 342, NOT 228 (the asking-price basis)
        assert report["projected_yield_bps"] == 342
