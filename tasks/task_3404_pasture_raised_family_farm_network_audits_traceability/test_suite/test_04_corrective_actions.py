"""Corrective-action lifecycle: rework loop, segregation of duties, overdue cascade."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_route_conservation,
    complete_audit,
    create_active_farm,
    create_farm,
    get_farm,
    get_route,
    list_audit_corrective_actions,
    make_auditor_headers,
    schedule_audit,
    set_clock,
    setup_route_with_stop,
    submit_corrective_action,
    validate_error,
    validate_success,
    verify_corrective_action,
)
from test_helpers import TEST_USERS

NM = TEST_USERS["network_manager_headers"]


def _farm_with_open_ca(severity, description, auditor_user_id="auditor-a"):
    """Farm + INITIAL audit completed CORRECTIVE_ACTION_REQUIRED with one finding;
    returns (farm_id, audit_id, corrective_action row)."""
    farm = create_farm(name="CA Farm")
    farm_id = farm["id"]
    audit = schedule_audit(farm_id)
    set_clock("2026-09-03T09:00:00Z")
    complete_audit(
        audit["id"],
        "CORRECTIVE_ACTION_REQUIRED",
        findings=[{"severity": severity, "description": description}],
        auditor_user_id=auditor_user_id,
    )
    cas = list_audit_corrective_actions(audit["id"])
    assert len(cas) == 1, f"expected exactly one corrective action, got {len(cas)}"
    return farm_id, audit["id"], cas[0]


def test_corrective_action_reject_rework_cycle(api):
    """PRD §3.3: "A `REJECT` decision sends the action back to `OPEN` for rework
    with its `due_at` unchanged — the same corrective action may cycle through
    submission and rejection repeatedly until it is verified or the farm is
    removed."

    Design: Corner/state_machines/corrective_action_reject_rework_cycle
    """
    _, _, ca = _farm_with_open_ca("MAJOR", "insufficient nest pad depth")
    original_due_at = ca["due_at"]

    submitted = submit_corrective_action(ca["id"], "added shavings")
    assert submitted["status"] == "SUBMITTED"

    rejected = verify_corrective_action(ca["id"], "REJECT", auditor_user_id="auditor-b")
    assert rejected["status"] == "OPEN", "REJECT returns the action to OPEN (rework loop)"
    assert rejected["due_at"] == original_due_at, (
        f"rejection must not extend the deadline: {rejected['due_at']} != {original_due_at}"
    )
    assert rejected.get("verified_by_user_id") is None


def test_ca_verify_by_same_auditor_returns_sod_violation(api):
    """PRD §3.3: "Verification is segregated: the verifying auditor's `X-User-ID`
    must differ from the `auditor_user_id` recorded on the parent audit, and a
    verdict attempted by the same auditor who completed that audit is refused
    with `ERR_SOD_VIOLATION` (HTTP 403)."

    Design: Corner/state_machines/ca_verify_by_same_auditor_returns_sod_violation
    """
    _, _, ca = _farm_with_open_ca("MINOR", "record book gaps", auditor_user_id="auditor-x")
    submit_corrective_action(ca["id"], "records updated")

    resp = api.verify_corrective_action(
        ca["id"], {"decision": "VERIFY_CLOSED"}, make_auditor_headers("auditor-x")
    )
    validate_error(resp, ApiErrorId.ERR_SOD_VIOLATION, 403)

    # Re-read via the parent audit list: submit moved it to SUBMITTED, and the
    # SoD rejection must not move it.
    cas = list_audit_corrective_actions(ca["audit_id"])
    assert cas[0]["status"] == "SUBMITTED", (
        f"no state change on SoD rejection, got {cas[0]['status']}"
    )


def test_ca_verify_when_not_submitted_returns_invalid_state(api):
    """PRD §3.3: "A verdict is only legal while the action is `SUBMITTED`;
    anything else is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/ca_verify_when_not_submitted_returns_invalid_state
    """
    _, _, ca = _farm_with_open_ca("CRITICAL", "birds without pasture access")
    assert ca["status"] == "OPEN"

    resp = api.verify_corrective_action(
        ca["id"], {"decision": "VERIFY_CLOSED"}, make_auditor_headers("auditor-b")
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def _setup_critical_ca_overdue():
    """ACTIVE farm with a SCHEDULED 6-case stop on a capacity-10 route, plus an
    ANNUAL audit completed CORRECTIVE_ACTION_REQUIRED with one CRITICAL finding
    at 2026-10-03T09:00:00Z (due 2026-10-10T09:00:00Z)."""
    bundle = create_active_farm(name="Hilltop Layers")
    farm_id = bundle["farm"]["id"]
    route_bundle = setup_route_with_stop(
        farm_id, route_date="2026-09-20", planned_cases=6, capacity_cases=10
    )
    route_id = route_bundle["route"]["id"]
    audit2 = schedule_audit(farm_id, "ANNUAL", "2026-10-03T00:00:00Z")
    set_clock("2026-10-03T09:00:00Z")
    complete_audit(
        audit2["id"],
        "CORRECTIVE_ACTION_REQUIRED",
        findings=[{"severity": "CRITICAL", "description": "broken fencing perimeter"}],
    )
    return farm_id, audit2["id"], route_id


def test_critical_ca_overdue_flips_ca_and_suspends_farm(api):
    """PRD §2.5: "every corrective action in `OPEN` or `SUBMITTED` whose `due_at`
    is now strictly in the past flips to `OVERDUE`, and each flip escalates the
    farm by severity: a `CRITICAL` finding suspends the farm if it is currently
    `ACTIVE` or `PROBATION`, triggering the stop-skip cascade described in §3.4"

    Design: Difficulty/transitive_cascade/critical_ca_overdue_suspends_farm_skips_stops_restores_capacity
    """
    farm_id, audit2_id, _ = _setup_critical_ca_overdue()

    # Advance strictly past the CRITICAL deadline (2026-10-10T09:00:00Z).
    set_clock("2026-10-11T00:00:00Z")

    cas = list_audit_corrective_actions(audit2_id)
    assert cas[0]["status"] == "OVERDUE", (
        f"expected OVERDUE after the clock passed due_at, got {cas[0]['status']}"
    )

    farm = get_farm(farm_id)
    assert farm["status"] == "SUSPENDED", (
        f"CRITICAL overdue suspends an ACTIVE farm, got {farm['status']}"
    )


def test_critical_ca_overdue_skips_stop_and_restores_capacity(api):
    """PRD §3.4: "every stop naming that farm still in `SCHEDULED` status on any
    route still `PLANNED` flips to `SKIPPED`, and each affected route recomputes
    its `committed_cases` and `available_cases` per the conservation rule of
    §2.9, releasing the skipped stops' planned capacity."

    Design: Difficulty/transitive_cascade/critical_ca_overdue_suspends_farm_skips_stops_restores_capacity
    """
    farm_id, _, route_id = _setup_critical_ca_overdue()

    route_before = get_route(route_id)
    assert route_before["committed_cases"] == 6
    assert route_before["available_cases"] == 4

    set_clock("2026-10-11T00:00:00Z")

    farm = get_farm(farm_id)
    assert farm["status"] == "SUSPENDED"

    route = get_route(route_id)
    stop = next(s for s in route["stops"] if s["stop_sequence"] == 1)
    assert stop["status"] == "SKIPPED", f"suspension skips the scheduled stop, got {stop['status']}"
    assert route["committed_cases"] == 0
    assert route["available_cases"] == 10
    assert_route_conservation(route)
