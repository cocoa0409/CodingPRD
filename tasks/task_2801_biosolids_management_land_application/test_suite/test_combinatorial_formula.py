"""Multi-input formulas whose evaluation and rounding order is pinned:
the agronomic rate cap, the loading ledger, and the outlet cost breakdown.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import ERR_AGRONOMIC_RATE_EXCEEDED
from test_helpers.assertions import (
    assert_cost_breakdown,
    assert_dry_tons,
    assert_loading_delta,
    assert_money,
    assert_pan,
    assert_wet_tons,
)
from test_helpers.test_users import AGRONOMIST_HEADERS, OFFICER_HEADERS, make_operator_headers
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAgronomicRateCapNestedMinimum:
    def test_nitrogen_wins_the_four_way_minimum_with_one_final_rounding(
        self, base_world
    ):
        """PRD §3.7: "`binding_rate_constraint` is the **first** of them whose value equals the minimum, so nitrogen wins any tie, then phosphorus, then the APLR rate, then the agreement cap."

        With nitrogen 9.8765..., phosphorus at the 9999.0 sentinel (soil P index 40
        sits below the 75 tier), APLR 42.3785... and the agreement ceiling 20.0, the
        cap is the minimum rounded once at the end: 9.88, labelled NITROGEN.

        Plant available nitrogen is 16.2000 lb per dry ton, which already carries the
        SURFACE volatilization factor 0.50 on the ammonium fraction.

        Design: Difficulty/combinatorial_formula/agronomic_cap_nested_min_selects_nitrogen_over_three_rivals
        """
        build = base_world.build
        event = build.event(
            base_world.site_id,
            base_world.batch_id,
            base_world.agreement_id,
            acres_treated=100.0,
            planned_dry_tons=100.000,
        )

        assert_pan(event["plant_available_n_lb_per_dry_ton"], 16.2000)
        assert event["agronomic_rate_cap_dry_tons_per_acre"] == 9.88
        assert event["binding_rate_constraint"] == C.BINDING_NITROGEN
        assert event["requested_rate_dry_tons_per_acre"] == 1.00
        assert event["status"] == C.EVENT_SCHEDULED
        assert_dry_tons(event["reserved_dry_tons"], 100.000)

        batch = build.read_batch(base_world.batch_id)
        assert_dry_tons(batch["unallocated_dry_tons"], 60.000)

    def test_requested_rate_two_hundredths_above_the_cap_is_refused(
        self, api, base_world
    ):
        """PRD §2.7: "**Priority 51 — agronomic rate.** `requested_rate_dry_tons_per_acre` is at most `agronomic_rate_cap_dry_tons_per_acre`; equality is accepted."

        99.000 dry tons on 10.0 acres is a requested rate of 9.90 against a cap of
        9.88, so the schedule is refused with ERR_AGRONOMIC_RATE_EXCEEDED and no
        second event is recorded on the site.

        Design: Difficulty/combinatorial_formula/agronomic_cap_nested_min_selects_nitrogen_over_three_rivals
        """
        build = base_world.build
        build.event(
            base_world.site_id,
            base_world.batch_id,
            base_world.agreement_id,
            acres_treated=100.0,
            planned_dry_tons=100.000,
        )

        response = api.create_event(
            F.event_payload(
                base_world.site_id,
                base_world.batch_id,
                base_world.agreement_id,
                window_start="2026-09-10T00:00:00Z",
                window_end="2026-09-11T00:00:00Z",
                acres_treated=10.0,
                planned_dry_tons=99.000,
            ),
            AGRONOMIST_HEADERS,
        )
        validate_error(response, ERR_AGRONOMIC_RATE_EXCEEDED)

        rows, meta = validate_paginated(
            api.list_events(OFFICER_HEADERS, {"site_id": base_world.site_id})
        )
        assert meta["total_count"] == 1
        assert len(rows) == 1


class TestLoadingLedgerRoundThenSum:
    @staticmethod
    def _two_applications(base_world):
        build = base_world.build
        event_a = build.event(
            base_world.site_id,
            base_world.batch_id,
            base_world.agreement_id,
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-21T00:00:00Z",
            acres_treated=80.0,
            planned_dry_tons=80.000,
        )
        event_b = build.event(
            base_world.site_id,
            base_world.batch_id,
            base_world.agreement_id,
            window_start="2026-09-10T00:00:00Z",
            window_end="2026-09-11T00:00:00Z",
            acres_treated=80.0,
            planned_dry_tons=80.000,
        )

        build.set_clock("2026-08-20T06:00:00Z")
        build.start(event_a["id"])
        build.haul_ticket(
            event_a["id"],
            truck_id="T-1",
            wet_tons=400.00,
            depart_at="2026-08-20T08:00:00Z",
            return_at="2026-08-20T10:00:00Z",
            odometer_miles=30.0,
        )
        build.complete(event_a["id"], applied_dry_tons=80.000)

        build.set_clock("2026-09-10T06:00:00Z")
        build.start(event_b["id"])
        build.haul_ticket(
            event_b["id"],
            truck_id="T-1",
            wet_tons=400.00,
            depart_at="2026-09-10T08:00:00Z",
            return_at="2026-09-10T10:00:00Z",
            odometer_miles=30.0,
        )
        build.complete(event_b["id"], applied_dry_tons=80.000)
        return event_a, event_b

    def test_site_totals_sum_the_already_rounded_ledger_rows(self, base_world):
        """PRD §2.10: "At read time, the site's `cumulative_loading_kg_per_hectare` is a map from analyte name to the **sum of the already-rounded deltas** of every ledger entry for that site and analyte, with both entry types included and no status filter, because ledger rows are immutable and are never soft-deleted."

        Two closed-out applications of 80.000 dry tons on 80.0 acres each post a
        delta rounded to 0.0448 kg/ha, and the site total is the sum of the rounded
        rows: 0.0896, not the 0.0897 that summing the unrounded increments gives.

        Headroom is measured against the same rounded total, leaving 38.9104 kg/ha of
        cumulative headroom and 1.8104 kg/ha of annual headroom for CADMIUM.

        Design: Difficulty/combinatorial_formula/loading_ledger_rounds_each_entry_before_summing
        """
        self._two_applications(base_world)

        summary = base_world.build.loading_summary(base_world.site_id)
        assert_loading_delta(summary["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.0896)
        assert summary["cumulative_loading_kg_per_hectare"]["CADMIUM"] != 0.0897
        assert_loading_delta(
            summary["annual_loading_kg_per_hectare"]["2026:CADMIUM"], 0.0896
        )
        assert_loading_delta(summary["cplr_headroom_kg_per_hectare"]["CADMIUM"], 38.9104)
        assert_loading_delta(summary["aplr_headroom_kg_per_hectare"]["CADMIUM"], 1.8104)

    def test_each_ledger_row_is_rounded_on_the_way_in(self, base_world):
        """PRD §2.10: "The rounding order here is pinned and normative: **round each ledger entry, then sum**."

        Exactly two APPLICATION rows are written, each carrying the per-entry
        rounded delta 0.0448 and the applied year taken from the window start, and the
        two closed-out events drain the batch's 800.00 wet tons out of storage.

        Design: Difficulty/combinatorial_formula/loading_ledger_rounds_each_entry_before_summing
        """
        build = base_world.build
        self._two_applications(base_world)

        entries = build.ledger_entries(site_id=base_world.site_id)
        assert len(entries) == 2
        for entry in entries:
            assert entry["entry_type"] == C.ENTRY_APPLICATION
            assert entry["applied_year"] == 2026
            assert entry["analyte"] == "CADMIUM"
            assert entry["reversal_of_id"] is None
            assert_loading_delta(entry["kg_per_hectare_delta"], 0.0448)

        site = build.read_site(base_world.site_id)
        assert site["status"] == C.SITE_PERMITTED

        facility = build.read_facility(base_world.facility_id)
        assert_wet_tons(facility["storage_used_wet_tons"], 0.00)


class TestOutletCostEscalatorOrder:
    @staticmethod
    def _three_outlets(build):
        compost = build.outlet(
            name="Greenfield Compost",
            outlet_type=C.OUTLET_COMPOST,
            gate_fee_per_wet_ton=12.00,
            haul_rate_per_mile_per_wet_ton=0.2400,
            min_load_wet_tons=25.00,
            max_annual_wet_tons=5000,
            min_percent_solids=15.0,
        )
        landfill = build.outlet(
            name="County Landfill Cell 4",
            outlet_type=C.OUTLET_LANDFILL,
            gate_fee_per_wet_ton=20.00,
            haul_rate_per_mile_per_wet_ton=0.3000,
            min_load_wet_tons=25.00,
            max_annual_wet_tons=8000,
            min_percent_solids=15.0,
        )
        thermal = build.outlet(
            name="Regional Thermal Dryer",
            outlet_type=C.OUTLET_THERMAL,
            gate_fee_per_wet_ton=45.00,
            haul_rate_per_mile_per_wet_ton=0.3000,
            min_load_wet_tons=25.00,
            max_annual_wet_tons=3000,
            min_percent_solids=18.0,
        )
        return compost, landfill, thermal

    def test_escalator_touches_hauling_only_so_the_subtotal_misses_the_tier_floor(
        self, build, facility
    ):
        """PRD §3.10: "The escalator applies to hauling **only** and never to the gate fee."

        100.00 wet tons over 30.0 miles at a 12.00 gate fee gives processing
        1200.00 and hauling 777.60 once the 1.08 fuel escalator is applied to the
        hauling leg alone. The subtotal 1977.60 lands 2.40 below the 2000.00 tier
        floor, so the surcharge percentage is 0.00 and the total stays at 1977.60,
        which is 98.88 per dry ton.

        Design: Difficulty/combinatorial_formula/outlet_cost_escalator_applies_to_hauling_before_tier_lookup
        """
        batch = build.dewatered_batch(facility["id"])
        compost, _, _ = self._three_outlets(build)

        order = build.order(
            batch["id"],
            compost["id"],
            batch["version"],
            dry_tons=20.000,
            wet_tons=100.00,
            haul_miles=30.0,
        )
        assert_cost_breakdown(
            order,
            processing=1200.00,
            hauling=777.60,
            subtotal=1977.60,
            surcharge_pct=0.00,
            surcharge=0.00,
            total=1977.60,
            per_dry_ton=98.88,
        )
        assert order["status"] == C.ORDER_DRAFT

    def test_cost_comparison_prices_every_accepting_outlet_on_its_own_tier(
        self, api, build, facility
    ):
        """PRD §3.10: "**The cost comparison read** re-runs the six cost steps for every outlet whose `status` is `ACCEPTING`, using this order's own `wet_tons`, `dry_tons` and `haul_miles` for each candidate."

        The comparison re-runs the six steps for all three ACCEPTING outlets with
        this order's tonnage and mileage, sorts them by cost per dry ton ascending -
        COMPOST 98.88, LANDFILL 153.06, THERMAL 281.81 - and recommends the first.

        The tier lookup is per outlet: the LANDFILL subtotal of 2972.00 clears the
        2000.00 floor and carries a 0.03 surcharge while the COMPOST row carries 0.00.

        Design: Difficulty/combinatorial_formula/outlet_cost_escalator_applies_to_hauling_before_tier_lookup
        """
        batch = build.dewatered_batch(facility["id"])
        compost, _, _ = self._three_outlets(build)
        order = build.order(
            batch["id"],
            compost["id"],
            batch["version"],
            dry_tons=20.000,
            wet_tons=100.00,
            haul_miles=30.0,
        )

        comparison = validate_success(
            api.get_cost_comparison(order["id"], make_operator_headers())
        )
        options = comparison["options"]
        assert len(options) == 3
        assert [option["outlet_type"] for option in options] == [
            C.OUTLET_COMPOST,
            C.OUTLET_LANDFILL,
            C.OUTLET_THERMAL,
        ]
        assert_money(options[0]["cost_per_dry_ton"], 98.88)
        assert_money(options[1]["cost_per_dry_ton"], 153.06)
        assert_money(options[2]["cost_per_dry_ton"], 281.81)
        assert comparison["recommended_outlet_id"] == compost["id"]

        assert options[0]["surcharge_pct"] == 0.00
        assert options[1]["surcharge_pct"] == 0.03
        assert_money(options[1]["subtotal_cost"], 2972.00)
