"""Routes: enrollment conversion, reads, withdrawal, and deferral."""

from flask import Blueprint, request

from auth import require_roles
from domain import (
    active_caseload_count,
    current_auth_row,
    financial_hold,
    latest_non_void_tce,
    lazy_release_package,
    packages_for_enrollment,
    recompute_package_totals,
    r2t4_institutional,
    r2t4_title_iv,
    ser_enrollment,
)
from errors import raise_err
from response import ok_list, ok_object
from store import STORE, CLOCK, bump, new_entity, parse_date
from validate import (
    get_body,
    opt_date,
    paginate,
    req_enum,
    req_int,
    req_str,
)

bp = Blueprint("enrollments", __name__)

READ_ROLES = ("SystemAdmin", "RegistrarAdmin", "FinancialAidOfficer", "Advisor")
INTENSITIES = ("FULL_TIME", "HALF_TIME", "LESS_THAN_HALF_TIME")
ENROLLMENT_STATUSES = ("REGISTERED", "ACTIVE", "COMPLETED", "WITHDRAWN", "DEFERRED")


@bp.post("/api/enrollments")
def create_enrollment():
    require_roles("RegistrarAdmin")
    body = get_body()
    application_id = req_str(body, "application_id")
    advisor_id = req_str(body, "advisor_id")
    intensity = req_enum(body, "enrollment_intensity", INTENSITIES)
    tuition = req_int(body, "tuition_cents")
    expected_version = req_int(body, "expected_application_version")

    # Shape-level staff_type rule: an advisor_id referencing an existing staff
    # member whose staff_type is not ADVISOR fails as ERR_INVALID_REQUEST.
    advisor = STORE.staff.get(advisor_id)
    if advisor is not None and advisor["staff_type"] != "ADVISOR":
        raise_err("ERR_INVALID_REQUEST", "advisor_id must reference a Staff member with staff_type ADVISOR")

    # Existence, left to right.
    application = STORE.applications.get(application_id)
    if application is None:
        raise_err("ERR_NOT_FOUND", "application not found")
    if advisor is None:
        raise_err("ERR_NOT_FOUND", "advisor not found")

    # Optimistic concurrency on the application version (PRD §2.8).
    if expected_version != application["version"]:
        raise_err("ERR_STALE_VERSION", "application version has advanced since it was observed")

    if application["status"] != "ADMITTED":
        raise_err("ERR_INVALID_STATE", "only ADMITTED applications may be converted")

    applicant = STORE.applicants.get(application["applicant_id"])
    program = STORE.programs.get(application["program_id"])

    # Business gates in their pinned order (PRD §3.6).
    row = current_auth_row(application["program_id"], applicant["state_code"] if applicant else None)
    if row is None or row["authorization_status"] in ("PENDING", "PROHIBITED"):
        raise_err("ERR_STATE_NOT_AUTHORIZED", "no current AUTHORIZED/RESTRICTED state authorization")
    if row["authorization_status"] == "RESTRICTED" and not application["disclosure_acknowledged"]:
        raise_err("ERR_DISCLOSURE_REQUIRED", "RESTRICTED state authorization requires disclosure_acknowledged")
    if program is not None and program["licensure_flag"] and not application["licensure_disclosure_acknowledged"]:
        raise_err(
            "ERR_LICENSURE_DISCLOSURE_REQUIRED",
            "licensure program requires licensure_disclosure_acknowledged",
        )
    if applicant is not None and applicant["assigned_counselor_id"]:
        counselor = STORE.staff.get(applicant["assigned_counselor_id"])
        if counselor is not None and counselor["compensation_plan"] == "INCENTIVE":
            raise_err(
                "ERR_INCENTIVE_COMP_VIOLATION",
                "conversion attribution to an INCENTIVE-plan counselor is barred",
            )
    tce = latest_non_void_tce(application_id)
    if tce is None or tce["status"] != "COMPLETED":
        raise_err(
            "ERR_EVALUATION_INCOMPLETE",
            "the latest transfer credit evaluation must be COMPLETED before enrollment",
        )
    if active_caseload_count(advisor) >= advisor["caseload_cap"]:
        raise_err("ERR_CASELOAD_CAP_EXCEEDED", "advisor active caseload is at its cap")

    # Conversion writes: application -> CONVERTED, applicant -> ENROLLED,
    # enrollment created in REGISTERED with term_id copied.
    application["status"] = "CONVERTED"
    bump(application)
    if applicant is not None and applicant["status"] == "ADMITTED":
        applicant["status"] = "ENROLLED"
        bump(applicant)
    enrollment = new_entity(
        {
            "application_id": application_id,
            "term_id": application["term_id"],
            "advisor_id": advisor_id,
            "enrollment_intensity": intensity,
            "tuition_cents": tuition,
            "status": "REGISTERED",
            "withdrawal_date": None,
            "institutional_refund_cents": 0,
        }
    )
    STORE.enrollments[enrollment["id"]] = enrollment
    return ok_object(ser_enrollment(enrollment), 201)


@bp.get("/api/enrollments")
def list_enrollments():
    require_roles(*READ_ROLES)
    items = sorted(STORE.enrollments.values(), key=lambda e: e["_seq"])
    f_advisor = request.args.get("advisor_id")
    f_term = request.args.get("term_id")
    f_app = request.args.get("application_id")
    f_status = request.args.get("status")
    if f_advisor is not None:
        items = [e for e in items if e["advisor_id"] == f_advisor]
    if f_term is not None:
        items = [e for e in items if e["term_id"] == f_term]
    if f_app is not None:
        items = [e for e in items if e["application_id"] == f_app]
    if f_status is not None:
        items = [e for e in items if e["status"] == f_status]
    page, limit, offset, total = paginate([ser_enrollment(e) for e in items])
    return ok_list(page, limit, offset, total)


@bp.get("/api/enrollments/<eid>")
def get_enrollment(eid):
    require_roles(*READ_ROLES)
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    return ok_object(ser_enrollment(enrollment))


@bp.post("/api/enrollments/<eid>/withdraw")
def withdraw_enrollment(eid):
    require_roles("RegistrarAdmin")
    body = get_body()
    w_raw, w_date = opt_date(body, "withdrawal_date")
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")
    # State legality before the withdrawal window.
    if enrollment["status"] not in ("REGISTERED", "ACTIVE"):
        raise_err(
            "ERR_INVALID_STATE",
            "only REGISTERED or ACTIVE enrollments may be withdrawn",
        )
    term = STORE.terms.get(enrollment["term_id"])
    if term is None:
        raise_err("ERR_NOT_FOUND", "term not found")
    effective = w_date if w_date is not None else CLOCK.today()
    if effective > parse_date(term["end_date"]):
        raise_err("ERR_WITHDRAWAL_WINDOW_CLOSED", "withdrawal date is after the term end_date")

    # Aid package cascade. The withdrawal request mutates the package, so lazy
    # disbursement release runs first; the federal return is then computed over
    # disbursed aid at withdrawal time.
    for pkg in packages_for_enrollment(eid):
        if pkg["status"] not in ("CERTIFIED", "DISBURSING"):
            continue
        lazy_release_package(pkg)
        returned = r2t4_title_iv(pkg["disbursed_cents"], term, effective)
        pkg["returned_cents"] = returned
        for entry in pkg["disbursement_schedule"]:
            if entry["entry_status"] == "SCHEDULED":
                entry["entry_status"] = "CANCELLED"
            elif entry["entry_status"] == "DISBURSED":
                entry["entry_status"] = "RETURNED"
        recompute_package_totals(pkg)
        pkg["status"] = "RETURNED"
        bump(pkg)

    # Institutional refund (independent step function on tuition).
    enrollment["institutional_refund_cents"] = r2t4_institutional(
        enrollment["tuition_cents"], term, effective
    )
    enrollment["withdrawal_date"] = effective.isoformat()
    enrollment["status"] = "WITHDRAWN"
    bump(enrollment)

    # Applicant returns ENROLLED -> ADMITTED so the student may re-enroll.
    application = STORE.applications.get(enrollment["application_id"])
    applicant = STORE.applicants.get(application["applicant_id"]) if application else None
    if applicant is not None and applicant["status"] == "ENROLLED":
        applicant["status"] = "ADMITTED"
        bump(applicant)

    # Free every roster seat this enrollment occupies in the term's sections.
    for section in STORE.sections.values():
        if section["term_id"] != enrollment["term_id"]:
            continue
        if eid not in section["_roster"]:
            continue
        section["_roster"].remove(eid)
        section["enrolled_count"] -= 1
        section["seats_available"] += 1
        if section["status"] == "LOCKED":
            section["status"] = "OPEN"
        bump(section)

    return ok_object(ser_enrollment(enrollment))


@bp.post("/api/enrollments/<eid>/defer")
def defer_enrollment(eid):
    require_roles("RegistrarAdmin")
    body = get_body()
    to_state = req_enum(body, "to_state", ENROLLMENT_STATUSES)
    enrollment = STORE.enrollments.get(eid)
    if enrollment is None:
        raise_err("ERR_NOT_FOUND", "enrollment not found")

    cur = enrollment["status"]
    if to_state == "DEFERRED" and cur in ("REGISTERED", "ACTIVE"):
        enrollment["status"] = "DEFERRED"
        bump(enrollment)
    elif to_state == "REGISTERED" and cur == "DEFERRED":
        # Re-registration cycle: term-open gate before the financial-hold gate.
        term = STORE.terms.get(enrollment["term_id"])
        if term is None or term["status"] != "ENROLLMENT_OPEN":
            raise_err("ERR_TERM_NOT_OPEN", "term must be ENROLLMENT_OPEN to re-register")
        if financial_hold(enrollment):
            raise_err("ERR_FINANCIAL_HOLD", "re-registration is blocked by a financial hold")
        enrollment["status"] = "REGISTERED"
        bump(enrollment)
    else:
        raise_err(
            "ERR_INVALID_STATE",
            "cannot transition enrollment from %s to %s" % (cur, to_state),
        )
    return ok_object(ser_enrollment(enrollment))
