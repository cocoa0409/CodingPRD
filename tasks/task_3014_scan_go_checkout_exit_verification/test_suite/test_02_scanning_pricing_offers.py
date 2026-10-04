"""Scanning: per-line pricing, rounding, instant savings, and offer limits."""
from test_helpers import (
    ApiErrorId,
    create_item,
    create_member,
    create_offer,
    create_session,
    get_session,
    member_headers,
    scan_unit_line,
    scan_weighted_line,
    setup_club_member,
    setup_session_with_unit_item,
    validate_success,
    validate_paginated,
    MANAGER,
)


class TestSessionCreation:
    def test_session_creation_sets_open_with_zero_totals(self, api):
        """PRD §3.2: "A new session starts `OPEN` with a
        `provisional_total_cents` of zero."

        Design: Corner/entities/session_creation_sets_open_with_zero_totals
        """
        club, member = setup_club_member()
        session = create_session(club, member)
        assert session["status"] == "OPEN"
        assert session["provisional_total_cents"] == 0
        assert session["scanned_item_count"] == 0
        assert session["receipt_code"] is None

    def test_session_scanned_item_count_computed_across_modes(self, api):
        """PRD §3.2: "the session's `scanned_item_count` tracks physical items:
        the sum of `quantity` over non-`REMOVED` `UNIT` lines plus the count of
        non-`REMOVED` `WEIGHTED` lines — a bag of produce is exactly one
        physical item no matter its weight."

        Design: Corner/entities/session_scanned_item_count_computed_across_modes
        """
        club, member = setup_club_member(
            club_overrides={"exit_verification_mode": "CV_ARCH"},
        )
        unit_item = create_item(club["id"], sku="MILK", unit_price_cents=400)
        weighted_item = create_item(
            club["id"], sku="BAN", pricing_mode="WEIGHTED",
            price_per_pound_cents=250, unit_price_cents=None,
        )
        session = create_session(club, member)
        scan_unit_line(session, member, unit_item, quantity=2)
        scan_weighted_line(session, member, weighted_item, weight_grams=300)

        reread = get_session(session["id"])
        # 2 UNIT pieces + 1 WEIGHTED bag = 3 physical items.
        assert reread["scanned_item_count"] == 3
        # 2*400=800 plus round_half_up(300*250/454)=round_half_up(165.198)=165.
        assert reread["provisional_total_cents"] == 965


class TestWeightedRounding:
    def test_weighted_line_rounding_per_line_then_sum_line_values(self, api):
        """PRD §3.2: "For a `WEIGHTED` line, `line_gross_cents` is the weight in
        grams multiplied by the per-pound price, divided by 454 (the number of
        grams in a pound), rounded half-up to a whole cent. Rounding strictly
        precedes summation: two 150-gram bags of a 250-cents-per-pound item
        contribute 83 cents each and total 166 cents, never 165."

        Design: Difficulty/combinatorial_formula/weighted_line_rounding_per_line_then_sum
        """
        club, member = setup_club_member()
        item = create_item(
            club["id"], sku="BANANA", pricing_mode="WEIGHTED",
            price_per_pound_cents=250, unit_price_cents=None,
        )
        session = create_session(club, member)
        line1 = scan_weighted_line(session, member, item, weight_grams=150)
        line2 = scan_weighted_line(session, member, item, weight_grams=150)
        assert line1["line_gross_cents"] == 83
        assert line2["line_gross_cents"] == 83

    def test_weighted_lines_sum_to_166_not_165(self, api):
        """PRD §3.2: "Rounding strictly precedes summation: two 150-gram bags of
        a 250-cents-per-pound item contribute 83 cents each and total 166
        cents, never 165."

        Design: Difficulty/combinatorial_formula/weighted_line_rounding_per_line_then_sum
        """
        club, member = setup_club_member()
        item = create_item(
            club["id"], sku="BANANA", pricing_mode="WEIGHTED",
            price_per_pound_cents=250, unit_price_cents=None,
        )
        session = create_session(club, member)
        scan_weighted_line(session, member, item, weight_grams=150)
        scan_weighted_line(session, member, item, weight_grams=150)
        reread = get_session(session["id"])
        assert reread["provisional_total_cents"] == 166

    def test_weighted_round_half_up_exactly_half_cent_rounds_up(self, api):
        """PRD §2.6: "Where a calculation produces a fractional result — the
        weighted-item gross computation in §3.2 — the result is rounded to a
        whole number of cents using round-half-up, and the rounding is applied
        per line before line values are summed into cart totals."

        Design: Corner/calculations/weighted_round_half_up_exactly_half_cent_rounds_up
        """
        club, member = setup_club_member()
        item = create_item(
            club["id"], sku="HAM", pricing_mode="WEIGHTED",
            price_per_pound_cents=199, unit_price_cents=None,
        )
        session = create_session(club, member)
        # 227 * 199 / 454 == 99.5 exactly; round-half-up must give 100.
        line = scan_weighted_line(session, member, item, weight_grams=227)
        assert line["line_gross_cents"] == 100


class TestCommencedPoundsAndLimits:
    def test_commenced_pounds_boundary_454_vs_455_grams(self, api):
        """PRD §3.2: "Commenced pounds are counted by rounding up: 454 grams is
        one commenced pound, and anything beyond that — 455 grams, 500 grams —
        is two."

        Design: Corner/calculations/commenced_pounds_boundary_454_vs_455_grams
        """
        club, member = setup_club_member()
        item = create_item(
            club["id"], sku="TURK", pricing_mode="WEIGHTED",
            price_per_pound_cents=100, unit_price_cents=None,
        )
        create_offer(
            club["id"], item["id"], discount_cents=20, per_member_limit=10,
        )
        session = create_session(club, member)
        line1 = scan_weighted_line(session, member, item, weight_grams=454)
        line2 = scan_weighted_line(session, member, item, weight_grams=455)
        assert line1["offer_units_applied"] == 1
        assert line1["line_savings_cents"] == 20
        assert line2["offer_units_applied"] == 2
        assert line2["line_savings_cents"] == 40

    def test_weighted_offer_commenced_pounds_meets_per_member_limit_units(
        self, api,
    ):
        """PRD §3.2: "the discounted units on the line — recorded as
        `offer_units_applied` — are the line's units (its quantity for a
        `UNIT` item, or its commenced pounds for a `WEIGHTED` item) capped by
        the member's remaining allowance under the offer's `per_member_limit`,
        where the allowance already consumed is the sum of
        `offer_units_applied` across all of that member's lines carrying this
        offer on sessions that have not been voided and lines that have not
        been removed; the applied units never drop below zero."

        Design: Difficulty/combinatorial_formula/weighted_offer_commenced_pounds_meets_per_member_limit
        """
        club, member, session, _item = _setup_steak_offer_scenario(self, api)
        line1 = scan_weighted_line(session, member, _item, weight_grams=500)
        line2 = scan_weighted_line(session, member, _item, weight_grams=500)
        # 500g = 2 commenced pounds; limit 3 -> line1 redeems 2, line2 redeems 1.
        assert line1["offer_units_applied"] == 2
        assert line2["offer_units_applied"] == 1

    def test_weighted_offer_per_member_limit_line_totals(self, api):
        """PRD §3.2: "The line's `line_savings_cents` is the applied units
        multiplied by the offer's `discount_cents`" and "The line's
        `line_total_cents` is its gross minus its savings, floored at zero so a
        line can never go negative."

        Design: Difficulty/combinatorial_formula/weighted_offer_commenced_pounds_meets_per_member_limit
        """
        club, member, session, item = _setup_steak_offer_scenario(self, api)
        line1 = scan_weighted_line(session, member, item, weight_grams=500)
        line2 = scan_weighted_line(session, member, item, weight_grams=500)
        # gross = round_half_up(500*199/454) = 219; savings 100 then 50.
        assert line1["line_savings_cents"] == 100
        assert line1["line_total_cents"] == 119
        assert line2["line_savings_cents"] == 50
        assert line2["line_total_cents"] == 169
        reread = get_session(session["id"])
        assert reread["provisional_total_cents"] == 288

    def test_offer_per_member_limit_exhaustion_across_lines(self, api):
        """PRD §3.2: "the discounted units on the line — recorded as
        `offer_units_applied` — are the line's units (its quantity for a
        `UNIT` item, or its commenced pounds for a `WEIGHTED` item) capped by
        the member's remaining allowance under the offer's `per_member_limit`";
        "the applied units never drop below zero."

        Design: Corner/calculations/offer_per_member_limit_exhaustion_across_lines
        """
        club, member = setup_club_member()
        item = create_item(club["id"], sku="OJ", unit_price_cents=500)
        create_offer(
            club["id"], item["id"], discount_cents=100, per_member_limit=3,
        )
        session = create_session(club, member)
        line1 = scan_unit_line(session, member, item, quantity=3)
        line2 = scan_unit_line(session, member, item, quantity=1)
        assert line1["offer_units_applied"] == 3
        assert line1["line_total_cents"] == 1200
        assert line2["offer_units_applied"] == 0
        assert line2["line_total_cents"] == 500


def _setup_steak_offer_scenario(_self, api):
    club, member = setup_club_member(
        member_overrides={"tier": "PLUS", "birth_year": 1980},
    )
    item = create_item(
        club["id"], sku="STEAK", pricing_mode="WEIGHTED",
        price_per_pound_cents=199, unit_price_cents=None,
    )
    create_offer(
        club["id"], item["id"], discount_cents=50, per_member_limit=3,
        tier_eligibility="ALL",
    )
    session = create_session(club, member)
    return club, member, session, item


class TestOfferExpiryAtPay:
    def test_offer_expired_mid_shop_dropped_at_final_repricing(self, api):
        """PRD §3.4: "the server computes `final_total_cents` by re-pricing
        every non-`REMOVED` line against the current catalog prices and offers
        evaluated at the pay-time clock (not the scan-time snapshots)"; PRD
        §3.2: "The session's `provisional_total_cents` is the sum of
        `line_total_cents` over all non-`REMOVED` lines, recomputed on every
        line addition, removal, or intercept resolution, always from scan-time
        snapshots and scan-time offer evaluation."

        Design: Corner/calculations/offer_expired_mid_shop_dropped_at_final_repricing
        """
        from test_helpers import set_clock

        club, member = setup_club_member()
        item = create_item(club["id"], sku="PIZZA", unit_price_cents=900)
        create_offer(
            club["id"], item["id"], discount_cents=100, per_member_limit=5,
            valid_from_iso="2026-09-01T00:00:00Z",
            valid_to_iso="2026-09-01T12:30:00Z",
        )
        session = create_session(club, member)
        line = scan_unit_line(session, member, item, quantity=1)
        assert line["line_savings_cents"] == 100
        assert get_session(session["id"])["provisional_total_cents"] == 800

        # Past the window's closed end: the pay-time evaluation drops the offer.
        set_clock("2026-09-01T12:45:00Z")
        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["final_total_cents"] == 900
        assert paid["provisional_total_cents"] == 800


class TestOfferExpiryAtPay:
    def test_offer_expired_mid_shop_dropped_at_final_repricing(self, api):
        """PRD §3.4: "the server computes `final_total_cents` by re-pricing
        every non-`REMOVED` line against the current catalog prices and offers
        evaluated at the pay-time clock (not the scan-time snapshots)"; PRD
        §3.2: "The session's `provisional_total_cents` is the sum of
        `line_total_cents` over all non-`REMOVED` lines, recomputed on every
        line addition, removal, or intercept resolution, always from scan-time
        snapshots and scan-time offer evaluation."

        Design: Corner/calculations/offer_expired_mid_shop_dropped_at_final_repricing
        """
        from test_helpers import set_clock

        club, member = setup_club_member()
        item = create_item(club["id"], sku="PIZZA", unit_price_cents=900)
        create_offer(
            club["id"], item["id"], discount_cents=100, per_member_limit=5,
            valid_from_iso="2026-09-01T00:00:00Z",
            valid_to_iso="2026-09-01T12:30:00Z",
        )
        session = create_session(club, member)
        line = scan_unit_line(session, member, item, quantity=1)
        assert line["line_savings_cents"] == 100
        assert get_session(session["id"])["provisional_total_cents"] == 800

        # Past the window's closed end: the pay-time evaluation drops the offer.
        set_clock("2026-09-01T12:45:00Z")
        resp = api.pay_session(session["id"], member_headers(member))
        paid = validate_success(resp)
        assert paid["final_total_cents"] == 900
        assert paid["provisional_total_cents"] == 800


class TestOfferEligibilityAndConnectivity:
    def test_plus_only_offer_skipped_for_club_tier(self, api):
        """PRD §3.2: "Otherwise the system finds the offer for the session's
        club and the scanned item whose closed validity window contains the
        current logical-clock instant; if none exists, or the offer is
        `PLUS_ONLY` and the member's `tier` is `CLUB`, no savings apply."

        Design: Corner/calculations/plus_only_offer_skipped_for_club_tier
        """
        club, _m = setup_club_member()
        item = create_item(club["id"], sku="STEAKPK", unit_price_cents=1000)
        create_offer(
            club["id"], item["id"], discount_cents=150, per_member_limit=5,
            tier_eligibility="PLUS_ONLY",
        )
        club_member = create_member(club["id"], tier="CLUB", birth_year=1990)
        plus_member = create_member(club["id"], tier="PLUS", birth_year=1990)
        sess_club = create_session(club, club_member)
        sess_plus = create_session(club, plus_member)

        line_club = scan_unit_line(sess_club, club_member, item, quantity=1)
        line_plus = scan_unit_line(sess_plus, plus_member, item, quantity=1)
        assert line_club["line_savings_cents"] == 0
        assert line_club["line_total_cents"] == 1000
        assert line_plus["line_savings_cents"] == 150
        assert line_plus["line_total_cents"] == 850

    def test_degraded_connectivity_skips_offer_application(self, api):
        """PRD §3.2: "If the club's connectivity posture is anything other than
        `ONLINE` at evaluation time, no offer applies and `line_savings_cents`
        is zero."

        Design: Corner/calculations/degraded_connectivity_skips_offer_application
        """
        club, member = setup_club_member()
        item = create_item(club["id"], sku="WATER", unit_price_cents=800)
        create_offer(
            club["id"], item["id"], discount_cents=100, per_member_limit=5,
        )
        session = create_session(club, member)
        resp = api.set_connectivity(club["id"], "DEGRADED", MANAGER)
        assert resp.status_code == 200, f"Setup failed: {resp.text}"

        line = scan_unit_line(session, member, item, quantity=1)
        assert line["line_savings_cents"] == 0
        assert line["line_total_cents"] == 800
