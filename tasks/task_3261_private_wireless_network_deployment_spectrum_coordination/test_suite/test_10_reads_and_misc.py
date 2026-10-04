"""Computed reads, remaining RBAC exclusions, and the business-safety vs
temporal priority pair.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_lease,
    create_approved_survey,
    create_enterprise_with_site,
    create_lease_payload,
    create_site_payload,
    get_success_data,
    validate_error,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
SC = TEST_USERS["spectrum_coordinator_headers"]
SR = TEST_USERS["spectrum_regulator_headers"]


class TestSiteSummary:
    def test_summary_returns_computed_aggregates_on_fresh_site(self):
        """PRD §3.11: "A site summary capability returns a computed rollup for
        one Site — its `posture`, capacity shortfall, spectrum utilization,
        device count, open alerts, and active slices — for the
        `NetworkArchitect`, `RFEngineer`, `SpectrumCoordinator`, and
        `FieldTechnician` roles."
        PRD §3.1: "Its `posture` — a derived field beginning at `DORMANT`".

        Design: Corner/endpoints/site_summary_returns_computed_aggregates
        """
        _ent, site = create_enterprise_with_site()
        resp = api_client.get_site_summary(site["id"], NA)
        data = validate_success(resp)
        assert data["posture"] == "DORMANT"
        assert data["spectrum_utilization_mhz"] == 0
        assert data["device_count"] == 0

    def test_summary_reflects_survey_approval_posture(self):
        """PRD §3.11: "A site summary capability returns a computed rollup for
        one Site — its `posture`, capacity shortfall, spectrum utilization,
        device count, open alerts, and active slices".
        PRD §3.2: "the parent Site transitions `PLANNED → SURVEYED`, its
        `posture` becomes `DESIGNING`, and its `version` increments."

        Design: Corner/endpoints/site_summary_returns_computed_aggregates
        """
        _ent, site = create_enterprise_with_site()
        create_approved_survey(site["id"], surveyor_id="ft-sum")
        resp = api_client.get_site_summary(site["id"], NA)
        data = validate_success(resp)
        assert data["posture"] == "DESIGNING"


class TestRegulatorRbac:
    def test_regulator_cannot_file_coordination_request(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.1: "`SpectrumCoordinator` — the spectrum planning specialist;
        files coordination requests, manages spectrum leases, and creates
        spectrum assignments."

        Design: Corner/rbac/spectrum_regulator_cannot_file_coordination_request
        """
        _ent, site = create_enterprise_with_site()
        payload = {
            "requesting_coordinator_id": "reg-001",
            "band_class": "SHARED_CBRS",
            "requested_bandwidth_mhz": 20,
            "requested_start_utc": "2026-10-01T00:00:00Z",
            "requested_end_utc": "2027-10-01T00:00:00Z",
        }
        resp = api_client.create_coordination_request(site["id"], payload, SR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_regulator_can_read_leases_and_coordination_requests(self):
        """PRD §2.1: "`SpectrumRegulator` — the external regulator (an FCC/SAS
        administrator proxy); approves or rejects coordination requests and may
        read spectrum leases, contracts, and coordination requests."

        Design: Corner/rbac/spectrum_regulator_cannot_file_coordination_request
        """
        ent, site = create_enterprise_with_site()
        lease = create_active_lease(ent["id"])
        resp = api_client.get_lease(lease["id"], SR)
        data = validate_success(resp)
        assert data["id"] == lease["id"]


class TestSafetyBeforeTemporalPriority:
    def test_invalid_window_alone_surfaces_time_window_error(self):
        """PRD §2.11: "a window whose end equals or precedes its start is
        rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400)."
        PRD §2.9: "Business-safety checks (interference margin, survey signal
        strength, URLLC edge placement, PAL spectrum overlap) come next, then
        temporal rules (time-window validity, lease coverage, assignment
        overlap, contract overlap)".

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_temporal_on_lease_create
        """
        ent, _site = create_enterprise_with_site()
        create_active_lease(
            ent["id"],
            band_class="SHARED_CBRS",
            center_frequency_mhz=3550,
            bandwidth_mhz=20,
            lease_start_utc="2026-09-01T00:00:00Z",
            lease_end_utc="2027-09-01T00:00:00Z",
            priority_access_tier="PAL",
        )
        # Same invalid window but OUTSIDE the ±10 MHz bucket: no overlap, so
        # the temporal check is the one that surfaces.
        resp = api_client.create_lease(
            ent["id"],
            create_lease_payload(
                band_class="SHARED_CBRS",
                center_frequency_mhz=3600,
                bandwidth_mhz=10,
                lease_start_utc="2026-12-01T00:00:00Z",
                lease_end_utc="2026-06-01T00:00:00Z",
                priority_access_tier="PAL",
            ),
            SC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)
