"""Routes: go-live events, support transitions, tickets, maintenance agreements."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_GO_LIVE_IN_BLACKOUT, ERR_GO_LIVE_DATE_MISMATCH, ERR_GO_LIVE_PREREQUISITE,
    ERR_GO_LIVE_EXISTS, ERR_READINESS_TOO_LOW, ERR_COVERAGE_GAP, ERR_STALE_VERSION,
)
from middleware import require_roles
from response import success_object, success_list, parse_pagination, paginate
from routes_contracts import get_contract_or_404
from services_common import (
    strip_internal, append_audit, compute_readiness_score,
    recompute_transition_counters, maybe_lapse_agreement,
)
from util import (
    new_id, now_ts, touch, require_fields, require_int, parse_date, get_clock_date,
)

bp = Blueprint("golive_support", __name__)

READINESS_THRESHOLD = 80
WARRANTY_DAYS = 90
ROLLBACK_WINDOW_DAYS = 14
ESCALATOR_PCT = 3
SLA_DAYS = {"SEV1": 1, "SEV2": 5, "SEV3": 20}
SLA_BREACH_ALLOWANCE = 2


def get_event_or_404(eid):
    e = db.get("go_live_events", eid)
    if e is None:
        raise_error(ERR_NOT_FOUND, "go-live event not found")
    return e


def get_transition_or_404(tid):
    t = db.get("support_transitions", tid)
    if t is None:
        raise_error(ERR_NOT_FOUND, "support transition not found")
    return t


def get_agreement_or_404(aid):
    a = db.get("maintenance_agreements", aid)
    if a is None:
        raise_error(ERR_NOT_FOUND, "maintenance agreement not found")
    return maybe_lapse_agreement(a)


def _check_blackout(contract, planned_date):
    agency = db.get("agencies", contract["agency_id"])
    if agency is None:
        return
    d = parse_date(planned_date, "planned_date")
    for w in db.filter_items("calendar_windows", agency_id=agency["id"]):
        if not w.get("blackout"):
            continue
        if parse_date(w["starts_on"]) <= d <= parse_date(w["ends_on"]):
            raise_error(ERR_GO_LIVE_IN_BLACKOUT, "planned_date inside blackout window")


@bp.route("/programs/contracts/<contract_id>/go-live-events", methods=["POST"])
def create_go_live(contract_id):
    require_roles("ImplementationManager")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["planned_date"])
    parse_date(payload["planned_date"], "planned_date")
    for ev in db.filter_items("go_live_events", contract_id=c["id"]):
        if ev["status"] != "CANCELLED":
            raise_error(ERR_GO_LIVE_EXISTS, "contract already has a non-CANCELLED go-live event")
    _check_blackout(c, payload["planned_date"])
    now = now_ts()
    event = {
        "id": new_id(),
        "contract_id": c["id"],
        "planned_date": payload["planned_date"],
        "status": "PROPOSED",
        "readiness_score": 0,
        "readiness_notes": "",
        "executed_at": None,
        "rolled_back_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("go_live_events", event)
    return success_object(strip_internal(event), 201)


@bp.route("/programs/contracts/<contract_id>/go-live-events", methods=["GET"])
def list_go_lives(contract_id):
    require_roles("ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("go_live_events", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(e) for e in page], limit, offset, total)


@bp.route("/programs/go-live-events/<eid>", methods=["GET"])
def get_go_live(eid):
    require_roles("ImplementationManager", "AgencyProjectManager", "PlatformAdmin", "SupportManager")
    return success_object(strip_internal(get_event_or_404(eid)), 200)


@bp.route("/programs/go-live-events/<eid>/readiness-check", methods=["POST"])
def readiness_check(eid):
    require_roles("ImplementationManager")
    ev = get_event_or_404(eid)
    if ev["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "event not PROPOSED")
    c = get_contract_or_404(ev["contract_id"])
    _check_blackout(c, ev["planned_date"])
    ev["readiness_score"] = compute_readiness_score(ev["contract_id"])
    ev["status"] = "READINESS_CHECKED"
    touch(ev)
    return success_object(strip_internal(ev), 200)


@bp.route("/programs/go-live-events/<eid>/approve", methods=["POST"])
def approve_go_live(eid):
    user_id, role = require_roles("AgencyProjectManager")
    ev = get_event_or_404(eid)
    if ev["status"] != "READINESS_CHECKED":
        raise_error(ERR_INVALID_STATE, "event not READINESS_CHECKED")
    if ev["readiness_score"] < READINESS_THRESHOLD:
        raise_error(ERR_READINESS_TOO_LOW, "readiness_score below threshold")
    c = get_contract_or_404(ev["contract_id"])
    if c["status"] != "IMPLEMENTATION":
        raise_error(ERR_INVALID_STATE, "contract not IMPLEMENTATION")
    ev["status"] = "APPROVED"
    touch(ev)
    append_audit(ev["contract_id"], role, user_id, "POST /programs/go-live-events/{id}/approve",
                 "GoLiveEvent", ev["id"], "READINESS_CHECKED -> APPROVED")
    return success_object(strip_internal(ev), 200)


@bp.route("/programs/go-live-events/<eid>/revise", methods=["POST"])
def revise_go_live(eid):
    require_roles("ImplementationManager")
    ev = get_event_or_404(eid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["planned_date"])
    if ev["status"] != "READINESS_CHECKED":
        raise_error(ERR_INVALID_STATE, "event not READINESS_CHECKED")
    parse_date(payload["planned_date"], "planned_date")
    ev["planned_date"] = payload["planned_date"]
    ev["status"] = "PROPOSED"
    touch(ev)
    return success_object(strip_internal(ev), 200)


@bp.route("/programs/go-live-events/<eid>/execute", methods=["POST"])
def execute_go_live(eid):
    user_id, role = require_roles("ImplementationManager")
    ev = get_event_or_404(eid)
    if ev["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "event not APPROVED")
    today = get_clock_date()
    planned = parse_date(ev["planned_date"], "planned_date")
    if today != planned:
        raise_error(ERR_GO_LIVE_DATE_MISMATCH, "clock date must equal planned_date")
    for other in db.filter_items("go_live_events", contract_id=ev["contract_id"]):
        if other["id"] != ev["id"] and other["status"] == "EXECUTED":
            raise_error(ERR_INVALID_STATE, "another go-live event already EXECUTED")
    for b in db.filter_items("migration_batches", contract_id=ev["contract_id"]):
        if b["status"] != "ACCEPTED":
            raise_error(ERR_GO_LIVE_PREREQUISITE, "migration batch not ACCEPTED")
    for i in db.filter_items("interfaces", contract_id=ev["contract_id"]):
        if i["status"] != "CERTIFIED":
            raise_error(ERR_GO_LIVE_PREREQUISITE, "interface not CERTIFIED")
    ev["status"] = "EXECUTED"
    ev["executed_at"] = now_ts()
    touch(ev)
    # cascade 1: create SupportTransition
    warranty_end = planned + timedelta(days=WARRANTY_DAYS)
    now = now_ts()
    transition = {
        "id": new_id(),
        "contract_id": ev["contract_id"],
        "warranty_end_on": warranty_end.isoformat(),
        "status": "WARRANTY",
        "open_sev1_count": 0,
        "total_tickets": 0,
        "sla_breach_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("support_transitions", transition)
    # cascade 2: release retainage on RETAINAGE_HELD milestones
    for m in db.filter_items("milestones", contract_id=ev["contract_id"]):
        if m.get("billing_variant") == "RETAINAGE_HELD" and "retained_cents" in m:
            m["payable_cents"] = m["billable_amount_cents"]
            m["retained_released"] = True
            touch(m)
    append_audit(ev["contract_id"], role, user_id, "POST /programs/go-live-events/{id}/execute",
                 "GoLiveEvent", ev["id"], "APPROVED -> EXECUTED")
    return success_object(strip_internal(ev), 200)


@bp.route("/programs/go-live-events/<eid>/rollback", methods=["POST"])
def rollback_go_live(eid):
    user_id, role = require_roles("ImplementationManager")
    ev = get_event_or_404(eid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["rollback_reason"])
    if ev["status"] != "EXECUTED":
        raise_error(ERR_INVALID_STATE, "event not EXECUTED")
    today = get_clock_date()
    planned = parse_date(ev["planned_date"], "planned_date")
    if today > planned + timedelta(days=ROLLBACK_WINDOW_DAYS):
        raise_error(ERR_GO_LIVE_DATE_MISMATCH, "rollback window elapsed")
    ev["status"] = "ROLLED_BACK"
    ev["rolled_back_at"] = now_ts()
    touch(ev)
    append_audit(ev["contract_id"], role, user_id, "POST /programs/go-live-events/{id}/rollback",
                 "GoLiveEvent", ev["id"], "EXECUTED -> ROLLED_BACK")
    return success_object(strip_internal(ev), 200)


@bp.route("/programs/go-live-events/<eid>/replan", methods=["POST"])
def replan_go_live(eid):
    require_roles("ImplementationManager")
    ev = get_event_or_404(eid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["planned_date"])
    if ev["status"] != "ROLLED_BACK":
        raise_error(ERR_INVALID_STATE, "event not ROLLED_BACK")
    new_date = parse_date(payload["planned_date"], "planned_date")
    if new_date <= get_clock_date():
        raise_error(ERR_INVALID_REQUEST, "planned_date must be strictly after current clock date")
    ev["planned_date"] = payload["planned_date"]
    ev["status"] = "PROPOSED"
    touch(ev)
    return success_object(strip_internal(ev), 200)


@bp.route("/programs/go-live-events/<eid>/cancel", methods=["POST"])
def cancel_go_live(eid):
    require_roles("ImplementationManager")
    ev = get_event_or_404(eid)
    if ev["status"] != "PROPOSED":
        raise_error(ERR_INVALID_STATE, "event not PROPOSED")
    ev["status"] = "CANCELLED"
    touch(ev)
    return success_object(strip_internal(ev), 200)


# ---------------- support transitions & tickets ----------------

@bp.route("/programs/contracts/<contract_id>/support-transitions", methods=["GET"])
def list_transitions(contract_id):
    require_roles("SupportManager", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("support_transitions", contract_id=c["id"])
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(t) for t in page], limit, offset, total)


@bp.route("/programs/support-transitions/<tid>", methods=["GET"])
def get_transition(tid):
    require_roles("SupportManager", "ImplementationManager", "AgencyProjectManager", "PlatformAdmin")
    return success_object(strip_internal(get_transition_or_404(tid)), 200)


@bp.route("/programs/support-transitions/<tid>/advance", methods=["POST"])
def advance_transition(tid):
    user_id, role = require_roles("SupportManager")
    t = get_transition_or_404(tid)
    if t["status"] == "WARRANTY":
        # open tickets past SLA count as breached when the transition advances
        today = get_clock_date()
        for ticket in db.filter_items("support_tickets", support_transition_id=t["id"]):
            if ticket.get("resolution") is None and not ticket.get("breached_sla"):
                raised = parse_date(ticket["raised_on"], "raised_on")
                if (today - raised).days > SLA_DAYS[ticket["severity"]]:
                    ticket["breached_sla"] = True
        recompute_transition_counters(t)
        if get_clock_date() <= parse_date(t["warranty_end_on"], "warranty_end_on"):
            raise_error(ERR_INVALID_STATE, "warranty period not ended")
        if t["open_sev1_count"] != 0:
            raise_error(ERR_INVALID_STATE, "open SEV1 tickets remain")
        t["status"] = "STABILIZATION"
    elif t["status"] == "STABILIZATION":
        recompute_transition_counters(t)
        if t["open_sev1_count"] != 0:
            raise_error(ERR_INVALID_STATE, "open SEV1 tickets remain")
        if t["sla_breach_count"] > SLA_BREACH_ALLOWANCE:
            raise_error(ERR_INVALID_STATE, "too many SLA breaches")
        t["status"] = "STEADY_STATE"
    else:
        raise_error(ERR_INVALID_STATE, "transition cannot advance")
    touch(t)
    append_audit(t["contract_id"], role, user_id, "POST /programs/support-transitions/{id}/advance",
                 "SupportTransition", t["id"], f"-> {t['status']}")
    return success_object(strip_internal(t), 200)


@bp.route("/programs/support-transitions/<tid>/sunset", methods=["POST"])
def sunset_transition(tid):
    require_roles("SupportManager")
    t = get_transition_or_404(tid)
    if t["status"] != "STEADY_STATE":
        raise_error(ERR_INVALID_STATE, "transition not STEADY_STATE")
    c = get_contract_or_404(t["contract_id"])
    if c["status"] != "CLOSED":
        raise_error(ERR_INVALID_STATE, "contract not CLOSED")
    t["status"] = "SUNSET"
    touch(t)
    return success_object(strip_internal(t), 200)


@bp.route("/programs/support-transitions/<tid>/tickets", methods=["POST"])
def create_ticket(tid):
    require_roles("SupportManager", "AgencyProjectManager")
    t = get_transition_or_404(tid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["severity", "summary"])
    if payload["severity"] not in SLA_DAYS:
        raise_error(ERR_INVALID_REQUEST, "invalid severity")
    now = now_ts()
    ticket = {
        "id": new_id(),
        "support_transition_id": t["id"],
        "severity": payload["severity"],
        "summary": payload["summary"],
        "raised_on": get_clock_date().isoformat(),
        "resolution": None,
        "resolved_on": None,
        "breached_sla": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("support_tickets", ticket)
    recompute_transition_counters(t)
    return success_object(strip_internal(ticket), 201)


@bp.route("/programs/support-transitions/<tid>/tickets", methods=["GET"])
def list_tickets(tid):
    require_roles("SupportManager", "AgencyProjectManager", "PlatformAdmin")
    t = get_transition_or_404(tid)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("support_tickets", support_transition_id=t["id"])
    severity = request.args.get("severity")
    if severity is not None:
        items = [x for x in items if x["severity"] == severity]
    resolution = request.args.get("resolution")
    if resolution is not None:
        items = [x for x in items if x.get("resolution") == resolution]
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(x) for x in page], limit, offset, total)


@bp.route("/programs/support-tickets/<tid>/resolve", methods=["POST"])
def resolve_ticket(tid):
    require_roles("SupportManager")
    ticket = db.get("support_tickets", tid)
    if ticket is None:
        raise_error(ERR_NOT_FOUND, "ticket not found")
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["resolution"])
    resolution = payload["resolution"]
    if resolution not in ("RESOLVED", "WORKAROUND", "DEFERRED", "DUPLICATE"):
        raise_error(ERR_INVALID_REQUEST, "invalid resolution")
    if ticket.get("resolution") is not None:
        raise_error(ERR_INVALID_STATE, "ticket already resolved")
    ticket["resolution"] = resolution
    resolved = get_clock_date()
    ticket["resolved_on"] = resolved.isoformat()
    raised = parse_date(ticket["raised_on"], "raised_on")
    ticket["breached_sla"] = (resolved - raised).days > SLA_DAYS[ticket["severity"]]
    touch(ticket)
    transition = get_transition_or_404(ticket["support_transition_id"])
    recompute_transition_counters(transition)
    return success_object(strip_internal(ticket), 200)


# ---------------- maintenance agreements ----------------

def _escalated_fee(annual_fee_cents, renewal_index):
    if renewal_index == 0:
        return annual_fee_cents
    factor = (Decimal(1) + Decimal(ESCALATOR_PCT) / Decimal(100)) ** renewal_index
    return int((Decimal(annual_fee_cents) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


@bp.route("/programs/contracts/<contract_id>/maintenance-agreements", methods=["POST"])
def create_agreement(contract_id):
    require_roles("FinanceOfficer")
    c = get_contract_or_404(contract_id)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["annual_fee_cents", "coverage_start_on"])
    fee = require_int(payload, "annual_fee_cents")
    parse_date(payload["coverage_start_on"], "coverage_start_on")
    now = now_ts()
    agreement = {
        "id": new_id(),
        "contract_id": c["id"],
        "annual_fee_cents": fee,
        "coverage_start_on": payload["coverage_start_on"],
        "status": "DRAFT",
        "renewal_index": 0,
        "escalated_fee_cents": fee,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("maintenance_agreements", agreement)
    return success_object(strip_internal(agreement), 201)


@bp.route("/programs/contracts/<contract_id>/maintenance-agreements", methods=["GET"])
def list_agreements(contract_id):
    require_roles("FinanceOfficer", "ImplementationManager", "PlatformAdmin")
    c = get_contract_or_404(contract_id)
    limit, offset = parse_pagination(request.args)
    items = db.filter_items("maintenance_agreements", contract_id=c["id"])
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if maybe_lapse_agreement(a)["status"] == status]
    else:
        for a in items:
            maybe_lapse_agreement(a)
    page, total = paginate(items, limit, offset)
    return success_list([strip_internal(a) for a in page], limit, offset, total)


@bp.route("/programs/maintenance-agreements/<aid>", methods=["GET"])
def get_agreement(aid):
    require_roles("FinanceOfficer", "ImplementationManager", "PlatformAdmin")
    return success_object(strip_internal(get_agreement_or_404(aid)), 200)


@bp.route("/programs/maintenance-agreements/<aid>/activate", methods=["POST"])
def activate_agreement(aid):
    user_id, role = require_roles("FinanceOfficer")
    a = get_agreement_or_404(aid)
    if a["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "agreement not DRAFT")
    transitions = db.filter_items("support_transitions", contract_id=a["contract_id"])
    if not transitions or transitions[0]["status"] != "STEADY_STATE":
        raise_error(ERR_INVALID_STATE, "support transition not STEADY_STATE")
    warranty_end = parse_date(transitions[0]["warranty_end_on"], "warranty_end_on")
    coverage_start = parse_date(a["coverage_start_on"], "coverage_start_on")
    if coverage_start != warranty_end + timedelta(days=1):
        raise_error(ERR_COVERAGE_GAP, "coverage_start_on must be warranty_end_on + 1 day")
    for ev in db.filter_items("go_live_events", contract_id=a["contract_id"]):
        if ev["status"] == "ROLLED_BACK":
            raise_error(ERR_INVALID_STATE, "go-live event rolled back")
    a["status"] = "ACTIVE"
    a["escalated_fee_cents"] = _escalated_fee(a["annual_fee_cents"], a["renewal_index"])
    touch(a)
    append_audit(a["contract_id"], role, user_id,
                 "POST /programs/maintenance-agreements/{id}/activate",
                 "MaintenanceAgreement", a["id"], "DRAFT -> ACTIVE")
    return success_object(strip_internal(a), 200)


@bp.route("/programs/maintenance-agreements/<aid>/renew", methods=["POST"])
def renew_agreement(aid):
    user_id, role = require_roles("FinanceOfficer")
    a = get_agreement_or_404(aid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["expected_agreement_version"])
    expected = require_int(payload, "expected_agreement_version")
    if a["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "agreement not ACTIVE")
    if expected != a["version"]:
        raise_error(ERR_STALE_VERSION, "stale agreement version")
    # successor
    successor_index = a["renewal_index"] + 1
    now = now_ts()
    successor = {
        "id": new_id(),
        "contract_id": a["contract_id"],
        "annual_fee_cents": a["annual_fee_cents"],
        "coverage_start_on": a["coverage_start_on"],
        "status": "DRAFT",
        "renewal_index": successor_index,
        "escalated_fee_cents": _escalated_fee(a["annual_fee_cents"], successor_index),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.put("maintenance_agreements", successor)
    a["status"] = "RENEWED"
    touch(a)
    append_audit(a["contract_id"], role, user_id,
                 "POST /programs/maintenance-agreements/{id}/renew",
                 "MaintenanceAgreement", a["id"], "ACTIVE -> RENEWED")
    return success_object(strip_internal(a), 200)


@bp.route("/programs/maintenance-agreements/<aid>/suspend", methods=["POST"])
def suspend_agreement(aid):
    require_roles("FinanceOfficer")
    a = get_agreement_or_404(aid)
    if a["status"] == "ACTIVE":
        a["status"] = "SUSPENDED"
    elif a["status"] == "SUSPENDED":
        a["status"] = "ACTIVE"
    else:
        raise_error(ERR_INVALID_STATE, "agreement not ACTIVE or SUSPENDED")
    touch(a)
    return success_object(strip_internal(a), 200)
