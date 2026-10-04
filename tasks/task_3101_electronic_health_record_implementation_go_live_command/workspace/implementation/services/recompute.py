"""Derived-field recomputation and system-driven state transitions."""

from decimal import Decimal

from db import (
    COMMAND_CENTER_ESCALATION_MINUTES,
    DB,
    HANDOFF_BUFFER_MINUTES,
    add_minutes,
)
from services import calculations as C
from services import lookups as L

D = Decimal


# --------------------------------------------------------------------------
# Leaf recomputation
# --------------------------------------------------------------------------
def recompute_defect(defect):
    defect["blocks_go_live"] = (
        defect["severity"] in ("SEV1", "SEV2") and defect["status"] != "RESOLVED"
    )
    if defect.get("opened_utc") is not None:
        delta = DB.clock.get() - defect["opened_utc"]
        hours = delta.total_seconds() / 3600.0
        defect["aging_hours"] = float(C.q2(hours)) if hours > 0 else 0.0
    else:
        defect["aging_hours"] = 0.0


def recompute_scenario(scenario):
    scenario["open_defect_count"] = sum(
        1
        for d in L.scenario_defects(scenario["id"])
        if d["status"] not in ("RESOLVED", "DEFERRED")
    )
    return scenario


def recompute_build_item(item, program=None):
    if program is None:
        program = DB.ehr_implementations.get(item["ehr_implementation_id"])
    scenarios = L.build_item_scenarios(item["id"])
    epoch = program["current_epoch_index"] if program is not None else 0
    item["test_cycles_passed"] = C.test_cycles_passed(scenarios, epoch)
    item["open_defect_count"] = sum(
        1
        for scenario in scenarios
        for d in L.scenario_defects(scenario["id"])
        if d["status"] not in ("RESOLVED", "DEFERRED")
    )
    return item


def recompute_department(department):
    staff = L.department_staff(department["id"])
    cleared = C.cleared_staff(staff)
    department["proficiency_cleared_count"] = len(cleared)
    ratio, gate_open = C.proficiency_ratio(department["required_staff_count"], len(cleared))
    department["proficiency_cleared_ratio"] = float(ratio)
    department["proficiency_gate_open"] = gate_open

    blocking = 0
    for item in L.department_build_items(department["id"]):
        for scenario in L.build_item_scenarios(item["id"]):
            for defect in L.scenario_defects(scenario["id"]):
                if defect["severity"] in ("SEV1", "SEV2") and defect["status"] in C.OPEN_DEFECT_STATES:
                    blocking += 1
    department["build_blocking_defect_count"] = blocking
    return department


def recompute_facility(facility):
    orders = L.facility_orders(facility["id"])
    facility["revenue_cycle_stabilization_index"] = float(
        C.revenue_cycle_index(DB.clock.get(), orders)
    )
    reconciled = [
        b for b in L.children_by(DB.data_conversion_batches, "facility_id", facility["id"])
        if b["status"] == "RECONCILED"
    ]
    facility["conversion_variance_index"] = float(
        max(
            [D(str(b["variance_penalty_points"] or 0)) for b in reconciled],
            default=D("0.00"),
        )
    )
    facility["converted_patient_count"] = int(facility.get("converted_patient_count") or 0)
    facility["is_live"] = bool(facility.get("is_live"))
    return facility


def recompute_trainer(trainer):
    if trainer["status"] == "CERTIFIED" and trainer.get("expires_utc") is not None:
        if DB.clock.get() >= trainer["expires_utc"]:
            trainer["status"] = "EXPIRED"
            DB.touch(trainer, common=True)
    return trainer


def recompute_channel(channel):
    epoch = DB.ehr_implementations[channel["ehr_implementation_id"]]["current_epoch_index"]
    cycle = int(channel.get("_cycle") or 0)
    messages = L.channel_messages(channel["id"])
    validated = 0
    rejected = 0
    for message in messages:
        if message.get("decided_epoch") != epoch:
            continue
        if int(message.get("_cycle") or 0) != cycle:
            # decided in a validation cycle that was discarded by return-to-build
            continue
        if message["validation_status"] == "VALIDATED":
            validated += 1
        elif message["validation_status"] == "REJECTED":
            rejected += 1
    channel["validated_message_count"] = validated
    channel["rejected_message_count"] = rejected
    rate, passes = C.interface_pass_rate(validated, rejected)
    channel["interface_message_validation_pass_rate"] = float(rate)
    channel["_validation_passes"] = passes
    return channel


def recompute_program(program):
    base, posture = C.readiness_scores(program, optimistic=False)
    optimistic, _ = C.readiness_scores(program, optimistic=True)
    program["readiness_score"] = float(base)
    program["readiness_posture"] = posture
    program["optimistic_readiness_score"] = float(optimistic)
    program["net_trainer_count"] = sum(
        1
        for t in DB.credentialed_trainers.values()
        if t["ehr_implementation_id"] == program["id"] and t["status"] == "CERTIFIED"
    )
    return program


# --------------------------------------------------------------------------
# System-driven state transitions
#
# Each of these is an *event* trigger named by SCAFFOLD §1.2. They are invoked
# at the single operation that fires them rather than on every read, so a
# derived count that later returns to zero never silently re-transitions a row
# on an unrelated request.
# --------------------------------------------------------------------------
def on_blocking_defect_change(department):
    """BUILD_COMPLETE <-> BUILD_REJECTED cyclic revision loop."""
    blocking = department["build_blocking_defect_count"]
    if department["status"] == "BUILD_COMPLETE" and blocking > 0:
        department["status"] = "BUILD_REJECTED"
        DB.touch(department, common=True)
        on_department_rejection_change(DB.facilities.get(department["facility_id"]))
    elif department["status"] == "BUILD_REJECTED" and blocking == 0:
        department["status"] = "BUILD_COMPLETE"
        DB.touch(department, common=True)
        on_department_rejection_change(DB.facilities.get(department["facility_id"]))


def on_department_rejection_change(facility):
    """BUILD_CONFIGURED <-> REMEDIATION_REQUIRED."""
    if facility is None:
        return
    any_rejected = any(
        d["status"] == "BUILD_REJECTED" for d in L.facility_departments(facility["id"])
    )
    if facility["status"] == "BUILD_CONFIGURED" and any_rejected:
        facility["status"] = "REMEDIATION_REQUIRED"
        DB.touch(facility, common=True)
    elif facility["status"] == "REMEDIATION_REQUIRED" and not any_rejected:
        facility["status"] = "BUILD_CONFIGURED"
        DB.touch(facility, common=True)


def on_proficiency_ratio_change(department):
    """TRAINING_IN_PROGRESS -> REMEDIATION_REQUIRED after a completed exam."""
    if department is None:
        return
    if department["status"] == "TRAINING_IN_PROGRESS" and not department[
        "proficiency_gate_open"
    ]:
        department["status"] = "REMEDIATION_REQUIRED"
        DB.touch(department, common=True)


def on_facility_entered_live(facility):
    """Cascade fired when a facility enters LIVE.

    Link 2: each of its READY_FOR_GO_LIVE departments reaches the terminal LIVE.
    Link 3: an order still UNPOSTED at go-live, placed during the downtime window
    (i.e. carried over from before the cutover), has no electronic charge and
    moves to PAPER_BACKFILL_REQUIRED on its own.
    """
    for department in L.facility_departments(facility["id"]):
        if department["status"] == "READY_FOR_GO_LIVE":
            department["status"] = "LIVE"
            DB.touch(department, common=True)
    now = DB.clock.get()
    for order in L.facility_orders(facility["id"]):
        if (
            order["clinical_state"] == "CONVERTED"
            and order["billing_state"] == "UNPOSTED"
            and order["encounter_utc"] <= now
        ):
            order["clinical_state"] = "PAPER_BACKFILL_REQUIRED"
            DB.touch(order, common=True)


def on_facility_billing_change(facility):
    """LIVE <-> STABILIZATION_AT_RISK cyclic revert driven by claim denials."""
    if facility is None:
        return
    any_denied = any(
        o["billing_state"] == "CLAIM_DENIED" for o in L.facility_orders(facility["id"])
    )
    if facility["status"] == "LIVE" and any_denied:
        facility["status"] = "STABILIZATION_AT_RISK"
        DB.touch(facility, common=True)
    elif facility["status"] == "STABILIZATION_AT_RISK" and not any_denied:
        facility["status"] = "LIVE"
        DB.touch(facility, common=True)



def settle_program(program):
    if program["status"] != "COMMAND_CENTER_ACTIVE":
        return
    pending = {"SITE_REGISTERED", "BUILD_CONFIGURED", "VALIDATED", "CUTOVER_READY", "LIVE"}
    if all(f["status"] not in pending for f in L.program_facilities(program["id"])):
        program["status"] = "STABILIZED"


def recompute_program_tree(program_id):
    program = DB.ehr_implementations.get(program_id)
    if program is None:
        return
    # clock-driven automatic transitions
    for assignment in DB.training_assignments.values():
        if assignment["ehr_implementation_id"] != program_id:
            continue
        if assignment["status"] in ("ASSIGNED", "IN_PROGRESS"):
            due = assignment.get("due_utc")
            if due is not None and DB.clock.get() > due:
                assignment["status"] = "OVERDUE"
                DB.touch(assignment, common=True)
    for trainer in DB.credentialed_trainers.values():
        if trainer["ehr_implementation_id"] == program_id:
            recompute_trainer(trainer)
    for shift in DB.staffing_shifts.values():
        if shift["ehr_implementation_id"] != program_id:
            continue
        if shift["status"] == "SCHEDULED":
            deadline = add_minutes(shift["start_utc"], HANDOFF_BUFFER_MINUTES)
            if DB.clock.get() > deadline:
                shift["status"] = "NO_SHOW"
                DB.touch(shift, common=True)
    for ticket in DB.command_center_tickets.values():
        if ticket["ehr_implementation_id"] != program_id:
            continue
        if ticket["triage_state"] in ("TRIAGED", "IN_RESOLUTION"):
            deadline = add_minutes(ticket["reported_utc"], COMMAND_CENTER_ESCALATION_MINUTES)
            if DB.clock.get() > deadline:
                ticket["triage_state"] = "ESCALATED"
                DB.touch(ticket, common=True)

    # derived fields, leaves first
    for defect in L.program_defects(program_id):
        recompute_defect(defect)
    for scenario in L.children_by(DB.test_scenarios, "ehr_implementation_id", program_id):
        recompute_scenario(scenario)
    for item in L.program_build_items(program_id):
        recompute_build_item(item, program)
    for department in DB.departments.values():
        if department["ehr_implementation_id"] == program_id:
            recompute_department(department)
    for facility in L.program_facilities(program_id):
        recompute_facility(facility)
    for channel in L.program_channels(program_id):
        recompute_channel(channel)

    for department in DB.departments.values():
        if department["ehr_implementation_id"] == program_id:
            recompute_department(department)
    for facility in L.program_facilities(program_id):
        recompute_facility(facility)

    recompute_program(program)
    settle_program(program)


def recompute_for_ehr(ehr_implementation_id):
    if ehr_implementation_id:
        recompute_program_tree(ehr_implementation_id)