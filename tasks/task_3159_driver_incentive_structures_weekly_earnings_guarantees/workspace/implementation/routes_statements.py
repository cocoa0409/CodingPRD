"""EarningsStatement endpoints."""
from flask import Blueprint, request

import db
from errors import err_invalid_request, err_invalid_state, err_statement_settlements_open
from middleware import require_roles
from response import success_list, success_object
from services import (
    get_driver_or_404,
    get_statement_or_404,
    new_entity,
    paginate,
    parse_iso,
    statement_compute_fields,
    statement_view,
    touch,
)

bp = Blueprint("statements", __name__)


def _fmt_week(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


@bp.post("/statements/compute")
@require_roles("PaymentsOfficer")
def compute_statement(_user_id, _role):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("JSON body must be an object")
    driver_id = body.get("driver_id")
    if not isinstance(driver_id, str):
        raise err_invalid_request("driver_id is required")
    driver = get_driver_or_404(driver_id)
    week_start_raw = body.get("week_start_utc")
    if not isinstance(week_start_raw, str):
        raise err_invalid_request("week_start_utc is required")
    week_start = parse_iso(week_start_raw, "week_start_utc")

    base, tips, bonus, make_up, adjustments, total = statement_compute_fields(driver, week_start)
    s = new_entity(
        {
            "driver_id": driver["id"],
            "week_start_utc": _fmt_week(week_start),
            "base_fares_cents": base,
            "tips_cents_total": tips,
            "bonus_total_cents": bonus,
            "make_up_total_cents": make_up,
            "adjustments_cents": adjustments,
            "total_cents": total,
            "status": "DRAFT",
        }
    )
    db.statements[s["id"]] = s
    return success_object(statement_view(s), 201)


@bp.get("/statements/<sid>")
@require_roles("PlatformAdmin", "PaymentsOfficer", "Driver")
def get_statement(sid, _user_id, _role):
    s = get_statement_or_404(sid)
    return success_object(statement_view(s))


@bp.get("/statements")
@require_roles("PlatformAdmin", "PaymentsOfficer")
def list_statements(_user_id, _role):
    items = list(db.statements.values())
    driver_id = request.args.get("driver_id")
    status = request.args.get("status")
    if driver_id is not None:
        items = [s for s in items if s["driver_id"] == driver_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, limit, offset, total = paginate(items, request.args)
    return success_list([statement_view(s) for s in page], limit, offset, total)


@bp.post("/statements/<sid>/publish")
@require_roles("PaymentsOfficer")
def publish_statement(sid, _user_id, _role):
    s = get_statement_or_404(sid)
    if s["status"] != "DRAFT":
        raise err_invalid_state("Statement must be DRAFT to publish")
    week_start = parse_iso(s["week_start_utc"])
    for st in db.settlements.values():
        if (
            st["driver_id"] == s["driver_id"]
            and parse_iso(st["week_start_utc"]) == week_start
            and st["status"] in ("DRAFT", "FINALIZED", "REOPENED")
        ):
            raise err_statement_settlements_open()
    s["status"] = "PUBLISHED"
    touch(s)
    return success_object(statement_view(s))
