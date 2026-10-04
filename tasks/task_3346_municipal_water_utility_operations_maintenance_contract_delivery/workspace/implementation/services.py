"""Shared cascades and side effects referenced by more than one workflow."""
from datetime import timedelta

import calc
from core import (ApiError, DB, apply, create, dec, get, iso, now, now_iso,
                  parse_dt, rows, set_status)

# --------------------------------------------------------------------------
# performance standards
# --------------------------------------------------------------------------
def standards_of(contract_id, status=None):
    return [s for s in DB["standards"].values()
            if s["contract_id"] == contract_id and (status is None or s["status"] == status)]


def breached_count(contract_id):
    return len(standards_of(contract_id, "BREACHED"))


def breach_penalty_total(contract_id):
    return sum(int(s.get("breach_penalty_cents") or 0)
               for s in standards_of(contract_id, "BREACHED"))


def recompute_staffing_floor(contract):
    floor = calc.staffing_floor_fte(contract["id"])
    apply(contract, staffing_floor_fte=floor)
    return floor


def recompute_benchmark(municipality):
    apply(municipality, benchmark_index_baseline=calc.benchmark_index(municipality))


def breach_penalty_share(standard):
    contract = DB["contracts"][standard["contract_id"]]
    count = breached_count(contract["id"])
    operator, _ = calc.penalty_shares(standard.get("breach_penalty_cents") or 0,
                                      contract["operator_penalty_share_pct"], count)
    return operator


def add_breach_penalty(standard):
    contract = DB["contracts"][standard["contract_id"]]
    share = breach_penalty_share(standard)
    municipality = DB["municipalities"].get(contract["municipality_id"])
    total = int(contract.get("total_operator_penalty_cents") or 0) + share
    apply(contract, total_operator_penalty_cents=total)
    if municipality is not None:
        tolerance = dec(municipality.get("benchmark_index_baseline") or 0) * 100000
        if dec(total) > tolerance:
            recompute_benchmark(municipality)


def remove_breach_penalty(standard):
    contract = DB["contracts"][standard["contract_id"]]
    share = breach_penalty_share(standard)
    apply(contract, total_operator_penalty_cents=max(
        0, int(contract.get("total_operator_penalty_cents") or 0) - share))


def mark_breached(standard, reason_code):
    set_status(standard, "BREACHED", breach_reason_code=reason_code or "")
    add_breach_penalty(standard)


def mark_cleared(standard):
    remove_breach_penalty(standard)
    set_status(standard, "ACTIVE", breach_reason_code="")
    recompute_staffing_floor(DB["contracts"][standard["contract_id"]])


def latest_measurement(standard_id):
    items = [m for m in DB["measurements"].values() if m["performance_standard_id"] == standard_id]
    if not items:
        return None
    items.sort(key=lambda m: (str(m.get("period_end") or ""), m["created_at"], m["_seq"]))
    return items[-1]


# --------------------------------------------------------------------------
# staffing commitments
# --------------------------------------------------------------------------
def commitments_of(contract_id, status=None):
    return [c for c in DB["staffing"].values()
            if c["contract_id"] == contract_id and (status is None or c["status"] == status)]


def employees_of(contract_id, status=None, role_code=None):
    return [e for e in DB["employees"].values()
            if e["contract_id"] == contract_id
            and (status is None or e["status"] == status)
            and (role_code is None or e["role_code"] == role_code)]


FILLED_STATUSES = ("TRANSFERRED", "INDUCTION", "ACTIVE")


def filled_fte_for(contract_id, role_code):
    total = dec(0)
    for employee in employees_of(contract_id, role_code=role_code):
        if employee["status"] in FILLED_STATUSES:
            total += dec(employee.get("transfer_offer_fte") or 0)
    return float(total)


def refresh_commitment(commitment, demote=True):
    committed = dec(commitment.get("committed_fte") or 0)
    filled = dec(filled_fte_for(commitment["contract_id"], commitment["role_code"]))
    vacancy = committed - filled
    if vacancy < 0:
        vacancy = dec(0)
    apply(commitment, filled_fte=float(filled), vacancy_fte=float(vacancy))
    if demote and commitment["status"] == "BINDING" and filled < committed:
        set_status(commitment, "SHORTFALL")
    return float(filled)


def matching_commitment(contract_id, role_code):
    for commitment in DB["staffing"].values():
        if commitment["contract_id"] == contract_id and commitment["role_code"] == role_code:
            return commitment
    return None


def open_emergency_events(contract_id):
    return [e for e in DB["emergencies"].values()
            if e["contract_id"] == contract_id and e["status"] != "CLOSED"]


def guard_emergency_staffing_floor(contract):
    """PRD 3.3: staffing may not fall below the floor while an emergency is open."""
    if not open_emergency_events(contract["id"]):
        return
    committed = dec(0)
    for commitment in commitments_of(contract["id"]):
        if commitment["status"] in ("BINDING", "REMEDIATING", "SATISFIED"):
            committed += dec(commitment.get("committed_fte") or 0)
    if committed <= dec(contract.get("staffing_floor_fte") or 0):
        raise ApiError("ERR_EMERGENCY_STAFFING_FLOOR")


# --------------------------------------------------------------------------
# assets
# --------------------------------------------------------------------------
def assets_of(contract_id, status=None):
    return [a for a in DB["assets"].values()
            if a["contract_id"] == contract_id and (status is None or a["status"] == status)]


def set_condition(asset, score):
    value = dec(score)
    if value < 0:
        value = dec(0)
    if value > 100:
        value = dec(100)
    apply(asset, condition_score=float(calc.rhu(value, 4)),
          condition_band=calc.condition_band(value))


def flag_asset(asset):
    apply(asset, status="REPLACEMENT_FLAGGED", status_changed_at=now_iso(),
          replacement_flagged_at=now_iso())
    create("work_orders",
           asset_id=asset["id"],
           contract_id=asset["contract_id"],
           work_type="CORRECTIVE",
           expense_class="CAPITAL_LIFE_EVENT",
           estimated_cost_cents=calc.OPERATING_COST_CEILING_CENTS,
           actual_cost_cents=0,
           cost_variance_cents=0,
           documentation_complete=False,
           submitted_to_municipality_at=None,
           status="DRAFT",
           _flagged_capital=True)


def draft_capital_work_order(asset):
    for work_order in DB["work_orders"].values():
        if work_order["asset_id"] == asset["id"] and work_order.get("_flagged_capital") \
                and work_order["status"] != "CANCELLED":
            return work_order
    return None


def baseline_accepted(asset_id):
    """Exactly one accepted assessment under the asset is the frozen baseline."""
    accepted = [a for a in DB["assessments"].values()
                if a["asset_id"] == asset_id and a["status"] == "ACCEPTED"]
    return len(accepted) == 1


# --------------------------------------------------------------------------
# preventive maintenance
# --------------------------------------------------------------------------
def schedules_of(contract_id=None, asset_id=None, status=None):
    out = []
    for schedule in DB["pm_schedules"].values():
        if contract_id is not None and schedule["contract_id"] != contract_id:
            continue
        if asset_id is not None and schedule["asset_id"] != asset_id:
            continue
        if status is not None and schedule["status"] != status:
            continue
        out.append(schedule)
    return out


def live_schedule_statuses():
    return ("ACTIVE", "DUE", "OVERDUE")


def create_pm_work_order(schedule):
    work_order = create("work_orders",
                        asset_id=schedule["asset_id"],
                        contract_id=schedule["contract_id"],
                        work_type="PREVENTIVE",
                        expense_class="OPERATING",
                        estimated_cost_cents=250000,
                        actual_cost_cents=0,
                        cost_variance_cents=0,
                        documentation_complete=False,
                        submitted_to_municipality_at=None,
                        status="SCHEDULED",
                        _pm_schedule_id=schedule["id"])
    asset = DB["assets"].get(schedule["asset_id"])
    if asset is not None:
        apply(work_order, expense_class=calc.expense_class(work_order, asset))
    return work_order


def current_occurrence(schedule):
    occurrences = schedule.get("_occurrences") or []
    return occurrences[-1] if occurrences else None


def evaluate_schedule(schedule):
    """Drive the ACTIVE -> DUE -> OVERDUE transitions against the logical clock."""
    current = now()
    due = parse_dt(schedule.get("next_due_at"))
    if due is None:
        return
    if schedule["status"] == "ACTIVE" and current >= due:
        set_status(schedule, "DUE")
        work_order = create_pm_work_order(schedule)
        schedule.setdefault("_occurrences", []).append({
            "due_at": iso(due),
            "work_order_id": work_order["id"],
            "created_at": now_iso(),
        })
    # The overdue test is driven by the clock against `next_due_at`, not by the
    # schedule's own status: PRD §3.6 re-applies it after each advance, which is how
    # `missed_occurrence_count` can climb past one to the "exactly 3" flagging rule.
    if schedule["status"] in ("DUE", "OVERDUE"):
        window_end = due + timedelta(days=calc.PM_GRACE_DAYS)
        occurrence = current_occurrence(schedule)
        work_order = DB["work_orders"].get(occurrence["work_order_id"]) if occurrence else None
        if current > window_end and (work_order is None or work_order["status"] != "CLOSED"):
            if schedule["status"] != "OVERDUE":
                set_status(schedule, "OVERDUE")
            schedule["missed_occurrence_count"] = int(schedule.get("missed_occurrence_count") or 0) + 1
            schedule["compliance_rate_pct"] = calc.pm_compliance_rate(schedule)
            schedule["next_due_at"] = iso(due + timedelta(days=int(schedule["frequency_days"])))
            if int(schedule["missed_occurrence_count"]) == 3:
                asset = DB["assets"].get(schedule["asset_id"])
                if asset is not None and asset["status"] == "IN_SERVICE":
                    flag_asset(asset)


def advance_schedule(schedule):
    due = parse_dt(schedule.get("next_due_at")) or now()
    schedule["next_due_at"] = iso(due + timedelta(days=int(schedule["frequency_days"])))


# --------------------------------------------------------------------------
# transition obligations
# --------------------------------------------------------------------------
def obligations_of(contract_id, status=None):
    return [o for o in DB["obligations"].values()
            if o["contract_id"] == contract_id and (status is None or o["status"] == status)]


def create_obligation(contract, obligation_type, due_at, is_critical, penalty_per_day_cents,
                      status="PENDING"):
    obligation = create("obligations",
                        contract_id=contract["id"],
                        obligation_type=obligation_type,
                        due_at=iso(due_at),
                        completed_at=None,
                        is_critical=bool(is_critical),
                        penalty_per_day_cents=int(penalty_per_day_cents or 0),
                        outstanding_days=0,
                        withholding_cents=0,
                        status=status)
    refresh_obligation(obligation)
    return obligation


def refresh_obligation(obligation):
    due = parse_dt(obligation.get("due_at"))
    if due is None:
        return
    if obligation["status"] == "DISPUTED":
        return
    days = calc.outstanding_days(due)
    apply(obligation,
          outstanding_days=days,
          withholding_cents=calc.withholding_cents(due, obligation.get("penalty_per_day_cents"),
                                                    obligation["status"]))


def evaluate_obligation(obligation):
    due = parse_dt(obligation.get("due_at"))
    if due is None:
        return
    if obligation["status"] in ("PENDING", "IN_PROGRESS") and now() >= due:
        set_status(obligation, "OVERDUE")
    refresh_obligation(obligation)
    if obligation["status"] == "OVERDUE" and int(obligation.get("outstanding_days") or 0) > 30:
        set_status(obligation, "ESCALATED")
        contract = DB["contracts"].get(obligation["contract_id"])
        if contract is not None and contract["status"] == "HANDING_BACK":
            set_status(contract, "UNDER_REVIEW")


def handback_started_at(contract):
    return parse_dt(contract.get("_handback_started_at")) or parse_dt(contract.get("status_changed_at"))


# --------------------------------------------------------------------------
# permits / allocations
# --------------------------------------------------------------------------
def permits_of(contract_id, status=None):
    return [p for p in DB["permits"].values()
            if p["contract_id"] == contract_id and (status is None or p["status"] == status)]


def allocations_of(contract_id, status=None):
    return [a for a in DB["allocations"].values()
            if a["contract_id"] == contract_id and (status is None or a["status"] == status)]


def active_permit(contract_id):
    permits = permits_of(contract_id, "ACTIVE")
    if not permits:
        return None
    permits.sort(key=lambda p: (p["created_at"], p["_seq"]))
    return permits[0]


def permit_action_unresolved(contract_id):
    return any(p["status"] == "NOTICE_OF_VIOLATION" for p in permits_of(contract_id))


def recompute_allocation(allocation, total_penalty_cents):
    contract = DB["contracts"][allocation["contract_id"]]
    operator, municipality = calc.penalty_shares(
        total_penalty_cents, contract["operator_penalty_share_pct"], breached_count(contract["id"]))
    baseline = calc.state_baseline_share(allocation, total_penalty_cents,
                                         contract["operator_penalty_share_pct"])
    if operator + municipality != int(total_penalty_cents):
        raise ApiError("ERR_PENALTY_ALLOCATION_NOT_CONSERVED")
    return operator, municipality, baseline


# --------------------------------------------------------------------------
# emergency events
# --------------------------------------------------------------------------
def emergencies_of(contract_id=None, asset_id=None, status=None, event_type=None, severity=None):
    out = []
    for event in DB["emergencies"].values():
        if contract_id is not None and event["contract_id"] != contract_id:
            continue
        if asset_id is not None and event["asset_id"] != asset_id:
            continue
        if status is not None and event["status"] != status:
            continue
        if event_type is not None and event["event_type"] != event_type:
            continue
        if severity is not None and event["severity"] != severity:
            continue
        out.append(event)
    return out


def acknowledge(event, action):
    event.setdefault("_acks", [])
    if action not in event["_acks"]:
        event["_acks"].append(action)


def is_critical_notification(event):
    return event["severity"] == "CRITICAL" or event["event_type"] == "CONTAMINATION"


def acknowledgements(event):
    return len(event.get("_acks") or [])


# --------------------------------------------------------------------------
# proposals
# --------------------------------------------------------------------------
def proposals_of(contract_id, status=None):
    return [p for p in DB["proposals"].values()
            if p["contract_id"] == contract_id and (status is None or p["status"] == status)]


def lapse_open_proposals(contract):
    for proposal in proposals_of(contract["id"]):
        if proposal["status"] in ("DRAFTED", "SUBMITTED", "UNDER_REVIEW"):
            set_status(proposal, "LAPSED")


# --------------------------------------------------------------------------
# contracts
# --------------------------------------------------------------------------
def contract_or_404(contract_id):
    return get("contracts", contract_id, "ERR_CONTRACT_NOT_FOUND")


def municipality_of(contract):
    return DB["municipalities"].get(contract["municipality_id"])


def waiver_of_non_critical(contract):
    for obligation in obligations_of(contract["id"]):
        if obligation["status"] in ("PENDING", "IN_PROGRESS"):
            set_status(obligation, "WAIVED", withholding_cents=0)
