"""Launch-site selection: OCC on select-launch-site, the wind-margin-ranked
candidate read model, the empty-pool fallback, and flight reverse-lookup
filters (PRD §2.7, §3.2, §3.3)."""
from test_helpers import (
    ApiErrorId,
    create_balloon,
    create_draft_flight,
    create_granted_site,
    create_inspected_balloon,
    create_launch_site,
    create_pilot,
    enter_weather_review,
    get_flight,
    get_success_data,
    grant_permission,
    record_briefing,
    set_clock,
    setup_publish_ready,
    setup_scheduled_flight,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestFlightReverseLookup:
    def test_flights_list_filter_by_balloon(self, api, ops_headers):
        """PRD §3.2: "Flights can be listed with optional reverse-lookup filters
        on `launch_site_id`, `balloon_id`, `pilot_id`, and `status`, so the desk
        can see everything committed against a site, an aircraft, or a pilot."

        Design: Corner/endpoints/flights_list_filter_by_balloon
        """
        ctx = setup_publish_ready()
        balloon2 = create_balloon()
        f1 = create_draft_flight(ctx)
        f2 = create_draft_flight(
            ctx,
            balloon_id=balloon2["id"],
            scheduled_date="2026-08-12",
            dawn_window_start="2026-08-12T05:30:00Z",
            dawn_window_end="2026-08-12T07:00:00Z",
        )
        data, meta = validate_paginated(
            api.list_flights(ops_headers, params={"balloon_id": ctx["balloon"]["id"]})
        )
        ids = [f["id"] for f in data]
        assert f1["id"] in ids, "filter by balloon_id must include that balloon's flight"
        assert f2["id"] not in ids, "filter by balloon_id must exclude other balloons' flights"
        assert meta["total_count"] == 1


class TestSelectLaunchSiteOcc:
    def test_occ_stale_version_on_select_launch_site(self, api, ops_headers):
        """PRD §2.7: "Changing a flight's launch site requires the request to
        carry `expected_flight_version`, holding the client's last-observed
        `version` of the flight. If the flight's current `version` has advanced
        past that value, the write is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."
        PRD §3.3: "A successful change increments the flight's `version` by
        one."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_select_launch_site
        """
        ctx = setup_publish_ready()
        site2 = create_granted_site(name="Corrales Bosque", surface_wind_limit_kts=9,
                                    aloft_wind_limit_kts=22, per_use_fee_cents=12000)
        flight = create_draft_flight(ctx)
        stale_version = flight["version"]

        # PUBLISH mutates the flight and advances its version.
        get_success_data(
            api.flight_event(flight["id"], {"event_type": "PUBLISH"}, ops_headers)
        )

        stale = api.select_launch_site(
            flight["id"],
            {"launch_site_id": site2["id"], "expected_flight_version": stale_version},
            ops_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_flight(flight["id"])["version"]
        changed = validate_success(
            api.select_launch_site(
                flight["id"],
                {"launch_site_id": site2["id"], "expected_flight_version": fresh_version},
                ops_headers,
            )
        )
        assert changed["launch_site_id"] == site2["id"]
        assert changed["version"] == fresh_version + 1


class TestSiteCandidates:
    def test_site_candidates_ranked_by_wind_margin(self, api, ops_headers):
        """PRD §3.3: "Eligible sites are ranked by wind margin: each site's
        `wind_margin_kts` is the smaller of two differences — the site's
        `surface_wind_limit_kts` minus the briefing's `surface_wind_kts`, and
        the site's `aloft_wind_limit_kts` minus the briefing's `aloft_wind_kts` —
        and the ranking sorts by `wind_margin_kts` descending, so the site with
        the most headroom against the observed winds wins."
        PRD §3.3: "the operations desk and the assigned pilot can fetch the
        flight's ranked candidate sites, where each row exposes `site_id`,
        `wind_margin_kts`, and `permission_granted_at`."

        Design: Corner/endpoints/site_candidates_ranked_by_wind_margin
        """
        # Site A (8/20) grants first; site B (7/15) grants a day later.
        set_clock()
        site_a = create_granted_site(name="Site A", surface_wind_limit_kts=8,
                                     aloft_wind_limit_kts=20)
        site_b = create_launch_site(name="Site B", surface_wind_limit_kts=7,
                                    aloft_wind_limit_kts=15, per_use_fee_cents=12000)
        set_clock("2026-08-02T00:00:00Z")
        grant_permission(site_b["id"])

        balloon = create_inspected_balloon()
        pilot = create_pilot()
        ctx = {"site": site_a, "balloon": balloon, "pilot": pilot}
        flight = create_draft_flight(ctx)
        ctx["flight"] = get_success_data(
            api.flight_event(flight["id"], {"event_type": "PUBLISH"}, ops_headers)
        )

        # Enter weather review and record a briefing of surface 6 / aloft 12.
        enter_weather_review(ctx)
        record_briefing(ctx, surface_wind_kts=6, aloft_wind_kts=12,
                        visibility_mi=10.0, precipitation=False)

        candidates = validate_success(
            api.list_site_candidates(ctx["flight"]["id"], ops_headers)
        )
        assert isinstance(candidates, list) and len(candidates) == 2
        # A: min(8-6, 20-12) = 2 ; B: min(7-6, 15-12) = 1 -> A outranks B.
        assert candidates[0]["site_id"] == site_a["id"]
        assert candidates[0]["wind_margin_kts"] == 2
        assert candidates[1]["site_id"] == site_b["id"]
        assert candidates[1]["wind_margin_kts"] == 1

    def test_site_candidates_empty_pool(self, api, ops_headers):
        """PRD §3.3: "A site is eligible when all of the following hold: its
        `permission_status` is `GRANTED`; its `permission_expires_on` is on or
        after the flight's `scheduled_date`; and either no `RECORDED` weather
        briefing exists for the flight yet, or the site tolerates the observed
        conditions — meaning the site's `surface_wind_limit_kts` is at least the
        briefing's `surface_wind_kts` and its `aloft_wind_limit_kts` is at least
        the briefing's `aloft_wind_kts`."
        PRD §3.3: "If the eligible pool is empty, the operation is rejected with
        `ERR_NO_SUITABLE_SITE` (HTTP 422)."

        Design: Corner/endpoints/site_candidates_empty_pool
        """
        ctx = setup_scheduled_flight()
        flight = ctx["flight"]
        # Revoking the flight's only site empties the eligible pool.
        get_success_data(
            api.launch_site_event(
                ctx["site"]["id"], {"event_type": "REVOKE_PERMISSION"}, ops_headers
            )
        )
        fresh_version = get_flight(flight["id"])["version"]
        resp = api.select_launch_site(
            flight["id"], {"expected_flight_version": fresh_version}, ops_headers
        )
        validate_error(resp, ApiErrorId.ERR_NO_SUITABLE_SITE)
