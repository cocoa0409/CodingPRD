"""Money calculations: sponsorship projection/reconciliation and royalty true-up."""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data, ApiErrorId,
    set_clock, make_studio, make_season, make_locked_season, make_title, approve_title,
    make_location, book_slot, make_published_block, make_air_slot, make_sponsorship,
    make_license,
)
from test_helpers.fixtures import (
    setup_delivered_title, setup_archived_season_with_premieres,
    ADMIN, PLANNER, PROD, EXEC, ADS, LIC,
)


class TestSponsorshipProjectionVsReconciliation:
    def test_projected_spiked_25000_at_booking(self, api):
        """PRD §3.6: "If the season's air window — the half-open interval from
        `air_window_start` to `air_window_end` — intersects the December spike
        window of the season's `year`, defined as the half-open interval from
        midnight UTC on December 1 of that year to midnight UTC on December 26 of
        that year, then the projection is the base multiplied by 125 and divided
        by 100, with the result floored once to whole cents".

        Design: Difficulty/dual_variant_calc/sponsorship_projection_vs_reconciliation_diverge
        """
        ctx = setup_archived_season_with_premieres(2, ad_budget_cents=10000000)
        season_id = ctx["season"]["id"]
        spon = get_success_data(api_client.create_sponsorship(
            {"season_id": season_id, "advertiser": "Greeting Cards Co",
             "season_cpm_cents": 2000, "viewership_thousands": 10}, ADS))
        # floor(2000 * 10 * 125 / 100) == 25000
        assert spon["projected_cost_cents"] == 25000, \
            f"expected spiked projection 25000, got {spon['projected_cost_cents']}"

    def test_reconcile_drops_spike_and_weights_premieres(self, api):
        """PRD §3.6: "The actual cost deliberately differs from the projection in
        two ways: it adds the season's `premiered_title_count` at reconcile time
        to the booked `viewership_thousands`, and it drops the December spike
        multiplier entirely."

        Design: Difficulty/dual_variant_calc/sponsorship_projection_vs_reconciliation_diverge
        """
        ctx = setup_archived_season_with_premieres(2, ad_budget_cents=10000000)
        studio_id = ctx["studio"]["id"]
        season_id = ctx["season"]["id"]
        # Book the sponsorship BEFORE archive is irrelevant to the formula;
        # the season here is already archived (reconcile requires ARCHIVED).
        spon = get_success_data(api_client.create_sponsorship(
            {"season_id": season_id, "advertiser": "Greeting Cards Co",
             "season_cpm_cents": 2000, "viewership_thousands": 10}, ADS))
        assert spon["projected_cost_cents"] == 25000
        reconciled = validate_success(api_client.reconcile_sponsorship(spon["id"], ADS))
        # actual = 2000 * (10 + 2 premieres) == 24000, spike dropped
        assert reconciled["actual_cost_cents"] == 24000, \
            f"expected actual 24000, got {reconciled['actual_cost_cents']}"
        assert reconciled["status"] == "RECONCILED"
        studio = get_success_data(api_client.get_studio(studio_id, ADMIN))
        assert studio["ad_budget_cents"] == 10000000 - 24000 == 9976000


class TestRoyaltyProvisionalVsTrueupDelta:
    def test_provisional_is_floored_revenue_times_rate(self, api):
        """PRD §3.8: "Reporting immediately computes the `provisional_royalty_cents`
        as the reported revenue multiplied by the royalty rate, floored after the
        multiplication to whole cents".

        Design: Difficulty/dual_variant_calc/royalty_provisional_vs_trueup_delta
        """
        ctx = setup_delivered_title(name="Mistletoe Merch", genre="FAMILY",
                                    tone_rating="WARM", duration_minutes=84)
        lic = make_license(ctx["season"]["id"], ctx["title"]["id"],
                           royalty_rate=0.10, reported_revenue_cents=1500000)
        # floor(1500000 * 0.10) == 150000
        assert lic["provisional_royalty_cents"] == 150000, \
            f"expected provisional 150000, got {lic['provisional_royalty_cents']}"
        assert lic["status"] == "REPORTED"

    def test_audit_trueup_is_signed_delta_with_bonus(self, api):
        """PRD §3.8: "finally the `trued_royalty_cents` is the floored gross minus
        the already-floored `provisional_royalty_cents`" and "when the
        `reported_revenue_cents` is at least ten thousand dollars — one million
        cents — a flat audit bonus of fifty thousand cents is added to the gross".

        Design: Difficulty/dual_variant_calc/royalty_provisional_vs_trueup_delta
        """
        ctx = setup_delivered_title(name="Mistletoe Merch", genre="FAMILY",
                                    tone_rating="WARM", duration_minutes=84)
        lic = make_license(ctx["season"]["id"], ctx["title"]["id"],
                           royalty_rate=0.10, reported_revenue_cents=1500000)
        audited = validate_success(api_client.audit_license(lic["id"], LIC))
        # floor(1500000*0.10 + 50000) - 150000 == 50000 (DELTA, not re-stated royalty)
        assert audited["trued_royalty_cents"] == 50000, \
            f"expected trued delta 50000, got {audited['trued_royalty_cents']}"
        assert audited["status"] == "AUDITED"


class TestSponsorshipSpikeMultiplierNestedFloor:
    def test_spiked_season_projection_applies_125_over_100(self, api):
        """PRD §3.6: "then the projection is the base multiplied by 125 and
        divided by 100, with the result floored once to whole cents".

        Design: Difficulty/combinatorial_formula/sponsorship_spike_multiplier_nested_floor
        """
        studio = make_studio()
        season = make_season(studio["id"], label="Countdown")
        spon = make_sponsorship(season["id"], advertiser="CardsCo",
                                season_cpm_cents=2000, viewership_thousands=10)
        # floor(2000 * 10 * 125 / 100) == 25000
        assert spon["projected_cost_cents"] == 25000, \
            f"expected spiked projection 25000, got {spon['projected_cost_cents']}"

    def test_flat_season_projection_is_base_without_multiplier(self, api):
        """PRD §3.6: "If there is no intersection, the projection is simply the
        base with no multiplier."

        Design: Difficulty/combinatorial_formula/sponsorship_spike_multiplier_nested_floor
        """
        studio = make_studio()
        season = make_season(
            studio["id"], label="Winter Warmup",
            air_window_start="2027-02-01T00:00:00Z",
            air_window_end="2027-03-01T00:00:00Z",
            delivery_deadline="2027-01-01T00:00:00Z",
        )
        spon = make_sponsorship(season["id"], advertiser="CardsCo",
                                season_cpm_cents=2000, viewership_thousands=10)
        # identical money inputs, no December intersection -> 2000 * 10 == 20000
        assert spon["projected_cost_cents"] == 20000, \
            f"expected flat projection 20000, got {spon['projected_cost_cents']}"


class TestRoyaltyTrueupPinnedEvaluationOrder:
    def test_above_threshold_gets_bonus_delta(self, api):
        """PRD §3.8: "The true-up is computed in a pinned order: first the gross
        royalty is the `reported_revenue_cents` multiplied by the `royalty_rate`,
        kept exact; then, when the `reported_revenue_cents` is at least ten
        thousand dollars — one million cents — a flat audit bonus of fifty
        thousand cents is added to the gross".

        Design: Difficulty/combinatorial_formula/royalty_trueup_pinned_evaluation_order
        """
        ctx = setup_delivered_title(name="Novel Tie-In", genre="MYSTERY",
                                    tone_rating="WARM", duration_minutes=100)
        lic = make_license(ctx["season"]["id"], ctx["title"]["id"], category="PUBLISHING",
                           licensee="BookHouse", royalty_rate=0.10,
                           reported_revenue_cents=1500000)
        audited = validate_success(api_client.audit_license(lic["id"], LIC))
        assert audited["provisional_royalty_cents"] == 150000
        # floor(1500000 * 0.10 + 50000) - 150000 == 50000
        assert audited["trued_royalty_cents"] == 50000

    def test_below_threshold_gets_zero_delta(self, api):
        """PRD §3.8: "with reports below that threshold receiving no bonus".

        Design: Difficulty/combinatorial_formula/royalty_trueup_pinned_evaluation_order
        """
        ctx = setup_delivered_title(name="Novel Tie-In", genre="MYSTERY",
                                    tone_rating="WARM", duration_minutes=100)
        lic = make_license(ctx["season"]["id"], ctx["title"]["id"], category="PUBLISHING",
                           licensee="BookHouse", royalty_rate=0.10,
                           reported_revenue_cents=999999)
        audited = validate_success(api_client.audit_license(lic["id"], LIC))
        # floor(999999 * 0.10) == 99999 pins per-report floor order
        assert audited["provisional_royalty_cents"] == 99999, \
            f"expected provisional 99999, got {audited['provisional_royalty_cents']}"
        # no bonus: floor(99999.9) - 99999 == 0
        assert audited["trued_royalty_cents"] == 0
