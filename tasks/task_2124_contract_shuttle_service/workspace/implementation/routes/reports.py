"""ServicePeriodReport endpoints (PRD 3.8)."""

from flask import Blueprint

import calc
import store
from envelope import created, ok, paginate, pagination
from errors import ApiError
from guards import (ALL_ROLES, authorize, body, equality_filter, id_field,
                    must_exist, validate_body)
from store import touch

bp = Blueprint("reports", __name__)

CREATE_SPEC = [
    id_field("contract_id"),
    {"name": "period_start_date", "kind": "date"},
    {"name": "period_end_date", "kind": "date"},
]
DISPUTE_SPEC = [{"name": "dispute_reason", "kind": "string", "min_len": 1}]


@bp.post("/service-period-reports")
def create_report():
    authorize(["ClientLiaison", "ContractAdmin"])
    data = validate_body(body(), CREATE_SPEC)
    contract = must_exist(store.contracts, data["contract_id"], "ERR_CONTRACT_NOT_FOUND")
    start = data["period_start_date"]
    end = data["period_end_date"]
    if start > end or start < contract["term_start_date"] or end > contract["term_end_date"]:
        raise ApiError("ERR_PERIOD_OUT_OF_TERM")
    for existing in store.service_period_reports.values():
        if existing["contract_id"] != contract["id"]:
            continue
        if start <= existing["period_end_date"] and existing["period_start_date"] <= end:
            raise ApiError("ERR_PERIOD_OVERLAP")

    row = store.base_row()
    row.update({
        "contract_id": contract["id"],
        "period_start_date": start,
        "period_end_date": end,
        "status": "DRAFT",
        "settlement_variant": "NONE",
        "revision_round": 0,
        "submitted_by_user_id": None,
        "approved_by_user_id": None,
        "dispute_reason": None,
        "effective_rate_cents_per_service_hour": 0,
    })
    for field in calc.SETTLEMENT_FIGURES:
        row[field] = 0
    store.register_new(row)
    store.service_period_reports[row["id"]] = row
    return created(store.public(row))


@bp.get("/service-period-reports/<rid>")
def get_report(rid):
    authorize(ALL_ROLES)
    return ok(store.public(must_exist(store.service_period_reports, rid,
                                      "ERR_REPORT_NOT_FOUND")))


@bp.get("/service-period-reports")
def list_reports():
    authorize(ALL_ROLES)
    limit, offset = pagination()
    rows = list(store.service_period_reports.values())
    rows = equality_filter(rows, "contract_id", "contract_id")
    rows = equality_filter(rows, "status", "status")
    rows.sort(key=store.sort_key_created)
    return paginate(rows, limit, offset, store.public)


@bp.post("/service-period-reports/<rid>/submit")
def submit_report(rid):
    caller = authorize(["ClientLiaison", "ContractAdmin"])
    report = must_exist(store.service_period_reports, rid, "ERR_REPORT_NOT_FOUND")
    if report["status"] not in ("DRAFT", "DISPUTED"):
        raise ApiError("ERR_REPORT_NOT_SUBMITTABLE")
    contract = store.contracts.get(report["contract_id"])
    if report["status"] == "DISPUTED":
        report["revision_round"] += 1
    report["effective_rate_cents_per_service_hour"] = (
        contract["base_rate_cents_per_service_hour"] if contract else 0)
    calc.compute_settlement(report, contract, "PROVISIONAL")
    report["submitted_by_user_id"] = caller.user_id
    report["status"] = "SUBMITTED"
    touch(report)
    return ok(store.public(report))


@bp.post("/service-period-reports/<rid>/approve")
def approve_report(rid):
    caller = authorize(["ContractAdmin"])
    report = must_exist(store.service_period_reports, rid, "ERR_REPORT_NOT_FOUND")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED")
    contract = store.contracts.get(report["contract_id"])
    if contract is None or contract["status"] not in calc.ACTIVE_CONTRACT_STATES:
        raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
    if caller.user_id == report["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    input_set, memos = calc.compute_settlement(report, contract, "FINAL")
    report["approved_by_user_id"] = caller.user_id
    report["status"] = "APPROVED"
    touch(report)

    # cascade 1 — the period's ISSUED memos are consumed by this report
    if memos:
        for memo in memos:
            memo["status"] = "APPLIED"
            memo["applied_report_id"] = report["id"]
            touch(memo)
        calc.recompute_contract_credit_balance(contract)

    # cascade 2 — the settled trips move UNBILLED -> BILLED
    for trip in input_set:
        if trip["settlement_status"] == "UNBILLED":
            trip["settlement_status"] = "BILLED"
            touch(trip)
    return ok(store.public(report))


@bp.post("/service-period-reports/<rid>/dispute")
def dispute_report(rid):
    authorize(["ClientLiaison"])
    data = validate_body(body(), DISPUTE_SPEC)
    report = must_exist(store.service_period_reports, rid, "ERR_REPORT_NOT_FOUND")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_NOT_SUBMITTED")
    report["dispute_reason"] = data["dispute_reason"]
    report["status"] = "DISPUTED"
    calc.zero_settlement(report)
    touch(report)
    return ok(store.public(report))
