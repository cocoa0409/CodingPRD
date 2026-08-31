"""Selections: proposal, the decision fork, rescission and notice delivery."""
from flask import Blueprint

from core import ApiError, db, iso_ms, ok, ok_list, parse_date, touch
from domain import (latest_analysis, recompute_plan, selection_offers, state_rule)
from selection_ops import (apply_exempt, apply_rescind, apply_select,
                           create_selection, guard_duplicate, guard_scores,
                           guard_warn_window)
from serialize import selection_out
from validation import (READER_ROLES, bad, body, endpoint, must_exist, opt_bool,
                        opt_str, paginate, pagination, parse_criterion_scores,
                        query_enum, query_str, req_date, req_enum, req_str)

bp = Blueprint("selections", __name__)

SELECTION_STATUSES = ("PROPOSED", "SELECTED", "EXEMPTED", "RESCINDED", "SEPARATED")
SCRIPT_CODES = ("MANAGER_SCRIPT_STANDARD", "MANAGER_SCRIPT_REMOTE", "MANAGER_SCRIPT_UNION")
LIVE_OFFER_STATUSES = ("ISSUED", "SIGNED", "EFFECTIVE")


@bp.route("/selections", methods=["POST"])
@endpoint(["RestructuringLead"])
def create_selection_route():
    payload = body()
    plan_id = req_str(payload, "plan_id")
    employee_id = req_str(payload, "employee_id")
    proposed_date = req_date(payload, "proposed_separation_date")
    scores = parse_criterion_scores(payload)

    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404)
    employee = db.employees.get(employee_id)
    if employee is None:
        raise ApiError("ERR_EMPLOYEE_NOT_FOUND", 404)

    if plan["criteria_status"] != "LOCKED":
        raise ApiError("ERR_CRITERIA_NOT_LOCKED", 422)

    guard_warn_window(employee, proposed_date)
    guard_duplicate(plan["id"], employee["id"])
    guard_scores(plan, scores)

    record = create_selection(plan, employee, proposed_date, scores)
    recompute_plan(plan)
    return ok(selection_out(record), 201)


@bp.route("/selections/<selection_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_selection(selection_id):
    return ok(selection_out(must_exist("selections", selection_id)))


@bp.route("/selections", methods=["GET"])
@endpoint(READER_ROLES)
def list_selections():
    limit, offset = pagination()
    plan_id = query_str("plan_id")
    employee_id = query_str("employee_id")
    status = query_enum("status", SELECTION_STATUSES)

    rows = sorted(db.selections.values(), key=lambda r: r["_seq"])
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if employee_id is not None:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list([selection_out(r) for r in page], limit, offset, total)


@bp.route("/selections/<selection_id>/decide", methods=["POST"])
@endpoint(["RestructuringLead"])
def decide_selection(selection_id):
    payload = body()
    decision = req_enum(payload, "decision", ("SELECT", "EXEMPT"))
    exemption_reason = opt_str(payload, "exemption_reason", None, allow_empty=False)
    if decision == "EXEMPT" and (exemption_reason is None or exemption_reason.strip() == ""):
        raise bad("Field 'exemption_reason' is required for an EXEMPT decision.")

    selection = must_exist("selections", selection_id)
    plan = db.plans[selection["plan_id"]]

    if selection["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if plan["approval_status"] == "APPROVED":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)
    if plan["approval_status"] == "EXECUTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if decision == "SELECT" and plan["criteria_status"] != "LOCKED":
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    if decision == "SELECT":
        apply_select(selection)
    else:
        apply_exempt(selection, exemption_reason)
    return ok(selection_out(selection))


@bp.route("/selections/<selection_id>/rescind", methods=["POST"])
@endpoint(["RestructuringLead"])
def rescind_selection(selection_id):
    payload = body()
    reason = req_str(payload, "rescind_reason")

    selection = must_exist("selections", selection_id)
    plan = db.plans[selection["plan_id"]]

    if selection["status"] != "SELECTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if plan["approval_status"] == "EXECUTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    for offer in selection_offers(selection["id"]):
        if offer["status"] in LIVE_OFFER_STATUSES:
            raise ApiError("ERR_INVALID_OFFER_STATE", 409)

    apply_rescind(selection, reason)
    return ok(selection_out(selection))


@bp.route("/selections/<selection_id>/deliver-notice", methods=["POST"])
@endpoint(["RestructuringLead"])
def deliver_notice(selection_id):
    payload = body()
    script_code = req_enum(payload, "script_code", SCRIPT_CODES)
    acknowledge = opt_bool(payload, "acknowledge_short_notice", False)

    selection = must_exist("selections", selection_id)
    plan = db.plans[selection["plan_id"]]
    employee = db.employees.get(selection["employee_id"])
    site = db.sites.get(employee["site_id"]) if employee is not None else None

    if selection["status"] != "SELECTED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)
    if selection["notice_status"] == "DELIVERED":
        raise ApiError("ERR_INVALID_SELECTION_STATE", 409)

    analysis = latest_analysis(plan["id"])
    if analysis is None or analysis["status"] != "CLEARED":
        raise ApiError("ERR_IMPACT_ANALYSIS_NOT_CLEARED", 422)

    delivered_at = db.clock
    proposed = parse_date(selection["proposed_separation_date"])
    days_before = (proposed - delivered_at.date()).days
    required = site["required_notice_days"] if site is not None else 0
    short = days_before < required
    if short and not acknowledge:
        raise ApiError("ERR_NOTICE_PERIOD_INSUFFICIENT", 422)

    if plan["approval_status"] != "APPROVED":
        raise ApiError("ERR_PLAN_NOT_APPROVED", 422)

    if site is not None:
        rule = state_rule(site["state_code"])
        if rule is not None and "UNION_NOTICE" in rule["required_content_codes"]:
            if script_code != "MANAGER_SCRIPT_UNION":
                raise ApiError("ERR_SCRIPT_JURISDICTION_MISMATCH", 422)

    selection["notice_status"] = "DELIVERED"
    selection["notice_delivered_utc"] = iso_ms(delivered_at)
    selection["notice_script_code"] = script_code
    selection["notice_days_before_separation"] = days_before
    selection["short_notice_acknowledged"] = bool(short)
    touch(selection)
    return ok(selection_out(selection))
