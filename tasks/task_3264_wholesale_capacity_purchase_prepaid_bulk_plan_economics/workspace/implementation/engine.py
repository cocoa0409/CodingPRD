"""Cross-entity cascades: plan sync, cycle book, cycle roll, churn, sweeps.

Every cascade here is derived from scaffold Table 2 side effects and PRD
sections 3.3 - 3.9. Each touched row gets its own updated_at/version refresh.
"""

import calcs
import store
from store import add_days, add_hours, add_months, add_seconds, iso, now, parse_ts, stamp, touch


def agreement_of_plan(plan):
    return store.AGREEMENTS.get(plan["agreement_id"])


def plan_has_terms(plan_id, statuses):
    for term in store.TERMS.values():
        if term["plan_id"] == plan_id and term["term_status"] in statuses:
            return True
    return False


def sync_plan_status(plan):
    """M2: an ACTIVE plan falls back to OFFERED once its last live term leaves."""
    if plan["plan_status"] == "ACTIVE" and not plan_has_terms(plan["id"], calcs.PLAN_BLOCKS_WITHDRAW):
        plan["plan_status"] = "OFFERED"
        touch(plan)
    return plan


def subscriber_accepted_msisdn(subscriber):
    """The number actually live for this subscriber, from their activation row."""
    activations = [a for a in store.ACTIVATIONS.values() if a["subscriber_id"] == subscriber["id"]]
    activations.sort(key=lambda a: (a.get("created_at") or "", a["id"]), reverse=True)
    for activation in activations:
        if activation.get("accepted_msisdn"):
            return activation["accepted_msisdn"]
    for activation in activations:
        if activation.get("provisioned_msisdn"):
            return activation["provisioned_msisdn"]
    return subscriber.get("msisdn")


def void_addons(subscriber):
    """M11 ACTIVE_to_VOIDED: every REQUESTED/ACTIVE add-on is voided at churn."""
    msisdn = subscriber_accepted_msisdn(subscriber)
    for addon in store.ADDONS.values():
        if addon["subscriber_id"] != subscriber["id"]:
            continue
        if addon["addon_status"] in ("REQUESTED", "ACTIVE"):
            addon["addon_status"] = "VOIDED"
            addon["deprovisioned_msisdn"] = msisdn
            addon["addon_price_cents"] = 0
            touch(addon)


def close_cases(subscriber, statuses):
    for case in store.CASES.values():
        if case["subscriber_id"] != subscriber["id"]:
            continue
        if case["case_status"] in statuses:
            case["case_status"] = "CLOSED"
            touch(case)


def escalate_due_cases(subscriber, at_dt):
    """System escalation at a cycle roll whose closed_at is at or after sla_due_at."""
    for case in store.CASES.values():
        if case["subscriber_id"] != subscriber["id"]:
            continue
        if case["case_status"] not in ("OPEN", "ASSIGNED"):
            continue
        due = parse_ts(case.get("sla_due_at"))
        if due is None or at_dt >= due:
            case["case_status"] = "ESCALATED"
            case["escalation_reason"] = "SLA_BREACH"
            case["handling_seconds"] = (case.get("handling_seconds") or 0) + calcs.ESCALATION_SECONDS
            touch(case)
    calcs.refresh_support_counters(subscriber)


def close_resolved_cases(subscriber):
    for case in store.CASES.values():
        if case["subscriber_id"] != subscriber["id"]:
            continue
        if case["case_status"] in ("RESOLVED_SELF_SERVICE", "RESOLVED_AGENT"):
            case["case_status"] = "CLOSED"
            touch(case)


def expire_due_addons(subscriber, at_dt):
    for addon in store.ADDONS.values():
        if addon["subscriber_id"] != subscriber["id"]:
            continue
        if addon["addon_status"] != "ACTIVE":
            continue
        end_at = parse_ts(addon.get("end_at"))
        if end_at is not None and at_dt >= end_at:
            addon["addon_status"] = "EXPIRED"
            addon["addon_price_cents"] = 0
            touch(addon)


def release_reservation(block):
    """Undo a reservation taken by a provisioning call."""
    if block is None:
        return
    if block["inventory_status"] == "RESERVED_PREPAID":
        block["reserved_count"] = max(0, (block.get("reserved_count") or 0) - 1)
        block["reserved_for_activation_id"] = None
        if block["reserved_count"] == 0 and block["units_shipped"] == 0:
            block["inventory_status"] = "AVAILABLE"
        touch(block)


def deliver_due_inventory(at_dt):
    """M8 SHIPPED_to_DELIVERED: the shipment_sla_days window has elapsed."""
    for block in store.INVENTORY.values():
        if block["inventory_status"] != "SHIPPED":
            continue
        sla = block.get("shipment_sla_days")
        if sla is None:
            continue
        shipped_at = parse_ts(block.get("_shipped_at")) or parse_ts(block.get("updated_at"))
        if shipped_at is None:
            continue
        if at_dt >= add_days(shipped_at, sla):
            block["inventory_status"] = "DELIVERED"
            touch(block)


def auto_deflect_partners():
    """M7 ACTIVE_to_DEFLECTED: two or more SHIPPED blocks past their SLA window."""
    at_dt = now()
    for partner in store.PARTNERS.values():
        if partner["partner_status"] != "ACTIVE":
            continue
        late = 0
        for block in store.INVENTORY.values():
            if block.get("retail_partner_id") != partner["id"]:
                continue
            if block["inventory_status"] != "SHIPPED":
                continue
            sla = block.get("shipment_sla_days")
            if sla is None:
                continue
            shipped_at = parse_ts(block.get("_shipped_at"))
            if shipped_at is not None and at_dt >= add_days(shipped_at, sla):
                late += 1
        if late >= 2:
            partner["partner_status"] = "DEFLECTED"
            touch(partner)


def expire_term_with_breakage(term):
    """M4 to EXPIRED: write breakage through early_churn_revenue_recognition."""
    calcs.early_churn_revenue_recognition(term)
    term["term_status"] = "EXPIRED"
    touch(term)
    return term


def open_term_cycles(term, opened_at):
    """Open the term's first cycle (PRD 3.4 / 3.7).

    PRD 3.7 is explicit that completion "opens the term's first cycle", and PRD 3.4
    that "exactly one cycle is `OPEN` at a time" and that the next row is opened at
    the roll: "If the cycle that closed was not the last one, a fresh cycle record
    opens at the next `cycle_index`". Only the open cycle carries `opened_at`.
    """
    months = store.PLANS[term["plan_id"]]["term_months"]
    created = []
    for index in range(1, min(months, 1) + 1):
        row = stamp({
            "prepaid_term_id": term["id"],
            "cycle_index": index,
            "cycle_status": "OPEN",
            "opened_at": iso(opened_at) if index == 1 else None,
            "closed_at": None,
            "cycle_data_used_mb": 0,
            "cycle_deprioritization_days": 0,
            "earned_cents": 0,
        })
        row.pop("updated_at", None)
        row.pop("version", None)
        store.CYCLES[row["id"]] = row
        created.append(row)
    return created


def current_cycle(term, cycle_index):
    """The live row for this ordinal: prefer the newest OPEN row, so a renewed
    term's fresh cycle set is never confused with the previous period's rows."""
    matches = [c for c in store.CYCLES.values()
               if c["prepaid_term_id"] == term["id"] and c["cycle_index"] == cycle_index]
    if not matches:
        return None
    matches.sort(key=lambda c: (c.get("created_at") or "", c["id"]))
    for candidate in reversed(matches):
        if candidate["cycle_status"] == "OPEN":
            return candidate
    return matches[-1]


def cycle_open(endpoint_error=True):
    if endpoint_error:
        from errors import ApiError
        raise ApiError("ERR_CYCLE_ALREADY_ROLLED")


def roll_cycle(subscriber):
    """The full cycle roll cascade (scaffold M9 OPEN_to_ROLLED + endpoint effects)."""
    term = calcs.current_term(subscriber["id"])
    if term is None:
        from errors import ApiError
        raise ApiError("ERR_INVALID_STATE", "subscriber has no open cycle to roll")
    # M3 GRACE_to_CHURNED / M4 GRACE_to_EXPIRED: a subscriber still parked in
    # grace churns automatically at the first cycle roll instead of opening one.
    if subscriber["subscriber_status"] == "GRACE" or term["term_status"] == "GRACE":
        return churn_subscriber(subscriber, expect_term=True)
    plan = store.PLANS[term["plan_id"]]
    agreement = agreement_of_plan(plan)
    index = subscriber.get("cycle_index") or 1
    cycle = current_cycle(term, index)
    if cycle is None or cycle["cycle_status"] != "OPEN":
        from errors import ApiError
        raise ApiError("ERR_CYCLE_ALREADY_ROLLED")

    at_dt = now()
    cycle["cycle_status"] = "ROLLED"
    cycle["closed_at"] = iso(at_dt)
    cycle["cycle_data_used_mb"] = subscriber["data_used_mb_cycle"]
    cycle["cycle_deprioritization_days"] = subscriber["cycle_deprioritization_days"]
    cycle["earned_cents"] = calcs.final_cycle_earned(term, cycle)

    calcs.apply_final_schedule(term)
    touch(term)

    subscriber["cycles_rolled"] = (subscriber.get("cycles_rolled") or 0) + 1
    subscriber["data_used_mb_cycle"] = 0
    subscriber["deprioritized_this_cycle"] = False
    subscriber["cycle_deprioritization_days"] = 0

    months = plan["term_months"]
    if index < months:
        subscriber["cycle_index"] = index + 1
        nxt = current_cycle(term, index + 1)
        if nxt is None:
            # PRD 3.4: "a fresh cycle record opens at the next cycle_index".
            nxt = stamp({
                "prepaid_term_id": term["id"],
                "cycle_index": index + 1,
                "cycle_status": "OPEN",
                "opened_at": iso(at_dt),
                "closed_at": None,
                "cycle_data_used_mb": 0,
                "cycle_deprioritization_days": 0,
                "earned_cents": 0,
            })
            nxt.pop("updated_at", None)
            nxt.pop("version", None)
            store.CYCLES[nxt["id"]] = nxt
        else:
            nxt["opened_at"] = iso(at_dt)
    else:
        term["term_status"] = "RENEWAL_DUE"
        touch(term)
        open_case(subscriber, "RENEWAL_PRICING")
        sub_status = subscriber["subscriber_status"]
        if sub_status == "GRACE":
            churn_subscriber(subscriber, expect_term=True)

    escalate_due_cases(subscriber, at_dt)
    close_resolved_cases(subscriber)
    expire_due_addons(subscriber, at_dt)
    deliver_due_inventory(at_dt)
    auto_deflect_partners()
    sync_plan_status(plan)
    if agreement is not None:
        calcs.settlement_clearing(agreement)
    touch(subscriber)
    return subscriber


def open_case(subscriber, topic_code, at_dt=None):
    at_dt = at_dt or now()
    case = stamp({
        "subscriber_id": subscriber["id"],
        "topic_code": topic_code,
        "case_status": "OPEN",
        "handling_seconds": 0,
        "sla_due_at": iso(add_hours(at_dt, calcs.SLA_HOURS[topic_code])),
        "escalation_reason": None,
    })
    store.CASES[case["id"]] = case
    return case


def churn_subscriber(subscriber, expect_term=True):
    """The wide churn cascade shared by subscriber cancel and GRACE auto-churn."""
    subscriber["subscriber_status"] = "CHURNED"
    subscriber["allocation_status"] = "NONE"
    if expect_term:
        for term in store.TERMS.values():
            if term["subscriber_id"] != subscriber["id"]:
                continue
            if term["term_status"] in ("ACTIVE", "ACTIVE_RENEWAL", "RENEWAL_DUE", "GRACE",
                                       "PURCHASED", "AWAITING_ACTIVATION"):
                expire_term_with_breakage(term)
                sync_plan_status(store.PLANS[term["plan_id"]])
    void_addons(subscriber)
    close_cases(subscriber, ("OPEN", "ASSIGNED", "ESCALATED"))
    for term in store.TERMS.values():
        if term["subscriber_id"] == subscriber["id"]:
            plan = store.PLANS.get(term["plan_id"])
            if plan is not None:
                sync_plan_status(plan)
    touch(subscriber)
    recompute_all_agreements()
    return subscriber


def recompute_all_agreements():
    """Capacity-allocation events recompute every agreement touched by the book."""
    for agreement in store.AGREEMENTS.values():
        calcs.settlement_clearing(agreement)