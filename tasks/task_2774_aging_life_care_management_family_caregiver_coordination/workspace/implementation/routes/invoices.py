"""The retainer ledger, invoice lifecycle and payment posting."""
from flask import Blueprint

import auth
import clock
import derive
import envelope
import lookup
import serialize
import validators as v
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("invoices", __name__)

INVOICE_STATUSES = ("DRAFT", "ISSUED", "PAID", "VOIDED")
BLOCKING_STATUSES = ("DRAFT", "ISSUED", "PAID")

FILTERS = {"client_id": "client_id", "status": "status"}

MONEY_FIELDS = ("variant", "line_entry_ids", "line_subtotal_cents",
                "admin_fee_cents", "total_due_cents", "retainer_applied_cents",
                "balance_due_cents")


def _store_money(record, computed):
    for key in MONEY_FIELDS:
        record[key] = computed[key]


@bp.route("/care/invoices", methods=["POST"])
def create_invoice():
    auth.actor_for(auth.ROLE_BILLING)
    body = v.json_body()
    client_id = v.req_str(body, "client_id", 1, None)
    period_start = v.req_date(body, "period_start")
    period_end = v.req_date(body, "period_end")
    if period_end < period_start:
        raise v.bad("'period_end' may not fall earlier than 'period_start'.")
    client = lookup.need_client(client_id)
    if client["status"] == "DISCHARGED":
        raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                       "An invoice may not be opened for a discharged client.")
    for other in db.invoices.values():
        if other["client_id"] != client_id:
            continue
        if other["status"] not in BLOCKING_STATUSES:
            continue
        if other["period_start"] <= period_end and \
                period_start <= other["period_end"]:
            raise ApiError("ERR_INVOICE_PERIOD_OVERLAP",
                           "Another live invoice already covers part of this "
                           "billing period.")
    draft = {
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
    }
    computed = derive.invoice_totals(draft, "PROVISIONAL")
    if not computed["line_entry_ids"]:
        raise ApiError("ERR_NO_BILLABLE_ACTIVITY",
                       "No billable activity falls inside this period.")
    record = new_record({
        "client_id": client_id,
        "period_start": period_start,
        "period_end": period_end,
        "amount_paid_cents": 0,
        "status": "DRAFT",
        "issued_at": None,
        "voided_reason": None,
    })
    _store_money(record, computed)
    db.invoices[record["id"]] = record
    return envelope.created(serialize.invoice(record))


@bp.route("/care/invoices", methods=["GET"])
def list_invoices():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.invoices.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, FILTERS, v.filters(FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.invoice(r) for r in records], limit, offset)


@bp.route("/care/invoices/<invoice_id>", methods=["GET"])
def read_invoice(invoice_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_invoice(invoice_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.invoice(record))


@bp.route("/care/invoices/<invoice_id>/state", methods=["PATCH"])
def invoice_state(invoice_id):
    auth.actor_for(auth.ROLE_BILLING)
    body = v.json_body()
    to_state = v.req_enum(body, "to_state", INVOICE_STATUSES)
    reason = v.opt_str(body, "reason")
    record = lookup.need_invoice(invoice_id)
    client = db.clients[record["client_id"]]
    if to_state == "ISSUED":
        _issue(record, client)
    elif to_state == "VOIDED":
        _void(record, client, reason)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s may not be requested." % to_state)
    return envelope.ok(serialize.invoice(record))


def _issue(record, client):
    if record["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "ISSUED is only reachable from DRAFT.")
    if client["status"] == "DISCHARGED":
        raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                       "The client is discharged.")
    computed = derive.invoice_totals(record, "FINAL")
    if not computed["line_entry_ids"]:
        raise ApiError("ERR_NO_BILLABLE_ACTIVITY",
                       "No supervisor-approved activity remains on this "
                       "period.")
    _store_money(record, computed)
    record["issued_at"] = clock.now()
    record["status"] = "ISSUED"
    for entry_id in computed["line_entry_ids"]:
        entry = db.time_entries[entry_id]
        entry["status"] = "INVOICED"
        entry["invoice_id"] = record["id"]
        touch(entry)
    touch(record)
    if client["status"] == "ACTIVE_CARE" and \
            derive.retainer_balance(client["id"]) < \
            client["retainer_floor_cents"] and \
            record["balance_due_cents"] > 0:
        derive.suspend_client_for_nonpayment(client)
    touch(client)


def _void(record, client, reason):
    if record["status"] == "DRAFT":
        _store_money(record, derive.invoice_totals(record, "PROVISIONAL"))
        record["voided_reason"] = reason
        record["status"] = "VOIDED"
        touch(record)
        return
    if record["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "VOIDED is not reachable from %s." % record["status"])
    if record["amount_paid_cents"] != 0:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A partly or fully paid invoice must be settled another "
                       "way.")
    record["voided_reason"] = reason
    record["status"] = "VOIDED"
    touch(record)
    derive.release_invoice_entries(record)
    derive.restore_client_from_nonpayment(client)
    touch(client)


@bp.route("/care/invoices/<invoice_id>/payments", methods=["POST"])
def post_payment(invoice_id):
    auth.actor_for(auth.ROLE_BILLING)
    body = v.json_body()
    amount_cents = v.req_int(body, "amount_cents", 1)
    v.req_dt(body, "received_at")
    v.req_str(body, "method", 1, None)
    record = lookup.need_invoice(invoice_id)
    if record["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A payment may only be posted against an ISSUED "
                       "invoice.")
    proposed = record["amount_paid_cents"] + amount_cents
    if proposed > record["balance_due_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE",
                       "The payment exceeds the balance still due.")
    record["amount_paid_cents"] = proposed
    if proposed == record["balance_due_cents"]:
        record["status"] = "PAID"
    touch(record)
    return envelope.ok(serialize.invoice(record))
