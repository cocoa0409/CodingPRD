"""Depth tests for multi-factor formulas with pinned rounding order."""
from test_helpers import (
    api_client,
    create_buyer,
    create_published_workshop_item,
    create_regional_price_payload,
    create_released_title,
    create_user,
    create_workshop_sale_payload,
    get_success_data,
    make_developer_headers,
    make_user_headers,
    read_title,
    validate_success,
)


class TestRegionalPriceMultifactor:
    def _setup_with_eur_override(self, base_price_usd_cents=6000, override_cents=4000):
        developer, title = create_released_title(base_price_usd_cents=base_price_usd_cents)
        dev_headers = make_developer_headers(developer["id"])
        version = read_title(title["id"], developer)["version"]
        get_success_data(
            api_client.create_regional_price(
                create_regional_price_payload(title["id"], "EUR", override_cents, version),
                dev_headers,
            )
        )
        return developer, title, dev_headers

    def test_effective_price_prefers_active_override_over_recommendation(self):
        """PRD §3.3: "For a purchase in another currency, an `ACTIVE` override
        for that title and currency wins; otherwise the recommended price is
        charged."

        Design: Difficulty/combinatorial_formula/regional_price_multifactor_branch
        """
        developer, title, dev_headers = self._setup_with_eur_override()

        data = validate_success(
            api_client.get_pricing_recommendation(
                title["id"], dev_headers, params={"currency": "EUR"}
            )
        )
        # recommended = round_half_up(6000 * 0.92 * 0.90) = 4968
        assert data["recommended_cents"] == 4968
        assert data["effective_cents"] == 4000
        # usd_recognized_per_unit = round_half_up(4000 / 0.92) = 4348
        assert data["usd_recognized_per_unit"] == 4348

    def test_recommendation_without_override_is_fx_times_ppp(self):
        """PRD §3.3: "The recommended price for a currency is the base USD price
        multiplied by that currency's FX rate and then by its purchasing-power
        multiplier, rounded half-up to integer minor units."

        Design: Difficulty/combinatorial_formula/regional_price_multifactor_branch
        """
        developer, title = create_released_title(base_price_usd_cents=6000)
        dev_headers = make_developer_headers(developer["id"])

        data = validate_success(
            api_client.get_pricing_recommendation(
                title["id"], dev_headers, params={"currency": "EUR"}
            )
        )
        assert data["recommended_cents"] == 4968
        assert data["effective_cents"] == 4968  # no override -> recommendation is charged
        # usd_recognized_per_unit = round_half_up(4968 / 0.92) = 5400
        assert data["usd_recognized_per_unit"] == 5400


class TestWorkshopShareNestedRounding:
    def _sale(self, price_cents, creator_share_bps):
        developer, title = create_released_title()
        creator = create_user()
        buyer = create_buyer()
        item = create_published_workshop_item(
            title, creator, price_cents=price_cents, creator_share_bps=creator_share_bps
        )
        return get_success_data(
            api_client.create_workshop_sale(
                create_workshop_sale_payload(item["id"], buyer["id"]),
                make_user_headers(buyer["id"]),
            )
        )

    def test_creator_share_floored_first_999_at_3333_bps(self):
        """PRD §3.8: "The split rounds in a pinned order: the creator's share is
        computed first as the floor of the gross multiplied by the creator's
        basis points and divided by ten thousand, and the platform's share is
        whatever remains — so on a 999-cent item at 3333 basis points the creator
        receives 332 cents and the platform 667, never the other way around."

        Design: Difficulty/combinatorial_formula/workshop_share_nested_rounding_order
        """
        sale = self._sale(999, 3333)
        assert sale["gross_cents"] == 999
        assert sale["creator_share_cents"] == 332  # floor(999 * 3333 / 10000)
        assert sale["platform_share_cents"] == 667

    def test_creator_share_floored_first_100_at_3333_bps(self):
        """PRD §2.8: "Wherever a computation produces a fractional minor unit,
        the result is rounded half-up to the nearest integer unless a rule
        explicitly says otherwise; the workshop creator split is the one place
        a floor is used instead".

        Design: Difficulty/combinatorial_formula/workshop_share_nested_rounding_order
        """
        sale = self._sale(100, 3333)
        # floor(100 * 3333 / 10000) = floor(33.33) = 33; platform takes the remainder.
        # Reversed order would give the creator 34.
        assert sale["creator_share_cents"] == 33
        assert sale["platform_share_cents"] == 67
        assert sale["creator_share_cents"] + sale["platform_share_cents"] == 100
