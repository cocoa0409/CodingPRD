"""Billing statement issuance/settlement and recognition snapshot append."""
from flask import Blueprint

from authz import require_roles
from calc import compute_billing, recompute_billed_to_date
from envelope import success
from errors import api_err
from recognition import build_snapshot_fields
from routes_agreements import get_agreement_or_404
from serialize import snapshot_json, statement_json
from storage import DB, new_id, next_seq, now, touch
from timeutil import check_not_future_period
from validate import as_period, body, req_field

bp = Blueprint("billing", __name__)


@bp.route("/api/agreements/<agreement_id>/billing-statements", methods=["POST"])
def issue_statement(agreement_id):
    require_roles("FinanceController")
    agreement = get_agreement_or_404(agreement_id)
    data = body()
    period_raw = req_field(data, "period")
    period_tuple = as_period(period_raw, "period")
    check_not_future_period(period_tuple, now())
    if any(s["agreement_id"] == agreement_id and s["period_tuple"] == period_tuple
           for s in DB["statements"].values()):
        raise api_err("ERR_DUPLICATE_STATEMENT",
                      "a statement already exists for this agreement and period")
    if agreement["status"] != "ACTIVE":
        raise api_err("ERR_AGREEMENT_NOT_ACTIVE", "issuance requires an ACTIVE agreement")
    lines, total = compute_billing(agreement, period_tuple, "PROVISIONAL")
    ts = now()
    statement = {
        "id": new_id(), "agreement_id": agreement_id, "period": period_raw,
        "period_tuple": period_tuple, "status": "ISSUED", "line_items": lines,
        "provisional_total_usd": total, "final_total_usd": None, "adjustment_usd": None,
        "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq(),
    }
    DB["statements"][statement["id"]] = statement
    if recompute_billed_to_date(agreement):
        touch(agreement)
    return success(statement_json(statement), 201)


@bp.route("/api/billing-statements/<statement_id>/settle", methods=["POST"])
def settle_statement(statement_id):
    require_roles("FinanceController")
    statement = DB["statements"].get(statement_id)
    if statement is None:
        raise api_err("ERR_STATEMENT_NOT_FOUND", "billing statement does not exist")
    if statement["status"] != "ISSUED":
        raise api_err("ERR_INVALID_STATE", "statement is not ISSUED")
    agreement = DB["agreements"][statement["agreement_id"]]
    lines, total = compute_billing(agreement, statement["period_tuple"], "FINAL")
    statement["line_items"] = lines
    statement["final_total_usd"] = total
    statement["adjustment_usd"] = total - statement["provisional_total_usd"]
    statement["status"] = "SETTLED"
    touch(statement)
    if recompute_billed_to_date(agreement):
        touch(agreement)
    return success(statement_json(statement), 200)


@bp.route("/api/agreements/<agreement_id>/recognition-snapshots", methods=["POST"])
def append_snapshot(agreement_id):
    require_roles("FinanceController")
    agreement = get_agreement_or_404(agreement_id)
    fields = build_snapshot_fields(agreement)
    snapshot = {
        "id": new_id(), "_seq": next_seq(), "created_at": now(),
    }
    snapshot.update(fields)
    DB["snapshots"][snapshot["id"]] = snapshot
    return success(snapshot_json(snapshot), 201)
