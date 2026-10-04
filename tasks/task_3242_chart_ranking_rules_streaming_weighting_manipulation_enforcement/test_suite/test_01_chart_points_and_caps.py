"""Chart points formula and album-unit counting tests.

Covers the weighted chart-points calculation (integer-floor division per
component before weighting, final rounding to 4 decimals round-half-up) and
the per-buyer album cap waterfall.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    accept_report,
    compute_week,
    create_provider,
    create_sale_batch_ok,
    find_entry,
    get_success_data,
    set_clock,
    setup_locked_week_with_sales,
    setup_open_week_scenario,
    submit_report_ok,
)


class TestDualVariantPointsFormula:
    def test_singles_points_formula_canonical_input(self, api):
        """PRD §3.5:"On a `SINGLES` chart, or for a `TRACK` title, points are
        `w_sales` times sales units, plus `w_on_demand` times the sum of paid
        and ad stream-equivalent units, plus `w_programmed` times programmed
        stream-equivalent units, plus `w_airplay` times airplay"

    Design: Difficulty/dual_variant_calc/singles_vs_albums_points_formula"""
        scenario = setup_open_week_scenario(product_kind="TRACK")
        title = scenario["title"]
        week = scenario["week"]
        pv_sales = create_provider(feed_kind="SALES", territory="DOMESTIC")
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        pv_prog = create_provider(feed_kind="STREAM_PROGRAMMED", territory="DOMESTIC")
        pv_air = create_provider(feed_kind="AIRPLAY", territory="DOMESTIC")
        reports = [
            submit_report_ok(pv_sales, title["id"], week["id"],
                             component_kind="SALES", quantity=500,
                             file_fingerprint="fp-s"),
            submit_report_ok(pv_od, title["id"], week["id"],
                             component_kind="STREAM_ON_DEMAND_PAID",
                             quantity=10000, file_fingerprint="fp-p"),
            submit_report_ok(pv_od, title["id"], week["id"],
                             component_kind="STREAM_ON_DEMAND_AD",
                             quantity=7500, file_fingerprint="fp-a"),
            submit_report_ok(pv_prog, title["id"], week["id"],
                             component_kind="STREAM_PROGRAMMED", quantity=5000,
                             file_fingerprint="fp-g"),
            submit_report_ok(pv_air, title["id"], week["id"],
                             component_kind="AIRPLAY", quantity=100000,
                             file_fingerprint="fp-r"),
        ]
        for report in reports:
            accept_report(report["id"])
        set_clock(week["closes_at"])
        from test_helpers import TEST_USERS
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        entry = find_entry(entries, title["id"])
        assert entry is not None, "expected an entry for the track title"
        # 1.0*500 + 0.5*(floor(10000/1250)+floor(7500/3750))
        #   + 0.2*floor(5000/2500) + 0.0001*100000 = 515.4
        assert entry["points"] == pytest.approx(515.4, abs=1e-9), (
            f"singles points expected 515.4, got {entry['points']}")

    def test_albums_tea_points_formula_diverges(self, api):
        """PRD §3.5:"On an `ALBUMS` chart for an `ALBUM` title, the on-demand
        component converts to track-equivalent albums: the paid
        stream-equivalent units are divided by `tea_rate` and floored to whole
        album units, and ad-supported on-demand streams do not count toward
        album points at all; points are then `w_sales` times sales units, plus
        `w_on_demand` times those album-equivalent units, plus `w_programmed`
        and `w_airplay` terms as before"

    Design: Difficulty/dual_variant_calc/singles_vs_albums_points_formula"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        title = scenario["title"]
        week = scenario["week"]
        pv_sales = create_provider(feed_kind="SALES", territory="DOMESTIC")
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        pv_prog = create_provider(feed_kind="STREAM_PROGRAMMED", territory="DOMESTIC")
        pv_air = create_provider(feed_kind="AIRPLAY", territory="DOMESTIC")
        reports = [
            submit_report_ok(pv_sales, title["id"], week["id"],
                             component_kind="SALES", quantity=500,
                             file_fingerprint="fp-s"),
            submit_report_ok(pv_od, title["id"], week["id"],
                             component_kind="STREAM_ON_DEMAND_PAID",
                             quantity=10000, file_fingerprint="fp-p"),
            submit_report_ok(pv_od, title["id"], week["id"],
                             component_kind="STREAM_ON_DEMAND_AD",
                             quantity=7500, file_fingerprint="fp-a"),
            submit_report_ok(pv_prog, title["id"], week["id"],
                             component_kind="STREAM_PROGRAMMED", quantity=5000,
                             file_fingerprint="fp-g"),
            submit_report_ok(pv_air, title["id"], week["id"],
                             component_kind="AIRPLAY", quantity=100000,
                             file_fingerprint="fp-r"),
        ]
        for report in reports:
            accept_report(report["id"])
        set_clock(week["closes_at"])
        from test_helpers import TEST_USERS
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        entry = find_entry(entries, title["id"])
        assert entry is not None, "expected an entry for the album title"
        # 1.0*500 + 0.5*floor(floor(10000/1250)/10) + 0.2*floor(5000/2500)
        #   + 0.0001*100000 = 500 + 0.5*0 + 0.4 + 10 = 510.4
        assert entry["points"] == pytest.approx(510.4, abs=1e-9), (
            f"albums points expected 510.4, got {entry['points']}")


class TestCombinatorialFormula:
    def test_weighted_points_multifactor_canonical(self, api):
        """PRD §2.6:"all intermediate component sums are exact integers; each
        stream-to-unit division is an integer floor applied per component
        before any weighting is applied; methodology weights themselves are
        never rounded; and only the final points value is rounded, to 4
        decimal places, round-half-up"

    Design: Difficulty/combinatorial_formula/weighted_points_mode_a_multifactor"""
        scenario = setup_open_week_scenario(product_kind="TRACK")
        title = scenario["title"]
        week = scenario["week"]
        pv_sales = create_provider(feed_kind="SALES", territory="DOMESTIC")
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        pv_prog = create_provider(feed_kind="STREAM_PROGRAMMED", territory="DOMESTIC")
        pv_air = create_provider(feed_kind="AIRPLAY", territory="DOMESTIC")
        reports = [
            submit_report_ok(pv_sales, title["id"], week["id"],
                             component_kind="SALES", quantity=500,
                             file_fingerprint="cf-s"),
            submit_report_ok(pv_od, title["id"], week["id"],
                             component_kind="STREAM_ON_DEMAND_PAID",
                             quantity=10000, file_fingerprint="cf-p"),
            submit_report_ok(pv_od, title["id"], week["id"],
                             component_kind="STREAM_ON_DEMAND_AD",
                             quantity=7500, file_fingerprint="cf-a"),
            submit_report_ok(pv_prog, title["id"], week["id"],
                             component_kind="STREAM_PROGRAMMED", quantity=5000,
                             file_fingerprint="cf-g"),
            submit_report_ok(pv_air, title["id"], week["id"],
                             component_kind="AIRPLAY", quantity=100000,
                             file_fingerprint="cf-r"),
        ]
        for report in reports:
            accept_report(report["id"])
        set_clock(week["closes_at"])
        from test_helpers import TEST_USERS
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        entry = find_entry(entries, title["id"])
        assert entry["points"] == pytest.approx(515.4, abs=1e-9)

    def test_weighted_points_ad_streams_below_divisor_contribute_zero(self, api):
        """PRD §3.5:"the ad-supported stream-equivalent units are the floor
        of the `STREAM_ON_DEMAND_AD` total divided by `ad_stream_divisor`"
    PRD §2.6:"each stream-to-unit division is an integer floor applied
        per component before any weighting is applied"

    Design: Difficulty/combinatorial_formula/weighted_points_mode_a_multifactor"""
        scenario = setup_open_week_scenario(product_kind="TRACK")
        title = scenario["title"]
        week = scenario["week"]
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        # 3749 ad streams: floor(3749/3750) == 0, so points stay 0 even
        # though a naive non-floored division would contribute ~0.4999.
        report = submit_report_ok(pv_od, title["id"], week["id"],
                                  component_kind="STREAM_ON_DEMAND_AD",
                                  quantity=3749, file_fingerprint="cf-ad-low")
        accept_report(report["id"])
        set_clock(week["closes_at"])
        from test_helpers import TEST_USERS
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        entry = find_entry(entries, title["id"])
        assert entry is not None
        assert entry["points"] == pytest.approx(0.0, abs=1e-9), (
            f"floor-first division must zero 3749 ad streams, got {entry['points']}")


class TestCappedBatchVsUncappedSalesReport:
    def test_d2c_batch_capped_at_four(self, api):
        """PRD §3.4:"Countable units are allocated per (`buyer_key`, title,
        chart week) group under a per-buyer cap of 4 album units per buyer per
        week"

    Design: Difficulty/dual_variant_calc/capped_batch_vs_uncapped_sales_report"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        batch = create_sale_batch_ok(
            scenario["title"]["id"], channel="D2C", quantity=6,
            buyer_key="buyer-X", chart_week_id=scenario["week"]["id"])
        assert batch["countable_units"] == 4, (
            f"cap must bind: min(6, 4) == 4, got {batch['countable_units']}")

    def test_sales_report_counts_full_quantity_uncapped(self, api):
        """PRD §3.4:"Unit sales arriving as consumption reports with
        `component_kind` `SALES` count in full — there is no buyer identity
        on a report, so no cap applies"

    Design: Difficulty/dual_variant_calc/capped_batch_vs_uncapped_sales_report"""
        scenario = setup_locked_week_with_sales(
            chart_kind="ALBUMS", product_kind="ALBUM", sales_quantity=6)
        entries = compute_week(scenario["week"]["id"])
        entry = find_entry(entries, scenario["title"]["id"])
        assert entry is not None
        # w_sales is 1.0 in the canonical methodology; full 6 units count.
        assert entry["points"] == pytest.approx(6.0, abs=1e-9), (
            f"uncapped SALES report of 6 must yield 6.0 points, "
            f"got {entry['points']}")


class TestPerBuyerCapWaterfall:
    def test_fill_in_order_headroom_exhaustion(self, api):
        """PRD §3.4:"Within a group, eligible batches — those with
        `review_status` `CLEARED` and channel `D2C` or `RETAIL` — are ordered
        by `created_at` ascending with a `quantity` ascending tie-break, and
        filled strictly in order: each batch's `countable_units` is the
        smaller of its `quantity` and the remaining headroom, and the headroom
        decreases by each allocation"

    Design: Difficulty/combinatorial_formula/per_buyer_cap_waterfall_mode_c_ordered_allocation"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        title_id = scenario["title"]["id"]
        week_id = scenario["week"]["id"]
        b1 = create_sale_batch_ok(title_id, channel="D2C", quantity=4,
                                  buyer_key="buyer-Y", chart_week_id=week_id)
        b2 = create_sale_batch_ok(title_id, channel="D2C", quantity=3,
                                  buyer_key="buyer-Y", chart_week_id=week_id)
        assert b1["countable_units"] == 4
        assert b2["countable_units"] == 0, (
            "headroom exhausted after first batch; fill-in-order, not proportional")

    def test_exact_multiple_of_cap_gives_last_batch_zero(self, api):
        """PRD §3.4:"A consequence of strict fill-in-order: when the group's
        total eligible quantity is an exact multiple of the cap, the last
        batch in the ordering receives 0 units — there is no proportional
        split"

    Design: Difficulty/combinatorial_formula/per_buyer_cap_waterfall_mode_c_ordered_allocation"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        title_id = scenario["title"]["id"]
        week_id = scenario["week"]["id"]
        b1 = create_sale_batch_ok(title_id, channel="D2C", quantity=4,
                                  buyer_key="buyer-M", chart_week_id=week_id)
        b2 = create_sale_batch_ok(title_id, channel="D2C", quantity=4,
                                  buyer_key="buyer-M", chart_week_id=week_id)
        assert b1["countable_units"] == 4
        assert b2["countable_units"] == 0, (
            "total 8 is an exact multiple of the cap 4: the last batch gets 0")


class TestCalculationCornerCases:
    def test_territory_and_status_filters_exclude_inputs(self, api):
        """PRD §3.5:"Only reports from `DOMESTIC` providers contribute;
        everything else — `INTERNATIONAL` providers, non-`ACCEPTED` reports —
        contributes zero"

    Design: Corner/calculations/territory_and_status_filter_excludes_inputs"""
        scenario = setup_open_week_scenario(product_kind="TRACK")
        title = scenario["title"]
        week = scenario["week"]
        pv_dom = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        pv_intl = create_provider(feed_kind="STREAM_ON_DEMAND",
                                  territory="INTERNATIONAL")
        r_acc = submit_report_ok(pv_dom, title["id"], week["id"],
                                 component_kind="STREAM_ON_DEMAND_PAID",
                                 quantity=2500, file_fingerprint="k1-acc")
        r_quar = submit_report_ok(pv_dom, title["id"], week["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=10000, file_fingerprint="k1-quar")
        r_intl = submit_report_ok(pv_intl, title["id"], week["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=10000, file_fingerprint="k1-intl")
        accept_report(r_acc["id"])
        from test_helpers import TEST_USERS
        get_success_data(api.quarantine_report(
            r_quar["id"], {"reason": "suspect"}, TEST_USERS["chart_ops_headers"]))
        accept_report(r_intl["id"])
        set_clock(week["closes_at"])
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        entry = find_entry(entries, title["id"])
        assert entry is not None
        # only floor(2500/1250)=2 SEA * 0.5 = 1.0 point counts.
        assert entry["points"] == pytest.approx(1.0, abs=1e-9), (
            f"expected 1.0 (quarantined and international excluded), "
            f"got {entry['points']}")

    def test_division_floor_before_weighting(self, api):
        """PRD §2.6:"each stream-to-unit division is an integer floor applied
        per component before any weighting is applied"

    Design: Corner/calculations/division_floor_before_weighting"""
        scenario = setup_open_week_scenario(product_kind="TRACK")
        title = scenario["title"]
        week = scenario["week"]
        pv_od = create_provider(feed_kind="STREAM_ON_DEMAND", territory="DOMESTIC")
        report = submit_report_ok(pv_od, title["id"], week["id"],
                                  component_kind="STREAM_ON_DEMAND_PAID",
                                  quantity=1249, file_fingerprint="k2-a")
        accept_report(report["id"])
        set_clock(week["closes_at"])
        from test_helpers import TEST_USERS
        get_success_data(api.lock_week(week["id"], TEST_USERS["chart_manager_headers"]))
        entries = compute_week(week["id"])
        entry = find_entry(entries, title["id"])
        assert entry is not None
        # floor(1249/1250) == 0 before weighting: 0 * 0.5 == 0.0
        assert entry["points"] == pytest.approx(0.0, abs=1e-9)

    def test_per_buyer_cap_applied_per_buyer_independently(self, api):
        """PRD §3.4:"Countable units are allocated per (`buyer_key`, title,
        chart week) group under a per-buyer cap of 4 album units per buyer per
        week"

    Design: Corner/calculations/per_buyer_cap_constants_applied"""
        scenario = setup_open_week_scenario(
            chart_kind="ALBUMS", product_kind="ALBUM")
        title_id = scenario["title"]["id"]
        week_id = scenario["week"]["id"]
        ba = create_sale_batch_ok(title_id, channel="D2C", quantity=5,
                                  buyer_key="buyer-A", chart_week_id=week_id)
        bb = create_sale_batch_ok(title_id, channel="D2C", quantity=5,
                                  buyer_key="buyer-B", chart_week_id=week_id)
        assert ba["countable_units"] == 4
        assert bb["countable_units"] == 4, (
            "the cap is per buyer; buyer-B has independent headroom")
