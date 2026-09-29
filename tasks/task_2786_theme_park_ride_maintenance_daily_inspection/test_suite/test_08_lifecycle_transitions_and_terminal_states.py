"""Lifecycle machines: opening states, declared edges, cycles and terminal lockdown.

Each entity in this service owns its own state machine and its own state error, so a
trigger fired from a state that declares no such edge must be refused by the machine
that owns it and must leave the target row exactly as it found it.
"""

import pytest

from test_helpers import (
    ADMIN,
    INSPECTOR,
    MANAGER,
    OPERATOR,
    SAFETY_OFFICER,
    TECHNICIAN,
    api_client,
    assert_bulletin,
    assert_bulletin_action,
    assert_bulletin_risk_shape,
    assert_component,
    assert_downtime_event,
    assert_incident,
    assert_inspection_template,
    assert_instant_equals,
    assert_inspection_counters,
    assert_operator_certification,
    assert_part_requisition,
    assert_work_order,
    factories,
    fixtures,
    make_maintenance_manager_headers,
    make_maintenance_technician_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CLOCK_START = "2026-08-01T00:00:00.000Z"


def _initial_state_park():
    """One attraction, one essential component and one two-slot bay."""
    attraction = fixtures.create_attraction(
        name="Initial State Ride",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="IS-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=1000,
        min_operators_required=2,
        parts_budget_cents=9000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Lift Chain",
        component_type="LIFT_CHAIN",
        criticality="ESSENTIAL",
        ndt_interval_cycles=800000,
        ndt_interval_days=3650,
    )
    shop_bay = fixtures.create_shop_bay("Bay Init", 2)
    return {"attraction": attraction, "component": component, "shop_bay": shop_bay}


def test_every_machine_reports_its_declared_initial_state():
    """Six freshly created rows open at DRAFT, OPEN, REQUESTED, ISSUED, REPORTED and SCHEDULED.

    PRD §3.1: "A new revision opens with `status` `DRAFT`, an `item_count` of 0 and a
    null `activated_at`."
    PRD §3.4: "A newly opened event starts at `status` `OPEN` with `auto_opened` false,
    and the server pins its `service_date` to the UTC calendar date of `started_at` —
    that pinned date, not the event's creation timestamp, is the bucketing key every
    capacity-impact window uses."
    PRD §3.4: "The four minute-and-capacity fields — `duration_minutes`, `peak_minutes`,
    `off_peak_minutes` and `settled_guest_slots_lost` — stay null until the event is
    resolved, along with `ended_at`, `root_cause_code`, `failed_component_id` and
    `void_reason`."
    PRD §3.5: "Creation computes `total_cost_cents` as the `quantity` multiplied by the
    `unit_cost_cents`, in whole cents, and leaves the requisition at `status`
    `REQUESTED` with `expected_availability_date` and `cancel_reason` both null."
    PRD §3.6: "Publication leaves the bulletin at `status` `ISSUED` with
    `action_total_count` and `action_verified_count` both 0 and `acknowledged_at` and
    `acknowledged_by_user_id` both null."
    PRD §3.8: "An incident whose `injury_severity` is `NONE` or `MINOR` opens at
    `status` `REPORTED`, its `regulator_notification_due_at` stays null, and no cascade
    runs at all — the ride keeps operating."
    PRD §3.9: "Booking succeeds at `status` `SCHEDULED`, increments the bay's
    `booked_order_count` by one, and increments the bay's `version` by one — which is
    precisely why a second planner working from a stale read of the same bay will be
    turned away."
    PRD §2.8: "`DOWN` — if any of the following holds: the attraction has a downtime
    event whose `status` is `OPEN`, `DIAGNOSED`, `AWAITING_PARTS` or `RESOLVED`; or any
    component of the attraction whose `criticality` is `SAFETY_CRITICAL` derives an
    `ndt_status` of `OVERDUE`; or the attraction's daily inspection for the current
    service date has a `status` of `BLOCKED`."

    Design: Corner/state_machines/every_machine_starts_in_its_declared_initial_state
    """
    park = _initial_state_park()
    attraction_id = park["attraction"]["id"]

    template = validate_success(
        api_client.create_inspection_template(
            factories.create_inspection_template_payload(attraction_id, "2026-08-01"),
            ADMIN,
        ),
        201,
    )
    assert_inspection_template(template)
    assert template["status"] == "DRAFT"
    assert template["revision"] == 1
    assert template["item_count"] == 0
    assert template["activated_at"] is None

    event = validate_success(
        api_client.create_downtime_event(
            factories.create_downtime_event_payload(
                attraction_id, "2026-08-01T09:00:00.000Z", "ELECTRICAL"
            ),
            TECHNICIAN,
        ),
        201,
    )
    assert_downtime_event(event)
    assert event["status"] == "OPEN"
    assert event["service_date"] == "2026-08-01"
    assert event["auto_opened"] is False
    assert event["ended_at"] is None
    assert event["duration_minutes"] is None
    assert event["peak_minutes"] is None
    assert event["off_peak_minutes"] is None
    assert event["settled_guest_slots_lost"] is None
    assert event["root_cause_code"] is None
    assert event["failed_component_id"] is None
    assert event["void_reason"] is None

    requisition = validate_success(
        api_client.create_part_requisition(
            factories.create_part_requisition_payload(
                attraction_id,
                part_number="PN-INIT",
                quantity=1,
                unit_cost_cents=25000,
                needed_by_date="2026-08-15",
            ),
            TECHNICIAN,
        ),
        201,
    )
    assert_part_requisition(requisition)
    assert requisition["status"] == "REQUESTED"
    assert requisition["total_cost_cents"] == 25000
    assert requisition["expected_availability_date"] is None
    assert requisition["cancel_reason"] is None

    bulletin = validate_success(
        api_client.create_bulletin(
            factories.create_bulletin_payload(
                "BR-INIT-1",
                manufacturer="Intamin",
                model_code="IS-1",
                severity="ADVISORY",
                issued_date="2026-07-15",
                compliance_deadline_date="2026-11-30",
            ),
            ADMIN,
        ),
        201,
    )
    assert_bulletin(bulletin)
    assert bulletin["status"] == "ISSUED"
    assert bulletin["action_total_count"] == 0
    assert bulletin["action_verified_count"] == 0
    assert bulletin["acknowledged_at"] is None
    assert bulletin["acknowledged_by_user_id"] is None

    incident = validate_success(
        api_client.create_incident(
            factories.create_incident_payload(
                attraction_id,
                occurred_at="2026-08-01T10:00:00.000Z",
                injury_severity="MINOR",
                guest_count_affected=1,
                narrative="Guest reported a scraped knee at the exit ramp.",
            ),
            SAFETY_OFFICER,
        ),
        201,
    )
    assert_incident(incident)
    assert incident["status"] == "REPORTED"
    assert incident["regulator_notification_due_at"] is None
    assert incident["suspended_certification_count"] == 0
    assert incident["notified_late"] is False

    work_order = validate_success(
        api_client.create_overhaul_work_order(
            factories.create_overhaul_work_order_payload(
                attraction_id,
                park["component"]["id"],
                park["shop_bay"]["id"],
                park["shop_bay"]["version"],
                window_start_date="2026-10-05",
                window_end_date="2026-10-07",
                parts_subtotal_cents=100000,
                labor_hours=10,
            ),
            MANAGER,
        ),
        201,
    )
    assert_work_order(work_order)
    assert work_order["status"] == "SCHEDULED"
    assert work_order["recommissioned_at"] is None

    assert fixtures.read_attraction(attraction_id)["operational_posture"] == "DOWN"


def test_activating_a_revision_supersedes_the_prior_one_and_bumps_the_attraction():
    """Two revisions are never both live, and each activation costs the attraction a version.

    PRD §3.1: "When those gates pass, the revision moves `DRAFT` → `ACTIVE`, its
    `activated_at` is stamped with the current logical clock instant, whichever
    revision of that same attraction was previously `ACTIVE` — there is at most one —
    moves `ACTIVE` → `SUPERSEDED` and is no longer pointed at by the attraction, the
    attraction's `active_template_id` is repointed at the newly activated revision, the
    attraction's `version` increments by one, and the attraction's
    `operational_posture` is recomputed."
    PRD §3.1: "The server assigns the `revision` number itself: 1 for an attraction's
    first template, and otherwise the greatest existing `revision` for that attraction
    plus one."
    PRD §2.8: "`CLOSED_PENDING_INSPECTION` — if the attraction's
    `last_signed_off_service_date` is not the same as the logical clock's current UTC
    date."

    Design: Corner/state_machines/template_activation_applies_every_declared_side_effect_and_supersedes_the_prior_revision
    """
    attraction = fixtures.create_attraction(
        name="Side Effect Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="SE-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    first = fixtures.create_template(attraction["id"], effective_from_date="2026-08-01")
    fixtures.append_line(first["id"], 1, description="Walk the track")
    second = fixtures.create_template(attraction["id"], effective_from_date="2026-08-02")
    fixtures.append_line(
        second["id"], 1, description="Walk the track and the lift hill"
    )
    assert first["revision"] == 1
    assert second["revision"] == 2

    opening_version = fixtures.read_attraction(attraction["id"])["version"]
    activated = validate_success(
        api_client.activate_inspection_template(
            first["id"],
            factories.activate_inspection_template_payload(opening_version),
            ADMIN,
        )
    )
    assert activated["status"] == "ACTIVE"
    assert_instant_equals(activated["activated_at"], CLOCK_START, "activated_at")

    midpoint = fixtures.read_attraction(attraction["id"])
    assert midpoint["active_template_id"] == first["id"]
    assert midpoint["version"] == 2
    assert midpoint["operational_posture"] == "CLOSED_PENDING_INSPECTION"

    validate_success(
        api_client.activate_inspection_template(
            second["id"],
            factories.activate_inspection_template_payload(midpoint["version"]),
            ADMIN,
        )
    )
    retired = validate_success(
        api_client.get_inspection_template(first["id"], ADMIN)
    )
    assert retired["status"] == "SUPERSEDED"
    assert validate_success(
        api_client.get_inspection_template(second["id"], ADMIN)
    )["status"] == "ACTIVE"

    settled = fixtures.read_attraction(attraction["id"])
    assert settled["active_template_id"] == second["id"]
    assert settled["version"] == 3
    assert settled["operational_posture"] == "CLOSED_PENDING_INSPECTION"

    rows, meta = validate_paginated(
        api_client.list_inspection_templates(
            ADMIN, params={"attraction_id": attraction["id"], "status": "ACTIVE"}
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == second["id"]


def _one_row_in_every_machine():
    """One live row per machine: ACTIVE template, OPEN event, REQUESTED requisition,
    REPORTED incident, TRAINEE certification, PENDING fleet action, SCHEDULED order."""
    attraction = fixtures.create_attraction(
        name="Invalid From Ride",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="IF-1",
        ride_class="WATER",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=9000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Control PLC",
        component_type="CONTROL_PLC",
        criticality="ESSENTIAL",
        ndt_interval_cycles=900000,
        ndt_interval_days=3650,
    )
    template = fixtures.create_template(
        attraction["id"], effective_from_date="2026-08-01"
    )
    fixtures.append_line(template["id"], 1, description="Check water level")
    opening_version = fixtures.read_attraction(attraction["id"])["version"]
    fixtures.activate_template(template["id"], attraction["id"])

    event = fixtures.open_downtime(
        attraction["id"], "2026-08-01T09:00:00.000Z", "WEATHER"
    )
    requisition = fixtures.create_requisition(
        attraction["id"],
        part_number="PN-IF",
        quantity=1,
        unit_cost_cents=10000,
        needed_by_date="2026-08-20",
    )
    incident = fixtures.create_incident(
        attraction["id"],
        occurred_at="2026-08-01T08:00:00.000Z",
        injury_severity="MINOR",
        guest_count_affected=1,
        narrative="Guest slipped on the exit stairs.",
    )
    certification = fixtures.create_certification(
        attraction["id"],
        operator_user_id="op-trainee",
        effective_from="2026-08-01T00:00:00.000Z",
        expires_at="2026-12-01T00:00:00.000Z",
        restraint_verification_score=70,
        dispatch_procedure_score=75,
    )
    bulletin = fixtures.create_bulletin(
        "BR-IF-1",
        manufacturer="Mack",
        model_code="IF-1",
        severity="MANDATORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-12-01",
    )
    fixtures.acknowledge_bulletin(bulletin["id"])
    action = fixtures.list_bulletin_actions(bulletin["id"])[0]

    booked = fixtures.book_work_order(
        attraction["id"],
        component["id"],
        bay_name="Bay IF",
        concurrent_slot_capacity=1,
        window_start_date="2026-10-10",
        window_end_date="2026-10-12",
        parts_subtotal_cents=50000,
        labor_hours=5,
    )
    return {
        "attraction": attraction,
        "opening_version": opening_version,
        # The version the attraction settled at once the whole park was built,
        # so the refusals below can be shown to have moved nothing.
        "settled_version": fixtures.read_attraction(attraction["id"])["version"],
        "template": template,
        "event": event,
        "requisition": requisition,
        "incident": incident,
        "certification": certification,
        "action": action,
        "work_order": booked["work_order"],
    }


def test_a_trigger_fired_from_an_undeclared_state_names_the_owning_entity():
    """Seven refusals, seven entity-specific 409 codes, and not one row moved.

    PRD §2.6: "**Declared-transition check.** The target row is in a state from which
    the requested transition is declared. The error names the entity:
    `ERR_TEMPLATE_STATE_INVALID`, `ERR_INSPECTION_STATE_INVALID`,
    `ERR_BULLETIN_STATE_INVALID`, `ERR_ACTION_STATE_INVALID`,
    `ERR_DOWNTIME_STATE_INVALID`, `ERR_REQUISITION_STATE_INVALID`,
    `ERR_CERTIFICATION_STATE_INVALID`, `ERR_INCIDENT_STATE_INVALID` or
    `ERR_WORK_ORDER_STATE_INVALID`, each with HTTP 409."
    PRD §3.4: "An event sitting in `AWAITING_PARTS` must return to `DIAGNOSED` before
    resolution is permitted at all; attempting to resolve from `AWAITING_PARTS` reports
    `ERR_DOWNTIME_STATE_INVALID`."
    PRD §3.8: "A `SafetyOfficer` opens the investigation on an incident that is
    `RIDE_HELD`, moving it `RIDE_HELD` → `UNDER_INVESTIGATION` and recording the acting
    badge in `investigator_user_id`."
    PRD §3.1: "Checklist lines are appended to a revision one at a time, and only while
    that revision is still `DRAFT` — appending to a revision that is `ACTIVE` or
    `SUPERSEDED` is refused with `ERR_TEMPLATE_STATE_INVALID`."
    PRD §3.6: "A `QualifiedInspector` then verifies an action that is `IN_WORK`, moving
    it `IN_WORK` → `VERIFIED`, which is terminal."
    PRD §3.7: "Attempting to suspend a certification whose derived status is `TRAINEE`,
    `SUSPENDED` or `EXPIRED` is refused with `ERR_CERTIFICATION_STATE_INVALID`."
    PRD §3.9: "A `target_phase` that skips a phase, moves backwards, or is requested
    against an order already at `RECOMMISSIONED` is refused with
    `ERR_WORK_ORDER_STATE_INVALID`."

    Design: Corner/state_machines/invalid_from_state_triggers_are_rejected_with_the_owning_entity_state_error
    """
    park = _one_row_in_every_machine()

    resolve = api_client.resolve_downtime_event(
        park["event"]["id"],
        factories.resolve_downtime_payload("2026-08-01T10:00:00.000Z"),
        TECHNICIAN,
    )
    validate_error(resolve, "ERR_DOWNTIME_STATE_INVALID", 409)
    event = validate_success(
        api_client.get_downtime_event(park["event"]["id"], TECHNICIAN)
    )
    assert event["status"] == "OPEN"
    assert event["ended_at"] is None

    receive = api_client.receive_part_requisition(park["requisition"]["id"], TECHNICIAN)
    validate_error(receive, "ERR_REQUISITION_STATE_INVALID", 409)
    assert validate_success(
        api_client.get_part_requisition(park["requisition"]["id"], TECHNICIAN)
    )["status"] == "REQUESTED"

    investigate = api_client.investigate_incident(
        park["incident"]["id"], SAFETY_OFFICER
    )
    validate_error(investigate, "ERR_INCIDENT_STATE_INVALID", 409)
    incident = validate_success(
        api_client.get_incident(park["incident"]["id"], SAFETY_OFFICER)
    )
    assert incident["status"] == "REPORTED"
    assert incident["investigator_user_id"] is None

    append = api_client.append_checklist_item(
        park["template"]["id"],
        factories.append_checklist_item_payload(
            sequence_no=2, description="Late addition to an ACTIVE template"
        ),
        ADMIN,
    )
    validate_error(append, "ERR_TEMPLATE_STATE_INVALID", 409)
    assert validate_success(
        api_client.get_inspection_template(park["template"]["id"], ADMIN)
    )["item_count"] == 1

    verify = api_client.verify_bulletin_action(park["action"]["id"], INSPECTOR)
    validate_error(verify, "ERR_ACTION_STATE_INVALID", 409)
    action = validate_success(
        api_client.get_bulletin_action(park["action"]["id"], MANAGER)
    )
    assert_bulletin_action(action)
    assert action["status"] == "PENDING"
    assert action["verified_at"] is None

    suspend = api_client.suspend_operator_certification(
        park["certification"]["id"],
        factories.suspend_certification_payload("Trainee cannot be suspended"),
        SAFETY_OFFICER,
    )
    validate_error(suspend, "ERR_CERTIFICATION_STATE_INVALID", 409)
    certification = validate_success(
        api_client.get_operator_certification(park["certification"]["id"], MANAGER)
    )
    assert_operator_certification(certification)
    assert certification["status"] == "TRAINEE"
    assert certification["suspended_at"] is None

    advance = api_client.advance_overhaul_work_order(
        park["work_order"]["id"], factories.advance_work_order_payload("REBUILD"), MANAGER
    )
    validate_error(advance, "ERR_WORK_ORDER_STATE_INVALID", 409)
    assert validate_success(
        api_client.get_overhaul_work_order(park["work_order"]["id"], MANAGER)
    )["status"] == "SCHEDULED"

    attraction = fixtures.read_attraction(park["attraction"]["id"])
    assert attraction["operational_posture"] == "DOWN"
    assert attraction["version"] == park["settled_version"], (
        "seven refused triggers advanced the attraction's version"
    )


def test_a_second_acknowledge_is_refused_without_re_running_the_fan_out():
    """The repeat trigger is rejected and, critically, creates no second fleet action.

    PRD §3.6: "A bulletin that is `ISSUED` moves `ISSUED` → `ACKNOWLEDGED`;
    acknowledging one that is already `ACKNOWLEDGED`, `COMPLETED` or `SUPERSEDED` is
    refused with `ERR_BULLETIN_STATE_INVALID`."
    PRD §3.6: "Acknowledgement stamps `acknowledged_at` with the current logical clock
    instant and `acknowledged_by_user_id` with the acting badge, and then fans out: the
    server creates one fleet action with `status` `PENDING` for **every** attraction
    whose `manufacturer` equals the bulletin's `manufacturer` and whose `model_code`
    equals the bulletin's `model_code` — both must match — creating them in order of
    the attractions' `created_at` ascending."
    PRD §3.6: "A `MaintenanceTechnician` starts an action that is `PENDING`, moving it
    `PENDING` → `IN_WORK`; the start additionally requires the parent bulletin's
    `status` to be `ACKNOWLEDGED`, and a start against a non-`PENDING` action or a
    non-acknowledged parent is refused with `ERR_ACTION_STATE_INVALID`."

    Design: Corner/state_machines/bulletin_acknowledge_and_action_start_rejects_the_second_identical_trigger
    """
    fixtures.create_attraction(
        name="Idempotency Ride",
        park_area="SKYLINE",
        manufacturer="Intamin",
        model_code="ID-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=900,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    bulletin = fixtures.create_bulletin(
        "BR-IDEM-1",
        manufacturer="Intamin",
        model_code="ID-1",
        severity="ADVISORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-12-01",
    )
    fixtures.acknowledge_bulletin(bulletin["id"], "mgr-1")
    action = fixtures.list_bulletin_actions(bulletin["id"])[0]
    fixtures.start_action(action["id"])

    repeat = api_client.acknowledge_bulletin(
        bulletin["id"], make_maintenance_manager_headers("mgr-2")
    )
    validate_error(repeat, "ERR_BULLETIN_STATE_INVALID", 409)

    restart = api_client.start_bulletin_action(
        action["id"], make_maintenance_technician_headers("tech-2")
    )
    validate_error(restart, "ERR_ACTION_STATE_INVALID", 409)

    settled = validate_success(api_client.get_bulletin(bulletin["id"], MANAGER))
    assert settled["status"] == "ACKNOWLEDGED"
    assert settled["action_total_count"] == 1
    assert settled["action_verified_count"] == 0
    assert settled["acknowledged_by_user_id"] == "mgr-1"
    assert_instant_equals(settled["acknowledged_at"], CLOCK_START, "acknowledged_at")

    rows, meta = validate_paginated(
        api_client.list_bulletin_actions(MANAGER, params={"bulletin_id": bulletin["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["status"] == "IN_WORK"


def test_terminal_rows_refuse_every_further_trigger_and_keep_their_audit_fields():
    """A cancelled requisition and a cleared incident are closed books.

    PRD §3.5: "A `MaintenanceManager` may cancel a requisition whose `status` is
    `REQUESTED`, `RESERVED` or `BACKORDERED`, supplying a `cancel_reason` that is stored
    on the row; cancelling one that is already `RECEIVED` or `CANCELLED` is refused with
    `ERR_REQUISITION_STATE_INVALID`, and `CANCELLED` is terminal."
    PRD §3.5: "A requisition that is `RESERVED` or `BACKORDERED` moves to `RECEIVED`,
    which is terminal."
    PRD §3.8: "A `SafetyOfficer` clears an incident whose `status` is
    `REGULATOR_NOTIFIED` or `INTERNAL_REVIEW_CLOSED`, moving it to
    `CLEARED_TO_OPERATE`, which is terminal; clearing from any other state is refused
    with `ERR_INCIDENT_STATE_INVALID`."
    PRD §3.8: "Placing a hold on an incident that is not `REPORTED` is refused with
    `ERR_INCIDENT_STATE_INVALID`."
    PRD §3.8: "On this branch `regulator_case_ref` and `notified_at` both stay null and
    `notified_late` stays false; no regulator bookkeeping is created at all."
    PRD §3.8: "The attraction's `regulatory_hold` becomes false — but only when no other
    incident report of that attraction remains in `RIDE_HELD`, `UNDER_INVESTIGATION` or
    `REGULATOR_NOTIFIED`, so a second live incident keeps the hold in place."
    PRD §2.9: "Requisitions in `REQUESTED` and `CANCELLED` are excluded."

    Design: Corner/state_machines/terminal_state_lockdown_rejects_every_further_trigger
    """
    attraction = fixtures.create_attraction(
        name="Terminal Ride",
        park_area="KIDS_COVE",
        manufacturer="Zamperla",
        model_code="TR-1",
        ride_class="KIDDIE",
        theoretical_hourly_capacity=400,
        min_operators_required=1,
        parts_budget_cents=500000,
    )
    requisition = fixtures.create_requisition(
        attraction["id"],
        part_number="PN-TERM",
        quantity=1,
        unit_cost_cents=15000,
        needed_by_date="2026-08-25",
    )
    validate_success(
        api_client.cancel_part_requisition(
            requisition["id"],
            factories.cancel_requisition_payload("Ordered in error"),
            MANAGER,
        )
    )

    incident = fixtures.held_incident(
        attraction["id"],
        injury_severity="MINOR",
        occurred_at="2026-08-01T09:30:00.000Z",
        guest_count_affected=1,
        narrative="Guest bumped an elbow on the restraint.",
    )
    fixtures.clear_incident_internally(incident["id"])

    receive = api_client.receive_part_requisition(requisition["id"], TECHNICIAN)
    validate_error(receive, "ERR_REQUISITION_STATE_INVALID", 409)

    recancel = api_client.cancel_part_requisition(
        requisition["id"],
        factories.cancel_requisition_payload("Second cancel attempt"),
        MANAGER,
    )
    validate_error(recancel, "ERR_REQUISITION_STATE_INVALID", 409)

    settled_requisition = validate_success(
        api_client.get_part_requisition(requisition["id"], TECHNICIAN)
    )
    assert settled_requisition["status"] == "CANCELLED"
    assert settled_requisition["cancel_reason"] == "Ordered in error"

    reclear = api_client.clear_incident(incident["id"], SAFETY_OFFICER)
    validate_error(reclear, "ERR_INCIDENT_STATE_INVALID", 409)

    rehold = api_client.hold_ride(incident["id"], SAFETY_OFFICER)
    validate_error(rehold, "ERR_INCIDENT_STATE_INVALID", 409)

    settled_incident = validate_success(
        api_client.get_incident(incident["id"], SAFETY_OFFICER)
    )
    assert settled_incident["status"] == "CLEARED_TO_OPERATE"
    assert_instant_equals(settled_incident["cleared_at"], CLOCK_START, "cleared_at")
    assert settled_incident["regulator_case_ref"] is None
    assert settled_incident["notified_at"] is None
    assert settled_incident["notified_late"] is False

    settled_attraction = fixtures.read_attraction(attraction["id"])
    assert settled_attraction["regulatory_hold"] is False
    assert settled_attraction["parts_budget_committed_cents"] == 0


def _precondition_walk():
    """A two-line walk: sequence 1 safety-critical, sequence 2 advisory."""
    attraction = fixtures.create_attraction(
        name="Precondition Ride",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="PC-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    template = fixtures.create_template(
        attraction["id"], effective_from_date="2026-08-01"
    )
    fixtures.append_line(
        template["id"], 1, severity_class="SAFETY_CRITICAL",
        description="Restraint pull test",
    )
    fixtures.append_line(
        template["id"], 2, severity_class="ADVISORY", description="Queue line signage"
    )
    fixtures.activate_template(template["id"], attraction["id"])
    inspection = fixtures.open_inspection(attraction["id"], "2026-08-01", "tech-1")
    return {
        "attraction": attraction,
        "inspection": inspection,
        "results": fixtures.list_item_results(inspection["id"]),
    }


def test_a_waived_safety_critical_line_and_a_rejected_parent_fail_differently():
    """One endpoint, two preconditions: a 400 for the waiver and a 409 for the parent state.

    PRD §3.2: "Recording a `PENDING` row as `NA` also decrements `pending_item_count` by
    one — but `NA` may never be recorded against a line whose `severity_class` is
    `SAFETY_CRITICAL`, because a safety-critical check can never be waived, and
    attempting it is a request-shape violation reported as `ERR_INVALID_REQUEST`."
    PRD §3.2: "Recording a `PENDING` row as `PASS` decrements `pending_item_count` by
    one."
    PRD §3.2: "Any attempt to record against an inspection that is `REJECTED` or
    `SIGNED_OFF`, or to record a `PASS` against a `PENDING_SIGN_OFF` inspection, is
    refused with `ERR_INSPECTION_STATE_INVALID`."
    PRD §3.3: "A `MaintenanceTechnician` submits an inspection that is `IN_PROGRESS`,
    moving it `IN_PROGRESS` → `PENDING_SIGN_OFF`, and the operation touches no field on
    any other entity — only the inspection's own `updated_at` and `version` advance."
    PRD §3.3: "Rejecting an inspection that is `PENDING_SIGN_OFF` moves it
    `PENDING_SIGN_OFF` → `REJECTED` and stores the supplied `rejection_reason`, which is
    retained across later reopens for audit purposes."
    PRD §3.2: "Recording sets the row's `recorded_by_user_id` to the acting badge and
    its `recorded_at` to the current logical clock instant, appends that badge to the
    parent inspection's `recorded_by_user_ids` if it is not already present, and
    recomputes the inspection's `pending_item_count`, `blocking_item_count` and
    `essential_fail_count`."

    Design: Corner/state_machines/record_na_on_safety_critical_line_and_record_on_rejected_inspection_are_rejected
    """
    walk = _precondition_walk()
    inspection_id = walk["inspection"]["id"]
    critical, advisory = walk["results"]
    technician = make_maintenance_technician_headers("tech-1")

    waiver = api_client.record_inspection_item_result(
        critical["id"], factories.record_item_result_payload("NA"), technician
    )
    validate_error(waiver, "ERR_INVALID_REQUEST", 400)
    assert validate_success(
        api_client.get_inspection_item_result(critical["id"], TECHNICIAN)
    )["outcome"] == "PENDING"
    assert_inspection_counters(
        validate_success(api_client.get_daily_inspection(inspection_id, TECHNICIAN)),
        status="IN_PROGRESS",
        pending=2,
    )

    passed = validate_success(
        api_client.record_inspection_item_result(
            critical["id"], factories.record_item_result_payload("PASS"), technician
        )
    )
    assert passed["outcome"] == "PASS"
    assert_inspection_counters(
        validate_success(api_client.get_daily_inspection(inspection_id, TECHNICIAN)),
        pending=1,
    )

    waived = validate_success(
        api_client.record_inspection_item_result(
            advisory["id"], factories.record_item_result_payload("NA"), technician
        )
    )
    assert waived["outcome"] == "NA", "NA is legal on an ADVISORY line"
    assert_inspection_counters(
        validate_success(api_client.get_daily_inspection(inspection_id, TECHNICIAN)),
        pending=0,
    )

    submitted = fixtures.submit_inspection(inspection_id, "tech-1")
    assert submitted["status"] == "PENDING_SIGN_OFF"

    rejected = fixtures.reject_inspection(
        inspection_id, "Photo evidence missing", "insp-1"
    )
    assert rejected["status"] == "REJECTED"
    assert rejected["rejection_reason"] == "Photo evidence missing"
    assert rejected["rework_round"] == 0
    assert rejected["recorded_by_user_ids"] == ["tech-1"]

    late = api_client.record_inspection_item_result(
        advisory["id"], factories.record_item_result_payload("PASS"), technician
    )
    validate_error(late, "ERR_INSPECTION_STATE_INVALID", 409)
    assert validate_success(
        api_client.get_inspection_item_result(advisory["id"], TECHNICIAN)
    )["outcome"] == "NA"


def _diagnosed_event_with_two_linked_requisitions():
    """A diagnosed repair waiting on a seal kit and an impeller."""
    attraction = fixtures.create_attraction(
        name="Loop Ride",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="LP-1",
        ride_class="WATER",
        theoretical_hourly_capacity=600,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    event = fixtures.open_downtime(
        attraction["id"], "2026-08-01T11:00:00.000Z", "MECHANICAL"
    )
    fixtures.diagnose_downtime(event["id"], "PUMP-SEAL-LEAK")
    first = fixtures.create_requisition(
        attraction["id"],
        part_number="PN-SEAL",
        quantity=2,
        unit_cost_cents=20000,
        needed_by_date="2026-08-05",
        downtime_event_id=event["id"],
    )
    second = fixtures.create_requisition(
        attraction["id"],
        part_number="PN-IMPELLER",
        quantity=1,
        unit_cost_cents=30000,
        needed_by_date="2026-08-07",
        downtime_event_id=event["id"],
    )
    return {
        "attraction": attraction,
        "event": event,
        "first": first,
        "second": second,
    }


def test_the_awaiting_parts_loop_returns_to_diagnosed_each_time_a_part_arrives():
    """Two full round trips out of and back into DIAGNOSED, driven only by the requisitions.

    PRD §3.4: "Backordering a requisition linked to a `DIAGNOSED` event moves that event
    `DIAGNOSED` → `AWAITING_PARTS`; the attraction's posture stays `DOWN` and the event
    is excluded from the settled capacity picture until it is eventually closed."
    PRD §3.4: "Receiving that part, or cancelling the backordered requisition, moves the
    event `AWAITING_PARTS` → `DIAGNOSED` again, changing no other entity. That round
    trip may repeat any number of times."
    PRD §3.5: "Backordering a requisition that is `REQUESTED` moves it `REQUESTED` →
    `BACKORDERED`, stores the vendor's promise date in `expected_availability_date`, and
    adds the same `total_cost_cents` to `parts_budget_committed_cents`."
    PRD §3.5: "The committed budget does not change, because `RECEIVED` stays inside the
    committed set — this is the one status transition in the requisition lifecycle that
    moves money not at all despite crossing a boundary."
    PRD §2.9: "`ytd_downtime_minutes` is the sum, in whole minutes, of
    `duration_minutes` across every downtime event of that attraction whose `status` is
    exactly `CLOSED`."

    Design: Corner/state_machines/downtime_awaiting_parts_loop_returns_to_diagnosed_when_the_part_arrives
    """
    repair = _diagnosed_event_with_two_linked_requisitions()
    attraction_id = repair["attraction"]["id"]
    event_id = repair["event"]["id"]

    def _event_status():
        return validate_success(
            api_client.get_downtime_event(event_id, TECHNICIAN)
        )

    def _posture():
        return fixtures.read_attraction(attraction_id)["operational_posture"]

    parked = validate_success(
        api_client.backorder_part_requisition(
            repair["first"]["id"], MANAGER, {"expected_availability_date": "2026-08-04"}
        )
    )
    assert parked["status"] == "BACKORDERED"
    assert parked["expected_availability_date"] == "2026-08-04"
    assert _event_status()["status"] == "AWAITING_PARTS"
    assert _posture() == "DOWN"
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"] == 40000
    )

    arrived = validate_success(
        api_client.receive_part_requisition(repair["first"]["id"], TECHNICIAN)
    )
    assert arrived["status"] == "RECEIVED"
    assert _event_status()["status"] == "DIAGNOSED"
    assert _posture() == "DOWN"
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"] == 40000
    )

    validate_success(
        api_client.backorder_part_requisition(
            repair["second"]["id"], MANAGER, {"expected_availability_date": "2026-08-06"}
        )
    )
    assert _event_status()["status"] == "AWAITING_PARTS", "second traversal of the loop"
    assert _posture() == "DOWN"
    assert (
        fixtures.read_attraction(attraction_id)["parts_budget_committed_cents"] == 70000
    )

    validate_success(
        api_client.receive_part_requisition(repair["second"]["id"], TECHNICIAN)
    )
    settled_event = _event_status()
    assert settled_event["status"] == "DIAGNOSED"
    assert settled_event["root_cause_code"] == "PUMP-SEAL-LEAK"
    assert settled_event["ended_at"] is None
    assert _posture() == "DOWN"
    assert fixtures.read_attraction(attraction_id)["ytd_downtime_minutes"] == 0


def _two_units_one_diagnosed_one_open():
    """A1 holds an undiagnosed event and two requisitions; A2 holds a diagnosed one."""
    first = fixtures.create_attraction(
        name="Conditional A1",
        park_area="FRONTIER",
        manufacturer="Vekoma",
        model_code="CC-1",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    second = fixtures.create_attraction(
        name="Conditional A2",
        park_area="LAGOON",
        manufacturer="Mack",
        model_code="CC-2",
        ride_class="WATER",
        theoretical_hourly_capacity=600,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    open_event = fixtures.open_downtime(
        first["id"], "2026-08-01T09:00:00.000Z", "ELECTRICAL"
    )
    diagnosed_event = fixtures.open_downtime(
        second["id"], "2026-08-01T09:00:00.000Z", "MECHANICAL"
    )
    fixtures.diagnose_downtime(diagnosed_event["id"], "GEARBOX-WEAR")
    linked_to_open = fixtures.create_requisition(
        first["id"],
        part_number="PN-CC-A",
        quantity=1,
        unit_cost_cents=10000,
        needed_by_date="2026-08-10",
        downtime_event_id=open_event["id"],
    )
    unlinked = fixtures.create_requisition(
        first["id"],
        part_number="PN-CC-B",
        quantity=1,
        unit_cost_cents=20000,
        needed_by_date="2026-08-10",
    )
    linked_to_diagnosed = fixtures.create_requisition(
        second["id"],
        part_number="PN-CC-C",
        quantity=1,
        unit_cost_cents=50000,
        needed_by_date="2026-08-10",
        downtime_event_id=diagnosed_event["id"],
    )
    return {
        "first": first,
        "second": second,
        "open_event": open_event,
        "diagnosed_event": diagnosed_event,
        "linked_to_open": linked_to_open,
        "unlinked": unlinked,
        "linked_to_diagnosed": linked_to_diagnosed,
    }


def test_a_backorder_parks_only_a_diagnosed_event_and_a_cancel_walks_it_back():
    """The parking cascade fires on exactly one shape of link, and its reverse leg undoes it.

    PRD §3.5: "Backordering carries one cross-entity consequence that reserving does
    not: when the requisition names a `downtime_event_id` whose event is currently
    `DIAGNOSED`, that event moves `DIAGNOSED` → `AWAITING_PARTS`."
    PRD §3.5: "Cancelling a `BACKORDERED` requisition additionally returns a linked
    `AWAITING_PARTS` downtime event to `DIAGNOSED`, on the reasoning that a cancelled
    backorder is no longer a reason to wait."
    PRD §3.5: "Cancelling a `RESERVED` or `BACKORDERED` requisition subtracts exactly
    its `total_cost_cents` back out of the attraction's `parts_budget_committed_cents`,
    restoring the counter to its precise pre-commitment value."
    PRD §2.8: "`DOWN` — if any of the following holds: the attraction has a downtime
    event whose `status` is `OPEN`, `DIAGNOSED`, `AWAITING_PARTS` or `RESOLVED`; or any
    component of the attraction whose `criticality` is `SAFETY_CRITICAL` derives an
    `ndt_status` of `OVERDUE`; or the attraction's daily inspection for the current
    service date has a `status` of `BLOCKED`."

    Design: Corner/state_machines/backorder_parks_only_a_diagnosed_event_and_cancel_walks_it_back
    """
    park = _two_units_one_diagnosed_one_open()
    promise = {"expected_availability_date": "2026-08-09"}

    def _status(event_id):
        return validate_success(
            api_client.get_downtime_event(event_id, TECHNICIAN)
        )["status"]

    validate_success(
        api_client.backorder_part_requisition(
            park["linked_to_open"]["id"], MANAGER, promise
        )
    )
    assert _status(park["open_event"]["id"]) == "OPEN", (
        "the event was not DIAGNOSED, so the cascade is skipped"
    )

    validate_success(
        api_client.backorder_part_requisition(park["unlinked"]["id"], MANAGER, promise)
    )
    assert _status(park["open_event"]["id"]) == "OPEN"

    validate_success(
        api_client.backorder_part_requisition(
            park["linked_to_diagnosed"]["id"], MANAGER, promise
        )
    )
    assert _status(park["diagnosed_event"]["id"]) == "AWAITING_PARTS"

    cancelled = validate_success(
        api_client.cancel_part_requisition(
            park["linked_to_diagnosed"]["id"],
            factories.cancel_requisition_payload("Vendor cannot supply"),
            MANAGER,
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert _status(park["diagnosed_event"]["id"]) == "DIAGNOSED"

    first = fixtures.read_attraction(park["first"]["id"])
    second = fixtures.read_attraction(park["second"]["id"])
    assert first["parts_budget_committed_cents"] == 30000
    assert second["parts_budget_committed_cents"] == 0
    assert first["operational_posture"] == "DOWN"
    assert second["operational_posture"] == "DOWN"


def _acknowledged_bulletin_with_one_started_and_one_deferred_action():
    """Two Zierer ZC-9 units, one mandatory bulletin, one action in work and one deferred."""
    first = fixtures.create_attraction(
        name="Fleet Unit One",
        park_area="FRONTIER",
        manufacturer="Zierer",
        model_code="ZC-9",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    second = fixtures.create_attraction(
        name="Fleet Unit Two",
        park_area="SKYLINE",
        manufacturer="Zierer",
        model_code="ZC-9",
        ride_class="FAMILY",
        theoretical_hourly_capacity=700,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    bulletin = fixtures.create_bulletin(
        "BR-CASC-1",
        manufacturer="Zierer",
        model_code="ZC-9",
        severity="MANDATORY",
        issued_date="2026-07-01",
        compliance_deadline_date="2026-12-01",
    )
    fixtures.acknowledge_bulletin(bulletin["id"])
    actions = fixtures.list_bulletin_actions(bulletin["id"])
    fixtures.start_action(actions[0]["id"])
    fixtures.defer_action(actions[1]["id"], "Parts on order", "2026-11-15")
    return {
        "attractions": [first, second],
        "bulletin": bulletin,
        "actions": actions,
    }


def test_a_successor_bulletin_cancels_only_the_non_terminal_actions():
    """Retirement cascades down to the outstanding work and empties the risk input set.

    PRD §3.6: "The named bulletin, if its `status` is `ISSUED` or `ACKNOWLEDGED`, moves
    to `SUPERSEDED`, which is terminal for a bulletin."
    PRD §3.6: "Every fleet action belonging to that retired bulletin whose `status` is
    `PENDING`, `IN_WORK` or `DEFERRED` moves to `CANCELLED`, and the retired bulletin's
    `action_total_count` is then recomputed with those cancelled rows excluded — which,
    when every outstanding action was cancelled, drives that count to zero."
    PRD §3.6: "That set is every fleet action of the bulletin whose `status` is
    `PENDING`, `IN_WORK` or `DEFERRED`; actions in `VERIFIED` and `CANCELLED` are
    excluded from both figures."
    PRD §3.6: "The `escalation_factor` reflects how much of the fleet has been deferred:
    it is 1 plus 0.05 for each action in the evaluated set whose `status` is `DEFERRED`,
    so `deferred_action_count` deferrals give a factor of 1 plus five hundredths times
    that count."
    PRD §3.6: "When the evaluated set is empty, both scores are 0.00 and `divergence` is
    0.00."

    Design: Corner/state_machines/superseding_bulletin_cancels_only_non_terminal_actions_and_recomputes_the_total
    """
    fleet = _acknowledged_bulletin_with_one_started_and_one_deferred_action()
    retired_id = fleet["bulletin"]["id"]
    started, deferred = fleet["actions"]

    successor = validate_success(
        api_client.create_bulletin(
            factories.create_bulletin_payload(
                "BR-CASC-2",
                manufacturer="Zierer",
                model_code="ZC-9",
                severity="MANDATORY",
                issued_date="2026-08-01",
                compliance_deadline_date="2027-01-15",
                supersedes_bulletin_id=retired_id,
            ),
            ADMIN,
        ),
        201,
    )
    assert successor["status"] == "ISSUED"
    assert successor["supersedes_bulletin_id"] == retired_id
    assert successor["action_total_count"] == 0

    retired = validate_success(api_client.get_bulletin(retired_id, MANAGER))
    assert retired["status"] == "SUPERSEDED"
    assert retired["action_total_count"] == 0
    assert retired["action_verified_count"] == 0

    assert validate_success(
        api_client.get_bulletin_action(started["id"], MANAGER)
    )["status"] == "CANCELLED"

    audited = validate_success(
        api_client.get_bulletin_action(deferred["id"], MANAGER)
    )
    assert audited["status"] == "CANCELLED"
    assert audited["deferral_reason"] == "Parts on order"
    assert audited["deferred_until_date"] == "2026-11-15"

    _rows, meta = validate_paginated(
        api_client.list_bulletin_actions(
            MANAGER, params={"bulletin_id": retired_id, "status": "CANCELLED"}
        )
    )
    assert meta["total_count"] == 2

    risk = validate_success(api_client.get_bulletin_risk(retired_id, MANAGER))
    assert_bulletin_risk_shape(risk)
    assert risk["evaluated_action_count"] == 0
    assert risk["deferred_action_count"] == 0
    assert risk["escalation_factor"] == pytest.approx(1.00, abs=0.01)
    assert risk["fleet_aggregate_score"] == pytest.approx(0.00, abs=0.01)
    assert risk["per_unit_max_score"] == pytest.approx(0.00, abs=0.01)
    assert risk["divergence"] == pytest.approx(0.00, abs=0.01)


def _overdue_axle_in_rebuild():
    """An overdue, failed axle torn down into a single-slot bay, with 30 closed minutes."""
    attraction = fixtures.create_attraction(
        name="Compensation Ride",
        park_area="FRONTIER",
        manufacturer="Gerstlauer",
        model_code="CM-1",
        ride_class="THRILL",
        theoretical_hourly_capacity=800,
        min_operators_required=2,
        parts_budget_cents=1000000,
    )
    component = fixtures.create_component(
        attraction["id"],
        name="Main Axle",
        component_type="AXLE",
        criticality="SAFETY_CRITICAL",
        ndt_interval_cycles=1000,
        ndt_interval_days=3650,
    )
    fixtures.log_cycles(attraction["id"], 1200, "2026-08-01", headers=OPERATOR)

    event = fixtures.open_downtime(
        attraction["id"], "2026-08-01T09:00:00.000Z", "MECHANICAL"
    )
    fixtures.diagnose_downtime(event["id"], "AXLE-CRACK", component["id"])
    fixtures.resolve_downtime(event["id"], "2026-08-01T09:30:00.000Z")
    fixtures.close_downtime(event["id"])

    shop_bay = fixtures.create_shop_bay("Bay Comp", 1)
    booked = fixtures.book_work_order(
        attraction["id"],
        component["id"],
        shop_bay=shop_bay,
        window_start_date="2026-11-05",
        window_end_date="2026-11-09",
        parts_subtotal_cents=200000,
        labor_hours=20,
    )
    for phase in ("TEARDOWN", "INSPECTION", "REBUILD"):
        fixtures.advance_work_order(booked["work_order"]["id"], phase)
    return {
        "attraction": attraction,
        "component": component,
        "event": event,
        "shop_bay": shop_bay,
        "work_order": booked["work_order"],
    }


def test_recommissioning_rebases_the_testing_baselines_and_frees_the_bay_slot():
    """The final phase compensates the lapse it inherited without touching the minutes ledger.

    PRD §3.9: "The `REBUILD` → `RECOMMISSIONED` step is the one that returns iron to
    service: it stamps `recommissioned_at` with the current logical clock instant, resets
    the component's `last_ndt_at` to that same instant and its `last_ndt_cycles` to the
    attraction's current `cumulative_cycles` so its `ndt_status` returns to `CURRENT`,
    returns the component's `condition_flag` to `OK`, decrements the bay's
    `booked_order_count`, and recomputes the attraction's `operational_posture`, which
    now leaves `OVERHAUL`."
    PRD §2.8: "1. `OVERHAUL` — if any overhaul work order of the attraction has a
    `status` of `TEARDOWN`, `INSPECTION` or `REBUILD`. This is the highest-precedence
    posture and outranks even a regulatory hold."
    PRD §3.4: "When a `failed_component_id` is supplied, that component's
    `condition_flag` becomes `FAILED` — a stronger statement than the `SUSPECT` flag an
    inspection failure raises."
    PRD §3.1: "It is **overdue by cycles** when the cycles elapsed is greater than or
    equal to `ndt_interval_cycles` multiplied by a grace factor of 1.20 and rounded up
    to a whole number, and **overdue by days** when the days elapsed is greater than or
    equal to `ndt_interval_days` multiplied by that same 1.20 grace factor and rounded
    up to a whole number."
    PRD §2.9: "Closing a resolved event adds its `duration_minutes` to the counter;
    voiding a closed event subtracts exactly the same number back out, returning the
    counter to its pre-close value."
    PRD §3.4: "For one event, the settled loss is the attraction's
    `theoretical_hourly_capacity` multiplied by that event's weighted lost hours, rounded
    half up to 2 decimal places; that per-event value is exactly what is stamped onto the
    event's own `settled_guest_slots_lost` field at resolution."

    Design: Corner/state_machines/recommissioning_reverses_the_ndt_lapse_and_releases_the_bay_slot
    """
    overhaul = _overdue_axle_in_rebuild()
    component_id = overhaul["component"]["id"]
    bay_id = overhaul["shop_bay"]["id"]

    torn_down = fixtures.read_component(component_id)
    assert_component(torn_down)
    assert torn_down["ndt_status"] == "OVERDUE"
    assert torn_down["condition_flag"] == "FAILED"
    assert fixtures.read_shop_bay(bay_id)["booked_order_count"] == 1
    assert (
        fixtures.read_attraction(overhaul["attraction"]["id"])["operational_posture"]
        == "OVERHAUL"
    )

    recommissioned = validate_success(
        api_client.advance_overhaul_work_order(
            overhaul["work_order"]["id"],
            factories.advance_work_order_payload("RECOMMISSIONED"),
            MANAGER,
        )
    )
    assert_work_order(recommissioned)
    assert recommissioned["status"] == "RECOMMISSIONED"
    assert_instant_equals(
        recommissioned["recommissioned_at"], CLOCK_START, "recommissioned_at"
    )

    rebased = fixtures.read_component(component_id)
    assert rebased["last_ndt_cycles"] == 1200
    assert_instant_equals(rebased["last_ndt_at"], CLOCK_START, "last_ndt_at")
    assert rebased["ndt_status"] == "CURRENT"
    assert rebased["condition_flag"] == "OK"

    assert fixtures.read_shop_bay(bay_id)["booked_order_count"] == 0

    released = fixtures.read_attraction(overhaul["attraction"]["id"])
    assert released["operational_posture"] == "CLOSED_PENDING_INSPECTION"
    assert released["ytd_downtime_minutes"] == 30

    event = validate_success(
        api_client.get_downtime_event(overhaul["event"]["id"], MANAGER)
    )
    assert event["settled_guest_slots_lost"] == pytest.approx(220.00, abs=0.01)
