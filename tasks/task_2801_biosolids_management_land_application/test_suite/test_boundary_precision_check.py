"""Inputs parked on the exact inclusive edge of a threshold, paired with the
nearest input on the other side of it.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_CPLR_HEADROOM_EXCEEDED,
    ERR_INSUFFICIENT_UNALLOCATED_TONS,
)
from test_helpers.assertions import (
    assert_dry_tons,
    assert_percent,
    assert_wet_tons,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    OFFICER_HEADERS,
    make_operator_headers,
)
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVolatileSolidsReductionMinimum:
    def test_van_kleeck_exactly_at_the_minimum_is_accepted(self, api, build, facility):
        """PRD §3.2: "The gate compares the **rounded** `vsr_pct_van_kleeck` against 38.00, and a value of exactly 38.00 passes."

        A digester run leaving 43.11% volatile solids from a 55.00% feed reduces
        volatile solids by exactly 38.00% on the van Kleeck formula, which is the
        inclusive vector attraction minimum, so the quality dimension stays UNTESTED
        with no rejection reason while the process dimension advances to DIGESTED.

        Design: Difficulty/boundary_precision_check/vsr_exactly_at_thirty_eight_percent_is_accepted
        """
        batch = build.batch(facility["id"], volatile_solids_in_pct=55.00)

        digested = validate_success(
            api.advance_process(
                batch["id"],
                F.digest_payload(volatile_solids_out_pct=43.11),
                make_operator_headers(facility["id"]),
            )
        )

        assert_percent(digested["vsr_pct_van_kleeck"], 38.00)
        assert_percent(digested["vsr_pct_mass_balance"], 37.29)
        assert digested["process_status"] == C.PROCESS_DIGESTED
        assert digested["quality_status"] == C.QUALITY_UNTESTED
        assert digested["rejection_reason"] is None

    def test_one_hundredth_below_the_minimum_rejects_the_quality_dimension(
        self, api, build, facility
    ):
        """PRD §3.2: "This rejection is deliberately **not** a ceiling exceedance: it does not set `ceiling_exceedance_flag`, it does not change the facility's `open_ceiling_exceedance_count`, and it therefore does not freeze the plant."

        One hundredth of a percent more volatile solids in the outlet stream, 43.12%,
        drops van Kleeck to 37.97 and rejects the quality dimension with
        VSR_BELOW_MINIMUM, while the process dimension still advances and the plant is
        untouched because a vector attraction miss is not a ceiling exceedance.

        Design: Difficulty/boundary_precision_check/vsr_exactly_at_thirty_eight_percent_is_accepted
        """
        batch = build.batch(facility["id"], volatile_solids_in_pct=55.00)

        digested = validate_success(
            api.advance_process(
                batch["id"],
                F.digest_payload(volatile_solids_out_pct=43.12),
                make_operator_headers(facility["id"]),
            )
        )

        assert_percent(digested["vsr_pct_van_kleeck"], 37.97)
        assert digested["process_status"] == C.PROCESS_DIGESTED
        assert digested["quality_status"] == C.QUALITY_REJECTED
        assert digested["rejection_reason"] == "VSR_BELOW_MINIMUM"
        assert digested["ceiling_exceedance_flag"] is False

        current_facility = build.read_facility(facility["id"])
        assert current_facility["posture"] == C.POSTURE_OPEN


class TestCumulativeLoadingHeadroomEquality:
    @staticmethod
    def _tight_world(build):
        facility = build.facility()
        build.limit(cplr_kg_per_hectare=0.1793)
        batch = build.qualified_batch(facility["id"])
        site = build.permitted_site(facility["id"])
        agreement = build.active_agreement(site["id"], site["version"])
        build.weather(site["id"])
        return facility, batch, site, agreement

    def test_projection_exactly_equal_to_the_limit_is_scheduled(self, api, build):
        """PRD §2.7: "**Priority 52 — cumulative loading headroom.** For every analyte with a CPLR, the site's cumulative loading plus this event's rounded increment is at most `cplr_kg_per_hectare`; equality is accepted."

        80.000 dry tons on 20.0 acres is 4.00 dry tons per acre, which projects a
        cumulative cadmium increment of exactly 0.1793 kg/ha against a 0.1793 kg/ha
        limit. Equality passes, so the window is SCHEDULED at a requested rate of 4.00
        under the 9.88 nitrogen-bound agronomic cap.

        Design: Difficulty/boundary_precision_check/cplr_projection_exactly_equal_to_limit_is_accepted
        """
        _, batch, site, agreement = self._tight_world(build)

        event = validate_success(
            api.create_event(
                F.event_payload(
                    site["id"],
                    batch["id"],
                    agreement["id"],
                    acres_treated=20.0,
                    planned_dry_tons=80.000,
                ),
                AGRONOMIST_HEADERS,
            ),
            201,
        )

        assert event["status"] == C.EVENT_SCHEDULED
        assert_percent(event["requested_rate_dry_tons_per_acre"], 4.00)
        assert_percent(event["agronomic_rate_cap_dry_tons_per_acre"], 9.88)
        assert event["binding_rate_constraint"] == C.BINDING_NITROGEN

    def test_projection_one_ten_thousandth_over_the_limit_is_refused(self, api, build):
        """PRD §3.7: "Strictly greater than the limit is `ERR_CPLR_HEADROOM_EXCEEDED`; equality passes."

        80.200 dry tons on the same 20.0 acres is 4.01 per acre and projects 0.1798,
        which exceeds the 0.1793 limit, so the second window is refused for headroom
        rather than for the 80.000 remaining unallocated tons; scheduling writes no
        ledger row and releases no tonnage.

        Design: Difficulty/boundary_precision_check/cplr_projection_exactly_equal_to_limit_is_accepted
        """
        _, batch, site, agreement = self._tight_world(build)
        build.event(
            site["id"],
            batch["id"],
            agreement["id"],
            acres_treated=20.0,
            planned_dry_tons=80.000,
        )

        response = api.create_event(
            F.event_payload(
                site["id"],
                batch["id"],
                agreement["id"],
                window_start="2026-09-10T00:00:00Z",
                window_end="2026-09-11T00:00:00Z",
                acres_treated=20.0,
                planned_dry_tons=80.200,
            ),
            AGRONOMIST_HEADERS,
        )
        error = validate_error(response, ERR_CPLR_HEADROOM_EXCEEDED)
        assert error["error_id"] != ERR_INSUFFICIENT_UNALLOCATED_TONS

        current_site = build.read_site(site["id"])
        assert current_site["status"] == C.SITE_PERMITTED
        _, meta = validate_paginated(
            api.list_ledger_entries(OFFICER_HEADERS, {"site_id": site["id"]})
        )
        assert meta["total_count"] == 0
        assert_dry_tons(build.read_batch(batch["id"])["unallocated_dry_tons"], 80.000)


class TestStorageProjectionZeroNetChange:
    @staticmethod
    def _matched_world(build):
        facility = build.facility(daily_production_wet_tons=10.00, storage_capacity_wet_tons=5000.00)
        build.limit()
        batch = build.dewatered_batch(facility["id"])
        outlet = build.outlet(
            gate_fee_per_wet_ton=12.00,
            haul_rate_per_mile_per_wet_ton=0.2400,
            min_load_wet_tons=25.00,
        )
        order = build.order(
            batch["id"], outlet["id"], batch["version"],
            dry_tons=60.000, wet_tons=300.00, haul_miles=30.0,
        )
        build.commit_order(order["id"])
        return facility, batch, order

    def test_zero_daily_net_change_returns_the_sentinel(self, api, build):
        """PRD §3.1: "When `daily_net` is at or below 0 — that is, when committed removals match or outpace production — `days_of_capacity` is the sentinel 9999."

        A single COMMITTED diversion of 300.00 wet tons over the 30-day horizon
        removes 10.0000 wet tons a day, exactly matching the 10.00 wet tons a day of
        production, so the daily net change is 0.0000 and days_of_capacity is the 9999
        sentinel instead of a division by zero.

        Design: Difficulty/boundary_precision_check/storage_projection_with_zero_net_change_returns_sentinel
        """
        facility, _, _ = self._matched_world(build)

        projection = validate_success(api.get_storage_projection(facility["id"], OFFICER_HEADERS))

        assert projection["days_of_capacity"] == C.DAYS_OF_CAPACITY_SENTINEL
        assert_wet_tons(projection["projected_outflow_wet_tons"], 300.00)
        assert_wet_tons(projection["storage_capacity_wet_tons"], 5000.00)

    def test_committed_order_counts_toward_outflow_without_debiting_storage(
        self, api, build
    ):
        """PRD §2.9: "A `DRAFT` or `COMMITTED` diversion order does **not** debit storage, which is why voiding a committed order leaves storage untouched while still returning the dry tons."

        The committed order is already part of the projected outflow, yet storage
        still holds all 800.00 wet tons at 16.00% utilization with the plant OPEN,
        because only settlement debits storage; the order's tonnage does leave the
        batch's unallocated pool.

        Design: Difficulty/boundary_precision_check/storage_projection_with_zero_net_change_returns_sentinel
        """
        facility, batch, order = self._matched_world(build)

        projection = validate_success(api.get_storage_projection(facility["id"], OFFICER_HEADERS))
        assert_wet_tons(projection["storage_used_wet_tons"], 800.00)
        assert_percent(projection["storage_utilization_pct"], 16.00)
        assert projection["posture"] == C.POSTURE_OPEN

        assert build.read_order(order["id"])["status"] == C.ORDER_COMMITTED
        assert_dry_tons(build.read_batch(batch["id"])["unallocated_dry_tons"], 100.000)
