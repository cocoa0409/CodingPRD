"""Post-event savings reports (PRD section 3.9)."""
from flask import Blueprint

import clock
import db as store
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from money import q2
from services import calc, flows, rollups

bp = Blueprint("reports", __name__)

REPORT_EVENT_STATUSES = ("CONTRACTED", "COMPLETED")


@bp.route("/sourcing/events/<event_id>/post-event-report", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def file_report(event_id):
    event = lookup.event(event_id)
    data = validate.body()
    actual_room_nights = validate.req_int(data, "actual_room_nights", minimum=0)
    actual_fnb = validate.req_money(data, "actual_fnb_usd")
    actual_av = validate.req_money(data, "actual_av_usd")
    notes = validate.opt_str(data, "notes", max_len=1000)

    if event["status"] not in REPORT_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "This event cannot be closed out in its current status")

    if clock.now() <= clock.day_end(event["end_date"]):
        raise ApiError("ERR_EVENT_NOT_CONCLUDED",
                       "The meeting has not concluded yet")

    if lookup.reports_of_event(event["id"]):
        raise ApiError("ERR_POST_EVENT_REPORT_EXISTS",
                       "This event already has a post-event report")

    contract = lookup.executed_contract_of_event(event["id"])
    if contract is None:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "This event has no executed contract to close out")
    venue = db.venues[contract["venue_id"]]
    benchmark = flows.require_benchmark(venue, event)

    if actual_room_nights > contract["contracted_paid_room_nights"]:
        raise ApiError("ERR_ACTUALS_EXCEED_CONTRACT",
                       "actual_room_nights exceeds the contracted paid nights")

    figures = calc.post_event_savings(
        contract, event, benchmark["benchmark_adr_usd"], actual_room_nights,
        actual_fnb, actual_av,
    )
    report = store.base_row()
    report.update({
        "event_id": event["id"],
        "contract_id": contract["id"],
        "actual_room_nights": actual_room_nights,
        "actual_fnb_usd": q2(actual_fnb),
        "actual_av_usd": q2(actual_av),
        "attrition_allowed_nights": figures["attrition_allowed_nights"],
        "attrition_shortfall_nights": figures["attrition_shortfall_nights"],
        "attrition_charge_usd": figures["attrition_charge_usd"],
        "actual_room_cost_usd": figures["actual_room_cost_usd"],
        "realized_service_charge_usd": figures["realized_service_charge_usd"],
        "realized_tax_usd": figures["realized_tax_usd"],
        "realized_total_usd": figures["realized_total_usd"],
        "benchmark_room_cost_usd": figures["benchmark_room_cost_usd"],
        "savings_vs_benchmark_usd": figures["savings_vs_benchmark_usd"],
        "savings_vs_budget_usd": figures["savings_vs_budget_usd"],
        "notes": notes,
    })
    db.reports[report["id"]] = report

    venue["blocked_room_nights"] = (
        venue["blocked_room_nights"] - contract["contracted_paid_room_nights"]
    )
    touch(venue)

    event["status"] = "COMPLETED"
    event["savings_recognized_usd"] = figures["savings_vs_budget_usd"]
    event["committed_spend_usd"] = figures["realized_total_usd"]
    rollups.refresh_budget_envelope(event)
    touch(event)
    return response.obj(serializers.report(report), 201)


@bp.route("/sourcing/post-event-reports/<report_id>", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def get_report(report_id):
    return response.obj(serializers.report(lookup.report(report_id)))


@bp.route("/sourcing/post-event-reports", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_reports():
    limit, offset = validate.pagination()
    event_id = validate.str_filter("event_id")
    contract_id = validate.str_filter("contract_id")
    rows = store.ordered(db.reports.values())
    if event_id is not None:
        rows = [r for r in rows if r["event_id"] == event_id]
    if contract_id is not None:
        rows = [r for r in rows if r["contract_id"] == contract_id]
    return validate.page(rows, limit, offset, serializers.report)
