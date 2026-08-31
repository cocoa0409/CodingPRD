"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared endpoints,
because the harness restarts the server (and therefore empties the database) before
each individual test. Setup calls use the lenient validator so a broken precondition
surfaces as a clear "Setup step failed" rather than as a confusing assertion.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    MONITOR_MODEL,
    MONITOR_UNIT,
    POOL_MONITOR_UNIT,
    PUMP_MODEL,
    PUMP_UNIT,
    SCALE_MODEL,
    SCALE_UNIT,
    VENTILATOR_MODEL,
    create_department_payload,
    create_device_model_payload,
    create_device_payload,
    create_facility_payload,
    create_loaner_assignment_payload,
    create_pm_task_payload,
    create_recall_notice_payload,
    create_security_finding_payload,
    create_service_contract_payload,
    create_vendor_payload,
    create_work_order_payload,
)
from .test_users import (
    TEST_USERS,
    make_biomed_tech_headers,
    make_dept_steward_headers,
    make_vendor_rep_headers,
)

MANAGER = TEST_USERS["ce_manager_headers"]
TECH = TEST_USERS["biomed_tech_headers"]
TECH_PEER = TEST_USERS["biomed_tech_peer_headers"]
OFFICER = TEST_USERS["security_officer_headers"]


# ─── Tier 0: primitive creators ────────────────────────────────────────────

def set_clock(to_iso8601: str) -> str:
    """Move the logical UTC clock and return the resulting current_utc."""
    data = get_success_data(api_client.set_clock({"to_iso8601": to_iso8601}, MANAGER))
    return data.get("current_utc")


def create_facility(**overrides) -> dict:
    return get_success_data(
        api_client.create_facility(create_facility_payload(**overrides), MANAGER)
    )


def create_department(facility_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_department(create_department_payload(facility_id, **overrides), MANAGER)
    )


def create_vendor(**overrides) -> dict:
    return get_success_data(
        api_client.create_vendor(create_vendor_payload(**overrides), MANAGER)
    )


def create_device_model(base=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_device_model(create_device_model_payload(base, **overrides), MANAGER)
    )


def create_pump_model(**overrides) -> dict:
    return create_device_model(PUMP_MODEL, **overrides)


def create_monitor_model(**overrides) -> dict:
    return create_device_model(MONITOR_MODEL, **overrides)


def create_scale_model(**overrides) -> dict:
    return create_device_model(SCALE_MODEL, **overrides)


def create_ventilator_model(**overrides) -> dict:
    return create_device_model(VENTILATOR_MODEL, **overrides)


def create_device(facility_id: str, department_id: str, device_model_id: str,
                  base=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_device(
            create_device_payload(facility_id, department_id, device_model_id, base, **overrides),
            MANAGER,
        )
    )


def create_service_contract(vendor_id: str, device_model_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_service_contract(
            create_service_contract_payload(vendor_id, device_model_id, **overrides), MANAGER
        )
    )


def create_security_finding(device_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_security_finding(
            create_security_finding_payload(device_id, **overrides), OFFICER
        )
    )


def set_security_state(device_id: str, to_state: str, note: str = None) -> dict:
    payload = {"to_state": to_state}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.set_device_security_state(device_id, payload, OFFICER))


def resolve_security_finding(finding_id: str, resolution: str, note: str = None,
                             headers=None) -> dict:
    payload = {"resolution": resolution}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.resolve_security_finding(finding_id, payload, headers or OFFICER)
    )


def set_posture(facility_id: str, to_posture: str, note: str = None) -> dict:
    payload = {"to_posture": to_posture}
    if note is not None:
        payload["note"] = note
    return get_success_data(api_client.set_facility_posture(facility_id, payload, MANAGER))


def run_pm_audit(facility_id: str) -> dict:
    return get_success_data(api_client.run_pm_audit(facility_id, MANAGER))


# ─── Tier 0b: readers used to thread OCC versions ──────────────────────────

def read_facility(facility_id: str) -> dict:
    return get_success_data(api_client.get_facility(facility_id, MANAGER))


def read_department(department_id: str) -> dict:
    return get_success_data(api_client.get_department(department_id, MANAGER))


def department_version(department_id: str) -> int:
    return read_department(department_id)["version"]


def read_device(device_id: str) -> dict:
    return get_success_data(api_client.get_device(device_id, MANAGER))


def read_work_order(work_order_id: str) -> dict:
    return get_success_data(api_client.get_work_order(work_order_id, MANAGER))


def work_order_version(work_order_id: str) -> int:
    return read_work_order(work_order_id)["version"]


def read_pm_task(pm_task_id: str) -> dict:
    return get_success_data(api_client.get_pm_task(pm_task_id, MANAGER))


def read_loaner_assignment(loaner_id: str) -> dict:
    return get_success_data(api_client.get_loaner_assignment(loaner_id, MANAGER))


def read_recall_notice(notice_id: str) -> dict:
    return get_success_data(api_client.get_recall_notice(notice_id, MANAGER))


def read_recall_match(match_id: str) -> dict:
    return get_success_data(api_client.get_recall_match(match_id, MANAGER))


def read_service_contract(contract_id: str) -> dict:
    return get_success_data(api_client.get_service_contract(contract_id, MANAGER))


def read_security_finding(finding_id: str) -> dict:
    return get_success_data(api_client.get_security_finding(finding_id, OFFICER))


# ─── Tier 1: campus bootstraps ─────────────────────────────────────────────

def bootstrap_campus(model_factory=create_monitor_model, device_base=None,
                     dept_overrides=None, facility_overrides=None,
                     device_overrides=None, model_overrides=None) -> dict:
    """Facility + department + catalogue model + one unit.

    Returns {"facility", "department", "model", "device"}.
    """
    facility = create_facility(**(facility_overrides or {}))
    department = create_department(facility["id"], **(dept_overrides or {}))
    model = model_factory(**(model_overrides or {}))
    device = create_device(
        facility["id"], department["id"], model["id"],
        device_base if device_base is not None else MONITOR_UNIT,
        **(device_overrides or {}),
    )
    return {"facility": facility, "department": department, "model": model, "device": device}


def bootstrap_pump_campus(**kwargs) -> dict:
    """Cardiac Cath Lab + a network-connected infusion pump scoring CRITICAL (38)."""
    kwargs.setdefault("model_factory", create_pump_model)
    kwargs.setdefault("device_base", PUMP_UNIT)
    kwargs.setdefault("dept_overrides", {"name": "Cardiac Cath Lab",
                                         "cost_center_code": "CC-4100"})
    return bootstrap_campus(**kwargs)


def bootstrap_monitor_campus(**kwargs) -> dict:
    """Telemetry Unit + a non-network patient monitor scoring MEDIUM (22)."""
    kwargs.setdefault("model_factory", create_monitor_model)
    kwargs.setdefault("device_base", MONITOR_UNIT)
    return bootstrap_campus(**kwargs)


def bootstrap_monitor_campus_with_pool(pool_overrides=None, **kwargs) -> dict:
    """Monitor campus plus one same-model unit flagged into the loaner pool."""
    scene = bootstrap_monitor_campus(**kwargs)
    scene["pool_device"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["model"]["id"],
        POOL_MONITOR_UNIT, **(pool_overrides or {}),
    )
    return scene


def bootstrap_pump_campus_with_pool(pool_overrides=None, **kwargs) -> dict:
    """Pump campus plus one same-model network-connected unit in the loaner pool."""
    scene = bootstrap_pump_campus(**kwargs)
    overrides = {
        "serial_number": "SN-1002",
        "acquisition_date": "2023-01-10",
        "acquisition_cost_cents": 3_100_000,
        "condition_score": 2,
        "is_loaner_pool": True,
    }
    overrides.update(pool_overrides or {})
    scene["pool_device"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["model"]["id"],
        PUMP_UNIT, **overrides,
    )
    return scene


# ─── Tier 2: work-order lifecycle steps ────────────────────────────────────

def intake_work_order(device_id: str, headers=None, **overrides) -> dict:
    return get_success_data(
        api_client.create_work_order(create_work_order_payload(device_id, **overrides),
                                     headers or TECH)
    )


def assign_work_order(work_order_id: str, service_mode: str = "IN_HOUSE",
                      vendor_id: str = None, headers=None) -> dict:
    payload = {"service_mode": service_mode}
    if vendor_id is not None:
        payload["vendor_id"] = vendor_id
    return get_success_data(
        api_client.assign_work_order(work_order_id, payload, headers or TECH)
    )


def parts_hold_work_order(work_order_id: str, note: str = None, headers=None) -> dict:
    payload = {} if note is None else {"note": note}
    return get_success_data(
        api_client.parts_hold_work_order(work_order_id, payload, headers or TECH)
    )


def resume_work_order(work_order_id: str, headers=None) -> dict:
    return get_success_data(api_client.resume_work_order(work_order_id, headers or TECH))


def complete_repair(work_order_id: str, labor_minutes: int, parts_cost_cents: int = 0,
                    headers=None) -> dict:
    payload = {"labor_minutes": labor_minutes, "parts_cost_cents": parts_cost_cents}
    return get_success_data(
        api_client.complete_repair(work_order_id, payload, headers or TECH)
    )


def verify_work_order(work_order_id: str, result: str = "PASS", note: str = None,
                      headers=None) -> dict:
    payload = {"result": result}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.verify_work_order(work_order_id, payload, headers or TECH_PEER)
    )


def close_work_order(work_order_id: str, department_id: str, expected_version: int = None,
                     headers=None) -> dict:
    version = expected_version if expected_version is not None else department_version(department_id)
    return get_success_data(
        api_client.close_work_order(work_order_id, {"expected_department_version": version},
                                    headers or MANAGER)
    )


def cancel_work_order(work_order_id: str, reason: str = "Cancelled by manager",
                      headers=None) -> dict:
    return get_success_data(
        api_client.cancel_work_order(work_order_id, {"reason": reason}, headers or MANAGER)
    )


def drive_to_verified(device_id: str, labor_minutes: int = 60, parts_cost_cents: int = 0,
                      service_mode: str = "IN_HOUSE", vendor_id: str = None,
                      repair_headers=None, intake_headers=None, **intake_overrides) -> dict:
    """Intake -> assign -> complete-repair -> verify. Returns the VERIFIED order."""
    order = intake_work_order(device_id, headers=intake_headers, **intake_overrides)
    assign_work_order(order["id"], service_mode=service_mode, vendor_id=vendor_id,
                      headers=MANAGER if service_mode == "VENDOR" else TECH)
    complete_repair(order["id"], labor_minutes, parts_cost_cents,
                    headers=repair_headers or TECH)
    return verify_work_order(order["id"], "PASS", headers=TECH_PEER)


def drive_to_closed(device_id: str, department_id: str, labor_minutes: int = 60,
                    parts_cost_cents: int = 0, service_mode: str = "IN_HOUSE",
                    vendor_id: str = None, repair_headers=None, **intake_overrides) -> dict:
    """Full in-house or vendor lifecycle through CLOSED. Returns the CLOSED order."""
    verified = drive_to_verified(device_id, labor_minutes, parts_cost_cents,
                                 service_mode=service_mode, vendor_id=vendor_id,
                                 repair_headers=repair_headers, **intake_overrides)
    return close_work_order(verified["id"], department_id)


# ─── Tier 3: PM, loaner, recall and contract helpers ───────────────────────

def create_pm_task(device_id: str, window_start: str = None, window_end: str = None,
                   headers=None) -> dict:
    overrides = {}
    if window_start is not None:
        overrides["window_start"] = window_start
    if window_end is not None:
        overrides["window_end"] = window_end
    return get_success_data(
        api_client.create_pm_task(create_pm_task_payload(device_id, **overrides),
                                  headers or MANAGER)
    )


def complete_pm_task(pm_task_id: str, result: str = "PASS", labor_minutes: int = 30,
                     headers=None) -> dict:
    payload = {"result": result, "labor_minutes": labor_minutes}
    return get_success_data(
        api_client.complete_pm_task(pm_task_id, payload, headers or TECH)
    )


def defer_pm_task(pm_task_id: str, new_window_start: str, new_window_end: str,
                  reason: str = "Clinical schedule conflict") -> dict:
    payload = {
        "new_window_start": new_window_start,
        "new_window_end": new_window_end,
        "reason": reason,
    }
    return get_success_data(api_client.defer_pm_task(pm_task_id, payload, MANAGER))


def create_loaner_assignment(work_order_id: str, expected_version: int = None,
                             headers=None, **overrides) -> dict:
    version = (expected_version if expected_version is not None
               else work_order_version(work_order_id))
    payload = create_loaner_assignment_payload(work_order_id, version, **overrides)
    return get_success_data(
        api_client.create_loaner_assignment(payload, headers or MANAGER)
    )


def return_loaner_assignment(loaner_id: str, headers=None) -> dict:
    return get_success_data(
        api_client.return_loaner_assignment(loaner_id, headers or MANAGER)
    )


def create_recall_notice(facility_id: str, device_model_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_recall_notice(
            create_recall_notice_payload(facility_id, device_model_id, **overrides), MANAGER
        )
    )


def publish_recall_notice(notice_id: str) -> dict:
    return get_success_data(api_client.publish_recall_notice(notice_id, MANAGER))


def close_recall_notice(notice_id: str) -> dict:
    return get_success_data(api_client.close_recall_notice(notice_id, MANAGER))


def list_recall_matches(**params) -> list:
    body = get_success_data(api_client.list_recall_matches(MANAGER, params=params or None))
    return body


def first_recall_match_id(notice_id: str) -> str:
    matches = list_recall_matches(recall_notice_id=notice_id)
    assert matches, f"Setup step failed: recall notice {notice_id} produced no matches"
    return matches[0]["id"]


def disposition_recall_match(match_id: str, disposition: str, note: str = None,
                             headers=None) -> dict:
    payload = {"disposition": disposition}
    if note is not None:
        payload["note"] = note
    return get_success_data(
        api_client.disposition_recall_match(match_id, payload, headers or MANAGER)
    )


# ─── Tier 4: threshold / accumulation targeting ────────────────────────────

def setup_verified_in_house_repair(dept_budget: int = 5_000_000, labor_minutes: int = 60,
                                   parts_cost_cents: int = 0, assign_clock: str = None,
                                   dept_name: str = "Telemetry Unit",
                                   dept_code: str = "CC-5200") -> dict:
    """Monitor campus with one in-house repair sitting at VERIFIED, ready to close.

    A day-shift assignment pins shift_multiplier_applied at 1.0, so the list-rate
    labour term is exactly labor_minutes * 9000 / 60.
    """
    scene = bootstrap_monitor_campus(
        dept_overrides={"downtime_budget_cents": dept_budget, "name": dept_name,
                        "cost_center_code": dept_code}
    )
    if assign_clock:
        set_clock(assign_clock)
    scene["work_order"] = drive_to_verified(scene["device"]["id"], labor_minutes,
                                            parts_cost_cents)
    return scene


def setup_department_on_hold(budget: int = 10_000, labor_minutes: int = 400) -> dict:
    """Close one repair large enough to drive the department to ON_HOLD.

    With a 10,000-cent ceiling a 400-minute in-house repair posts 60,000 cents,
    so post-debit spend passes the ceiling and budget_state becomes ON_HOLD.
    """
    scene = bootstrap_monitor_campus(
        dept_overrides={"downtime_budget_cents": budget, "name": "Respiratory Therapy",
                        "cost_center_code": "CC-7100"}
    )
    set_clock("2026-08-02T09:00:00Z")
    scene["work_order"] = drive_to_closed(scene["device"]["id"], scene["department"]["id"],
                                          labor_minutes=labor_minutes,
                                          problem_summary="First repair")
    scene["department"] = read_department(scene["department"]["id"])
    return scene


def setup_downed_monitor_with_pool_unit(dept_budget: int = 5_000_000,
                                        pool_overrides=None) -> dict:
    """Monitor campus, one same-model pool unit, and the downed unit at IN_REPAIR."""
    scene = bootstrap_monitor_campus_with_pool(
        dept_overrides={"downtime_budget_cents": dept_budget},
        pool_overrides=pool_overrides,
    )
    scene["work_order"] = intake_work_order(scene["device"]["id"])
    scene["work_order"] = assign_work_order(scene["work_order"]["id"])
    return scene


def setup_vendor_repair_ready_to_close(deductible_cents: int = 25000,
                                       covered_event_cap: int = 2,
                                       coverage_start: str = "2026-01-01T00:00:00Z",
                                       coverage_end: str = "2026-12-31T00:00:00Z",
                                       assign_clock: str = "2026-08-03T21:00:00Z",
                                       labor_minutes: int = 95,
                                       parts_cost_cents: int = 15000,
                                       dept_budget: int = 5_000_000,
                                       with_contract: bool = True) -> dict:
    """Pump campus + approved vendor (+ optional covering contract) + VERIFIED order.

    The assign clock defaults to 21:00 UTC, outside the 07:00-19:00 day shift, so
    shift_multiplier_applied is pinned at 1.5.
    """
    scene = bootstrap_pump_campus(
        dept_overrides={"downtime_budget_cents": dept_budget, "name": "Cardiac Cath Lab",
                        "cost_center_code": "CC-4100"}
    )
    scene["vendor"] = create_vendor()
    if with_contract:
        scene["contract"] = create_service_contract(
            scene["vendor"]["id"], scene["model"]["id"],
            coverage_start=coverage_start, coverage_end=coverage_end,
            deductible_cents=deductible_cents, covered_event_cap=covered_event_cap,
        )
    set_clock(assign_clock)
    order = intake_work_order(scene["device"]["id"],
                              reported_severity="CLINICAL_IMPACT",
                              problem_summary="Occlusion alarm will not clear")
    assign_work_order(order["id"], service_mode="VENDOR",
                      vendor_id=scene["vendor"]["id"], headers=MANAGER)
    complete_repair(order["id"], labor_minutes, parts_cost_cents,
                    headers=make_vendor_rep_headers(scene["vendor"]["id"]))
    scene["work_order"] = verify_work_order(order["id"], "PASS", headers=TECH_PEER)
    return scene


def setup_pm_compliance_divergence() -> dict:
    """Three PM tasks on one pump whose statuses split the two audit denominators.

    Task A is completed on time inside its window, task B is left untouched so the
    sweep moves it to MISSED, and task C is deferred exactly once into a window that
    is still ahead of the audit clock.  Returns the scene plus the three tasks; the
    caller runs the audit itself.
    """
    scene = bootstrap_pump_campus(
        facility_overrides={"pm_compliance_target_pct": 90.00},
        device_overrides={"lot_number": "LOT-A7", "utilization_hours": 12000},
    )
    device_id = scene["device"]["id"]
    scene["task_a"] = create_pm_task(device_id, "2026-08-01T00:00:00Z", "2026-08-01T23:59:00Z")
    scene["task_b"] = create_pm_task(device_id, "2026-08-02T00:00:00Z", "2026-08-02T23:59:00Z")
    scene["task_c"] = create_pm_task(device_id, "2026-08-03T00:00:00Z", "2026-08-03T23:59:00Z")

    set_clock("2026-08-01T10:00:00Z")
    complete_pm_task(scene["task_a"]["id"], "PASS", 45)
    set_clock("2026-08-03T09:00:00Z")
    defer_pm_task(scene["task_c"]["id"], "2026-08-20T00:00:00Z", "2026-08-20T23:59:00Z",
                  reason="Vendor parts backorder")
    set_clock("2026-08-10T00:00:00Z")
    return scene


def setup_pm_audit_with_empty_window() -> dict:
    """A campus whose only PM task opens entirely after the audit clock.

    Nothing is due, so both compliance denominators are empty.
    """
    scene = bootstrap_pump_campus(facility_overrides={"pm_compliance_target_pct": 90.00})
    scene["pm_task"] = create_pm_task(scene["device"]["id"],
                                      "2026-09-01T00:00:00Z", "2026-09-01T23:59:00Z")
    return scene


def setup_pm_task_deferred_twice() -> dict:
    """A PM task that has already consumed both permitted deferrals."""
    scene = bootstrap_monitor_campus()
    task = create_pm_task(scene["device"]["id"],
                          "2026-08-10T00:00:00Z", "2026-08-10T23:59:00Z")
    defer_pm_task(task["id"], "2026-08-25T00:00:00Z", "2026-08-25T23:59:00Z",
                  reason="Unit in clinical use")
    scene["pm_task"] = defer_pm_task(task["id"], "2026-09-10T00:00:00Z",
                                     "2026-09-10T23:59:00Z",
                                     reason="Technician unavailable")
    return scene


def setup_quarantined_device_with_expired_pm_window() -> dict:
    """A quarantined pump whose PM window closed before the current clock."""
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]
    scene["pm_task"] = create_pm_task(device_id, "2026-08-01T00:00:00Z",
                                      "2026-08-01T12:00:00Z")
    set_security_state(device_id, "VULNERABLE")
    set_security_state(device_id, "QUARANTINED", note="Unpatched firmware on clinical VLAN")
    set_clock("2026-08-05T00:00:00Z")
    return scene


def setup_pump_repair_complete_day_shift(labor_minutes: int = 60) -> dict:
    """A pump order assigned at 09:00 UTC and completed once, sitting at REPAIR_COMPLETE.

    The 09:00 assignment falls inside the day shift, so shift_multiplier_applied is
    pinned at 1.0 for the life of the order.
    """
    scene = bootstrap_pump_campus()
    set_clock("2026-08-02T09:00:00Z")
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Intermittent air-in-line fault")
    assign_work_order(order["id"])
    set_clock("2026-08-02T11:00:00Z")
    scene["work_order"] = complete_repair(order["id"], labor_minutes, 0)
    return scene


def setup_work_order_with_deployed_pool_loaner(dept_budget: int = 5_000_000,
                                               start_at: str = "2026-08-01T00:00:00Z",
                                               end_at: str = "2026-08-08T00:00:00Z") -> dict:
    """A downed monitor at IN_REPAIR whose coverage is a DEPLOYED pool unit.

    Intake is performed by the owning department's steward so the ownership rule is
    exercised the way the department actually reports faults.
    """
    scene = bootstrap_monitor_campus_with_pool(
        dept_overrides={"downtime_budget_cents": dept_budget}
    )
    steward = make_dept_steward_headers(scene["department"]["id"])
    order = intake_work_order(scene["device"]["id"], headers=steward,
                              problem_summary="Reported drift, later found in spec")
    scene["work_order"] = assign_work_order(order["id"])
    scene["loaner"] = create_loaner_assignment(
        order["id"], expected_version=scene["work_order"]["version"],
        loaner_device_id=scene["pool_device"]["id"], start_at=start_at, end_at=end_at,
    )
    return scene


def setup_locked_down_campus_with_intake() -> dict:
    """A pump campus driven to LOCKDOWN with one work order already at INTAKE."""
    scene = bootstrap_pump_campus()
    set_posture(scene["facility"]["id"], "LOCKDOWN", note="Facility-wide network incident")
    scene["work_order"] = intake_work_order(scene["device"]["id"],
                                            problem_summary="Screen backlight failure")
    return scene


def setup_repair_with_parts_hold_ready_to_close() -> dict:
    """A CRITICAL pump repair split by a 21.5-hour parts hold, verified and ready to close.

    Segments: 09:00-11:30 on 2026-08-02 (2.5 h) and 09:00-10:15 on 2026-08-03 (1.25 h),
    with the AWAITING_PARTS span between them excluded from active repair time.
    """
    scene = bootstrap_pump_campus()
    set_clock("2026-08-02T08:00:00Z")
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Pump stalls mid-infusion")
    set_clock("2026-08-02T09:00:00Z")
    assign_work_order(order["id"])
    set_clock("2026-08-02T11:30:00Z")
    parts_hold_work_order(order["id"], note="Motor assembly on order")
    set_clock("2026-08-03T09:00:00Z")
    resume_work_order(order["id"])
    set_clock("2026-08-03T10:15:00Z")
    complete_repair(order["id"], 225, 0)
    scene["work_order"] = verify_work_order(order["id"], "PASS")
    set_clock("2026-08-03T12:00:00Z")
    return scene


def setup_pre_debit_tier_scene(budget: int = 1_000_000, first_labor_minutes: int = 1000,
                               first_parts_cost_cents: int = 350_000,
                               second_labor_minutes: int = 60) -> dict:
    """One closed repair plus a second verified repair, so the tier reading is observable.

    The first close runs against a pre-debit spend of 0 (tier T0); the second close then
    sees the spend the first one posted.
    """
    scene = bootstrap_pump_campus(
        dept_overrides={"downtime_budget_cents": budget, "name": "Cardiac Cath Lab",
                        "cost_center_code": "CC-4100"}
    )
    device_id = scene["device"]["id"]
    set_clock("2026-08-02T08:00:00Z")
    first = drive_to_verified(device_id, first_labor_minutes, first_parts_cost_cents,
                              problem_summary="Annual calibration drift")
    set_clock("2026-08-02T12:00:00Z")
    scene["first_order"] = close_work_order(first["id"], scene["department"]["id"])
    scene["second_order"] = drive_to_verified(device_id, second_labor_minutes, 0,
                                              problem_summary="Battery pack replacement")
    return scene


def setup_close_debit_cascade_scene(budget: int = 100_000, labor_minutes: int = 400) -> dict:
    """Two 60,000-cent repairs against a 100,000-cent ceiling.

    The first close leaves the department OPEN at 60,000; the second is verified and
    waiting, and its T1-tiered charge will push the department past the ceiling.
    """
    scene = bootstrap_pump_campus(
        dept_overrides={"downtime_budget_cents": budget, "name": "Endoscopy",
                        "cost_center_code": "CC-6100"}
    )
    device_id = scene["device"]["id"]
    set_clock("2026-08-02T09:00:00Z")
    first = drive_to_verified(device_id, labor_minutes, 0,
                              problem_summary="Pressure sensor drift")
    scene["first_order"] = close_work_order(first["id"], scene["department"]["id"])
    scene["second_order"] = drive_to_verified(device_id, labor_minutes, 0,
                                              problem_summary="Door interlock switch")
    return scene


def setup_verified_repair_with_deployed_pool_loaner() -> dict:
    """A verified 9,000-cent in-house repair whose pool loaner is still DEPLOYED."""
    scene = bootstrap_monitor_campus_with_pool()
    set_clock("2026-08-02T09:00:00Z")
    order = intake_work_order(scene["device"]["id"], problem_summary="Fan bearing noise")
    assigned = assign_work_order(order["id"])
    scene["loaner"] = create_loaner_assignment(
        order["id"], expected_version=assigned["version"],
        loaner_device_id=scene["pool_device"]["id"],
        start_at="2026-08-02T09:00:00Z", end_at="2026-08-06T09:00:00Z",
    )
    complete_repair(order["id"], 60, 0)
    scene["work_order"] = verify_work_order(order["id"], "PASS")
    return scene


def setup_rental_loaner_on_critical_unit(start_at: str = "2026-08-01T00:00:00Z",
                                         end_at: str = "2026-08-11T00:00:00Z") -> dict:
    """A CRITICAL pump downed by an in-house order, covered by an external RENTAL."""
    scene = bootstrap_pump_campus()
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Display flicker under load")
    assigned = assign_work_order(order["id"])
    scene["work_order"] = assigned
    scene["loaner"] = create_loaner_assignment(
        order["id"], expected_version=assigned["version"], source="RENTAL",
        start_at=start_at, end_at=end_at,
    )
    return scene


def setup_quarantined_pool_unit_scene() -> dict:
    """The only same-model pool unit driven UNASSESSED -> VULNERABLE -> QUARANTINED."""
    scene = bootstrap_monitor_campus_with_pool()
    set_security_state(scene["pool_device"]["id"], "VULNERABLE")
    set_security_state(scene["pool_device"]["id"], "QUARANTINED",
                       note="Telnet service exposed")
    order = intake_work_order(scene["device"]["id"], problem_summary="SpO2 module dropout")
    scene["work_order"] = assign_work_order(order["id"])
    return scene


def setup_networked_pool_unit_unassessed() -> dict:
    """A network-connected pump campus whose pool unit is still at security_state UNASSESSED."""
    scene = bootstrap_pump_campus_with_pool()
    order = intake_work_order(scene["device"]["id"], problem_summary="Pump motor noise")
    scene["work_order"] = assign_work_order(order["id"])
    return scene


def setup_pool_unit_after_one_returned_occupancy() -> dict:
    """A pool unit whose first occupancy [08-01T08:00, 08-05T08:00) is already RETURNED."""
    scene = bootstrap_monitor_campus_with_pool()
    set_clock("2026-08-01T08:00:00Z")
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Alarm speaker distortion")
    assigned = assign_work_order(order["id"])
    scene["work_order"] = assigned
    scene["first_loaner"] = create_loaner_assignment(
        order["id"], expected_version=assigned["version"],
        loaner_device_id=scene["pool_device"]["id"],
        start_at="2026-08-01T08:00:00Z", end_at="2026-08-05T08:00:00Z",
    )
    set_clock("2026-08-05T08:00:00Z")
    scene["first_loaner"] = return_loaner_assignment(scene["first_loaner"]["id"])
    return scene


def setup_two_pool_units_awaiting_selection() -> dict:
    """Two same-model pool units at condition_score 2 and 4 and one downed unit at IN_REPAIR.

    The pinned ranking (condition_score ASC) must pick the condition-2 unit.
    """
    scene = bootstrap_monitor_campus_with_pool()
    scene["pool_device_two"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["model"]["id"],
        POOL_MONITOR_UNIT, serial_number="SN-2003", condition_score=4,
    )
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="NIBP cuff inflation fault")
    scene["work_order"] = assign_work_order(order["id"])
    return scene


def count_available_pool_units(facility_id: str) -> int:
    """Pool units at a campus that are still IN_SERVICE — the conserved capacity figure."""
    body = api_client.list_devices(
        MANAGER,
        params={"facility_id": facility_id, "is_loaner_pool": "true",
                "operational_state": "IN_SERVICE"},
    )
    return len(get_success_data(body))


def setup_published_class_ii_recall() -> dict:
    """A CLASS_II notice already published against one matching monitor."""
    scene = bootstrap_monitor_campus()
    scene["notice"] = create_recall_notice(scene["facility"]["id"], scene["model"]["id"],
                                           source_reference="FDA-2026-3001",
                                           hazard_class="CLASS_II")
    scene["notice"] = publish_recall_notice(scene["notice"]["id"])
    return scene


def setup_lot_scoped_recall() -> dict:
    """Two same-model monitors on lots LOT-C1 and LOT-C2 with a DRAFT notice naming LOT-C1."""
    scene = bootstrap_monitor_campus(device_overrides={"lot_number": "LOT-C1"})
    scene["miss_device"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["model"]["id"],
        MONITOR_UNIT, serial_number="SN-2002", lot_number="LOT-C2",
    )
    scene["notice"] = create_recall_notice(
        scene["facility"]["id"], scene["model"]["id"],
        source_reference="FDA-2026-4001", hazard_class="CLASS_II",
        affected_lot_numbers=["LOT-C1"],
    )
    return scene


def setup_two_model_recall_branches() -> dict:
    """One campus, two models with one unit each, and a DRAFT notice on each hazard branch."""
    scene = bootstrap_pump_campus(device_overrides={"lot_number": "LOT-A7"})
    scene["monitor_model"] = create_monitor_model()
    scene["monitor_device"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["monitor_model"]["id"],
        MONITOR_UNIT, serial_number="SN-2001", lot_number="LOT-C1",
    )
    scene["class_i_notice"] = create_recall_notice(
        scene["facility"]["id"], scene["model"]["id"],
        source_reference="FDA-2026-1188", hazard_class="CLASS_I",
        response_due_at="2026-09-01T00:00:00Z",
    )
    scene["class_iii_notice"] = create_recall_notice(
        scene["facility"]["id"], scene["monitor_model"]["id"],
        source_reference="FDA-2026-2044", hazard_class="CLASS_III",
        response_due_at="2026-10-01T00:00:00Z",
    )
    return scene


def setup_class_i_cascade_scene() -> dict:
    """A parked P3 order covered by a pool unit that a DRAFT CLASS_I notice will match.

    The downed monitor sits at AWAITING_PARTS, and a same-model pool unit is ON_LOAN
    covering it, so publishing the notice must run the whole four-link chain.
    """
    scene = bootstrap_monitor_campus_with_pool()
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="ECG lead noise on channel 2")
    assign_work_order(order["id"])
    held = parts_hold_work_order(order["id"], note="Awaiting lead set")
    scene["work_order"] = held
    scene["loaner"] = create_loaner_assignment(
        order["id"], expected_version=held["version"],
        loaner_device_id=scene["pool_device"]["id"],
        start_at="2026-08-01T00:00:00Z", end_at="2026-08-08T00:00:00Z",
    )
    scene["notice"] = create_recall_notice(
        scene["facility"]["id"], scene["model"]["id"],
        source_reference="FDA-2026-1188", hazard_class="CLASS_I",
        response_due_at="2026-09-01T00:00:00Z",
    )
    return scene


def setup_published_class_iii_recall_with_pending_match() -> dict:
    """A published CLASS_III notice whose single match is still PENDING."""
    scene = bootstrap_monitor_campus()
    scene["notice"] = create_recall_notice(scene["facility"]["id"], scene["model"]["id"],
                                           source_reference="FDA-2026-3003",
                                           hazard_class="CLASS_III")
    scene["notice"] = publish_recall_notice(scene["notice"]["id"])
    scene["match_id"] = first_recall_match_id(scene["notice"]["id"])
    return scene


def setup_replacement_plan_scene() -> dict:
    """Three units at one campus scoring 60.63, 54.50 and 21.75 on three different models."""
    scene = bootstrap_pump_campus()
    scene["monitor_model"] = create_monitor_model()
    scene["scale_model"] = create_scale_model()
    scene["monitor_device"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["monitor_model"]["id"],
        MONITOR_UNIT,
    )
    scene["scale_device"] = create_device(
        scene["facility"]["id"], scene["department"]["id"], scene["scale_model"]["id"],
        SCALE_UNIT,
    )
    return scene


def setup_tied_replacement_scores() -> dict:
    """Two ventilators on a 2-year-life model, both saturating the age factor at 1.0.

    The newer unit is created FIRST, so created_at cannot be what decides the ranking.
    """
    facility = create_facility()
    department = create_department(facility["id"], name="Respiratory Therapy",
                                   cost_center_code="CC-7100")
    model = create_ventilator_model()
    newer = create_device(facility["id"], department["id"], model["id"], MONITOR_UNIT,
                          serial_number="SN-NEWER", acquisition_date="2018-01-01",
                          acquisition_cost_cents=480_000, condition_score=3)
    older = create_device(facility["id"], department["id"], model["id"], MONITOR_UNIT,
                          serial_number="SN-OLDER", acquisition_date="2015-01-01",
                          acquisition_cost_cents=470_000, condition_score=3)
    return {"facility": facility, "department": department, "model": model,
            "newer_device": newer, "older_device": older}


def setup_retired_device_in_on_hold_department() -> dict:
    """A retired pump whose department is simultaneously past its downtime ceiling.

    A 60,000-cent repair against a 10,000-cent ceiling flips the department to ON_HOLD,
    and a CLASS_III recall match dispositioned REMOVED retires the unit, so a fresh
    intake violates both the retirement rule and the budget rule at once.
    """
    scene = bootstrap_pump_campus(
        dept_overrides={"downtime_budget_cents": 10_000, "name": "Respiratory Therapy",
                        "cost_center_code": "CC-7100"},
        device_overrides={"lot_number": "LOT-A7"},
    )
    set_clock("2026-08-02T09:00:00Z")
    scene["closed_order"] = drive_to_closed(scene["device"]["id"], scene["department"]["id"],
                                            labor_minutes=400,
                                            problem_summary="Flow sensor fault")
    scene["notice"] = create_recall_notice(scene["facility"]["id"], scene["model"]["id"],
                                           source_reference="FDA-2026-2044",
                                           hazard_class="CLASS_III",
                                           response_due_at="2026-10-01T00:00:00Z")
    publish_recall_notice(scene["notice"]["id"])
    scene["match_id"] = first_recall_match_id(scene["notice"]["id"])
    disposition_recall_match(scene["match_id"], "REMOVED",
                            note="Unit removed from service per alert")
    scene["department"] = read_department(scene["department"]["id"])
    return scene


def setup_reverse_reachability_scene() -> dict:
    """One child row of every kind, so each filtered list can be checked in reverse."""
    scene = bootstrap_monitor_campus_with_pool()
    scene["vendor"] = create_vendor()
    scene["contract"] = create_service_contract(
        scene["vendor"]["id"], scene["model"]["id"],
        annual_premium_cents=900_000, deductible_cents=30000, covered_event_cap=2,
    )
    scene["pm_task"] = create_pm_task(scene["device"]["id"],
                                      "2026-09-01T00:00:00Z", "2026-09-01T23:59:00Z")
    order = intake_work_order(scene["device"]["id"],
                              problem_summary="Reverse-reachability probe")
    assigned = assign_work_order(order["id"])
    scene["work_order"] = assigned
    scene["loaner"] = create_loaner_assignment(
        order["id"], expected_version=assigned["version"],
        loaner_device_id=scene["pool_device"]["id"],
    )
    scene["finding"] = create_security_finding(scene["device"]["id"], severity="LOW",
                                               advisory_reference="CVE-2026-0001")
    scene["notice"] = create_recall_notice(scene["facility"]["id"], scene["model"]["id"],
                                           source_reference="FDA-2026-6001",
                                           hazard_class="CLASS_III",
                                           response_due_at="2026-11-01T00:00:00Z")
    return scene


def setup_two_departments_one_device() -> dict:
    """Two departments at one campus; the only device belongs to the second."""
    facility = create_facility()
    dept_a = create_department(facility["id"], name="Department A", cost_center_code="CC-A")
    dept_b = create_department(facility["id"], name="Department B", cost_center_code="CC-B")
    model = create_monitor_model()
    device = create_device(facility["id"], dept_b["id"], model["id"], MONITOR_UNIT,
                           serial_number="SN-B-1")
    return {"facility": facility, "department_a": dept_a, "department_b": dept_b,
            "model": model, "device": device}


def setup_two_vendors_one_assigned_order() -> dict:
    """A vendor-mode order assigned to the first of two approved vendors."""
    scene = bootstrap_pump_campus()
    scene["vendor"] = create_vendor()
    scene["rival_vendor"] = create_vendor(name="Rival Service Co", vendor_code="RSC",
                                          hourly_rate_cents=21000, travel_flat_cents=18000)
    order = intake_work_order(scene["device"]["id"], problem_summary="Vendor service call")
    scene["work_order"] = assign_work_order(order["id"], service_mode="VENDOR",
                                            vendor_id=scene["vendor"]["id"], headers=MANAGER)
    return scene


def setup_two_verified_repairs_same_department() -> dict:
    """Two 9,000-cent in-house repairs on one device, both VERIFIED and awaiting close."""
    scene = bootstrap_monitor_campus()
    device_id = scene["device"]["id"]
    set_clock("2026-08-02T09:00:00Z")
    first = intake_work_order(device_id, problem_summary="Repair one")
    second = intake_work_order(device_id, problem_summary="Repair two")
    for order in (first, second):
        assign_work_order(order["id"])
        complete_repair(order["id"], 60, 0)
        verify_work_order(order["id"], "PASS")
    scene["first_order"] = read_work_order(first["id"])
    scene["second_order"] = read_work_order(second["id"])
    return scene


def setup_immediate_consistency_scene() -> dict:
    """A 9,000-cent repair reported at 08:00 and verified, with the clock parked at 12:00."""
    scene = bootstrap_monitor_campus()
    device_id = scene["device"]["id"]
    set_clock("2026-08-02T08:00:00Z")
    order = intake_work_order(device_id, problem_summary="Immediate-consistency probe")
    set_clock("2026-08-02T09:00:00Z")
    assign_work_order(order["id"])
    set_clock("2026-08-02T10:00:00Z")
    complete_repair(order["id"], 60, 0)
    scene["work_order"] = verify_work_order(order["id"], "PASS")
    set_clock("2026-08-02T12:00:00Z")
    return scene
