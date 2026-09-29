"""Compensation cascades, the severity ladder and the compliance sweep."""
import calc
from store import add_days, new_row, now, ordered, store, touch


def employee_of(row):
    return store.employees.get(row["employee_id"])


def bump_employee(emp):
    if emp is not None:
        touch(emp)


# --------------------------------------------------------------- notice exits
def expire_sent_notices(assignment_id):
    """Every SENT EscalationNotice of the assignment becomes EXPIRED."""
    count = 0
    for notice in calc.notices_of_assignment(assignment_id):
        if notice["state"] == "SENT":
            notice["state"] = "EXPIRED"
            touch(notice)
            count += 1
    return count


def close_assignment_consequences(assignment_id, new_state, lift_reason_code):
    """Every ACTIVE AccessConsequence sourced from the assignment leaves ACTIVE."""
    count = 0
    for row in calc.consequences_of_assignment(assignment_id):
        if row["state"] == "ACTIVE":
            row["state"] = new_state
            row["lifted_at"] = now()
            row["lift_reason_code"] = lift_reason_code
            touch(row)
            count += 1
    return count


# ------------------------------------------------------------ severity ladder
def apply_access_consequence(emp, reason_code, consequence_type=None,
                             source_assignment_id=None, trigger_level=None):
    """calculations.access_consequence_severity, five pinned steps."""
    # Step 1 -- pre-existing rank, excluding the row about to be created.
    pre_rank = calc.max_active_rank(emp["id"])

    # Step 2 -- the new rank.
    if consequence_type is not None:
        new_rank = calc.RANK_BY_TYPE[consequence_type]
    else:
        rung = trigger_level if trigger_level else 1
        new_rank = min(max(pre_rank + 1, rung), 3)

    # Step 3 -- create the row, then supersede same-type ACTIVE siblings.
    row = new_row()
    row.update({
        "employee_id": emp["id"],
        "source_assignment_id": source_assignment_id,
        "consequence_type": calc.TYPE_BY_RANK[new_rank],
        "severity_rank": new_rank,
        "state": "ACTIVE",
        "reason_code": reason_code,
        "applied_at": now(),
        "lifted_at": None,
        "lift_reason_code": None,
    })
    store.consequences[row["id"]] = row

    for other in calc.consequences_of(emp["id"]):
        if other["id"] == row["id"]:
            continue
        if other["state"] == "ACTIVE" and other["consequence_type"] == row["consequence_type"]:
            other["state"] = "LIFTED"
            other["lifted_at"] = now()
            other["lift_reason_code"] = "SUPERSEDED"
            touch(other)

    # Steps 4 and 5 -- access_posture and active_suspension_count are derived
    # from the ACTIVE set, so they follow automatically from the rows above.
    return row


# ------------------------------------------------------------- assignment ops
def create_assignment(emp, module, assignment_reason):
    """Creates the row and runs the supersession cascade. Bumps no versions."""
    window = calc.due_window_days(assignment_reason, module["criticality"])
    assigned_at = now()
    row = new_row()
    row.update({
        "employee_id": emp["id"],
        "module_id": module["id"],
        "assignment_reason": assignment_reason,
        "assigned_at": assigned_at,
        "due_at": add_days(assigned_at, window),
        "granted_extension_days": 0,
        "state": "ASSIGNED",
        "attempt_count": 0,
        "last_score_pct": None,
        "completed_at": None,
        "reminders_sent": 0,
        "last_reminder_at": None,
        "escalation_level": 0,
        "superseded_by_assignment_id": None,
        "void_reason_code": None,
    })

    # Supersession: any prior non-terminal assignment of the same pair.
    for prior in calc.assignments_of(emp["id"]):
        if prior["module_id"] != module["id"]:
            continue
        if prior["state"] not in calc.ASSIGNMENT_NON_TERMINAL:
            continue
        prior["state"] = "VOIDED"
        prior["void_reason_code"] = "SUPERSEDED_BY_NEW_ASSIGNMENT"
        prior["superseded_by_assignment_id"] = row["id"]
        touch(prior)
        expire_sent_notices(prior["id"])
        close_assignment_consequences(prior["id"], "VOIDED", "SUPERSEDED_BY_NEW_ASSIGNMENT")

    store.assignments[row["id"]] = row
    return row


def void_assignment(asg, void_reason_code):
    asg["state"] = "VOIDED"
    asg["void_reason_code"] = void_reason_code
    touch(asg)
    expire_sent_notices(asg["id"])
    close_assignment_consequences(asg["id"], "VOIDED", "ASSIGNMENT_VOIDED")


def complete_assignment(asg):
    """Passing submission: the widest release cascade in the training half."""
    asg["state"] = "COMPLETED"
    asg["completed_at"] = now()
    touch(asg)
    expire_sent_notices(asg["id"])
    close_assignment_consequences(asg["id"], "LIFTED", "TRAINING_COMPLETED")
    # A coaching assignment bubbles its intervention up to COACHING_COMPLETED.
    for iv in ordered(list(store.interventions.values())):
        if iv["coaching_assignment_id"] == asg["id"] and iv["state"] == "COACHING_ASSIGNED":
            iv["state"] = "COACHING_COMPLETED"
            touch(iv)


# ------------------------------------------------------------- intervention
def evaluate_intervention(emp, delivery):
    """Opens or escalates a RepeatClickerIntervention after a failure."""
    tier = calc.repeat_clicker_tier(emp)
    if tier < 2:
        return None
    active = [iv for iv in ordered(list(store.interventions.values()))
              if iv["employee_id"] == emp["id"]
              and iv["state"] in calc.INTERVENTION_ACTIVE_STATES]
    if not active:
        row = new_row()
        row.update({
            "employee_id": emp["id"],
            "triggering_delivery_id": delivery["id"] if delivery else None,
            "coaching_assignment_id": None,
            "tier_at_open": tier,
            "state": "ESCALATED_TO_MANAGER" if tier >= 3 else "OPEN",
            "opened_at": now(),
            "closed_at": None,
            "resolution_code": None,
            "tier_decay_applied": False,
        })
        store.interventions[row["id"]] = row
        return row
    for iv in active:
        if iv["state"] == "OPEN" and tier >= 3:
            iv["state"] = "ESCALATED_TO_MANAGER"
            touch(iv)
            return iv
    return active[0]


# --------------------------------------------------------- delivery releases
def release_queued_deliveries(campaign, excluded_reason):
    """EXCLUDE every QUEUED delivery of the campaign, releasing reservations."""
    touched = []
    for delivery in calc.deliveries_of_campaign(campaign["id"]):
        if delivery["state"] != "QUEUED":
            continue
        delivery["state"] = "EXCLUDED"
        delivery["excluded_reason"] = excluded_reason
        touch(delivery)
        emp = employee_of(delivery)
        bump_employee(emp)
        touched.append(delivery)
    return touched


# ------------------------------------------------------------ compliance sweep
def run_compliance_sweep():
    clock = now()
    all_assignments = ordered(list(store.assignments.values()))
    result = {
        "assignments_scanned": len(all_assignments),
        "reminders_sent_count": 0,
        "overdue_count": 0,
        "escalations_created_count": 0,
        "consequences_applied_count": 0,
        "swept_at": clock,
    }

    # --- Step A: at most one cadence reminder per assignment.
    for asg in all_assignments:
        if asg["state"] not in calc.ASSIGNMENT_NON_TERMINAL:
            continue
        module = store.modules.get(asg["module_id"])
        if module is None:
            continue
        due = calc.next_reminder_due_at(asg, module)
        if due is not None and due <= clock:
            asg["reminders_sent"] += 1
            asg["last_reminder_at"] = clock
            touch(asg)
            result["reminders_sent_count"] += 1

    # --- Step B: overdue marking.
    for asg in ordered(list(store.assignments.values())):
        if asg["state"] not in ("ASSIGNED", "IN_PROGRESS", "FAILED_ATTEMPT"):
            continue
        if calc.effective_due_at(asg) < clock:
            asg["state"] = "OVERDUE"
            touch(asg)
            bump_employee(employee_of(asg))
            result["overdue_count"] += 1

    # --- Step C: the escalation ladder, walking every newly reached rung.
    for asg in ordered(list(store.assignments.values())):
        if asg["state"] not in ("OVERDUE", "ESCALATED"):
            continue
        days = calc.days_overdue(asg, clock)
        target = calc.escalation_target_level(days)
        if target <= asg["escalation_level"]:
            continue
        emp = employee_of(asg)
        start = asg["escalation_level"] + 1
        for level in range(start, target + 1):
            asg["escalation_level"] = level          # hop 1
            if emp is None or not emp.get("manager_id"):
                continue                              # hop 2 fails -> 3 and 4 never fire
            notice = new_row()
            notice.update({
                "assignment_id": asg["id"],
                "manager_id": emp["manager_id"],
                "level": level,
                "sent_at": clock,
                "state": "SENT",
                "acknowledged_at": None,
                "action_plan_note": None,
            })
            store.notices[notice["id"]] = notice
            result["escalations_created_count"] += 1
            if level >= 2:                            # hop 3
                apply_access_consequence(
                    emp,
                    reason_code="ESCALATION_LEVEL_%d" % level,
                    consequence_type=None,
                    source_assignment_id=asg["id"],
                    trigger_level=level,
                )
                result["consequences_applied_count"] += 1
        if asg["escalation_level"] >= 2 and asg["state"] == "OVERDUE":
            asg["state"] = "ESCALATED"
        touch(asg)
        bump_employee(emp)

    # --- Step D: every derived field is computed on read, so nothing to do.
    return result
