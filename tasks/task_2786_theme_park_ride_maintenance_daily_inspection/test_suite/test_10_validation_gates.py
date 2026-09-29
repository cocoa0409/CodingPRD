"""Validation gates: the refusals that guard the daily walk and its neighbours.

Each gate is exercised against a scenario that satisfies every check above it in
the §2.6 ladder, so the error the caller hears is unambiguously the gate under
test, and the refused call is shown to have changed nothing.
"""

import pytest

from test_helpers import (
    ADMIN,
    INSPECTOR,
    MANAGER,
    SAFETY_OFFICER,
    TECHNICIAN,
    api_client,
    assert_bulletin,
    assert_bulletin_action,
    assert_component,
    assert_daily_inspection,
    assert_downtime_event,
    assert_error_envelope,
    assert_incident,
    assert_inspection_counters,
    assert_inspection_template,
    assert_instant_equals,
    assert_item_result,
    factories,
    fixtures,
    make_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"


def _read_inspection(inspection_id: str) -> dict:
    """The daily inspection as the walking technician sees it."""
    return validate_success(
        api_client.get_daily_inspection(inspection_id, TECHNICIAN)
    )


def test_the_inspection_setup_path_carries_three_independent_gates():
    """No active template, an empty revision and a duplicate service date each refuse.

    PRD §3.2: "The attraction must have an `active_template_id` that is not null,
    since an attraction with no activated checklist cannot be inspected — that failure
    reports `ERR_NO_ACTIVE_TEMPLATE`. No inspection may already exist for that same
    combination of `attraction_id` and `service_date`, since exactly one pre-opening
    walk exists per attraction per operating date — a repeat reports
    `ERR_DUPLICATE_INSPECTION`."
    PRD §3.1: "and it must carry at least one checklist line, since activating an
    empty revision is refused with `ERR_TEMPLATE_HAS_NO_ITEMS`."

    Design: Corner/validations/template_and_inspection_gates_fire_for_no_active_template_empty_template_and_duplicate_service_date
    """
    attraction = fixtures.create_attraction(
        name="Gate Ride",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="GT-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=600,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    template = fixtures.create_template(attraction["id"], effective_from_date="2026-08-01")
    opening_version = fixtures.read_attraction(attraction["id"])["version"]

    too_early = api_client.create_daily_inspection(
        factories.create_daily_inspection_payload(attraction["id"], "2026-08-01"),
        TECHNICIAN,
    )
    validate_error(too_early, "ERR_NO_ACTIVE_TEMPLATE", 409)
    _rows, meta = validate_paginated(
        api_client.list_daily_inspections(
            TECHNICIAN, params={"attraction_id": attraction["id"]}
        )
    )
    assert meta["total_count"] == 0

    empty = api_client.activate_inspection_template(
        template["id"],
        factories.activate_inspection_template_payload(opening_version),
        ADMIN,
    )
    validate_error(empty, "ERR_TEMPLATE_HAS_NO_ITEMS", 422)
    still_draft = validate_success(
        api_client.get_inspection_template(template["id"], ADMIN)
    )
    assert_inspection_template(still_draft)
    assert still_draft["status"] == "DRAFT"
    unchanged = fixtures.read_attraction(attraction["id"])
    assert unchanged["active_template_id"] is None
    assert unchanged["version"] == opening_version

    fixtures.append_line(
        template["id"],
        1,
        severity_class="ADVISORY",
        description="Walk the track and verify no debris",
    )
    activated = validate_success(
        api_client.activate_inspection_template(
            template["id"],
            factories.activate_inspection_template_payload(opening_version),
            ADMIN,
        )
    )
    assert activated["status"] == "ACTIVE"
    assert activated["item_count"] == 1
    repointed = fixtures.read_attraction(attraction["id"])
    assert repointed["active_template_id"] == template["id"]
    assert repointed["version"] == opening_version + 1

    inspection = validate_success(
        api_client.create_daily_inspection(
            factories.create_daily_inspection_payload(attraction["id"], "2026-08-01"),
            TECHNICIAN,
        ),
        201,
    )
    assert_daily_inspection(inspection)
    assert inspection["status"] == "IN_PROGRESS"
    assert inspection["template_id"] == template["id"]
    assert_inspection_counters(inspection, pending=1, rework_round=0)

    duplicate = api_client.create_daily_inspection(
        factories.create_daily_inspection_payload(attraction["id"], "2026-08-01"),
        TECHNICIAN,
    )
    validate_error(duplicate, "ERR_DUPLICATE_INSPECTION", 409)
    _same_date, same_date_meta = validate_paginated(
        api_client.list_daily_inspections(
            TECHNICIAN,
            params={"attraction_id": attraction["id"], "service_date": "2026-08-01"},
        )
    )
    assert same_date_meta["total_count"] == 1

    next_day = validate_success(
        api_client.create_daily_inspection(
            factories.create_daily_inspection_payload(attraction["id"], "2026-08-02"),
            TECHNICIAN,
        ),
        201,
    )
    assert next_day["service_date"] == "2026-08-02"


def test_submission_refuses_a_pending_line_and_an_essential_fail_refuses_a_missing_note():
    """The submit gate counts pending lines; the record gate demands the written note.

    PRD §3.3: "Submission is refused while any line remains unanswered: a
    `pending_item_count` greater than zero yields `ERR_ITEM_RESULTS_PENDING`."
    PRD §3.2: "A `FAIL` on a line whose `severity_class` is `ESSENTIAL` requires a
    non-empty `note`; omitting it is refused with `ERR_ESSENTIAL_FAIL_NOTE_REQUIRED`."
    PRD §3.2: "Recording a `PENDING` row as `FAIL` increments `essential_fail_count`
    by one when that row's `severity_class` is `ESSENTIAL`, and increments
    `blocking_item_count` by one when it is `SAFETY_CRITICAL`."

    Design: Corner/validations/submit_and_sign_off_refuse_pending_lines_blocking_lines_and_an_unnoted_essential_fail
    """
    attraction = fixtures.create_attraction(
        name="Blocking Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="BL-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=900,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    template = fixtures.create_template(attraction["id"], effective_from_date="2026-08-01")
    fixtures.append_line(
        template["id"],
        1,
        severity_class="ESSENTIAL",
        description="Verify restraint locking on every car",
    )
    fixtures.append_line(
        template["id"],
        2,
        severity_class="ADVISORY",
        description="Confirm queue gates latch",
    )
    fixtures.activate_template(template["id"], attraction["id"])
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01")
    essential_row, advisory_row = fixtures.list_item_results(inspection["id"])

    premature = api_client.submit_daily_inspection(inspection["id"], TECHNICIAN)
    validate_error(premature, "ERR_ITEM_RESULTS_PENDING", 409)
    assert_inspection_counters(
        _read_inspection(inspection["id"]),
        pending=2,
        blocking=0,
        essential_fail=0,
        status="IN_PROGRESS",
    )

    unnoted = api_client.record_inspection_item_result(
        essential_row["id"], factories.record_item_result_payload("FAIL"), TECHNICIAN
    )
    validate_error(unnoted, "ERR_ESSENTIAL_FAIL_NOTE_REQUIRED", 422)
    untouched = validate_success(
        api_client.get_inspection_item_result(essential_row["id"], TECHNICIAN)
    )
    assert_item_result(untouched)
    assert untouched["outcome"] == "PENDING"
    assert untouched["recorded_by_user_id"] is None
    assert_inspection_counters(
        _read_inspection(inspection["id"]),
        pending=2,
        blocking=0,
        essential_fail=0,
    )

    noted = fixtures.record_result(
        essential_row["id"], "FAIL", note="Car 3 restraint sensor intermittent"
    )
    assert noted["outcome"] == "FAIL"
    assert noted["severity_class"] == "ESSENTIAL"
    assert noted["note"] == "Car 3 restraint sensor intermittent"
    assert_inspection_counters(
        _read_inspection(inspection["id"]),
        pending=1,
        blocking=0,
        essential_fail=1,
    )

    fixtures.record_result(advisory_row["id"], "PASS")
    submitted = fixtures.submit_inspection(inspection["id"], "tech-1")
    assert_inspection_counters(
        submitted,
        pending=0,
        blocking=0,
        essential_fail=1,
        status="PENDING_SIGN_OFF",
    )
    assert submitted["recorded_by_user_ids"] == ["tech-1"]

    assert (
        fixtures.read_attraction(attraction["id"])["operational_posture"]
        == "CLOSED_PENDING_INSPECTION"
    )


def test_sign_off_is_refused_while_a_sibling_safety_critical_component_is_overdue():
    """A flawless walk is unsignable until the component inventory is brought current.

    PRD §3.3: "No component of the attraction whose `criticality` is
    `SAFETY_CRITICAL` may derive an `ndt_status` of `OVERDUE`. One that does yields
    `ERR_NDT_OVERDUE_SAFETY_CRITICAL`."
    PRD §3.1: "The record resets both interval baselines at once: `last_ndt_method`
    becomes the supplied `ndt_method`, `last_ndt_at` becomes the current logical clock
    instant, and `last_ndt_cycles` becomes the attraction's `cumulative_cycles` as
    observed now, so `ndt_status` necessarily returns to `CURRENT`."

    Design: Corner/validations/ndt_overdue_on_a_safety_critical_component_blocks_sign_off_until_a_pass_is_recorded
    """
    attraction = fixtures.create_attraction(
        name="NDT Gate Ride",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="ND-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Restraint Cylinder",
        component_type="RESTRAINT_ACTUATOR",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=100,
        ndt_interval_days=3650,
    )
    fixtures.log_cycles(attraction["id"], 120, "2026-08-01")
    template = fixtures.create_template(attraction["id"], effective_from_date="2026-08-01")
    fixtures.append_line(
        template["id"],
        1,
        severity_class="ADVISORY",
        description="Confirm station gate interlock",
    )
    fixtures.activate_template(template["id"], attraction["id"])
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01")
    result_row = fixtures.list_item_results(inspection["id"])[0]
    fixtures.record_result(result_row["id"], "PASS")
    fixtures.submit_inspection(inspection["id"], "tech-1")

    overdue = fixtures.read_component(component["id"])
    assert_component(overdue)
    assert overdue["ndt_status"] == "OVERDUE"
    assert fixtures.read_attraction(attraction["id"])["cumulative_cycles"] == 120
    assert fixtures.read_attraction(attraction["id"])["operational_posture"] == "DOWN"
    assert_inspection_counters(
        _read_inspection(inspection["id"]), blocking=0, status="PENDING_SIGN_OFF"
    )

    refused = api_client.sign_off_daily_inspection(inspection["id"], INSPECTOR)
    validate_error(refused, "ERR_NDT_OVERDUE_SAFETY_CRITICAL", 409)
    assert _read_inspection(inspection["id"])["status"] == "PENDING_SIGN_OFF"

    tested = fixtures.record_ndt(component["id"], "ULTRASONIC", "PASS")
    assert tested["last_ndt_cycles"] == 120
    assert tested["last_ndt_method"] == "ULTRASONIC"
    assert tested["ndt_status"] == "CURRENT"
    assert tested["condition_flag"] == "OK"
    assert_instant_equals(tested["last_ndt_at"], CLOCK_START, "last_ndt_at")
    assert (
        fixtures.read_attraction(attraction["id"])["operational_posture"]
        == "CLOSED_PENDING_INSPECTION"
    )

    signed = fixtures.sign_off_inspection(inspection["id"], "insp-1")
    assert signed["status"] == "SIGNED_OFF"
    assert signed["signed_off_by_user_id"] == "insp-1"
    opened = fixtures.read_attraction(attraction["id"])
    assert opened["last_signed_off_service_date"] == "2026-08-01"
    assert opened["operational_posture"] == "OPEN"

    readiness = validate_success(
        api_client.get_dispatch_readiness(attraction["id"], MANAGER)
    )
    assert readiness["operational_posture"] == "OPEN"
    assert readiness["certified_operator_count"] == 0
    assert readiness["dispatch_readiness_index"] == pytest.approx(0.00, abs=0.01)


def test_the_live_event_rule_and_the_midnight_span_rule_are_both_enforced():
    """One live event per attraction, and no resolution across the pinned service date.

    PRD §2.6: "`ERR_DOWNTIME_ALREADY_OPEN` (409) — an attraction may hold at most one
    downtime event whose `status` is `OPEN`, `DIAGNOSED`, `AWAITING_PARTS` or
    `RESOLVED`."
    PRD §3.4: "The supplied `ended_at` must be strictly later than `started_at`, and
    its UTC calendar date must equal the event's pinned `service_date` — a repair that
    spans midnight must be recorded as two events, and attempting to resolve across
    the date boundary is refused with `ERR_DOWNTIME_SPANS_SERVICE_DATES`."

    Design: Corner/validations/downtime_uniqueness_and_service_date_span_guards_are_both_enforced
    """
    fixtures.set_clock("2026-08-11T02:00:00.000Z")
    attraction = fixtures.create_attraction(
        name="Span Guard Ride",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="SG-1",
        ride_class="WATER",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    event = fixtures.open_downtime(
        attraction["id"],
        started_at="2026-08-10T22:00:00.000Z",
        cause_category="ELECTRICAL",
    )
    fixtures.diagnose_downtime(event["id"], root_cause_code="VFD-TRIP")

    second = api_client.create_downtime_event(
        factories.create_downtime_event_payload(
            attraction["id"],
            started_at="2026-08-11T00:30:00.000Z",
            cause_category="MECHANICAL",
        ),
        TECHNICIAN,
    )
    validate_error(second, "ERR_DOWNTIME_ALREADY_OPEN", 409)
    _rows, meta = validate_paginated(
        api_client.list_downtime_events(
            TECHNICIAN, params={"attraction_id": attraction["id"]}
        )
    )
    assert meta["total_count"] == 1

    spanning = api_client.resolve_downtime_event(
        event["id"], factories.resolve_downtime_payload("2026-08-11T01:00:00.000Z"), TECHNICIAN
    )
    validate_error(spanning, "ERR_DOWNTIME_SPANS_SERVICE_DATES", 422)
    still_diagnosed = validate_success(
        api_client.get_downtime_event(event["id"], TECHNICIAN)
    )
    assert still_diagnosed["status"] == "DIAGNOSED"
    assert still_diagnosed["ended_at"] is None
    assert still_diagnosed["duration_minutes"] is None

    resolved = fixtures.resolve_downtime(event["id"], "2026-08-10T23:00:00.000Z")
    assert_downtime_event(resolved)
    assert resolved["status"] == "RESOLVED"
    assert resolved["service_date"] == "2026-08-10"
    assert resolved["duration_minutes"] == 60
    assert resolved["peak_minutes"] == 0
    assert resolved["off_peak_minutes"] == 60

    closed = fixtures.close_downtime(event["id"])
    assert closed["status"] == "CLOSED"
    assert fixtures.read_attraction(attraction["id"])["ytd_downtime_minutes"] == 60

    fresh = validate_success(
        api_client.create_downtime_event(
            factories.create_downtime_event_payload(
                attraction["id"],
                started_at="2026-08-11T00:30:00.000Z",
                cause_category="MECHANICAL",
            ),
            TECHNICIAN,
        ),
        201,
    )
    assert fresh["status"] == "OPEN"
    assert fresh["service_date"] == "2026-08-11"


def test_the_deferral_rule_reads_through_to_the_parent_bulletins_severity():
    """Two actions on one unit differ only by parent severity, and only one defers.

    PRD §2.6: "`ERR_RECALL_NOT_DEFERRABLE` (409) — a fleet action belonging to a
    bulletin whose `severity` is `RECALL` may not be deferred."
    PRD §3.6: "An action that is `PENDING` moves `PENDING` → `DEFERRED` when the
    manager supplies a `deferral_reason` and a `deferred_until_date`; that date must be
    no later than the parent bulletin's `compliance_deadline_date`."

    Design: Corner/validations/deferral_is_refused_for_a_recall_action_and_accepted_for_an_advisory_one
    """
    attraction = fixtures.create_attraction(
        name="Deferral Ride",
        park_area="KIDS_COVE",
        manufacturer="Chance",
        model_code="DF-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=500,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    recall = fixtures.acknowledged_bulletin_with_actions(
        bulletin_ref="BR-REC-1",
        manufacturer="Chance",
        model_code="DF-1",
        severity="RECALL",
        attractions=[attraction],
        issued_date="2026-07-15",
        compliance_deadline_date="2026-09-15",
    )
    advisory = fixtures.acknowledged_bulletin_with_actions(
        bulletin_ref="BR-ADV-1",
        manufacturer="Chance",
        model_code="DF-1",
        severity="ADVISORY",
        attractions=[attraction],
        issued_date="2026-07-15",
        compliance_deadline_date="2026-12-15",
    )
    recall_action = recall["actions"][0]
    advisory_action = advisory["actions"][0]
    assert_bulletin_action(recall_action)

    refused = api_client.defer_bulletin_action(
        recall_action["id"],
        factories.defer_bulletin_action_payload("Awaiting factory kit", "2026-09-01"),
        MANAGER,
    )
    validate_error(refused, "ERR_RECALL_NOT_DEFERRABLE", 409)
    unchanged = validate_success(
        api_client.get_bulletin_action(recall_action["id"], MANAGER)
    )
    assert unchanged["status"] == "PENDING"
    assert unchanged["deferred_until_date"] is None

    deferred = validate_success(
        api_client.defer_bulletin_action(
            advisory_action["id"],
            factories.defer_bulletin_action_payload(
                "Bundled with the autumn shutdown", "2026-11-01"
            ),
            MANAGER,
        )
    )
    assert deferred["status"] == "DEFERRED"
    assert deferred["deferred_until_date"] == "2026-11-01"
    assert deferred["deferral_reason"] == "Bundled with the autumn shutdown"

    parent = validate_success(api_client.get_bulletin(recall["bulletin"]["id"], MANAGER))
    assert_bulletin(parent)
    assert parent["status"] == "ACKNOWLEDGED"
    assert parent["action_total_count"] == 1
    assert parent["action_verified_count"] == 0

    assert recall_action["attraction_id"] == attraction["id"]
    assert advisory_action["attraction_id"] == attraction["id"]
    assert (
        fixtures.read_attraction(attraction["id"])["parts_budget_committed_cents"] == 0
    )


def test_a_minor_incident_cannot_be_filed_with_the_regulator_and_clears_internally():
    """The notification branch is reserved for reportable injuries.

    PRD §3.8: "This branch is only meaningful for a genuine reportable injury:
    attempting it on an incident whose `injury_severity` is `NONE` or `MINOR` is
    refused with `ERR_NOTIFICATION_NOT_REQUIRED`."
    PRD §3.8: "On this branch `regulator_case_ref` and `notified_at` both stay null and
    `notified_late` stays false; no regulator bookkeeping is created at all. Clearance
    from this branch requires no clearance reference."

    Design: Corner/validations/regulator_notification_is_refused_for_a_minor_incident_and_the_internal_branch_clears_without_a_reference
    """
    attraction = fixtures.create_attraction(
        name="Minor Incident Ride",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="MI-1",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=300,
        min_operators_required=1,
        parts_budget_cents=1000000,
    )
    incident = fixtures.create_incident(
        attraction["id"],
        occurred_at="2026-08-01T10:00:00.000Z",
        injury_severity="MINOR",
        guest_count_affected=1,
        narrative="Guest scraped a knee on the exit ramp.",
    )
    assert_incident(incident)
    assert incident["status"] == "REPORTED"
    assert incident["regulator_notification_due_at"] is None
    assert fixtures.read_attraction(attraction["id"])["regulatory_hold"] is False

    held = validate_success(api_client.hold_ride(incident["id"], SAFETY_OFFICER))
    assert held["status"] == "RIDE_HELD"
    assert held["suspended_certification_count"] == 0
    on_hold = fixtures.read_attraction(attraction["id"])
    assert on_hold["regulatory_hold"] is True
    assert on_hold["operational_posture"] == "HOLD"

    investigating = validate_success(
        api_client.investigate_incident(incident["id"], SAFETY_OFFICER)
    )
    assert investigating["status"] == "UNDER_INVESTIGATION"

    not_required = api_client.notify_regulator(
        incident["id"],
        factories.notify_regulator_payload("REG-MINOR-1"),
        SAFETY_OFFICER,
    )
    validate_error(not_required, "ERR_NOTIFICATION_NOT_REQUIRED", 422)
    untouched = validate_success(api_client.get_incident(incident["id"], SAFETY_OFFICER))
    assert untouched["status"] == "UNDER_INVESTIGATION"
    assert untouched["regulator_case_ref"] is None
    assert untouched["notified_at"] is None

    internal = validate_success(
        api_client.close_internal_review(incident["id"], SAFETY_OFFICER)
    )
    assert internal["status"] == "INTERNAL_REVIEW_CLOSED"
    assert internal["notified_late"] is False

    cleared = validate_success(api_client.clear_incident(incident["id"], SAFETY_OFFICER))
    assert cleared["status"] == "CLEARED_TO_OPERATE"
    assert_instant_equals(cleared["cleared_at"], CLOCK_START, "cleared_at")
    released = fixtures.read_attraction(attraction["id"])
    assert released["regulatory_hold"] is False
    assert released["operational_posture"] == "CLOSED_PENDING_INSPECTION"


def test_authentication_is_decided_before_the_role_test_and_the_path_lookup():
    """A blank or unrecognised identity is 401, whatever else is wrong with the request.

    PRD §2.6: "1. **Authentication.** `X-User-Role` and `X-User-ID` are both present
    and non-blank — otherwise `ERR_UNAUTHENTICATED` (401)."
    PRD §2.6: "Checks are evaluated strictly in the ascending priority order below,
    and the first violated check supplies the response."

    Design: Corner/validations/blank_or_unrecognised_role_headers_return_unauthenticated_before_any_lookup
    """
    attraction = fixtures.create_attraction(
        name="Auth Probe Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="AU-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )

    blank_role = api_client.get_attraction(
        attraction["id"], make_headers("admin-1", "")
    )
    validate_error(blank_role, "ERR_UNAUTHENTICATED", 401)
    assert_error_envelope(blank_role)

    blank_badge = api_client.get_attraction(
        attraction["id"], make_headers("", "ParkOpsAdmin")
    )
    validate_error(blank_badge, "ERR_UNAUTHENTICATED", 401)
    assert_error_envelope(blank_badge)

    unknown_role = api_client.get_attraction(
        attraction["id"], make_headers("admin-1", "SuperAdmin")
    )
    validate_error(unknown_role, "ERR_UNAUTHENTICATED", 401)
    assert_error_envelope(unknown_role)

    blank_and_missing = api_client.get_attraction(UNKNOWN_ID, make_headers("", ""))
    validate_error(blank_and_missing, "ERR_UNAUTHENTICATED", 401)
    assert_error_envelope(blank_and_missing)


def test_diagnosis_refuses_a_component_installed_on_another_attraction():
    """Both ids resolve, so the mismatch check is the deciding gate.

    PRD §2.6: "`ERR_COMPONENT_ATTRACTION_MISMATCH` (422) — a supplied component
    identifier names a component installed on a different attraction than the one the
    request targets. This guards three operations: creating an overhaul work order,
    diagnosing a downtime event, and appending a checklist line to a template."
    PRD §3.4: "When a `failed_component_id` is supplied, that component's
    `condition_flag` becomes `FAILED` — a stronger statement than the `SUSPECT` flag
    an inspection failure raises."

    Design: Corner/validations/failed_component_from_another_attraction_is_refused_while_the_installed_component_is_accepted
    """
    first = fixtures.create_attraction(
        name="Mismatch Ride A",
        park_area="SKYLINE",
        manufacturer="B&M",
        model_code="MM-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    second = fixtures.create_attraction(
        name="Mismatch Ride B",
        park_area="SKYLINE",
        manufacturer="B&M",
        model_code="MM-2",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    own_component = fixtures.create_component(
        first["id"],
        name="A Lift Chain",
        component_type="LIFT_CHAIN",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )
    foreign_component = fixtures.create_component(
        second["id"],
        name="B Lift Chain",
        component_type="LIFT_CHAIN",
        criticality="ESSENTIAL",
        ndt_interval_cycles=500000,
        ndt_interval_days=3650,
    )
    event = fixtures.open_downtime(first["id"], started_at="2026-08-01T09:00:00.000Z")

    mismatched = api_client.diagnose_downtime_event(
        event["id"],
        factories.diagnose_downtime_payload(
            root_cause_code="CHAIN-STRETCH",
            failed_component_id=foreign_component["id"],
        ),
        TECHNICIAN,
    )
    validate_error(mismatched, "ERR_COMPONENT_ATTRACTION_MISMATCH", 422)
    still_open = validate_success(api_client.get_downtime_event(event["id"], TECHNICIAN))
    assert still_open["status"] == "OPEN"
    assert still_open["failed_component_id"] is None
    assert fixtures.read_component(foreign_component["id"])["condition_flag"] == "OK"

    diagnosed = fixtures.diagnose_downtime(
        event["id"],
        root_cause_code="CHAIN-STRETCH",
        failed_component_id=own_component["id"],
    )
    assert diagnosed["status"] == "DIAGNOSED"
    assert diagnosed["root_cause_code"] == "CHAIN-STRETCH"
    assert diagnosed["failed_component_id"] == own_component["id"]

    assert fixtures.read_component(own_component["id"])["condition_flag"] == "FAILED"
    assert fixtures.read_component(foreign_component["id"])["condition_flag"] == "OK"
    assert fixtures.read_attraction(first["id"])["operational_posture"] == "DOWN"
    assert (
        fixtures.read_attraction(second["id"])["operational_posture"]
        == "CLOSED_PENDING_INSPECTION"
    )
