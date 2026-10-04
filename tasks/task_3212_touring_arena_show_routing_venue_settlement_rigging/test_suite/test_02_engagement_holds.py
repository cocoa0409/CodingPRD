"""Engagement hold lifecycle: hold TTL expiry, windows, OCC on avail version."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_date_avail_payload,
    create_engagement_payload,
    setup_confirmed_engagement,
    setup_held_engagement,
    setup_tour_and_venue,
    set_clock,
    validate_error,
    validate_success,
    create_date_avail,
)

TM = TEST_USERS["tour_manager_headers"]
VB = TEST_USERS["venue_booker_headers"]
PA = TEST_USERS["platform_admin_headers"]


class TestHoldTtlExpiryBoundary:
    def test_hold_ttl_expiry_one_second_before_keeps_hold(self):
        """PRD §3.3: "On any read of a `HOLD` engagement, or any write attempted
        against it, the system compares the logical clock against
        `hold_expires_at`: if the clock is at or past expiry, the engagement
        auto-transitions `HOLD → CANCELLED` with the full cancellation cascade
        described below. The boundary is inclusive — a clock exactly equal to
        `hold_expires_at` triggers expiry."

        Design: Corner/calculations/hold_ttl_expiry_boundary_at_exact_expiry
        """
        ctx = setup_held_engagement()
        set_clock("2026-09-03T23:59:59Z")
        resp = api_client.get_engagement(
            ctx["tour"]["id"], ctx["engagement"]["id"], TM
        )
        data = validate_success(resp)
        assert data["status"] == "HOLD"

    def test_hold_ttl_expiry_at_exact_expiry_auto_cancels(self):
        """PRD §3.3: "On any read of a `HOLD` engagement, or any write attempted
        against it, the system compares the logical clock against
        `hold_expires_at`: if the clock is at or past expiry, the engagement
        auto-transitions `HOLD → CANCELLED` with the full cancellation cascade
        described below. The boundary is inclusive — a clock exactly equal to
        `hold_expires_at` triggers expiry."

        Design: Corner/calculations/hold_ttl_expiry_boundary_at_exact_expiry
        """
        ctx = setup_held_engagement()
        set_clock("2026-09-04T00:00:00Z")
        resp = api_client.get_engagement(
            ctx["tour"]["id"], ctx["engagement"]["id"], TM
        )
        data = validate_success(resp)
        assert data["status"] == "CANCELLED"


class TestEngagementWindowContainment:
    def test_engagement_window_half_open_containment_load_out_at_closes_at(self):
        """PRD §3.2: "A `VenueBooker` declares a DateAvail on a venue with
        `opens_at` (the inclusive start of the available window) and `closes_at`
        (the exclusive end — the window is half-open, so an engagement ending
        exactly at `closes_at` does not fit)"
        PRD §3.3: "the engagement must fit inside the avail's half-open window —
        `load_in_at` at or after the avail's `opens_at`, and `load_out_at`
        strictly before the avail's `closes_at`; a violation is rejected with
        `ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/engagement_window_half_open_containment_within_avail
        """
        tour, venue = setup_tour_and_venue()
        avail = create_date_avail(venue["id"])
        payload = create_engagement_payload(
            venue["id"], avail["id"], avail["version"],
            load_out_at="2026-09-15T00:00:00Z",
        )
        resp = api_client.create_engagement(tour["id"], payload, TM)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL)

        list_resp = api_client.list_engagements(tour["id"], TM)
        data = validate_success(list_resp)
        assert data == []

    def test_engagement_window_load_in_before_opens_at_rejected(self):
        """PRD §3.3: "Second, containment: the engagement must fit inside the
        avail's half-open window — `load_in_at` at or after the avail's
        `opens_at`, and `load_out_at` strictly before the avail's `closes_at`; a
        violation is rejected with `ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/engagement_window_half_open_containment_within_avail
        """
        tour, venue = setup_tour_and_venue()
        avail = create_date_avail(venue["id"])
        payload = create_engagement_payload(
            venue["id"], avail["id"], avail["version"],
            load_in_at="2026-09-09T23:00:00Z",
            first_show_at="2026-09-10T19:00:00Z",
            load_out_at="2026-09-12T23:00:00Z",
        )
        resp = api_client.create_engagement(tour["id"], payload, TM)
        validate_error(resp, ApiErrorId.ERR_ENGAGEMENT_WINDOW_OUT_OF_AVAIL)


class TestStaleAvailVersionOcc:
    def test_stale_avail_version_on_engagement_create_returns_412(self):
        """PRD §2.7: "Creating an engagement requires a non-optional
        `expected_avail_version` field carrying the client's last observed
        `version` of the target date avail; if the avail's current `version` has
        advanced — because another writer has created an engagement holding the
        same avail or has released it — the create is rejected with
        `ERR_STALE_AVAIL_VERSION` (HTTP 412), and the client must re-read the
        avail and re-issue."

        Design: Corner/validations/stale_avail_version_on_engagement_create_returns_412
        """
        ctx = setup_held_engagement()
        api_client.cancel_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)

        payload = create_engagement_payload(
            ctx["venue"]["id"], ctx["avail"]["id"], ctx["avail"]["version"],
        )
        resp = api_client.create_engagement(ctx["tour"]["id"], payload, TM)
        validate_error(resp, ApiErrorId.ERR_STALE_AVAIL_VERSION)
