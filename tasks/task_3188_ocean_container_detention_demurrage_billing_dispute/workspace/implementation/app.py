"""Flask app entry point: routes, error handlers."""
import os
import sys
from datetime import datetime, timedelta, timezone

from flask import Flask, request

# Ensure local package imports work when run as `python3 app.py`
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import db, now_utc, iso_utc
from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN, ERR_NOT_FOUND,
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_ACCOUNT_NOT_ACTIVE,
    ERR_ACCOUNT_CREDIT_HOLD, ERR_ACCOUNT_BALANCE_OUTSTANDING,
    ERR_ACCOUNT_CONTAINERS_ACTIVE, ERR_CONTRACT_NOT_IN_EFFECT,
    ERR_CONTAINER_HELD, ERR_APPOINTMENT_REQUIRED, ERR_SLOT_RELEASED,
    ERR_NOT_A_WORKING_DAY, ERR_CAPACITY_OR_CONFLICT, ERR_NO_RETURN_LOCATION,
    ERR_RETURN_LOCATION_CLOSED, ERR_RETURN_LOCATION_RESTRICTED,
    ERR_REFERENTIAL_GUARD, ERR_DISPUTE_ALREADY_OPEN, ERR_EVIDENCE_REQUIRED,
    ERR_JUSTIFICATION_REQUIRED, ERR_RESOLVED_AMOUNT_INVALID,
    ERR_WAIVER_AUTHORITY_EXCEEDED, ERR_SEGREGATION_OF_DUTIES,
    ERR_CREDIT_EXCEEDS_BALANCE, ERR_PAYMENT_EXCEEDS_BALANCE,
    ERR_INVOICE_NOT_AGED_ENOUGH, ERR_INVOICE_ALREADY_SETTLED,
    ERR_REVERSAL_EXCEEDS_NET, ERR_STALE_VERSION,
)
from middleware import get_auth, require_roles
from response import success_object, success_list, error_response
import services as S

app = Flask(__name__)


@app.errorhandler(ApiError)
def _api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _not_found(e):
    return error_response(ERR_NOT_FOUND, 404, "Resource not found")


@app.errorhandler(405)
def _method_not_allowed(e):
    return error_response(ERR_NOT_FOUND, 404, "Method not allowed")


@app.errorhandler(Exception)
def _unhandled(e):
    import traceback
    traceback.print_exc()
    return error_response(ERR_INVALID_REQUEST, 400, f"Unhandled: {e}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _payload():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def _get_account(account_id):
    a = db.accounts.get(account_id)
    if not a:
        raise ApiError(ERR_NOT_FOUND, 404, f"Account {account_id} not found")
    return a


def _get_contract(contract_id):
    c = db.contracts.get(contract_id)
    if not c:
        raise ApiError(ERR_NOT_FOUND, 404, f"Contract {contract_id} not found")
    return c


def _get_terminal(tid):
    t = db.terminals.get(tid)
    if not t:
        raise ApiError(ERR_NOT_FOUND, 404, f"Terminal {tid} not found")
    return t


def _get_slot(sid):
    s = db.slots.get(sid)
    if not s:
        raise ApiError(ERR_NOT_FOUND, 404, f"Slot {sid} not found")
    return s


def _get_location(lid):
    loc = db.locations.get(lid)
    if not loc:
        raise ApiError(ERR_NOT_FOUND, 404, f"Location {lid} not found")
    return loc


def _get_container(cid):
    c = db.containers.get(cid)
    if not c:
        raise ApiError(ERR_NOT_FOUND, 404, f"Container {cid} not found")
    return c


def _get_invoice(iid):
    inv = db.invoices.get(iid)
    if not inv:
        raise ApiError(ERR_NOT_FOUND, 404, f"Invoice {iid} not found")
    return inv


def _get_dispute(did):
    d = db.disputes.get(did)
    if not d:
        raise ApiError(ERR_NOT_FOUND, 404, f"Dispute {did} not found")
    return d


def _get_evidence(eid):
    ev = db.evidence.get(eid)
    if not ev:
        raise ApiError(ERR_NOT_FOUND, 404, f"Evidence {eid} not found")
    return ev


def _get_waiver(wid):
    w = db.waivers.get(wid)
    if not w:
        raise ApiError(ERR_NOT_FOUND, 404, f"Waiver {wid} not found")
    return w


def _get_booking(bid):
    b = db.bookings.get(bid)
    if not b:
        raise ApiError(ERR_NOT_FOUND, 404, f"Booking {bid} not found")
    return b


def _check_rep_owns_account(user_id, role, account_id):
    if role == "CustomerRep" and user_id != account_id:
        raise ApiError(ERR_FORBIDDEN, 403, "CustomerRep may only act on own account's resources")


# ---------------------------------------------------------------------------
# Serializers (public view of entities)
# ---------------------------------------------------------------------------

def ser_account(a):
    return {
        "id": a["id"],
        "account_code": a["account_code"],
        "legal_name": a["legal_name"],
        "credit_hold": a["credit_hold"],
        "outstanding_balance_cents": a["outstanding_balance_cents"],
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def ser_contract(c):
    return {
        "id": c["id"],
        "customer_account_id": c["customer_account_id"],
        "contract_ref": c["contract_ref"],
        "demurrage_free_days": c["demurrage_free_days"],
        "detention_free_days": c["detention_free_days"],
        "saturday_counts_as_free_day": c["saturday_counts_as_free_day"],
        "demurrage_rate_schedule": c["demurrage_rate_schedule"],
        "detention_rate_schedule": c["detention_rate_schedule"],
        "effective_from": iso_utc(c["effective_from"]),
        "effective_to": iso_utc(c["effective_to"]),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_terminal(t):
    return {
        "id": t["id"],
        "terminal_code": t["terminal_code"],
        "timezone": t["timezone"],
        "daily_appointment_capacity": t["daily_appointment_capacity"],
        "gate_closed_weekends": t["gate_closed_weekends"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def ser_holiday(h):
    return {
        "id": h["id"],
        "terminal_id": h["terminal_id"],
        "holiday_date": iso_utc(h["holiday_date"]),
        "name": h["name"],
        "created_at": h["created_at"],
    }


def ser_slot(s):
    return {
        "id": s["id"],
        "terminal_id": s["terminal_id"],
        "slot_date": iso_utc(s["slot_date"]),
        "slot_seq": s["slot_seq"],
        "capacity": s["capacity"],
        "booked_count": s["booked_count"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def ser_location(loc):
    return {
        "id": loc["id"],
        "location_code": loc["location_code"],
        "terminal_id": loc["terminal_id"],
        "accepts_equipment_types": list(loc["accepts_equipment_types"]),
        "daily_empty_capacity": loc["daily_empty_capacity"],
        "status": loc["status"],
        "created_at": loc["created_at"],
        "updated_at": loc["updated_at"],
        "version": loc["version"],
    }


def _container_provisional(c):
    """Compute provisional accruals for display per PRD §3.5."""
    if c["status"] == "AVAILABLE":
        terminal = db.terminals[c["terminal_id"]]
        contract = db.contracts[c["service_contract_id"]]
        end_d = S.local_date(now_utc(), terminal["timezone"])
        n, amount, _, _ = S.compute_accrual(c, contract, terminal, "DEMURRAGE", end_d)
        c["demurrage_billable_days"] = n
        c["demurrage_amount_cents"] = amount
    elif c["status"] == "GATE_OUT":
        terminal = db.terminals[c["terminal_id"]]
        contract = db.contracts[c["service_contract_id"]]
        end_d = S.local_date(now_utc(), terminal["timezone"])
        n, amount, _, _ = S.compute_accrual(c, contract, terminal, "DETENTION", end_d)
        c["detention_billable_days"] = n
        c["detention_amount_cents"] = amount


def ser_container(c):
    return {
        "id": c["id"],
        "container_number": c["container_number"],
        "equipment_type": c["equipment_type"],
        "customer_account_id": c["customer_account_id"],
        "service_contract_id": c["service_contract_id"],
        "terminal_id": c["terminal_id"],
        "discharge_ts": iso_utc(c["discharge_ts"]),
        "available_ts": iso_utc(c["available_ts"]),
        "gate_out_ts": iso_utc(c["gate_out_ts"]) if c.get("gate_out_ts") else None,
        "empty_return_ts": iso_utc(c["empty_return_ts"]) if c.get("empty_return_ts") else None,
        "assigned_return_location_id": c.get("assigned_return_location_id"),
        "hold_flags": [
            {
                "code": h["code"],
                "placed_ts": iso_utc(h["placed_ts"]),
                "released_ts": iso_utc(h["released_ts"]) if h.get("released_ts") else None,
            }
            for h in c.get("hold_flags", [])
        ],
        "demurrage_billable_days": c["demurrage_billable_days"],
        "detention_billable_days": c["detention_billable_days"],
        "demurrage_amount_cents": c["demurrage_amount_cents"],
        "detention_amount_cents": c["detention_amount_cents"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def ser_accrual(a):
    return {
        "id": a["id"],
        "container_id": a["container_id"],
        "charge_kind": a["charge_kind"],
        "billable_days": a["billable_days"],
        "amount_cents": a["amount_cents"],
        "rate_schedule": a["rate_schedule"],
        "computed_at": iso_utc(a["computed_at"]),
        "window_from": a["window_from"].isoformat() if a.get("window_from") else None,
        "window_to": a["window_to"].isoformat() if a.get("window_to") else None,
        "voided": a["voided"],
        "created_at": a["created_at"],
    }


def ser_invoice(inv):
    S.recompute_invoice_derived(inv)
    return {
        "id": inv["id"],
        "customer_account_id": inv["customer_account_id"],
        "container_id": inv["container_id"],
        "demurrage_total_cents": inv["demurrage_total_cents"],
        "detention_total_cents": inv["detention_total_cents"],
        "gross_amount_cents": inv["gross_amount_cents"],
        "credit_total_cents": inv["credit_total_cents"],
        "paid_total_cents": inv["paid_total_cents"],
        "balance_due_cents": inv["balance_due_cents"],
        "issued_at": iso_utc(inv["issued_at"]),
        "due_at": iso_utc(inv["due_at"]),
        "aging_bucket": inv["aging_bucket"],
        "status": inv["status"],
        "created_at": inv["created_at"],
        "updated_at": inv["updated_at"],
        "version": inv["version"],
    }


def ser_dispute(d):
    return {
        "id": d["id"],
        "invoice_id": d["invoice_id"],
        "filed_by_account_id": d["filed_by_account_id"],
        "dispute_reason": d["dispute_reason"],
        "contested_amount_cents": d["contested_amount_cents"],
        "evidence_window_start": iso_utc(d["evidence_window_start"]),
        "evidence_window_end": iso_utc(d["evidence_window_end"]),
        "evidence_summary": d["evidence_summary"],
        "resolution_code": d.get("resolution_code"),
        "resolved_amount_cents": d.get("resolved_amount_cents", 0),
        "resolution_justification": d.get("resolution_justification"),
        "reviewing_user_id": d.get("reviewing_user_id"),
        "submitted_at": iso_utc(d["submitted_at"]),
        "sla_due_at": iso_utc(d["sla_due_at"]),
        "escalated": d["escalated"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


def ser_evidence(ev):
    return {
        "id": ev["id"],
        "dispute_id": ev["dispute_id"],
        "evidence_type": ev["evidence_type"],
        "evidence_date": iso_utc(ev["evidence_date"]),
        "reference_uri": ev["reference_uri"],
        "supersedes_evidence_id": ev.get("supersedes_evidence_id"),
        "created_at": ev["created_at"],
    }


def ser_waiver(w):
    return {
        "id": w["id"],
        "invoice_id": w["invoice_id"],
        "dispute_id": w.get("dispute_id"),
        "amount_cents": w["amount_cents"],
        "authority_tier": w["authority_tier"],
        "justification": w["justification"],
        "applied_by_user_id": w["applied_by_user_id"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


def ser_payment(p):
    return {
        "id": p["id"],
        "invoice_id": p["invoice_id"],
        "amount_cents": p["amount_cents"],
        "tendered_at": iso_utc(p["tendered_at"]),
        "status": p["status"],
        "created_at": p["created_at"],
    }


def ser_booking(b):
    return {
        "booking_id": b["id"],
        "slot_id": b["slot_id"],
        "container_id": b["container_id"],
        "booked_date": iso_utc(b["booked_date"]),
    }


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/_clock/set_current_utc")
def set_clock():
    require_roles(
        "ContractManager", "TerminalOperator", "EquipmentController",
        "BillingAgent", "CreditSupervisor", "CreditDirector",
    )
    body = _payload()
    _require_fields(body, ["to_iso8601"])
    target = S.parse_iso(body["to_iso8601"], "to_iso8601")
    db.clock = target
    S.contract_expiry_sweep()
    S.dispute_escalation_sweep()
    S.aging_posture_sweep()
    return success_object({"current_utc": iso_utc(db.clock)})


# ---------------------------------------------------------------------------
# CustomerAccount
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/customer-accounts")
def create_account():
    require_roles("ContractManager")
    body = _payload()
    _require_fields(body, ["account_code", "legal_name"])
    for a in db.accounts.values():
        if a["account_code"] == body["account_code"]:
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "account_code already exists")
    rec = S.new_common()
    rec.update({
        "account_code": body["account_code"],
        "legal_name": body["legal_name"],
        "credit_hold": False,
        "outstanding_balance_cents": 0,
        "status": "ACTIVE",
    })
    db.accounts[rec["id"]] = rec
    db.consecutive_61_plus[rec["id"]] = 0
    return success_object(ser_account(rec), 201)


@app.get("/ocean-billing/customer-accounts")
def list_accounts():
    get_auth()
    limit, offset = S.parse_pagination(request.args)
    status = request.args.get("status")
    items = sorted(db.accounts.values(), key=lambda a: a["created_at"])
    if status:
        items = [a for a in items if a["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_account(a) for a in page], limit, offset, total)


@app.get("/ocean-billing/customer-accounts/<account_id>")
def get_account(account_id):
    get_auth()
    S.recompute_account_outstanding(account_id)
    a = _get_account(account_id)
    return success_object(ser_account(a))


@app.post("/ocean-billing/customer-accounts/<account_id>/close")
def close_account(account_id):
    require_roles("ContractManager")
    a = _get_account(account_id)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Account already closed")
    S.recompute_account_outstanding(account_id)
    if a["outstanding_balance_cents"] != 0:
        raise ApiError(ERR_ACCOUNT_BALANCE_OUTSTANDING, 409, "Outstanding balance")
    for c in db.containers.values():
        if c["customer_account_id"] == account_id and c["status"] in (
            "DISCHARGED", "AVAILABLE", "GATE_OUT"
        ):
            raise ApiError(ERR_ACCOUNT_CONTAINERS_ACTIVE, 409, "Active containers exist")
    a["status"] = "CLOSED"
    S.touch(a)
    return success_object(ser_account(a))


# ---------------------------------------------------------------------------
# ServiceContract
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/customer-accounts/<account_id>/service-contracts")
def create_contract(account_id):
    require_roles("ContractManager")
    _get_account(account_id)
    body = _payload()
    _require_fields(body, [
        "contract_ref", "demurrage_free_days", "detention_free_days",
        "demurrage_rate_schedule", "detention_rate_schedule",
        "effective_from", "effective_to",
    ])
    dfd = body["demurrage_free_days"]
    tfd = body["detention_free_days"]
    if not isinstance(dfd, int) or not (0 <= dfd <= 30):
        raise ApiError(ERR_INVALID_REQUEST, 400, "demurrage_free_days must be 0..30")
    if not isinstance(tfd, int) or not (0 <= tfd <= 30):
        raise ApiError(ERR_INVALID_REQUEST, 400, "detention_free_days must be 0..30")
    if body["demurrage_rate_schedule"] not in ("STANDARD", "EXTENDED_TIERED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid demurrage_rate_schedule")
    if body["detention_rate_schedule"] not in ("STANDARD", "EXTENDED_TIERED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Invalid detention_rate_schedule")
    eff_from = S.parse_iso(body["effective_from"], "effective_from")
    eff_to = S.parse_iso(body["effective_to"], "effective_to")
    if eff_to < eff_from:
        raise ApiError(ERR_INVALID_REQUEST, 400, "effective_to must be >= effective_from")
    for c in db.contracts.values():
        if c["contract_ref"] == body["contract_ref"]:
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "contract_ref already exists")
    rec = S.new_common()
    rec.update({
        "customer_account_id": account_id,
        "contract_ref": body["contract_ref"],
        "demurrage_free_days": dfd,
        "detention_free_days": tfd,
        "saturday_counts_as_free_day": bool(body.get("saturday_counts_as_free_day", False)),
        "demurrage_rate_schedule": body["demurrage_rate_schedule"],
        "detention_rate_schedule": body["detention_rate_schedule"],
        "effective_from": eff_from,
        "effective_to": eff_to,
        "status": "DRAFT",
    })
    db.contracts[rec["id"]] = rec
    return success_object(ser_contract(rec), 201)


@app.get("/ocean-billing/customer-accounts/<account_id>/service-contracts")
def list_contracts(account_id):
    require_roles(
        "ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector",
        "TerminalOperator", "CustomerRep",
    )
    _get_account(account_id)
    limit, offset = S.parse_pagination(request.args)
    status = request.args.get("status")
    items = [c for c in db.contracts.values() if c["customer_account_id"] == account_id]
    items.sort(key=lambda c: c["created_at"])
    if status:
        items = [c for c in items if c["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_contract(c) for c in page], limit, offset, total)


@app.get("/ocean-billing/service-contracts/<contract_id>")
def get_contract(contract_id):
    require_roles(
        "ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector",
        "TerminalOperator", "CustomerRep",
    )
    c = _get_contract(contract_id)
    return success_object(ser_contract(c))


@app.post("/ocean-billing/service-contracts/<contract_id>/activate")
def activate_contract(contract_id):
    require_roles("ContractManager")
    c = _get_contract(contract_id)
    if c["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "Contract not DRAFT")
    current_date = now_utc().date()
    if not (c["effective_from"].date() <= current_date <= c["effective_to"].date()):
        raise ApiError(ERR_CONTRACT_NOT_IN_EFFECT, 409, "Outside effective window")
    acct = _get_account(c["customer_account_id"])
    if acct["status"] != "ACTIVE":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "Account not ACTIVE")
    c["status"] = "ACTIVE"
    S.touch(c)
    return success_object(ser_contract(c))


# ---------------------------------------------------------------------------
# Terminal / Holiday / Slot
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/terminals")
def create_terminal():
    require_roles("TerminalOperator")
    body = _payload()
    _require_fields(body, ["terminal_code", "timezone", "daily_appointment_capacity"])
    cap = body["daily_appointment_capacity"]
    if not isinstance(cap, int) or cap < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "daily_appointment_capacity must be >= 1")
    for t in db.terminals.values():
        if t["terminal_code"] == body["terminal_code"]:
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "terminal_code already exists")
    rec = S.new_common()
    rec.update({
        "terminal_code": body["terminal_code"],
        "timezone": body["timezone"],
        "daily_appointment_capacity": cap,
        "gate_closed_weekends": bool(body.get("gate_closed_weekends", True)),
    })
    db.terminals[rec["id"]] = rec
    return success_object(ser_terminal(rec), 201)


@app.get("/ocean-billing/terminals")
def list_terminals():
    get_auth()
    limit, offset = S.parse_pagination(request.args)
    items = sorted(db.terminals.values(), key=lambda t: t["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_terminal(t) for t in page], limit, offset, total)


@app.get("/ocean-billing/terminals/<terminal_id>")
def get_terminal(terminal_id):
    get_auth()
    t = _get_terminal(terminal_id)
    return success_object(ser_terminal(t))


@app.post("/ocean-billing/terminals/<terminal_id>/holidays")
def create_holiday(terminal_id):
    require_roles("TerminalOperator")
    t = _get_terminal(terminal_id)
    body = _payload()
    _require_fields(body, ["holiday_date", "name"])
    hd = S.parse_iso(body["holiday_date"], "holiday_date")
    # unique per (terminal, holiday_date) by local date
    new_local = S.local_date(hd, t["timezone"])
    for h in db.holidays.values():
        if h["terminal_id"] == terminal_id and S.local_date(h["holiday_date"], t["timezone"]) == new_local:
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "holiday_date already declared")
    rec = S.new_ledger()
    rec.update({"terminal_id": terminal_id, "holiday_date": hd, "name": body["name"]})
    db.holidays[rec["id"]] = rec
    return success_object(ser_holiday(rec), 201)


@app.get("/ocean-billing/terminals/<terminal_id>/holidays")
def list_holidays(terminal_id):
    get_auth()
    _get_terminal(terminal_id)
    limit, offset = S.parse_pagination(request.args)
    items = [h for h in db.holidays.values() if h["terminal_id"] == terminal_id]
    items.sort(key=lambda h: h["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_holiday(h) for h in page], limit, offset, total)


@app.post("/ocean-billing/terminals/<terminal_id>/appointment-slots")
def create_slot(terminal_id):
    require_roles("TerminalOperator")
    t = _get_terminal(terminal_id)
    body = _payload()
    _require_fields(body, ["slot_date", "slot_seq", "capacity"])
    sd = S.parse_iso(body["slot_date"], "slot_date")
    seq = body["slot_seq"]
    cap = body["capacity"]
    if not isinstance(seq, int) or seq < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "slot_seq must be >= 1")
    if not isinstance(cap, int) or cap < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "capacity must be >= 1")
    sd_local = S.local_date(sd, t["timezone"])
    if not S.slot_day_is_operating(sd_local, t):
        raise ApiError(ERR_NOT_A_WORKING_DAY, 422, "slot_date is not a working day")
    for s in db.slots.values():
        if (
            s["terminal_id"] == terminal_id
            and S.local_date(s["slot_date"], t["timezone"]) == sd_local
            and s["slot_seq"] == seq
        ):
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "slot already exists for that date/seq")
    rec = S.new_common()
    rec.update({
        "terminal_id": terminal_id,
        "slot_date": sd,
        "slot_seq": seq,
        "capacity": cap,
        "booked_count": 0,
        "status": "OPEN",
    })
    db.slots[rec["id"]] = rec
    return success_object(ser_slot(rec), 201)


@app.get("/ocean-billing/terminals/<terminal_id>/appointment-slots")
def list_slots(terminal_id):
    get_auth()
    _get_terminal(terminal_id)
    limit, offset = S.parse_pagination(request.args)
    slot_date = request.args.get("slot_date")
    status = request.args.get("status")
    items = [s for s in db.slots.values() if s["terminal_id"] == terminal_id]
    items.sort(key=lambda s: s["created_at"])
    if slot_date:
        sd = S.parse_iso(slot_date, "slot_date")
        t = db.terminals[terminal_id]
        sd_local = S.local_date(sd, t["timezone"])
        items = [s for s in items if S.local_date(s["slot_date"], t["timezone"]) == sd_local]
    if status:
        items = [s for s in items if s["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_slot(s) for s in page], limit, offset, total)


@app.get("/ocean-billing/terminal-appointment-slots/<slot_id>")
def get_slot(slot_id):
    get_auth()
    s = _get_slot(slot_id)
    return success_object(ser_slot(s))


@app.post("/ocean-billing/terminal-appointment-slots/<slot_id>/release")
def release_slot(slot_id):
    require_roles("TerminalOperator")
    s = _get_slot(slot_id)
    if s["status"] == "RELEASED":
        raise ApiError(ERR_INVALID_STATE, 409, "Slot already released")
    s["status"] = "RELEASED"
    S.touch(s)
    return success_object(ser_slot(s))


# ---------------------------------------------------------------------------
# EquipmentReturnLocation
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/return-locations")
def create_location():
    require_roles("EquipmentController")
    body = _payload()
    _require_fields(body, ["location_code", "terminal_id", "accepts_equipment_types", "daily_empty_capacity"])
    _get_terminal(body["terminal_id"])
    aet = body["accepts_equipment_types"]
    if not isinstance(aet, list) or not aet:
        raise ApiError(ERR_INVALID_REQUEST, 400, "accepts_equipment_types must be a non-empty list")
    valid = {"DRY20", "DRY40", "DRY40HC", "REEFER40", "FLATRACK40"}
    for e in aet:
        if e not in valid:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"invalid equipment_type {e}")
    cap = body["daily_empty_capacity"]
    if not isinstance(cap, int) or cap < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "daily_empty_capacity must be >= 1")
    for loc in db.locations.values():
        if loc["location_code"] == body["location_code"]:
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "location_code already exists")
    rec = S.new_common()
    rec.update({
        "location_code": body["location_code"],
        "terminal_id": body["terminal_id"],
        "accepts_equipment_types": list(aet),
        "daily_empty_capacity": cap,
        "status": "OPEN",
        "restricted_at": None,
    })
    db.locations[rec["id"]] = rec
    return success_object(ser_location(rec), 201)


@app.get("/ocean-billing/return-locations")
def list_locations():
    get_auth()
    limit, offset = S.parse_pagination(request.args)
    terminal_id = request.args.get("terminal_id")
    status = request.args.get("status")
    items = sorted(db.locations.values(), key=lambda l: l["created_at"])
    if terminal_id:
        items = [l for l in items if l["terminal_id"] == terminal_id]
    if status:
        items = [l for l in items if l["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_location(l) for l in page], limit, offset, total)


@app.get("/ocean-billing/return-locations/<location_id>")
def get_location(location_id):
    get_auth()
    loc = _get_location(location_id)
    return success_object(ser_location(loc))


@app.post("/ocean-billing/return-locations/<location_id>/set-status")
def set_location_status(location_id):
    require_roles("EquipmentController")
    loc = _get_location(location_id)
    body = _payload()
    _require_fields(body, ["status"])
    new_status = body["status"]
    if new_status not in ("OPEN", "RESTRICTED", "CLOSED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "status must be OPEN|RESTRICTED|CLOSED")
    if new_status == "RESTRICTED" and loc["status"] != "RESTRICTED":
        loc["restricted_at"] = now_utc()
    loc["status"] = new_status
    S.touch(loc)
    return success_object(ser_location(loc))


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/containers")
def create_container():
    require_roles("TerminalOperator")
    body = _payload()
    _require_fields(body, [
        "container_number", "equipment_type", "customer_account_id",
        "service_contract_id", "terminal_id", "discharge_ts", "available_ts",
    ])
    valid_eq = {"DRY20", "DRY40", "DRY40HC", "REEFER40", "FLATRACK40"}
    if body["equipment_type"] not in valid_eq:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid equipment_type")
    discharge = S.parse_iso(body["discharge_ts"], "discharge_ts")
    available = S.parse_iso(body["available_ts"], "available_ts")
    for c in db.containers.values():
        if c["container_number"] == body["container_number"]:
            raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "container_number already exists")
    acct = _get_account(body["customer_account_id"])
    contract = _get_contract(body["service_contract_id"])
    _get_terminal(body["terminal_id"])
    if acct["status"] == "CLOSED":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "Account closed")
    if acct["status"] == "SUSPENDED" and acct["credit_hold"]:
        raise ApiError(ERR_ACCOUNT_CREDIT_HOLD, 409, "Account on credit hold")
    if contract["status"] != "ACTIVE":
        raise ApiError(ERR_CONTRACT_NOT_IN_EFFECT, 409, "Contract not ACTIVE")
    if contract["customer_account_id"] != body["customer_account_id"]:
        raise ApiError(ERR_REFERENTIAL_GUARD, 409, "Contract not owned by account")
    rec = S.new_common()
    rec.update({
        "container_number": body["container_number"],
        "equipment_type": body["equipment_type"],
        "customer_account_id": body["customer_account_id"],
        "service_contract_id": body["service_contract_id"],
        "terminal_id": body["terminal_id"],
        "discharge_ts": discharge,
        "available_ts": available,
        "gate_out_ts": None,
        "empty_return_ts": None,
        "assigned_return_location_id": None,
        "assigned_return_location_ts": None,
        "hold_flags": [],
        "demurrage_billable_days": 0,
        "detention_billable_days": 0,
        "demurrage_amount_cents": 0,
        "detention_amount_cents": 0,
        "status": "DISCHARGED",
    })
    db.containers[rec["id"]] = rec
    return success_object(ser_container(rec), 201)


@app.get("/ocean-billing/containers")
def list_containers():
    get_auth()
    limit, offset = S.parse_pagination(request.args)
    items = sorted(db.containers.values(), key=lambda c: c["created_at"])
    for fkey in ("customer_account_id", "terminal_id", "status", "service_contract_id", "assigned_return_location_id"):
        v = request.args.get(fkey)
        if v:
            items = [c for c in items if str(c.get(fkey)) == v]
    for c in items:
        _container_provisional(c)
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_container(c) for c in page], limit, offset, total)


@app.get("/ocean-billing/containers/<container_id>")
def get_container(container_id):
    get_auth()
    c = _get_container(container_id)
    _container_provisional(c)
    return success_object(ser_container(c))


@app.get("/ocean-billing/containers/<container_id>/accruals")
def list_accruals(container_id):
    get_auth()
    _get_container(container_id)
    limit, offset = S.parse_pagination(request.args)
    charge_kind = request.args.get("charge_kind")
    voided = request.args.get("voided")
    items = [a for a in db.accruals.values() if a["container_id"] == container_id]
    items.sort(key=lambda a: a["created_at"])
    if charge_kind:
        items = [a for a in items if a["charge_kind"] == charge_kind]
    if voided is not None and voided != "":
        v = voided.lower() in ("true", "1", "yes")
        items = [a for a in items if a["voided"] == v]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_accrual(a) for a in page], limit, offset, total)


@app.post("/ocean-billing/containers/<container_id>/mark-available")
def mark_available(container_id):
    require_roles("TerminalOperator")
    c = _get_container(container_id)
    if c["status"] != "DISCHARGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Container not DISCHARGED")
    if c["available_ts"] < c["discharge_ts"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "available_ts before discharge_ts")
    c["status"] = "AVAILABLE"
    S.touch(c)
    return success_object(ser_container(c))


@app.post("/ocean-billing/containers/<container_id>/holds")
def set_hold(container_id):
    require_roles("TerminalOperator", "EquipmentController")
    c = _get_container(container_id)
    body = _payload()
    _require_fields(body, ["hold_code", "action"])
    code = body["hold_code"]
    action = body["action"]
    if code not in ("CUSTOMS_HOLD", "CHASSIS_SHORTAGE", "USDA_HOLD"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid hold_code")
    if action not in ("PLACE", "RELEASE"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "action must be PLACE or RELEASE")
    if action == "PLACE":
        # idempotent if same code already active
        for h in c["hold_flags"]:
            if h["code"] == code and h.get("released_ts") is None:
                return success_object(ser_container(c))
        c["hold_flags"].append({
            "code": code,
            "placed_ts": now_utc(),
            "released_ts": None,
        })
    else:
        target = None
        for h in c["hold_flags"]:
            if h["code"] == code and h.get("released_ts") is None:
                target = h
                break
        if target is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"No active {code} hold to release")
        target["released_ts"] = now_utc()
    S.touch(c)
    return success_object(ser_container(c))


@app.post("/ocean-billing/containers/<container_id>/appointments")
def book_appointment(container_id):
    user_id, role = require_roles("TerminalOperator", "CustomerRep")
    c = _get_container(container_id)
    body = _payload()
    _require_fields(body, ["slot_id"])
    slot = _get_slot(body["slot_id"])
    if role == "CustomerRep":
        _check_rep_owns_account(user_id, role, c["customer_account_id"])
    if slot["terminal_id"] != c["terminal_id"]:
        raise ApiError(ERR_REFERENTIAL_GUARD, 409, "Slot at a different terminal")
    if slot["status"] == "RELEASED":
        raise ApiError(ERR_SLOT_RELEASED, 409, "Slot released")
    if slot["status"] == "FULL" or slot["booked_count"] >= slot["capacity"]:
        raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "Slot full")
    rec = S.new_ledger()
    rec.update({
        "slot_id": slot["id"],
        "container_id": container_id,
        "booked_date": now_utc(),
        "cancelled": False,
    })
    db.bookings[rec["id"]] = rec
    slot["booked_count"] += 1
    if slot["booked_count"] >= slot["capacity"]:
        slot["status"] = "FULL"
    S.touch(slot)
    return success_object(ser_booking(rec), 201)


@app.post("/ocean-billing/containers/<container_id>/appointments/<booking_id>/cancel")
def cancel_appointment(container_id, booking_id):
    user_id, role = require_roles("TerminalOperator", "CustomerRep")
    c = _get_container(container_id)
    b = _get_booking(booking_id)
    if b["container_id"] != container_id:
        raise ApiError(ERR_NOT_FOUND, 404, "Booking not under container")
    if role == "CustomerRep":
        _check_rep_owns_account(user_id, role, c["customer_account_id"])
    if b.get("cancelled"):
        raise ApiError(ERR_INVALID_STATE, 409, "Booking already cancelled")
    b["cancelled"] = True
    slot = db.slots[b["slot_id"]]
    slot["booked_count"] = max(0, slot["booked_count"] - 1)
    if slot["status"] == "FULL" and slot["booked_count"] < slot["capacity"]:
        slot["status"] = "OPEN"
    S.touch(slot)
    return success_object(ser_booking(b))


@app.post("/ocean-billing/containers/<container_id>/gate-out")
def gate_out(container_id):
    require_roles("TerminalOperator")
    c = _get_container(container_id)
    body = _payload()
    if c["status"] != "AVAILABLE":
        raise ApiError(ERR_INVALID_STATE, 409, "Container not AVAILABLE")
    # Hold overlay
    for h in c["hold_flags"]:
        if h["code"] in ("CUSTOMS_HOLD", "USDA_HOLD") and h.get("released_ts") is None:
            raise ApiError(ERR_CONTAINER_HELD, 409, f"Active {h['code']}")
    # Appointment or override
    slot_override = bool(body.get("slot_override", False))
    override_reason = body.get("slot_override_reason")
    if slot_override:
        if not override_reason:
            raise ApiError(ERR_INVALID_REQUEST, 400, "slot_override_reason required")
    else:
        terminal = db.terminals[c["terminal_id"]]
        today = S.local_date(now_utc(), terminal["timezone"])
        found = False
        for b in db.bookings.values():
            if b["container_id"] == container_id and not b.get("cancelled"):
                slot = db.slots[b["slot_id"]]
                if S.local_date(slot["slot_date"], terminal["timezone"]) == today:
                    found = True
                    break
        if not found:
            raise ApiError(ERR_APPOINTMENT_REQUIRED, 409, "No confirmed appointment for gate-out day")
    # Return location selection
    pool = []
    for loc in db.locations.values():
        if loc["terminal_id"] != c["terminal_id"]:
            continue
        if c["equipment_type"] not in loc["accepts_equipment_types"]:
            continue
        if loc["status"] not in ("OPEN", "RESTRICTED"):
            continue
        pool.append(loc)
    if not pool:
        raise ApiError(ERR_NO_RETURN_LOCATION, 422, "No eligible return location")
    pool.sort(key=lambda l: (-l["daily_empty_capacity"], l["location_code"]))
    chosen = pool[0]

    c["gate_out_ts"] = now_utc()
    c["assigned_return_location_id"] = chosen["id"]
    c["assigned_return_location_ts"] = now_utc()
    # Final demurrage accrual
    terminal = db.terminals[c["terminal_id"]]
    contract = db.contracts[c["service_contract_id"]]
    end_d = S.local_date(c["gate_out_ts"], terminal["timezone"])
    n, amount, wf, wt = S.compute_accrual(c, contract, terminal, "DEMURRAGE", end_d)
    c["demurrage_billable_days"] = n
    c["demurrage_amount_cents"] = amount
    acc = S.new_ledger()
    acc.update({
        "container_id": container_id,
        "charge_kind": "DEMURRAGE",
        "billable_days": n,
        "amount_cents": amount,
        "rate_schedule": contract["demurrage_rate_schedule"],
        "computed_at": now_utc(),
        "window_from": wf,
        "window_to": wt,
        "voided": False,
    })
    db.accruals[acc["id"]] = acc
    c["status"] = "GATE_OUT"
    S.touch(c)
    return success_object(ser_container(c))


@app.post("/ocean-billing/containers/<container_id>/reassign-return-location")
def reassign_return_location(container_id):
    require_roles("EquipmentController")
    c = _get_container(container_id)
    body = _payload()
    _require_fields(body, ["assigned_return_location_id"])
    if c["status"] != "GATE_OUT":
        raise ApiError(ERR_INVALID_STATE, 409, "Container not GATE_OUT")
    loc = _get_location(body["assigned_return_location_id"])
    if loc["terminal_id"] != c["terminal_id"]:
        raise ApiError(ERR_REFERENTIAL_GUARD, 409, "Location serves different terminal")
    if c["equipment_type"] not in loc["accepts_equipment_types"]:
        raise ApiError(ERR_REFERENTIAL_GUARD, 409, "Location does not accept equipment type")
    c["assigned_return_location_id"] = loc["id"]
    c["assigned_return_location_ts"] = now_utc()
    S.touch(c)
    return success_object(ser_container(c))


@app.post("/ocean-billing/containers/<container_id>/return-empty")
def return_empty(container_id):
    require_roles("EquipmentController")
    c = _get_container(container_id)
    if c["status"] != "GATE_OUT":
        raise ApiError(ERR_INVALID_STATE, 409, "Container not GATE_OUT")
    if not c.get("assigned_return_location_id"):
        raise ApiError(ERR_INVALID_STATE, 409, "No assigned return location")
    loc = db.locations[c["assigned_return_location_id"]]
    if loc["status"] == "CLOSED":
        raise ApiError(ERR_RETURN_LOCATION_CLOSED, 409, "Location CLOSED")
    if loc["status"] == "RESTRICTED":
        assigned_at = c.get("assigned_return_location_ts")
        restricted_at = loc.get("restricted_at")
        if restricted_at and assigned_at and assigned_at >= restricted_at:
            raise ApiError(ERR_RETURN_LOCATION_RESTRICTED, 409, "Assigned after restriction")
    if c["equipment_type"] not in loc["accepts_equipment_types"]:
        raise ApiError(ERR_REFERENTIAL_GUARD, 409, "Equipment type not accepted")
    terminal = db.terminals[c["terminal_id"]]
    return_date = S.local_date(now_utc(), terminal["timezone"]).isoformat()
    key = (loc["id"], return_date)
    used = db.location_daily_returns.get(key, 0)
    if used >= loc["daily_empty_capacity"]:
        raise ApiError(ERR_CAPACITY_OR_CONFLICT, 409, "Daily empty capacity reached")

    c["empty_return_ts"] = now_utc()
    contract = db.contracts[c["service_contract_id"]]
    n, amount, wf, wt = S.compute_accrual(c, contract, terminal, "DETENTION", S.local_date(c["empty_return_ts"], terminal["timezone"]))
    c["detention_billable_days"] = n
    c["detention_amount_cents"] = amount
    acc = S.new_ledger()
    acc.update({
        "container_id": container_id,
        "charge_kind": "DETENTION",
        "billable_days": n,
        "amount_cents": amount,
        "rate_schedule": contract["detention_rate_schedule"],
        "computed_at": now_utc(),
        "window_from": wf,
        "window_to": wt,
        "voided": False,
    })
    db.accruals[acc["id"]] = acc
    db.location_daily_returns[key] = used + 1
    c["status"] = "EMPTY_RETURNED"
    S.touch(c)
    return success_object(ser_container(c))


@app.post("/ocean-billing/containers/<container_id>/issue-invoice")
def issue_invoice(container_id):
    require_roles("BillingAgent")
    c = _get_container(container_id)
    if c["status"] != "EMPTY_RETURNED":
        raise ApiError(ERR_INVALID_STATE, 409, "Container not EMPTY_RETURNED")
    acct = _get_account(c["customer_account_id"])
    if acct["status"] == "CLOSED":
        raise ApiError(ERR_ACCOUNT_NOT_ACTIVE, 409, "Account CLOSED")
    dem_total = sum(a["amount_cents"] for a in db.accruals.values()
                    if a["container_id"] == container_id and a["charge_kind"] == "DEMURRAGE" and not a["voided"])
    det_total = sum(a["amount_cents"] for a in db.accruals.values()
                    if a["container_id"] == container_id and a["charge_kind"] == "DETENTION" and not a["voided"])
    issued = now_utc()
    inv = S.new_common()
    inv.update({
        "customer_account_id": c["customer_account_id"],
        "container_id": container_id,
        "demurrage_total_cents": dem_total,
        "detention_total_cents": det_total,
        "gross_amount_cents": dem_total + det_total,
        "credit_total_cents": 0,
        "paid_total_cents": 0,
        "balance_due_cents": dem_total + det_total,
        "issued_at": issued,
        "due_at": issued + timedelta(days=30),
        "aging_bucket": "CURRENT",
        "status": "ISSUED",
    })
    db.invoices[inv["id"]] = inv
    c["status"] = "BILLED"
    S.touch(c)
    S.recompute_account_outstanding(c["customer_account_id"])
    S.aging_posture_sweep()
    return success_object(ser_invoice(inv), 201)


# ---------------------------------------------------------------------------
# Invoices / payments / write-off
# ---------------------------------------------------------------------------

@app.get("/ocean-billing/invoices")
def list_invoices():
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    limit, offset = S.parse_pagination(request.args)
    items = sorted(db.invoices.values(), key=lambda i: i["created_at"])
    for fkey in ("customer_account_id", "status", "container_id"):
        v = request.args.get(fkey)
        if v:
            items = [i for i in items if str(i.get(fkey)) == v]
    # recompute aging on all to apply aging_bucket filter
    for i in items:
        S.recompute_invoice_derived(i)
    aging = request.args.get("aging_bucket")
    if aging:
        items = [i for i in items if i["aging_bucket"] == aging]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_invoice(i) for i in page], limit, offset, total)


@app.get("/ocean-billing/invoices/<invoice_id>")
def get_invoice(invoice_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    inv = _get_invoice(invoice_id)
    return success_object(ser_invoice(inv))


@app.post("/ocean-billing/invoices/<invoice_id>/payments")
def create_payment(invoice_id):
    require_roles("BillingAgent")
    inv = _get_invoice(invoice_id)
    body = _payload()
    _require_fields(body, ["amount_cents"])
    amount = body["amount_cents"]
    if not isinstance(amount, int) or amount < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be >= 1")
    if inv["status"] in ("PAID", "WRITTEN_OFF"):
        raise ApiError(ERR_INVOICE_ALREADY_SETTLED, 409, "Invoice settled")
    S.recompute_invoice_derived(inv)
    if amount > inv["balance_due_cents"]:
        raise ApiError(ERR_PAYMENT_EXCEEDS_BALANCE, 422, "Payment exceeds balance_due")
    rec = S.new_ledger()
    rec.update({
        "invoice_id": invoice_id,
        "amount_cents": amount,
        "tendered_at": now_utc(),
        "status": "SETTLED",
    })
    db.payments[rec["id"]] = rec
    S.recompute_invoice_derived(inv)
    if inv["balance_due_cents"] == 0:
        inv["status"] = "PAID"
    else:
        inv["status"] = "PARTIALLY_PAID"
    S.touch(inv)
    S.recompute_account_outstanding(inv["customer_account_id"])
    S.aging_posture_sweep()
    return success_object(ser_payment(rec), 201)


@app.post("/ocean-billing/invoices/<invoice_id>/write-off")
def write_off_invoice(invoice_id):
    user_id, role = require_roles("CreditDirector")
    inv = _get_invoice(invoice_id)
    body = _payload()
    justification = body.get("justification")
    if not justification or not str(justification).strip():
        raise ApiError(ERR_JUSTIFICATION_REQUIRED, 422, "justification required")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice not in write-off state")
    S.recompute_invoice_derived(inv)
    if inv["aging_bucket"] != "DAYS_61_PLUS":
        raise ApiError(ERR_INVOICE_NOT_AGED_ENOUGH, 409, "Invoice not in DAYS_61_PLUS")
    # Implicit TIER_3 APPLIED waiver covering full balance
    amount = inv["balance_due_cents"]
    w = S.new_common()
    w.update({
        "invoice_id": invoice_id,
        "dispute_id": None,
        "amount_cents": amount,
        "authority_tier": "TIER_3_DIRECTOR",
        "justification": justification,
        "applied_by_user_id": user_id,
        "status": "APPLIED",
    })
    db.waivers[w["id"]] = w
    _apply_credit_to_accruals(inv, amount, exclude_waiver_id=w["id"])
    S.recompute_invoice_derived(inv)
    inv["status"] = "WRITTEN_OFF"
    S.touch(inv)
    S.recompute_account_outstanding(inv["customer_account_id"])
    S.aging_posture_sweep()
    return success_object(ser_invoice(inv))


@app.get("/ocean-billing/invoices/<invoice_id>/payments")
def list_payments(invoice_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    _get_invoice(invoice_id)
    limit, offset = S.parse_pagination(request.args)
    items = [p for p in db.payments.values() if p["invoice_id"] == invoice_id]
    items.sort(key=lambda p: p["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_payment(p) for p in page], limit, offset, total)


@app.get("/ocean-billing/invoices/<invoice_id>/credit-waivers")
def list_invoice_waivers(invoice_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    _get_invoice(invoice_id)
    limit, offset = S.parse_pagination(request.args)
    status = request.args.get("status")
    items = [w for w in db.waivers.values() if w["invoice_id"] == invoice_id]
    items.sort(key=lambda w: w["created_at"])
    if status:
        items = [w for w in items if w["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_waiver(w) for w in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

EVIDENCE_REASONS = {"APPOINTMENT_UNAVAILABLE", "CHASSIS_SHORTAGE", "CUSTOMS_HOLD"}
DISPUTE_REASONS = EVIDENCE_REASONS | {"FREE_TIME_MISCALC", "RATE_MISMATCH", "OTHER"}
EVIDENCE_TYPES = {
    "APPOINTMENT_SCREENSHOT", "CHASSIS_POOL_NOTICE", "CUSTOMS_HOLD_NOTICE",
    "APPOINTMENT_API_LOG", "OTHER",
}


def _authority_tier(amount: int) -> str:
    if amount <= 50000:
        return "TIER_1_AGENT"
    if amount <= 500000:
        return "TIER_2_SUPERVISOR"
    return "TIER_3_DIRECTOR"


_ROLE_TIER = {
    "BillingAgent": 1,
    "CreditSupervisor": 2,
    "CreditDirector": 3,
}
_TIER_RANK = {"TIER_1_AGENT": 1, "TIER_2_SUPERVISOR": 2, "TIER_3_DIRECTOR": 3}


def _apply_credit_to_accruals(invoice, amount, exclude_waiver_id=None):
    """Run the credit waterfall: detention first, then demurrage. Track
    cumulative per-component credits; void accruals at exact component total.
    Returns (credited_detention, credited_demurrage)."""
    prior = [w for w in db.waivers.values()
             if w["invoice_id"] == invoice["id"] and w["status"] == "APPLIED"
             and w["id"] != exclude_waiver_id]
    det_total = invoice["detention_total_cents"]
    dem_total = invoice["demurrage_total_cents"]
    det_credited = 0
    dem_credited = 0
    for w in sorted(prior, key=lambda x: x["created_at"]):
        remaining = w["amount_cents"]
        cdt = min(remaining, det_total - det_credited)
        det_credited += cdt
        remaining -= cdt
        cdm = min(remaining, dem_total - dem_credited)
        dem_credited += cdm
        remaining -= cdm
    # This credit
    remaining = amount
    new_det = min(remaining, det_total - det_credited)
    remaining -= new_det
    new_dem = min(remaining, dem_total - dem_credited)
    remaining -= new_dem
    if remaining > 0:
        raise ApiError(ERR_CREDIT_EXCEEDS_BALANCE, 422, "Credit exceeds creditable balance")
    det_credited += new_det
    dem_credited += new_dem
    # Void accruals when a component is fully credited
    if det_total > 0 and det_credited == det_total:
        _void_component_accruals(invoice["container_id"], "DETENTION")
    if dem_total > 0 and dem_credited == dem_total:
        _void_component_accruals(invoice["container_id"], "DEMURRAGE")
    return new_det, new_dem


def _void_component_accruals(container_id, kind):
    rows = [a for a in db.accruals.values()
            if a["container_id"] == container_id and a["charge_kind"] == kind and not a["voided"]]
    rows.sort(key=lambda a: a["computed_at"])
    for r in rows:
        r["voided"] = True


@app.post("/ocean-billing/invoices/<invoice_id>/disputes")
def create_dispute(invoice_id):
    user_id, role = require_roles("CustomerRep")
    inv = _get_invoice(invoice_id)
    _check_rep_owns_account(user_id, role, inv["customer_account_id"])
    body = _payload()
    _require_fields(body, [
        "dispute_reason", "contested_amount_cents",
        "evidence_window_start", "evidence_window_end", "evidence_summary",
    ])
    if body["dispute_reason"] not in DISPUTE_REASONS:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid dispute_reason")
    amount = body["contested_amount_cents"]
    if not isinstance(amount, int) or amount < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "contested_amount_cents must be >= 1")
    if not str(body.get("evidence_summary", "")).strip():
        raise ApiError(ERR_INVALID_REQUEST, 400, "evidence_summary must be non-empty")
    ws = S.parse_iso(body["evidence_window_start"], "evidence_window_start")
    we = S.parse_iso(body["evidence_window_end"], "evidence_window_end")
    if we < ws:
        raise ApiError(ERR_INVALID_REQUEST, 400, "evidence_window_end < evidence_window_start")
    if inv["status"] not in ("ISSUED", "PARTIALLY_PAID", "DISPUTED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Invoice not disputable")
    for d in db.disputes.values():
        if d["invoice_id"] == invoice_id and d["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            raise ApiError(ERR_DISPUTE_ALREADY_OPEN, 409, "Open dispute exists")
    S.recompute_invoice_derived(inv)
    if amount > inv["balance_due_cents"]:
        raise ApiError(ERR_INVALID_REQUEST, 400, "contested_amount exceeds balance_due")
    submitted = now_utc()
    rec = S.new_common()
    rec.update({
        "invoice_id": invoice_id,
        "filed_by_account_id": inv["customer_account_id"],
        "dispute_reason": body["dispute_reason"],
        "contested_amount_cents": amount,
        "evidence_window_start": ws,
        "evidence_window_end": we,
        "evidence_summary": body["evidence_summary"],
        "resolution_code": None,
        "resolved_amount_cents": 0,
        "resolution_justification": None,
        "reviewing_user_id": None,
        "submitted_at": submitted,
        "sla_due_at": submitted + timedelta(days=14),
        "escalated": False,
        "status": "SUBMITTED",
    })
    db.disputes[rec["id"]] = rec
    inv["status"] = "DISPUTED"
    S.touch(inv)
    return success_object(ser_dispute(rec), 201)


@app.get("/ocean-billing/disputes")
def list_disputes():
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    limit, offset = S.parse_pagination(request.args)
    items = sorted(db.disputes.values(), key=lambda d: d["created_at"])
    for fkey in ("invoice_id", "filed_by_account_id", "status"):
        v = request.args.get(fkey)
        if v:
            items = [d for d in items if str(d.get(fkey)) == v]
    esc = request.args.get("escalated")
    if esc is not None and esc != "":
        v = esc.lower() in ("true", "1", "yes")
        items = [d for d in items if d["escalated"] == v]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_dispute(d) for d in page], limit, offset, total)


@app.get("/ocean-billing/disputes/<dispute_id>")
def get_dispute(dispute_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    d = _get_dispute(dispute_id)
    return success_object(ser_dispute(d))


@app.get("/ocean-billing/dispute-evidence/<evidence_id>")
def get_evidence(evidence_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    ev = _get_evidence(evidence_id)
    return success_object(ser_evidence(ev))


@app.get("/ocean-billing/dispute-evidence")
def list_all_evidence():
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    limit, offset = S.parse_pagination(request.args)
    items = sorted(db.evidence.values(), key=lambda e: e["created_at"])
    dispute_id = request.args.get("dispute_id")
    supersedes = request.args.get("supersedes_evidence_id")
    if dispute_id:
        items = [e for e in items if e["dispute_id"] == dispute_id]
    if supersedes:
        items = [e for e in items if e.get("supersedes_evidence_id") == supersedes]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_evidence(e) for e in page], limit, offset, total)


@app.post("/ocean-billing/disputes/<dispute_id>/evidence")
def attach_evidence(dispute_id):
    user_id, role = require_roles("CustomerRep", "BillingAgent")
    dsp = _get_dispute(dispute_id)
    if role == "CustomerRep":
        _check_rep_owns_account(user_id, role, dsp["filed_by_account_id"])
    if dsp["status"] not in ("SUBMITTED", "UNDER_REVIEW"):
        raise ApiError(ERR_INVALID_STATE, 409, "Dispute not open")
    body = _payload()
    _require_fields(body, ["evidence_type", "evidence_date", "reference_uri"])
    if body["evidence_type"] not in EVIDENCE_TYPES:
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid evidence_type")
    ed = S.parse_iso(body["evidence_date"], "evidence_date")
    if not (dsp["evidence_window_start"] <= ed <= dsp["evidence_window_end"]):
        raise ApiError(ERR_NOT_A_WORKING_DAY, 422, "evidence_date outside dispute window")
    supersedes = body.get("supersedes_evidence_id")
    if supersedes:
        prev = _get_evidence(supersedes)
        if prev["dispute_id"] != dispute_id:
            raise ApiError(ERR_REFERENTIAL_GUARD, 409, "superseded evidence belongs to another dispute")
    rec = S.new_ledger()
    rec.update({
        "dispute_id": dispute_id,
        "evidence_type": body["evidence_type"],
        "evidence_date": ed,
        "reference_uri": body["reference_uri"],
        "supersedes_evidence_id": supersedes,
        "filed_by_user_id": user_id,
    })
    db.evidence[rec["id"]] = rec
    S.touch(dsp)
    return success_object(ser_evidence(rec), 201)


@app.get("/ocean-billing/disputes/<dispute_id>/evidence")
def list_dispute_evidence(dispute_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    _get_dispute(dispute_id)
    limit, offset = S.parse_pagination(request.args)
    items = [e for e in db.evidence.values() if e["dispute_id"] == dispute_id]
    items.sort(key=lambda e: e["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_evidence(e) for e in page], limit, offset, total)


@app.post("/ocean-billing/disputes/<dispute_id>/start-review")
def start_review(dispute_id):
    user_id, role = require_roles("BillingAgent")
    dsp = _get_dispute(dispute_id)
    if dsp["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispute not SUBMITTED")
    if dsp["dispute_reason"] in EVIDENCE_REASONS:
        has_evidence = any(e["dispute_id"] == dispute_id for e in db.evidence.values())
        if not has_evidence:
            raise ApiError(ERR_EVIDENCE_REQUIRED, 422, "Evidence required for this reason")
    dsp["status"] = "UNDER_REVIEW"
    dsp["reviewing_user_id"] = user_id
    S.touch(dsp)
    return success_object(ser_dispute(dsp))


@app.post("/ocean-billing/disputes/<dispute_id>/return-to-queue")
def return_to_queue(dispute_id):
    require_roles("BillingAgent")
    dsp = _get_dispute(dispute_id)
    if dsp["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispute not UNDER_REVIEW")
    dsp["status"] = "SUBMITTED"
    dsp["reviewing_user_id"] = None
    S.touch(dsp)
    return success_object(ser_dispute(dsp))


@app.post("/ocean-billing/disputes/<dispute_id>/resolve")
def resolve_dispute(dispute_id):
    user_id, role = require_roles("BillingAgent", "CreditSupervisor", "CreditDirector")
    dsp = _get_dispute(dispute_id)
    body = _payload()
    _require_fields(body, ["resolution_code", "resolution_justification", "expected_dispute_version"])
    if dsp["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispute not UNDER_REVIEW")
    # OCC check
    expected = body["expected_dispute_version"]
    if not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_dispute_version must be int")
    if expected != dsp["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale dispute version")
    justification = body.get("resolution_justification")
    if not justification or not str(justification).strip():
        raise ApiError(ERR_JUSTIFICATION_REQUIRED, 422, "resolution_justification required")
    code = body["resolution_code"]
    if code not in ("FULL_CREDIT", "PARTIAL_CREDIT", "DENIED"):
        raise ApiError(ERR_INVALID_REQUEST, 400, "invalid resolution_code")

    if code in ("FULL_CREDIT", "PARTIAL_CREDIT"):
        resolved = body.get("resolved_amount_cents")
        if not isinstance(resolved, int):
            raise ApiError(ERR_RESOLVED_AMOUNT_INVALID, 422, "resolved_amount_cents required")
        if code == "FULL_CREDIT":
            if resolved != dsp["contested_amount_cents"]:
                raise ApiError(ERR_RESOLVED_AMOUNT_INVALID, 422, "FULL_CREDIT requires resolved == contested")
        else:
            if not (1 <= resolved < dsp["contested_amount_cents"]):
                raise ApiError(ERR_RESOLVED_AMOUNT_INVALID, 422, "PARTIAL_CREDIT requires 1 <= resolved < contested")
        # Authority check
        actor_rank = _ROLE_TIER[role]
        needed_rank = _TIER_RANK[_authority_tier(resolved)]
        if actor_rank < needed_rank:
            raise ApiError(ERR_WAIVER_AUTHORITY_EXCEEDED, 403, "Authority tier insufficient")
        # Segregation of duties: BillingAgent resolver must not be the evidence filer
        if role == "BillingAgent":
            for ev in db.evidence.values():
                if ev["dispute_id"] == dispute_id and ev.get("filed_by_user_id") == user_id:
                    raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Resolver filed evidence")
        # Apply credit
        inv = _get_invoice(dsp["invoice_id"])
        S.recompute_invoice_derived(inv)
        w = S.new_common()
        w.update({
            "invoice_id": inv["id"],
            "dispute_id": dispute_id,
            "amount_cents": resolved,
            "authority_tier": _authority_tier(resolved),
            "justification": justification,
            "applied_by_user_id": user_id,
            "status": "APPLIED",
        })
        db.waivers[w["id"]] = w
        _apply_credit_to_accruals(inv, resolved, exclude_waiver_id=w["id"])
        S.recompute_invoice_derived(inv)
        if inv["balance_due_cents"] == 0:
            inv["status"] = "PAID"
        else:
            inv["status"] = "ISSUED" if inv["paid_total_cents"] == 0 else "PARTIALLY_PAID"
        S.touch(inv)
        S.recompute_account_outstanding(inv["customer_account_id"])
        S.aging_posture_sweep()
        dsp["resolution_code"] = code
        dsp["resolved_amount_cents"] = resolved
        dsp["resolution_justification"] = justification
        dsp["status"] = "RESOLVED_FULL_CREDIT" if code == "FULL_CREDIT" else "RESOLVED_PARTIAL_CREDIT"
    else:  # DENIED
        inv = _get_invoice(dsp["invoice_id"])
        S.recompute_invoice_derived(inv)
        inv["status"] = "ISSUED" if inv["paid_total_cents"] == 0 else "PARTIALLY_PAID"
        S.touch(inv)
        dsp["resolution_code"] = "DENIED"
        dsp["resolved_amount_cents"] = 0
        dsp["resolution_justification"] = justification
        dsp["status"] = "RESOLVED_DENIED"
    S.touch(dsp)
    return success_object(ser_dispute(dsp))


@app.post("/ocean-billing/disputes/<dispute_id>/withdraw")
def withdraw_dispute(dispute_id):
    user_id, role = require_roles("CustomerRep")
    dsp = _get_dispute(dispute_id)
    _check_rep_owns_account(user_id, role, dsp["filed_by_account_id"])
    if dsp["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispute not SUBMITTED")
    dsp["status"] = "WITHDRAWN"
    dsp["resolution_code"] = "WITHDRAWN"
    inv = _get_invoice(dsp["invoice_id"])
    S.recompute_invoice_derived(inv)
    inv["status"] = "ISSUED" if inv["paid_total_cents"] == 0 else "PARTIALLY_PAID"
    S.touch(inv)
    S.touch(dsp)
    return success_object(ser_dispute(dsp))


@app.get("/ocean-billing/disputes/<dispute_id>/credit-waivers")
def list_dispute_waivers(dispute_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    _get_dispute(dispute_id)
    limit, offset = S.parse_pagination(request.args)
    items = [w for w in db.waivers.values() if w.get("dispute_id") == dispute_id]
    items.sort(key=lambda w: w["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([ser_waiver(w) for w in page], limit, offset, total)


# ---------------------------------------------------------------------------
# Credit waivers (goodwill / non-dispute path)
# ---------------------------------------------------------------------------

@app.post("/ocean-billing/invoices/<invoice_id>/credit-waivers")
def propose_waiver(invoice_id):
    user_id, role = require_roles("BillingAgent", "CreditSupervisor", "CreditDirector")
    inv = _get_invoice(invoice_id)
    body = _payload()
    _require_fields(body, ["amount_cents", "justification"])
    amount = body["amount_cents"]
    if not isinstance(amount, int) or amount < 1:
        raise ApiError(ERR_INVALID_REQUEST, 400, "amount_cents must be >= 1")
    justification = body["justification"]
    if not str(justification).strip():
        raise ApiError(ERR_JUSTIFICATION_REQUIRED, 422, "justification required")
    if inv["status"] in ("PAID", "WRITTEN_OFF"):
        raise ApiError(ERR_INVOICE_ALREADY_SETTLED, 409, "Invoice settled")
    S.recompute_invoice_derived(inv)
    tier = _authority_tier(amount)
    actor_rank = _ROLE_TIER[role]
    # Only enforce authority when the actor would immediately apply (TIER_1
    # amounts). Higher-tier amounts stay PROPOSED for later approval; the
    # approver's authority is checked at approve time.
    if amount > inv["balance_due_cents"]:
        raise ApiError(ERR_CREDIT_EXCEEDS_BALANCE, 422, "Credit exceeds balance")
    rec = S.new_common()
    rec.update({
        "invoice_id": invoice_id,
        "dispute_id": None,
        "amount_cents": amount,
        "authority_tier": tier,
        "justification": justification,
        "applied_by_user_id": user_id,
        "status": "PROPOSED",
    })
    db.waivers[rec["id"]] = rec
    if tier == "TIER_1_AGENT" and actor_rank >= 1:
        # auto-apply
        _apply_credit_to_accruals(inv, amount, exclude_waiver_id=rec["id"])
        rec["status"] = "APPLIED"
        S.recompute_invoice_derived(inv)
        if inv["balance_due_cents"] == 0:
            inv["status"] = "PAID"
        S.touch(inv)
        S.recompute_account_outstanding(inv["customer_account_id"])
        S.aging_posture_sweep()
    return success_object(ser_waiver(rec), 201)


@app.get("/ocean-billing/credit-waivers/<waiver_id>")
def get_waiver(waiver_id):
    require_roles("ContractManager", "BillingAgent", "CreditSupervisor", "CreditDirector", "CustomerRep")
    w = _get_waiver(waiver_id)
    return success_object(ser_waiver(w))


@app.post("/ocean-billing/credit-waivers/<waiver_id>/approve")
def approve_waiver(waiver_id):
    user_id, role = require_roles("CreditSupervisor", "CreditDirector")
    w = _get_waiver(waiver_id)
    body = _payload()
    _require_fields(body, ["expected_waiver_version"])
    if w["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Waiver not PROPOSED")
    expected = body["expected_waiver_version"]
    if not isinstance(expected, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_waiver_version must be int")
    if expected != w["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "Stale waiver version")
    inv = _get_invoice(w["invoice_id"])
    if inv["status"] in ("PAID", "WRITTEN_OFF"):
        raise ApiError(ERR_INVOICE_ALREADY_SETTLED, 409, "Invoice settled")
    S.recompute_invoice_derived(inv)
    if w["amount_cents"] > inv["balance_due_cents"]:
        raise ApiError(ERR_CREDIT_EXCEEDS_BALANCE, 422, "Credit exceeds balance")
    actor_rank = _ROLE_TIER[role]
    needed_rank = _TIER_RANK[w["authority_tier"]]
    if actor_rank < needed_rank:
        raise ApiError(ERR_WAIVER_AUTHORITY_EXCEEDED, 403, "Authority tier insufficient")
    if w["applied_by_user_id"] == user_id:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403, "Approver cannot be proposer")
    _apply_credit_to_accruals(inv, w["amount_cents"], exclude_waiver_id=w["id"])
    w["status"] = "APPLIED"
    S.touch(w)
    S.recompute_invoice_derived(inv)
    if inv["balance_due_cents"] == 0:
        inv["status"] = "PAID"
    S.touch(inv)
    S.recompute_account_outstanding(inv["customer_account_id"])
    S.aging_posture_sweep()
    return success_object(ser_waiver(w))


@app.post("/ocean-billing/credit-waivers/<waiver_id>/reject")
def reject_waiver(waiver_id):
    require_roles("CreditSupervisor", "CreditDirector")
    w = _get_waiver(waiver_id)
    if w["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, 409, "Waiver not PROPOSED")
    w["status"] = "REJECTED"
    S.touch(w)
    return success_object(ser_waiver(w))


@app.post("/ocean-billing/credit-waivers/<waiver_id>/reverse")
def reverse_waiver(waiver_id):
    user_id, role = require_roles("CreditDirector")
    w = _get_waiver(waiver_id)
    body = _payload()
    justification = body.get("justification")
    if not justification or not str(justification).strip():
        raise ApiError(ERR_JUSTIFICATION_REQUIRED, 422, "justification required")
    if w["status"] != "APPLIED":
        raise ApiError(ERR_INVALID_STATE, 409, "Waiver not APPLIED")
    inv = _get_invoice(w["invoice_id"])
    if inv["status"] == "PAID":
        raise ApiError(ERR_INVOICE_ALREADY_SETTLED, 409, "Invoice PAID")
    S.recompute_invoice_derived(inv)
    # After reversal, credit_total_cents decreases by amount; the new credit
    # total is credit_total - amount. Paid must not exceed gross - new_credit.
    new_credit = inv["credit_total_cents"] - w["amount_cents"]
    if inv["paid_total_cents"] > inv["gross_amount_cents"] - new_credit:
        raise ApiError(ERR_REVERSAL_EXCEEDS_NET, 422, "Reversal exceeds net")
    w["status"] = "REVERSED"
    S.touch(w)
    # Recompute accrual voids: recompute cumulative credits per component
    _recompute_accrual_voids(inv)
    S.recompute_invoice_derived(inv)
    S.touch(inv)
    S.recompute_account_outstanding(inv["customer_account_id"])
    S.aging_posture_sweep()
    return success_object(ser_waiver(w))


def _recompute_accrual_voids(invoice):
    """Reset and re-derive accrual voided flags from the current APPLIED credit set."""
    container_id = invoice["container_id"]
    for a in db.accruals.values():
        if a["container_id"] == container_id:
            a["voided"] = False
    det_total = invoice["detention_total_cents"]
    dem_total = invoice["demurrage_total_cents"]
    det_credited = 0
    dem_credited = 0
    prior = [w for w in db.waivers.values()
             if w["invoice_id"] == invoice["id"] and w["status"] == "APPLIED"]
    for w in sorted(prior, key=lambda x: x["created_at"]):
        remaining = w["amount_cents"]
        cdt = min(remaining, det_total - det_credited)
        det_credited += cdt
        remaining -= cdt
        cdm = min(remaining, dem_total - dem_credited)
        dem_credited += cdm
    if det_total > 0 and det_credited == det_total:
        _void_component_accruals(container_id, "DETENTION")
    if dem_total > 0 and dem_credited == dem_total:
        _void_component_accruals(container_id, "DEMURRAGE")


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
