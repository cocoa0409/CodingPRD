"""Domain services: derivations, recomputation and cascades."""
from decimal import Decimal

import calc
import store
from errors import ApiError

BILLING_COMMITTED_STATES = ("DRAFT", "SUBMITTED", "APPROVED", "PAID")


# ---------------------------------------------------------------- lookups
def plan_orders(plan_id):
    return store.ordered([w for w in store.work_orders.values()
                          if w.get("work_plan_id") == plan_id])


def order_assignments(work_order_id):
    return store.ordered([a for a in store.crew_assignments.values()
                          if a.get("work_order_id") == work_order_id])


def crew_assignments_of(crew_id):
    return store.ordered([a for a in store.crew_assignments.values()
                          if a.get("crew_id") == crew_id])


def assignment_entries(assignment_id):
    return [e for e in store.production_entries.values()
            if e.get("crew_assignment_id") == assignment_id]


def order_entries(work_order_id):
    rows = []
    for assignment in order_assignments(work_order_id):
        rows.extend(assignment_entries(assignment["id"]))
    return sorted(rows, key=lambda r: (r.get("work_date") or "",
                                       r.get("created_at") or "", r.get("_seq", 0)))


def order_notifications(work_order_id):
    return store.ordered([n for n in store.customer_notifications.values()
                          if n.get("work_order_id") == work_order_id])


def order_lines(work_order_id):
    return store.ordered([b for b in store.billing_lines.values()
                          if b.get("work_order_id") == work_order_id])


def plan_lines(plan_id):
    ids = {w["id"] for w in plan_orders(plan_id)}
    return store.ordered([b for b in store.billing_lines.values()
                          if b.get("work_order_id") in ids])


def circuit_of_plan(plan):
    return store.circuits.get(plan.get("circuit_id")) if plan else None


def plan_of_order(work_order):
    return store.work_plans.get(work_order.get("work_plan_id")) if work_order else None


def circuit_of_order(work_order):
    plan = plan_of_order(work_order)
    return circuit_of_plan(plan) if plan else None


def crew_of_assignment(assignment):
    return store.crews.get(assignment.get("crew_id")) if assignment else None


# ---------------------------------------------------------------- prescriptions
def resolve_prescription_for(circuit):
    candidates = [p for p in store.prescriptions.values()
                  if p.get("status") == "ACTIVE"
                  and p.get("voltage_class") == circuit.get("voltage_class")
                  and p.get("growth_zone") == circuit.get("growth_zone")]
    if not candidates:
        raise ApiError("ERR_NO_ACTIVE_PRESCRIPTION",
                       "no ACTIVE prescription matches the circuit")
    candidates.sort(key=lambda p: (p.get("effective_from") or "",
                                   p.get("created_at") or "", p.get("_seq", 0)),
                    reverse=True)
    return candidates[0]


def prescription_of_circuit(circuit):
    if not circuit:
        return None
    return store.prescriptions.get(circuit.get("prescription_id"))


# ---------------------------------------------------------------- circuits
def apply_cycle(circuit, bump=False):
    prescription = prescription_of_circuit(circuit)
    if prescription is None:
        return False
    months, due = calc.trim_cycle_months(circuit, prescription)
    changed = (circuit.get("cycle_months") != months
               or circuit.get("next_trim_due_on") != due)
    circuit["cycle_months"] = months
    circuit["next_trim_due_on"] = due
    if changed and bump:
        store.touch(circuit)
    return changed


def recompute_reliability(circuit, write=True):
    index_36, index_ytd, count_36, tier = calc.reliability_windows(
        circuit, list(store.outage_records.values()), store.now())
    if write:
        circuit["reliability_index_36mo"] = index_36
        circuit["reliability_index_ytd"] = index_ytd
        circuit["tree_caused_outage_count_36mo"] = count_36
        circuit["reliability_tier"] = tier
    return index_36, index_ytd, count_36, tier


def set_trim_status(circuit, new_status):
    if circuit is None:
        return
    if circuit.get("trim_status") == new_status:
        return
    circuit["trim_status"] = new_status
    store.touch(circuit)


# ---------------------------------------------------------------- work plans
def recompute_plan(plan, bump=True):
    if plan is None:
        return False
    orders = plan_orders(plan["id"])
    planned = sum(int(w.get("planned_unit_count") or 0) for w in orders
                  if w.get("execution_status") != "CANCELLED")
    completed = sum(int(w.get("actual_units_completed") or 0) for w in orders
                    if w.get("execution_status") in ("IN_PROGRESS", "STORM_PREEMPTED",
                                                     "COMPLETED"))
    pct = calc.ratio_pct(completed, planned)
    changed = (plan.get("planned_unit_count") != planned
               or plan.get("completed_unit_count") != completed
               or plan.get("production_pct") != pct)
    plan["planned_unit_count"] = planned
    plan["completed_unit_count"] = completed
    plan["production_pct"] = pct
    if changed and bump:
        store.touch(plan)
    return changed


def recompute_committed(plan, bump=True):
    if plan is None:
        return False
    total = sum(int(b.get("final_payable_cents") or 0)
                for b in plan_lines(plan["id"])
                if b.get("status") in BILLING_COMMITTED_STATES)
    changed = plan.get("committed_cents") != total
    plan["committed_cents"] = total
    if changed and bump:
        store.touch(plan)
    return changed


def committed_with(plan, line, forced_status):
    """committed_cents recomputed as if `line` carried `forced_status`."""
    total = 0
    for row in plan_lines(plan["id"]):
        status = forced_status if row["id"] == line["id"] else row.get("status")
        if status in BILLING_COMMITTED_STATES:
            total += int(row.get("final_payable_cents") or 0)
    return total


def crew_production_rate(plan):
    units = Decimal(0)
    hours = Decimal(0)
    for work_order in plan_orders(plan["id"]):
        if work_order.get("execution_status") == "CANCELLED":
            continue
        for entry in order_entries(work_order["id"]):
            units += calc.dec(entry.get("units_trimmed") or 0)
            hours += calc.dec(entry.get("labor_hours") or 0)
    return calc.rate_per_hour(units, hours)


# ---------------------------------------------------------------- billing
def price_line(line, work_order):
    """Run work_order_billable_amount + billing_line_settlement onto the line."""
    circuit = circuit_of_order(work_order)
    if line.get("billing_method") == "UNIT_PRICE":
        actual = int(work_order.get("actual_units_completed") or 0)
        blocked = int(work_order.get("refusal_blocked_unit_count") or 0)
        billable = max(0, actual - blocked)
        multiplier = calc.density_multiplier(billable, work_order.get("span_miles"))
        gross = calc.unit_price_gross(billable, multiplier, circuit["voltage_class"])
        line["billable_units"] = billable
        line["density_multiplier"] = float(multiplier)
    else:
        gross = 0
        for entry in order_entries(work_order["id"]):
            gross += int(entry.get("entry_cents") or 0)
        line["billable_units"] = 0
        line["density_multiplier"] = 1.00
    result = calc.settlement(gross, work_order.get("storm_event_id") is not None)
    line.update(result)
    return line


def newest_live_line(work_order_id):
    live = [b for b in store.billing_lines.values()
            if b.get("work_order_id") == work_order_id and b.get("status") != "VOID"]
    if not live:
        return None
    live.sort(key=lambda b: (b.get("created_at") or "", int(b.get("version") or 0),
                             b.get("_seq", 0)), reverse=True)
    return live[0]


LINE_TO_BILLING_STATUS = {
    "DRAFT": "LINE_DRAFTED",
    "SUBMITTED": "SUBMITTED",
    "APPROVED": "APPROVED",
    "DISPUTED": "DISPUTED",
    "PAID": "SETTLED",
}


def derive_billing_status(work_order, bump=True):
    newest = newest_live_line(work_order["id"])
    if newest is None:
        target = "BILLABLE" if work_order.get("execution_status") == "COMPLETED" \
            else "NOT_BILLABLE"
    else:
        target = LINE_TO_BILLING_STATUS.get(newest.get("status"),
                                            work_order.get("billing_status"))
    if work_order.get("billing_status") == target:
        return False
    work_order["billing_status"] = target
    if bump:
        store.touch(work_order)
    return True


def reprice_draft_lines(work_order):
    for line in order_lines(work_order["id"]):
        if line.get("status") != "DRAFT":
            continue
        price_line(line, work_order)
        store.touch(line)


def recompute_refusal_blocked(work_order):
    total = sum(int(n.get("unit_count_at_premise") or 0)
                for n in order_notifications(work_order["id"])
                if n.get("status") == "FINAL_REFUSAL")
    work_order["refusal_blocked_unit_count"] = total
    return total


# ---------------------------------------------------------------- crews
def crew_has_live_booking(crew_id, exclude_id=None):
    for assignment in crew_assignments_of(crew_id):
        if exclude_id is not None and assignment["id"] == exclude_id:
            continue
        if assignment.get("status") in ("SCHEDULED", "ACTIVE"):
            return True
    return False


def free_crew_if_idle(crew, exclude_id=None, bump=True):
    if crew is None:
        return False
    if crew.get("status") != "ASSIGNED":
        return False
    if crew_has_live_booking(crew["id"], exclude_id):
        return False
    crew["status"] = "AVAILABLE"
    if bump:
        store.touch(crew)
    return True


def release_order_assignments(work_order):
    for assignment in order_assignments(work_order["id"]):
        if assignment.get("status") not in ("SCHEDULED", "ACTIVE"):
            continue
        assignment["status"] = "RELEASED"
        store.touch(assignment)
        free_crew_if_idle(crew_of_assignment(assignment))


# ---------------------------------------------------------------- plan moves
def plan_begin_execution(plan):
    """WorkPlan RELEASED -> IN_PROGRESS (driven by the first span start)."""
    if plan is None or plan.get("status") != "RELEASED":
        return False
    plan["status"] = "IN_PROGRESS"
    store.touch(plan)
    circuit = circuit_of_plan(plan)
    if circuit is not None and circuit.get("trim_status") == "SCHEDULED":
        set_trim_status(circuit, "ACTIVE_CYCLE")
    return True


def plan_maybe_complete(plan):
    """WorkPlan IN_PROGRESS -> COMPLETED when every span is terminal."""
    if plan is None or plan.get("status") != "IN_PROGRESS":
        return False
    orders = plan_orders(plan["id"])
    if not orders:
        return False
    if any(w.get("execution_status") not in ("COMPLETED", "CANCELLED") for w in orders):
        return False
    if not any(w.get("execution_status") == "COMPLETED" for w in orders):
        return False
    plan["status"] = "COMPLETED"
    store.touch(plan)
    circuit = circuit_of_plan(plan)
    if circuit is not None:
        if circuit.get("trim_status") == "ACTIVE_CYCLE":
            circuit["trim_status"] = "CYCLE_COMPLETE"
        circuit["last_trim_completed_on"] = store.today_str()
        apply_cycle(circuit, bump=False)
        store.touch(circuit)
    return True


def plan_maybe_suspend(plan):
    """Storm hop 4: WorkPlan IN_PROGRESS -> SUSPENDED."""
    if plan is None or plan.get("status") != "IN_PROGRESS":
        return False
    relevant = [w for w in plan_orders(plan["id"])
                if w.get("execution_status") not in ("CANCELLED", "PLANNED")]
    if not relevant:
        return False
    if any(w.get("execution_status") != "STORM_PREEMPTED" for w in relevant):
        return False
    plan["status"] = "SUSPENDED"
    store.touch(plan)
    circuit = circuit_of_plan(plan)
    if circuit is not None and circuit.get("trim_status") == "ACTIVE_CYCLE":
        set_trim_status(circuit, "CYCLE_AT_RISK")
    return True


def plan_maybe_resume(plan):
    """Demobilization: WorkPlan SUSPENDED -> IN_PROGRESS."""
    if plan is None or plan.get("status") != "SUSPENDED":
        return False
    if any(w.get("execution_status") == "STORM_PREEMPTED" for w in plan_orders(plan["id"])):
        return False
    plan["status"] = "IN_PROGRESS"
    store.touch(plan)
    circuit = circuit_of_plan(plan)
    if circuit is not None and circuit.get("trim_status") == "CYCLE_AT_RISK":
        set_trim_status(circuit, "ACTIVE_CYCLE")
    return True


def cancel_order(work_order):
    work_order["execution_status"] = "CANCELLED"
    store.touch(work_order)
    release_order_assignments(work_order)


# ---------------------------------------------------------------- storm
def refresh_storm_counters(event):
    deployed = sum(1 for c in store.crews.values()
                   if c.get("status") == "STORM_DEPLOYED"
                   and c.get("_storm_event_id") == event["id"])
    preempted = sum(1 for a in store.crew_assignments.values()
                    if a.get("preempted_by_storm_event_id") == event["id"]
                    and a.get("status") == "PREEMPTED")
    changed = (event.get("reassigned_crew_count") != deployed
               or event.get("preempted_assignment_count") != preempted)
    event["reassigned_crew_count"] = deployed
    event["preempted_assignment_count"] = preempted
    return changed


def spawn_remainder_child(parent, event):
    planned = int(parent.get("planned_unit_count") or 0)
    actual = int(parent.get("actual_units_completed") or 0)
    remainder = planned - actual
    child = store.new_record()
    child.update({
        "work_plan_id": parent.get("work_plan_id"),
        "parent_work_order_id": parent["id"],
        "storm_event_id": event["id"],
        "span_miles": parent.get("span_miles"),
        "billing_method": parent.get("billing_method"),
        "planned_unit_count": remainder,
        "clearance_radius_ft": None,
        "actual_units_completed": 0,
        "refusal_blocked_unit_count": 0,
        "execution_status": "PLANNED",
        "billing_status": "NOT_BILLABLE",
        "completed_at": None,
    })
    store.work_orders[child["id"]] = child
    parent["planned_unit_count"] = actual
    return child


def storm_reassign(event, crew):
    # hop 1
    crew["status"] = "STORM_DEPLOYED"
    crew["_storm_event_id"] = event["id"]
    store.touch(crew)

    # hop 2
    touched_orders = []
    for assignment in crew_assignments_of(crew["id"]):
        if assignment.get("status") not in ("SCHEDULED", "ACTIVE"):
            continue
        assignment["status"] = "PREEMPTED"
        assignment["preempted_by_storm_event_id"] = event["id"]
        store.touch(assignment)
        work_order = store.work_orders.get(assignment.get("work_order_id"))
        if work_order is not None and work_order not in touched_orders:
            touched_orders.append(work_order)

    # hop 3
    affected_plans = []
    for work_order in touched_orders:
        if work_order.get("execution_status") != "IN_PROGRESS":
            continue
        bookings = order_assignments(work_order["id"])
        if any(a.get("status") not in ("PREEMPTED", "RELEASED") for a in bookings):
            continue
        work_order["execution_status"] = "STORM_PREEMPTED"
        spawn_remainder_child(work_order, event)
        store.touch(work_order)
        plan = plan_of_order(work_order)
        if plan is not None and plan not in affected_plans:
            affected_plans.append(plan)

    # hop 4
    for plan in affected_plans:
        plan_maybe_suspend(plan)
        recompute_plan(plan)

    refresh_storm_counters(event)
    store.touch(event)
    return event


def storm_demobilize(event):
    event["status"] = "DEMOBILIZING"
    store.touch(event)

    touched_orders = []
    for assignment in store.ordered(list(store.crew_assignments.values())):
        if assignment.get("preempted_by_storm_event_id") != event["id"]:
            continue
        if assignment.get("status") != "PREEMPTED":
            continue
        assignment["status"] = "RELEASED"
        store.touch(assignment)
        work_order = store.work_orders.get(assignment.get("work_order_id"))
        if work_order is not None and work_order not in touched_orders:
            touched_orders.append(work_order)

    for crew in store.ordered(list(store.crews.values())):
        if crew.get("status") == "STORM_DEPLOYED" and crew.get("_storm_event_id") == event["id"]:
            crew["status"] = "AVAILABLE"
            crew["_storm_event_id"] = None
            store.touch(crew)

    affected_plans = []
    for work_order in touched_orders:
        if work_order.get("execution_status") != "STORM_PREEMPTED":
            continue
        work_order["execution_status"] = "RELEASED"
        for child in plan_orders(work_order.get("work_plan_id")):
            if (child.get("parent_work_order_id") == work_order["id"]
                    and child.get("storm_event_id") == event["id"]
                    and child.get("execution_status") == "PLANNED"):
                child["execution_status"] = "CANCELLED"
                store.touch(child)
                work_order["planned_unit_count"] = (
                    int(work_order.get("planned_unit_count") or 0)
                    + int(child.get("planned_unit_count") or 0))
        store.touch(work_order)
        plan = plan_of_order(work_order)
        if plan is not None and plan not in affected_plans:
            affected_plans.append(plan)

    for plan in affected_plans:
        recompute_plan(plan)
        plan_maybe_resume(plan)

    event["reassigned_crew_count"] = 0
    event["preempted_assignment_count"] = 0
    return event


# ---------------------------------------------------------------- transitions
TERMINAL_STATES = {
    "prescription": {"SUPERSEDED"},
    "work_plan": {"COMPLETED", "CANCELLED"},
    "work_order": {"COMPLETED", "CANCELLED"},
    "crew_assignment": {"RELEASED"},
    "customer_notification": {"ACKNOWLEDGED", "FINAL_REFUSAL"},
    "hazard_tree": {"DECLINED", "REMOVED"},
    "herbicide_permit": {"DENIED", "REVOKED", "EXPIRED"},
    "storm_event": {"CLOSED"},
    "billing_line": {"PAID", "VOID"},
    "work_order_billing": {"SETTLED"},
}


def require_state(record, kind, allowed_from, field="status"):
    """Priority 11 (terminal) then priority 10 (declared transition)."""
    current = record.get(field)
    if current in TERMINAL_STATES.get(kind, set()):
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "resource is already in terminal state %s" % current)
    if current not in allowed_from:
        raise ApiError("ERR_INVALID_STATE",
                       "transition is not declared from state %s" % current)
    return current
