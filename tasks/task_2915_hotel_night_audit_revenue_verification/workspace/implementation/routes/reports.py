"""Revenue reports: the day's published snapshot, guarded by a version token."""
from flask import Blueprint

import db
import response
import shapes
from constants import PACE_BASES, PREFIX
from errors import ApiError
from middleware import (ALL_ROLES, CONTROLLER, NIGHT_AUDITOR, REVENUE_MANAGER,
                        authenticate)
from money import q2
from services import calc, derive, lookup, serial

bp = Blueprint("reports", __name__, url_prefix=PREFIX)

READY_STATES = ("SETTLEMENT_REVIEW", "BALANCED", "REOPENED")


@bp.route("/revenue-reports", methods=["POST"])
def create_report():
    user_id, _role = authenticate([REVENUE_MANAGER, NIGHT_AUDITOR])
    body = shapes.parse([
        shapes.Field("business_date_id", "string", required=True),
        shapes.Field("recipient_role_list", "array", required=True),
        shapes.Field("expected_business_date_version", "integer", required=True),
        shapes.Field("pace_basis", "string", enum=PACE_BASES,
                     default="CALENDAR_ALIGNED"),
    ])
    for entry in body["recipient_role_list"]:
        if not isinstance(entry, str):
            shapes.bad("recipient_role_list must hold role names.")
    date_row = lookup.get_date(body["business_date_id"])
    lookup.require_not_archived(date_row)
    if date_row["status"] not in READY_STATES:
        raise ApiError("ERR_DATE_NOT_READY_TO_BALANCE",
                       "The operating day is not ready to be reported on.")
    if int(body["expected_business_date_version"]) != int(date_row["version"]):
        raise ApiError("ERR_STALE_BUSINESS_DATE_VERSION",
                       "The operating day has moved since it was read.")
    figures = derive.date_aggregates(date_row)
    basis = body["pace_basis"] or "CALENDAR_ALIGNED"
    if basis == "WEEKDAY_ALIGNED":
        benchmark = q2(date_row["benchmark_weekday_room_revenue_amount"])
    else:
        benchmark = q2(date_row["benchmark_calendar_room_revenue_amount"])
    derive.supersede_reports(date_row)
    row = db.insert("reports", {
        "_kind": "RevenueReport",
        "business_date_id": date_row["id"],
        "pace_basis": basis,
        "rooms_available_count": figures["rooms_available_count"],
        "rooms_occupied_count": figures["rooms_occupied_count"],
        "occupancy_pct": figures["occupancy_pct"],
        "adr_amount": figures["adr_amount"],
        "revpar_amount": figures["revpar_amount"],
        "room_revenue_amount": figures["room_revenue_amount"],
        "tax_revenue_amount": figures["tax_revenue_amount"],
        "outlet_revenue_amount": figures["outlet_revenue_amount"],
        "total_revenue_amount": figures["total_revenue_amount"],
        "benchmark_room_revenue_amount": benchmark,
        "pace_index_pct": calc.pace_index_pct(
            figures["room_revenue_amount"], benchmark
        ),
        "status": "DRAFT",
        "recipient_role_list": list(body["recipient_role_list"]),
        "distributed_at": None,
        "generated_by_user_id": user_id,
    })
    derive.touch(date_row)
    return response.created(serial.report_out(row))


@bp.route("/revenue-reports/<row_id>/distribute", methods=["POST"])
def distribute_report(row_id):
    _user_id, _role = authenticate([REVENUE_MANAGER, CONTROLLER])
    body = shapes.parse([shapes.Field("recipient_role_list", "array")])
    report = lookup.get_report(row_id)
    date_row = db.store.business_dates.get(report["business_date_id"])
    if date_row is not None:
        lookup.require_not_archived(date_row)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_NOT_DRAFT",
                       "Only a draft report may be distributed.")
    recipients = report["recipient_role_list"]
    if body["recipient_role_list"] is not None:
        for entry in body["recipient_role_list"]:
            if not isinstance(entry, str):
                shapes.bad("recipient_role_list must hold role names.")
        recipients = list(body["recipient_role_list"])
    if not recipients:
        raise ApiError("ERR_DISTRIBUTION_LIST_EMPTY",
                       "A report must name at least one recipient role.")
    report["recipient_role_list"] = recipients
    report["status"] = "DISTRIBUTED"
    report["distributed_at"] = db.now()
    derive.touch(report)
    return response.ok(serial.report_out(report))


@bp.route("/revenue-reports/<row_id>", methods=["GET"])
def get_report(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.report_out(lookup.get_report(row_id)))


@bp.route("/revenue-reports", methods=["GET"])
def list_reports():
    authenticate(ALL_ROLES)
    rows = db.all_of("reports")
    for key in ("business_date_id", "status", "pace_basis"):
        value = shapes.q(key)
        if value is not None:
            rows = [r for r in rows if r[key] == value]
    items, meta = shapes.page(rows, serial.report_out)
    return response.collection(items, meta)
