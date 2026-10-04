"""Closing cascade, management-referral onboarding fee, and lease continuity."""
import pytest

from test_helpers import (
    DEFAULT_CLOCK_ISO,
    PLATFORM_ADMIN_HEADERS,
    get_success_data,
    make_buyer_headers,
    make_seller_headers,
    set_clock,
    setup_closed_sale,
)


class TestClosingCascade:
    def test_close_moves_listing_lease_referral_and_guarantee(self, api):
        """PRD §3.7: "Closing (`FUNDED` → `CLOSED`) is the `EscrowOfficer`'s
        action and fires the sale cascade: the listing moves from
        `UNDER_CONTRACT` to `SOLD`; the listing's `ACTIVE` lease moves to
        `ASSIGNED`, continuing the tenancy to the buyer, and the onboarding
        referral for the listing has its `lease_continuity_confirmed` set to
        true once that assignment lands; any management referral on the listing
        in `REFERRED` or `ACCEPTED` moves to `ONBOARDED` with its onboarding fee
        computed (§3.8); any guarantee on the listing in `ISSUED` moves to
        `ACTIVE`; and the seller's `listed_count` and `bulk_discount_bps` are
        recomputed."

        Design: Difficulty/transitive_cascade/closing_cascade_depth4
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True,
            with_referral=True,
            guarantee={"guarantee_kind": "VACANCY", "coverage_months": 3},
            pm_overrides={"onboarding_fee_bps": 200},
            lease_overrides={"monthly_rent_cents": 100_000},
            offer_overrides={"amount_cents": 15_000_000},
        )
        assert ctx["listing"]["status"] == "SOLD"
        seller_h = make_seller_headers(ctx["seller"]["id"])
        lease = get_success_data(api.get_lease(ctx["lease"]["id"], seller_h))
        assert lease["status"] == "ASSIGNED"
        referral = get_success_data(
            api.get_management_referral(ctx["referral"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert referral["status"] == "ONBOARDED"
        assert referral["lease_continuity_confirmed"] is True
        guarantees = get_success_data(
            api.list_guarantees(ctx["listing"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert guarantees[0]["status"] == "ACTIVE"

    def test_close_computes_onboarding_fee_from_scheduled_rent(self, api):
        """PRD §3.8: "Scheduled annual rent is that lease's `monthly_rent_cents`
        multiplied by 12, or zero if no such lease exists. The fee is then the
        scheduled annual rent multiplied by the property manager's
        `onboarding_fee_bps` and divided by 10000, floored to integer cents."

        Design: Difficulty/transitive_cascade/closing_cascade_depth4
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True,
            with_referral=True,
            pm_overrides={"onboarding_fee_bps": 200},
            lease_overrides={"monthly_rent_cents": 100_000},
            offer_overrides={"amount_cents": 15_000_000},
        )
        referral = get_success_data(
            api.get_management_referral(ctx["referral"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        # floor(100000 * 12 * 200 / 10000) = 24000
        assert referral["onboarding_fee_cents"] == 24_000


class TestOnboardingFeePinnedOrder:
    def test_fee_derives_from_lease_rent_and_pm_basis(self, api):
        """PRD §3.8: "Scheduled annual rent is that lease's `monthly_rent_cents`
        multiplied by 12, or zero if no such lease exists. The fee is then the
        scheduled annual rent multiplied by the property manager's
        `onboarding_fee_bps` and divided by 10000, floored to integer cents."

        Design: Difficulty/combinatorial_formula/pm_onboarding_fee_circular_order_pinned
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True,
            with_referral=True,
            pm_overrides={"onboarding_fee_bps": 150},
            lease_overrides={"monthly_rent_cents": 125_000},
            offer_overrides={"amount_cents": 20_000_000},
        )
        referral = get_success_data(
            api.get_management_referral(ctx["referral"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert referral["status"] == "ONBOARDED"
        # floor(125000 * 12 * 150 / 10000) = 22500
        assert referral["onboarding_fee_cents"] == 22_500

    def test_fee_does_not_feed_back_into_lease_or_offer(self, api):
        """PRD §3.8: "The fee is derived from lease rent and the manager's fee
        basis only; it never feeds back into the lease, the offer, or the
        listing price."

        Design: Difficulty/combinatorial_formula/pm_onboarding_fee_circular_order_pinned
        """
        set_clock(DEFAULT_CLOCK_ISO)
        ctx = setup_closed_sale(
            with_lease=True,
            with_referral=True,
            pm_overrides={"onboarding_fee_bps": 150},
            lease_overrides={"monthly_rent_cents": 125_000},
            offer_overrides={"amount_cents": 20_000_000},
        )
        seller_h = make_seller_headers(ctx["seller"]["id"])
        buyer_h = make_buyer_headers(ctx["buyer"]["id"])
        lease = get_success_data(api.get_lease(ctx["lease"]["id"], seller_h))
        assert lease["monthly_rent_cents"] == 125_000
        assert lease["status"] == "ASSIGNED"
        offer = get_success_data(api.get_offer(ctx["offer"]["id"], buyer_h))
        assert offer["amount_cents"] == 20_000_000
        listing = get_success_data(api.get_listing(ctx["listing"]["id"], seller_h))
        assert listing["asking_price_cents"] == 10_000_000
        referral = get_success_data(
            api.get_management_referral(ctx["referral"]["id"], PLATFORM_ADMIN_HEADERS)
        )
        assert referral["lease_continuity_confirmed"] is True
