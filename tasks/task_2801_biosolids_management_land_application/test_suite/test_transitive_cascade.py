"""Multi-hop cascades where each hop is caused by the previous hop's write, not
by anything named in the triggering request.
"""

from test_helpers import constants as C
from test_helpers.assertions import (
    assert_dry_tons,
    assert_loading_delta,
    assert_percent,
    assert_wet_tons,
)
from test_helpers.test_users import OFFICER_HEADERS
from prd_bench_local_runner.testing import validate_paginated


class TestCompletionCascade:
    def test_ledger_write_re_sums_the_site_and_trips_the_restriction(
        self, tight_cplr_world
    ):
        """PRD §3.8: "*Hop 4.* Caused by hop 3: when any analyte's cumulative loading has reached 0.90 multiplied by that analyte's `cplr_kg_per_hectare`, the site moves `PERMITTED` to `RESTRICTED` with `restriction_reason` `CPLR_HEADROOM_LOW`, and every **sibling** application event on that site whose `status` is `SCHEDULED` or `WEATHER_HOLD` moves to `DEFERRED` with `defer_reason` `SITE_RESTRICTED`, each incrementing its own `version` by 1 and each retaining its `reserved_dry_tons`."

        Closing one application at 4.00 dry tons per acre posts a single ledger row
        of 0.1793 kg/ha, the site total is re-summed from that row, and because
        0.1793 has reached 0.90 of the 0.19 kg/ha cumulative limit the site is
        restricted with reason CPLR_HEADROOM_LOW - none of which the close-out
        request mentions.

        Design: Difficulty/transitive_cascade/completion_cascade_restricts_site_then_defers_sibling_event
        """
        build = tight_cplr_world["build"]
        site = tight_cplr_world["site"]
        event_a = tight_cplr_world["event_a"]
        build.complete(event_a["id"], applied_dry_tons=80.000)

        entries = build.ledger_entries(site_id=site["id"])
        assert len(entries) == 1
        entry = entries[0]
        assert entry["entry_type"] == C.ENTRY_APPLICATION
        assert entry["analyte"] == "CADMIUM"
        assert entry["source_event_id"] == event_a["id"]
        assert entry["applied_year"] == 2026
        assert_loading_delta(entry["kg_per_hectare_delta"], 0.1793)

        restricted = build.read_site(site["id"])
        assert_loading_delta(
            restricted["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.1793
        )
        assert restricted["status"] == C.SITE_RESTRICTED
        assert restricted["restriction_reason"] == "CPLR_HEADROOM_LOW"

    def test_restriction_defers_the_sibling_event_and_settles_the_quantities(
        self, tight_cplr_world
    ):
        """PRD §2.11: "First, a deferral **retains** the event's `reserved_dry_tons`, whereas a cancellation **releases** it back to the batch; the distinction is what keeps the dry-tons invariant true through both paths."

        The site restriction in turn defers the untouched sibling event with reason
        SITE_RESTRICTED while it keeps its 80.000 reserved dry tons, and the closed
        event settles its own quantities: 80.000 applied dry tons, 400.00 applied wet
        tons from its single haul ticket, nothing left reserved, and the closing
        officer recorded.

        Design: Difficulty/transitive_cascade/completion_cascade_restricts_site_then_defers_sibling_event
        """
        build = tight_cplr_world["build"]
        facility = tight_cplr_world["facility"]
        batch = tight_cplr_world["batch"]
        event_a = tight_cplr_world["event_a"]
        event_b = tight_cplr_world["event_b"]
        completed = build.complete(event_a["id"], applied_dry_tons=80.000)

        assert completed["status"] == C.EVENT_COMPLETED
        assert_dry_tons(completed["applied_dry_tons"], 80.000)
        assert_wet_tons(completed["applied_wet_tons"], 400.00)
        assert_dry_tons(completed["reserved_dry_tons"], 0.000)
        assert completed["completed_by_user_id"] == "officer-close-2"

        deferred = build.read_event(event_b["id"])
        assert deferred["status"] == C.EVENT_DEFERRED
        assert deferred["defer_reason"] == "SITE_RESTRICTED"
        assert_dry_tons(deferred["reserved_dry_tons"], 80.000)

        current_facility = build.read_facility(facility["id"])
        assert_wet_tons(current_facility["storage_used_wet_tons"], 400.00)
        assert_percent(current_facility["storage_utilization_pct"], 8.00)

        current_batch = build.read_batch(batch["id"])
        assert_dry_tons(current_batch["unallocated_dry_tons"], 0.000)


class TestCeilingExceedanceCascade:
    @staticmethod
    def _scheduled_event_then_lead_limit(base_world):
        build = base_world.build
        event = build.event(
            base_world.site_id,
            base_world.batch_id,
            base_world.agreement_id,
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-21T00:00:00Z",
            acres_treated=80.0,
            planned_dry_tons=80.000,
        )
        build.limit(
            analyte="LEAD",
            ceiling_mg_kg=300.0,
            monthly_avg_mg_kg=200.0,
            aplr_kg_per_hectare_yr=21.0,
            cplr_kg_per_hectare=300.0,
        )
        return event

    def test_confirmatory_result_withdraws_the_certification(self, base_world):
        """PRD §3.4: "*Hop 1.* The batch's `ceiling_exceedance_flag` is set true, `quality_status` moves to `REJECTED` and `rejection_reason` is set to `CEILING_EXCEEDED`."

        A LEAD result of 400.0 mg/kg against a ceiling of 300.0 arrives after the
        batch was certified. The exceedance rejects the batch, raises the exceedance
        flag, records CEILING_EXCEEDED and clears the certification stamp that the
        earlier sign-off had written.

        Design: Difficulty/transitive_cascade/ceiling_exceedance_cascade_cancels_event_then_freezes_facility
        """
        build = base_world.build
        self._scheduled_event_then_lead_limit(base_world)

        result = build.lab_result(
            base_world.batch_id,
            analyte="LEAD",
            concentration_mg_kg=400.0,
            sampling_event_index=0,
            analyzed_at="2026-08-10T00:00:00Z",
        )
        assert result["exceeds_ceiling"] is True

        batch = build.read_batch(base_world.batch_id)
        assert batch["quality_status"] == C.QUALITY_REJECTED
        assert batch["ceiling_exceedance_flag"] is True
        assert batch["rejection_reason"] == "CEILING_EXCEEDED"
        assert batch["certified_at"] is None
        assert batch["certified_by_user_id"] is None

    def test_withdrawn_certification_cancels_the_event_and_freezes_the_plant(
        self, api, base_world
    ):
        """PRD §3.4: "*Hop 3.* Caused by hop 1: the facility's `open_ceiling_exceedance_count` is recomputed upward, its `posture` is re-derived, and because the count is now greater than 0 the posture becomes `FROZEN`."

        The flag flip cancels the scheduled application and returns its 80.000
        reserved dry tons to the batch, and that rejected-with-exceedance batch drives
        the facility's open exceedance count to 1 and freezes the plant. The site was
        never applied to, so it stays PERMITTED with no ledger rows, and the batch's
        wet tons are still in storage.

        Design: Difficulty/transitive_cascade/ceiling_exceedance_cascade_cancels_event_then_freezes_facility
        """
        build = base_world.build
        event = self._scheduled_event_then_lead_limit(base_world)
        build.lab_result(
            base_world.batch_id,
            analyte="LEAD",
            concentration_mg_kg=400.0,
            sampling_event_index=0,
            analyzed_at="2026-08-10T00:00:00Z",
        )

        cancelled = build.read_event(event["id"])
        assert cancelled["status"] == C.EVENT_CANCELLED
        assert_dry_tons(cancelled["reserved_dry_tons"], 0.000)

        batch = build.read_batch(base_world.batch_id)
        assert_dry_tons(batch["unallocated_dry_tons"], 160.000)

        facility = build.read_facility(base_world.facility_id)
        assert facility["open_ceiling_exceedance_count"] == 1
        assert facility["posture"] == C.POSTURE_FROZEN
        assert_wet_tons(facility["storage_used_wet_tons"], 800.00)

        site = build.read_site(base_world.site_id)
        assert site["status"] == C.SITE_PERMITTED
        _, meta = validate_paginated(
            api.list_ledger_entries(OFFICER_HEADERS, {"site_id": base_world.site_id})
        )
        assert meta["total_count"] == 0
