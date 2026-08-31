"""The preventive-maintenance calendar and the campus audit epoch."""

from test_helpers import (
    ApiErrorId,
    assert_pm_task,
    assert_timestamp_equals,
    bootstrap_monitor_campus,
    bootstrap_pump_campus,
    create_pm_task,
    complete_pm_task,
    read_device,
    read_facility,
    read_pm_task,
    run_pm_audit,
    setup_pm_audit_with_empty_window,
    setup_pm_compliance_divergence,
    setup_pm_task_deferred_twice,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_defer_rewrites_the_window_but_preserves_original_due_at(api, ce_manager_headers):
    """PRD §3.3: "The task is created with `status` at `SCHEDULED` and `deferral_count` at 0,
    and with **both** `due_at` and `original_due_at` set to `window_end`."
    PRD §3.3: "On success, `window_start`, `window_end` and `due_at` are all rewritten to the
    new window, `original_due_at` is left exactly as it was, `deferral_count` increases by 1,
    and the task's `status` becomes `DEFERRED`."

    Design: Corner/entities/pm_task_original_due_at_survives_defer
    """
    scene = bootstrap_monitor_campus()
    task = create_pm_task(scene["device"]["id"],
                          "2026-08-03T00:00:00Z", "2026-08-03T23:59:00Z")
    assert_timestamp_equals(task["original_due_at"], "2026-08-03T23:59:00Z", "original_due_at")

    data = validate_success(
        api.defer_pm_task(task["id"],
                          {"new_window_start": "2026-08-20T00:00:00Z",
                           "new_window_end": "2026-08-20T23:59:00Z",
                           "reason": "Clinical schedule conflict"},
                          ce_manager_headers),
        200,
    )
    assert_pm_task(data)
    assert data["status"] == "DEFERRED"
    assert data["deferral_count"] == 1
    assert_timestamp_equals(data["due_at"], "2026-08-20T23:59:00Z", "due_at")
    assert_timestamp_equals(data["window_start"], "2026-08-20T00:00:00Z", "window_start")
    assert_timestamp_equals(data["original_due_at"], "2026-08-03T23:59:00Z", "original_due_at")


def test_third_deferral_is_rejected_and_leaves_the_task_untouched(api, ce_manager_headers):
    """PRD §3.3: "The transition `DEFERRED` → `DEFERRED` is a legitimate self-loop for the
    second deferral; a third attempt, made when `deferral_count` already stands at 2, is
    rejected with `ERR_DEFERRAL_LIMIT_EXCEEDED`."

    Design: Corner/validations/pm_third_defer_returns_deferral_limit_exceeded
    """
    scene = setup_pm_task_deferred_twice()
    task_id = scene["pm_task"]["id"]

    response = api.defer_pm_task(task_id,
                                 {"new_window_start": "2026-10-01T00:00:00Z",
                                  "new_window_end": "2026-10-01T23:59:00Z",
                                  "reason": "Third attempt"},
                                 ce_manager_headers)
    validate_error(response, ApiErrorId.ERR_DEFERRAL_LIMIT_EXCEEDED.value, 422)

    after = read_pm_task(task_id)
    assert after["deferral_count"] == 2
    assert after["status"] == "DEFERRED"
    assert_timestamp_equals(after["due_at"], "2026-09-10T23:59:00Z", "due_at")
    assert_timestamp_equals(after["original_due_at"], "2026-08-10T23:59:00Z", "original_due_at")


def test_completion_before_the_window_opens_is_rejected(api, biomed_tech_headers):
    """PRD §3.3: "Three further guards apply, in the order of §2.11: the device must not be
    `RETIRED` (`ERR_DEVICE_RETIRED`), the device's `security_state` must not be `QUARANTINED`
    (`ERR_DEVICE_QUARANTINED`), and the logical clock must lie at or after `window_start` and
    at or before `window_end` of the task's **current** window — a completion attempt outside
    that closed interval is rejected with `ERR_PM_OUTSIDE_WINDOW`."

    Design: Corner/validations/pm_complete_before_window_opens_returns_pm_outside_window
    """
    scene = bootstrap_monitor_campus()
    task = create_pm_task(scene["device"]["id"],
                          "2026-08-02T00:00:00Z", "2026-08-02T23:59:00Z")

    response = api.complete_pm_task(task["id"], {"result": "PASS", "labor_minutes": 30},
                                    biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_PM_OUTSIDE_WINDOW.value, 422)

    after = read_pm_task(task["id"])
    assert after["status"] == "SCHEDULED"
    assert after["completed_at"] is None
    # The device is neither quarantined nor retired, so no earlier guard can mask the rule.
    assert read_device(scene["device"]["id"])["security_state"] == "UNASSESSED"


def test_completing_an_already_completed_task_is_rejected(api, biomed_tech_headers):
    """PRD §3.3: "Completion is accepted only from `SCHEDULED` or `DEFERRED`; a task that has
    already reached `COMPLETED` or `MISSED` is rejected with `ERR_INVALID_PM_TASK_STATE`."

    Design: Corner/state_machines/pm_task_complete_after_completed_returns_invalid_pm_task_state
    """
    scene = bootstrap_monitor_campus()
    task = create_pm_task(scene["device"]["id"],
                          "2026-08-01T00:00:00Z", "2026-08-01T23:59:00Z")
    complete_pm_task(task["id"], "PASS", 45)

    response = api.complete_pm_task(task["id"], {"result": "PASS", "labor_minutes": 10},
                                    biomed_tech_headers)
    validate_error(response, ApiErrorId.ERR_INVALID_PM_TASK_STATE.value, 409)

    after = read_pm_task(task["id"])
    assert after["status"] == "COMPLETED"
    assert after["labor_minutes"] == 45, "The rejected second call must not overwrite labour"


def test_failed_pm_opens_a_work_order_reachable_only_through_the_listing(api, ce_manager_headers,
                                                                        biomed_tech_headers):
    """PRD §3.3: "A `FAIL` completion takes the device to `DOWN` and automatically opens a
    follow-on corrective work order in `INTAKE` with `reported_severity` set to
    `CLINICAL_IMPACT` and `problem_summary` set to the text "PM failure on " followed by the
    unit's `serial_number`; that cascade-created order is returned by no create call and is
    discoverable only through the filtered work-order listing."

    Design: Corner/entities/auto_created_work_order_reachable_via_device_filtered_list
    """
    scene = bootstrap_monitor_campus()
    device_id = scene["device"]["id"]
    task = create_pm_task(device_id, "2026-08-01T00:00:00Z", "2026-08-01T23:59:00Z")

    data = validate_success(
        api.complete_pm_task(task["id"], {"result": "FAIL", "labor_minutes": 55},
                             biomed_tech_headers),
        200,
    )
    assert data["status"] == "COMPLETED"
    assert data["result"] == "FAIL"

    orders, meta = validate_paginated(
        api.list_work_orders(ce_manager_headers, params={"device_id": device_id})
    )
    assert len(orders) == 1, f"Expected exactly 1 cascade-created order, got {len(orders)}"
    assert meta["total_count"] == 1
    assert orders[0]["status"] == "INTAKE"
    assert orders[0]["reported_severity"] == "CLINICAL_IMPACT"
    assert orders[0]["device_id"] == device_id
    assert read_device(device_id)["operational_state"] == "DOWN"


def test_pass_with_defect_ages_the_unit_without_downing_it(api, biomed_tech_headers,
                                                           ce_manager_headers):
    """PRD §3.3: "A `PASS_WITH_DEFECT` completion leaves the device in service but ages it:
    `condition_score` becomes the smaller of 5 and its current value plus 1 — so a unit
    already at 5 stays at 5 — and the capital-replacement score of §3.9 is recomputed."
    PRD §3.3: "It then derives `on_time`, which is `true` when `completed_at` is at or before
    `original_due_at` — against the *original* deadline, never the deferred one."

    Design: Corner/calculations/pm_pass_with_defect_increments_condition_score
    """
    scene = bootstrap_pump_campus()
    device_id = scene["device"]["id"]
    assert scene["device"]["condition_score"] == 3
    assert float(scene["device"]["replacement_priority_score"]) == 60.63
    task = create_pm_task(device_id, "2026-08-01T00:00:00Z", "2026-08-01T23:59:00Z")

    data = validate_success(
        api.complete_pm_task(task["id"],
                             {"result": "PASS_WITH_DEFECT", "labor_minutes": 50},
                             biomed_tech_headers),
        200,
    )
    assert data["status"] == "COMPLETED"
    assert data["result"] == "PASS_WITH_DEFECT"
    assert data["on_time"] is True

    device = read_device(device_id)
    assert device["condition_score"] == 4
    assert device["operational_state"] == "IN_SERVICE"
    assert float(device["replacement_priority_score"]) == 68.13

    orders, _ = validate_paginated(
        api.list_work_orders(ce_manager_headers, params={"device_id": device_id})
    )
    assert orders == [], "PASS_WITH_DEFECT must not open a corrective work order"


def test_audit_reports_diverging_strict_and_operational_rates(api, ce_manager_headers):
    """PRD §3.3: "The **strict** denominator counts every task whose `status` is `COMPLETED`,
    `MISSED` or `DEFERRED` — every deferral counts against the campus, which is what a
    regulator asks for."
    PRD §3.3: "The **operational** denominator counts every task whose `status` is `COMPLETED`
    or `MISSED`, plus those tasks that are `DEFERRED` and whose `deferral_count` is 2 or more
    — a first, approved deferral is forgiven, which is what the internal operations dashboard
    shows."

    Design: Difficulty/dual_variant_calc/pm_compliance_strict_vs_operational_denominator_diverges
    """
    scene = setup_pm_compliance_divergence()

    data = validate_success(api.run_pm_audit(scene["facility"]["id"], ce_manager_headers), 200)

    assert float(data["pm_compliance_pct_strict"]) == 33.33, (
        f"One on-time completion over a strict denominator of 3 is 33.33, "
        f"got {data['pm_compliance_pct_strict']}"
    )
    assert float(data["pm_compliance_pct_operational"]) == 50.00, (
        f"One on-time completion over an operational denominator of 2 is 50.00, "
        f"got {data['pm_compliance_pct_operational']}"
    )
    assert float(data["pm_compliance_pct_strict"]) != float(data["pm_compliance_pct_operational"])


def test_audit_sweeps_overdue_tasks_and_spares_the_deferred_one(api, ce_manager_headers):
    """PRD §3.3: "Every PM task whose device belongs to this campus, whose `status` is
    `SCHEDULED` or `DEFERRED`, and whose `due_at` lies strictly before the current logical
    clock is moved to `MISSED`."
    PRD §3.3: "It then derives `on_time`, which is `true` when `completed_at` is at or before
    `original_due_at` — against the *original* deadline, never the deferred one."

    Design: Difficulty/dual_variant_calc/pm_compliance_strict_vs_operational_denominator_diverges
    """
    scene = setup_pm_compliance_divergence()
    run_pm_audit(scene["facility"]["id"])

    assert read_pm_task(scene["task_b"]["id"])["status"] == "MISSED"

    task_c = read_pm_task(scene["task_c"]["id"])
    assert task_c["status"] == "DEFERRED", "A task deferred past the clock survives the sweep"
    assert task_c["deferral_count"] == 1

    task_a = read_pm_task(scene["task_a"]["id"])
    assert task_a["status"] == "COMPLETED"
    assert task_a["on_time"] is True


def test_audit_escalates_posture_and_advances_the_epoch_counter(api, ce_manager_headers):
    """PRD §3.3: "When the strict denominator is greater than zero, and
    `pm_compliance_pct_strict` is strictly below the campus `pm_compliance_target_pct`, and
    `ce_posture` is currently `NORMAL`, the posture escalates to `HEIGHTENED`."
    PRD §3.3: "The fourth step increments `pm_audit_index` by 1, giving every epoch a
    monotonic sequence number."

    Design: Difficulty/dual_variant_calc/pm_compliance_strict_vs_operational_denominator_diverges
    """
    scene = setup_pm_compliance_divergence()
    assert scene["facility"]["ce_posture"] == "NORMAL"

    run_pm_audit(scene["facility"]["id"])

    facility = read_facility(scene["facility"]["id"])
    assert facility["ce_posture"] == "HEIGHTENED", (
        "A strict rate of 33.33 against a 90.00 target must escalate a NORMAL posture"
    )
    assert facility["pm_audit_index"] == 1


def test_empty_denominators_report_asymmetric_compliance_constants(api, ce_manager_headers):
    """PRD §3.3: "`pm_compliance_pct_strict` is 0.00 when the strict denominator is zero, and
    otherwise 100 multiplied by the numerator divided by the strict denominator, rounded half
    up to two decimal places."
    PRD §3.3: "`pm_compliance_pct_operational` is 100.00 when the operational denominator is
    zero, and otherwise 100 multiplied by the numerator divided by the operational
    denominator, rounded half up to two decimal places."

    Design: Difficulty/boundary_precision_check/pm_audit_empty_denominator_strict_zero_operational_hundred
    """
    scene = setup_pm_audit_with_empty_window()

    data = validate_success(api.run_pm_audit(scene["facility"]["id"], ce_manager_headers), 200)

    assert float(data["pm_compliance_pct_strict"]) == 0.00
    assert float(data["pm_compliance_pct_operational"]) == 100.00
    assert data["pm_audit_index"] == 1


def test_empty_strict_denominator_suppresses_posture_escalation(api, ce_manager_headers):
    """PRD §3.3: "A campus with an empty strict denominator never escalates on this path,
    however low the reported figure looks."
    PRD §3.3: "The measured window is every PM task whose device belongs to this campus and
    whose `original_due_at` is at or before the current clock — the original deadline, so
    deferring a task cannot remove it from the population that judges the campus."

    Design: Difficulty/boundary_precision_check/pm_audit_empty_denominator_strict_zero_operational_hundred
    """
    scene = setup_pm_audit_with_empty_window()
    run_pm_audit(scene["facility"]["id"])

    facility = read_facility(scene["facility"]["id"])
    assert facility["ce_posture"] == "NORMAL", (
        "A 0.00 strict rate over an empty denominator must not escalate the posture"
    )
    assert read_pm_task(scene["pm_task"]["id"])["status"] == "SCHEDULED", (
        "A task whose window has not opened is not swept"
    )
