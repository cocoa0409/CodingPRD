"""Routes: logical clock, departments, terms, rate schedules."""

import re

from flask import Blueprint, request

import errors
import helpers
import services
from helpers import (
    find_or_404,
    list_response,
    new_record,
    opt_bool,
    opt_enum,
    opt_int,
    opt_str,
    pagination_params,
    parse_date,
    req_date,
    req_enum,
    req_int,
    req_number,
    req_str,
    success_obj,
    term_by_code,
    today,
    touch,
)
from store import STORE, set_now

bp = Blueprint("core", __name__)

ALL_ROLES = ["HRAdmin", "HRReviewer", "DepartmentChair", "Dean", "PayrollOfficer"]
CODE_RE = re.compile(r"^[A-Z0-9]{2,12}$")

TIER_ORDER = ["BACHELORS", "MASTERS", "DOCTORATE"]
RATE_BASES = ["PER_CONTACT_HOUR", "PER_COURSE"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    helpers.require_roles(["HRAdmin"])
    data = helpers.body()
    dt = helpers.parse_instant(data.get("to_iso8601"))
    if dt is None:
        raise errors.invalid_request("Field 'to_iso8601' must be an ISO 8601 instant")
    set_now(dt)
    services.advance_clock_effects()
    from store import now_iso

    return success_obj({"current_utc": now_iso()})


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------

@bp.post("/departments")
def create_department():
    helpers.require_roles(["HRAdmin"])
    data = helpers.body()
    code = req_str(data, "code")
    if not CODE_RE.match(code):
        raise errors.invalid_request(
            "Field 'code' must be 2-12 uppercase alphanumeric characters"
        )
    name = req_str(data, "name")
    contact_hour_value = req_number(data, "contact_hour_value", gt=0, max_decimals=2)
    active = opt_bool(data, "active")
    if active is None:
        active = True
    for d in STORE["departments"].values():
        if d["code"] == code:
            raise errors.duplicate("Department code '%s' already exists" % code)
    rec = new_record()
    rec.update(
        {
            "code": code,
            "name": name,
            "contact_hour_value": contact_hour_value,
            "active": active,
        }
    )
    STORE["departments"][rec["id"]] = rec
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out, status=201)


@bp.get("/departments/<rid>")
def get_department(rid):
    helpers.require_roles(ALL_ROLES)
    rec = find_or_404("departments", rid, "Department")
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


@bp.get("/departments")
def list_departments():
    helpers.require_roles(ALL_ROLES)
    return list_response(
        STORE["departments"].values(),
        {"active": request.args.get("active")},
    )


@bp.patch("/departments/<rid>")
def patch_department(rid):
    helpers.require_roles(["HRAdmin"])
    rec = find_or_404("departments", rid, "Department")
    data = helpers.body()
    name = opt_str(data, "name")
    contact_hour_value = None
    if "contact_hour_value" in data and data["contact_hour_value"] is not None:
        contact_hour_value = req_number(
            data, "contact_hour_value", gt=0, max_decimals=2
        )
    active = opt_bool(data, "active")
    if active is False:
        # deactivation guard: OPEN postings or ISSUED/ACTIVE contracts
        for p in STORE["postings"].values():
            if p["department_id"] == rec["id"] and p["posting_status"] == "OPEN":
                raise errors.reference_in_use(
                    "Department has OPEN postings referencing it"
                )
        for c in STORE["contracts"].values():
            if c["contract_status"] in ("ISSUED", "ACTIVE"):
                section = STORE["sections"].get(c["section_id"])
                if section is not None and section["department_id"] == rec["id"]:
                    raise errors.reference_in_use(
                        "Department has ISSUED/ACTIVE contracts referencing it"
                    )
    if name is not None:
        rec["name"] = name
    if contact_hour_value is not None:
        rec["contact_hour_value"] = contact_hour_value
    if active is not None:
        rec["active"] = active
    touch(rec)
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------

@bp.post("/terms")
def create_term():
    helpers.require_roles(["HRAdmin"])
    data = helpers.body()
    code = req_str(data, "code")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    early = req_date(data, "early_census_date")
    late = req_date(data, "late_census_date")
    load_cap = req_number(data, "load_cap_units", gt=0, max_decimals=2)
    s = parse_date(start_date)
    e = parse_date(end_date)
    ec = parse_date(early)
    lc = parse_date(late)
    if not (e > s) or (e - s).days < 14:
        raise errors.invalid_date_range(
            "end_date must fall after start_date with a span of at least 14 days"
        )
    if not (s <= ec < lc <= e):
        raise errors.invalid_date_range(
            "Census ordering violated: start_date <= early_census_date < late_census_date <= end_date"
        )
    for t in STORE["terms"].values():
        if t["code"] == code:
            raise errors.duplicate("Term code '%s' already exists" % code)
    rec = new_record()
    rec.update(
        {
            "code": code,
            "start_date": start_date,
            "end_date": end_date,
            "early_census_date": early,
            "late_census_date": late,
            "load_cap_units": load_cap,
            "rollover_status": "SCHEDULED",
        }
    )
    STORE["terms"][rec["id"]] = rec
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out, status=201)


@bp.get("/terms/<rid>")
def get_term(rid):
    helpers.require_roles(ALL_ROLES)
    rec = find_or_404("terms", rid, "TermConfig")
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


@bp.get("/terms")
def list_terms():
    helpers.require_roles(ALL_ROLES)
    return list_response(
        STORE["terms"].values(),
        {
            "code": request.args.get("code"),
            "rollover_status": request.args.get("rollover_status"),
        },
    )


@bp.post("/terms/<rid>/open")
def open_term(rid):
    helpers.require_roles(["HRAdmin"])
    rec = find_or_404("terms", rid, "TermConfig")
    if rec["rollover_status"] != "SCHEDULED":
        raise errors.invalid_state("Term is not SCHEDULED")
    rec["rollover_status"] = "OPEN"
    touch(rec)
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


@bp.post("/terms/<rid>/rollover")
def rollover_term(rid):
    helpers.require_roles(["HRAdmin"])
    rec = find_or_404("terms", rid, "TermConfig")
    if rec["rollover_status"] == "ROLLED_OVER":
        raise errors.invalid_state("Term is already ROLLED_OVER")
    services.run_rollover(rec)
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


# ---------------------------------------------------------------------------
# Rate schedules
# ---------------------------------------------------------------------------

@bp.post("/rate-schedules")
def create_rate_schedule():
    helpers.require_roles(["HRAdmin"])
    data = helpers.body()
    department_id = data.get("department_id")
    if not isinstance(department_id, str) or not department_id:
        raise errors.invalid_request("Field 'department_id' is required")
    dept = find_or_404("departments", department_id, "Department")
    tier = req_enum(data, "education_tier", TIER_ORDER)
    basis = req_enum(data, "rate_basis", RATE_BASES)
    base_rate = req_int(data, "base_rate_cents", min_value=1)
    step = req_int(data, "longevity_step_cents", min_value=0)
    cap = req_int(data, "longevity_step_cap", min_value=0)
    eff_start = req_date(data, "effective_start_date")
    eff_end = req_date(data, "effective_end_date")
    if parse_date(eff_end) <= parse_date(eff_start):
        raise errors.invalid_date_range(
            "effective_end_date must fall after effective_start_date"
        )
    rec = new_record()
    rec.update(
        {
            "department_id": dept["id"],
            "education_tier": tier,
            "rate_basis": basis,
            "base_rate_cents": base_rate,
            "longevity_step_cents": step,
            "longevity_step_cap": cap,
            "effective_start_date": eff_start,
            "effective_end_date": eff_end,
            "schedule_status": "DRAFT",
            "published_version": None,
        }
    )
    STORE["rate_schedules"][rec["id"]] = rec
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out, status=201)


@bp.get("/rate-schedules/<rid>")
def get_rate_schedule(rid):
    helpers.require_roles(["HRAdmin", "HRReviewer", "DepartmentChair", "Dean"])
    rec = find_or_404("rate_schedules", rid, "RateSchedule")
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


@bp.get("/rate-schedules")
def list_rate_schedules():
    helpers.require_roles(["HRAdmin", "HRReviewer", "DepartmentChair", "Dean"])
    return list_response(
        STORE["rate_schedules"].values(),
        {
            "department_id": request.args.get("department_id"),
            "education_tier": request.args.get("education_tier"),
            "schedule_status": request.args.get("schedule_status"),
        },
    )


@bp.post("/rate-schedules/<rid>/publish")
def publish_rate_schedule(rid):
    helpers.require_roles(["HRAdmin"])
    rec = find_or_404("rate_schedules", rid, "RateSchedule")
    if rec["schedule_status"] != "DRAFT":
        raise errors.invalid_state("Rate schedule is not DRAFT")
    dept = STORE["departments"].get(rec["department_id"])
    if dept is None or not dept["active"]:
        raise errors.invalid_state("Department is not active")
    s1 = parse_date(rec["effective_start_date"])
    e1 = parse_date(rec["effective_end_date"])
    for other in STORE["rate_schedules"].values():
        if other["id"] == rec["id"]:
            continue
        if other["schedule_status"] != "PUBLISHED":
            continue
        if (
            other["department_id"] == rec["department_id"]
            and other["education_tier"] == rec["education_tier"]
        ):
            s2 = parse_date(other["effective_start_date"])
            e2 = parse_date(other["effective_end_date"])
            # half-open [start, end) intersection; adjacency is not overlap
            if s1 < e2 and s2 < e1:
                raise errors.schedule_overlap(
                    "An overlapping PUBLISHED schedule exists for this department and tier"
                )
    rec["published_version"] = rec["version"]
    rec["schedule_status"] = "PUBLISHED"
    touch(rec)
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)


@bp.post("/rate-schedules/<rid>/retire")
def retire_rate_schedule(rid):
    helpers.require_roles(["HRAdmin"])
    rec = find_or_404("rate_schedules", rid, "RateSchedule")
    if rec["schedule_status"] != "PUBLISHED":
        raise errors.invalid_state("Rate schedule is not PUBLISHED")
    for c in STORE["contracts"].values():
        if c["rate_schedule_id"] == rec["id"] and c["contract_status"] in (
            "ISSUED",
            "ACTIVE",
        ):
            raise errors.reference_in_use(
                "Schedule is referenced by ISSUED/ACTIVE contracts"
            )
    rec["schedule_status"] = "RETIRED"
    touch(rec)
    out = dict(rec)
    out.pop("_seq", None)
    return success_obj(out)
