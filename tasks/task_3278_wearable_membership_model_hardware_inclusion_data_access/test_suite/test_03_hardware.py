"""Hardware tests: upgrades, device continuity, replacement logistics."""
from test_helpers import (
    ApiErrorId,
    create_member_with_term,
    create_and_activate_device,
    create_ingest_payload,
    create_release_payload,
    get_success_data,
    make_member_headers,
    make_platform_admin_headers,
    make_support_headers,
    provision_device_for,
    set_clock,
    setup_member_with_active_device,
    setup_approved_replacement,
    setup_open_replacement_request,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestUpgradeEligibilityBoundary:
    def test_upgrade_eligibility_inclusive_month_boundary(self, api, anonymous_headers):
        """PRD: "The upgrade proceeds only when the full months elapsed are at
        least upgrade_eligibility_months — the boundary is inclusive — and
        otherwise the request is rejected with ERR_UPGRADE_NOT_ELIGIBLE."

        Design: Difficulty/boundary_precision_check/upgrade_eligibility_inclusive_month_boundary
        """
        member, term = create_member_with_term(
            commitment_months=24, upgrade_eligibility_months=6
        )
        create_and_activate_device(member["id"], term["id"])
        headers = make_member_headers(member["id"])
        set_clock("2027-02-28T00:00:00Z")
        terms, _ = validate_paginated(api.list_member_terms(member["id"], headers))
        term_version = terms[0]["version"]
        resp = api.upgrade_term(
            term["id"], {"expected_term_version": term_version}, headers
        )
        validate_error(resp, ApiErrorId.ERR_UPGRADE_NOT_ELIGIBLE, expected_status=422)
        set_clock("2027-03-01T00:00:00Z")
        upgraded = validate_success(
            api.upgrade_term(term["id"], {"expected_term_version": term_version}, headers)
        )
        assert upgraded["last_upgrade_on"] == "2027-03-01"
        assert upgraded["version"] == term_version + 1

    def test_upgrade_success_creates_provisioned_band_pro_device(self, api, anonymous_headers):
        """PRD: "On success, last_upgrade_on is stamped with today, the term's
        version increments, and a new PROVISIONED device of hardware tier BAND_PRO
        is created for the member under this term and returned in the response."

        Design: Difficulty/boundary_precision_check/upgrade_eligibility_inclusive_month_boundary
        """
        member, term = create_member_with_term(
            commitment_months=24, upgrade_eligibility_months=6
        )
        create_and_activate_device(member["id"], term["id"])
        headers = make_member_headers(member["id"])
        set_clock("2027-03-01T00:00:00Z")
        terms, _ = validate_paginated(api.list_member_terms(member["id"], headers))
        validate_success(
            api.upgrade_term(
                term["id"], {"expected_term_version": terms[0]["version"]}, headers
            )
        )
        devices, _ = validate_paginated(
            api.list_devices(make_support_headers(), params={"member_id": member["id"]})
        )
        assert len(devices) == 2
        new_devices = [d for d in devices if d["device_status"] == "PROVISIONED"]
        assert len(new_devices) == 1
        assert new_devices[0]["hardware_tier"] == "BAND_PRO"


class TestUpgradeOcc:
    def test_occ_stale_version_on_term_upgrade(self, api, anonymous_headers):
        """PRD: "A hardware upgrade request on a term must carry
        expected_term_version equal to that term's current version."
        PRD: "In both cases, a mismatch between the supplied expectation and the
        parent's current version is rejected with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_term_upgrade
        """
        member, term = create_member_with_term(
            upgrade_eligibility_months=0, pause_days_per_term=10
        )
        headers = make_member_headers(member["id"])
        captured_v0 = term["version"]
        # A pause+resume cycle mutates the term, bumping its version past v0.
        resp = api.pause_term(
            term["id"], {"start_on": "2026-09-01", "days": 2}, headers
        )
        get_success_data(resp)
        resp = api.upgrade_term(
            term["id"], {"expected_term_version": captured_v0}, headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_stale_version_on_term_upgrade_after_resume(self, api, anonymous_headers):
        """PRD: "A hardware upgrade request on a term must carry
        expected_term_version equal to that term's current version."
        PRD: "In both cases, a mismatch between the supplied expectation and the
        parent's current version is rejected with ERR_STALE_VERSION (HTTP 412)."

        Design: Corner/validations/occ_stale_version_on_term_upgrade
        """
        member, term = create_member_with_term(
            upgrade_eligibility_months=0, pause_days_per_term=10
        )
        headers = make_member_headers(member["id"])
        captured_v0 = term["version"]
        get_success_data(
            api.pause_term(term["id"], {"start_on": "2026-09-01", "days": 2}, headers)
        )
        get_success_data(api.resume_term(term["id"], headers))
        resp = api.upgrade_term(
            term["id"], {"expected_term_version": captured_v0}, headers
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestDeviceContinuityOverlap:
    def test_device_continuity_closed_interval_same_day_conflicts(self, api, anonymous_headers):
        """PRD: "a brand-new device whose first covered day would coincide with
        another device of the same member still covering that day is rejected with
        ERR_CONTINUITY_WINDOW_OVERLAP — same-day adjacency counts as overlap."

        Design: Difficulty/resource_temporal_overlap/device_continuity_closed_interval_same_day_conflicts
        """
        member, term = create_member_with_term()
        create_and_activate_device(member["id"], term["id"], serial_number="SN-V1")
        device2 = provision_device_for(member["id"], term["id"], serial_number="SN-V2")
        resp = api.activate_device(device2["id"], make_member_headers(member["id"]))
        validate_error(
            resp, ApiErrorId.ERR_CONTINUITY_WINDOW_OVERLAP, expected_status=409
        )

    def test_device_continuity_overlap_leaves_second_device_provisioned(self, api, anonymous_headers):
        """PRD: "a brand-new device whose first covered day would coincide with
        another device of the same member still covering that day is rejected with
        ERR_CONTINUITY_WINDOW_OVERLAP — same-day adjacency counts as overlap."

        Design: Difficulty/resource_temporal_overlap/device_continuity_closed_interval_same_day_conflicts
        """
        member, term = create_member_with_term()
        create_and_activate_device(member["id"], term["id"], serial_number="SN-V1")
        device2 = provision_device_for(member["id"], term["id"], serial_number="SN-V2")
        api.activate_device(device2["id"], make_member_headers(member["id"]))
        device2_after = validate_success(
            api.get_device(device2["id"], make_support_headers())
        )
        assert device2_after["device_status"] == "PROVISIONED"


class TestReplacementFlow:
    def test_replacement_already_open_rejected(self, api, anonymous_headers):
        """PRD: "A device may carry at most one OPEN request — a second attempt is
        rejected with ERR_REPLACEMENT_ALREADY_OPEN".

        Design: Corner/errors/replacement_already_open
        """
        member, term, device, request = setup_open_replacement_request()
        assert request["request_status"] == "OPEN"
        resp = api.open_replacement_request(
            device["id"], {"reason": "BATTERY_DRAIN"}, make_member_headers(member["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REPLACEMENT_ALREADY_OPEN, expected_status=422)

    def test_decide_reject_no_fault_restores_device_active(self, api, anonymous_headers):
        """PRD: "A decision of REJECT carries a diagnosis in the payload: with
        NO_FAULT the device returns to ACTIVE as a compensating restore and its
        diagnosis is set to NO_FAULT; with USER_DAMAGE the device remains
        SUSPECT_FAULT. Either way the request lands in the terminal REJECTED
        state."

        Design: Difficulty/cross_entity_state_dependency/replacement_decide_requires_device_faulty_and_term_open
        """
        member, term, device, request = setup_open_replacement_request()
        support = make_support_headers()
        decided = validate_success(
            api.decide_replacement_request(
                request["id"], {"decision": "REJECT", "diagnosis": "NO_FAULT"}, support
            )
        )
        assert decided["request_status"] == "REJECTED"
        device_after = validate_success(api.get_device(device["id"], support))
        assert device_after["device_status"] == "ACTIVE"
        assert device_after["diagnosis"] == "NO_FAULT"

    def test_decide_approve_after_no_fault_reject_and_second_request(self, api, anonymous_headers):
        """PRD: "A decision of APPROVE records the request's diagnosis as
        CONFIRMED_FAILURE and fires a two-sibling cascade: the faulty device moves
        to RMA_INBOUND, and a fresh PROVISIONED device is created for the same
        member_id and term_id with a server-minted serial, its id stored on the
        request as replacement_device_id."

        Design: Difficulty/cross_entity_state_dependency/replacement_decide_requires_device_faulty_and_term_open
        """
        member, term, device = setup_member_with_active_device()
        headers = make_member_headers(member["id"])
        support = make_support_headers()
        # First request: rejected NO_FAULT, device returns to ACTIVE.
        r1 = validate_success(
            api.open_replacement_request(device["id"], {"reason": "HARDWARE_FAILURE"}, headers),
            expected_status=201,
        )
        validate_success(
            api.decide_replacement_request(
                r1["id"], {"decision": "REJECT", "diagnosis": "NO_FAULT"}, support
            )
        )
        # Second request: device re-faults; approve creates the replacement.
        r2 = validate_success(
            api.open_replacement_request(device["id"], {"reason": "SENSOR_DRIFT"}, headers),
            expected_status=201,
        )
        decided = validate_success(
            api.decide_replacement_request(r2["id"], {"decision": "APPROVE"}, support)
        )
        assert decided["request_status"] == "APPROVED"
        assert decided["diagnosis"] == "CONFIRMED_FAILURE"
        replacement_id = decided["replacement_device_id"]
        assert replacement_id
        device_after = validate_success(api.get_device(device["id"], support))
        assert device_after["device_status"] == "RMA_INBOUND"
        replacement = validate_success(api.get_device(replacement_id, support))
        assert replacement["device_status"] == "PROVISIONED"
        assert replacement["member_id"] == member["id"]
        assert replacement["term_id"] == term["id"]
        # A second decide on the terminal R1 must fail.
        resp = api.decide_replacement_request(
            r1["id"], {"decision": "APPROVE"}, support
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    def test_terminal_state_lockdown_replacement_decide_twice(self, api, anonymous_headers):
        """PRD: "Either way the request lands in the terminal REJECTED state."

        Design: Corner/state_machines/terminal_state_lockdown_replacement_decide_twice
        """
        member, term, device, request = setup_open_replacement_request(
            reason="BATTERY_DRAIN"
        )
        support = make_support_headers()
        validate_success(
            api.decide_replacement_request(
                request["id"], {"decision": "REJECT", "diagnosis": "USER_DAMAGE"}, support
            )
        )
        resp = api.decide_replacement_request(
            request["id"], {"decision": "APPROVE"}, support
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION, expected_status=409)

    def test_terminal_state_lockdown_leaves_device_untouched(self, api, anonymous_headers):
        """PRD: "with USER_DAMAGE the device remains SUSPECT_FAULT."

        Design: Corner/state_machines/terminal_state_lockdown_replacement_decide_twice
        """
        member, term, device, request = setup_open_replacement_request(
            reason="BATTERY_DRAIN"
        )
        support = make_support_headers()
        validate_success(
            api.decide_replacement_request(
                request["id"], {"decision": "REJECT", "diagnosis": "USER_DAMAGE"}, support
            )
        )
        api.decide_replacement_request(request["id"], {"decision": "APPROVE"}, support)
        device_after = validate_success(api.get_device(device["id"], support))
        assert device_after["device_status"] == "SUSPECT_FAULT"


class TestContinuityConservationAcrossReplacement:
    def test_continuity_days_conserved_across_replacement_swap(self, api, anonymous_headers):
        """PRD: "When that precondition holds, the replacement's continuity_start_on
        is stitched to the faulty device's continuity_end_on plus one day — which
        may be earlier than today, deliberately backfilling the data-continuity
        gap."
        PRD: "the faulty device moves from RMA_INBOUND to RETIRED with
        continuity_end_on stamped today — closing its interval inclusive of
        today".

        Design: Difficulty/compensating_invariant/continuity_days_conserved_across_replacement_swap
        """
        member, term, faulty, request, replacement_id = setup_approved_replacement(
            reason="BATTERY_DRAIN"
        )
        set_clock("2026-09-03T00:00:00Z")
        support = make_support_headers()
        validate_success(api.receive_return(request["id"], support))
        activated = validate_success(
            api.activate_device(replacement_id, make_member_headers(member["id"]))
        )
        faulty_after = validate_success(api.get_device(faulty["id"], support))
        assert faulty_after["device_status"] == "RETIRED"
        assert faulty_after["continuity_start_on"] == "2026-09-01"
        assert faulty_after["continuity_end_on"] == "2026-09-03"
        assert activated["device_status"] == "ACTIVE"
        assert activated["continuity_start_on"] == "2026-09-04"

    def test_continuity_stitch_is_exactly_one_day_after_faulty_end(self, api, anonymous_headers):
        """PRD: "A member's data history is stitchable across devices precisely
        because the replacement's first covered day is defined as the faulty
        device's last covered day plus one."

        Design: Difficulty/compensating_invariant/continuity_days_conserved_across_replacement_swap
        """
        member, term, faulty, request, replacement_id = setup_approved_replacement()
        support = make_support_headers()
        validate_success(api.receive_return(request["id"], support))
        activated = validate_success(
            api.activate_device(replacement_id, make_member_headers(member["id"]))
        )
        faulty_after = validate_success(api.get_device(faulty["id"], support))
        assert faulty_after["continuity_end_on"] == "2026-09-01"
        assert activated["continuity_start_on"] == "2026-09-02"
