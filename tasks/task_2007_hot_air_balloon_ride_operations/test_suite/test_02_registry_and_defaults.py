"""Registry entities: launch sites, balloons, pilots — defaults, computed
fields, permission and inspection lifecycles, and pilot currency (PRD §2.7,
§2.10, §3.1, §3.2)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_launch_site,
    assert_pilot,
    assert_timestamp_matches_instant,
    create_balloon,
    create_draft_flight,
    create_launch_site,
    create_pilot,
    get_success_data,
    grant_permission,
    record_inspection,
    set_clock,
    setup_publish_ready,
    validate_error,
    validate_success,
)


class TestLaunchSiteDefaults:
    def test_launch_site_created_with_pending_permission_default(self, api, ops_headers):
        """PRD §3.1: "A new site's `permission_status` starts at `PENDING`.
        Granting landowner permission moves it to `GRANTED` and stamps
        `permission_granted_at` with the logical clock's current instant (the
        field stays null until the first grant)".

        Design: Corner/entities/launch_site_created_with_pending_permission_default
        """
        set_clock()
        site = create_launch_site(name="Corrales Bosque")
        assert_launch_site(site)
        assert site["permission_status"] == "PENDING", (
            f"new site must start PENDING, got {site['permission_status']}"
        )
        assert site["permission_granted_at"] is None, (
            "permission_granted_at stays null until the first grant"
        )


class TestLaunchSitePermissionLifecycle:
    def test_launch_site_permission_cycle(self, api, ops_headers):
        """PRD §3.1: "revoking permission moves a `GRANTED` site to `REVOKED`;
        and a revoked site can be re-granted, which again refreshes
        `permission_granted_at`."

        Design: Corner/state_machines/launch_site_permission_cycle
        """
        set_clock()
        site = create_launch_site()
        granted = grant_permission(site["id"])
        assert granted["permission_status"] == "GRANTED"
        assert_timestamp_matches_instant(
            granted["permission_granted_at"], "2026-08-01T00:00:00Z"
        )

        revoked = get_success_data(
            api.launch_site_event(site["id"], {"event_type": "REVOKE_PERMISSION"}, ops_headers)
        )
        assert revoked["permission_status"] == "REVOKED"

        set_clock("2026-08-02T00:00:00Z")
        regranted = get_success_data(
            api.launch_site_event(site["id"], {"event_type": "GRANT_PERMISSION"}, ops_headers)
        )
        assert regranted["permission_status"] == "GRANTED"
        assert_timestamp_matches_instant(
            regranted["permission_granted_at"], "2026-08-02T00:00:00Z"
        )


class TestBalloonInspection:
    def test_balloon_inspection_due_on_computed(self, api, ops_headers):
        """PRD §3.1: "Recording an inspection sets `last_inspection_on` to the
        supplied date, recomputes `inspection_due_on` as exactly 365 days after
        `last_inspection_on`, and increments the balloon's `version`."
        PRD §3.1: "Until a balloon's first inspection, both `last_inspection_on`
        and `inspection_due_on` are null."

        Design: Corner/entities/balloon_inspection_due_on_computed
        """
        set_clock()
        balloon = create_balloon()
        assert balloon["last_inspection_on"] is None
        assert balloon["inspection_due_on"] is None

        inspected = record_inspection(balloon["id"], "2026-07-01")
        assert inspected["last_inspection_on"] == "2026-07-01"
        assert inspected["inspection_due_on"] == "2027-07-01", (
            f"inspection_due_on must be last_inspection_on + 365 days, got "
            f"{inspected['inspection_due_on']}"
        )
        assert inspected["version"] == balloon["version"] + 1, (
            "recording an inspection increments the balloon's version by one"
        )


class TestBalloonInspectionOcc:
    def test_occ_stale_version_on_record_inspection(self, api, ops_headers):
        """PRD §2.7: "Recording a balloon inspection requires the request to
        carry `expected_balloon_version`, holding the client's last-observed
        `version` of the balloon. If the balloon's current `version` no longer
        matches, the write is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_record_inspection
        """
        set_clock()
        balloon = create_balloon()
        inspected = record_inspection(balloon["id"], "2026-07-01")
        stale_version = inspected["version"]

        # An intervening GROUND event mutates the balloon and advances version.
        get_success_data(api.balloon_event(balloon["id"], {"event_type": "GROUND"}, ops_headers))

        stale = api.balloon_event(
            balloon["id"],
            {
                "event_type": "RECORD_INSPECTION",
                "inspected_on": "2026-08-01",
                "expected_balloon_version": stale_version,
            },
            ops_headers,
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        # Retrying with the freshly observed version succeeds.
        fresh = validate_success(api.get_balloon(balloon["id"], ops_headers))
        retry = api.balloon_event(
            balloon["id"],
            {
                "event_type": "RECORD_INSPECTION",
                "inspected_on": "2026-08-01",
                "expected_balloon_version": fresh["version"],
            },
            ops_headers,
        )
        retried = validate_success(retry)
        assert retried["last_inspection_on"] == "2026-08-01"


class TestPilotDefaultsAndCurrency:
    def test_pilot_optional_experience_defaults_to_zero(self, api, ops_headers):
        """PRD §3.1: "Pilots are registered with their full `name`, FAA
        `certificate_number`, the `medical_expires_on` date of their medical
        certificate, and optionally their externally logged experience —
        `external_pic_hours_180d` and `external_takeoffs_landings_90d`, both
        defaulting to 0."
        PRD §2.10: "The pilot's `currency_status` is `CURRENT` when both checks
        are met and `EXPIRED` otherwise."

        Design: Corner/entities/pilot_optional_experience_defaults_to_zero
        """
        set_clock()
        resp = api.create_pilot(
            {
                "name": "New Pilot",
                "certificate_number": "PC-0001",
                "medical_expires_on": "2027-06-30",
            },
            ops_headers,
        )
        pilot = validate_success(resp, expected_status=201)
        assert_pilot(pilot)
        assert pilot["external_pic_hours_180d"] == 0
        assert pilot["external_takeoffs_landings_90d"] == 0
        assert pilot["faa_currency_met"] is False
        assert pilot["operator_currency_met"] is False
        assert pilot["currency_status"] == "EXPIRED"

    def test_pilot_currency_faa_met_operator_unmet_expired(self, api, ops_headers):
        """PRD §2.10: "The FAA-style check, `faa_currency_met`, is true exactly
        when `takeoffs_landings_90d_total` is at least 3 — it looks at the
        takeoffs-and-landings count only and ignores hours entirely. The
        operator's rolling-hours check, `operator_currency_met`, is true exactly
        when `pic_hours_180d_total` is at least 12.0 hours — it looks at hours
        only and ignores the takeoffs-and-landings count, so the two methods can
        diverge on the same pilot record."
        PRD §2.10: "The pilot's `currency_status` is `CURRENT` when both checks
        are met and `EXPIRED` otherwise."

        Design: Difficulty/dual_variant_calc/pilot_currency_faa_vs_operator_diverge
        """
        set_clock()
        pilot = create_pilot(external_pic_hours_180d=8.0, external_takeoffs_landings_90d=5)
        assert pilot["takeoffs_landings_90d_total"] == 5
        assert pilot["pic_hours_180d_total"] == pytest.approx(8.0)
        assert pilot["faa_currency_met"] is True, "5 takeoffs/landings >= 3 must satisfy FAA check"
        assert pilot["operator_currency_met"] is False, "8.0 hours < 12.0 must fail operator check"
        assert pilot["currency_status"] == "EXPIRED", (
            "currency_status follows the conservative AND of the two methods"
        )

    @pytest.mark.parametrize(
        "hours,takeoffs,expected_faa,expected_operator,expected_status",
        [
            (12.0, 3, True, True, "CURRENT"),      # both thresholds exactly met
            (20.0, 2, False, True, "EXPIRED"),     # FAA count just under 3
            (11.9, 5, True, False, "EXPIRED"),     # operator hours just under 12.0
        ],
    )
    def test_pilot_currency_thresholds_exactly_met_and_unmet(
        self, api, ops_headers, hours, takeoffs, expected_faa, expected_operator, expected_status
    ):
        """PRD §2.10: "The FAA-style check, `faa_currency_met`, is true exactly
        when `takeoffs_landings_90d_total` is at least 3" and "The operator's
        rolling-hours check, `operator_currency_met`, is true exactly when
        `pic_hours_180d_total` is at least 12.0 hours". "The pilot's
        `currency_status` is `CURRENT` when both checks are met and `EXPIRED`
        otherwise."

        Design: Difficulty/dual_variant_calc/pilot_currency_faa_vs_operator_diverge
        """
        set_clock()
        pilot = create_pilot(
            external_pic_hours_180d=hours, external_takeoffs_landings_90d=takeoffs
        )
        assert pilot["faa_currency_met"] is expected_faa
        assert pilot["operator_currency_met"] is expected_operator
        assert pilot["currency_status"] == expected_status


class TestFlightSeasonTier:
    def test_flight_season_tier_computed_peak_vs_regular(self, api, ops_headers):
        """PRD §3.2: "At creation the system derives the flight's `season_tier`:
        `PEAK` when `scheduled_date` falls within October 1 through October 14 —
        the Balloon Fiesta window — and `REGULAR` otherwise."

        Design: Corner/entities/flight_season_tier_computed_peak_vs_regular
        """
        ctx = setup_publish_ready()
        peak = create_draft_flight(
            ctx,
            scheduled_date="2026-10-01",
            dawn_window_start="2026-10-01T05:30:00Z",
            dawn_window_end="2026-10-01T07:00:00Z",
        )
        regular = create_draft_flight(
            ctx,
            scheduled_date="2026-10-15",
            dawn_window_start="2026-10-15T05:30:00Z",
            dawn_window_end="2026-10-15T07:00:00Z",
        )
        assert peak["season_tier"] == "PEAK", "Oct 1 is inside the Balloon Fiesta window"
        assert regular["season_tier"] == "REGULAR", "Oct 15 is outside the Fiesta window"
