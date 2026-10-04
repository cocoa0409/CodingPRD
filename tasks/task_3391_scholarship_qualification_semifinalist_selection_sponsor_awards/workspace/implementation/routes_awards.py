"""Award endpoints: reads, accept/decline, disbursement schedule reads and
release, renewal verification submission and decision."""

from flask import Blueprint, g, request

import constants as C
import services
from errors import err
from helpers import (
    apply_filters,
    body,
    check_enum_field,
    check_num_field,
    created_key,
    is_int,
    paginate,
    require_present,
    require_roles,
    resp_object,
    bad,
)
from serializers import ser_award, ser_disbursement, ser_renewal
from store import base_record, clock_now, db, parse_dt

bp = Blueprint("awards", __name__)


def _get_award_or_404(award_id):
    rec = db["awards"].get(award_id)
    if rec is None:
        err("ERR_NOT_FOUND", "award not found")
    return rec


def _check_student_owns_award(award):
    if g.user_role == C.ROLE_STUDENT and g.user_id != award["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "students may only act on their own awards")


@bp.route("/api/awards/<award_id>", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_STUDENT, C.ROLE_SPONSOR_ADMIN, C.ROLE_COLLEGE_ADMIN)
def get_award(award_id):
    rec = _get_award_or_404(award_id)
    _check_student_owns_award(rec)
    return resp_object(ser_award(rec))


@bp.route("/api/awards", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_SPONSOR_ADMIN, C.ROLE_COLLEGE_ADMIN, C.ROLE_STUDENT)
def list_awards():
    records = sorted(db["awards"].values(), key=created_key)
    records = apply_filters(
        records,
        [
            ("cycle_id", request.args.get("cycle_id")),
            ("application_id", request.args.get("application_id")),
            ("student_id", request.args.get("student_id")),
            ("agreement_id", request.args.get("agreement_id")),
            ("college_id", request.args.get("college_id")),
            ("category", request.args.get("category")),
            ("recipient_status", request.args.get("recipient_status")),
        ],
    )
    return paginate(records, ser_award)


@bp.route("/api/awards/<award_id>/accept", methods=["POST"])
@require_roles(C.ROLE_STUDENT)
def accept_award(award_id):
    rec = _get_award_or_404(award_id)
    # Priority 3, ownership.
    if g.user_id != rec["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "only the recipient may accept")
    # Priority 6, recipient state. An offer past its acceptance deadline has
    # already been swept to EXPIRED by the clock advance, so this state gate
    # fires first.
    if rec["recipient_status"] != "OFFERED":
        err("ERR_AWARD_NOT_OFFERED", "award is not OFFERED")
    services.accept_award(rec)
    return resp_object(ser_award(rec))


@bp.route("/api/awards/<award_id>/decline", methods=["POST"])
@require_roles(C.ROLE_STUDENT)
def decline_award(award_id):
    rec = _get_award_or_404(award_id)
    if g.user_id != rec["student_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "only the recipient may decline")
    if rec["recipient_status"] != "OFFERED":
        err("ERR_AWARD_NOT_OFFERED", "award is not OFFERED")
    services.release_cascade(rec, "DECLINED")
    return resp_object(ser_award(rec))


@bp.route("/api/awards/<award_id>/disbursements", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_STUDENT, C.ROLE_COLLEGE_ADMIN)
def list_disbursements(award_id):
    rec = _get_award_or_404(award_id)
    _check_student_owns_award(rec)
    records = [d for d in db["disbursements"].values() if d["award_id"] == award_id]
    records.sort(key=lambda d: d["term_index"])
    return paginate(records, ser_disbursement)


@bp.route("/api/disbursements/<disbursement_id>/release", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def release_disbursement(disbursement_id):
    rec = db["disbursements"].get(disbursement_id)
    if rec is None:
        err("ERR_NOT_FOUND", "disbursement not found")
    award = db["awards"][rec["award_id"]]
    # Priority 6, entity state gates.
    if rec["status"] == "HELD":
        err("ERR_DISBURSEMENT_HELD", "disbursement is held pending renewal")
    if rec["status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", "disbursement is in a terminal state")
    if award["recipient_status"] not in ("ACCEPTED", "ENROLLED", "RENEWED"):
        err("ERR_INVALID_STATE", "award recipient state does not allow release")
    # Priority 8, temporal: logical clock at or past the scheduled date.
    if clock_now() < parse_dt(rec["scheduled_date"]):
        err("ERR_DISBURSEMENT_NOT_DUE", "disbursement is not yet due")
    services.release_disbursement(rec)
    return resp_object(ser_disbursement(rec))


@bp.route("/api/awards/<award_id>/renewal-verifications", methods=["GET"])
@require_roles(C.ROLE_PROGRAM_ADMIN, C.ROLE_COLLEGE_ADMIN, C.ROLE_STUDENT)
def list_renewals(award_id):
    rec = _get_award_or_404(award_id)
    _check_student_owns_award(rec)
    records = [r for r in db["renewals"].values() if r["award_id"] == award_id]
    records.sort(key=created_key)
    return paginate(records, ser_renewal)


@bp.route("/api/awards/<award_id>/renewal-verifications", methods=["POST"])
@require_roles(C.ROLE_COLLEGE_ADMIN)
def create_renewal(award_id):
    rec = _get_award_or_404(award_id)
    # Priority 3, ownership: X-User-ID == award.college_id; a null college_id
    # (national/corporate award) lets any CollegeAdmin pass to the
    # renewability gate.
    if rec["college_id"] is not None and g.user_id != rec["college_id"]:
        err("ERR_FORBIDDEN_OWNERSHIP", "college admins may only verify their own institution's awards")
    # Priority 6: renewability first (PRD 3.8), then recipient state.
    if rec["renewable_years_total"] < 2:
        err("ERR_NOT_RENEWABLE", "award is not renewable")
    if rec["recipient_status"] not in ("ENROLLED", "RENEWED"):
        err("ERR_INVALID_STATE", "award recipient state does not allow renewal verification")
    b = body()
    # Priority 7: one verification per (award, academic_year_index); the year
    # must be 2..renewable_years_total and the immediately next unverified one.
    year = b.get("academic_year_index")
    if is_int(year):
        expected_year = rec["years_renewed"] + 2
        exists = any(
            r["award_id"] == rec["id"] and r["academic_year_index"] == year
            for r in db["renewals"].values()
        )
        if year < 2 or year > rec["renewable_years_total"] or year != expected_year or exists:
            err("ERR_RENEWAL_ALREADY_EXISTS", "renewal verification already exists or out of sequence")
    # Priority 10, field shape.
    require_present(b, "academic_year_index", "reported_enrollment", "reported_gpa")
    if not is_int(b["academic_year_index"]):
        bad("academic_year_index must be an integer")
    check_enum_field(b, "reported_enrollment", C.REPORTED_ENROLLMENTS)
    check_num_field(b, "reported_gpa", minimum=C.GPA_MIN, maximum=C.GPA_MAX)
    new = base_record()
    new.update(
        {
            "award_id": rec["id"],
            "academic_year_index": b["academic_year_index"],
            "reported_enrollment": b["reported_enrollment"],
            "reported_gpa": b["reported_gpa"],
            "status": "SUBMITTED",
            "submitted_by_college_id": g.user_id,
            "decided_logical_at": None,
        }
    )
    db["renewals"][new["id"]] = new
    return resp_object(ser_renewal(new), code=201)


@bp.route("/api/renewal-verifications/<renewal_id>/decision", methods=["POST"])
@require_roles(C.ROLE_PROGRAM_ADMIN)
def decide_renewal(renewal_id):
    rec = db["renewals"].get(renewal_id)
    if rec is None:
        err("ERR_NOT_FOUND", "renewal verification not found")
    # Priority 6, entity state.
    if rec["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", "renewal verification already decided")
    b = body()
    decision = b.get("decision")
    if decision not in C.RENEWAL_DECISIONS:
        bad("decision must be one of APPROVE, REJECT")
    # Priority 7, renewal criteria on APPROVE.
    if decision == "APPROVE":
        if rec["reported_enrollment"] != "FULL_TIME" or rec["reported_gpa"] < C.RENEWAL_MIN_GPA:
            err("ERR_RENEWAL_CRITERIA_UNMET", "renewal criteria not met")
    services.decide_renewal(rec, approve=(decision == "APPROVE"))
    return resp_object(ser_renewal(rec))
