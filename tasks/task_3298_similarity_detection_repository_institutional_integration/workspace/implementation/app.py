"""Similarity Detection Repository API — Flask entrypoint."""
import os
from datetime import timedelta
from flask import Flask, g

from store import DB, now_logical, set_logical, parse_iso, fmt_iso
from helpers import (
    ApiError, err_unauthenticated, err_forbidden, err_not_found, err_validation,
    err_stale_version, ok_object, error_response, require_auth, require_role,
    get_pagination, paginate, sort_by_created, get_body,
)
from services import (
    REGIONS, PROVIDERS, PARTICIPATION, CONSENT_ENFORCEMENT, REPO_OPTIONS,
    REPORT_VISIBILITY, SOURCE_TYPES, MANUAL_SOURCE_TYPES, MATCH_CATEGORIES,
    INTERPRETATIONS, APPLIES_TO, CONSENT_ACTIONS, GRACE_DAYS,
    stamp_new, stamp_common, bump, word_count_of,
    lazy_auto_close_assignment, lazy_expire_policy,
    reports_of_submission, report_of_submission, stale_report,
    stale_reports_touching_source, retract_source_cascade,
    deposits_of_submission, recompute_comparable, withdraw_deposit,
    consent_withdraw_cascade, institution_opt_out_cascade,
    institution_opt_in_cascade, supersede_submission, recompute_submission_count,
    institution_of_submission, assignment_of_submission, integration_of_assignment,
)
from calcs import (
    compute_weighted_words, similarity_score_bps, filtered_fragment_set,
    ai_confidence,
)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e)


@app.errorhandler(404)
def handle_404(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(405)
def handle_405(e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "Resource not found"))


@app.errorhandler(Exception)
def handle_exc(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_VALIDATION", 400, str(e)))


# ---------------- serializers ----------------

def ser_institution(x):
    return {
        "id": x["id"], "name": x["name"], "residency_region": x["residency_region"],
        "repository_participation": x["repository_participation"],
        "cross_institution_comparison_enabled": x["cross_institution_comparison_enabled"],
        "ai_detection_enabled": x["ai_detection_enabled"],
        "data_residency_locked": x["data_residency_locked"],
        "comparable_submission_count": x["comparable_submission_count"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_integration(x):
    return {
        "id": x["id"], "institution_id": x["institution_id"], "provider": x["provider"],
        "external_key": x["external_key"], "status": x["status"],
        "consent_enforcement": x["consent_enforcement"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_instructor(x):
    return {
        "id": x["id"], "institution_id": x["institution_id"], "email": x["email"],
        "full_name": x["full_name"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_student(x):
    return {
        "id": x["id"], "institution_id": x["institution_id"],
        "external_lms_id": x["external_lms_id"], "email": x["email"],
        "full_name": x["full_name"], "home_region": x["home_region"],
        "consent_status": x["consent_status"], "consent_recorded_at": x["consent_recorded_at"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_assignment(x):
    return {
        "id": x["id"], "lms_integration_id": x["lms_integration_id"],
        "instructor_id": x["instructor_id"], "title": x["title"], "due_at": x["due_at"],
        "accepting_state": x["accepting_state"], "report_visibility": x["report_visibility"],
        "repository_option": x["repository_option"],
        "exclude_quotes": x["exclude_quotes"], "exclude_bibliography": x["exclude_bibliography"],
        "exclude_small_matches": x["exclude_small_matches"],
        "small_match_threshold_words": x["small_match_threshold_words"],
        "max_submissions_per_student": x["max_submissions_per_student"],
        "submission_count": x["submission_count"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_submission(x):
    return {
        "id": x["id"], "assignment_id": x["assignment_id"], "student_id": x["student_id"],
        "content_text": x["content_text"], "word_count": x["word_count"],
        "pipeline_state": x["pipeline_state"], "revision_number": x["revision_number"],
        "supersedes_submission_id": x["supersedes_submission_id"],
        "submitted_at": x["submitted_at"],
        "ai_burstiness": x["ai_burstiness"], "ai_perplexity": x["ai_perplexity"],
        "ai_stylometry": x["ai_stylometry"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_source(x):
    return {
        "id": x["id"], "origin_institution_id": x["origin_institution_id"],
        "source_type": x["source_type"], "uri": x["uri"], "region": x["region"],
        "publication_date": x["publication_date"], "status": x["status"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_fragment(x):
    return {
        "id": x["id"], "submission_id": x["submission_id"],
        "source_document_id": x["source_document_id"],
        "matched_word_count": x["matched_word_count"],
        "match_category": x["match_category"], "offset_start": x["offset_start"],
        "weighted_words": x["weighted_words"], "excluded": x["excluded"],
        "created_at": x["created_at"],
    }


def ser_report(x):
    return {
        "id": x["id"], "submission_id": x["submission_id"],
        "raw_score_bps": x["raw_score_bps"], "filtered_score_bps": x["filtered_score_bps"],
        "exclusion_snapshot": x["exclusion_snapshot"], "report_state": x["report_state"],
        "instructor_interpretation": x["instructor_interpretation"],
        "finalized_at": x["finalized_at"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_assessment(x):
    return {
        "id": x["id"], "submission_id": x["submission_id"],
        "ai_score_bps": x["ai_score_bps"], "confidence_band": x["confidence_band"],
        "conservative_score_bps": x["conservative_score_bps"],
        "assessment_state": x["assessment_state"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_deposit(x):
    return {
        "id": x["id"], "submission_id": x["submission_id"],
        "institution_id": x["institution_id"], "scope": x["scope"],
        "deposit_state": x["deposit_state"], "stored_at": x["stored_at"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_policy(x):
    return {
        "id": x["id"], "institution_id": x["institution_id"], "region": x["region"],
        "applies_to": x["applies_to"], "retention_start": x["retention_start"],
        "retention_end": x["retention_end"], "policy_state": x["policy_state"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


def ser_grade(x):
    return {
        "id": x["id"], "submission_id": x["submission_id"],
        "score_points": x["score_points"], "feedback_text": x["feedback_text"],
        "grade_state": x["grade_state"], "pinned_report_version": x["pinned_report_version"],
        "created_at": x["created_at"], "updated_at": x["updated_at"], "version": x["version"],
    }


# ---------------- Institution ----------------

@app.post("/integrity/institutions")
def create_institution():
    require_auth()
    require_role("PlatformAdmin")
    body = get_body()
    name = body.get("name")
    residency_region = body.get("residency_region")
    if not isinstance(name, str) or not name:
        raise err_validation("name is required")
    if residency_region not in REGIONS:
        raise err_validation("residency_region must be one of EU, US, APAC")
    rp = body.get("repository_participation", "INSTITUTION_ONLY")
    if rp not in PARTICIPATION:
        raise err_validation("repository_participation invalid")
    cic = body.get("cross_institution_comparison_enabled", False)
    if not isinstance(cic, bool):
        raise err_validation("cross_institution_comparison_enabled must be boolean")
    ai = body.get("ai_detection_enabled", True)
    if not isinstance(ai, bool):
        raise err_validation("ai_detection_enabled must be boolean")
    drl = body.get("data_residency_locked", False)
    if not isinstance(drl, bool):
        raise err_validation("data_residency_locked must be boolean")
    inst = {
        "name": name, "residency_region": residency_region,
        "repository_participation": rp,
        "cross_institution_comparison_enabled": cic,
        "ai_detection_enabled": ai, "data_residency_locked": drl,
        "comparable_submission_count": 0,
    }
    stamp_new(inst); stamp_common(inst)
    DB["institutions"][inst["id"]] = inst
    return ok_object(ser_institution(inst), 201)


@app.get("/integrity/institutions/<id>")
def get_institution(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor", "Student")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    return ok_object(ser_institution(inst))


@app.patch("/integrity/institutions/<id>")
def patch_institution(id):
    require_auth()
    require_role("PlatformAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    body = get_body()
    if "expected_institution_version" not in body:
        raise err_validation("expected_institution_version is required")
    if not isinstance(body["expected_institution_version"], int):
        raise err_validation("expected_institution_version must be integer")
    new_rp = body.get("repository_participation")
    if new_rp is not None and new_rp not in PARTICIPATION:
        raise err_validation("repository_participation invalid")
    new_rr = body.get("residency_region")
    if new_rr is not None and new_rr not in REGIONS:
        raise err_validation("residency_region invalid")
    for fld in ("cross_institution_comparison_enabled", "ai_detection_enabled"):
        if fld in body and not isinstance(body[fld], bool):
            raise err_validation(f"{fld} must be boolean")
    # residency locked check (business-safety, priority 11)
    if new_rr is not None and new_rr != inst["residency_region"] and inst["data_residency_locked"]:
        raise ApiError("ERR_RESIDENCY_LOCKED", 409, "residency_region is immutable while data_residency_locked")
    # OCC (last)
    if body["expected_institution_version"] != inst["version"]:
        raise err_stale_version("institution version mismatch")
    old_rp = inst["repository_participation"]
    if new_rp is not None:
        inst["repository_participation"] = new_rp
    if new_rr is not None:
        inst["residency_region"] = new_rr
    for fld in ("cross_institution_comparison_enabled", "ai_detection_enabled"):
        if fld in body:
            inst[fld] = body[fld]
    bump(inst)
    new_part = inst["repository_participation"]
    if new_rp is not None and new_rp != old_rp:
        if new_part == "OPT_OUT":
            institution_opt_out_cascade(inst)
        elif old_rp == "OPT_OUT" and new_part in ("GLOBAL_SHARED", "INSTITUTION_ONLY"):
            institution_opt_in_cascade(inst)
    return ok_object(ser_institution(inst))


# ---------------- LMS integrations ----------------

@app.post("/integrity/institutions/<id>/lms-integrations")
def create_integration(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    body = get_body()
    provider = body.get("provider")
    external_key = body.get("external_key")
    if provider not in PROVIDERS:
        raise err_validation("provider invalid")
    if not isinstance(external_key, str) or not external_key:
        raise err_validation("external_key is required")
    ce = body.get("consent_enforcement", "STRICT")
    if ce not in CONSENT_ENFORCEMENT:
        raise err_validation("consent_enforcement invalid")
    li = {
        "institution_id": id, "provider": provider, "external_key": external_key,
        "status": "PENDING", "consent_enforcement": ce,
    }
    stamp_new(li); stamp_common(li)
    DB["lms_integrations"][li["id"]] = li
    return ok_object(ser_integration(li), 201)


@app.get("/integrity/institutions/<id>/lms-integrations")
def list_integrations(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    items = [ser_integration(x) for x in DB["lms_integrations"].values() if x["institution_id"] == id]
    return paginate(sort_by_created(items))


@app.post("/integrity/lms-integrations/<id>/activate")
def activate_integration(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    li = DB["lms_integrations"].get(id)
    if not li:
        raise err_not_found("integration not found")
    if li["status"] not in ("PENDING", "SUSPENDED"):
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "integration not in PENDING or SUSPENDED")
    li["status"] = "ACTIVE"
    bump(li)
    return ok_object(ser_integration(li))


@app.post("/integrity/lms-integrations/<id>/suspend")
def suspend_integration(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    li = DB["lms_integrations"].get(id)
    if not li:
        raise err_not_found("integration not found")
    if li["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "integration not ACTIVE")
    li["status"] = "SUSPENDED"
    bump(li)
    # cascade: OPEN assignments of this integration -> CLOSED
    for a in DB["assignments"].values():
        if a["lms_integration_id"] == id and a["accepting_state"] == "OPEN":
            a["accepting_state"] = "CLOSED"
            bump(a)
    return ok_object(ser_integration(li))


# ---------------- Instructors ----------------

@app.post("/integrity/institutions/<id>/instructors")
def create_instructor(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    body = get_body()
    email = body.get("email"); full_name = body.get("full_name")
    if not isinstance(email, str) or not email:
        raise err_validation("email is required")
    if not isinstance(full_name, str) or not full_name:
        raise err_validation("full_name is required")
    ins = {"institution_id": id, "email": email, "full_name": full_name}
    stamp_new(ins); stamp_common(ins)
    DB["instructors"][ins["id"]] = ins
    return ok_object(ser_instructor(ins), 201)


@app.get("/integrity/institutions/<id>/instructors")
def list_instructors(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    items = [ser_instructor(x) for x in DB["instructors"].values() if x["institution_id"] == id]
    return paginate(sort_by_created(items))


# ---------------- Students ----------------

@app.post("/integrity/institutions/<id>/students")
def create_student(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    body = get_body()
    external_lms_id = body.get("external_lms_id")
    email = body.get("email"); full_name = body.get("full_name")
    home_region = body.get("home_region")
    if not isinstance(external_lms_id, str) or not external_lms_id:
        raise err_validation("external_lms_id is required")
    if not isinstance(email, str) or not email:
        raise err_validation("email is required")
    if not isinstance(full_name, str) or not full_name:
        raise err_validation("full_name is required")
    if home_region not in REGIONS:
        raise err_validation("home_region invalid")
    st = {
        "institution_id": id, "external_lms_id": external_lms_id, "email": email,
        "full_name": full_name, "home_region": home_region,
        "consent_status": "NOT_GIVEN", "consent_recorded_at": None,
    }
    stamp_new(st); stamp_common(st)
    DB["students"][st["id"]] = st
    return ok_object(ser_student(st), 201)


@app.get("/integrity/institutions/<id>/students")
def list_students(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    items = [ser_student(x) for x in DB["students"].values() if x["institution_id"] == id]
    return paginate(sort_by_created(items))


@app.post("/integrity/students/<id>/consents")
def consent(id):
    require_auth()
    require_role("Student", "InstitutionalAdmin")
    st = DB["students"].get(id)
    if not st:
        raise err_not_found("student not found")
    # ownership: Student role may only write own record
    if g.user_role == "Student" and g.user_id != id:
        raise err_forbidden("students may only record consent on own record")
    body = get_body()
    if "expected_student_version" not in body:
        raise err_validation("expected_student_version is required")
    if not isinstance(body["expected_student_version"], int):
        raise err_validation("expected_student_version must be integer")
    action = body.get("consent_action")
    if action not in CONSENT_ACTIONS:
        raise err_validation("consent_action must be GRANT or WITHDRAW")
    cur = st["consent_status"]
    if action == "GRANT":
        if cur not in ("NOT_GIVEN", "WITHDRAWN"):
            raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "consent already granted")
    else:  # WITHDRAW
        if cur != "GRANTED":
            raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "consent not granted")
    # OCC last
    if body["expected_student_version"] != st["version"]:
        raise err_stale_version("student version mismatch")
    st["consent_status"] = "GRANTED" if action == "GRANT" else "WITHDRAWN"
    st["consent_recorded_at"] = fmt_iso(now_logical())
    bump(st)
    if action == "WITHDRAW":
        consent_withdraw_cascade(id)
    return ok_object(ser_student(st))


# ---------------- Assignments ----------------

@app.post("/integrity/lms-integrations/<id>/assignments")
def create_assignment(id):
    require_auth()
    require_role("Instructor")
    li = DB["lms_integrations"].get(id)
    if not li:
        raise err_not_found("integration not found")
    body = get_body()
    instructor_id = body.get("instructor_id")
    if not isinstance(instructor_id, str) or not instructor_id:
        raise err_validation("instructor_id is required")
    if instructor_id not in DB["instructors"]:
        raise err_not_found("instructor not found")
    # ownership: instructor_id must equal X-User-ID
    if instructor_id != g.user_id:
        raise err_forbidden("instructor_id must equal X-User-ID")
    title = body.get("title")
    due_at = body.get("due_at")
    if not isinstance(title, str) or not title:
        raise err_validation("title is required")
    if not isinstance(due_at, str):
        raise err_validation("due_at is required")
    try:
        parse_iso(due_at)
    except Exception:
        raise err_validation("due_at must be ISO8601")
    repository_option = body.get("repository_option", "COMPARE_ONLY")
    if repository_option not in REPO_OPTIONS:
        raise err_validation("repository_option invalid")
    for fld in ("exclude_quotes", "exclude_bibliography", "exclude_small_matches"):
        if fld in body and not isinstance(body[fld], bool):
            raise err_validation(f"{fld} must be boolean")
    smt = body.get("small_match_threshold_words", 8)
    if not isinstance(smt, int) or isinstance(smt, bool):
        raise err_validation("small_match_threshold_words must be integer")
    mss = body.get("max_submissions_per_student", 3)
    if not isinstance(mss, int) or isinstance(mss, bool):
        raise err_validation("max_submissions_per_student must be integer")
    # state: integration must be ACTIVE
    if li["status"] != "ACTIVE":
        raise ApiError("ERR_INTEGRATION_NOT_ACTIVE", 409, "integration not ACTIVE")
    if smt < 1 or smt > 32:
        raise ApiError("ERR_THRESHOLD_OUT_OF_RANGE", 422, "small_match_threshold_words out of range")
    if mss < 1 or mss > 10:
        raise err_validation("max_submissions_per_student out of range")
    a = {
        "lms_integration_id": id, "instructor_id": instructor_id, "title": title,
        "due_at": due_at, "accepting_state": "OPEN", "report_visibility": "HIDDEN",
        "repository_option": repository_option,
        "exclude_quotes": body.get("exclude_quotes", False),
        "exclude_bibliography": body.get("exclude_bibliography", False),
        "exclude_small_matches": body.get("exclude_small_matches", False),
        "small_match_threshold_words": smt,
        "max_submissions_per_student": mss,
        "submission_count": 0,
    }
    stamp_new(a); stamp_common(a)
    DB["assignments"][a["id"]] = a
    return ok_object(ser_assignment(a), 201)


@app.get("/integrity/lms-integrations/<id>/assignments")
def list_assignments_of_integration(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    li = DB["lms_integrations"].get(id)
    if not li:
        raise err_not_found("integration not found")
    items = []
    for a in DB["assignments"].values():
        if a["lms_integration_id"] == id:
            lazy_auto_close_assignment(a)
            items.append(ser_assignment(a))
    return paginate(sort_by_created(items))


@app.get("/integrity/assignments/<id>")
def get_assignment(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor", "Student")
    a = DB["assignments"].get(id)
    if not a:
        raise err_not_found("assignment not found")
    lazy_auto_close_assignment(a)
    return ok_object(ser_assignment(a))


@app.get("/integrity/assignments")
def list_assignments():
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    from flask import request
    instructor_id = request.args.get("instructor_id")
    li_id = request.args.get("lms_integration_id")
    items = []
    for a in DB["assignments"].values():
        if instructor_id and a["instructor_id"] != instructor_id:
            continue
        if li_id and a["lms_integration_id"] != li_id:
            continue
        lazy_auto_close_assignment(a)
        items.append(ser_assignment(a))
    return paginate(sort_by_created(items))


@app.patch("/integrity/assignments/<id>")
def patch_assignment(id):
    require_auth()
    require_role("Instructor")
    a = DB["assignments"].get(id)
    if not a:
        raise err_not_found("assignment not found")
    lazy_auto_close_assignment(a)
    # ownership
    if a["instructor_id"] != g.user_id:
        raise err_forbidden("acting instructor does not own the assignment")
    body = get_body()
    if "expected_assignment_version" not in body:
        raise err_validation("expected_assignment_version is required")
    if not isinstance(body["expected_assignment_version"], int):
        raise err_validation("expected_assignment_version must be integer")
    for fld in ("exclude_quotes", "exclude_bibliography", "exclude_small_matches"):
        if fld in body and not isinstance(body[fld], bool):
            raise err_validation(f"{fld} must be boolean")
    if "report_visibility" in body and body["report_visibility"] not in REPORT_VISIBILITY:
        raise err_validation("report_visibility invalid")
    if "repository_option" in body and body["repository_option"] not in REPO_OPTIONS:
        raise err_validation("repository_option invalid")
    if "small_match_threshold_words" in body:
        smt = body["small_match_threshold_words"]
        if not isinstance(smt, int) or isinstance(smt, bool):
            raise err_validation("small_match_threshold_words must be integer")
        if smt < 1 or smt > 32:
            raise ApiError("ERR_THRESHOLD_OUT_OF_RANGE", 422, "small_match_threshold_words out of range")
    # OCC last
    if body["expected_assignment_version"] != a["version"]:
        raise err_stale_version("assignment version mismatch")
    exclusion_changed = False
    for fld in ("exclude_quotes", "exclude_bibliography", "exclude_small_matches", "small_match_threshold_words"):
        if fld in body and body[fld] != a[fld]:
            exclusion_changed = True
            a[fld] = body[fld]
    if "report_visibility" in body:
        a["report_visibility"] = body["report_visibility"]
    if "repository_option" in body:
        a["repository_option"] = body["repository_option"]
    bump(a)
    if exclusion_changed:
        # cascade: DRAFT/FINALIZED reports of this assignment's submissions -> STALE
        for s in DB["submissions"].values():
            if s["assignment_id"] == a["id"]:
                rep = report_of_submission(s["id"])
                if rep:
                    stale_report(rep)
    return ok_object(ser_assignment(a))


# ---------------- Submissions ----------------

@app.post("/integrity/assignments/<id>/submissions")
def create_submission(id):
    require_auth()
    require_role("Student")
    a = DB["assignments"].get(id)
    if not a:
        raise err_not_found("assignment not found")
    body = get_body()
    student_id = body.get("student_id")
    if not isinstance(student_id, str) or not student_id:
        raise err_validation("student_id is required")
    # ownership
    if student_id != g.user_id:
        raise err_forbidden("student_id must equal X-User-ID")
    st = DB["students"].get(student_id)
    if not st:
        raise err_not_found("student not found")
    content_text = body.get("content_text")
    if not isinstance(content_text, str):
        raise err_validation("content_text is required")
    for fld in ("ai_burstiness", "ai_perplexity", "ai_stylometry"):
        if fld in body and body[fld] is not None:
            v = body[fld]
            if not isinstance(v, (int, float)) or isinstance(v, bool):
                raise err_validation(f"{fld} must be a number")
            if v < 0 or v > 1:
                raise err_validation(f"{fld} must be within [0,1]")
    supersedes = body.get("supersedes_submission_id")
    if supersedes is not None and not isinstance(supersedes, str):
        raise err_validation("supersedes_submission_id must be a string")
    # state: assignment gate (lazy auto-close first)
    lazy_auto_close_assignment(a)
    if a["accepting_state"] != "OPEN":
        raise ApiError("ERR_ASSIGNMENT_CLOSED", 409, "assignment closed")
    li = integration_of_assignment(a)
    inst = DB["institutions"].get(li["institution_id"]) if li else None
    # consent gate
    ce = li["consent_enforcement"]
    if ce == "STRICT":
        if st["consent_status"] != "GRANTED":
            raise ApiError("ERR_CONSENT_MISSING", 422, "consent required")
    else:  # LENIENT
        if st["consent_status"] == "WITHDRAWN":
            raise ApiError("ERR_CONSENT_MISSING", 422, "consent withdrawn")
    # residency
    if inst and inst["data_residency_locked"] and st["home_region"] != inst["residency_region"]:
        raise ApiError("ERR_RESIDENCY_VIOLATION", 422, "home_region violates residency lock")
    # content
    wc = word_count_of(content_text)
    if wc < 1:
        raise ApiError("ERR_CONTENT_INVALID", 422, "content_text empty or zero words")
    # quota
    live = sum(
        1 for s in DB["submissions"].values()
        if s["assignment_id"] == id and s["student_id"] == student_id
        and s["pipeline_state"] != "SUPERSEDED"
    )
    if live >= a["max_submissions_per_student"]:
        raise ApiError("ERR_SUBMISSION_LIMIT_REACHED", 422, "submission limit reached")
    # supersede target
    prior = None
    if supersedes is not None:
        prior = DB["submissions"].get(supersedes)
        if not prior:
            raise ApiError("ERR_INVALID_SUPERSEDE_TARGET", 422, "supersede target not found")
        if prior["student_id"] != student_id or prior["assignment_id"] != id:
            raise ApiError("ERR_INVALID_SUPERSEDE_TARGET", 422, "supersede target mismatch")
        if prior["pipeline_state"] not in ("REPORT_READY", "FAILED"):
            raise ApiError("ERR_INVALID_SUPERSEDE_TARGET", 422, "supersede target state invalid")
    sub = {
        "assignment_id": id, "student_id": student_id, "content_text": content_text,
        "word_count": wc, "pipeline_state": "RECEIVED",
        "revision_number": (prior["revision_number"] + 1) if prior else 1,
        "supersedes_submission_id": supersedes,
        "submitted_at": fmt_iso(now_logical()),
        "ai_burstiness": body.get("ai_burstiness"),
        "ai_perplexity": body.get("ai_perplexity"),
        "ai_stylometry": body.get("ai_stylometry"),
    }
    stamp_new(sub); stamp_common(sub)
    DB["submissions"][sub["id"]] = sub
    if prior:
        supersede_submission(prior)
    recompute_submission_count(id)
    return ok_object(ser_submission(sub), 201)


@app.get("/integrity/assignments/<id>/submissions")
def list_submissions_of_assignment(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    a = DB["assignments"].get(id)
    if not a:
        raise err_not_found("assignment not found")
    items = [ser_submission(s) for s in DB["submissions"].values() if s["assignment_id"] == id]
    return paginate(sort_by_created(items))


@app.get("/integrity/submissions/<id>")
def get_submission(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor", "Student")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    if g.user_role == "Student" and s["student_id"] != g.user_id:
        raise err_forbidden("students may read only own submissions")
    return ok_object(ser_submission(s))


@app.get("/integrity/submissions")
def list_submissions():
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    from flask import request
    student_id = request.args.get("student_id")
    supersedes = request.args.get("supersedes_submission_id")
    items = []
    for s in DB["submissions"].values():
        if student_id and s["student_id"] != student_id:
            continue
        if supersedes and s["supersedes_submission_id"] != supersedes:
            continue
        items.append(ser_submission(s))
    return paginate(sort_by_created(items))


# ---------------- Process pipeline ----------------

@app.post("/integrity/submissions/<id>/process")
def process_submission(id):
    require_auth()
    require_role("Instructor", "PlatformAdmin")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    if s["pipeline_state"] not in ("RECEIVED", "FAILED", "REPORT_READY"):
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "submission cannot be processed from current state")
    a = assignment_of_submission(s)
    li = integration_of_assignment(a) if a else None
    inst = DB["institutions"].get(li["institution_id"]) if li else None
    # transient PROCESSING bump
    s["pipeline_state"] = "PROCESSING"
    bump(s)
    if s["word_count"] == 0:
        s["pipeline_state"] = "FAILED"
        return ok_object(ser_submission(s))
    # success branch
    s["pipeline_state"] = "REPORT_READY"
    # --- similarity report upsert ---
    snapshot = {
        "exclude_quotes": a["exclude_quotes"],
        "exclude_bibliography": a["exclude_bibliography"],
        "exclude_small_matches": a["exclude_small_matches"],
        "small_match_threshold_words": a["small_match_threshold_words"],
    }
    frags = [f for f in DB["match_fragments"].values() if f["submission_id"] == id]
    non_excl = [f for f in frags if not f["excluded"]]
    raw = similarity_score_bps(non_excl, s["word_count"])
    filtered_set = filtered_fragment_set(frags, snapshot)
    filtered = similarity_score_bps(filtered_set, s["word_count"])
    rep = report_of_submission(id)
    if rep:
        rep["raw_score_bps"] = raw
        rep["filtered_score_bps"] = filtered
        rep["exclusion_snapshot"] = snapshot
        rep["report_state"] = "DRAFT"
        rep["instructor_interpretation"] = None
        rep["finalized_at"] = None
        bump(rep)
    else:
        rep = {
            "submission_id": id, "raw_score_bps": raw, "filtered_score_bps": filtered,
            "exclusion_snapshot": snapshot, "report_state": "DRAFT",
            "instructor_interpretation": None, "finalized_at": None,
        }
        stamp_new(rep); stamp_common(rep)
        DB["similarity_reports"][rep["id"]] = rep
    # --- AI writing assessment upsert ---
    assessment = None
    for x in DB["ai_writing_assessments"].values():
        if x["submission_id"] == id:
            assessment = x
            break
    ai_enabled = inst["ai_detection_enabled"] if inst else True
    signals = (s["ai_burstiness"], s["ai_perplexity"], s["ai_stylometry"])
    if not ai_enabled or s["word_count"] < 250:
        new_state = "SUPPRESSED"
        score = band = cons = None
    elif all(v is not None for v in signals):
        score, band, cons = ai_confidence(*signals)
        new_state = "COMPLETE"
    else:
        # required but signals absent: stays PENDING
        new_state = "PENDING"
        score = band = cons = None
    if assessment:
        assessment["assessment_state"] = new_state
        assessment["ai_score_bps"] = score
        assessment["confidence_band"] = band
        assessment["conservative_score_bps"] = cons
        bump(assessment)
    else:
        assessment = {
            "submission_id": id, "ai_score_bps": score, "confidence_band": band,
            "conservative_score_bps": cons, "assessment_state": new_state,
        }
        stamp_new(assessment); stamp_common(assessment)
        DB["ai_writing_assessments"][assessment["id"]] = assessment
    # --- repository deposit ---
    if a["repository_option"] == "STORE_AND_COMPARE" and inst:
        scope = "GLOBAL_SHARED" if inst["repository_participation"] == "GLOBAL_SHARED" else "INSTITUTION_ONLY"
        dep_state = "QUARANTINED" if inst["repository_participation"] == "OPT_OUT" else "STORED"
        dep = {
            "submission_id": id, "institution_id": inst["id"], "scope": scope,
            "deposit_state": dep_state, "stored_at": fmt_iso(now_logical()),
            "quarantine_cause": "participation" if dep_state == "QUARANTINED" else None,
        }
        stamp_new(dep); stamp_common(dep)
        DB["repository_deposits"][dep["id"]] = dep
        src = {
            "origin_institution_id": inst["id"],
            "source_type": "STUDENT_REPOSITORY",
            "uri": f"repository://{dep['id']}",
            "region": inst["residency_region"],
            "publication_date": None, "status": "ACTIVE",
            "auto_deposit_id": dep["id"],
        }
        stamp_new(src); stamp_common(src)
        DB["source_documents"][src["id"]] = src
        recompute_comparable(inst["id"])
    recompute_submission_count(a["id"])
    return ok_object(ser_submission(s))


# ---------------- Source documents ----------------

@app.post("/integrity/institutions/<id>/source-documents")
def create_source(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    body = get_body()
    source_type = body.get("source_type")
    if source_type == "STUDENT_REPOSITORY":
        raise err_validation("STUDENT_REPOSITORY sources cannot be created manually")
    if source_type not in MANUAL_SOURCE_TYPES:
        raise err_validation("source_type invalid")
    uri = body.get("uri")
    if not isinstance(uri, str) or not uri:
        raise err_validation("uri is required")
    region = body.get("region")
    if region not in REGIONS:
        raise err_validation("region invalid")
    pub = body.get("publication_date")
    if pub is not None:
        if not isinstance(pub, str):
            raise err_validation("publication_date must be ISO8601 or null")
        try:
            parse_iso(pub)
        except Exception:
            raise err_validation("publication_date must be ISO8601 or null")
    src = {
        "origin_institution_id": id, "source_type": source_type, "uri": uri,
        "region": region, "publication_date": pub, "status": "ACTIVE",
        "auto_deposit_id": None,
    }
    stamp_new(src); stamp_common(src)
    DB["source_documents"][src["id"]] = src
    return ok_object(ser_source(src), 201)


@app.get("/integrity/institutions/<id>/source-documents")
def list_sources(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    items = [ser_source(x) for x in DB["source_documents"].values() if x["origin_institution_id"] == id]
    return paginate(sort_by_created(items))


@app.get("/integrity/source-documents/<id>")
def get_source(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    src = DB["source_documents"].get(id)
    if not src:
        raise err_not_found("source not found")
    return ok_object(ser_source(src))


@app.post("/integrity/source-documents/<id>/retract")
def retract_source(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    src = DB["source_documents"].get(id)
    if not src:
        raise err_not_found("source not found")
    if src["status"] != "ACTIVE":
        raise ApiError("ERR_SOURCE_RETRACTED", 409, "source already retracted")
    retract_source_cascade(src)
    return ok_object(ser_source(src))


# ---------------- Match fragments ----------------

@app.get("/integrity/submissions/<id>/match-fragments")
def list_fragments_of_submission(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    items = [ser_fragment(f) for f in DB["match_fragments"].values() if f["submission_id"] == id]
    return paginate(sort_by_created(items))


@app.get("/integrity/source-documents/<id>/match-fragments")
def list_fragments_of_source(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    src = DB["source_documents"].get(id)
    if not src:
        raise err_not_found("source not found")
    items = [ser_fragment(f) for f in DB["match_fragments"].values() if f["source_document_id"] == id]
    return paginate(sort_by_created(items))


@app.post("/integrity/_matches/inject")
def inject_fragment():
    require_auth()
    require_role("PlatformAdmin")
    body = get_body()
    submission_id = body.get("submission_id")
    source_document_id = body.get("source_document_id")
    if not isinstance(submission_id, str) or not submission_id:
        raise err_validation("submission_id is required")
    if not isinstance(source_document_id, str) or not source_document_id:
        raise err_validation("source_document_id is required")
    s = DB["submissions"].get(submission_id)
    if not s:
        raise err_not_found("submission not found")
    src = DB["source_documents"].get(source_document_id)
    if not src:
        raise err_not_found("source not found")
    mwc = body.get("matched_word_count")
    if not isinstance(mwc, int) or isinstance(mwc, bool):
        raise err_validation("matched_word_count must be integer")
    if mwc < 1:
        raise err_validation("matched_word_count must be >= 1")
    cat = body.get("match_category")
    if cat not in MATCH_CATEGORIES:
        raise err_validation("match_category invalid")
    off = body.get("offset_start")
    if not isinstance(off, int) or isinstance(off, bool):
        raise err_validation("offset_start must be integer")
    if off < 0:
        raise err_validation("offset_start must be >= 0")
    # state: source must be ACTIVE
    if src["status"] != "ACTIVE":
        raise ApiError("ERR_SOURCE_RETRACTED", 409, "source retracted")
    # cross-region / cross-institution check
    inst = institution_of_submission(s)
    allowed = False
    if inst and src["region"] == inst["residency_region"]:
        allowed = True
    elif src["source_type"] == "STUDENT_REPOSITORY" and src.get("auto_deposit_id"):
        dep = DB["repository_deposits"].get(src["auto_deposit_id"])
        if dep and dep["deposit_state"] == "STORED" and dep["scope"] == "GLOBAL_SHARED":
            origin_inst = DB["institutions"].get(src["origin_institution_id"])
            if (origin_inst and inst
                    and origin_inst["cross_institution_comparison_enabled"]
                    and inst["cross_institution_comparison_enabled"]):
                allowed = True
    if not allowed:
        raise ApiError("ERR_CROSS_REGION_COMPARISON", 422, "cross-region comparison not permitted")
    frag = {
        "submission_id": submission_id, "source_document_id": source_document_id,
        "matched_word_count": mwc, "match_category": cat, "offset_start": off,
        "weighted_words": compute_weighted_words(mwc, cat),
        "excluded": False,
    }
    stamp_new(frag)  # MatchFragment has no common fields
    DB["match_fragments"][frag["id"]] = frag
    return ok_object(ser_fragment(frag), 201)


# ---------------- Similarity reports ----------------

@app.get("/integrity/submissions/<id>/similarity-reports")
def get_reports_of_submission(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor", "Student")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    if g.user_role == "Student":
        if s["student_id"] != g.user_id:
            raise err_forbidden("students may read only own reports")
        a = assignment_of_submission(s)
        if not a or a["report_visibility"] != "RELEASED":
            raise err_forbidden("report not released")
    items = [ser_report(r) for r in reports_of_submission(id)]
    return paginate(sort_by_created(items))


@app.post("/integrity/similarity-reports/<id>/finalize")
def finalize_report(id):
    require_auth()
    require_role("Instructor")
    rep = DB["similarity_reports"].get(id)
    if not rep:
        raise err_not_found("report not found")
    s = DB["submissions"].get(rep["submission_id"])
    a = assignment_of_submission(s) if s else None
    if not a or a["instructor_id"] != g.user_id:
        raise err_forbidden("acting instructor does not own the assignment")
    body = get_body()
    interp = body.get("instructor_interpretation")
    if interp is not None and interp not in INTERPRETATIONS:
        raise err_validation("instructor_interpretation invalid")
    # state checks
    if rep["report_state"] == "STALE":
        raise ApiError("ERR_REPORT_STALE", 409, "stale report must be regenerated first")
    if rep["report_state"] != "DRAFT":
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "report not DRAFT")
    if interp is None:
        raise err_validation("instructor_interpretation is required")
    rep["instructor_interpretation"] = interp
    rep["report_state"] = "FINALIZED"
    rep["finalized_at"] = fmt_iso(now_logical())
    bump(rep)
    # cascade: PROVISIONAL grade entries -> RELEASED
    for ge in DB["grade_entries"].values():
        if ge["submission_id"] == rep["submission_id"] and ge["grade_state"] == "PROVISIONAL":
            ge["grade_state"] = "RELEASED"
            bump(ge)
    return ok_object(ser_report(rep))


# ---------------- AI writing assessments ----------------

@app.get("/integrity/submissions/<id>/ai-writing-assessments")
def get_assessments(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    items = [ser_assessment(x) for x in DB["ai_writing_assessments"].values() if x["submission_id"] == id]
    return paginate(sort_by_created(items))


# ---------------- Repository deposits ----------------

@app.get("/integrity/submissions/<id>/repository-deposits")
def get_deposits_of_submission(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    items = [ser_deposit(d) for d in deposits_of_submission(id)]
    return paginate(sort_by_created(items))


@app.get("/integrity/institutions/<id>/repository-deposits")
def get_deposits_of_institution(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    items = [ser_deposit(d) for d in DB["repository_deposits"].values() if d["institution_id"] == id]
    return paginate(sort_by_created(items))


@app.post("/integrity/repository-deposits/<id>/withdraw")
def withdraw_deposit_route(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    dep = DB["repository_deposits"].get(id)
    if not dep:
        raise err_not_found("deposit not found")
    if dep["deposit_state"] not in ("STORED", "QUARANTINED"):
        raise ApiError("ERR_INVALID_SUBMISSION_STATE", 409, "deposit already withdrawn")
    withdraw_deposit(dep, retract_source=True)
    return ok_object(ser_deposit(dep))


# ---------------- Retention policies ----------------

def _windows_overlap(a_start, a_end, b_start, b_end):
    # half-open intervals: adjacency (a_end == b_start) is NOT overlap
    return a_start < b_end and b_start < a_end


def _applies_collide(x, y):
    if x == "BOTH" or y == "BOTH":
        return True
    return x == y


@app.post("/integrity/institutions/<id>/retention-policies")
def create_policy(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    body = get_body()
    region = body.get("region")
    if region not in REGIONS:
        raise err_validation("region invalid")
    applies_to = body.get("applies_to")
    if applies_to not in APPLIES_TO:
        raise err_validation("applies_to invalid")
    rs = body.get("retention_start")
    re_ = body.get("retention_end")
    if not isinstance(rs, str) or not isinstance(re_, str):
        raise err_validation("retention_start and retention_end are required")
    try:
        rs_dt = parse_iso(rs); re_dt = parse_iso(re_)
    except Exception:
        raise err_validation("retention window must be ISO8601")
    # temporal rules
    if not (rs_dt < re_dt) or region != inst["residency_region"]:
        raise ApiError("ERR_INVALID_RETENTION_WINDOW", 422, "invalid retention window")
    for p in DB["data_retention_policies"].values():
        if p["institution_id"] != id:
            continue
        lazy_expire_policy(p)
        if p["policy_state"] != "ACTIVE":
            continue
        if not _applies_collide(p["applies_to"], applies_to):
            continue
        if _windows_overlap(rs_dt, re_dt, parse_iso(p["retention_start"]), parse_iso(p["retention_end"])):
            raise ApiError("ERR_RETENTION_WINDOW_OVERLAP", 409, "retention window overlaps existing policy")
    pol = {
        "institution_id": id, "region": region, "applies_to": applies_to,
        "retention_start": rs, "retention_end": re_, "policy_state": "ACTIVE",
    }
    stamp_new(pol); stamp_common(pol)
    DB["data_retention_policies"][pol["id"]] = pol
    return ok_object(ser_policy(pol), 201)


@app.get("/integrity/institutions/<id>/retention-policies")
def list_policies(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    inst = DB["institutions"].get(id)
    if not inst:
        raise err_not_found("institution not found")
    items = []
    for p in DB["data_retention_policies"].values():
        if p["institution_id"] == id:
            lazy_expire_policy(p)
            items.append(ser_policy(p))
    return paginate(sort_by_created(items))


@app.post("/integrity/retention-policies/<id>/run-purge")
def run_purge(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin")
    pol = DB["data_retention_policies"].get(id)
    if not pol:
        raise err_not_found("policy not found")
    lazy_expire_policy(pol)
    if pol["policy_state"] != "ACTIVE":
        raise ApiError("ERR_POLICY_EXPIRED", 409, "policy expired")
    rs_dt = parse_iso(pol["retention_start"])
    re_dt = parse_iso(pol["retention_end"])
    grace_start = rs_dt - timedelta(days=GRACE_DAYS)
    candidates = []
    if pol["applies_to"] in ("SUBMISSIONS", "BOTH"):
        for s in DB["submissions"].values():
            inst = institution_of_submission(s)
            if not inst or inst["id"] != pol["institution_id"]:
                continue
            if s["pipeline_state"] == "SUPERSEDED":
                continue
            sub_dt = parse_iso(s["submitted_at"])
            if rs_dt <= sub_dt < re_dt:
                candidates.append(s)
    candidates.sort(key=lambda s: (s["submitted_at"], s["created_at"]))
    # aggregate grace conflict check
    for s in candidates:
        for dep in deposits_of_submission(s["id"]):
            if dep["deposit_state"] == "STORED":
                stored_dt = parse_iso(dep["stored_at"])
                if grace_start <= stored_dt <= re_dt:
                    raise ApiError("ERR_PURGE_GRACE_CONFLICT", 409, "purge grace conflict")
    purged_ids = []
    for s in candidates:
        sid = s["id"]
        purged_ids.append(sid)
        # deposits STORED/QUARANTINED -> WITHDRAWN (no source retraction on purge)
        for dep in deposits_of_submission(sid):
            if dep["deposit_state"] in ("STORED", "QUARANTINED"):
                dep["deposit_state"] = "WITHDRAWN"
                bump(dep)
                recompute_comparable(dep["institution_id"])
        # delete fragments and reports of this submission
        for fid in [f["id"] for f in DB["match_fragments"].values() if f["submission_id"] == sid]:
            del DB["match_fragments"][fid]
        for rid in [r["id"] for r in DB["similarity_reports"].values() if r["submission_id"] == sid]:
            del DB["similarity_reports"][rid]
        aid = s["assignment_id"]
        del DB["submissions"][sid]
        recompute_submission_count(aid)
    return ok_object({"purged_count": len(purged_ids), "purged_submission_ids": purged_ids})


# ---------------- Grade entries ----------------

@app.post("/integrity/submissions/<id>/grade-entries")
def create_grade(id):
    require_auth()
    require_role("Instructor")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    body = get_body()
    sp = body.get("score_points")
    if not isinstance(sp, (int, float)) or isinstance(sp, bool):
        raise err_validation("score_points must be a number")
    if sp < 0:
        raise err_validation("score_points must be >= 0")
    fb = body.get("feedback_text", "")
    if not isinstance(fb, str):
        raise err_validation("feedback_text must be a string")
    rep = report_of_submission(id)
    if not rep or rep["report_state"] not in ("DRAFT", "FINALIZED"):
        raise ApiError("ERR_GRADE_REQUIRES_REPORT", 409, "grade requires a DRAFT or FINALIZED report")
    ge = {
        "submission_id": id, "score_points": sp, "feedback_text": fb,
        "grade_state": "PROVISIONAL", "pinned_report_version": rep["version"],
    }
    stamp_new(ge); stamp_common(ge)
    DB["grade_entries"][ge["id"]] = ge
    return ok_object(ser_grade(ge), 201)


@app.get("/integrity/submissions/<id>/grade-entries")
def list_grades(id):
    require_auth()
    require_role("PlatformAdmin", "InstitutionalAdmin", "Instructor")
    s = DB["submissions"].get(id)
    if not s:
        raise err_not_found("submission not found")
    items = [ser_grade(x) for x in DB["grade_entries"].values() if x["submission_id"] == id]
    return paginate(sort_by_created(items))


# ---------------- Clock ----------------

@app.post("/integrity/_clock/set_current_utc")
def set_clock():
    require_auth()
    require_role("PlatformAdmin")
    body = get_body()
    to = body.get("to_iso8601")
    if not isinstance(to, str):
        raise err_validation("to_iso8601 is required")
    try:
        dt = parse_iso(to)
    except Exception:
        raise err_validation("to_iso8601 must be ISO8601")
    set_logical(dt)
    return ok_object({"current_utc": fmt_iso(dt)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
