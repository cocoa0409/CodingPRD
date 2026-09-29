"""Reversals that restore a conserved quantity to its exact prior value by writing
a compensating record, never by editing or deleting the original.
"""

from test_helpers import constants as C
from test_helpers.assertions import (
    assert_application_entry,
    assert_cost_breakdown,
    assert_dry_tons,
    assert_facility_storage,
    assert_loading_delta,
    assert_reversal_entry,
    assert_wet_tons,
)
from test_helpers.test_users import OFFICER_HEADERS, make_officer_headers
from prd_bench_local_runner.testing import validate_paginated, validate_success


def _rows_by_type(entries):
    return {entry["entry_type"]: entry for entry in entries}


class TestVoidRestoresSiteMetalLoading:
    @staticmethod
    def _completed_then_voided(world):
        build = world["build"]
        build.complete(world["event_a"]["id"], applied_dry_tons=80.000)
        return build.void(world["event_a"]["id"])

    def test_void_writes_a_reversal_row_and_lifts_the_restriction(
        self, api, tight_cplr_world
    ):
        """PRD §2.10: "On the void of a completed event, one entry with `entry_type` `REVERSAL` is written for each `APPLICATION` entry of that event, in the same ascending analyte order, with `reversal_of_id` naming the entry it offsets and `kg_per_hectare_delta` the **exact negation** of that entry's already-rounded delta."

        The void leaves the +0.1793 APPLICATION row exactly as written and adds a
        -0.1793 REVERSAL row pointing at it, so the site's cumulative cadmium loading is
        back to 0.0000 with the full 0.1900 kg/ha of headroom, and the CPLR-driven
        restriction lifts back to PERMITTED with no reason recorded.

        Design: Difficulty/compensating_invariant/void_restores_site_metal_loading_to_exact_prior_value
        """
        site_id = tight_cplr_world["site"]["id"]
        event_a_id = tight_cplr_world["event_a"]["id"]
        self._completed_then_voided(tight_cplr_world)

        entries, meta = validate_paginated(
            api.list_ledger_entries(OFFICER_HEADERS, {"site_id": site_id})
        )
        assert meta["total_count"] == 2
        rows = _rows_by_type(entries)
        application = rows[C.ENTRY_APPLICATION]
        reversal = rows[C.ENTRY_REVERSAL]

        assert_application_entry(application, site_id, event_a_id)
        assert_loading_delta(application["kg_per_hectare_delta"], 0.1793)
        assert application["applied_year"] == 2026
        assert_reversal_entry(reversal, application["id"])
        assert_loading_delta(reversal["kg_per_hectare_delta"], -0.1793)

        summary = validate_success(api.get_loading_summary(site_id, OFFICER_HEADERS))
        assert_loading_delta(summary["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.0000)
        assert_loading_delta(
            summary["annual_loading_kg_per_hectare"]["2026:CADMIUM"], 0.0000
        )
        assert_loading_delta(summary["cplr_headroom_kg_per_hectare"]["CADMIUM"], 0.1900)

        site = tight_cplr_world["build"].read_site(site_id)
        assert site["status"] == C.SITE_PERMITTED
        assert site["restriction_reason"] is None

    def test_compensation_keeps_the_audit_trail_and_does_not_reschedule_the_sibling(
        self, api, tight_cplr_world
    ):
        """PRD §2.11: "Second, no cascade ever auto-reschedules a deferred event: once the restriction that deferred it is lifted, each event must be rescheduled explicitly with a fresh window."

        The voided event retains its applied tonnages for audit while its tonnage
        returns to the batch and its wet tons return to the pad. The sibling event that
        the restriction deferred stays DEFERRED: compensation restores quantities, it is
        not an undo of the cascade.

        Design: Difficulty/compensating_invariant/void_restores_site_metal_loading_to_exact_prior_value
        """
        build = tight_cplr_world["build"]
        voided = self._completed_then_voided(tight_cplr_world)

        assert voided["status"] == C.EVENT_VOIDED
        assert voided["voided_at"] is not None
        assert_dry_tons(voided["applied_dry_tons"], 80.000)
        assert_wet_tons(voided["applied_wet_tons"], 400.00)

        sibling = build.read_event(tight_cplr_world["event_b"]["id"])
        assert sibling["status"] == C.EVENT_DEFERRED
        assert sibling["defer_reason"] == "SITE_RESTRICTED"

        assert_dry_tons(
            build.read_batch(tight_cplr_world["batch"]["id"])["unallocated_dry_tons"],
            80.000,
        )
        assert_facility_storage(
            build.read_facility(tight_cplr_world["facility"]["id"]), 800.00, 16.00
        )


class TestVoidRestoresBatchDryTons:
    @staticmethod
    def _committed_order(build):
        facility = build.facility()
        build.limit()
        batch = build.dewatered_batch(facility["id"])
        outlet = build.outlet(
            gate_fee_per_wet_ton=12.00,
            haul_rate_per_mile_per_wet_ton=0.2400,
            min_load_wet_tons=25.00,
            max_annual_wet_tons=5000.00,
            min_percent_solids=15.0,
        )
        order = build.order(
            batch["id"], outlet["id"], batch["version"],
            dry_tons=60.000, wet_tons=300.00, haul_miles=30.0,
        )
        build.commit_order(order["id"])
        return facility, batch, outlet, order

    def test_voided_order_keeps_its_costed_history(self, api, build):
        """PRD §3.10: "**Voiding** is a `ComplianceOfficer` action from `DRAFT` or `COMMITTED`, requiring a `void_reason`; from `SETTLED` or `VOIDED` it is `ERR_ORDER_INVALID_STATE`."

        Voiding the committed diversion sets VOIDED with the supplied reason and keeps
        the commitment stamp, and every costed figure survives on the voided row - the
        compensation is financial history, not deletion.

        Design: Difficulty/compensating_invariant/diversion_void_restores_batch_dry_tons_conservation
        """
        _, batch, _, order = self._committed_order(build)

        voided = validate_success(
            api.void_order(
                order["id"],
                OFFICER_HEADERS,
                {"void_reason": "Compost site suspended intake after a wet-weather washout"},
            )
        )

        assert voided["status"] == C.ORDER_VOIDED
        assert voided["void_reason"] is not None
        assert voided["committed_at"] is not None
        assert_cost_breakdown(
            voided,
            processing=3600.00,
            hauling=2332.80,
            subtotal=5932.80,
            surcharge_pct=0.03,
            surcharge=177.98,
            total=6110.78,
            per_dry_ton=101.85,
        )

        _, meta = validate_paginated(
            api.list_diversion_orders(OFFICER_HEADERS, {"batch_id": batch["id"]})
        )
        assert meta["total_count"] == 1

    def test_void_returns_the_tonnage_and_unwinds_the_outlet_acceptance(self, api, build):
        """PRD §2.9: "A `DRAFT` or `COMMITTED` diversion order does **not** debit storage, which is why voiding a committed order leaves storage untouched while still returning the dry tons."

        All 60.000 dry tons return to the batch, so produced equals unallocated again
        with nothing reserved, applied or diverted; the outlet's annual acceptance drops
        back to 0.00 wet tons; and storage never moved, because a committed order that is
        never settled never debits the pad.

        Design: Difficulty/compensating_invariant/diversion_void_restores_batch_dry_tons_conservation
        """
        facility, batch, outlet, order = self._committed_order(build)

        validate_success(
            api.void_order(
                order["id"],
                make_officer_headers("officer-close-2"),
                {"void_reason": "Compost site suspended intake after a wet-weather washout"},
            )
        )

        current_batch = build.read_batch(batch["id"])
        assert_dry_tons(current_batch["unallocated_dry_tons"], 160.000)
        assert_dry_tons(current_batch["dry_tons_produced"], 160.000)

        assert_wet_tons(build.read_outlet(outlet["id"])["ytd_accepted_wet_tons"], 0.00)
        assert_facility_storage(build.read_facility(facility["id"]), 800.00, 16.00)
