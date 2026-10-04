"""Wing-prep forecasting and wing-price quoting (depth: dual-variant and
combinatorial formulas, quantity-tier boundary)."""

import pytest

from test_helpers import (
    HOST_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
    add_order_line,
    create_event,
    create_guest,
    create_open_check,
    create_promo_rule,
    create_venue,
    event_payload,
    get_success_data,
    promo_rule_payload,
    validate_success,
    wing_quote_payload,
)


class TestWingPrepForecastOverlayVsBase:
    """48-hour wing-prep forecast with and without an overlay event."""

    def _setup_three_base_events(self, api):
        venue = create_venue()
        event_b1 = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Bills vs Jets",
            expected_attendance=9000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        event_b2 = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Sunday Night",
            expected_attendance=12000,
            scheduled_start="2026-09-14T01:00:00Z",
            scheduled_end="2026-09-14T04:00:00Z",
        )
        event_b3 = create_event(
            kind="BASE",
            league="MLB",
            title="Yankees",
            home_market_zip="10001",
            expected_attendance=3000,
            scheduled_start="2026-09-14T18:00:00Z",
            scheduled_end="2026-09-14T21:00:00Z",
        )
        return venue, event_b1, event_b2, event_b3

    def test_forecast_includes_overlay_lift_on_the_largest_overlapped_base_event(self, api):
        """PRD §3.1: "On top of the base, each `INGESTED` overlay event contributes an uplift: an overlay event carries a `lift_pct`, a fractional lift that applies only to overlays and is null otherwise, and the uplift is the overlapped base event's `expected_attendance` multiplied by that fraction."
        PRD §3.1: "Each wing eater consumes 15 pieces, so `required_pieces` is the floored wing-eater count times 15."

        Base events sum to 9000 + 12000 + 3000 = 24000; the overlay (lift 0.25)
        overlaps B1 and B2 and applies to B2 (the highest expected_attendance),
        adding 12000 * 0.25 = 3000. Gross 27000; floor(27000 * 0.70) = 18900
        dine-in; floor(18900 * 0.40) = 7560 wing eaters; 7560 * 15 = 113400
        pieces. Volatility at cost 180 is 0, so no shortage risk.

        Design: Difficulty/dual_variant_calc/wing_prep_forecast_overlay_vs_base
        """
        venue, _b1, _b2, _b3 = self._setup_three_base_events(api)
        create_event(
            kind="OVERLAY",
            league="ENTERTAINMENT",
            title="Halftime Show",
            expected_attendance=0,
            scheduled_start="2026-09-13T22:30:00Z",
            scheduled_end="2026-09-14T02:30:00Z",
            lift_pct=0.25,
        )

        forecast = validate_success(
            api.get_wing_prep_forecast(
                venue["id"], VENUE_MANAGER_HEADERS, date="2026-09-13"
            )
        )

        assert forecast["base_attendance"] == 24000
        assert forecast["overlay_attendance"] == 3000
        assert forecast["required_pieces"] == 113400
        assert forecast["shortage_risk"] is False

    def test_forecast_with_no_overlay_reports_base_only(self, api):
        """PRD §3.1: "The gross attendance is base plus overlay."
        PRD §3.1: "Each wing eater consumes 15 pieces, so `required_pieces` is the floored wing-eater count times 15."

        Without any overlay the gross equals the base 24000; floor(24000 *
        0.70) = 16800 dine-in; floor(16800 * 0.40) = 6720 wing eaters; 6720 *
        15 = 100800 pieces, with zero overlay attendance reported.

        Design: Difficulty/dual_variant_calc/wing_prep_forecast_overlay_vs_base
        """
        venue, _b1, _b2, _b3 = self._setup_three_base_events(api)

        forecast = validate_success(
            api.get_wing_prep_forecast(
                venue["id"], VENUE_MANAGER_HEADERS, date="2026-09-13"
            )
        )

        assert forecast["base_attendance"] == 24000
        assert forecast["overlay_attendance"] == 0
        assert forecast["required_pieces"] == 100800
        assert forecast["shortage_risk"] is False

    def test_forecast_reports_base_and_overlay_attendance_separately(self, api):
        """PRD §3.1: "The forecast response also reports `base_attendance` and `overlay_attendance` separately."

        With the overlay present the response must still expose both figures
        side by side rather than a single fused attendance number.

        Design: Difficulty/dual_variant_calc/wing_prep_forecast_overlay_vs_base
        """
        venue, _b1, _b2, _b3 = self._setup_three_base_events(api)
        create_event(
            kind="OVERLAY",
            league="ENTERTAINMENT",
            title="Halftime Show",
            expected_attendance=0,
            scheduled_start="2026-09-13T22:30:00Z",
            scheduled_end="2026-09-14T02:30:00Z",
            lift_pct=0.25,
        )

        forecast = validate_success(
            api.get_wing_prep_forecast(
                venue["id"], VENUE_MANAGER_HEADERS, date="2026-09-13"
            )
        )

        assert set(("base_attendance", "overlay_attendance")) <= set(forecast.keys())
        assert forecast["base_attendance"] + forecast["overlay_attendance"] == 27000


class TestWingQuotePromoTierSurcharge:
    """The quote combines promo selection, quantity tier, and surcharge."""

    def _setup_venue_guest_promo(self, api, promo_price_cents_per_10=900):
        venue = create_venue()
        guest = create_guest(venue["id"])
        create_promo_rule(
            day_of_week=6,
            wing_kind="TRADITIONAL",
            promo_price_cents_per_10=promo_price_cents_per_10,
            start_date="2026-09-01T00:00:00Z",
            end_date="2026-09-30T23:59:59Z",
        )
        return venue, guest

    def test_quote_with_promo_and_quantity_tier_but_no_surcharge(self, api):
        """PRD §3.5: "A matching promo replaces the base with the rule's `promo_price_cents_per_10` divided by 10 — every promo rule's `portion_size` is fixed at 10 wings per portion."
        PRD §3.5: "When the order is at least 50 pieces, a quantity-tier multiplier of 0.95 applies and `quantity_tier_applied` is true."

        60 pieces on a Sunday promo of 900 cents per 10 wings gives a per-wing
        price of 90 cents; round_half_up(90 * 60 * 0.95) = 5130... the quote
        chain is per-unit 90, times 60 pieces, times 0.95 = 5130. With no
        prior settled consumption the surcharge is inactive.

        Design: Difficulty/combinatorial_formula/wing_quote_promo_tier_surcharge_mode_a
        """
        venue, guest = self._setup_venue_guest_promo(api, promo_price_cents_per_10=900)

        quote = validate_success(
            api.quote_wing_price(
                venue["id"],
                wing_quote_payload(
                    guest_id=guest["id"],
                    wing_kind="TRADITIONAL",
                    pieces=60,
                    event_date="2026-09-13",
                ),
                SERVER_HEADERS,
            )
        )

        # promo 900/10 = 90 per wing; 90 * 60 * 0.95 = 5130
        assert quote["quote_cents"] == 5130
        assert quote["promo_applied"] is True
        assert quote["quantity_tier_applied"] is True
        assert quote["surcharge_applied"] is False

    def test_quote_without_promo_uses_the_150_cent_base(self, api):
        """PRD §3.5: "The base per-wing price is 150 cents, unless a promo rule matches."

        The same 60-piece order on a Wednesday — a weekday the Sunday promo
        does not cover — prices at round_half_up(150 * 60 * 0.95) = 8550 with
        `promo_applied` false.

        Design: Difficulty/combinatorial_formula/wing_quote_promo_tier_surcharge_mode_a
        """
        venue, guest = self._setup_venue_guest_promo(api, promo_price_cents_per_10=900)

        quote = validate_success(
            api.quote_wing_price(
                venue["id"],
                wing_quote_payload(
                    guest_id=guest["id"],
                    wing_kind="TRADITIONAL",
                    pieces=60,
                    event_date="2026-09-16",  # Wednesday: promo day_of_week=6 does not match
                ),
                SERVER_HEADERS,
            )
        )

        assert quote["quote_cents"] == 8550
        assert quote["promo_applied"] is False
        assert quote["quantity_tier_applied"] is True
        assert quote["surcharge_applied"] is False

    def test_quote_with_surcharge_after_high_prior_consumption(self, api):
        """PRD §3.5: "Separately, the system sums the pieces the guest ordered on settled checks at this venue over the prior 30 days; when that rolling total exceeds 5000 pieces, a surcharge multiplier of 1.10 applies and `surcharge_applied` is true."

        Eleven settled checks of 510 pieces each put the guest's rolling total
        at 5610 pieces; a 60-piece promo quote then carries the 1.10 surcharge:
        round_half_up(90 * 60 * 0.95 * 1.10) = 5643.

        Design: Difficulty/combinatorial_formula/wing_quote_promo_tier_surcharge_mode_a
        """
        venue, guest = self._setup_venue_guest_promo(api, promo_price_cents_per_10=900)
        # Accumulate 5610 settled pieces for this guest (each line: 51 portions
        # = 510 pieces at the 90-cent promo unit price).
        for _ in range(11):
            check = create_open_check(venue["id"], guest["id"])
            add_order_line(check["id"], kind="TRADITIONAL", portion_count=51)
            validate_success(api.settle_check(check["id"], SERVER_HEADERS))

        quote = validate_success(
            api.quote_wing_price(
                venue["id"],
                wing_quote_payload(
                    guest_id=guest["id"],
                    wing_kind="TRADITIONAL",
                    pieces=60,
                    event_date="2026-09-13",
                ),
                SERVER_HEADERS,
            )
        )

        assert quote["surcharge_applied"] is True
        assert quote["quote_cents"] == 5643


class TestWingQuoteQuantityTierBoundary:
    """The 50-piece quantity tier flips exactly at the threshold."""

    def test_forty_nine_pieces_pays_full_price(self, api):
        """PRD §3.5: "When the order is at least 50 pieces, a quantity-tier multiplier of 0.95 applies and `quantity_tier_applied` is true."

        At 49 pieces the multiplier stays at 1.0: 150 * 49 = 7350 cents.

        Design: Difficulty/boundary_precision_check/wing_quote_quantity_tier_boundary
        """
        venue = create_venue()
        guest = create_guest(venue["id"])

        quote = validate_success(
            api.quote_wing_price(
                venue["id"],
                wing_quote_payload(
                    guest_id=guest["id"],
                    wing_kind="TRADITIONAL",
                    pieces=49,
                    event_date="2026-09-13",
                ),
                SERVER_HEADERS,
            )
        )

        assert quote["quote_cents"] == 7350
        assert quote["quantity_tier_applied"] is False

    def test_fifty_pieces_triggers_the_tier(self, api):
        """PRD §3.5: "When the order is at least 50 pieces, a quantity-tier multiplier of 0.95 applies and `quantity_tier_applied` is true."

        At exactly 50 pieces the 0.95 multiplier engages: 150 * 50 * 0.95 =
        7125 cents.

        Design: Difficulty/boundary_precision_check/wing_quote_quantity_tier_boundary
        """
        venue = create_venue()
        guest = create_guest(venue["id"])

        quote = validate_success(
            api.quote_wing_price(
                venue["id"],
                wing_quote_payload(
                    guest_id=guest["id"],
                    wing_kind="TRADITIONAL",
                    pieces=50,
                    event_date="2026-09-13",
                ),
                SERVER_HEADERS,
            )
        )

        assert quote["quote_cents"] == 7125
        assert quote["quantity_tier_applied"] is True
