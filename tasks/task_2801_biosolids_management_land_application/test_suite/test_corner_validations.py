"""Validation-ladder corners: two simultaneous violations resolved by priority, a
method-conditional rule that both blocks and permits, and boundary instants.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import (
    ERR_ANALYTE_PANEL_INCOMPLETE,
    ERR_BATCH_NOT_FOUND,
    ERR_INSUFFICIENT_UNALLOCATED_TONS,
    ERR_PATHOGEN_CLASS_INSUFFICIENT,
    ERR_REAPPLICATION_INTERVAL,
    ERR_SETBACK_VIOLATION,
    ERR_STORAGE_CAPACITY_EXCEEDED,
    ERR_UNAUTHORIZED,
    ERR_WEATHER_RESTRICTION,
)
from test_helpers.assertions import (
    assert_dry_tons,
    assert_facility_storage,
    assert_instant_equals,
    assert_loading_delta,
    assert_pan,
    assert_percent,
    assert_wet_tons,
)
from test_helpers.test_users import (
    AGRONOMIST_HEADERS,
    CERTIFYING_OFFICER_HEADERS,
    LAB_ANALYST_HEADERS,
    make_operator_headers,
)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_success,
)


class TestRoleCheckOutranksExistence:
    def test_lab_analyst_certifying_a_missing_batch_is_unauthorized(self, api, facility):
        """PRD §2.7: "This ordering is part of the contract: a request that is both unauthorized and malformed returns `ERR_UNAUTHORIZED`, not `ERR_INVALID_REQUEST`, and a request naming a non-existent site with an out-of-range rate returns `ERR_SITE_NOT_FOUND`, not `ERR_AGRONOMIC_RATE_EXCEEDED`."

        A LabAnalyst is not among the roles allowed to certify, and the batch id does
        not exist either. Two rules are violated, and the role check at priority 2
        answers first with ERR_UNAUTHORIZED, so the 403 leaks nothing about whether the
        batch exists.

        Design: Corner/validations/val_role_check_outranks_existence_on_certify
        """
        error = validate_error(
            api.certify_batch(NON_EXISTENT_UUID, LAB_ANALYST_HEADERS),
            ERR_UNAUTHORIZED,
            403,
        )
        assert error["error_id"] != ERR_BATCH_NOT_FOUND


class TestPathogenCheckOutranksPanelCompleteness:
    def test_pathogen_class_answers_before_the_missing_analyte_panel(
        self, api, build, facility, cadmium_limit
    ):
        """PRD §2.7: "**Priority 33 — pathogen class.** The batch's derived `pathogen_class` is `CLASS_B` or `CLASS_A`, otherwise `ERR_PATHOGEN_CLASS_INSUFFICIENT` (422)."

        The batch fails the pathogen rule (10.0 detention days against the 15.0-day
        constant) and the panel rule (no laboratory result at all for the ACTIVE CADMIUM
        limit) in the same request. Priority 33 speaks before priority 35, so the answer
        is ERR_PATHOGEN_CLASS_INSUFFICIENT.

        Design: Corner/validations/val_pathogen_class_check_outranks_incomplete_analyte_panel
        """
        batch = build.batch(facility["id"], detention_days=10.0, digester_temp_c=36.0)
        build.digest(batch["id"], detention_days=10.0, digester_temp_c=36.0)
        build.dewater(batch["id"])

        error = validate_error(
            api.certify_batch(batch["id"], CERTIFYING_OFFICER_HEADERS),
            ERR_PATHOGEN_CLASS_INSUFFICIENT,
        )
        assert error["error_id"] != ERR_ANALYTE_PANEL_INCOMPLETE

        current = build.read_batch(batch["id"])
        assert current["pathogen_class"] == C.PATHOGEN_CLASS_NONE
        assert current["quality_status"] == C.QUALITY_PENDING_RESULTS


class TestMethodConditionalSetback:
    @staticmethod
    def _site_close_to_surface_water(build):
        facility = build.facility()
        build.limit()
        batch = build.qualified_batch(facility["id"])
        site = build.permitted_site(facility["id"], setback_to_surface_water_ft=80)
        agreement = build.active_agreement(site["id"], site["version"])
        build.weather(site["id"])
        return batch, site, agreement

    def test_surface_is_refused_and_incorporated_is_accepted_on_the_same_site(
        self, api, build
    ):
        """PRD §3.7: "**The method-conditional setbacks.** Independently of the baseline siting screen, the placement method demands its own clearances: `SURFACE` requires the site's `setback_to_surface_water_ft` to be at or above 100 **and** `slope_pct` to be at or below 15.0; `INCORPORATED` requires `setback_to_surface_water_ft` at or above 66; `INJECTED` requires `setback_to_surface_water_ft` at or above 33; and every method requires `setback_to_well_ft` at or above 100."

        80 feet from surface water is below the 100 SURFACE placement demands and
        above the 66 INCORPORATED demands, so the identical window is refused for one
        method and accepted for the other. The accepted method also lifts the
        volatilization factor from 0.50 to 0.75, which raises plant-available nitrogen
        to 18.2000 lb per dry ton and lowers the nitrogen-bound cap to 8.79.

        Design: Corner/validations/val_surface_setback_blocks_the_event_while_incorporated_method_passes
        """
        batch, site, agreement = self._site_close_to_surface_water(build)

        validate_error(
            api.create_event(
                F.event_payload(
                    site["id"],
                    batch["id"],
                    agreement["id"],
                    application_method=C.METHOD_SURFACE,
                ),
                AGRONOMIST_HEADERS,
            ),
            ERR_SETBACK_VIOLATION,
        )

        accepted = validate_success(
            api.create_event(
                F.event_payload(
                    site["id"],
                    batch["id"],
                    agreement["id"],
                    application_method=C.METHOD_INCORPORATED,
                ),
                AGRONOMIST_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == C.EVENT_SCHEDULED
        assert accepted["application_method"] == C.METHOD_INCORPORATED
        assert_pan(accepted["plant_available_n_lb_per_dry_ton"], 18.2000)
        assert_percent(accepted["agronomic_rate_cap_dry_tons_per_acre"], 8.79)
        assert accepted["binding_rate_constraint"] == C.BINDING_NITROGEN
        assert_percent(accepted["requested_rate_dry_tons_per_acre"], 0.80)


class TestWeatherClearanceBlocksStart:
    def test_heavy_rainfall_observation_blocks_an_otherwise_startable_event(
        self, api, base_world
    ):
        """PRD §2.7: "**Priority 39 — weather clearance.** The site's `weather_clearance_ok` is true, otherwise `ERR_WEATHER_RESTRICTION` (422)."

        The event is inside its half-open window and every other live condition holds;
        only the site-level observation of 0.60 inches of rain in 24 hours - over the
        0.50 inch bound - flips weather_clearance_ok to false, and start is refused with
        ERR_WEATHER_RESTRICTION while the event stays SCHEDULED with no hold recorded.

        Design: Corner/validations/val_weather_restriction_blocks_start_after_heavy_rainfall
        """
        w = base_world
        build = w.build
        event = build.event(w.site_id, w.batch_id, w.agreement_id)
        build.set_clock("2026-08-20T06:00:00Z")
        build.weather(w.site_id, rainfall_in_24h=0.60, forecast_rainfall_in_48h=0.00)

        validate_error(
            api.start_event(event["id"], make_operator_headers(w.facility_id)),
            ERR_WEATHER_RESTRICTION,
        )

        current_site = build.read_site(w.site_id)
        assert current_site["latest_rainfall_in_24h"] == 0.60
        assert current_site["weather_clearance_ok"] is False

        current_event = build.read_event(event["id"])
        assert current_event["status"] == C.EVENT_SCHEDULED
        assert current_event["hold_reason"] is None


class TestReapplicationIntervalBoundary:
    def test_the_day_before_the_boundary_is_refused_and_the_boundary_day_is_accepted(
        self, api, base_world
    ):
        """PRD §2.7: "**Priority 43 — reapplication interval.** `window_start` is at or after the latest `window_end` among `COMPLETED` events on this site plus `reapplication_interval_days` days; the boundary instant itself is accepted."

        A 10-day interval measured from the completed window_end of 2026-08-21 puts the
        earliest permissible opening at 2026-08-31. A window opening 2026-08-30 is refused
        with ERR_REAPPLICATION_INTERVAL even though the batch still holds enough
        unallocated tonnage, and the boundary instant itself is accepted.

        Design: Corner/validations/val_reapplication_interval_accepts_the_exact_boundary_day_and_rejects_the_day_before
        """
        w = base_world
        build = w.build
        build.completed_event(
            w.site_id,
            w.batch_id,
            w.agreement_id,
            complete_kwargs={"applied_dry_tons": 80.000},
        )

        error = validate_error(
            api.create_event(
                F.event_payload(
                    w.site_id,
                    w.batch_id,
                    w.agreement_id,
                    window_start="2026-08-30T00:00:00Z",
                    window_end="2026-08-31T00:00:00Z",
                ),
                AGRONOMIST_HEADERS,
            ),
            ERR_REAPPLICATION_INTERVAL,
        )
        assert error["error_id"] != ERR_INSUFFICIENT_UNALLOCATED_TONS

        accepted = validate_success(
            api.create_event(
                F.event_payload(
                    w.site_id,
                    w.batch_id,
                    w.agreement_id,
                    window_start="2026-08-31T00:00:00Z",
                    window_end="2026-09-01T00:00:00Z",
                ),
                AGRONOMIST_HEADERS,
            ),
            201,
        )
        assert accepted["status"] == C.EVENT_SCHEDULED
        assert_instant_equals(accepted["window_start"], "2026-08-31T00:00:00Z")
        assert_percent(accepted["requested_rate_dry_tons_per_acre"], 0.80)
        assert_percent(accepted["agronomic_rate_cap_dry_tons_per_acre"], 9.88)

        assert_dry_tons(build.read_batch(w.batch_id)["unallocated_dry_tons"], 0.000)
        summary = build.loading_summary(w.site_id)
        assert_loading_delta(summary["cumulative_loading_kg_per_hectare"]["CADMIUM"], 0.0359)


class TestStorageCapacityIsCollective:
    def test_the_sum_decides_and_an_exact_fit_freezes_the_plant(self, api, build):
        """PRD §2.7: "**Priority 55 — storage headroom.** The facility's `storage_used_wet_tons` plus the offered `wet_tons` is at most `storage_capacity_wet_tons`; landing exactly on capacity is accepted."

        Neither offered batch exceeds the 1000.00 wet ton capacity on its own; it is
        the running total that decides. 800.00 already stored plus 300.00 is refused with
        ERR_STORAGE_CAPACITY_EXCEEDED, while 800.00 plus 200.00 lands exactly on capacity
        and is accepted, taking utilization to 100.00 percent, the posture to FROZEN and
        the drawdown projection to 0 days.

        Design: Corner/validations/val_storage_capacity_rejects_the_collective_overage_but_accepts_an_exact_fit
        """
        facility = build.facility(
            storage_capacity_wet_tons=1000.00, daily_production_wet_tons=40.00
        )
        build.batch(facility["id"], wet_tons=800.00, dry_tons_in=200.000)

        validate_error(
            api.create_batch(
                F.batch_payload(facility["id"], wet_tons=300.00, dry_tons_in=75.000),
                make_operator_headers(facility["id"]),
            ),
            ERR_STORAGE_CAPACITY_EXCEEDED,
        )

        second = validate_success(
            api.create_batch(
                F.batch_payload(facility["id"], wet_tons=200.00, dry_tons_in=50.000),
                make_operator_headers(facility["id"]),
            ),
            201,
        )
        assert_wet_tons(second["wet_tons"], 200.00)

        current_facility = build.read_facility(facility["id"])
        assert_facility_storage(current_facility, 1000.00, 100.00, C.POSTURE_FROZEN)
        assert current_facility["days_of_capacity"] == 0


class TestEventCreationSatisfiesEveryRung:
    def test_a_fully_compliant_window_is_accepted_with_every_derived_field_pinned(
        self, api, base_world
    ):
        """PRD §3.7: "**Success.** The event is created in `SCHEDULED` with `version` 1, `applied_dry_tons` 0.000, `applied_wet_tons` 0.00, `reserved_dry_tons` equal to `planned_dry_tons`, and `hold_reason` and `defer_reason` null."

        A request that satisfies the crop month, the three-day notice, the agronomic
        cap, the cumulative headroom and the unallocated tonnage rule is accepted, and
        the creating response carries every pinned derivation: plant-available nitrogen
        16.2000, cap 9.88 bound by NITROGEN, requested rate 0.80 and 80.000 reserved dry
        tons. Scheduling writes no loading, so the site's cumulative map stays empty.

        Design: Corner/validations/val_event_creation_passes_every_rung_of_the_ladder_when_satisfied
        """
        w = base_world

        event = validate_success(
            api.create_event(
                F.event_payload(w.site_id, w.batch_id, w.agreement_id),
                AGRONOMIST_HEADERS,
            ),
            201,
        )
        assert event["status"] == C.EVENT_SCHEDULED
        assert_pan(event["plant_available_n_lb_per_dry_ton"], 16.2000)
        assert_percent(event["agronomic_rate_cap_dry_tons_per_acre"], 9.88)
        assert event["binding_rate_constraint"] == C.BINDING_NITROGEN
        assert_percent(event["requested_rate_dry_tons_per_acre"], 0.80)
        assert_dry_tons(event["reserved_dry_tons"], 80.000)
        assert_dry_tons(event["applied_dry_tons"], 0.000)
        assert_wet_tons(event["applied_wet_tons"], 0.00)
        assert event["hold_reason"] is None
        assert event["defer_reason"] is None

        assert_dry_tons(w.build.read_batch(w.batch_id)["unallocated_dry_tons"], 80.000)
        assert w.build.read_site(w.site_id)["cumulative_loading_kg_per_hectare"] == {}
