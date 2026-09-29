"""Assessment attempts, submission screen and rubric scoring (PRD 3.5, 3.6)."""
from flask import Blueprint, request

import db as store
from db import db, new_row, touch
from errors import ApiError, bad_request
from middleware import (ROLE_EVALUATOR, ROLE_FACULTY_MENTOR,
                        ROLE_INTEGRITY_OFFICER, ROLE_PLATFORM_ADMIN,
                        ROLE_REGISTRAR, ROLE_STUDENT, check_evaluator_ownership,
                        check_student_ownership, require)
from response import json_body, created_response, object_response, paginated
from services import calc, cascade, derive, lookup, serialize, shape
from services.nums import ZERO, dec, rhu

bp = Blueprint("attempts", __name__)

ATTEMPT_READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_FACULTY_MENTOR,
                      ROLE_EVALUATOR, ROLE_INTEGRITY_OFFICER, ROLE_STUDENT)
SCORE_READ_ROLES = (ROLE_REGISTRAR, ROLE_PLATFORM_ADMIN, ROLE_EVALUATOR,
                    ROLE_INTEGRITY_OFFICER)

SHARED_DEVICE_WINDOW_SECONDS = 72 * 3600


def _arg(name):
    raw = request.args.get(name, None)
    if raw is None:
        return None
    text = raw.strip()
    return text if text else None


def _consumable_endorsement(student_id, competency_id):
    """The oldest unconsumed endorsement for the pair, or None."""
    candidates = []
    for asg in lookup.assignments_of(student_id):
        for endorsement in derive.unconsumed_endorsements(asg):
            if endorsement["competency_id"] == competency_id:
                candidates.append((endorsement["created_at"],
                                   endorsement["seq"], asg, endorsement))
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2], candidates[0][3]


def _failed_attempts(student_id, competency_id):
    return [a for a in db.attempts.values()
            if a["student_id"] == student_id
            and a["competency_id"] == competency_id
            and a["status"] == "SCORED_NOT_MASTERED"]


@bp.route("/assessment-attempts", methods=["POST"])
def create_attempt():
    caller = require(ROLE_STUDENT, ROLE_REGISTRAR)
    body = json_body()
    check_student_ownership(caller, shape.raw_id(body, "student_id"))
    student = lookup.student(shape.req_id(body, "student_id"))
    competency = lookup.competency(shape.req_id(body, "competency_id"))
    program = lookup.program_of_competency(competency)
    if program is None or program["status"] != "PUBLISHED":
        raise ApiError("ERR_PROGRAM_NOT_PUBLISHED")
    if competency["status"] != "ACTIVE":
        raise ApiError("ERR_COMPETENCY_RETIRED")
    if student["enrollment_status"] != "ACTIVE":
        raise ApiError("ERR_STUDENT_NOT_ACTIVE")
    term = derive.active_term_covering_clock(student["id"])
    if term is None:
        raise ApiError("ERR_TERM_NOT_ACTIVE")
    policy = lookup.program_of_student(student) or program
    # rung one: redundant work
    if competency["id"] in derive.mastered_competency_map(student["id"]):
        raise ApiError("ERR_COMPETENCY_ALREADY_MASTERED")
    # rung two: the prerequisite chain, walked transitively to its root
    mastered = derive.mastered_competency_map(student["id"])
    cursor = db.competencies.get(competency["prerequisite_competency_id"]) \
        if competency["prerequisite_competency_id"] else None
    seen = set()
    while cursor is not None and cursor["id"] not in seen:
        seen.add(cursor["id"])
        if cursor["id"] not in mastered:
            raise ApiError("ERR_PREREQUISITE_NOT_MASTERED")
        nxt = cursor["prerequisite_competency_id"]
        cursor = db.competencies.get(nxt) if nxt else None
    blueprint = derive.effective_blueprint(competency)
    if blueprint is None:
        raise ApiError("ERR_NO_EFFECTIVE_BLUEPRINT")
    # rung three: the cool-off window
    failed = _failed_attempts(student["id"], competency["id"])
    if failed:
        latest = store.by_created(failed)[-1]
        until = derive.attempt_cooloff_until(latest)
        if until is not None and db.now() < until:
            raise ApiError("ERR_ATTEMPT_COOLOFF_ACTIVE")
    # rung four: the endorsement gate
    assignment = None
    endorsement = None
    if len(failed) >= policy["attempts_before_endorsement"]:
        assignment, endorsement = _consumable_endorsement(student["id"],
                                                          competency["id"])
        if endorsement is None:
            raise ApiError("ERR_MENTOR_ENDORSEMENT_REQUIRED")
    # rung five: the cadence gate, then the integrity gate
    active_assignment = derive.active_assignment(student["id"])
    if active_assignment is not None:
        _status, overdue, _due = derive.cadence_state(active_assignment)
        if overdue >= policy["cadence_gate_overdue_days"]:
            raise ApiError("ERR_MENTOR_CADENCE_OVERDUE")
    if derive.student_has_live_case(student["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD_ACTIVE")
    row = new_row()
    row.update({
        "student_id": student["id"],
        "competency_id": competency["id"],
        "blueprint_id": blueprint["id"],
        "term_id": term["id"],
        "status": "DRAFT",
        "held_from_status": None,
        "artifact_hash": None,
        "client_fingerprint": None,
        "integrity_attestation_accepted": False,
        "submitted_at_utc": None,
        "final_score_pct": None,
        "is_provisional_score": False,
        "score_variant": None,
        "critical_fail": False,
        "scored_at_utc": None,
        "mastered_at_utc": None,
        "revision_count": 0,
        "endorsement_consumed": False,
    })
    if endorsement is not None:
        endorsement["consumed"] = True
        row["endorsement_consumed"] = True
        touch(assignment)
    db.attempts[row["id"]] = row
    touch(term)
    touch(blueprint)
    return created_response(serialize.attempt(row))


@bp.route("/assessment-attempts/<aid>", methods=["GET"])
def read_attempt(aid):
    caller = require(*ATTEMPT_READ_ROLES)
    attempt = lookup.attempt(aid)
    check_student_ownership(caller, attempt["student_id"])
    return object_response(serialize.attempt(attempt))


@bp.route("/assessment-attempts", methods=["GET"])
def list_attempts():
    require(*ATTEMPT_READ_ROLES)
    student_id = _arg("student_id")
    competency_id = _arg("competency_id")
    blueprint_id = _arg("blueprint_id")
    term_id = _arg("term_id")
    status = _arg("status")
    rows = []
    for row in db.attempts.values():
        if student_id is not None and row["student_id"] != student_id:
            continue
        if competency_id is not None and row["competency_id"] != competency_id:
            continue
        if blueprint_id is not None and row["blueprint_id"] != blueprint_id:
            continue
        if term_id is not None and row["term_id"] != term_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    return paginated(store.by_created(rows), serialize.attempt)


@bp.route("/assessment-attempts/<aid>/reopen", methods=["POST"])
def reopen_attempt(aid):
    caller = require(ROLE_STUDENT, ROLE_REGISTRAR)
    attempt = lookup.attempt(aid)
    check_student_ownership(caller, attempt["student_id"])
    if attempt["status"] == "VOIDED":
        raise ApiError("ERR_ATTEMPT_VOIDED")
    if attempt["status"] != "REVISION_REQUESTED":
        raise ApiError("ERR_ATTEMPT_NOT_IN_REVISION")
    term = db.terms.get(attempt["term_id"])
    if term is None or term["status"] != "ACTIVE":
        raise ApiError("ERR_TERM_NOT_ACTIVE")
    attempt["status"] = "DRAFT"
    attempt["artifact_hash"] = None
    attempt["client_fingerprint"] = None
    attempt["integrity_attestation_accepted"] = False
    attempt["submitted_at_utc"] = None
    touch(attempt)
    return object_response(serialize.attempt(attempt))


# ---------------------------------------------------------------- submission

def _other_student_attempts(attempt):
    for other in db.attempts.values():
        if other["id"] == attempt["id"]:
            continue
        if other["status"] == "VOIDED":
            continue
        if other["student_id"] == attempt["student_id"]:
            continue
        yield other


def _integrity_signal(attempt, artifact_hash, fingerprint):
    """Duplicated artifact outranks the shared device when both fire."""
    shared = False
    duplicate = False
    now = db.now()
    for other in _other_student_attempts(attempt):
        if (other["artifact_hash"] is not None
                and other["artifact_hash"] == artifact_hash):
            duplicate = True
        submitted = other["submitted_at_utc"]
        if (other["client_fingerprint"] is not None
                and other["client_fingerprint"] == fingerprint
                and submitted is not None):
            elapsed = (now - submitted).total_seconds()
            if 0 <= elapsed <= SHARED_DEVICE_WINDOW_SECONDS:
                shared = True
    if duplicate:
        return "DUPLICATE_ARTIFACT"
    if shared:
        return "SHARED_DEVICE"
    return None


@bp.route("/assessment-attempts/<aid>/submit", methods=["POST"])
def submit_attempt(aid):
    caller = require(ROLE_STUDENT)
    attempt = lookup.attempt(aid)
    check_student_ownership(caller, attempt["student_id"])
    body = json_body()
    artifact_hash = shape.req_str(body, "artifact_hash")
    if not shape.present(body, "integrity_attestation_accepted"):
        raise bad_request("Field 'integrity_attestation_accepted' is required.")
    attested = body.get("integrity_attestation_accepted")
    if not shape.present(body, "client_fingerprint"):
        raise bad_request("Field 'client_fingerprint' is required.")
    fingerprint = body.get("client_fingerprint")
    if attempt["status"] == "VOIDED":
        raise ApiError("ERR_ATTEMPT_VOIDED")
    if attempt["status"] != "DRAFT":
        raise ApiError("ERR_ATTEMPT_NOT_DRAFT")
    term = db.terms.get(attempt["term_id"])
    now = db.now()
    if (term is None or term["status"] != "ACTIVE"
            or not (term["term_start_utc"] <= now < term["term_end_utc"])):
        raise ApiError("ERR_TERM_NOT_ACTIVE")
    if attested is not True:
        raise ApiError("ERR_ATTESTATION_REQUIRED")
    if not isinstance(fingerprint, str) or fingerprint.strip() == "":
        raise ApiError("ERR_ATTESTATION_REQUIRED")
    if derive.attempt_has_live_case(attempt["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD_ACTIVE")
    signal = _integrity_signal(attempt, artifact_hash, fingerprint)
    attempt["artifact_hash"] = artifact_hash
    attempt["client_fingerprint"] = fingerprint
    attempt["integrity_attestation_accepted"] = True
    attempt["submitted_at_utc"] = now
    if signal is None:
        attempt["status"] = "UNDER_REVIEW"
        touch(attempt)
        touch(term)
        return object_response(serialize.attempt(attempt))
    attempt["status"] = "INTEGRITY_HOLD"
    attempt["held_from_status"] = "UNDER_REVIEW"
    case = new_row()
    case.update({
        "attempt_id": attempt["id"],
        "student_id": attempt["student_id"],
        "signal_type": signal,
        "severity": "MEDIUM",
        "note": None,
        "status": "OPEN",
        "sanction": "NONE",
        "attempt_status_at_open": "DRAFT",
        "opened_by_user_id": "SYSTEM",
        "resolved_by_user_id": None,
        "resolved_at_utc": None,
        "auto_raised": True,
    })
    db.cases[case["id"]] = case
    touch(attempt)
    return object_response(serialize.attempt(attempt))


# ------------------------------------------------------------------- scoring

def _read_dimension_scores(body):
    raw = body.get("dimension_scores", None)
    if raw is None:
        raise bad_request("Field 'dimension_scores' is required.")
    if not isinstance(raw, list) or not raw:
        raise bad_request("Field 'dimension_scores' must be a non-empty array.")
    parsed = []
    for element in raw:
        if not isinstance(element, dict):
            raise bad_request(
                "Each dimension_scores element must be an object.")
        code = shape.req_str(element, "code")
        score = shape.req_number(element, "score", 2)
        parsed.append({"code": code, "score": score})
    codes = [item["code"] for item in parsed]
    if len(set(codes)) != len(codes):
        raise bad_request("Duplicate dimension code in 'dimension_scores'.")
    return parsed


@bp.route("/assessment-attempts/<aid>/scores", methods=["POST"])
def record_score(aid):
    caller = require(ROLE_EVALUATOR)
    attempt = lookup.attempt(aid)
    body = json_body()
    check_evaluator_ownership(caller, shape.raw_id(body, "evaluator_id"))
    evaluator = lookup.evaluator(shape.req_id(body, "evaluator_id"))
    dimension_scores = _read_dimension_scores(body)
    narrative = shape.opt_str(body, "narrative")
    if attempt["status"] == "VOIDED":
        raise ApiError("ERR_ATTEMPT_VOIDED")
    if attempt["status"] not in ("UNDER_REVIEW", "ADJUDICATION"):
        raise ApiError("ERR_ATTEMPT_NOT_UNDER_REVIEW")
    if derive.attempt_has_live_case(attempt["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD_ACTIVE")
    blueprint = db.blueprints.get(attempt["blueprint_id"])
    if blueprint is None:
        raise ApiError("ERR_BLUEPRINT_NOT_FOUND")
    program = lookup.program_of_attempt(attempt)
    live_scores = [s for s in lookup.scores_of(attempt["id"])
                   if s["status"] == "SUBMITTED"]
    # rule 19: segregation of duties
    if evaluator["mentor_id"] is not None:
        assignment = derive.active_assignment(attempt["student_id"])
        if (assignment is not None
                and assignment["mentor_id"] == evaluator["mentor_id"]):
            raise ApiError("ERR_EVALUATOR_CONFLICT_OF_INTEREST")
        for existing in live_scores:
            peer = db.evaluators.get(existing["evaluator_id"])
            if peer is not None and peer["mentor_id"] == evaluator["mentor_id"]:
                raise ApiError("ERR_EVALUATOR_CONFLICT_OF_INTEREST")
    # rule 20: one score per evaluator, and no more readers than required
    for existing in live_scores:
        if existing["evaluator_id"] == evaluator["id"]:
            raise ApiError("ERR_DUPLICATE_EVALUATOR_SCORE")
    if attempt["status"] == "ADJUDICATION":
        ordinal = 3
        if any(s["reader_ordinal"] == 3 for s in live_scores):
            raise ApiError("ERR_DUPLICATE_EVALUATOR_SCORE")
    else:
        if len(live_scores) >= blueprint["required_evaluator_count"]:
            raise ApiError("ERR_DUPLICATE_EVALUATOR_SCORE")
        ordinal = len(live_scores) + 1
    # rule 21: evaluator standing
    if evaluator["status"] == "SUSPENDED":
        raise ApiError("ERR_EVALUATOR_NOT_CERTIFIED")
    if ordinal == 3 and evaluator["status"] != "CERTIFIED":
        raise ApiError("ERR_EVALUATOR_NOT_CERTIFIED")
    # rule 23: the submitted code set must equal the rubric's exactly
    submitted_codes = set(item["code"] for item in dimension_scores)
    rubric_codes = set(d["code"] for d in blueprint["dimensions"])
    if submitted_codes != rubric_codes:
        raise ApiError("ERR_RUBRIC_DIMENSION_MISMATCH")
    raw_by_code = {}
    for item in dimension_scores:
        for dimension in blueprint["dimensions"]:
            if dimension["code"] != item["code"]:
                continue
            if item["score"] < ZERO or item["score"] > dec(dimension["max_score"]):
                raise bad_request(
                    "Dimension score for '%s' is outside 0..max_score."
                    % item["code"])
        raw_by_code[item["code"]] = item["score"]
    row = new_row()
    row.update({
        "attempt_id": attempt["id"],
        "evaluator_id": evaluator["id"],
        "dimension_scores": dimension_scores,
        "narrative": narrative,
        "weighted_score_pct": calc.weighted_rubric_score(blueprint,
                                                         raw_by_code),
        "critical_fail": calc.critical_fail_flag(blueprint, program,
                                                raw_by_code),
        "reader_ordinal": ordinal,
        "is_adjudication": ordinal == 3,
        "submitted_at_utc": db.now(),
        "status": "SUBMITTED",
        "voided_reason": None,
    })
    db.scores[row["id"]] = row
    mastered = calc.resolve_after_score(attempt, blueprint, program)
    touch(attempt)
    if blueprint["required_evaluator_count"] == 2 and ordinal in (1, 2):
        calc.refresh_pair_standing(attempt, program)
    if mastered:
        cascade.after_mastery(attempt)
    return created_response(serialize.score(row))


@bp.route("/assessment-attempts/<aid>/request-revision", methods=["POST"])
def request_revision(aid):
    require(ROLE_EVALUATOR, ROLE_REGISTRAR)
    attempt = lookup.attempt(aid)
    body = json_body()
    shape.req_str(body, "reason")
    if attempt["status"] == "VOIDED":
        raise ApiError("ERR_ATTEMPT_VOIDED")
    if attempt["status"] not in ("UNDER_REVIEW", "ADJUDICATION"):
        raise ApiError("ERR_ATTEMPT_NOT_UNDER_REVIEW")
    if derive.attempt_has_live_case(attempt["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD_ACTIVE")
    program = lookup.program_of_attempt(attempt)
    affected = [db.evaluators.get(s["evaluator_id"])
                for s in lookup.scores_of(attempt["id"])
                if s["status"] == "SUBMITTED"]
    attempt["status"] = "REVISION_REQUESTED"
    attempt["final_score_pct"] = None
    attempt["score_variant"] = None
    attempt["is_provisional_score"] = False
    attempt["critical_fail"] = False
    attempt["revision_count"] = attempt["revision_count"] + 1
    touch(attempt)
    cascade.void_scores(attempt, "REVISION_REQUESTED")
    for evaluator in affected:
        calc.check_demotion(evaluator, program)
    return object_response(serialize.attempt(attempt))


# --------------------------------------------------------- evaluator scores

@bp.route("/evaluator-scores/<sid>", methods=["GET"])
def read_score(sid):
    require(*SCORE_READ_ROLES)
    return object_response(serialize.score(lookup.score(sid)))


@bp.route("/evaluator-scores", methods=["GET"])
def list_scores():
    require(*SCORE_READ_ROLES)
    attempt_id = _arg("attempt_id")
    evaluator_id = _arg("evaluator_id")
    status = _arg("status")
    rows = []
    for row in db.scores.values():
        if attempt_id is not None and row["attempt_id"] != attempt_id:
            continue
        if evaluator_id is not None and row["evaluator_id"] != evaluator_id:
            continue
        if status is not None and row["status"] != status:
            continue
        rows.append(row)
    ordered = store.sort_rows(rows, [(lambda r: r["reader_ordinal"], False)])
    return paginated(ordered, serialize.score)
