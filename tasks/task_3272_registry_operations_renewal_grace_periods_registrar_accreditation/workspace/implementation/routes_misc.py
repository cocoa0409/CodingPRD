import db
import clock
from util import fmt_iso
from services import invoice_view, ledger_view, abuse_view, court_view
from middleware import require_roles, body_json, require_fields, pagination_params
from response import success_object, success_list
from errors import err_invalid_request, err_not_found, err_invalid_state, ApiError
from flask import Blueprint, request

bp = Blueprint("misc", __name__)

ABUSE_CATEGORIES = {"PHISHING", "MALWARE", "SPAM", "OTHER"}
COURT_ACTIONS = {"SUSPEND", "UNSUSPEND", "TRANSFER_TO_REGISTRY"}


# ---- invoices ----

@bp.get("/invoices")
def list_invoices():
    require_roles("RegistryAdmin", "RegistryFinance", "RegistrarOperator")
    limit, offset = pagination_params()
    rows = sorted(db.invoices.values(), key=lambda i: i["created_at"])
    for key in ("registrar_id", "domain_id", "kind", "status", "price_schedule_id"):
        v = request.args.get(key)
        if v:
            rows = [i for i in rows if str(i[key]) == v]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([invoice_view(i) for i in page], limit, offset, total)


@bp.get("/invoices/<iid>")
def get_invoice(iid):
    require_roles("RegistryAdmin", "RegistryFinance", "RegistrarOperator")
    i = db.invoices.get(iid)
    if i is None:
        raise err_not_found()
    return success_object(invoice_view(i))


# ---- ledger entries ----

@bp.get("/ledger-entries")
def list_ledger_entries():
    require_roles("RegistryAdmin", "RegistryFinance", "RegistrarOperator")
    limit, offset = pagination_params()
    rows = sorted(db.ledger_entries.values(), key=lambda e: e["created_at"])
    for key in ("registrar_id", "invoice_id"):
        v = request.args.get(key)
        if v:
            rows = [e for e in rows if str(e[key]) == v]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([ledger_view(e) for e in page], limit, offset, total)


@bp.get("/ledger-entries/<eid>")
def get_ledger_entry(eid):
    require_roles("RegistryAdmin", "RegistryFinance", "RegistrarOperator")
    e = db.ledger_entries.get(eid)
    if e is None:
        raise err_not_found()
    return success_object(ledger_view(e))


# ---- abuse reports ----

@bp.post("/abuse-reports")
def create_abuse_report():
    require_roles("AbuseAnalyst", "RegistryAdmin")
    data = body_json()
    require_fields(data, ["domain_id", "reporter_contact", "category", "detail"])
    did = data["domain_id"]
    if not isinstance(did, str):
        raise err_invalid_request("domain_id must be a string")
    d = db.domains.get(did)
    if d is None:
        raise err_not_found("domain_id does not exist")
    if data["category"] not in ABUSE_CATEGORIES:
        raise err_invalid_request("category must be one of PHISHING, MALWARE, SPAM, OTHER")
    for f in ("reporter_contact", "detail"):
        if not isinstance(data[f], str):
            raise err_invalid_request(f"{f} must be a string")
    rec = db.new_common(clock.now())
    rec.update({
        "domain_id": did,
        "reporter_contact": data["reporter_contact"],
        "category": data["category"],
        "detail": data["detail"],
        "status": "FILED",
    })
    db.abuse_reports[rec["id"]] = rec
    return success_object(abuse_view(rec), 201)


@bp.get("/abuse-reports")
def list_abuse_reports():
    require_roles("AbuseAnalyst", "RegistryAdmin")
    limit, offset = pagination_params()
    rows = sorted(db.abuse_reports.values(), key=lambda a: a["created_at"])
    did = request.args.get("domain_id")
    status = request.args.get("status")
    if did:
        rows = [a for a in rows if a["domain_id"] == did]
    if status:
        rows = [a for a in rows if a["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([abuse_view(a) for a in page], limit, offset, total)


@bp.get("/abuse-reports/<aid>")
def get_abuse_report(aid):
    require_roles("AbuseAnalyst", "RegistryAdmin")
    a = db.abuse_reports.get(aid)
    if a is None:
        raise err_not_found()
    return success_object(abuse_view(a))


def _get_report_or_404(aid):
    a = db.abuse_reports.get(aid)
    if a is None:
        raise err_not_found()
    return a


@bp.post("/abuse-reports/<aid>/review")
def review_report(aid):
    require_roles("AbuseAnalyst")
    a = _get_report_or_404(aid)
    if a["status"] != "FILED":
        raise err_invalid_state()
    a["status"] = "UNDER_REVIEW"
    db.touch(a, clock.now())
    return success_object(abuse_view(a))


@bp.post("/abuse-reports/<aid>/requeue")
def requeue_report(aid):
    require_roles("AbuseAnalyst")
    a = _get_report_or_404(aid)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state()
    a["status"] = "FILED"
    db.touch(a, clock.now())
    return success_object(abuse_view(a))


@bp.post("/abuse-reports/<aid>/resolve")
def resolve_report(aid):
    require_roles("AbuseAnalyst")
    a = _get_report_or_404(aid)
    if a["status"] != "UNDER_REVIEW":
        raise err_invalid_state()
    data = body_json()
    require_fields(data, ["action"])
    action = data["action"]
    if action not in ("ACTIONED", "DISMISSED"):
        raise err_invalid_request("action must be ACTIONED or DISMISSED")
    a["status"] = action
    db.touch(a, clock.now())
    if action == "ACTIONED":
        d = db.domains.get(a["domain_id"])
        if d is not None:
            d["suspension_status"] = "HOLD"
            db.touch(d, clock.now())
    return success_object(abuse_view(a))


# ---- court orders ----

@bp.post("/court-orders")
def create_court_order():
    import engine
    require_roles("RegistryAdmin")
    data = body_json()
    require_fields(data, ["case_reference", "domain_id", "action", "effective_immediately"])
    case_ref = data["case_reference"]
    if not isinstance(case_ref, str) or not case_ref:
        raise err_invalid_request("case_reference must be a non-empty string")
    did = data["domain_id"]
    if not isinstance(did, str):
        raise err_invalid_request("domain_id must be a string")
    d = db.domains.get(did)
    if d is None:
        raise err_not_found("domain_id does not exist")
    if data["action"] not in COURT_ACTIONS:
        raise err_invalid_request("action must be SUSPEND, UNSUSPEND, or TRANSFER_TO_REGISTRY")
    if not isinstance(data["effective_immediately"], bool):
        raise err_invalid_request("effective_immediately must be boolean")
    for c in db.court_orders.values():
        if c["case_reference"] == case_ref:
            raise ApiError("ERR_DUPLICATE_CASE_REFERENCE", "case_reference already lodged", 409)
    rec = db.new_common(clock.now())
    rec.update({
        "case_reference": case_ref,
        "domain_id": did,
        "action": data["action"],
        "effective_immediately": data["effective_immediately"],
        "status": "LODGED",
    })
    db.court_orders[rec["id"]] = rec
    if rec["effective_immediately"]:
        engine._enforce_court_order(rec)
    return success_object(court_view(rec), 201)


@bp.get("/court-orders")
def list_court_orders():
    require_roles("RegistryAdmin", "AbuseAnalyst")
    limit, offset = pagination_params()
    rows = sorted(db.court_orders.values(), key=lambda c: c["created_at"])
    did = request.args.get("domain_id")
    status = request.args.get("status")
    if did:
        rows = [c for c in rows if c["domain_id"] == did]
    if status:
        rows = [c for c in rows if c["status"] == status]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([court_view(c) for c in page], limit, offset, total)


@bp.get("/court-orders/<cid>")
def get_court_order(cid):
    require_roles("RegistryAdmin", "AbuseAnalyst")
    c = db.court_orders.get(cid)
    if c is None:
        raise err_not_found()
    return success_object(court_view(c))
