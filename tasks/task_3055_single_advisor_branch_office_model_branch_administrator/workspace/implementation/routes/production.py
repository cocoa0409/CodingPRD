"""Production record routes (§3.4)."""
from decimal import Decimal
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, parse_dt, get_or_404, stamp_new, touch,
    paginate, sort_by_created_at, round_half_up_cents, recompute_advisor_cumulative,
)
from response import success_object, success_list

bp = Blueprint("production", __name__)
PREFIX = "/branch-office/production-records"


@bp.route(PREFIX, methods=["POST"])
def create_production_record():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["advisor_id", "gross_commission_cents", "payout_rate", "posted_at"])
    advisor = get_or_404(db.advisors, body["advisor_id"], "Advisor")
    gross = body["gross_commission_cents"]
    if isinstance(gross, bool) or not isinstance(gross, int) or gross <= 0:
        raise err("ERR_INVALID_REQUEST", "gross_commission_cents must be a positive integer.")
    rate = body["payout_rate"]
    if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not (0 < rate <= 1):
        raise err("ERR_INVALID_REQUEST", "payout_rate must be > 0 and <= 1.")
    posted = parse_dt(body["posted_at"], "posted_at")
    commissions = round_half_up_cents(Decimal(gross) * Decimal(str(rate)))
    record = stamp_new({
        "advisor_id": advisor["id"],
        "gross_commission_cents": gross,
        "payout_rate": rate,
        "commissions_cents": commissions,
        "posted_at": db.iso_format(posted),
        "status": "POSTED",
    }, with_version=False)
    db.production_records[record["id"]] = record
    recompute_advisor_cumulative(advisor)
    touch(advisor)
    return success_object(record, 201)


@bp.route(f"{PREFIX}/<rid>/reverse", methods=["POST"])
def reverse_production_record(rid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    record = get_or_404(db.production_records, rid, "ProductionRecord")
    if record.get("status") != "POSTED":
        raise err("ERR_INVALID_STATE", "Production record is not POSTED.")
    record["status"] = "REVERSED"
    advisor = db.advisors.get(record.get("advisor_id"))
    if advisor is not None:
        recompute_advisor_cumulative(advisor)
        touch(advisor)
    return success_object(record)


@bp.route(PREFIX, methods=["GET"])
def list_production_records():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    items = list(db.production_records.values())
    advisor_id = request.args.get("advisor_id")
    if advisor_id:
        items = [r for r in items if r.get("advisor_id") == advisor_id]
    status = request.args.get("status")
    if status:
        items = [r for r in items if r.get("status") == status]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)
