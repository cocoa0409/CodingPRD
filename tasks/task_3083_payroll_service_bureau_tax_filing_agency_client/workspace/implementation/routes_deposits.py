"""TaxDeposit endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import (
    public,
    new_entity, paginate, touch, now_iso, parse_datetime, fmt_ts, fmt_ts_seconds,
)
from services_calc import deposit_due_date, quarter_of, compute_late_fields, registration_for

bp = Blueprint("deposits", __name__)

READ_ROLES = {"BureauCompliance", "BureauTaxFiler", "BureauTreasury", "ClientPayrollAdmin"}


def dep_view(d):
    out = public(d)
    if d["status"] == "CONFIRMED":
        jur = store.jurisdictions.get(d["jurisdiction_id"])
        if jur:
            late_days, penalty = compute_late_fields(d, jur)
            out["late_days"] = late_days
            out["penalty_exposure_cents"] = penalty
    return out


def _get_deposit(deposit_id):
    d = store.deposits.get(deposit_id)
    if not d:
        raise errors.not_found("Deposit not found")
    return d


@bp.route("/payroll-runs/<runId>/deposits", methods=["POST"])
def create_deposit(runId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    run = store.payroll_runs.get(runId)
    if not run:
        raise errors.not_found("Payroll run not found")
    body = request.get_json(silent=True) or {}

    jurisdiction_id = body.get("jurisdiction_id")
    if not jurisdiction_id:
        raise errors.invalid_request("jurisdiction_id is required")
    jur = store.jurisdictions.get(jurisdiction_id)
    if not jur:
        raise errors.not_found("Jurisdiction not found")

    amount = body.get("amount_cents")
    if amount is None:
        raise errors.invalid_request("amount_cents is required")
    if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
        raise errors.invalid_request("amount_cents must be a non-negative integer")

    expected = body.get("expected_payroll_run_version")
    if expected is None:
        raise errors.invalid_request("expected_payroll_run_version is required")

    if not jur.get("active", True):
        raise errors.invalid_request("Inactive jurisdiction cannot receive deposits")

    # OCC check on PayrollRun.version
    if expected != run["version"]:
        raise errors.stale_version("expected_payroll_run_version does not match PayrollRun.version")

    # Duplicate booking check
    for d in store.deposits.values():
        if d["payroll_run_id"] == runId and d["jurisdiction_id"] == jurisdiction_id \
                and d["status"] in ("SCHEDULED", "SUBMITTED"):
            raise errors.duplicate_deposit("Duplicate deposit for run and jurisdiction")

    # Cumulative cap
    cumulative = amount
    for d in store.deposits.values():
        if d["payroll_run_id"] == runId and d["status"] in ("SCHEDULED", "SUBMITTED", "CONFIRMED"):
            cumulative += d["amount_cents"]
    if cumulative > run["total_tax_cents"]:
        raise errors.deposit_exceeds_liability("Deposits exceed run total_tax_cents")

    pay_date = parse_datetime(run["pay_date"])
    due = deposit_due_date(jur["deposit_frequency"], pay_date)
    dep = new_entity({
        "client_id": run["client_id"],
        "jurisdiction_id": jurisdiction_id,
        "payroll_run_id": runId,
        "amount_cents": amount,
        "due_date": fmt_ts_seconds(due),
        "quarter": quarter_of(pay_date),
        "status": "SCHEDULED",
        "submitted_at": None,
        "confirmed_at": None,
        "late_days": 0,
        "penalty_exposure_cents": 0,
    })
    store.deposits[dep["id"]] = dep
    touch(run)
    return success_object(dep_view(dep), status=201)


@bp.route("/deposits", methods=["GET"])
def list_deposits():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.deposits.values())
    if auth.role == "ClientPayrollAdmin":
        items = [d for d in items if d["client_id"] == auth.user_id]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [d for d in items if d["client_id"] == cid]
    jid = request.args.get("jurisdiction_id")
    if jid is not None:
        items = [d for d in items if d["jurisdiction_id"] == jid]
    prid = request.args.get("payroll_run_id")
    if prid is not None:
        items = [d for d in items if d["payroll_run_id"] == prid]
    status = request.args.get("status")
    if status is not None:
        items = [d for d in items if d["status"] == status]
    quarter = request.args.get("quarter")
    if quarter is not None:
        items = [d for d in items if d["quarter"] == quarter]
    page, limit, offset, total = paginate(items)
    return success_list([dep_view(d) for d in page], limit, offset, total)


@bp.route("/deposits/<depositId>", methods=["GET"])
def get_deposit(depositId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    d = _get_deposit(depositId)
    check_client_identity(auth, d["client_id"])
    return success_object(dep_view(d))


@bp.route("/deposits/<depositId>/submit", methods=["POST"])
def submit_deposit(depositId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    d = _get_deposit(depositId)
    if d["status"] != "SCHEDULED":
        raise errors.invalid_state("Deposit must be SCHEDULED to submit")
    run = store.payroll_runs[d["payroll_run_id"]]
    if run["status"] != "SETTLED":
        raise errors.funds_not_settled("Backing run is not SETTLED")
    reg = registration_for(d["client_id"], d["jurisdiction_id"])
    if not reg or reg["status"] != "VERIFIED":
        raise errors.registration_not_verified("Registration is not VERIFIED")
    d["status"] = "SUBMITTED"
    d["submitted_at"] = now_iso()
    touch(d)
    return success_object(dep_view(d))


@bp.route("/deposits/<depositId>/confirm", methods=["POST"])
def confirm_deposit(depositId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    d = _get_deposit(depositId)
    if d["status"] != "SUBMITTED":
        raise errors.invalid_state("Deposit must be SUBMITTED to confirm")
    d["status"] = "CONFIRMED"
    d["confirmed_at"] = now_iso()
    jur = store.jurisdictions.get(d["jurisdiction_id"])
    late_days, penalty = compute_late_fields(d, jur)
    d["late_days"] = late_days
    d["penalty_exposure_cents"] = penalty
    touch(d)
    return success_object(dep_view(d))


@bp.route("/deposits/<depositId>/fail", methods=["POST"])
def fail_deposit(depositId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    d = _get_deposit(depositId)
    if d["status"] != "SUBMITTED":
        raise errors.invalid_state("Deposit must be SUBMITTED to fail")
    d["status"] = "FAILED"
    touch(d)
    return success_object(dep_view(d))


@bp.route("/deposits/<depositId>/reschedule", methods=["POST"])
def reschedule_deposit(depositId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    d = _get_deposit(depositId)
    if d["status"] != "FAILED":
        raise errors.invalid_state("Deposit must be FAILED to reschedule")
    d["status"] = "SCHEDULED"
    d["submitted_at"] = None
    touch(d)
    return success_object(dep_view(d))


@bp.route("/deposits/<depositId>/cancel", methods=["POST"])
def cancel_deposit(depositId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    d = _get_deposit(depositId)
    if d["status"] != "SCHEDULED":
        raise errors.invalid_state("Only SCHEDULED deposits can be cancelled manually")
    d["status"] = "CANCELLED"
    touch(d)
    return success_object(dep_view(d))
