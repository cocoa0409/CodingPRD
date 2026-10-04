"""Difficulty queue: cross-entity state dependencies.

Initiative publish/activate is gated on the forecast entity's state; reroute
assignment is gated on the sector facility's state.
"""

from test_helpers import (
    COMMAND_CENTER_HEADERS,
    FLOW_MANAGER_HEADERS,
    ApiErrorId,
    assert_instant,
    assign_reroute,
    at,
    create_airport,
    create_published_forecast,
    expected_hourly_bucket,
    get_tmi,
    list_facility_forecasts,
    patch_facility,
    propose_gdp,
    publish_tmi,
    report_and_confirm_event,
    reroute_assignment_payload,
    set_clock,
    setup_reroute_scenario,
    validate_error,
)


class TestActivationRequiresPublishedForecast:
    def test_publish_and_activate_blocked_without_current_forecast(self, api):
        """PRD §3.4: "The forecast gate requires a `PUBLISHED`, non-`STALE`,
        `PLANNING`-variant CapacityForecast covering the whole program window
        (else `ERR_NO_CURRENT_FORECAST`)."
        PRD §3.3: "When an overlapping constraint event on the same facility is
        confirmed or extended, every `PUBLISHED` forecast whose window overlaps
        the event's window is automatically marked `STALE`, its `version`
        incrementing, and `STALE` is terminal — there is no path back to
        `PUBLISHED`."

        Design: Difficulty/cross_entity_state_dependency/activation_requires_published_forecast
        """
        set_clock(api)
        facility = create_airport(api, ident="KEWR", base_acceptance_rate=30)
        tmi = propose_gdp(
            api, facility["id"], program_start=at("13:00"),
            program_end=at("15:00"), controlled_rate=6,
        )

        # publish blocked: no covering PLANNING forecast exists
        resp = api.publish_tmi(tmi["id"], COMMAND_CENTER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NO_CURRENT_FORECAST)

        forecast = create_published_forecast(
            api, facility["id"], variant="PLANNING",
            window_start=at("13:00"), window_end=at("15:00"),
        )
        published = publish_tmi(api, tmi["id"])
        assert published["status"] == "PUBLISHED", "the satisfied gate admits publish"

        # a confirmed overlapping event turns the only forecast STALE; the TMI
        # is only PUBLISHED (not ACTIVE), so no downgrade cascade applies
        report_and_confirm_event(
            api, facility["id"], event_type="WEATHER", severity=1,
            window_start=at("13:00"), window_end=at("15:00"),
        )
        forecasts, _ = list_facility_forecasts(api, facility["id"])
        status_by_id = {f["id"]: f["status"] for f in forecasts}
        assert status_by_id[forecast["id"]] == "STALE"

        # activate blocked: the gate has no PUBLISHED non-STALE forecast now
        resp = api.activate_tmi(tmi["id"], FLOW_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_NO_CURRENT_FORECAST)
        tmi_after = get_tmi(api, tmi["id"])
        assert tmi_after["status"] == "PUBLISHED"
        assert tmi_after["revision_count"] == 0


class TestRerouteBlockedBySectorOutage:
    def test_sector_outage_rejects_and_degraded_admits(self, api):
        """PRD §3.8: "the `via_sector_id` must resolve to a facility of type
        `EN_ROUTE_SECTOR`, and pointing it at an `AIRPORT` fails with
        `ERR_REROUTE_SECTOR_TYPE` (HTTP 422); the sector itself must not be in
        `OUTAGE`, else `ERR_FACILITY_NOT_OPERATIONAL`."
        PRD §3.1: "`OUTAGE` is a hard gate downstream: it blocks TMI activation
        and reroute assignments into the facility with
        `ERR_FACILITY_NOT_OPERATIONAL` (HTTP 409), though it forces no cascade
        by itself. `DEGRADED` is purely informational."

        Design: Difficulty/cross_entity_state_dependency/reroute_blocked_by_sector_outage
        """
        world = setup_reroute_scenario(api, sector_base_rate=2, flight_etas=("13:30",))
        sector = world["sector"]
        flight = world["flights"][0]
        tmi_id = world["tmi"]["id"]

        patch_facility(api, sector["id"], status="OUTAGE")
        resp = api.create_reroute_assignment(
            tmi_id,
            reroute_assignment_payload(
                flight_id=flight["id"], via_sector_id=sector["id"], assigned_route="J60"
            ),
            FLOW_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_FACILITY_NOT_OPERATIONAL)

        # DEGRADED is informational: the same assignment is admitted
        patch_facility(api, sector["id"], status="DEGRADED")
        assignment = assign_reroute(api, tmi_id, flight["id"], sector["id"])
        assert_instant(
            assignment["hourly_bucket"], expected_hourly_bucket(at("13:30")),
            "ETA 13:30 truncates to the 13:00 hour bucket",
        )
