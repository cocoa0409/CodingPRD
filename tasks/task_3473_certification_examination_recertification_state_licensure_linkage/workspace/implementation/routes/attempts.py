"""Cognitive exam attempts (PRD §3.4): scheduling gates (ATT, retake wait,
half-open slot occupation) and CAT response delivery / scoring."""

from flask import Blueprint, request

from db import (MAX_ITEMS, RETAKE_WAIT_DAYS, STORE, attempts_consumed,
                base_entity, now_dt, serialize, touch)
from envelope import ok_list, ok_object, list_page
from errors import raise_err
from middleware import (ALL_AUTHENTICATED_ROLES, authn, body, req_list,
                        req_str)
from services.scoring import score_attempt
from util import add_days, parse_datetime

bp = Blueprint("attempts", __name__)


@bp.post("/registry/cognitive-exam-attempts")
def schedule_attempt():
    uid, _ = authn(["Candidate"])
    b = body()
    att_id = req_str(b, "att_id")
    start = parse_datetime(b.get("scheduled_start"))
    end = parse_datetime(b.get("scheduled_end"))
    if start is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'scheduled_start' is required and must be an ISO-8601 timestamp")
    if end is None:
        raise_err("ERR_INVALID_REQUEST", "Field 'scheduled_end' is required and must be an ISO-8601 timestamp")
    if not end > start:
        raise_err("ERR_INVALID_REQUEST", "scheduled_end must be strictly after scheduled_start")

    att = STORE.atts.get(att_id)
    if not att:
        raise_err("ERR_NOT_FOUND", "AuthorizationToTest %s does not exist" % att_id)
    if att["candidate_id"] != uid:
        raise_err("ERR_FORBIDDEN_ROLE", "Only the ATT's candidate may schedule against it")

    now = now_dt()
    if att["status"] != "ISSUED" or now > att["expires_on"] or att.get("attempt_id"):
        raise_err("ERR_ATT_NOT_ISSUABLE",
                  "ATT is not ISSUED, is past expires_on, or already has an attempt")

    app = STORE.exam_apps.get(att["exam_application_id"])
    basis_id = app["completion_record_id"]
    consumed = attempts_consumed(basis_id)
    if consumed >= 1:
        scored = [a for a in STORE.attempts.values()
                  if a["basis_completion_record_id"] == basis_id
                  and a["status"] in ("SCORED_PASS", "SCORED_FAIL")]
        last_delivered = max(a["delivered_at"] for a in scored)
        if start < add_days(last_delivered, RETAKE_WAIT_DAYS):
            raise_err("ERR_RETAKE_WAIT_ACTIVE",
                      "scheduled_start must be at least %d days after the last scored attempt"
                      % RETAKE_WAIT_DAYS)

    for other in STORE.attempts.values():
        if other["candidate_id"] == uid and other["status"] == "SCHEDULED":
            # Half-open intersection: [s1,e1) vs [s2,e2); touching endpoints ok.
            if other["scheduled_start"] < end and start < other["scheduled_end"]:
                raise_err("ERR_ATTEMPT_SLOT_OVERLAP",
                          "Window conflicts with existing SCHEDULED attempt %s" % other["id"])

    e = base_entity()
    e.update({
        "att_id": att_id,
        "candidate_id": uid,
        "level_id": app["level_id"],
        "basis_completion_record_id": basis_id,
        "attempt_number": consumed + 1,
        "scheduled_start": start,
        "scheduled_end": end,
        "delivered_at": None,
        "responses": [],
        "items_delivered_count": None,
        "provisional_outcome": None,
        "final_outcome": None,
        "theta_final": None,
        "status": "SCHEDULED",
        "voided_by_case_id": None,
    })
    STORE.attempts[e["id"]] = e
    att["attempt_id"] = e["id"]
    touch(att)
    return ok_object(serialize(e), 201)


@bp.get("/registry/cognitive-exam-attempts")
def list_attempts():
    authn(ALL_AUTHENTICATED_ROLES)
    candidate_id = request.args.get("candidate_id")
    att_id = request.args.get("att_id")
    level_id = request.args.get("level_id")
    basis_id = request.args.get("basis_completion_record_id")
    status = request.args.get("status")
    voided_by = request.args.get("voided_by_case_id")
    items = []
    for a in STORE.attempts.values():
        if candidate_id is not None and a["candidate_id"] != candidate_id:
            continue
        if att_id is not None and a["att_id"] != att_id:
            continue
        if level_id is not None and a["level_id"] != level_id:
            continue
        if basis_id is not None and a["basis_completion_record_id"] != basis_id:
            continue
        if status is not None and a["status"] != status:
            continue
        if voided_by is not None and a.get("voided_by_case_id") != voided_by:
            continue
        items.append(a)
    page, total, limit, offset = list_page(items)
    return ok_list([serialize(a) for a in page], total, limit, offset)


@bp.get("/registry/cognitive-exam-attempts/<aid>")
def get_attempt(aid):
    authn(ALL_AUTHENTICATED_ROLES)
    a = STORE.attempts.get(aid)
    if not a:
        raise_err("ERR_NOT_FOUND", "CognitiveExamAttempt %s does not exist" % aid)
    return ok_object(serialize(a), 200)


@bp.post("/registry/cognitive-exam-attempts/<aid>/responses")
def deliver_responses(aid):
    authn(["ExamProctor"])
    b = body()
    responses = req_list(b, "responses")
    if len(responses) > MAX_ITEMS:
        raise_err("ERR_INVALID_REQUEST",
                  "responses may carry at most %d entries" % MAX_ITEMS)
    for i, r in enumerate(responses):
        if not isinstance(r, dict):
            raise_err("ERR_INVALID_REQUEST", "responses[%d] must be an object" % i)
        if not isinstance(r.get("item_id"), str) or not r.get("item_id"):
            raise_err("ERR_INVALID_REQUEST", "responses[%d].item_id is required" % i)
        d = r.get("difficulty_b")
        if isinstance(d, bool) or not isinstance(d, (int, float)) or not (0.1 <= float(d) <= 1.0):
            raise_err("ERR_INVALID_REQUEST", "responses[%d].difficulty_b must be between 0.1 and 1.0" % i)
        if not isinstance(r.get("correct"), bool):
            raise_err("ERR_INVALID_REQUEST", "responses[%d].correct must be a boolean" % i)
    attempt = STORE.attempts.get(aid)
    if not attempt:
        raise_err("ERR_NOT_FOUND", "CognitiveExamAttempt %s does not exist" % aid)

    if attempt["status"] != "SCHEDULED":
        raise_err("ERR_ATTEMPT_NOT_SCHEDULED",
                  "Attempt is %s, not SCHEDULED" % attempt["status"])
    now = now_dt()
    if not (attempt["scheduled_start"] <= now <= attempt["scheduled_end"]):
        raise_err("ERR_DELIVERY_WINDOW_NOT_OPEN",
                  "Current time is outside the delivery window")

    level = STORE.levels.get(attempt["level_id"])
    cut = float(level["cognitive_cut_score"]) if level else 0.0
    provisional, final, theta_final, items_delivered = score_attempt(responses, cut)

    attempt["responses"] = responses
    attempt["provisional_outcome"] = provisional
    attempt["final_outcome"] = final
    attempt["theta_final"] = theta_final
    attempt["items_delivered_count"] = items_delivered
    attempt["delivered_at"] = now
    attempt["status"] = "SCORED_PASS" if final == "PASS" else "SCORED_FAIL"
    touch(attempt)

    att = STORE.atts.get(attempt["att_id"])
    if att and att["status"] == "ISSUED":
        att["status"] = "CONSUMED"
        touch(att)
    return ok_object(serialize(attempt), 200)
