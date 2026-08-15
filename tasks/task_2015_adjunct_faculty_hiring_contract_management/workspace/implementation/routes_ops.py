"""Routes: course sections, contracts, payroll periods/entries,
evaluations, retention entries."""

from decimal import Decimal

from flask import Blueprint, request

import errors
import helpers
import services
from helpers import (
    find_or_404,
    is_int,
    list_response,
    new_record,
    opt_int,
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
from store import STORE

bp = Blueprint("ops", __name__)

READ_ROLES = ["HRAdmin", "HRReviewer", "DepartmentChair", "Dean", "PayrollOfficer"]
PAYROLL_READ_ROLES = ["HRAdmin", "PayrollOfficer"]
PERIOD_READ_ROLES = ["HRAdmin", "PayrollOfficer", "DepartmentChair", "Dean"]
EVAL_READ_ROLES = ["HRAdmin", "HRReviewer", "DepartmentChair", "Dean"]

CANCEL_REASONS = ["LOW_ENROLLMENT", "PROGRAM_CUT", "FACULTY_INITIATED", "ADMINISTRATIVE"]


def _out(rec):
    out = dict(rec)
    out.pop("_seq", None)
    return out


# ---------------------------------------------------------------------------
# Course sections
# ---------------------------------------------------------------------------

@bp.post("/sections")
def create_section():
    helpers.require_roles(["DepartmentChair"])
    data = helpers.body()
    department_id = data.get("department_id")
    if not isinstance(department_id, str) or not department_id:
        raise errors.invalid_request("Field 'department_id' is required")
    dept = find_or_404("departments", department_id, "Department")
    term_code = req_str(data, "term_code")
    course_code = req_str(data, "course_code")
    section_code = req_str(data, "section_code")
    weekly = req_number(data, "weekly_contact_hours", gt=0, max_decimals=2)
    credit = req_int(data, "credit_hours", min_value=0)
    enrollment = opt_int(data, "enrollment", min_value=0)
    if enrollment is None:
        enrollment = 0
    min_enrollment = req_int(data, "min_enrollment", min_value=0)
    term = term_by_code(term_code)
    if term is None:
        raise errors.invalid_request(
            "Field 'term_code' must match an existing TermConfig.code"
        )
    for s in STORE["sections"].values():
        if (
            s["term_code"] == term_code
            and s["course_code"] == course_code
            and s["section_code"] == section_code
        ):
            raise errors.duplicate(
                "A section with this (term_code, course_code, section_code) exists"
            )
    rec = new_record()
    rec.update(
        {
            "department_id": dept["id"],
            "term_code": term_code,
            "course_code": course_code,
            "section_code": section_code,
            "weekly_contact_hours": weekly,
            "credit_hours": credit,
            "enrollment": enrollment,
            "min_enrollment": min_enrollment,
            "section_status": "SCHEDULED",
        }
    )
    STORE["sections"][rec["id"]] = rec
    return success_obj(_out(rec), status=201)


@bp.get("/sections/<rid>")
def get_section(rid):
    helpers.require_roles(READ_ROLES)
    return success_obj(_out(find_or_404("sections", rid, "Section")))


@bp.get("/sections")
def list_sections():
    helpers.require_roles(READ_ROLES)
    return list_response(
        STORE["sections"].values(),
        {
            "department_id": request.args.get("department_id"),
            "term_code": request.args.get("term_code"),
            "section_status": request.args.get("section_status"),
        },
    )


@bp.patch("/sections/<rid>")
def patch_section(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("sections", rid, "Section")
    data = helpers.body()
    if rec["section_status"] not in ("SCHEDULED", "RUNNING"):
        raise errors.invalid_state("Section is not SCHEDULED or RUNNING")
    enrollment = req_int(data, "enrollment", min_value=0)
    rec["enrollment"] = enrollment
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/sections/<rid>/cancel")
def cancel_section(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("sections", rid, "Section")
    data = helpers.body()
    reason = data.get("cancellation_reason")
    if rec["section_status"] not in ("SCHEDULED", "RUNNING"):
        raise errors.invalid_state("Section is not SCHEDULED or RUNNING")
    if reason not in CANCEL_REASONS:
        raise errors.invalid_request(
            "Field 'cancellation_reason' must be one of " + ", ".join(CANCEL_REASONS)
        )
    term = term_by_code(rec["term_code"])
    if reason == "LOW_ENROLLMENT":
        if term is None or not (
            rec["enrollment"] < rec["min_enrollment"]
            and today() < parse_date(term["early_census_date"])
        ):
            raise errors.cancellation_policy(
                "LOW_ENROLLMENT requires enrollment < min_enrollment and current date "
                "strictly before early census"
            )
    rec["cancellation_reason"] = reason
    rec["section_status"] = "CANCELLED"
    touch(rec)
    services.cancel_section(rec)
    return success_obj(_out(rec))


@bp.post("/sections/<rid>/complete")
def complete_section(rid):
    helpers.require_roles(["DepartmentChair"])
    rec = find_or_404("sections", rid, "Section")
    if rec["section_status"] != "RUNNING":
        raise errors.invalid_state("Section is not RUNNING")
    term = term_by_code(rec["term_code"])
    if term is None or not (today() > parse_date(term["end_date"])):
        raise errors.invalid_state("Current logical date is not after term end_date")
    rec["section_status"] = "COMPLETED"
    touch(rec)
    services.complete_section(rec)
    return success_obj(_out(rec))


@bp.get("/sections/<rid>/contracts")
def section_contracts(rid):
    helpers.require_roles(READ_ROLES)
    find_or_404("sections", rid, "Section")
    contracts = [c for c in STORE["contracts"].values() if c["section_id"] == rid]
    return list_response(
        contracts, {"contract_status": request.args.get("contract_status")}
    )


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------

@bp.post("/contracts")
def create_contract():
    helpers.require_roles(["DepartmentChair"])
    data = helpers.body()
    faculty_id = data.get("faculty_id")
    section_id = data.get("section_id")
    rate_schedule_id = data.get("rate_schedule_id")
    for name, value in (
        ("faculty_id", faculty_id),
        ("section_id", section_id),
        ("rate_schedule_id", rate_schedule_id),
    ):
        if not isinstance(value, str) or not value:
            raise errors.invalid_request("Field '%s' is required" % name)
    # existence, body left-to-right
    fac = find_or_404("faculty", faculty_id, "Faculty")
    section = find_or_404("sections", section_id, "Section")
    schedule = find_or_404("rate_schedules", rate_schedule_id, "RateSchedule")
    term = term_by_code(section["term_code"])
    dept = STORE["departments"].get(section["department_id"])
    # priority 14: reference validity
    term_start = parse_date(section["term_code"] and term["start_date"]) if term else None
    ref_ok = (
        term is not None
        and dept is not None
        and schedule["schedule_status"] == "PUBLISHED"
        and schedule["department_id"] == section["department_id"]
        and schedule["education_tier"] == fac["education_tier"]
        and parse_date(schedule["effective_start_date"]) <= term_start
        and term_start < parse_date(schedule["effective_end_date"])
        and section["section_status"] not in ("CANCELLED", "COMPLETED")
        and fac["retention_status"] != "NON_REAPPOINTED"
        and term["rollover_status"] != "ROLLED_OVER"
    )
    if not ref_ok:
        raise errors.contract_reference_invalid()
    # computed snapshots
    load_units = round(
        Decimal(str(section["weekly_contact_hours"]))
        * Decimal(str(dept["contact_hour_value"])),
        2,
    )
    load_units = float(load_units)
    # priority 15: load-cap guard (prospective ISSUED+ACTIVE load in this term)
    prospective = Decimal(str(load_units))
    for c in STORE["contracts"].values():
        if c["faculty_id"] != fac["id"]:
            continue
        if c["contract_status"] not in ("ISSUED", "ACTIVE"):
            continue
        other_section = STORE["sections"].get(c["section_id"])
        if other_section is not None and other_section["term_code"] == term["code"]:
            prospective += Decimal(str(c["load_units"]))
    threshold = Decimal(str(term["load_cap_units"])) + Decimal(
        str(helpers.OVERAGE_ALLOWANCE)
    )
    if prospective > threshold:
        raise errors.load_cap_exceeded()
    # priority 20: OCC
    expected = data.get("expected_faculty_version")
    if not is_int(expected):
        raise errors.invalid_request(
            "Field 'expected_faculty_version' is required and must be an integer"
        )
    if expected != fac["version"]:
        raise errors.stale_faculty_version()
    gross = services.compute_gross_pay(fac, section, term, schedule)
    rec = new_record()
    rec.update(
        {
            "faculty_id": fac["id"],
            "section_id": section["id"],
            "rate_schedule_id": schedule["id"],
            "pinned_schedule_version": schedule.get("published_version"),
            "expected_faculty_version": expected,
            "load_units": load_units,
            "gross_pay_cents": gross,
            "payable_cents": gross,
            "contract_status": "ISSUED",
            "cancelled_at": None,
            "cancellation_reason": None,
        }
    )
    STORE["contracts"][rec["id"]] = rec
    touch(fac)  # issuance bumps the faculty version
    return success_obj(_out(rec), status=201)


@bp.get("/contracts/<rid>")
def get_contract(rid):
    helpers.require_roles(READ_ROLES)
    return success_obj(_out(find_or_404("contracts", rid, "Contract")))


@bp.get("/contracts")
def list_contracts():
    helpers.require_roles(READ_ROLES)
    return list_response(
        STORE["contracts"].values(),
        {
            "faculty_id": request.args.get("faculty_id"),
            "section_id": request.args.get("section_id"),
            "rate_schedule_id": request.args.get("rate_schedule_id"),
            "contract_status": request.args.get("contract_status"),
        },
    )


@bp.post("/contracts/<rid>/void")
def void_contract(rid):
    helpers.require_roles(["HRAdmin"])
    rec = find_or_404("contracts", rid, "Contract")
    if rec["contract_status"] != "ISSUED":
        raise errors.invalid_state("Contract is not ISSUED")
    services.void_contract(rec)
    return success_obj(_out(rec))


@bp.get("/contracts/<rid>/payroll-entries")
def contract_payroll_entries(rid):
    helpers.require_roles(PAYROLL_READ_ROLES)
    find_or_404("contracts", rid, "Contract")
    entries = [e for e in STORE["payroll_entries"].values() if e["contract_id"] == rid]
    return list_response(entries, {"entry_kind": request.args.get("entry_kind")})


# ---------------------------------------------------------------------------
# Payroll periods / entries
# ---------------------------------------------------------------------------

@bp.post("/payroll-periods")
def create_payroll_period():
    helpers.require_roles(["PayrollOfficer"])
    data = helpers.body()
    period_code = req_str(data, "period_code")
    start_date = req_date(data, "start_date")
    end_date = req_date(data, "end_date")
    if parse_date(end_date) < parse_date(start_date):
        raise errors.invalid_date_range("end_date must be on or after start_date")
    for p in STORE["payroll_periods"].values():
        if p["period_code"] == period_code:
            raise errors.duplicate("period_code '%s' already exists" % period_code)
    s1 = parse_date(start_date)
    e1 = parse_date(end_date)
    for p in STORE["payroll_periods"].values():
        if p["period_status"] == "CLOSED":
            continue
        s2 = parse_date(p["start_date"])
        e2 = parse_date(p["end_date"])
        # closed-interval semantics: touching endpoints count as overlap
        if s1 <= e2 and s2 <= e1:
            raise errors.payroll_period_overlap(
                "New period overlaps an existing non-CLOSED period"
            )
    rec = new_record()
    rec.update(
        {
            "period_code": period_code,
            "start_date": start_date,
            "end_date": end_date,
            "period_status": "OPEN",
        }
    )
    STORE["payroll_periods"][rec["id"]] = rec
    return success_obj(_out(rec), status=201)


@bp.get("/payroll-periods/<rid>")
def get_payroll_period(rid):
    helpers.require_roles(PERIOD_READ_ROLES)
    return success_obj(_out(find_or_404("payroll_periods", rid, "PayrollPeriod")))


@bp.get("/payroll-periods")
def list_payroll_periods():
    helpers.require_roles(PERIOD_READ_ROLES)
    return list_response(
        STORE["payroll_periods"].values(),
        {"period_status": request.args.get("period_status")},
    )


@bp.post("/payroll-periods/<rid>/lock")
def lock_payroll_period(rid):
    helpers.require_roles(["PayrollOfficer"])
    rec = find_or_404("payroll_periods", rid, "PayrollPeriod")
    if rec["period_status"] != "OPEN":
        raise errors.invalid_state("Payroll period is not OPEN")
    rec["period_status"] = "LOCKED"
    touch(rec)
    return success_obj(_out(rec))


@bp.post("/payroll-periods/<rid>/close")
def close_payroll_period(rid):
    helpers.require_roles(["PayrollOfficer"])
    rec = find_or_404("payroll_periods", rid, "PayrollPeriod")
    if rec["period_status"] == "CLOSED":
        raise errors.payroll_close_order("Period is already CLOSED")
    if rec["period_status"] != "LOCKED":
        raise errors.invalid_state("Payroll period is not LOCKED")
    my_start = parse_date(rec["start_date"])
    for p in STORE["payroll_periods"].values():
        if p["id"] == rec["id"]:
            continue
        if parse_date(p["start_date"]) < my_start and p["period_status"] != "CLOSED":
            raise errors.payroll_close_order(
                "An earlier-starting period is not yet CLOSED"
            )
    services.run_payroll_close(rec)
    rec["period_status"] = "CLOSED"
    touch(rec)
    return success_obj(_out(rec))


@bp.get("/payroll-periods/<rid>/payroll-entries")
def period_payroll_entries(rid):
    helpers.require_roles(PAYROLL_READ_ROLES)
    find_or_404("payroll_periods", rid, "PayrollPeriod")
    entries = [
        e for e in STORE["payroll_entries"].values() if e["payroll_period_id"] == rid
    ]
    return list_response(
        entries,
        {
            "entry_kind": request.args.get("entry_kind"),
            "contract_id": request.args.get("contract_id"),
        },
    )


@bp.get("/payroll-entries")
def list_payroll_entries():
    helpers.require_roles(PAYROLL_READ_ROLES)
    return list_response(
        STORE["payroll_entries"].values(),
        {
            "contract_id": request.args.get("contract_id"),
            "payroll_period_id": request.args.get("payroll_period_id"),
            "entry_kind": request.args.get("entry_kind"),
            "reversal_of_entry_id": request.args.get("reversal_of_entry_id"),
        },
    )


@bp.get("/payroll-entries/<rid>")
def get_payroll_entry(rid):
    helpers.require_roles(PAYROLL_READ_ROLES)
    return success_obj(_out(find_or_404("payroll_entries", rid, "PayrollEntry")))


# ---------------------------------------------------------------------------
# Evaluations
# ---------------------------------------------------------------------------

@bp.post("/evaluations")
def create_evaluation():
    user_id, _ = helpers.require_roles(["Dean"])
    data = helpers.body()
    faculty_id = data.get("faculty_id")
    if not isinstance(faculty_id, str) or not faculty_id:
        raise errors.invalid_request("Field 'faculty_id' is required")
    fac = find_or_404("faculty", faculty_id, "Faculty")
    term_code = req_str(data, "term_code")
    teaching = req_number(data, "teaching_score", min_value=0, max_value=5, max_decimals=2)
    service = req_number(data, "service_score", min_value=0, max_value=5, max_decimals=2)
    compliance = req_number(data, "compliance_score", min_value=0, max_value=5, max_decimals=2)
    composite = services.compute_composite(teaching, service, compliance)
    rec = new_record(common=False)
    rec.update(
        {
            "faculty_id": fac["id"],
            "term_code": term_code,
            "teaching_score": teaching,
            "service_score": service,
            "compliance_score": compliance,
            "composite_score": composite,
            "recorded_by_dean_id": user_id,
        }
    )
    STORE["evaluations"][rec["id"]] = rec
    return success_obj(_out(rec), status=201)


@bp.get("/evaluations/<rid>")
def get_evaluation(rid):
    helpers.require_roles(EVAL_READ_ROLES)
    return success_obj(_out(find_or_404("evaluations", rid, "Evaluation")))


@bp.get("/evaluations")
def list_evaluations():
    helpers.require_roles(EVAL_READ_ROLES)
    return list_response(
        STORE["evaluations"].values(),
        {
            "faculty_id": request.args.get("faculty_id"),
            "term_code": request.args.get("term_code"),
        },
    )


# ---------------------------------------------------------------------------
# Retention entries
# ---------------------------------------------------------------------------

@bp.post("/retention-entries")
def create_retention_entry():
    helpers.require_roles(["Dean"])
    data = helpers.body()
    faculty_id = data.get("faculty_id")
    department_id = data.get("department_id")
    for name, value in (("faculty_id", faculty_id), ("department_id", department_id)):
        if not isinstance(value, str) or not value:
            raise errors.invalid_request("Field '%s' is required" % name)
    fac = find_or_404("faculty", faculty_id, "Faculty")
    dept = find_or_404("departments", department_id, "Department")
    list_term_code = req_str(data, "list_term_code")
    rec = new_record()
    rec.update(
        {
            "faculty_id": fac["id"],
            "department_id": dept["id"],
            "list_term_code": list_term_code,
            "rank_position": None,
            "entry_status": "LISTED",
        }
    )
    STORE["retention_entries"][rec["id"]] = rec
    # flip faculty retention dimension
    if fac["retention_status"] == "PROVISIONAL":
        fac["retention_status"] = "RETENTION_LISTED"
        touch(fac)
    # full re-rank of the scope (after inserting the new entry)
    services.rerank_retention_scope(dept["id"], list_term_code)
    return success_obj(_out(rec), status=201)


@bp.get("/retention-entries/<rid>")
def get_retention_entry(rid):
    helpers.require_roles(EVAL_READ_ROLES)
    return success_obj(_out(find_or_404("retention_entries", rid, "RetentionEntry")))


@bp.get("/retention-entries")
def list_retention_entries():
    helpers.require_roles(EVAL_READ_ROLES)
    return list_response(
        STORE["retention_entries"].values(),
        {
            "faculty_id": request.args.get("faculty_id"),
            "department_id": request.args.get("department_id"),
            "list_term_code": request.args.get("list_term_code"),
            "entry_status": request.args.get("entry_status"),
        },
    )


@bp.post("/retention-entries/<rid>/reappoint")
def reappoint(rid):
    helpers.require_roles(["Dean"])
    rec = find_or_404("retention_entries", rid, "RetentionEntry")
    data = helpers.body()
    if rec["entry_status"] != "LISTED":
        raise errors.invalid_state("Retention entry is not LISTED")
    fac = STORE["faculty"].get(rec["faculty_id"])
    if fac is None:
        raise errors.not_found("Faculty not found")
    if fac["compliance_status"] != "COMPLIANT":
        raise errors.compliance_incomplete(
            "Reappointment requires faculty compliance_status == COMPLIANT"
        )
    expected = data.get("expected_faculty_version")
    if not is_int(expected):
        raise errors.invalid_request(
            "Field 'expected_faculty_version' is required and must be an integer"
        )
    if expected != fac["version"]:
        raise errors.stale_faculty_version()
    rec["entry_status"] = "REAPPOINTED"
    touch(rec)
    touch(fac)  # the decision touches the faculty row
    return success_obj(_out(rec))


@bp.post("/retention-entries/<rid>/mark-non-reappointed")
def mark_non_reappointed(rid):
    helpers.require_roles(["Dean"])
    rec = find_or_404("retention_entries", rid, "RetentionEntry")
    data = helpers.body()
    if rec["entry_status"] != "LISTED":
        raise errors.invalid_state("Retention entry is not LISTED")
    fac = STORE["faculty"].get(rec["faculty_id"])
    if fac is None:
        raise errors.not_found("Faculty not found")
    expected = data.get("expected_faculty_version")
    if not is_int(expected):
        raise errors.invalid_request(
            "Field 'expected_faculty_version' is required and must be an integer"
        )
    if expected != fac["version"]:
        raise errors.stale_faculty_version()
    rec["entry_status"] = "NON_REAPPOINTED"
    touch(rec)
    # cascade: faculty retention dimension flips
    fac["retention_status"] = "NON_REAPPOINTED"
    touch(fac)
    # void future ISSUED contracts (sections whose term starts after the list term's)
    list_term = term_by_code(rec["list_term_code"])
    list_start = parse_date(list_term["start_date"]) if list_term else None
    affected_faculty = fac["id"]
    for c in list(STORE["contracts"].values()):
        if c["faculty_id"] != affected_faculty or c["contract_status"] != "ISSUED":
            continue
        section = STORE["sections"].get(c["section_id"])
        if section is None:
            continue
        term = term_by_code(section["term_code"])
        if term is None or list_start is None:
            continue
        if parse_date(term["start_date"]) > list_start:
            services.void_contract(c)
    services.recompute_faculty_load(fac)
    return success_obj(_out(rec))
