"""PayrollRun endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import (
    public,
    new_entity, paginate, touch, now_iso, now_dt,
    parse_datetime, normalize_date_only, fmt_ts, fmt_ts_seconds, add_business_days,
)
from services_strikes import apply_funding_strike, cancel_scheduled_deposits_for_run

bp = Blueprint("payroll", __name__)

READ_ROLES = {"BureauCompliance", "BureauTreasury", "BureauTaxFiler", "ClientPayrollAdmin"}


def run_view(r):
    return public(r)


def _get_run(run_id):
    r = store.payroll_runs.get(run_id)
    if not r:
        raise errors.not_found("Payroll run not found")
    return r


@bp.route("/payroll-runs", methods=["POST"])
def create_run():
    auth = authenticate()
    require_roles(auth, {"ClientPayrollAdmin"})
    body = request.get_json(silent=True) or {}

    client_id = body.get("client_id")
    if not client_id:
        raise errors.invalid_request("client_id is required")
    # Entity-backed identity: must equal client_id being touched
    check_client_identity(auth, client_id)
    client = store.clients.get(client_id)
    if not client:
        raise errors.not_found("Client not found")

    for field in ("pay_date", "period_start", "period_end", "gross_pay_cents", "total_tax_cents"):
        if body.get(field) is None:
            raise errors.invalid_request(f"{field} is required")

    for f in ("gross_pay_cents", "total_tax_cents"):
        v = body[f]
        if not isinstance(v, int) or isinstance(v, bool):
            raise errors.invalid_request(f"{f} must be an integer")
        if v < 0:
            raise errors.invalid_request(f"{f} must be >= 0")

    pay_date = parse_datetime(body["pay_date"])
    period_start = parse_datetime(body["period_start"])
    period_end = parse_datetime(body["period_end"])
    if pay_date is None or period_start is None or period_end is None:
        raise errors.invalid_request("Invalid datetime format")
    pay_date = normalize_date_only(pay_date)
    if period_end < period_start:
        raise errors.invalid_request("period_end must be >= period_start")

    run = new_entity({
        "client_id": client_id,
        "pay_date": fmt_ts(pay_date),
        "period_start": fmt_ts(period_start),
        "period_end": fmt_ts(period_end),
        "gross_pay_cents": body["gross_pay_cents"],
        "total_tax_cents": body["total_tax_cents"],
        "impound_amount_cents": body["gross_pay_cents"] + body["total_tax_cents"],
        "status": "DRAFT",
        "funding_model": None,
        "funding_confirmed_at": None,
    })
    store.payroll_runs[run["id"]] = run
    return success_object(run_view(run), status=201)


@bp.route("/payroll-runs", methods=["GET"])
def list_runs():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.payroll_runs.values())
    if auth.role == "ClientPayrollAdmin":
        items = [r for r in items if r["client_id"] == auth.user_id]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [r for r in items if r["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([run_view(r) for r in page], limit, offset, total)


@bp.route("/payroll-runs/<runId>", methods=["GET"])
def get_run(runId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    r = _get_run(runId)
    check_client_identity(auth, r["client_id"])
    return success_object(run_view(r))


@bp.route("/payroll-runs/<runId>/submit", methods=["POST"])
def submit_run(runId):
    auth = authenticate()
    require_roles(auth, {"ClientPayrollAdmin"})
    r = _get_run(runId)
    check_client_identity(auth, r["client_id"])
    if r["status"] != "DRAFT":
        raise errors.invalid_state("Run must be DRAFT to submit")
    # Business: gross_pay > 0 and total_tax >= 0 (ERR_INVALID_REQUEST), then client ACTIVE
    if r["gross_pay_cents"] <= 0 or r["total_tax_cents"] < 0:
        raise errors.invalid_request("gross_pay_cents must be > 0 and total_tax_cents >= 0")
    client = store.clients[r["client_id"]]
    if client["status"] != "ACTIVE":
        raise errors.client_not_active("Client is not ACTIVE")
    r["funding_model"] = "WIRE_REQUIRED" if client["risk_posture"] == "HIGH" else "STANDARD"
    r["status"] = "SUBMITTED"
    touch(r)
    return success_object(run_view(r))


@bp.route("/payroll-runs/<runId>/initiate-impound", methods=["POST"])
def initiate_impound(runId):
    auth = authenticate()
    require_roles(auth, {"ClientPayrollAdmin"})
    r = _get_run(runId)
    check_client_identity(auth, r["client_id"])
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_client_version")
    client = store.clients[r["client_id"]]
    # Request-shape validation (OCC guard input) precedes the state and
    # business checks, per the §2.8 validation priority order.
    if expected is None:
        raise errors.invalid_request("expected_client_version is required")
    if expected != client["version"]:
        raise errors.stale_version("expected_client_version does not match Client.version")
    # Client credit gates (§3.4) precede the run's own state gate: a suspended
    # or held client is refused with its dedicated error even when the run is
    # not yet SUBMITTED.
    if client["status"] != "ACTIVE":
        raise errors.client_not_active("Client is not ACTIVE")
    if client["credit_hold"]:
        raise errors.credit_hold_active("Credit hold blocks impound initiation")
    if r["status"] != "SUBMITTED":
        raise errors.invalid_state("Run must be SUBMITTED to initiate impound")

    initiated = now_dt()
    if r["funding_model"] == "WIRE_REQUIRED":
        due_by = initiated.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        due_by = add_business_days(initiated, 2)

    imp = new_entity({
        "payroll_run_id": r["id"],
        "client_id": r["client_id"],
        "amount_cents": r["impound_amount_cents"],
        "initiated_at": fmt_ts(initiated),
        "due_by": fmt_ts_seconds(due_by),
        "settled_at": None,
        "status": "PENDING",
    })
    store.impounds[imp["id"]] = imp
    r["status"] = "IMPOUNDED"
    touch(r)
    touch(client)
    return success_object(public(imp), status=201)


@bp.route("/payroll-runs/<runId>/cancel", methods=["POST"])
def cancel_run(runId):
    auth = authenticate()
    require_roles(auth, {"ClientPayrollAdmin"})
    r = _get_run(runId)
    check_client_identity(auth, r["client_id"])
    if r["status"] != "SUBMITTED":
        raise errors.invalid_state("Run must be SUBMITTED to cancel")
    r["status"] = "CANCELLED"
    touch(r)
    return success_object(run_view(r))


@bp.route("/payroll-runs/<runId>/reverse", methods=["POST"])
def reverse_run(runId):
    auth = authenticate()
    require_roles(auth, {"BureauTreasury"})
    r = _get_run(runId)
    if r["status"] != "IMPOUNDED":
        raise errors.invalid_state("Run must be IMPOUNDED to reverse")
    # Find the run's impound
    imp = None
    for i in store.impounds.values():
        if i["payroll_run_id"] == r["id"]:
            imp = i
            break
    if imp is None or imp["status"] != "PENDING":
        raise errors.invalid_state("Run's impound is not PENDING")
    imp["status"] = "FAILED"
    touch(imp)
    client = store.clients[r["client_id"]]
    apply_funding_strike(client, imp, "NSF_RETURN")
    r["status"] = "REVERSED"
    touch(r)
    cancel_scheduled_deposits_for_run(r["id"])
    return success_object(run_view(r))
