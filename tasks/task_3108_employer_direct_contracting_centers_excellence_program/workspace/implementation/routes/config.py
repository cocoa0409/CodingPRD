"""Employers, rate books, bundle templates, and the logical clock."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_enum,
    f_int,
    f_map,
    f_str,
    fmt_dt,
    new_row,
    paginate,
    parse_dt,
    q_str,
    respond_object,
    sort_created,
    touch,
)
from core import scope_employer
from domain import (
    EMPLOYER_STATUSES,
    FAMILIES,
    READMIT_POLICIES,
    TEMPLATE_STATUSES,
    get_or_404,
    terminate_contract,
)

bp = Blueprint("config", __name__)


# ---------------------------------------------------------------------------
# Employers
# ---------------------------------------------------------------------------
@bp.route("/coe/employers", methods=["POST"])
@endpoint("ProgramAdmin")
def create_employer():
    data = body()
    legal_name = f_str(data, "legal_name")
    ein = f_str(data, "ein")
    rate_book_id = f_str(data, "baseline_rate_book")
    row = new_row(
        "employer",
        legal_name=legal_name,
        ein=ein,
        baseline_rate_book=rate_book_id,
        status="ACTIVE",
    )
    db.employers[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.route("/coe/employers", methods=["GET"])
@endpoint("ProgramAdmin")
def list_employers():
    rows = list(db.employers.values())
    status = q_str("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    book = q_str("baseline_rate_book")
    if book is not None:
        rows = [r for r in rows if r["baseline_rate_book"] == book]
    return paginate(sort_created(rows))


@bp.route("/coe/employers/<emp_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "ClaimsAdmin", "CareCoordinator")
def get_employer(emp_id):
    row = get_or_404("employers", emp_id)
    scope_employer(row["id"])
    return respond_object(dump(row))


@bp.route("/coe/employers/<emp_id>/terminate", methods=["POST"])
@endpoint("ProgramAdmin")
def terminate_employer(emp_id):
    row = get_or_404("employers", emp_id)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Employer is not ACTIVE.")
    row["status"] = "TERMINATED"
    touch(row)
    for contract in sort_created(db.contracts.values()):
        if contract["employer_id"] == row["id"] and contract["status"] in ("DRAFT", "ACTIVE"):
            terminate_contract(contract)
    return respond_object(dump(row))


@bp.route("/coe/employers/<emp_id>/contracts", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep")
def list_employer_contracts(emp_id):
    row = get_or_404("employers", emp_id)
    scope_employer(row["id"])
    rows = [c for c in db.contracts.values() if c["employer_id"] == row["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/employers/<emp_id>/patients", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "CareCoordinator")
def list_employer_patients(emp_id):
    row = get_or_404("employers", emp_id)
    scope_employer(row["id"])
    rows = [p for p in db.patients.values() if p["employer_id"] == row["id"]]
    return paginate(sort_created(rows))


@bp.route("/coe/employers/<emp_id>/reports", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep")
def list_employer_reports(emp_id):
    row = get_or_404("employers", emp_id)
    scope_employer(row["id"])
    rows = [r for r in db.reports.values() if r["employer_id"] == row["id"]]
    return paginate(sort_created(rows))


# ---------------------------------------------------------------------------
# Bundle templates
# ---------------------------------------------------------------------------
@bp.route("/coe/bundle-templates", methods=["POST"])
@endpoint("ProgramAdmin")
def create_template():
    data = body()
    family = f_enum(data, "procedure_family", FAMILIES)
    label = f_str(data, "label")
    warranty_days = f_int(data, "warranty_days", minimum=1)
    cap = f_int(data, "implant_component_cap_cents", minimum=0)
    readmit_policy = f_enum(data, "readmit_policy", READMIT_POLICIES)
    row = new_row(
        "template",
        procedure_family=family,
        label=label,
        warranty_days=warranty_days,
        implant_component_cap_cents=cap,
        readmit_policy=readmit_policy,
        status="ACTIVE",
    )
    db.templates[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.route("/coe/bundle-templates/<tpl_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep", "ClaimsAdmin", "CareCoordinator", "PhysicianReviewer")
def get_template(tpl_id):
    row = get_or_404("templates", tpl_id)
    return respond_object(dump(row))


@bp.route("/coe/bundle-templates/<tpl_id>/retire", methods=["POST"])
@endpoint("ProgramAdmin")
def retire_template(tpl_id):
    row = get_or_404("templates", tpl_id)
    if row["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Bundle template is not ACTIVE.")
    row["status"] = "RETIRED"
    touch(row)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Rate books
# ---------------------------------------------------------------------------
@bp.route("/coe/rate-books", methods=["POST"])
@endpoint("ProgramAdmin")
def create_rate_book():
    data = body()
    book_code = f_str(data, "book_code")
    rates = f_map(data, "rates")
    for key, value in rates.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise ApiError("ERR_INVALID_REQUEST", "Field 'rates' values must be integers.")
    row = new_row("rate_book", book_code=book_code, rates=rates)
    db.rate_books[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.route("/coe/rate-books/<book_id>", methods=["GET"])
@endpoint("ProgramAdmin", "EmployerRep")
def get_rate_book(book_id):
    row = get_or_404("rate_books", book_id)
    return respond_object(dump(row))


# ---------------------------------------------------------------------------
# Logical clock (test driving)
# ---------------------------------------------------------------------------
@bp.route("/coe/_clock/set_current_utc", methods=["POST"])
@endpoint("ProgramAdmin")
def set_clock():
    data = body()
    iso = f_str(data, "to_iso8601")
    parsed = parse_dt(iso)
    if parsed is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'to_iso8601' must be an ISO-8601 timestamp.")
    db.clock = parsed
    return respond_object({"current_utc": fmt_dt(db.clock)})
