"""CellSector, SpectrumAssignment, Device, and SIMProfile tests.

Covers cell transition guards, half-open assignment overlap, the
spectrum_utilization_mhz compensating invariant, duplicate IMEI, SIM
server-minted fields, and cross-enterprise SIM binding.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_device,
    assert_sim_profile,
    create_active_lease,
    create_cell,
    create_configured_cell,
    create_coordination_request,
    create_device,
    create_device_payload,
    create_enterprise,
    create_enterprise_payload,
    create_designed_site,
    create_enterprise_with_site,
    create_sim_profile,
    create_sim_profile_payload,
    create_site_payload,
    get_success_data,
    make_field_technician_headers,
    make_spectrum_coordinator_headers,
    validate_error,
    validate_success,
)

NA = TEST_USERS["network_architect_headers"]
RFE = TEST_USERS["rf_engineer_headers"]
SC = TEST_USERS["spectrum_coordinator_headers"]
FT = TEST_USERS["field_technician_headers"]

WIN_A = ("2026-10-01T00:00:00Z", "2026-11-01T00:00:00Z")
WIN_B = ("2026-11-01T00:00:00Z", "2026-12-01T00:00:00Z")


def _registered_request_and_active_lease(ent, site, bandwidth=40):
    """Drive a coordination request to REGISTERED and an ACTIVE lease whose
    window covers the request window. Returns (request, lease)."""
    lease = create_active_lease(
        ent["id"],
        band_class="SHARED_CBRS",
        center_frequency_mhz=3550,
        bandwidth_mhz=bandwidth,
        lease_start_utc="2026-09-01T00:00:00Z",
        lease_end_utc="2028-09-01T00:00:00Z",
    )
    req, sc_headers = create_coordination_request(
        site["id"], coordinator_id="sc-asn", band_class="SHARED_CBRS",
        requested_start_utc="2026-10-01T00:00:00Z",
        requested_end_utc="2027-10-01T00:00:00Z",
    )
    get_success_data(api_client.submit_coordination_request(site["id"], req["id"], sc_headers))
    cur = get_success_data(api_client.begin_coordination(site["id"], req["id"], sc_headers))
    get_success_data(
        api_client.approve_coordination_request(
            site["id"], req["id"], {"expected_request_version": cur["version"]},
            TEST_USERS["spectrum_regulator_headers"],
        )
    )
    req = get_success_data(
        api_client.register_coordination_request(site["id"], req["id"], sc_headers)
    )
    return req, lease


class TestCellTransitions:
    def test_off_air_from_configured_is_invalid(self):
        """PRD §3.5: "A `FieldTechnician` then walks the cell through `PLANNED
        → CONFIGURED → ON_AIR`, with `OFF_AIR` reachable from `ON_AIR`".
        PRD §2.9: "requesting a transition the resource's current state does
        not allow yields `ERR_INVALID_STATE` (HTTP 409)".

        Design: Corner/state_machines/cell_off_air_to_on_air_invalid
        """
        _ent, site = create_enterprise_with_site()
        cell = create_configured_cell(site["id"], sector_label="X")
        assert cell["status"] == "CONFIGURED"
        resp = api_client.off_air_cell(site["id"], cell["id"], FT)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_cell_created_in_planned_with_optimistic_margin(self):
        """PRD §3.5: "An `RFEngineer` creates a CellSector under a site in
        `PLANNED` status, giving a `sector_label` (such as NE-A or SW-B, unique
        within the Site), an `azimuth_degrees` between 0 and 359, an antenna
        `height_m` above ground, and a `max_eirp_dbm` ceiling. The server
        derives `cell_radius_m` from `height_m` and `max_eirp_dbm` via its
        propagation model, and initializes the cell's `interference_margin_db`
        to the optimistic 6 dB reserve against co-channel neighbors (the
        conservative variant used in final capacity computation is 9 dB)."

        Design: Corner/state_machines/cell_off_air_to_on_air_invalid
        """
        _ent, site = create_enterprise_with_site()
        resp = api_client.create_cell(
            site["id"],
            {"sector_label": "NEW-1", "azimuth_degrees": 90, "height_m": 20, "max_eirp_dbm": 40},
            RFE,
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "PLANNED"
        assert data["interference_margin_db"] == 6


class TestAssignmentOverlap:
    def test_adjacent_half_open_assignments_allowed(self):
        """PRD §2.11: "Overlap between two half-open windows means they share
        at least one instant — two windows that merely touch at a boundary (one
        ends exactly when the other begins) do not overlap."

        Design: Difficulty/resource_temporal_overlap/cell_assignment_half_open_disjoint
        """
        ent, site, _sv = create_designed_site()
        req, lease = _registered_request_and_active_lease(ent, site)
        cell = create_cell(site["id"], sector_label="HO-1")
        payload = {
            "coordination_request_id": req["id"],
            "spectrum_lease_id": lease["id"],
            "assigned_bandwidth_mhz": 10,
            "assignment_start_utc": WIN_A[0],
            "assignment_end_utc": WIN_A[1],
        }
        a1 = validate_success(api_client.create_assignment(cell["id"], payload, SC), expected_status=201)
        assert a1["status"] == "ACTIVE"

        payload2 = dict(payload, assignment_start_utc=WIN_B[0], assignment_end_utc=WIN_B[1])
        a2 = validate_success(api_client.create_assignment(cell["id"], payload2, SC), expected_status=201)
        assert a2["status"] == "ACTIVE"

    def test_overlapping_assignment_by_one_second_rejected(self):
        """PRD §3.5: "assignment windows on the same cell must be disjoint
        half-open intervals — an overlapping window is rejected with
        `ERR_ASSIGNMENT_OVERLAP` (HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/cell_assignment_half_open_disjoint
        """
        ent, site, _sv = create_designed_site()
        req, lease = _registered_request_and_active_lease(ent, site)
        cell = create_cell(site["id"], sector_label="HO-2")
        payload = {
            "coordination_request_id": req["id"],
            "spectrum_lease_id": lease["id"],
            "assigned_bandwidth_mhz": 10,
            "assignment_start_utc": WIN_A[0],
            "assignment_end_utc": WIN_A[1],
        }
        validate_success(api_client.create_assignment(cell["id"], payload, SC), expected_status=201)

        payload_overlap = dict(
            payload,
            assignment_start_utc="2026-10-01T00:00:01Z",
            assignment_end_utc="2026-11-01T00:00:00Z",
        )
        resp = api_client.create_assignment(cell["id"], payload_overlap, SC)
        validate_error(resp, ApiErrorId.ERR_ASSIGNMENT_OVERLAP)


class TestSpectrumUtilizationInvariant:
    def test_utilization_adds_then_release_restores(self):
        """PRD §3.1: "`spectrum_utilization_mhz`, the sum of
        `assigned_bandwidth_mhz` across all `ACTIVE` spectrum assignments on
        the site's cells".
        PRD §3.5: "A new assignment is immediately `ACTIVE`, and the site-level
        derived total reflects it at once: the parent Site's
        `spectrum_utilization_mhz` increases by the assigned bandwidth.
        Releasing an assignment … moves it to `RELEASED` and subtracts its
        bandwidth from the site's utilization."

        Design: Difficulty/compensating_invariant/site_spectrum_utilization_add_release_conserves
        """
        ent, site, _sv = create_designed_site()
        req, lease = _registered_request_and_active_lease(ent, site)
        cell = create_cell(site["id"], sector_label="CI-1")

        before = get_success_data(api_client.get_site(site["id"], NA))
        assert before["spectrum_utilization_mhz"] == 0

        payload = {
            "coordination_request_id": req["id"],
            "spectrum_lease_id": lease["id"],
            "assigned_bandwidth_mhz": 20,
            "assignment_start_utc": WIN_A[0],
            "assignment_end_utc": WIN_A[1],
        }
        assignment = validate_success(
            api_client.create_assignment(cell["id"], payload, SC), expected_status=201
        )
        after_add = get_success_data(api_client.get_site(site["id"], NA))
        assert after_add["spectrum_utilization_mhz"] == 20

        # Cell is PLANNED — release is permitted while PLANNED or OFF_AIR.
        resp = api_client.release_assignment(cell["id"], assignment["id"], FT)
        validate_success(resp)
        after_release = get_success_data(api_client.get_site(site["id"], NA))
        assert after_release["spectrum_utilization_mhz"] == 0

    def test_lease_bandwidth_exceeded_rejected(self):
        """PRD §3.5: "the sum of `assigned_bandwidth_mhz` across all `ACTIVE`
        assignments on the chosen lease, plus the new assignment, must not
        exceed the lease's total `bandwidth_mhz`, else the create fails with
        `ERR_LEASE_BANDWIDTH_EXCEEDED` (HTTP 422)."

        Design: Difficulty/compensating_invariant/site_spectrum_utilization_add_release_conserves
        """
        ent, site, _sv = create_designed_site()
        req, lease = _registered_request_and_active_lease(ent, site, bandwidth=30)
        cell = create_cell(site["id"], sector_label="CI-2")
        payload = {
            "coordination_request_id": req["id"],
            "spectrum_lease_id": lease["id"],
            "assigned_bandwidth_mhz": 25,
            "assignment_start_utc": WIN_A[0],
            "assignment_end_utc": WIN_A[1],
        }
        validate_success(api_client.create_assignment(cell["id"], payload, SC), expected_status=201)

        payload2 = dict(
            payload,
            assigned_bandwidth_mhz=10,  # 25 + 10 = 35 > 30
            assignment_start_utc=WIN_B[0],
            assignment_end_utc=WIN_B[1],
        )
        resp = api_client.create_assignment(cell["id"], payload2, SC)
        validate_error(resp, ApiErrorId.ERR_LEASE_BANDWIDTH_EXCEEDED)


class TestSimProfileSystemFields:
    def test_imsi_and_ki_server_minted(self):
        """PRD §3.6: "The server mints a unique 15-digit `imsi` and a
        `ki_key_ref` — a reference into the HSM vault that is never returned
        raw in any response."

        Design: Corner/entities/sim_profile_imsi_server_minted_not_input
        """
        ent, _site = create_enterprise_with_site()
        resp = api_client.create_sim_profile(ent["id"], create_sim_profile_payload(), FT)
        data = validate_success(resp, expected_status=201)
        assert_sim_profile(data)
        imsi = data["imsi"]
        assert isinstance(imsi, str) and len(imsi) == 15 and imsi.isdigit()
        assert isinstance(data["ki_key_ref"], str) and data["ki_key_ref"]
        assert data["status"] == "UNASSIGNED"

    def test_sim_defaults_applied_when_optional_fields_omitted(self):
        """PRD §3.6: "optionally a `subscription_profile` of `STANDARD`,
        `IOT_NBIOT`, `IOT_CATM`, or `PREMIUM_5G` (defaulting to `STANDARD`),
        and optionally a `monthly_quota_mb` data allowance defaulting to
        10,240 MB."

        Design: Corner/entities/sim_profile_imsi_server_minted_not_input
        """
        ent, _site = create_enterprise_with_site()
        resp = api_client.create_sim_profile(ent["id"], create_sim_profile_payload(), FT)
        data = validate_success(resp, expected_status=201)
        assert data["subscription_profile"] == "STANDARD"
        assert data["monthly_quota_mb"] == 10240


class TestDeviceUniqueness:
    def test_duplicate_imei_rejected(self):
        """PRD §2.10: "Globally — across all enterprises and sites — a
        Device's `serial_number` and `imei`, a SIMProfile's `iccid`, and an
        Enterprise's `erp_account_code` are each unique. A creation request
        colliding with any of these is rejected with
        `ERR_DUPLICATE_IDENTIFIER` (HTTP 409)."

        Design: Corner/entities/duplicate_imei_rejected
        """
        _ent, site = create_enterprise_with_site()
        cell = create_cell(site["id"], sector_label="DUP-1")
        create_device(cell["id"], serial_number="SN-A", imei="111111111111111")
        resp = api_client.create_device(
            cell["id"],
            create_device_payload(serial_number="SN-B", imei="111111111111111"),
            FT,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER)

    def test_duplicate_serial_number_rejected(self):
        """PRD §2.10: "Globally — across all enterprises and sites — a
        Device's `serial_number` and `imei` … are each unique. A creation
        request colliding with any of these is rejected with
        `ERR_DUPLICATE_IDENTIFIER` (HTTP 409)."

        Design: Corner/entities/duplicate_imei_rejected
        """
        _ent, site = create_enterprise_with_site()
        cell = create_cell(site["id"], sector_label="DUP-2")
        create_device(cell["id"], serial_number="SN-DUP", imei="222222222222222")
        resp = api_client.create_device(
            cell["id"],
            create_device_payload(serial_number="SN-DUP", imei="333333333333333"),
            FT,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER)


class TestCrossEnterpriseSimBinding:
    def test_cross_enterprise_bind_rejected(self):
        """PRD §3.6: "the bind succeeds only when the named SIMProfile exists,
        is `UNASSIGNED`, and belongs to the same Enterprise as the device's
        site — a cross-enterprise bind is rejected with
        `ERR_CROSS_ENTERPRISE_REFERENCE` (HTTP 422)".

        Design: Corner/validations/cross_enterprise_sim_binding_rejected
        """
        ent_a, site_a = create_enterprise_with_site(
            ent_overrides={"erp_account_code": "A-001"}
        )
        ent_b = create_enterprise(legal_name="B Co", erp_account_code="B-001")
        # Enterprise B needs a site before it can activate.
        site_b = get_success_data(
            api_client.create_site(ent_b["id"], create_site_payload(site_code="B1"), NA)
        )
        get_success_data(api_client.activate_enterprise(ent_b["id"], NA))

        cell_a = create_configured_cell(site_a["id"], sector_label="A")
        dev = create_device(cell_a["id"], serial_number="SN-X", imei="999999999999999")
        sim_b = create_sim_profile(ent_b["id"])

        resp = api_client.bind_sim(cell_a["id"], dev["id"], {"sim_profile_id": sim_b["id"]}, FT)
        validate_error(resp, ApiErrorId.ERR_CROSS_ENTERPRISE_REFERENCE)

    def test_same_enterprise_bind_succeeds_and_flips_sim_to_bound(self):
        """PRD §3.6: "On success the device moves `INVENTORY → PROVISIONING`,
        its `sim_profile_id` is set, and the SIM moves to `BOUND`."

        Design: Corner/validations/cross_enterprise_sim_binding_rejected
        """
        ent, site = create_enterprise_with_site()
        cell = create_configured_cell(site["id"], sector_label="OK")
        dev = create_device(cell["id"])
        sim = create_sim_profile(ent["id"])

        resp = api_client.bind_sim(cell["id"], dev["id"], {"sim_profile_id": sim["id"]}, FT)
        data = validate_success(resp)
        assert data["status"] == "PROVISIONING"
        assert data["sim_profile_id"] == sim["id"]
        sim_after = get_success_data(api_client.get_sim_profile(sim["id"], NA))
        assert sim_after["status"] == "BOUND"
