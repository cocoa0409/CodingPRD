"""Eligibility certifications and appeals (PRD 3.4, 3.5)."""

from decimal import Decimal

from flask import Blueprint

import calc
import derive
import helpers as h
import store as st
from errors import ApiError
from store import D, q2
from validation import (authenticate, bad_request, forbid, json_body,
                        want_action, want_decimal, want_enum, want_int,
                        want_string)

bp = Blueprint("cert", __name__)

CERT_READ_ONE = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
                 "ComplianceOfficer", "AppealsCommittee", "StudentAthlete"]
CERT_LIST = ["Registrar", "AcademicAdvisor", "CertificationOfficer",
             "ComplianceOfficer", "AppealsCommittee"]
APPEAL_READ_ONE = ["AppealsCommittee", "CertificationOfficer", "AcademicAdvisor",
                   "ComplianceOfficer", "StudentAthlete"]
APPEAL_LIST = ["AppealsCommittee", "CertificationOfficer", "AcademicAdvisor",
               "ComplianceOfficer"]

CERT_TYPES = ("INITIAL", "CONTINUING", "TRANSFER")
APPEAL_TYPES = ("PROGRESS_WAIVER", "MISSED_CLASS_EXCEPTION", "TRANSFER_EXCEPTION",
                "ASSISTANCE_REINSTATEMENT")


# --------------------------------------------------------- snapshot helpers
def _completed_full_time_terms_counted(student, term):
    indexes = calc.full_time_term_indexes(student)
    return len([i for i in indexes if i < term["term_index"]])


def _certification_relief(certification):
    """PRD 3.4 step 6: the granted appeal with the highest round_number wins."""
    best = None
    best_key = None
    for appeal in st.appeals.values():
        if appeal["certification_id"] != certification["id"]:
            continue
        if appeal["status"] != "GRANTED":
            continue
        key = (appeal["round_number"], appeal["created_at"], appeal["_seq"])
        if best_key is None or key > best_key:
            best = appeal
            best_key = key
    if best is None:
        return q2("0")
    return q2(best["granted_credit_relief"])


def _write_snapshot(certification, student, term):
    """Freeze / refresh the academic picture onto a certification."""
    relief = _certification_relief(certification)
    picture = derive.compute_picture(
        student,
        audit_variant=certification["audit_variant"],
        cert_term=term,
        relief=relief,
    )
    certification["_audit_base"] = picture["degree_applicable_credits"]
    certification["degree_applicable_credits_counted"] = q2(
        D(picture["degree_applicable_credits"]) + D(relief)
    )
    certification["required_progress_pct"] = picture["required_progress_pct"]
    certification["progress_pct"] = picture["progress_pct"]
    certification["gpa_at_certification"] = picture["cumulative_gpa"]
    certification["completed_full_time_terms_counted"] = (
        _completed_full_time_terms_counted(student, term)
    )
    certification["benchmark_result"] = picture["benchmark_result"]
    certification["failure_reasons"] = list(picture["failure_reasons"])
    certification["credit_relief_applied"] = relief
    return picture


# --------------------------------------------------------- certifications
@bp.get("/athletics/certifications/<certification_id>")
def get_certification(certification_id):
    authenticate(CERT_READ_ONE)
    return h.ok(h.certification_or_404(certification_id))


@bp.get("/athletics/certifications")
def list_certifications():
    authenticate(CERT_LIST)
    return h.listing(
        st.by_created(list(st.certifications.values())),
        ("student_athlete_id", "term_id", "status", "certification_type"),
    )


@bp.post("/athletics/certifications")
def create_certification():
    user_id, role = authenticate(["CertificationOfficer"])
    body = json_body()
    student = h.body_fk(body, "student_athlete_id", h.student_or_404)
    term = h.body_fk(body, "term_id", h.term_or_404)
    student_id = want_string(body, "student_athlete_id")
    term_id = want_string(body, "term_id")
    if student is None:
        student = h.student_or_404(student_id)
    if term is None:
        term = h.term_or_404(term_id)
    certification_type = want_enum(body, "certification_type", CERT_TYPES)
    expected_version = want_int(body, "expected_student_athlete_version", minimum=0)
    requested_variant = want_enum(body, "audit_variant", calc.AUDIT_VARIANTS,
                                  required=False, default=None)

    # Band 7 sits above every state and business check (PRD 2.8).
    if expected_version != student["version"]:
        raise ApiError("ERR_STALE_STUDENT_VERSION")
    h.require_term_open(term)

    if certification_type in ("CONTINUING", "TRANSFER"):
        if not student.get("declared_program_id"):
            raise ApiError("ERR_MAJOR_NOT_DECLARED")
    if certification_type == "TRANSFER":
        has_transfer = any(
            e["credit_source"] == "TRANSFER" and e["status"] == "COMPLETED"
            for e in calc.student_enrollments(student["id"])
        )
        if not has_transfer:
            raise ApiError("ERR_TRANSFER_CREDIT_SOURCE_INVALID")
    if certification_type == "INITIAL":
        if term["term_index"] != student["entry_term_index"]:
            raise ApiError("ERR_CERTIFICATION_TYPE_TERM_MISMATCH")
    elif certification_type == "CONTINUING":
        if term["term_index"] <= student["entry_term_index"]:
            raise ApiError("ERR_CERTIFICATION_TYPE_TERM_MISMATCH")
    else:
        if student["transfer_status"] != "INCOMING_TRANSFER":
            raise ApiError("ERR_CERTIFICATION_TYPE_TERM_MISMATCH")
        if calc.resident_completed_term_count(student) < calc.TRANSFER_RESIDENCY_TERMS:
            raise ApiError("ERR_TRANSFER_RESIDENCY_NOT_MET")

    # PRD 3.3 variant resolution ladder.
    if certification_type == "TRANSFER":
        variant = "CATALOG_AT_CERTIFICATION"
    elif certification_type == "INITIAL":
        variant = "CATALOG_AT_ENTRY"
    elif requested_variant is not None:
        variant = requested_variant
    else:
        variant = calc.default_audit_variant(student)

    certification = {
        "student_athlete_id": student["id"],
        "term_id": term["id"],
        "certification_type": certification_type,
        "status": "DRAFT",
        "audit_variant": variant,
        "degree_applicable_credits_counted": q2("0"),
        "required_progress_pct": None,
        "progress_pct": None,
        "gpa_at_certification": None,
        "completed_full_time_terms_counted": 0,
        "benchmark_result": None,
        "failure_reasons": [],
        "credit_relief_applied": q2("0"),
        "requested_by_user_id": user_id,
        "decided_by_user_id": None,
        "decided_at": None,
    }
    st.stamp_new(certification)

    for existing in st.by_created(list(st.certifications.values())):
        if (existing["student_athlete_id"] == student["id"]
                and existing["term_id"] == term["id"]
                and existing["status"] == "DRAFT"):
            existing["status"] = "SUPERSEDED"
            st.touch(existing)

    st.certifications[certification["id"]] = certification
    picture = _write_snapshot(certification, student, term)
    derive.persist_picture(student, picture)
    st.touch(student)
    return h.created(certification)


@bp.post("/athletics/certifications/<certification_id>/status")
def certification_status(certification_id):
    user_id, role = authenticate(["CertificationOfficer", "AcademicAdvisor"])
    certification = h.certification_or_404(certification_id)
    body = json_body()
    action = want_action(body, ("SUBMIT", "CERTIFY", "DENY", "REVOKE"))

    term = st.terms.get(certification["term_id"])
    student = st.students.get(certification["student_athlete_id"])
    h.require_term_open(term)

    status = certification["status"]
    if action == "SUBMIT":
        if status != "DRAFT":
            raise h.invalid_transition()
        if student["support_status"] == "SUPPORT_WITHHELD":
            raise h.invalid_transition()
        if certification["certification_type"] == "CONTINUING":
            program_id = student.get("declared_program_id")
            if not program_id:
                raise h.invalid_transition()
            program = st.degree_programs.get(program_id)
            standing = calc.academic_standing(student)
            if (program is None
                    or standing["completed_full_time_terms"]
                    > program["major_declaration_deadline_term_count"]):
                raise h.invalid_transition()
        if certification["certification_type"] == "TRANSFER":
            standing = calc.academic_standing(student)
            if standing["completed_full_time_terms"] < 1:
                raise h.invalid_transition()
        certification["status"] = "SUBMITTED"
        _write_snapshot(certification, student, term)
        st.touch(certification)
        return h.ok(certification)

    if action == "CERTIFY":
        if status != "SUBMITTED":
            raise h.invalid_transition()
        if certification["benchmark_result"] != "PASS":
            raise h.invalid_transition()
        if user_id == certification["requested_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        certification["status"] = "CERTIFIED"
        certification["decided_by_user_id"] = user_id
        certification["decided_at"] = st.now_iso()
    elif action == "DENY":
        if status != "SUBMITTED":
            raise h.invalid_transition()
        if user_id == certification["requested_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        certification["status"] = "DENIED"
        certification["decided_by_user_id"] = user_id
        certification["decided_at"] = st.now_iso()
    else:
        if status not in ("CERTIFIED", "RESTORED"):
            raise h.invalid_transition()
        certification["status"] = "REVOKED"

    st.touch(certification)
    derive.derive_eligibility_state(student)
    st.touch(student)
    return h.ok(certification)


# ----------------------------------------------------------------- appeals
def _appeal_term(appeal):
    certification = st.certifications.get(appeal["certification_id"])
    if certification is None:
        return None, None
    return certification, st.terms.get(certification["term_id"])


@bp.get("/athletics/appeals/<appeal_id>")
def get_appeal(appeal_id):
    authenticate(APPEAL_READ_ONE)
    return h.ok(h.appeal_or_404(appeal_id))


@bp.get("/athletics/appeals")
def list_appeals():
    authenticate(APPEAL_LIST)
    return h.listing(
        h.sorted_appeals(),
        ("certification_id", "predecessor_appeal_id", "status", "appeal_type"),
    )


@bp.post("/athletics/appeals")
def create_appeal():
    user_id, role = authenticate(["AcademicAdvisor", "CertificationOfficer"])
    body = json_body()
    certification = h.body_fk(body, "certification_id", h.certification_or_404)
    certification_id = want_string(body, "certification_id")
    if certification is None:
        certification = h.certification_or_404(certification_id)
    appeal_type = want_enum(body, "appeal_type", APPEAL_TYPES)
    rationale = want_string(body, "rationale")
    requested_relief = want_decimal(body, "requested_credit_relief", required=False,
                                    default=Decimal("0"), minimum=0, maximum=12)
    predecessor = h.body_fk(body, "predecessor_appeal_id", h.appeal_or_404)
    predecessor_id = body.get("predecessor_appeal_id")
    if predecessor_id is not None:
        if not isinstance(predecessor_id, str) or predecessor_id.strip() == "":
            raise bad_request("Field 'predecessor_appeal_id' must be a string.")
        predecessor = h.appeal_or_404(predecessor_id)

    term = st.terms.get(certification["term_id"])
    h.require_term_open(term)
    if certification["status"] not in ("DENIED", "REVOKED"):
        raise ApiError("ERR_APPEAL_NOT_ELIGIBLE")
    if predecessor is not None:
        if predecessor["round_number"] >= calc.MAX_APPEAL_ROUNDS:
            raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")
        round_number = predecessor["round_number"] + 1
    else:
        round_number = 1

    appeal = {
        "certification_id": certification["id"],
        "predecessor_appeal_id": predecessor["id"] if predecessor else None,
        "appeal_type": appeal_type,
        "requested_credit_relief": q2(requested_relief),
        "rationale": rationale,
        "status": "DRAFT",
        "round_number": round_number,
        "granted_credit_relief": q2("0"),
        "submitted_by_user_id": user_id,
        "decided_by_user_id": None,
        "decided_at": None,
    }
    st.stamp_new(appeal)
    st.appeals[appeal["id"]] = appeal
    return h.created(appeal)


@bp.post("/athletics/appeals/<appeal_id>/status")
def appeal_status(appeal_id):
    user_id, role = authenticate(["AppealsCommittee", "AcademicAdvisor"])
    appeal = h.appeal_or_404(appeal_id)
    body = json_body()
    action = want_action(body, ("SUBMIT", "OPEN_REVIEW", "GRANT", "DENY",
                                "REQUEST_REVISION", "WITHDRAW"))
    if action == "GRANT":
        granted = want_decimal(body, "granted_credit_relief", required=True, minimum=0)
    else:
        forbid(body, "granted_credit_relief", action)
        granted = None

    certification, term = _appeal_term(appeal)
    h.require_term_open(term)

    if action in ("SUBMIT", "GRANT", "DENY", "REQUEST_REVISION"):
        if certification is None or certification["status"] not in ("DENIED", "REVOKED"):
            raise ApiError("ERR_APPEAL_NOT_ELIGIBLE")

    status = appeal["status"]
    if action == "SUBMIT":
        if status == "DRAFT":
            appeal["status"] = "SUBMITTED"
            appeal["round_number"] = 1
        elif status == "REVISION_REQUESTED":
            if appeal["round_number"] >= calc.MAX_APPEAL_ROUNDS:
                raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")
            appeal["status"] = "SUBMITTED"
            appeal["round_number"] = appeal["round_number"] + 1
            appeal["decided_by_user_id"] = None
            appeal["decided_at"] = None
        else:
            raise h.invalid_transition()
        st.touch(appeal)
        return h.ok(appeal)

    if action == "OPEN_REVIEW":
        if status != "SUBMITTED":
            raise h.invalid_transition()
        appeal["status"] = "COMMITTEE_REVIEW"
        st.touch(appeal)
        return h.ok(appeal)

    if action == "WITHDRAW":
        if status not in ("DRAFT", "SUBMITTED", "REVISION_REQUESTED"):
            raise h.invalid_transition()
        appeal["status"] = "WITHDRAWN"
        st.touch(appeal)
        return h.ok(appeal)

    if action == "DENY":
        if status != "COMMITTEE_REVIEW":
            raise h.invalid_transition()
        if user_id == appeal["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        appeal["status"] = "DENIED"
        appeal["decided_by_user_id"] = user_id
        appeal["decided_at"] = st.now_iso()
        st.touch(appeal)
        return h.ok(appeal)

    if action == "REQUEST_REVISION":
        if status != "COMMITTEE_REVIEW":
            raise h.invalid_transition()
        if user_id == appeal["submitted_by_user_id"]:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES")
        if appeal["round_number"] >= calc.MAX_APPEAL_ROUNDS:
            raise ApiError("ERR_APPEAL_ROUNDS_EXHAUSTED")
        appeal["status"] = "REVISION_REQUESTED"
        appeal["decided_by_user_id"] = user_id
        appeal["decided_at"] = st.now_iso()
        st.touch(appeal)
        return h.ok(appeal)

    # GRANT
    if status != "COMMITTEE_REVIEW":
        raise h.invalid_transition()
    if user_id == appeal["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if D(granted) > D(appeal["requested_credit_relief"]):
        raise ApiError("ERR_RELIEF_EXCEEDS_REQUEST")

    appeal["status"] = "GRANTED"
    appeal["granted_credit_relief"] = q2(granted)
    appeal["decided_by_user_id"] = user_id
    appeal["decided_at"] = st.now_iso()
    st.touch(appeal)

    student = st.students.get(certification["student_athlete_id"])
    _write_snapshot(certification, student, term)
    if certification["benchmark_result"] == "PASS" and certification["status"] in (
        "DENIED",
        "REVOKED",
    ):
        certification["status"] = "RESTORED"
        st.touch(certification)
        derive.recompute_student(student)
        derive.derive_eligibility_state(student)
        st.touch(student)
    else:
        st.touch(certification)
    return h.ok(appeal)
