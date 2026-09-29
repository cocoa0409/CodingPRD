"""Sustainability diversion reporting (PRD 3.9)."""

from flask import Blueprint

import constants as C
import serialize
import services
import store
import validators as V
from envelope import list_response, object_response, paginate
from errors import ApiError

bp = Blueprint("reports", __name__)


@bp.post("/diversion-reports")
def create_diversion_report():
    V.guard("ProgramAdmin")
    payload = V.body()
    period_start_at = V.ts_field(payload, "period_start_at")
    period_end_at = V.ts_field(payload, "period_end_at")
    supersedes_report_id = V.id_field(payload, "supersedes_report_id", required=False)
    if period_end_at <= period_start_at:
        raise ApiError("ERR_INVALID_TIME_WINDOW")
    if not services.whole_days_apart(period_start_at, period_end_at):
        raise ApiError("ERR_INVALID_TIME_WINDOW")

    superseded = None
    if supersedes_report_id is not None:
        superseded = store.require("diversion_reports", supersedes_report_id)

    for other in store.rows("diversion_reports"):
        if other["status"] not in ("DRAFT", "PUBLISHED"):
            continue
        if superseded is not None and other["id"] == superseded["id"]:
            continue
        if services.half_open_overlap(
            period_start_at, period_end_at, other["period_start_at"], other["period_end_at"]
        ):
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP")

    fields = {
        "period_start_at": period_start_at,
        "period_end_at": period_end_at,
        "supersedes_report_id": supersedes_report_id,
    }
    fields.update(services.diversion_metrics(period_start_at, period_end_at))
    fields["status"] = "DRAFT"
    fields["published_at"] = None
    row = store.create("diversion_reports", fields)
    return object_response(serialize.out(row), 201)


@bp.get("/diversion-reports/<report_id>")
def get_diversion_report(report_id):
    V.guard("ProgramAdmin", "MerchandisingManager")
    return object_response(serialize.out(store.require("diversion_reports", report_id)))


@bp.get("/diversion-reports")
def list_diversion_reports():
    V.guard("ProgramAdmin", "MerchandisingManager")
    limit, offset = V.pagination()
    status = V.enum_query("status", C.REPORT_STATUSES)
    supersedes_report_id = V.id_query("supersedes_report_id")
    if supersedes_report_id is not None:
        store.require("diversion_reports", supersedes_report_id)
    rows = store.rows("diversion_reports")
    if supersedes_report_id is not None:
        rows = [r for r in rows if r.get("supersedes_report_id") == supersedes_report_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(store.ordered(rows), limit, offset)
    return list_response(serialize.out_list(page), limit, offset, total)


@bp.post("/diversion-reports/<report_id>/publish")
def publish_diversion_report(report_id):
    V.guard("ProgramAdmin")
    report = store.require("diversion_reports", report_id)
    if report["status"] != "DRAFT":
        raise ApiError("ERR_REPORT_ALREADY_PUBLISHED")
    report["status"] = "PUBLISHED"
    report["published_at"] = store.now()
    store.touch(report)
    # Cross-entity effect: the restated report retires, its metrics frozen.
    superseded_id = report.get("supersedes_report_id")
    if superseded_id is not None:
        superseded = store.get("diversion_reports", superseded_id)
        if superseded is not None and superseded["status"] in ("DRAFT", "PUBLISHED"):
            superseded["status"] = "SUPERSEDED"
            store.touch(superseded)
    return object_response(serialize.out(report))
