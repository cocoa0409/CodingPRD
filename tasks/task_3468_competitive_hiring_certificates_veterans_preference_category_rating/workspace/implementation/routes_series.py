"""Occupational series and position classification endpoints (PRD 3.1)."""
import re

from flask import Blueprint

from auth import get_auth, require_roles
from calc import official_grade, provisional_grade, total_points
from envelope import success_list, success_object
from errors import fail, invalid_state, not_found
from serializers import position_out, series_out
from store import DB, base_fields, touch
from validate import (get_body, parse_pagination, req_bool, req_enum, req_int,
                      req_str)

bp = Blueprint("series", __name__)

SENSITIVITY = ["NONE", "SECRET", "TOP_SECRET"]


def get_series_or_404(series_id):
    row = DB.series.get(series_id)
    if row is None:
        not_found("series")
    return row


def get_position_or_404(position_id):
    row = DB.positions.get(position_id)
    if row is None:
        not_found("position")
    return row


@bp.route("/hiring/series", methods=["POST"])
def create_series():
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    body = get_body()
    series_code = req_str(body, "series_code")
    if not re.fullmatch(r"\d{4}", series_code):
        fail("ERR_INVALID_REQUEST", "series_code must be a 4-digit string")
    title = req_str(body, "title")
    min_grade = req_int(body, "min_grade", 5, 15)
    max_grade = req_int(body, "max_grade", 5, 15)
    if min_grade > max_grade:
        fail("ERR_INVALID_REQUEST", "min_grade must be <= max_grade")
    quals_base_months = req_int(body, "quals_base_months", 0)
    quals_step = req_int(body, "quals_months_per_grade_step", 0)
    allows_edu = req_bool(body, "allows_education_substitution")
    edu_cap = req_int(body, "education_substitution_cap_months", 0)
    positive_edu = req_bool(body, "positive_education_required")
    for s in DB.series.values():
        if s["series_code"] == series_code:
            fail("ERR_DUPLICATE_KEY", "series_code already exists")
    row = base_fields()
    row.update({
        "series_code": series_code, "title": title,
        "min_grade": min_grade, "max_grade": max_grade,
        "quals_base_months": quals_base_months,
        "quals_months_per_grade_step": quals_step,
        "allows_education_substitution": allows_edu,
        "education_substitution_cap_months": edu_cap,
        "positive_education_required": positive_edu,
    })
    DB.series[row["id"]] = row
    return success_object(series_out(row), 201)


@bp.route("/hiring/series/<series_id>", methods=["GET"])
def read_series(series_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "HiringManager"])
    row = get_series_or_404(series_id)
    return success_object(series_out(row))


@bp.route("/hiring/series/<series_id>/positions", methods=["GET"])
def list_series_positions(series_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "HiringManager"])
    row = get_series_or_404(series_id)
    limit, offset = parse_pagination()
    items = [p for p in DB.positions.values() if p["series_id"] == row["id"]]
    items.sort(key=lambda p: (p["created_at"], p["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([position_out(p) for p in page], limit, offset, total)


@bp.route("/hiring/positions", methods=["POST"])
def create_position():
    _, role = get_auth()
    require_roles(role, ["HiringManager"])
    body = get_body()
    series_id = req_str(body, "series_id")
    title = req_str(body, "title")
    org_code = req_str(body, "org_code")
    k = req_int(body, "factor_knowledge_level", 1, 5)
    s = req_int(body, "factor_supervision_level", 1, 5)
    c = req_int(body, "factor_complexity_level", 1, 5)
    i = req_int(body, "factor_impact_level", 1, 5)
    sensitivity = req_enum(body, "sensitivity_level", SENSITIVITY)
    get_series_or_404(series_id)
    row = base_fields()
    row.update({
        "series_id": series_id, "title": title, "org_code": org_code,
        "factor_knowledge_level": k, "factor_supervision_level": s,
        "factor_complexity_level": c, "factor_impact_level": i,
        "total_points": total_points(k, s, c, i),
        "provisional_grade": provisional_grade(k, s, c, i),
        "official_grade": None,
        "sensitivity_level": sensitivity,
        "status": "DRAFT",
    })
    DB.positions[row["id"]] = row
    return success_object(position_out(row), 201)


@bp.route("/hiring/positions/<position_id>", methods=["GET"])
def read_position(position_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist", "HiringManager", "SelectingOfficial"])
    row = get_position_or_404(position_id)
    return success_object(position_out(row))


def _classify_grade_or_fail(position):
    series = DB.series[position["series_id"]]
    points = total_points(
        position["factor_knowledge_level"], position["factor_supervision_level"],
        position["factor_complexity_level"], position["factor_impact_level"])
    grade = official_grade(points)
    if grade is None or not (series["min_grade"] <= grade <= series["max_grade"]):
        fail("ERR_SERIES_GRADE_RANGE",
             "classified grade %s outside series range [%d, %d]"
             % (grade, series["min_grade"], series["max_grade"]))
    return points, grade


@bp.route("/hiring/positions/<position_id>/classify", methods=["POST"])
def classify_position(position_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    get_body()
    position = get_position_or_404(position_id)
    if position["status"] != "DRAFT":
        invalid_state("position is not DRAFT")
    points, grade = _classify_grade_or_fail(position)
    position["total_points"] = points
    position["official_grade"] = grade
    position["status"] = "CLASSIFIED"
    touch(position)
    return success_object(position_out(position))


@bp.route("/hiring/positions/<position_id>/reclassifications", methods=["POST"])
def reclassify_position(position_id):
    _, role = get_auth()
    require_roles(role, ["HRSpecialist"])
    body = get_body()
    k = req_int(body, "factor_knowledge_level", 1, 5)
    s = req_int(body, "factor_supervision_level", 1, 5)
    c = req_int(body, "factor_complexity_level", 1, 5)
    i = req_int(body, "factor_impact_level", 1, 5)
    expected_version = req_int(body, "expected_position_version")
    position = get_position_or_404(position_id)
    if position["status"] != "CLASSIFIED":
        invalid_state("position is not CLASSIFIED")
    series = DB.series[position["series_id"]]
    points = total_points(k, s, c, i)
    grade = official_grade(points)
    if grade is None or not (series["min_grade"] <= grade <= series["max_grade"]):
        fail("ERR_SERIES_GRADE_RANGE",
             "classified grade %s outside series range [%d, %d]"
             % (grade, series["min_grade"], series["max_grade"]))
    # OCC is the final check (priority 10).
    if expected_version != position["version"]:
        fail("ERR_STALE_VERSION", "position version has advanced; refresh before re-grading")
    position["factor_knowledge_level"] = k
    position["factor_supervision_level"] = s
    position["factor_complexity_level"] = c
    position["factor_impact_level"] = i
    position["total_points"] = points
    position["official_grade"] = grade
    touch(position)
    return success_object(position_out(position))
