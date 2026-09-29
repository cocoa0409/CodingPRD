"""Gross receipts reporting — PRD 3.8."""
import calc
from auth import ALL_ROLES, fetch, guard, require_owner
from envelope import created, listing, ok
from errors import ApiError
from logic import LIVE_REPORT_STATES, covering_plan, half_open_overlap, lease_of
from money import add_days, parse_date
from router import route
from shape import body, ref, req_date, req_int, req_str
from store import db, insert, touch

CATEGORY_FIELDS = ("lodging_receipts_cents", "food_beverage_receipts_cents",
                   "retail_receipts_cents", "activity_receipts_cents")


def _recompute(report, lease):
    total = sum(report[field] for field in CATEGORY_FIELDS)
    report["total_receipts_cents"] = total
    report["assessed_fee_cents"] = calc.period_fee(
        lease["base_fee_pct"],
        report["lodging_receipts_cents"],
        report["food_beverage_receipts_cents"],
        report["retail_receipts_cents"],
        report["activity_receipts_cents"],
    )
    report["maintenance_reserve_due_cents"] = calc.maintenance_reserve_due(total)


@route("/gross-receipts-reports", methods=["POST"])
def reports_create():
    guard("Concessionaire")
    data = body()
    lease = None
    lease_ref = ref(data, "lease_id")
    if lease_ref is not None:
        lease = fetch(db.leases, lease_ref, "ERR_LEASE_NOT_FOUND")
        require_owner(lease["offeror_id"])
    row = {
        "lease_id": req_str(data, "lease_id"),
        "operating_plan_id": None,
        "period_start": req_date(data, "period_start")[0],
        "period_end": req_date(data, "period_end")[0],
        "lodging_receipts_cents": req_int(data, "lodging_receipts_cents", minimum=0),
        "food_beverage_receipts_cents": req_int(data, "food_beverage_receipts_cents", minimum=0),
        "retail_receipts_cents": req_int(data, "retail_receipts_cents", minimum=0),
        "activity_receipts_cents": req_int(data, "activity_receipts_cents", minimum=0),
        "total_receipts_cents": 0,
        "assessed_fee_cents": 0,
        "maintenance_reserve_due_cents": 0,
        "remittance_received_cents": None,
        "restated_receipts_cents": None,
        "rejection_note": None,
        "status": "SUBMITTED",
    }
    start = parse_date(row["period_start"])
    end = parse_date(row["period_end"])
    if not start < end:
        raise ApiError("ERR_INVALID_INTERVAL",
                       "period_start must be strictly before its exclusive period_end")
    if lease["contract_status"] != "ACTIVE":
        raise ApiError("ERR_LEASE_NOT_ACTIVE", "The lease is not ACTIVE")
    plan = covering_plan(lease["id"], start, end)
    if plan is None:
        raise ApiError("ERR_NO_APPROVED_OPERATING_PLAN",
                       "No approved season covers the whole reporting period")
    term_start = parse_date(lease["term_start"])
    term_limit = add_days(parse_date(lease["term_end"]), 1)
    if start < term_start or end > term_limit:
        raise ApiError("ERR_PERIOD_OUTSIDE_TERM",
                       "The reporting period falls outside the contract term")
    for other in db.reports.values():
        if other["lease_id"] != lease["id"] or other["status"] not in LIVE_REPORT_STATES:
            continue
        if half_open_overlap(start, end,
                            parse_date(other["period_start"]), parse_date(other["period_end"])):
            raise ApiError("ERR_REPORT_PERIOD_OVERLAP",
                           "The period intersects a live report on this lease")
    row["operating_plan_id"] = plan["id"]
    report = insert(db.reports, row)
    _recompute(report, lease)
    return created(report)


@route("/gross-receipts-reports/<report_id>/accept", methods=["POST"])
def reports_accept(report_id):
    guard("ContractingOfficer")
    report = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    data = body()
    remittance = req_int(data, "remittance_received_cents")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_STATUS_INVALID",
                       "Report status %s cannot be accepted" % report["status"])
    if remittance != report["assessed_fee_cents"]:
        raise ApiError("ERR_REMITTANCE_MISMATCH",
                       "The remittance does not equal the assessed fee")
    report["remittance_received_cents"] = remittance
    report["status"] = "ACCEPTED"
    touch(report)
    lease = lease_of(report)
    if lease is not None:
        lease["reported_receipts_ytd_cents"] = \
            lease["reported_receipts_ytd_cents"] + report["total_receipts_cents"]
        lease["remitted_fee_ytd_cents"] = lease["remitted_fee_ytd_cents"] + remittance
        lease["maintenance_reserve_balance_cents"] = \
            lease["maintenance_reserve_balance_cents"] + report["maintenance_reserve_due_cents"]
        touch(lease)
    return ok(report)


@route("/gross-receipts-reports/<report_id>/reject", methods=["POST"])
def reports_reject(report_id):
    guard("ContractingOfficer")
    report = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    data = body()
    note = req_str(data, "rejection_note")
    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_REPORT_STATUS_INVALID",
                       "Report status %s cannot be rejected" % report["status"])
    report["rejection_note"] = note
    report["status"] = "REJECTED"
    touch(report)
    return ok(report)


@route("/gross-receipts-reports/<report_id>/amend", methods=["POST"])
def reports_amend(report_id):
    guard("Concessionaire")
    report = fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND")
    lease = lease_of(report)
    require_owner(lease["offeror_id"] if lease is not None else None)
    data = body()
    amounts = {}
    for field in CATEGORY_FIELDS:
        amounts[field] = req_int(data, field, minimum=0)
    if report["status"] != "REJECTED":
        raise ApiError("ERR_REPORT_STATUS_INVALID",
                       "Report status %s cannot be amended" % report["status"])
    for field in CATEGORY_FIELDS:
        report[field] = amounts[field]
    report["rejection_note"] = None
    report["status"] = "SUBMITTED"
    if lease is not None:
        _recompute(report, lease)
    touch(report)
    return ok(report)


@route("/gross-receipts-reports", methods=["GET"])
def reports_list():
    guard(*ALL_ROLES)
    return listing(db.reports, ("lease_id", "operating_plan_id", "status"))


@route("/gross-receipts-reports/<report_id>", methods=["GET"])
def reports_read(report_id):
    guard(*ALL_ROLES)
    return ok(fetch(db.reports, report_id, "ERR_REPORT_NOT_FOUND"))
