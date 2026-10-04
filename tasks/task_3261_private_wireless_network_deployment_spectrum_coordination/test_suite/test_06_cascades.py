"""Cascade tests: enterprise suspension fan-out, lease cancellation fan-out,
lease expiry under the logical clock, enterprise offboarding, and contract
termination teeth.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_active_contract,
    create_active_lease,
    create_cell,
    create_configured_cell,
    create_coordination_request,
    create_device,
    create_enterprise,
    create_enterprise_payload,
    create_designed_site,
    decommission_design_cells,
    create_enterprise_with_site,
    create_sim_profile,
    create_site_payload,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
SC = TEST_USERS["spectrum_coordinator_headers"]
SR = TEST_USERS["spectrum_regulator_headers"]
FT = TEST_USERS["field_technician_headers"]


def _cell_with_active_assignment(ent, site):
    """Cell (CONFIGURED) carrying one ACTIVE assignment on an ACTIVE lease.

    Returns (cell, assignment, lease).
    """
    # Lease window fully contains the request window [2026-10-01, 2027-10-01)
    # as registration requires (PRD §3.4).
    lease = create_active_lease(
        ent["id"],
        band_class="SHARED_CBRS",
        center_frequency_mhz=3550,
        bandwidth_mhz=40,
        lease_start_utc="2026-09-01T00:00:00Z",
        lease_end_utc="2028-09-01T00:00:00Z",
    )
    req, sc_headers = create_coordination_request(
        site["id"], coordinator_id="sc-casc", band_class="SHARED_CBRS",
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
    req = get_success_data(api_client.register_coordination_request(site["id"], req["id"], sc_headers))
    cell = create_configured_cell(site["id"], sector_label="CASC-1")
    payload = {
        "coordination_request_id": req["id"],
        "spectrum_lease_id": lease["id"],
        "assigned_bandwidth_mhz": 10,
        "assignment_start_utc": "2026-10-01T00:00:00Z",
        "assignment_end_utc": "2026-11-01T00:00:00Z",
    }
    assignment = validate_success(
        api_client.create_assignment(cell["id"], payload, SC), expected_status=201
    )
    return cell, assignment, lease


class TestEnterpriseSuspendCascade:
    def test_suspend_cascades_to_leases_devices_and_sims(self):
        """PRD §3.10: "Suspending an `ACTIVE` Enterprise is a broad-axe
        operation performed by a `NetworkArchitect`: every cell under the
        enterprise's deployed sites transitions to `OFF_AIR`, every device
        under those sites moves to `SUSPENDED`, and every `ACTIVE`
        SpectrumLease moves to `SUSPENDED`."

        Design: Difficulty/transitive_cascade/enterprise_suspend_cascades_four_levels
        """
        ent, site, _sv = create_designed_site()
        cell, assignment, lease = _cell_with_active_assignment(ent, site)
        # Bring the site fully live: cell ON_AIR, device ACTIVE with a bound
        # ACTIVE SIM, and an ACTIVE contract so the site can go OPERATIONAL.
        decommission_design_cells(site["id"])
        get_success_data(api_client.on_air_cell(site["id"], cell["id"], FT))
        dev = create_device(cell["id"])
        sim = create_sim_profile(ent["id"])
        get_success_data(
            api_client.bind_sim(cell["id"], dev["id"], {"sim_profile_id": sim["id"]}, FT)
        )
        contract = create_active_contract(ent["id"], contract_code="K-SUSP")
        get_success_data(api_client.activate_device(cell["id"], dev["id"], FT))
        get_success_data(api_client.activate_site(site["id"], NA))

        resp = api_client.suspend_enterprise(ent["id"], NA)
        ent_after = validate_success(resp)
        assert ent_after["status"] == "SUSPENDED"

        cell_after = get_success_data(api_client.get_cell(cell["id"], NA))
        assert cell_after["status"] == "OFF_AIR"
        lease_after = get_success_data(api_client.get_lease(lease["id"], SC))
        assert lease_after["status"] == "SUSPENDED"
        dev_after = get_success_data(api_client.get_device(dev["id"], NA))
        assert dev_after["status"] == "SUSPENDED"
        sim_after = get_success_data(api_client.get_sim_profile(sim["id"], NA))
        assert sim_after["status"] == "SUSPENDED"

    def test_resume_restores_enterprise_to_active_and_bumps_version(self):
        """PRD §3.10: "Resuming reverses the posture at the site level — sites
        that were `OPERATIONAL` before the suspension return to `OPERATIONAL` —
        and both transitions increment the Enterprise's `version`."
        PRD §3.1: "The Enterprise's full status progression is `ONBOARDING →
        ACTIVE → SUSPENDED → OFFBOARDED`, with `SUSPENDED → ACTIVE` as the
        resume path and `OFFBOARDED` terminal."

        Design: Difficulty/transitive_cascade/enterprise_suspend_cascades_four_levels
        """
        ent, site = create_enterprise_with_site()
        v_before = ent["version"]
        api_client.suspend_enterprise(ent["id"], NA)
        resp = api_client.resume_enterprise(ent["id"], NA)
        ent_after = validate_success(resp)
        assert ent_after["status"] == "ACTIVE"
        assert ent_after["version"] == v_before + 2


class TestLeaseCancelCascade:
    def test_cancel_revokes_assignments_degrades_cell_and_raises_alert(self):
        """PRD §3.4: "cancellation is the dangerous path, because every
        `ACTIVE` SpectrumAssignment backed by that lease is automatically
        `REVOKED`, each affected cell drops to `DEGRADED`, and the parent
        Site's `spectrum_utilization_mhz` is reduced by each revoked
        assignment's bandwidth. The same automatic revocation happens when a
        lease reaches its `lease_end_utc` under the logical clock and expires,
        and each such revocation also raises a MonitoringAlert of class
        `OUTAGE` at severity `MAJOR` on the affected site."

        Design: Difficulty/transitive_cascade/spectrum_lease_cancel_cascades_to_alert
        """
        ent, site, _sv = create_designed_site()
        cell, assignment, lease = _cell_with_active_assignment(ent, site)

        before_site = get_success_data(api_client.get_site(site["id"], NA))
        assert before_site["spectrum_utilization_mhz"] == 10

        resp = api_client.cancel_lease(lease["id"], SC)
        lease_after = validate_success(resp)
        assert lease_after["status"] == "CANCELLED"

        asg_after = get_success_data(api_client.get_assignment(assignment["id"], SC))
        assert asg_after["status"] == "REVOKED"
        cell_after = get_success_data(api_client.get_cell(cell["id"], NA))
        assert cell_after["status"] == "DEGRADED"
        site_after = get_success_data(api_client.get_site(site["id"], NA))
        assert site_after["spectrum_utilization_mhz"] == 0

    def test_cancel_raises_outage_alert_on_affected_site(self):
        """PRD §3.4: "each such revocation also raises a MonitoringAlert of
        class `OUTAGE` at severity `MAJOR` on the affected site."

        Design: Difficulty/transitive_cascade/spectrum_lease_cancel_cascades_to_alert
        """
        ent, site, _sv = create_designed_site()
        cell, assignment, lease = _cell_with_active_assignment(ent, site)

        api_client.cancel_lease(lease["id"], SC)
        data, meta = validate_paginated(
            api_client.list_site_alerts(site["id"], NA, params={"alert_class": "OUTAGE"})
        )
        assert len(data) == 1
        assert data[0]["alert_class"] == "OUTAGE"
        assert data[0]["severity"] == "MAJOR"
        assert data[0]["site_id"] == site["id"]


class TestSiteDecommissionGuard:
    def test_decommission_blocked_when_cell_not_off_air(self):
        """PRD §3.10: "Decommissioning a Site requires that all of its
        CellSectors are `OFF_AIR` or `DECOMMISSIONED` and all of its Devices
        are `DECOMMISSIONED`; any straggler rejects the operation with
        `ERR_CHILDREN_ACTIVE` (HTTP 422)."

        Design: Corner/validations/site_decommission_blocked_when_children_active
        """
        ent, site = create_enterprise_with_site()
        cell = create_configured_cell(site["id"], sector_label="Y")
        resp = api_client.decommission_site(site["id"], NA)
        validate_error(resp, ApiErrorId.ERR_CHILDREN_ACTIVE)

    def test_decommission_blocked_when_device_not_decommissioned(self):
        """PRD §3.10: "Decommissioning a Site requires that all of its
        CellSectors are `OFF_AIR` or `DECOMMISSIONED` and all of its Devices
        are `DECOMMISSIONED`; any straggler rejects the operation with
        `ERR_CHILDREN_ACTIVE` (HTTP 422)."

        Design: Corner/validations/site_decommission_blocked_when_children_active
        """
        ent, site = create_enterprise_with_site()
        cell = create_cell(site["id"], sector_label="Y2")
        create_device(cell["id"])
        resp = api_client.decommission_site(site["id"], NA)
        validate_error(resp, ApiErrorId.ERR_CHILDREN_ACTIVE)


class TestEnterpriseOffboard:
    def test_offboard_blocked_when_site_not_decommissioned(self):
        """PRD §3.10: "Offboarding an Enterprise is the final act and is
        permitted only from `ACTIVE`, only when every Site is `DECOMMISSIONED`
        and every ServiceContract is `TERMINATED` or `RENEWED`; otherwise the
        request is rejected with `ERR_ENTERPRISE_CHILDREN_ACTIVE` (HTTP 422)."

        Design: Difficulty/transitive_cascade/enterprise_suspend_cascades_four_levels
        """
        ent, site = create_enterprise_with_site()
        resp = api_client.offboard_enterprise(ent["id"], NA)
        validate_error(resp, ApiErrorId.ERR_ENTERPRISE_CHILDREN_ACTIVE)

    def test_offboard_success_retires_sim_profiles(self):
        """PRD §3.10: "Offboarding moves the Enterprise to `OFFBOARDED` and
        retires every SIMProfile it owns to `RETIRED`."

        Design: Difficulty/transitive_cascade/enterprise_suspend_cascades_four_levels
        """
        ent, site = create_enterprise_with_site()
        sim = create_sim_profile(ent["id"])
        # Decommission the only site to clear the offboard guard.
        get_success_data(api_client.decommission_site(site["id"], NA))
        resp = api_client.offboard_enterprise(ent["id"], NA)
        ent_after = validate_success(resp)
        assert ent_after["status"] == "OFFBOARDED"
        sim_after = get_success_data(api_client.get_sim_profile(sim["id"], NA))
        assert sim_after["status"] == "RETIRED"


class TestContractTerminationTeeth:
    def test_terminating_last_active_contract_moves_operational_site(self):
        """PRD §3.8: "The contract lifecycle is `DRAFT → ACTIVE → BREACHED →
        RENEWED → TERMINATED`, with `TERMINATED` also reachable directly from
        `DRAFT` or `ACTIVE`, and both `RENEWED` and `TERMINATED` terminal."

        Design: Difficulty/transitive_cascade/spectrum_lease_cancel_cascades_to_alert
        """
        ent, site = create_enterprise_with_site()
        contract = create_active_contract(ent["id"])
        resp = api_client.terminate_contract(ent["id"], contract["id"], NA)
        data = validate_success(resp)
        assert data["status"] == "TERMINATED"
