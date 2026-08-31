"""Adverse-impact analyses and OWBPA decisional-unit disclosures."""
from flask import Blueprint, g

from calc import OWBPA_PROTECTED_AGE, POOL_STATUSES, SELECTED_STATUSES, adverse_impact
from core import (ApiError, base_record, completed_years, db, iso_ms, num, ok,
                  ok_list, parse_date, touch)
from domain import plan_selections
from serialize import analysis_out, disclosure_out
from validation import (READER_ROLES, body, endpoint, must_exist, paginate,
                        pagination, query_enum, query_str, req_enum, req_int,
                        req_str)

bp = Blueprint("compliance", __name__)

ANALYSIS_STATUSES = ("COMPUTED", "FLAGGED", "CLEARED", "SUPERSEDED", "STALE")
DISCLOSURE_STATUSES = ("ATTACHED", "SUPERSEDED", "STALE")
METHODS = ("IMPACT_RATIO", "STANDARD_DEVIATION")


# ---------------------------------------------------------------------------
# AdverseImpactAnalysis
# ---------------------------------------------------------------------------
@bp.route("/adverse-impact-analyses", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def create_analysis():
    payload = body()
    plan_id = req_str(payload, "plan_id")
    method = req_enum(payload, "method", METHODS)
    expected_plan_version = req_int(payload, "expected_plan_version")

    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404)
    if expected_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_PLAN_VERSION", 412)

    pool_rows = []
    for selection in plan_selections(plan["id"]):
        if selection["status"] not in POOL_STATUSES:
            continue
        employee = db.employees.get(selection["employee_id"])
        if employee is None:
            continue
        pool_rows.append((selection["status"], employee["demographic_code"]))

    try:
        computed = adverse_impact(pool_rows, method)
    except ValueError:
        raise ApiError("ERR_IMPACT_ANALYSIS_INSUFFICIENT_DATA", 422)

    for existing in db.analyses.values():
        if (existing["plan_id"] == plan["id"]
                and existing["status"] in ("COMPUTED", "FLAGGED", "CLEARED")):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    record = base_record()
    record.update({
        "plan_id": plan["id"],
        "method": method,
        "status": computed["status"],
        "pool_count": computed["pool_count"],
        "selected_count": computed["selected_count"],
        "focal_class_code": computed["focal_class_code"],
        "focal_pool_count": computed["focal_pool_count"],
        "focal_selected_count": computed["focal_selected_count"],
        "focal_rate": num(computed["focal_rate"]),
        "reference_rate": num(computed["reference_rate"]),
        "impact_ratio": num(computed["impact_ratio"]),
        "standard_deviations": num(computed["standard_deviations"]),
        "shortfall_count": computed["shortfall_count"],
        "small_sample_suppressed": computed["small_sample_suppressed"],
        "justification": None,
        "cleared_by_user_id": None,
    })
    db.analyses[record["id"]] = record
    touch(plan)
    return ok(analysis_out(record), 201)


@bp.route("/adverse-impact-analyses/<analysis_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_analysis(analysis_id):
    return ok(analysis_out(must_exist("analyses", analysis_id)))


@bp.route("/adverse-impact-analyses", methods=["GET"])
@endpoint(READER_ROLES)
def list_analyses():
    limit, offset = pagination()
    plan_id = query_str("plan_id")
    status = query_enum("status", ANALYSIS_STATUSES)

    rows = sorted(db.analyses.values(), key=lambda r: r["_seq"])
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list([analysis_out(r) for r in page], limit, offset, total)


@bp.route("/adverse-impact-analyses/<analysis_id>/clear", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def clear_analysis(analysis_id):
    payload = body()
    justification = req_str(payload, "justification")
    analysis = must_exist("analyses", analysis_id)
    if analysis["status"] not in ("COMPUTED", "FLAGGED"):
        raise ApiError("ERR_INVALID_ANALYSIS_STATE", 409)
    analysis["status"] = "CLEARED"
    analysis["justification"] = justification
    analysis["cleared_by_user_id"] = g.user_id
    touch(analysis)
    return ok(analysis_out(analysis))


# ---------------------------------------------------------------------------
# OwbpaDisclosure
# ---------------------------------------------------------------------------
@bp.route("/owbpa-disclosures", methods=["POST"])
@endpoint(["EmploymentCounsel"])
def create_disclosure():
    payload = body()
    plan_id = req_str(payload, "plan_id")

    plan = db.plans.get(plan_id)
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND", 404)

    anchor = parse_date(plan["earliest_separation_date"])
    if anchor is None:
        raise ApiError("ERR_INVALID_PLAN_STATE", 409)

    selections = plan_selections(plan["id"])
    unit_site_ids = set()
    for selection in selections:
        if selection["status"] not in POOL_STATUSES:
            continue
        employee = db.employees.get(selection["employee_id"])
        if employee is not None:
            unit_site_ids.add(employee["site_id"])

    selected_employee_ids = set(
        s["employee_id"] for s in selections if s["status"] in SELECTED_STATUSES
    )

    unit = [e for e in db.employees.values()
            if e["site_id"] in unit_site_ids
            and e["employment_status"] in ("ACTIVE", "PENDING_SEPARATION", "SEPARATED")]

    ages = {}
    eligible_count = 0
    selected_count = 0
    for employee in unit:
        age = completed_years(parse_date(employee["birth_date"]), anchor)
        if age >= OWBPA_PROTECTED_AGE:
            eligible_count += 1
        band = ages.setdefault(age, {"age": age, "selected_count": 0, "non_selected_count": 0})
        if employee["id"] in selected_employee_ids:
            band["selected_count"] += 1
            selected_count += 1
        else:
            band["non_selected_count"] += 1

    age_bands = [ages[key] for key in sorted(ages.keys())]
    min_age = min(ages.keys()) if ages else None
    max_age = max(ages.keys()) if ages else None

    for existing in db.disclosures.values():
        if (existing["plan_id"] == plan["id"]
                and existing["status"] in ("ATTACHED", "STALE")):
            existing["status"] = "SUPERSEDED"
            touch(existing)

    record = base_record()
    record.update({
        "plan_id": plan["id"],
        "decisional_unit_name": plan["decisional_unit_name"],
        "eligible_count": eligible_count,
        "selected_count": selected_count,
        "non_selected_count": len(unit) - selected_count,
        "min_age": min_age,
        "max_age": max_age,
        "age_bands": age_bands,
        "consideration_days": plan["owbpa_consideration_days"],
        "snapshot_selected_count": plan["selected_count"],
        "snapshot_pool_count": plan["pool_count"],
        "status": "ATTACHED",
        "generated_utc": iso_ms(db.clock),
    })
    db.disclosures[record["id"]] = record
    touch(plan)
    return ok(disclosure_out(record), 201)


@bp.route("/owbpa-disclosures/<disclosure_id>", methods=["GET"])
@endpoint(READER_ROLES)
def get_disclosure(disclosure_id):
    return ok(disclosure_out(must_exist("disclosures", disclosure_id)))


@bp.route("/owbpa-disclosures", methods=["GET"])
@endpoint(READER_ROLES)
def list_disclosures():
    limit, offset = pagination()
    plan_id = query_str("plan_id")
    status = query_enum("status", DISCLOSURE_STATUSES)

    rows = sorted(db.disclosures.values(), key=lambda r: r["_seq"])
    if plan_id is not None:
        rows = [r for r in rows if r["plan_id"] == plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]

    page, total = paginate(rows, limit, offset)
    return ok_list([disclosure_out(r) for r in page], limit, offset, total)
