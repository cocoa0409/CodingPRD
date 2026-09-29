"""Read-your-writes: every cascade this service performs is immediate, so the
response that triggers it and the very next read already carry every effect.
"""

from test_helpers import constants as C
from test_helpers.assertions import (
    assert_dry_tons,
    assert_facility_storage,
    assert_loading_delta,
    assert_wet_tons,
)
from test_helpers.test_users import AGRONOMIST_HEADERS, OFFICER_HEADERS
from prd_bench_local_runner.testing import validate_success


class TestRestrictionCascadeIsVisibleImmediately:
    def test_the_restrict_response_and_the_next_event_read_already_show_the_cascade(
        self, api, base_world
    ):
        """PRD §3.5: "In all three cases the cascade is identical: every application event on the site whose `status` is `SCHEDULED` or `WEATHER_HOLD` moves to `DEFERRED` with `defer_reason` `SITE_RESTRICTED` (or `ODOR_RISK` when the odor cascade drove it), each incrementing its own `version` by 1, and each **retaining** its `reserved_dry_tons` rather than releasing it."

        No second write and no delay separate a restriction from its deferrals. The
        restrict response itself already reads RESTRICTED with reason OFFICER_ORDER, and the
        sibling event read immediately afterwards is already DEFERRED with defer_reason
        SITE_RESTRICTED at version 2, still holding its 80.000 reserved dry tons, because a
        deferral parks a window without releasing the tonnage behind it.

        Design: Corner/consistency_model/consistency_immediate_cascade_is_visible_in_the_same_response
        """
        w = base_world
        build = w.build
        event = build.event(w.site_id, w.batch_id, w.agreement_id)
        assert event["status"] == C.EVENT_SCHEDULED

        restricted = validate_success(api.restrict_site(w.site_id, {}, OFFICER_HEADERS))
        assert restricted["status"] == C.SITE_RESTRICTED
        assert restricted["restriction_reason"] == "OFFICER_ORDER"

        deferred = validate_success(api.get_event(event["id"], AGRONOMIST_HEADERS))
        assert deferred["status"] == C.EVENT_DEFERRED
        assert deferred["defer_reason"] == "SITE_RESTRICTED"
        assert_dry_tons(deferred["reserved_dry_tons"], 80.000)
        assert deferred["version"] == 2


class TestCrossAggregateWritesAreVisibleWithoutDelay:
    def test_one_close_out_lands_the_event_the_storage_and_the_ledger_at_once(
        self, api, base_world
    ):
        """PRD §3.8: "Close-out also debits storage: `applied_wet_tons` is subtracted from the facility's `storage_used_wet_tons`, `storage_utilization_pct` and `posture` are re-derived, and the facility's `version` is incremented by 1."

        A single close-out writes three aggregates on three different rows and all three
        are readable at once. The event response carries applied_wet_tons 400.00, the
        facility read immediately shows storage drawn from 800.00 down to 400.00 at 8.00
        percent utilization, and the site's loading summary immediately shows 0.0359 kg/ha
        of cumulative cadmium with 38.9641 kg/ha of headroom left against the 39.0 limit.

        Design: Corner/consistency_model/consistency_immediate_cross_aggregate_fields_are_visible_without_delay
        """
        w = base_world
        build = w.build

        completed = build.completed_event(
            w.site_id, w.batch_id, w.agreement_id,
            clock_at="2026-08-20T06:00:00Z",
            ticket_wet_tons=400.00,
            complete_kwargs={"applied_dry_tons": 80.000},
        )
        assert completed["status"] == C.EVENT_COMPLETED
        assert_wet_tons(completed["applied_wet_tons"], 400.00)
        assert_dry_tons(completed["applied_dry_tons"], 80.000)

        current_facility = build.read_facility(w.facility_id)
        assert_facility_storage(current_facility, 400.00, 8.00, C.POSTURE_OPEN)

        summary = validate_success(
            api.get_loading_summary(w.site_id, AGRONOMIST_HEADERS)
        )
        assert_loading_delta(summary["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.0359)
        assert_loading_delta(summary["cplr_headroom_kg_per_hectare"]["CADMIUM"], 38.9641)
