"""Service logs and the void compensation (PRD section 3.6)."""
from flask import Blueprint, g, request

from auth import (CASE_MANAGER, COMPLIANCE_OFFICER, PROGRAM_COORDINATOR,
                  RELATED_SERVICE_PROVIDER, SPED_DIRECTOR, endpoint,
                  is_provider_role)
from calcs import instructional_dates
from envelope import created, ok, ok_list, paginate
from errors import ApiError
from ledgers import recompute_commitment_ledger, recompute_student_ledger
from resolve import body_ref, path_ref
from serialize import many, public
from store import db, new_record, touch
from validate import (bad, body, opt_enum, req_date, req_enum, req_int, req_str)

bp = Blueprint("service_logs", __name__)

OUTCOMES = ("DELIVERED", "PARTIAL", "MISSED_DISTRICT", "MISSED_PARENT",
            "MISSED_STUDENT_ABSENT")
MISS_REASON_CODES = ("WEATHER", "STAFF_ABSENCE", "TRANSPORT_FAILURE",
                     "PARENT_CANCELLED", "STUDENT_ILL", "OTHER")
READ_ROLES = (CASE_MANAGER, PROGRAM_COORDINATOR, SPED_DIRECTOR,
              COMPLIANCE_OFFICER, RELATED_SERVICE_PROVIDER)


@bp.post("/esy/service-logs")
@endpoint((RELATED_SERVICE_PROVIDER, CASE_MANAGER))
def create_service_log():
    data = body()

    # PRD 2.7 check 4 runs ahead of body resolution: the acting provider must be
    # the provider on an assignment covering the referenced commitment.
    if is_provider_role():
        raw_commitment_id = data.get("commitment_id")
        if isinstance(raw_commitment_id, str):
            target = db.commitments.get(raw_commitment_id)
            if target is not None and not any(
                    a["commitment_id"] == target["id"] and a["provider_id"] == g.user_id
                    for a in db.assignments.values()):
                raise ApiError("ERR_NOT_ASSIGNED_PROVIDER")

    body_ref(data, "provider_id", "provider")
    commitment = body_ref(data, "commitment_id", "commitment")

    commitment_id = req_str(data, "commitment_id", 1, None)
    service_date = req_date(data, "service_date")
    outcome = req_enum(data, "outcome", OUTCOMES)
    minutes_scheduled = req_int(data, "minutes_scheduled", 1, 480)
    minutes_delivered = req_int(data, "minutes_delivered", 0, 480)
    provider_id = data.get("provider_id")
    if provider_id is not None and not isinstance(provider_id, str):
        raise bad("provider_id must be a string.")
    miss_reason_code = opt_enum(data, "miss_reason_code", MISS_REASON_CODES)

    if minutes_delivered > minutes_scheduled:
        raise bad("minutes_delivered must not exceed minutes_scheduled.")
    if outcome == "DELIVERED" and minutes_delivered != minutes_scheduled:
        raise bad("minutes_delivered must equal minutes_scheduled when DELIVERED.")
    if outcome.startswith("MISSED_") and minutes_delivered != 0:
        raise bad("minutes_delivered must be 0 for a MISSED_ outcome.")
    if outcome != "DELIVERED" and miss_reason_code is None:
        raise bad("miss_reason_code is required when the outcome is not DELIVERED.")

    program = db.programs.get(commitment["program_id"])
    if program is None or not any(day.isoformat() == service_date
                                 for day in instructional_dates(program)):
        raise ApiError("ERR_NOT_INSTRUCTIONAL_DATE")

    for existing in db.logs.values():
        if (existing["commitment_id"] == commitment_id
                and existing["service_date"] == service_date
                and existing["status"] == "VERIFIED"):
            raise ApiError("ERR_DUPLICATE_SERVICE_LOG")

    log = new_record("ServiceLog", {
        "commitment_id": commitment_id,
        "provider_id": provider_id,
        "service_date": service_date,
        "outcome": outcome,
        "minutes_scheduled": minutes_scheduled,
        "minutes_delivered": minutes_delivered,
        "miss_reason_code": miss_reason_code,
        "status": "VERIFIED",
        "generated_by": "CASE_MANAGER" if g.role == CASE_MANAGER else "PROVIDER",
        "void_reason": None,
    })
    db.logs[log["id"]] = log

    recompute_commitment_ledger(commitment)
    student = db.students.get(commitment["student_id"])
    if student is not None:
        recompute_student_ledger(student)
    return created(public(log))


@bp.get("/esy/service-logs")
@endpoint(READ_ROLES)
def list_service_logs():
    rows = list(db.logs.values())
    for key in ("commitment_id", "provider_id", "service_date", "outcome"):
        wanted = request.args.get(key)
        if wanted is not None:
            rows = [r for r in rows if r.get(key) == wanted]
    rows = sorted(rows, key=lambda r: (r["service_date"], r["created_at"], r["_seq"]))
    page, page_meta = paginate(rows)
    return ok_list(many(page), page_meta)


@bp.get("/esy/service-logs/<log_id>")
@endpoint(READ_ROLES)
def get_service_log(log_id):
    return ok(public(path_ref("log", log_id)))


@bp.post("/esy/service-logs/<log_id>/void")
@endpoint((COMPLIANCE_OFFICER,))
def void_service_log(log_id):
    log = path_ref("log", log_id)
    data = body()
    void_reason = req_str(data, "void_reason", 1, None)

    if log["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE")

    log["status"] = "VOIDED"
    log["void_reason"] = void_reason
    touch(log)

    commitment = db.commitments.get(log["commitment_id"])
    if commitment is not None:
        recompute_commitment_ledger(commitment)
        student = db.students.get(commitment["student_id"])
        if student is not None:
            recompute_student_ledger(student)
    return ok(public(log))
