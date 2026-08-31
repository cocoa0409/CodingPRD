"""The cyber dimension: security findings, quarantine and the parallel state axes."""

from test_helpers import (
    ApiErrorId,
    assert_security_finding,
    assert_timestamp_equals,
    bootstrap_monitor_campus,
    bootstrap_pump_campus,
    cancel_work_order,
    create_security_finding,
    intake_work_order,
    read_device,
    resolve_security_finding,
    set_security_state,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_an_undeclared_security_transition_is_rejected(api, security_officer_headers):
    """PRD §3.8: "The officer may also drive the cyber dimension directly, supplying a
    `to_state` and an optional `note`. Seven transitions are declared, and any request for a
    pair not on this list is rejected with `ERR_INVALID_SECURITY_STATE`."
    PRD §3.8: "From `UNASSESSED` the unit may move to `ASSESSED_OK` or to `VULNERABLE`."

    Design: Corner/state_machines/device_security_unassessed_to_remediated_returns_invalid_security_state
    """
    scene = bootstrap_monitor_campus(model_overrides={"is_network_connected": True})
    device_id = scene["device"]["id"]

    response = api.set_device_security_state(device_id, {"to_state": "REMEDIATED"},
                                             security_officer_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_SECURITY_STATE.value, 409)

    device = read_device(device_id)
    assert device["security_state"] == "UNASSESSED"
    assert device["operational_state"] == "IN_SERVICE"


def test_a_critical_finding_quarantines_and_downs_the_unit(api, security_officer_headers):
    """PRD §3.8: "The finding is created with `status` `OPEN`, `discovered_at` from the logical
    clock, and null `resolution_note` and `resolved_at`. Its `remediation_due_at` is derived by
    adding whole days to `discovered_at` according to the severity band: 7 days for `CRITICAL`,
    30 days for `HIGH`, 90 days for `MEDIUM` and 180 days for `LOW`."
    PRD §3.8: "A `CRITICAL` finding sets the device's `security_state` to `QUARANTINED` from
    whatever state it was in, and brings the full quarantine cascade with it."

    Design: Corner/state_machines/critical_security_finding_quarantines_device_on_create
    """
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]

    response = api.create_security_finding(
        {"device_id": device_id, "severity": "CRITICAL",
         "advisory_reference": "CVE-2026-9001", "requires_downtime": True},
        security_officer_headers,
    )
    data = validate_success(response, 201)
    assert_security_finding(data)

    assert data["status"] == "OPEN"
    assert_timestamp_equals(data["discovered_at"], "2026-08-01T00:00:00Z", "discovered_at")
    assert_timestamp_equals(data["remediation_due_at"], "2026-08-08T00:00:00Z",
                            "remediation_due_at")

    device = read_device(device_id)
    assert device["security_state"] == "QUARANTINED"
    assert device["operational_state"] == "DOWN"

    listed, meta = validate_paginated(
        api.list_security_findings(security_officer_headers, params={"device_id": device_id})
    )
    assert len(listed) == 1
    assert meta["total_count"] == 1


def test_mitigating_the_quarantining_finding_restores_the_unit(api, security_officer_headers):
    """PRD §3.8: "A `MITIGATED` resolution stamps `resolved_at`, sets the finding's `status` to
    `MITIGATED`, moves a device that this finding had quarantined `QUARANTINED` → `REMEDIATED`,
    and restores that device from `DOWN` to `IN_SERVICE` when nothing else holds it down — no
    non-terminal work order and no recall hold."

    Design: Corner/state_machines/security_finding_mitigated_restores_quarantined_device
    """
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]
    finding = create_security_finding(device_id, severity="CRITICAL",
                                      advisory_reference="CVE-2026-9001")
    assert read_device(device_id)["operational_state"] == "DOWN"

    data = validate_success(
        api.resolve_security_finding(finding["id"],
                                     {"resolution": "MITIGATED",
                                      "note": "Firmware 4.2.1 applied"},
                                     security_officer_headers),
        200,
    )
    assert data["status"] == "MITIGATED"
    assert_timestamp_equals(data["resolved_at"], "2026-08-01T00:00:00Z", "resolved_at")

    device = read_device(device_id)
    assert device["security_state"] == "REMEDIATED"
    assert device["operational_state"] == "IN_SERVICE"


def test_an_open_finding_blocks_the_move_to_assessed_ok(api, security_officer_headers):
    """PRD §3.8: "Both moves into `ASSESSED_OK` — the one from `UNASSESSED` and the one from
    `REMEDIATED` — carry the same precondition: no finding on that device may be `OPEN` or
    `REMEDIATION_SCHEDULED`, or the attempt is rejected with `ERR_SECURITY_FINDING_OPEN`."
    PRD §3.8: "A `MEDIUM` or `LOW` finding changes `security_state` not at all."

    Design: Corner/validations/security_state_assessed_ok_blocked_by_open_finding
    """
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]
    finding = create_security_finding(device_id, severity="MEDIUM",
                                      advisory_reference="CVE-2026-1234")
    assert_timestamp_equals(finding["remediation_due_at"], "2026-10-30T00:00:00Z",
                            "remediation_due_at")

    blocked = api.set_device_security_state(device_id, {"to_state": "ASSESSED_OK"},
                                            security_officer_headers)
    validate_error(blocked, ApiErrorId.ERR_SECURITY_FINDING_OPEN.value, 422)
    assert read_device(device_id)["security_state"] == "UNASSESSED"

    resolved = resolve_security_finding(finding["id"], "ACCEPTED_RISK",
                                        note="Compensating network control in place")
    assert resolved["status"] == "ACCEPTED_RISK"

    data = validate_success(
        api.set_device_security_state(device_id, {"to_state": "ASSESSED_OK"},
                                      security_officer_headers),
        200,
    )
    assert data["security_state"] == "ASSESSED_OK"
    assert data["operational_state"] == "IN_SERVICE", (
        "A MEDIUM finding never downs a unit, so availability is untouched throughout"
    )


def test_a_security_move_leaves_availability_untouched(api, security_officer_headers,
                                                       biomed_tech_headers):
    """PRD §2.8: "The two dimensions evolve on separate axes. Moving a unit to `ASSESSED_OK`,
    to `VULNERABLE`, or from `VULNERABLE` to `REMEDIATED` leaves `operational_state` untouched."
    PRD §3.4: "Intake takes the unit `DOWN`."

    Design: Difficulty/non_linear_state_machine/device_operational_and_security_dimensions_advance_independently
    """
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]

    assessed = validate_success(
        api.set_device_security_state(device_id, {"to_state": "ASSESSED_OK"},
                                      security_officer_headers),
        200,
    )
    assert assessed["security_state"] == "ASSESSED_OK"
    assert assessed["operational_state"] == "IN_SERVICE"

    validate_success(
        api.create_work_order({"device_id": device_id, "reported_severity": "ROUTINE",
                               "problem_summary": "Keypad unresponsive"},
                              biomed_tech_headers),
        201,
    )
    device = read_device(device_id)
    assert device["operational_state"] == "DOWN"
    assert device["security_state"] == "ASSESSED_OK", (
        "Work-order intake must not touch the cyber dimension"
    )


def test_availability_and_cyber_states_advance_on_separate_axes(api, security_officer_headers):
    """PRD §2.8: "Symmetrically, work-order and recall activity moves `operational_state`
    without ever changing `security_state`."
    PRD §3.8: "From `ASSESSED_OK` it may move to `VULNERABLE`, which removes it from the loaner
    candidate set from that instant on but leaves `operational_state` untouched."

    Design: Difficulty/non_linear_state_machine/device_operational_and_security_dimensions_advance_independently
    """
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]
    set_security_state(device_id, "ASSESSED_OK")
    order = intake_work_order(device_id, problem_summary="Keypad unresponsive")

    vulnerable = validate_success(
        api.set_device_security_state(device_id,
                                      {"to_state": "VULNERABLE",
                                       "note": "Advisory pending triage"},
                                      security_officer_headers),
        200,
    )
    assert vulnerable["operational_state"] == "DOWN"
    assert vulnerable["security_state"] == "VULNERABLE"

    cancelled = cancel_work_order(order["id"], reason="Resolved by user education")
    assert cancelled["status"] == "CANCELLED"

    device = read_device(device_id)
    assert device["operational_state"] == "IN_SERVICE"
    assert device["security_state"] == "VULNERABLE", (
        "Cancelling the order must not roll the cyber dimension back"
    )
