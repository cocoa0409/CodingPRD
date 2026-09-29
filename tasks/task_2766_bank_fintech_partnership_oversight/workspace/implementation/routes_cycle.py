"""Oversight cycles, the six-step close, and wind-down plans."""
from flask import Blueprint, g

import calc
import cascade
import respond
import schema
import serialize
import store
from authz import auth, scope_partner_id, scope_rows, sod
from errors import fail
from util import add_days

bp = Blueprint("cycle", __name__)
READ_ROLES = ("ProgramOfficer", "ComplianceOfficer", "RiskCommittee", "InternalAudit",
              "FintechPartner")
LIVE_PLAN_STATUSES = ("DRAFT", "PENDING_APPROVAL", "APPROVED", "IN_EXECUTION")
MIN_WIND_DOWN_NOTICE_DAYS = 30
RECOMPUTED_PARTNER_STATUSES = ("CONTRACTED", "LIVE", "WIND_DOWN")


# --------------------------------------------------------------------------- #
# Oversight cycles
# --------------------------------------------------------------------------- #
@bp.post("/oversight/cycles")
@auth("ProgramOfficer")
def create_cycle():
    data = schema.body()
    label = schema.req_str(data, "cycle_label", 1, 40)                # rank 18
    period_start = schema.req_dt(data, "period_start")
    period_end = schema.req_dt(data, "period_end")
    if period_end <= period_start:                                   # rank 60
        fail("ERR_INVALID_INTERVAL", "period_end must be after period_start")
    for other in store.rows("cycles"):                               # rank 64
        if period_start < other["period_end"] and other["period_start"] < period_end:
            fail("ERR_CYCLE_PERIOD_OVERLAP", "cycle periods may not intersect")
    next_index = 1
    for other in store.DB["cycles"].values():
        next_index = max(next_index, int(other["cycle_index"]) + 1)
    record = {
        "cycle_index": next_index,
        "cycle_label": label,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "closed_at": None,
        "partners_frozen_count": 0,
        "marketing_approvals_expired_count": 0,
        "complaints_escalated_count": 0,
        "alerts_reopened_count": 0,
        "growth_breach_partner_count": 0,
        "plans_completed_count": 0,
    }
    store.insert("cycles", record)
    return respond.ok(serialize.cycle(record), 201)


@bp.get("/oversight/cycles")
@auth(*READ_ROLES)
def list_cycles():
    rows = sorted(store.DB["cycles"].values(), key=lambda r: r["cycle_index"])
    status = schema.filter_enum("status", schema.CYCLE_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return respond.paginate(rows, serialize.cycle)


@bp.get("/oversight/cycles/<cid>")
@auth(*READ_ROLES)
def read_cycle(cid):
    return respond.ok(serialize.cycle(store.must("cycles", cid)))


def _expire_marketing(partner, cycle, only_stale):
    """Move APPROVED marketing reviews to EXPIRED; returns how many expired."""
    expired = 0
    for review in store.rows("marketing_reviews"):
        if review["partner_id"] != partner["id"] or review["status"] != "APPROVED":
            continue
        if only_stale and not (review["effective_until"] is not None
                               and review["effective_until"] < store.clock()):
            continue
        review["status"] = "EXPIRED"
        store.touch(review)
        expired += 1
    return expired


@bp.post("/oversight/cycles/<cid>/close")
@auth("ProgramOfficer")
def close_cycle(cid):
    cycle = store.must("cycles", cid)                                # rank 8
    data = schema.body()
    schema.opt_str(data, "closing_note", None)                       # rank 18
    if cycle["status"] != "OPEN":                                    # rank 34
        fail("ERR_CYCLE_NOT_OPEN", "cycle is not OPEN")
    for other in store.DB["cycles"].values():
        if other["status"] == "CLOSING":
            fail("ERR_CYCLE_NOT_OPEN", "another cycle is already CLOSING")
    if cycle["period_end"] > store.clock():                          # rank 68
        fail("ERR_CYCLE_PERIOD_NOT_ELAPSED", "the cycle period has not elapsed")

    # hop 1: OPEN -> CLOSING
    cycle["status"] = "CLOSING"
    store.touch(cycle)
    now = store.clock()
    counters = {"partners_frozen_count": 0, "marketing_approvals_expired_count": 0,
                "complaints_escalated_count": 0, "alerts_reopened_count": 0,
                "growth_breach_partner_count": 0, "plans_completed_count": 0}

    # step 1 — escalate overdue complaints
    overdue = [c for c in store.rows("complaints")
               if c["status"] in ("RECEIVED", "ROOT_CAUSE_ASSIGNED")
               and c["response_due_at"] is not None and c["response_due_at"] < now]
    overdue.sort(key=lambda c: (c["received_at"], c["created_at"], c["_seq"]))
    for complaint in overdue:
        complaint["escalation_count"] = int(complaint["escalation_count"]) + 1
        complaint["status"] = "ESCALATED"
        store.touch(complaint)
        partner = store.get("partners", complaint["partner_id"])
        if partner is not None:
            partner["open_complaint_count"] = int(partner["open_complaint_count"]) - 1
            partner["escalated_complaint_count"] = \
                int(partner["escalated_complaint_count"]) + 1
            store.touch(partner)
        counters["complaints_escalated_count"] += 1

    # step 2 — reopen SLA-breached alerts
    breached = [a for a in store.rows("alerts")
                if a["disposition"] == "PARTNER_RESPONSE_PENDING"
                and a["sla_due_at"] is not None and a["sla_due_at"] < now]
    breached.sort(key=lambda a: (a["triggered_at"], a["created_at"], a["_seq"]))
    for alert in breached:
        alert["sla_breach_count"] = int(alert["sla_breach_count"]) + 1
        alert["disposition"] = "OPEN"
        store.touch(alert)
        counters["alerts_reopened_count"] += 1

    # step 3 — re-underwrite every live partner
    population = [p for p in store.rows("partners")
                  if p["status"] in RECOMPUTED_PARTNER_STATUSES]
    previous_posture = {}
    for partner in population:
        previous_posture[partner["id"]] = partner["oversight_posture"]
        agreement = calc.governing_agreement(partner["id"])
        partner["systemic_root_cause_code"] = \
            calc.systemic_root_cause_code(partner["id"], cycle)
        cascade.refresh_complaint_rate(partner)
        cap_pct = agreement["monthly_growth_cap_pct"] if agreement else None
        pct, breach = calc.monthly_growth(partner, cycle, cap_pct)
        partner["monthly_growth_pct"] = pct
        if breach:
            partner["growth_breach_count"] = int(partner["growth_breach_count"]) + 1
            counters["growth_breach_partner_count"] += 1
        cascade.refresh_concentration(partner)
        cascade.refresh_reserve(partner)
        if int(partner["reserve_shortfall_cents"]) > 0:
            partner["consecutive_shortfall_cycles"] = \
                int(partner["consecutive_shortfall_cycles"]) + 1
        else:
            partner["consecutive_shortfall_cycles"] = 0
        cascade.refresh_posture(partner)
        store.touch(partner)

    # step 4 — apply the posture consequences
    for partner in population:
        posture = partner["oversight_posture"]
        if posture == "FROZEN":
            for account in store.rows("custody_accounts"):
                if account["partner_id"] == partner["id"] and account["status"] == "ACTIVE":
                    account["status"] = "FROZEN"
                    account["frozen_at"] = now
                    store.touch(account)
            if previous_posture[partner["id"]] != "FROZEN":
                counters["partners_frozen_count"] += 1
        else:
            for account in store.rows("custody_accounts"):
                if account["partner_id"] == partner["id"] and account["status"] == "FROZEN":
                    account["status"] = "ACTIVE"
                    account["frozen_at"] = None
                    store.touch(account)
        if posture in ("RESTRICTED", "FROZEN"):
            counters["marketing_approvals_expired_count"] += \
                _expire_marketing(partner, cycle, False)
        counters["marketing_approvals_expired_count"] += \
            _expire_marketing(partner, cycle, True)

    # step 5 — complete drained wind-down plans
    for plan in store.rows("wind_down_plans"):
        if plan["status"] != "IN_EXECUTION":
            continue
        plan["residual_balance_cents"] = calc.residual_balance(plan["partner_id"])
        if int(plan["residual_balance_cents"]) != 0:
            store.touch(plan)
            continue
        plan["status"] = "COMPLETED"
        plan["completed_at"] = now
        store.touch(plan)
        for account in store.rows("custody_accounts"):
            if account["partner_id"] != plan["partner_id"] or account["status"] == "CLOSED":
                continue
            account["status"] = "CLOSED"
            account["frozen_at"] = None
            store.touch(account)
        partner = store.get("partners", plan["partner_id"])
        if partner is not None and partner["status"] == "WIND_DOWN":
            partner["status"] = "TERMINATED"
            store.touch(partner)
        counters["plans_completed_count"] += 1

    # step 6 — write the ledger of the close
    for key, value in counters.items():
        cycle[key] = value
    cycle["closed_at"] = now
    cycle["status"] = "CLOSED"
    store.touch(cycle)
    return respond.ok(serialize.cycle(cycle))


# --------------------------------------------------------------------------- #
# Wind-down plans
# --------------------------------------------------------------------------- #
def _require_wind_down(partner):
    if partner["status"] != "WIND_DOWN":                             # rank 42
        fail("ERR_PARTNER_NOT_IN_WIND_DOWN", "partner is not in WIND_DOWN")


def _require_milestones(milestones):
    if "RETURN_FUNDS" not in milestones or "CLOSE_CUSTODY" not in milestones:
        fail("ERR_VALIDATION",
             "milestones must contain RETURN_FUNDS and CLOSE_CUSTODY")


@bp.post("/oversight/wind-down-plans")
@auth("ProgramOfficer")
def create_plan():
    data = schema.body()
    partner = None
    if data.get("partner_id") is not None:                           # rank 10
        partner = store.must("partners", data["partner_id"])
    schema.req_str(data, "partner_id")                               # rank 18
    trigger = schema.req_enum(data, "trigger_reason", schema.TERMINATION_TRIGGERS)
    disposition = schema.req_enum(data, "end_user_funds_disposition",
                                  schema.FUNDS_DISPOSITIONS)
    notice_days = schema.req_int(data, "notice_days", 1, 180)
    target = schema.req_dt(data, "target_completion_date")
    milestones = schema.req_enum_array(data, "milestones", schema.MILESTONES)
    _require_milestones(milestones)
    if partner["status"] in ("DILIGENCE_FAILED", "TERMINATED"):       # rank 32
        fail("ERR_PARTNER_TERMINAL", "partner is terminal")
    _require_wind_down(partner)                                      # rank 42
    agreement = calc.governing_agreement(partner["id"])
    contracted = list(agreement["termination_triggers"]) if agreement else []
    if trigger not in contracted:                                    # rank 59
        fail("ERR_TERMINATION_TRIGGER_NOT_CONTRACTED",
             "trigger_reason is not a contracted termination trigger")
    created_at = store.clock()
    if notice_days < MIN_WIND_DOWN_NOTICE_DAYS or \
            target < add_days(created_at, notice_days):              # rank 69
        fail("ERR_WIND_DOWN_NOTICE_NOT_ELAPSED", "the notice period is not real")
    for other in store.rows("wind_down_plans"):                      # rank 72
        if other["partner_id"] == partner["id"] and \
                other["status"] in LIVE_PLAN_STATUSES:
            fail("ERR_PLAN_ALREADY_OPEN", "a wind-down plan is already live")
    record = {
        "partner_id": partner["id"],
        "trigger_reason": trigger,
        "end_user_funds_disposition": disposition,
        "notice_days": notice_days,
        "target_completion_date": target,
        "milestones": milestones,
        "status": "DRAFT",
        "revision_round": 1,
        "residual_balance_cents": calc.residual_balance(partner["id"]),
        "approved_by_user_id": None,
        "completed_at": None,
        "created_by_user_id": g.user_id,
    }
    store.insert("wind_down_plans", record)
    return respond.ok(serialize.wind_down_plan(record), 201)


@bp.get("/oversight/wind-down-plans")
@auth(*READ_ROLES)
def list_plans():
    rows = store.rows("wind_down_plans")
    partner_id = schema.filter_str("partner_id")
    if partner_id is not None:
        rows = [r for r in rows if r["partner_id"] == partner_id]
    status = schema.filter_enum("status", schema.PLAN_STATUSES)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    for row in rows:
        row["residual_balance_cents"] = calc.residual_balance(row["partner_id"])
    return respond.paginate(scope_rows(rows), serialize.wind_down_plan)


@bp.get("/oversight/wind-down-plans/<pid>")
@auth(*READ_ROLES)
def read_plan(pid):
    plan = store.must("wind_down_plans", pid)
    scope_partner_id(plan["partner_id"])
    plan["residual_balance_cents"] = calc.residual_balance(plan["partner_id"])
    return respond.ok(serialize.wind_down_plan(plan))


@bp.post("/oversight/wind-down-plans/<pid>/submit")
@auth("ProgramOfficer")
def submit_plan(pid):
    plan = store.must("wind_down_plans", pid)                        # rank 8
    data = schema.body()
    schema.opt_str(data, "submission_note", None)                     # rank 18
    if plan["status"] != "DRAFT":                                    # rank 34
        fail("ERR_PLAN_NOT_DRAFT", "plan is not DRAFT")
    partner = store.get("partners", plan["partner_id"])
    _require_wind_down(partner)                                      # rank 42
    _require_milestones(plan["milestones"])
    plan["status"] = "PENDING_APPROVAL"
    plan["residual_balance_cents"] = calc.residual_balance(plan["partner_id"])
    store.touch(plan)
    return respond.ok(serialize.wind_down_plan(plan))


@bp.post("/oversight/wind-down-plans/<pid>/decide")
@auth("RiskCommittee")
def decide_plan(pid):
    plan = store.must("wind_down_plans", pid)                        # rank 8
    sod(plan["created_by_user_id"])                                  # rank 14
    data = schema.body()
    decision = schema.req_enum(data, "decision", ("APPROVE", "REVISE"))   # rank 18
    schema.opt_str(data, "decision_note", None)
    if plan["status"] != "PENDING_APPROVAL":                         # rank 34
        fail("ERR_PLAN_NOT_PENDING_APPROVAL", "plan is not PENDING_APPROVAL")
    partner = store.get("partners", plan["partner_id"])
    _require_wind_down(partner)                                      # rank 42
    if decision == "APPROVE":
        if int(plan["notice_days"]) < MIN_WIND_DOWN_NOTICE_DAYS:      # rank 69
            fail("ERR_WIND_DOWN_NOTICE_NOT_ELAPSED", "notice_days is below the minimum")
        plan["status"] = "APPROVED"
        plan["approved_by_user_id"] = g.user_id
    else:
        plan["status"] = "DRAFT"
        plan["revision_round"] = int(plan["revision_round"]) + 1
    plan["residual_balance_cents"] = calc.residual_balance(plan["partner_id"])
    store.touch(plan)
    return respond.ok(serialize.wind_down_plan(plan))


@bp.post("/oversight/wind-down-plans/<pid>/execute")
@auth("ProgramOfficer")
def execute_plan(pid):
    plan = store.must("wind_down_plans", pid)                        # rank 8
    data = schema.body()
    schema.opt_str(data, "execution_note", None)                      # rank 18
    if plan["status"] != "APPROVED":                                 # rank 34
        fail("ERR_PLAN_NOT_APPROVED", "plan is not APPROVED")
    partner = store.get("partners", plan["partner_id"])
    _require_wind_down(partner)                                      # rank 42
    for batch in store.rows("settlement_batches"):                   # rank 44
        if batch["partner_id"] != plan["partner_id"]:
            continue
        if batch["funding_status"] == "UNFUNDED" or \
                batch["reconciliation_status"] in ("UNRECONCILED", "VARIANCE_OPEN"):
            fail("ERR_UNSETTLED_BATCHES_OUTSTANDING", "a settlement batch is outstanding")
    if store.clock() < add_days(plan["created_at"], int(plan["notice_days"])):  # rank 69
        fail("ERR_WIND_DOWN_NOTICE_NOT_ELAPSED", "the notice period has not elapsed")
    plan["status"] = "IN_EXECUTION"
    plan["residual_balance_cents"] = calc.residual_balance(plan["partner_id"])
    store.touch(plan)
    return respond.ok(serialize.wind_down_plan(plan))
