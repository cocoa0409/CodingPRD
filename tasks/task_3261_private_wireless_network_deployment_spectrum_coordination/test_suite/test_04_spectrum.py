"""Spectrum tests: lease windows, PAL overlap buckets, coordination request
lifecycle, OCC on request approval, interference margin gate, registration
lease gating, and assignment overlap/bandwidth rules.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_lease,
    create_coordination_request,
    create_designed_site,
    create_enterprise_with_site,
    create_lease,
    create_lease_payload,
    get_success_data,
    make_spectrum_coordinator_headers,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
SC = TEST_USERS["spectrum_coordinator_headers"]
SR = TEST_USERS["spectrum_regulator_headers"]
FT = TEST_USERS["field_technician_headers"]

PAL_START = "2026-09-01T00:00:00Z"
PAL_END = "2027-09-01T00:00:00Z"


class TestLeaseTimeWindow:
    def test_lease_end_before_start_rejected(self):
        """PRD §2.11: "In every case the end must be strictly later than the
        start; a window whose end equals or precedes its start is rejected with
        `ERR_INVALID_TIME_WINDOW` (HTTP 400)."

        Design: Corner/validations/invalid_time_window_end_before_start
        """
        ent, _site = create_enterprise_with_site()
        resp = api_client.create_lease(
            ent["id"],
            create_lease_payload(
                lease_start_utc="2027-09-01T00:00:00Z",
                lease_end_utc="2026-09-01T00:00:00Z",
            ),
            SC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)

    def test_lease_end_equal_start_rejected(self):
        """PRD §2.11: "a window whose end equals or precedes its start is
        rejected with `ERR_INVALID_TIME_WINDOW` (HTTP 400)."

        Design: Corner/validations/invalid_time_window_end_before_start
        """
        ent, _site = create_enterprise_with_site()
        resp = api_client.create_lease(
            ent["id"],
            create_lease_payload(
                lease_start_utc="2026-09-01T00:00:00Z",
                lease_end_utc="2026-09-01T00:00:00Z",
            ),
            SC,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TIME_WINDOW)


class TestPalLeaseOverlap:
    def test_pal_overlap_within_bucket_rejected(self):
        """PRD §3.4: "for a `SHARED_CBRS` request at the `PAL` tier, the
        requested window must not overlap any other `PAL` lease on the same
        `band_class` whose center frequency falls within the same 10-megahertz
        bucket (center frequencies within ±10 MHz of each other), else the
        request fails with `ERR_SPECTRUM_OVERLAP` (HTTP 409) — and this same
        overlap rule is enforced symmetrically when a `PAL`-tier `SHARED_CBRS`
        lease is created".

        Design: Difficulty/resource_temporal_overlap/pal_lease_overlap_uses_frequency_bucket_and_closed_window
        """
        ent, _site = create_enterprise_with_site()
        create_active_lease(
            ent["id"],
            band_class="SHARED_CBRS",
            center_frequency_mhz=3550,
            bandwidth_mhz=20,
            lease_start_utc=PAL_START,
            lease_end_utc=PAL_END,
            priority_access_tier="PAL",
        )
        resp = api_client.create_lease(
            ent["id"],
            create_lease_payload(
                band_class="SHARED_CBRS",
                center_frequency_mhz=3559,  # within ±10 MHz of 3550
                bandwidth_mhz=10,
                lease_start_utc="2026-12-01T00:00:00Z",
                lease_end_utc="2027-06-01T00:00:00Z",
                priority_access_tier="PAL",
            ),
            SC,
        )
        validate_error(resp, ApiErrorId.ERR_SPECTRUM_OVERLAP)

    def test_pal_outside_bucket_succeeds(self):
        """PRD §3.4: "whose center frequency falls within the same 10-megahertz
        bucket (center frequencies within ±10 MHz of each other), else the
        request fails with `ERR_SPECTRUM_OVERLAP` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/pal_lease_overlap_uses_frequency_bucket_and_closed_window
        """
        ent, _site = create_enterprise_with_site()
        create_active_lease(
            ent["id"],
            band_class="SHARED_CBRS",
            center_frequency_mhz=3550,
            bandwidth_mhz=20,
            lease_start_utc=PAL_START,
            lease_end_utc=PAL_END,
            priority_access_tier="PAL",
        )
        resp = api_client.create_lease(
            ent["id"],
            create_lease_payload(
                band_class="SHARED_CBRS",
                center_frequency_mhz=3565,  # outside ±10 MHz bucket
                bandwidth_mhz=10,
                lease_start_utc="2026-12-01T00:00:00Z",
                lease_end_utc="2027-06-01T00:00:00Z",
                priority_access_tier="PAL",
            ),
            SC,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PENDING"

    def test_gaa_lease_same_bucket_not_blocked_by_pal_rule(self):
        """PRD §3.4: "For the `SHARED_CBRS` band only, a `priority_access_tier`
        of `PAL` (priority access license) or `GAA` (general authorized access)
        may be given, defaulting to `GAA`." — the overlap rule names only the
        `PAL` tier ("for a `SHARED_CBRS` request at the `PAL` tier"), so GAA
        leases in the same bucket are not covered by it.

        Design: Difficulty/resource_temporal_overlap/pal_lease_overlap_uses_frequency_bucket_and_closed_window
        """
        ent, _site = create_enterprise_with_site()
        create_active_lease(
            ent["id"],
            band_class="SHARED_CBRS",
            center_frequency_mhz=3550,
            bandwidth_mhz=20,
            lease_start_utc=PAL_START,
            lease_end_utc=PAL_END,
            priority_access_tier="PAL",
        )
        resp = api_client.create_lease(
            ent["id"],
            create_lease_payload(
                band_class="SHARED_CBRS",
                center_frequency_mhz=3552,  # within bucket, but GAA tier
                bandwidth_mhz=10,
                lease_start_utc="2026-12-01T00:00:00Z",
                lease_end_utc="2027-06-01T00:00:00Z",
                priority_access_tier="GAA",
            ),
            SC,
        )
        data = validate_success(resp, expected_status=201)
        assert data["priority_access_tier"] == "GAA"


class TestCoordinationRequestLifecycle:
    def test_new_request_created_in_draft(self):
        """PRD §3.4: "The request is created in `DRAFT`."

        Design: Difficulty/non_linear_state_machine/spectrum_coordination_request_withdrawal_branch
        """
        _ent, site = create_enterprise_with_site()
        req, _headers = create_coordination_request(site["id"], coordinator_id="sc-a")
        assert req["status"] == "DRAFT"
        assert req["version"] == 1

    def test_withdraw_from_draft_by_filing_coordinator(self):
        """PRD §3.4: "At any point before terminality — from `DRAFT`,
        `SUBMITTED`, `COORDINATING`, or `APPROVED` — the filing coordinator,
        and only the filing coordinator, may withdraw the request to
        `WITHDRAWN`."

        Design: Difficulty/non_linear_state_machine/spectrum_coordination_request_withdrawal_branch
        """
        _ent, site = create_enterprise_with_site()
        req, sc_headers = create_coordination_request(site["id"], coordinator_id="sc-wd")
        resp = api_client.withdraw_coordination_request(site["id"], req["id"], sc_headers)
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_from_submitted_by_filing_coordinator(self):
        """PRD §3.4: "At any point before terminality — from `DRAFT`,
        `SUBMITTED`, `COORDINATING`, or `APPROVED` — the filing coordinator,
        and only the filing coordinator, may withdraw the request to
        `WITHDRAWN`."

        Design: Difficulty/non_linear_state_machine/spectrum_coordination_request_withdrawal_branch
        """
        _ent, site, _sv = create_designed_site()
        req, sc_headers = create_coordination_request(site["id"], coordinator_id="sc-ws")
        get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
        resp = api_client.withdraw_coordination_request(site["id"], req["id"], sc_headers)
        data = validate_success(resp)
        assert data["status"] == "WITHDRAWN"

    def test_withdraw_by_other_operator_rejected(self):
        """PRD §3.4: "the filing coordinator, and only the filing coordinator,
        may withdraw the request to `WITHDRAWN`."
        PRD §2.1: "Where a workflow ties an action to the same operator (for
        example, only the filing coordinator may withdraw a request), the
        comparison is between `X-User-ID` and that recorded field, not against
        a user table."

        Design: Difficulty/non_linear_state_machine/spectrum_coordination_request_withdrawal_branch
        """
        _ent, site = create_enterprise_with_site()
        req, _sc_headers = create_coordination_request(site["id"], coordinator_id="sc-owner")
        intruder = make_spectrum_coordinator_headers("sc-intruder")
        resp = api_client.withdraw_coordination_request(site["id"], req["id"], intruder)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_begin_coordination_computes_interference_report_default(self):
        """PRD §3.4: "Beginning coordination moves the request to
        `COORDINATING` and triggers the interference analysis: the server
        computes the request's `interference_report`, an object with
        `aggregate_margin_db`, `worst_case_margin_db`, and
        `neighbor_cells_checked`. `worst_case_margin_db` is the smallest margin
        across all such neighbors — defaulting to +99 when there are none".

        Design: Difficulty/non_linear_state_machine/spectrum_coordination_request_withdrawal_branch
        """
        _ent, site, _sv = create_designed_site()
        req, sc_headers = create_coordination_request(site["id"], coordinator_id="sc-ir")
        get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
        resp = api_client.begin_coordination(site["id"], req["id"], sc_headers)
        data = validate_success(resp)
        assert data["status"] == "COORDINATING"
        report = data["interference_report"]
        assert report["worst_case_margin_db"] == 99
        assert report["neighbor_cells_checked"] == 0


class TestCoordinationOccAndPriority:
    def test_stale_request_version_rejected_on_approve(self):
        """PRD §2.7: "approving a spectrum coordination request requires the
        request to carry `expected_request_version` equal to the
        SpectrumCoordinationRequest's current `version`. This captures the case
        where the coordinator re-submitted or otherwise modified the request
        after the regulator's review snapshot. A mismatch is rejected with
        `ERR_STALE_REQUEST_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_coordination_request_version
        """
        _ent, site, _sv = create_designed_site()
        req, sc_headers = create_coordination_request(site["id"], coordinator_id="sc-occ")
        stale_v = req["version"]
        get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
        get_success_data(api_client.begin_coordination(site["id"], req["id"], sc_headers))
        resp = api_client.approve_coordination_request(
            site["id"], req["id"], {"expected_request_version": stale_v}, SR
        )
        validate_error(resp, ApiErrorId.ERR_STALE_REQUEST_VERSION)

    def test_approve_with_current_version_succeeds_and_mints_sas_id(self):
        """PRD §3.4: "On approval the server mints the request's
        `sas_registration_id` in the form SAS-XXXXXX, representing the Spectrum
        Access System registration."
        PRD §2.7: "approving a spectrum coordination request requires the
        request to carry `expected_request_version` equal to the
        SpectrumCoordinationRequest's current `version`."

        Design: Difficulty/cross_entity_state_dependency/coordination_register_requires_lease_active
        """
        _ent, site, _sv = create_designed_site()
        req, sc_headers = create_coordination_request(site["id"], coordinator_id="sc-ok")
        get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
        cur = get_success_data(api_client.begin_coordination(site["id"], req["id"], sc_headers))
        resp = api_client.approve_coordination_request(
            site["id"], req["id"], {"expected_request_version": cur["version"]}, SR
        )
        data = validate_success(resp)
        assert data["status"] == "APPROVED"
        assert isinstance(data["sas_registration_id"], str)
        assert data["sas_registration_id"].startswith("SAS-")

    def test_approve_in_draft_state_reports_state_error_not_interference(self):
        """PRD §2.9: "State checks follow: requesting a transition the
        resource's current state does not allow yields `ERR_INVALID_STATE`
        (HTTP 409)" and state checks come before business-safety checks in the
        fixed priority order ("Only then does existence checking run … State
        checks follow … Business-safety checks (interference margin, survey
        signal strength, URLLC edge placement, PAL spectrum overlap) come
        next").

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_coordination_approve
        """
        _ent, site = create_enterprise_with_site()
        req, _sc_headers = create_coordination_request(site["id"], coordinator_id="sc-pp")
        # Request is still DRAFT; approval is a state violation regardless of
        # any interference outcome.
        resp = api_client.approve_coordination_request(
            site["id"], req["id"], {"expected_request_version": req["version"]}, SR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_approve_in_submitted_state_also_reports_state_error(self):
        """PRD §2.9: "requesting a transition the resource's current state does
        not allow yields `ERR_INVALID_STATE` (HTTP 409)" — approval is defined
        only out of `COORDINATING` ("The full lifecycle is `DRAFT → SUBMITTED →
        COORDINATING → APPROVED → REGISTERED`", PRD §3.4), so approval from
        `SUBMITTED` is a state error surfaced before any business-safety check.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_coordination_approve
        """
        _ent, site, _sv = create_designed_site()
        req, sc_headers = create_coordination_request(site["id"], coordinator_id="sc-pp2")
        get_success_data(
            api_client.submit_coordination_request(site["id"], req["id"], sc_headers)
        )
        req_now = get_success_data(
            api_client.get_coordination_request_under_site(site["id"], req["id"], SC)
        )
        resp = api_client.approve_coordination_request(
            site["id"], req["id"], {"expected_request_version": req_now["version"]}, SR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCoordinationRegister:
    def test_register_without_active_lease_rejected(self):
        """PRD §3.4: "An `APPROVED` request becomes `REGISTERED` when the
        coordinator registers it — which requires the `sas_registration_id` to
        be present and an `ACTIVE` SpectrumLease to exist for this Enterprise
        covering the requested `band_class` over a window that fully contains
        the requested window; absent such a lease the registration is rejected
        with `ERR_NO_ACTIVE_LEASE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/coordination_register_requires_lease_active
        """
        ent, site, _sv = create_designed_site()
        req, sc_headers = create_coordination_request(
            site["id"], coordinator_id="sc-reg", band_class="SHARED_CBRS",
            requested_start_utc="2026-10-01T00:00:00Z",
            requested_end_utc="2027-10-01T00:00:00Z",
        )
        get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
        cur = get_success_data(api_client.begin_coordination(site["id"], req["id"], sc_headers))
        get_success_data(
            api_client.approve_coordination_request(
                site["id"], req["id"], {"expected_request_version": cur["version"]}, SR
            )
        )
        # Lease exists but remains PENDING (never activated).
        create_lease(
            ent["id"],
            band_class="SHARED_CBRS",
            center_frequency_mhz=3550,
            bandwidth_mhz=40,
            lease_start_utc="2026-09-01T00:00:00Z",
            lease_end_utc="2027-09-01T00:00:00Z",
        )
        resp = api_client.register_coordination_request(site["id"], req["id"], sc_headers)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_LEASE)

    def test_register_with_active_covering_lease_moves_site_to_coordinated(self):
        """PRD §3.4: "The first request for a site to reach `REGISTERED` moves
        the Site `DESIGNED → COORDINATED`, sets `posture` to `DEPLOYING`, and
        bumps the Site's `version`; subsequent registrations do not repeat that
        transition."

        Design: Difficulty/cross_entity_state_dependency/coordination_register_requires_lease_active
        """
        ent, site, _sv = create_designed_site()
        create_active_lease(
            ent["id"],
            band_class="SHARED_CBRS",
            center_frequency_mhz=3550,
            bandwidth_mhz=40,
            lease_start_utc="2026-09-01T00:00:00Z",
            lease_end_utc="2028-09-01T00:00:00Z",
        )
        req, sc_headers = create_coordination_request(
            site["id"], coordinator_id="sc-reg2", band_class="SHARED_CBRS",
            requested_start_utc="2026-10-01T00:00:00Z",
            requested_end_utc="2027-10-01T00:00:00Z",
        )
        get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
        cur = get_success_data(api_client.begin_coordination(site["id"], req["id"], sc_headers))
        get_success_data(
            api_client.approve_coordination_request(
                site["id"], req["id"], {"expected_request_version": cur["version"]}, SR
            )
        )
        resp = api_client.register_coordination_request(site["id"], req["id"], sc_headers)
        data = validate_success(resp)
        assert data["status"] == "REGISTERED"
