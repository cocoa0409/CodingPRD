"""WARN statute rows and jurisdictional notices."""
from datetime import timedelta

from flask import Blueprint

from core import (ApiError, apply_changes, base_record, date_at_midnight, date_str,
                  db, iso_ms, num, ok, ok_list, touch)
from calc import warn_determination
from domain import plan_selections, rule_for, site_employees
from serialize import notice_out, rule_out
from validation import (READER_ROLES, body, endpoint, must_exist, paginate,
                        pagination, query_enum, query_str, req_bool, req_enum,
                        req_int, req_num, req_state_code, req_str, req_str_list)

bp = Blueprint("warn", __name__)

JURISDICTIONS = ("FEDERAL", "STATE")
NOTICE_STATUSES = ("DRAFT", "ISSUED", "VOID")


# ---------------------------------------------------------------------------
# WarnRule
# ---------------------------------------------------------------------------
@bp.route("/warn-rules", methods=["POST"])
@endpoint(["SystemAdmin"])
def create_warn_rule():
    payload = body()
    jurisdiction = req_enum(payload, "jurisdiction", JURISDICTIONS)
    state_code = req_state_code(payload, "state_code")
    rule_code = req_str(payload, "rule_code")
    min_loss_count = req_int(payload, "min_loss_count", 0)
    min_percent = req_num(payload, "min_percent", 0)
    absolute_count = req_int(payload, "absolute_count", 0)
    notice_days = req_int(payload, "notice_days", 0)
    window_days = req_int(payload, "window_days", 0)
    counts_part_time = req_bool(payload, "counts_part_time")
    min_service_days = req_int(payload, "min_service_days", 0)
    required_content_codes = req_str_list(payload, "required_content_codes")

    for existing in db.warn_rules.values():
        if (existing["jurisdiction"] == jurisdiction
                and existing["state_code"] == state_code):
            raise ApiError("ERR_WARN_RULE_ALREADY_EXISTS", 409)

    record = base_record(versioned=False)
    record.update({
        "jurisdiction": jurisdiction,
        "state_code": state_code,
        "rule_code": rule_code,
        "min_loss_count": min_loss_count,
        "min_percent": min_percent,
        "absolute_count": absolute_count,
        "notice_days": notice_days,
        "window_days": window_days,
        "counts_part_time": counts_part_time,
        "min_service_days": min_service_days,
        "required_content_codes": list(required_content_codes),
    })
    db.warn_rules[record["id"]] = record
    return ok(rule_out(record), 201)


@bp.route("/warn-rules/<rule_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_warn_rule(rule_id):
    return ok(rule_out(must_exist("warn_rules", rule_id)))


# ---------------------------------------------------------------------------
# WarnNotice
# ---------------------------------------------------------------------------
@bp.route("/warn-notices", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def create_warn_notice():
    payload = body()
    plan_id = req_str(payload, "plan_id")
    site_id = req_str(payload, "site_id")
    jurisdiction = req_enum(payload, "jurisdiction", JURISDICTIONS)
    content_codes = req_str_list(payload, "content_codes")

    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404)
    site = db.sites.get(site_id)
    if site is None:
        raise ApiError("ERR_SITE_NOT_FOUND", 404)

    rule = rule_for(site, jurisdiction)
    if rule is None:
        raise ApiError("ERR_WARN_RULE_NOT_FOUND", 404)

    determination = warn_determination(site_employees(site["id"]), rule)
    if determination["workforce_count"] == 0:
        raise ApiError("ERR_WARN_WORKFORCE_EMPTY", 422)

    window_start = determination["window_start_date"]
    window_end = determination["window_end_date"]
    threshold_met = determination["threshold_met"]
    required_notice_days = int(rule["notice_days"])
    if threshold_met and window_start is not None:
        deadline = iso_ms(date_at_midnight(window_start) - timedelta(days=required_notice_days))
    else:
        deadline = None

    record = base_record()
    record.update({
        "plan_id": plan["id"],
        "site_id": site["id"],
        "jurisdiction": jurisdiction,
        "content_codes": list(content_codes),
        "applied_rule_code": rule["rule_code"],
        "employment_loss_count": determination["employment_loss_count"],
        "workforce_count": determination["workforce_count"],
        "loss_percent": num(determination["loss_percent"]),
        "threshold_met": threshold_met,
        "trigger_type": determination["trigger_type"],
        "required_notice_days": required_notice_days,
        "window_start_date": date_str(window_start),
        "window_end_date": date_str(window_end),
        "notice_deadline_utc": deadline,
        "status": "DRAFT",
        "issued_utc": None,
    })
    db.notices[record["id"]] = record
    return ok(notice_out(record), 201)


@bp.route("/warn-notices/<notice_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_warn_notice(notice_id):
    return ok(notice_out(must_exist("notices", notice_id)))


@bp.route("/warn-notices", methods=["GET"])
@endpoint(READER_ROLES)
def list_warn_notices():
    limit, offset = pagination()
    plan_id = query_str("plan_id")
    site_id = query_str("site_id")
    jurisdiction = query_enum("jurisdiction", JURISDICTIONS)
    status = query_enum("status", NOTICE_STATUSES)

    rows = sorted(db.notices.values(), key=lambda r: r["_seq"])
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if site_id is not None:
        rows = [r for r in rows if r["site_id"] == site_id]
    if jurisdiction is not None:
        rows = [r for r in rows if r["jurisdiction"] == jurisdiction]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list([notice_out(r) for r in page], limit, offset, total)


@bp.route("/warn-notices/<notice_id>/issue", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def issue_warn_notice(notice_id):
    notice = must_exist("notices", notice_id)
    if notice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_NOTICE_STATE", 409)
    if not notice["threshold_met"]:
        raise ApiError("ERR_INVALID_NOTICE_STATE", 409)

    site = db.sites.get(notice["site_id"])
    rule = rule_for(site, notice["jurisdiction"]) if site is not None else None
    required = list(rule["required_content_codes"]) if rule is not None else []
    carried = set(notice["content_codes"])
    for code in required:
        if code not in carried:
            raise ApiError("ERR_WARN_CONTENT_INCOMPLETE", 422)

    notice["status"] = "ISSUED"
    notice["issued_utc"] = iso_ms(db.clock)
    touch(notice)

    plan = db.plans.get(notice["plan_id"])
    if plan is not None and plan["warn_status"] == "THRESHOLD_PENDING":
        site_ids = []
        for selection in plan_selections(plan["id"]):
            if selection["status"] != "SELECTED":
                continue
            employee = db.employees.get(selection["employee_id"])
            if employee is not None and employee["site_id"] not in site_ids:
                site_ids.append(employee["site_id"])
        covered = True
        for candidate_id in site_ids:
            candidate = db.sites.get(candidate_id)
            if candidate is None or candidate["warn_trigger_status"] == "NONE":
                continue
            issued = any(n["plan_id"] == plan["id"] and n["site_id"] == candidate_id
                         and n["status"] == "ISSUED" for n in db.notices.values())
            if not issued:
                covered = False
                break
        if covered:
            apply_changes(plan, {"warn_status": "NOTICES_ISSUED"})

    return ok(notice_out(notice))
