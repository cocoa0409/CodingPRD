"""Members, coverage segments and benefit accumulators (PRD 3.2)."""

from flask import Blueprint, request

from auth import ALL_OPERATORS, endpoint
from envelope import created, ok
from errors import ApiError
from routes.common import filter_equals, filter_int_equals, render_list, resolve
from serializers import dump
from services.accumulators import create as create_accumulator
from services.eligibility import activate_member_if_covered, terminate_coverage
from services.lookup import coverages_of
from store import db
from validators import (
    body,
    check_interval,
    read_date,
    read_enum,
    read_int,
    read_string,
    require_fields,
)

bp = Blueprint("members", __name__)

OPEN_ENDED = "9999-12-31"


# --------------------------------------------------------------------------
# Member
# --------------------------------------------------------------------------
@bp.post("/adjudication/members")
@endpoint(["PlanAdmin"])
def enrol_member():
    payload = body()
    if payload.get("plan_id") is not None:
        resolve("benefit_plans", payload["plan_id"], "ERR_PLAN_NOT_FOUND")
    require_fields(payload, ["member_number", "plan_id"])
    member_number = read_string(payload, "member_number", required=True)
    plan_id = read_string(payload, "plan_id", required=True)
    member = {
        "member_number": member_number,
        "plan_id": plan_id,
        "first_name": read_string(payload, "first_name", "Given"),
        "last_name": read_string(payload, "last_name", "Family"),
        "date_of_birth": read_date(payload, "date_of_birth", "1980-01-01"),
        "status": "ACTIVE",
    }
    for existing in db.values("members"):
        if existing["member_number"] == member_number:
            raise ApiError("ERR_DUPLICATE_MEMBER_NUMBER")
    row = db.insert("members", member)
    plan = db.benefit_plans[plan_id]
    create_accumulator(row["id"], int(plan["plan_year_start_date"][:4]))
    return created(dump("member", row))


@bp.get("/adjudication/members/<member_id>")
@endpoint(ALL_OPERATORS)
def get_member(member_id):
    member = resolve("members", member_id, "ERR_MEMBER_NOT_FOUND")
    return ok(dump("member", member))


@bp.get("/adjudication/members")
@endpoint(ALL_OPERATORS)
def list_members():
    rows = db.values("members")
    rows = filter_equals(rows, "plan_id", request.args.get("plan_id"))
    rows = filter_equals(rows, "member_number", request.args.get("member_number"))
    rows = filter_equals(rows, "status", request.args.get("status"))
    return render_list("member", rows)


# --------------------------------------------------------------------------
# MemberCoverage
# --------------------------------------------------------------------------
@bp.post("/adjudication/members/<member_id>/coverages")
@endpoint(["PlanAdmin"])
def add_coverage(member_id):
    member = resolve("members", member_id, "ERR_MEMBER_NOT_FOUND")
    payload = body()
    require_fields(payload, ["effective_date", "cob_order"])
    effective_date = read_date(payload, "effective_date", required=True)
    term_date = read_date(payload, "term_date")
    check_interval("term_date", effective_date, term_date)
    segment = {
        "member_id": member["id"],
        "effective_date": effective_date,
        "term_date": term_date,
        "cob_order": read_enum(
            payload, "cob_order", ("PRIMARY", "SECONDARY", "TERTIARY"), required=True
        ),
        "other_payer_name": read_string(payload, "other_payer_name"),
        "coverage_tier": read_enum(
            payload, "coverage_tier", ("INDIVIDUAL", "FAMILY"), "INDIVIDUAL"
        ),
        "status": "ACTIVE",
    }
    _check_coverage_overlap(member["id"], effective_date, term_date)
    row = db.insert("member_coverages", segment)
    activate_member_if_covered(member, row)
    return created(dump("member_coverage", row))


def _check_coverage_overlap(member_id, effective_date, term_date):
    """Half-open intervals: adjacency is allowed, any intersection is not."""
    new_start = effective_date
    new_end = term_date or OPEN_ENDED
    for existing in coverages_of(member_id):
        old_start = existing["effective_date"]
        old_end = existing["term_date"] or OPEN_ENDED
        if new_start < old_end and old_start < new_end:
            raise ApiError("ERR_COVERAGE_OVERLAP")


@bp.get("/adjudication/members/<member_id>/coverages")
@endpoint(ALL_OPERATORS)
def list_coverages(member_id):
    member = resolve("members", member_id, "ERR_MEMBER_NOT_FOUND")
    rows = coverages_of(member["id"])
    rows = filter_equals(rows, "status", request.args.get("status"))
    return render_list("member_coverage", rows)


@bp.post("/adjudication/coverages/<coverage_id>/terminate")
@endpoint(["PlanAdmin"])
def terminate_coverage_route(coverage_id):
    from flask import g

    coverage = resolve("member_coverages", coverage_id, "ERR_COVERAGE_NOT_FOUND")
    payload = body()
    require_fields(payload, ["term_date"])
    term_date = read_date(payload, "term_date", required=True)
    check_interval("term_date", coverage["effective_date"], term_date)
    if coverage["status"] == "TERMINATED":
        raise ApiError("ERR_COVERAGE_ALREADY_TERMINATED")
    terminate_coverage(coverage, term_date, g.role, g.user_id)
    return ok(dump("member_coverage", coverage))


# --------------------------------------------------------------------------
# BenefitAccumulator
# --------------------------------------------------------------------------
@bp.get("/adjudication/members/<member_id>/accumulators")
@endpoint(ALL_OPERATORS)
def list_accumulators(member_id):
    member = resolve("members", member_id, "ERR_MEMBER_NOT_FOUND")
    rows = [a for a in db.values("benefit_accumulators") if a["member_id"] == member["id"]]
    rows = filter_int_equals(rows, "plan_year", request.args.get("plan_year"))
    return render_list(
        "benefit_accumulator", rows, sort_key=lambda a: (-a["plan_year"], a["_seq"])
    )


@bp.post("/adjudication/accumulators/<accumulator_id>/adjustments")
@endpoint(["PlanAdmin"])
def adjust_accumulator(accumulator_id):
    accumulator = resolve("benefit_accumulators", accumulator_id, "ERR_ACCUMULATOR_NOT_FOUND")
    payload = body()
    require_fields(
        payload, ["expected_accumulator_version", "deductible_delta_cents", "oop_delta_cents"]
    )
    expected = read_int(payload, "expected_accumulator_version", required=True)
    deductible_delta = read_int(payload, "deductible_delta_cents", required=True)
    oop_delta = read_int(payload, "oop_delta_cents", required=True)
    read_string(payload, "note")
    if expected != accumulator["version"]:
        raise ApiError("ERR_STALE_ACCUMULATOR_VERSION")
    new_deductible = accumulator["deductible_applied_cents"] + deductible_delta
    new_oop = accumulator["oop_applied_cents"] + oop_delta
    if new_deductible < 0 or new_oop < 0:
        raise ApiError("ERR_ACCUMULATOR_NEGATIVE")
    accumulator["deductible_applied_cents"] = new_deductible
    accumulator["oop_applied_cents"] = new_oop
    db.touch(accumulator)
    return ok(dump("benefit_accumulator", accumulator))
