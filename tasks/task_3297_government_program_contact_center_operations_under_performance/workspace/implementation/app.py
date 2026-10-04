import os
from datetime import datetime, timedelta, timezone

from flask import Flask, request

import auto_transitions
import calculations as calc
import db
import invoice_logic
import routing
from clock import iso_now, isoformat, now, parse_iso, set_clock
from errors import ApiError
from models import (make_agent, make_call, make_certification,
                    make_coaching_plan, make_contract, make_course_completion,
                    make_cure_period, make_incident, make_invoice,
                    make_knowledge_article, make_quality_review, make_queue,
                    make_service_level, make_surge_window, make_training_course,
                    touch)
from response import (current_actor, error_response, get_body, require_role,
                      sort_created, success_list, success_object)

app = Flask(__name__)


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Not found", 404))


@app.errorhandler(405)
def handle_405(err):
    return error_response(ApiError("ERR_INVALID_REQUEST", "Method not allowed", 405))


# ---------------- Clock ----------------

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock_endpoint():
    user_id, role = require_role("PlatformAdmin")
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is required", 400)
    try:
        target = parse_iso(to_iso)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "to_iso8601 is not a valid ISO8601 timestamp", 400)
    set_clock(target)
    auto_transitions.fire_auto_transitions()
    return success_object({"current_utc": isoformat(target)})


# ---------------- Contracts ----------------

@app.route("/contracts", methods=["POST"])
def create_contract():
    user_id, _ = require_role("PlatformAdmin")
    body = get_body()
    agency_name = body.get("agency_name")
    measurement_tz = body.get("measurement_tz")
    cap_absolutes = body.get("cap_absolutes")
    if not isinstance(agency_name, str) or not agency_name:
        raise ApiError("ERR_INVALID_REQUEST", "agency_name is required", 400)
    if not isinstance(measurement_tz, str) or not measurement_tz:
        raise ApiError("ERR_INVALID_REQUEST", "measurement_tz is required", 400)
    if not isinstance(cap_absolutes, bool):
        raise ApiError("ERR_INVALID_REQUEST", "cap_absolutes is required and must be boolean", 400)
    rec = make_contract({"agency_name": agency_name, "measurement_tz": measurement_tz,
                         "cap_absolutes": cap_absolutes})
    db.contracts[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/contracts", methods=["GET"])
def list_contracts():
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst", "QualityAnalyst",
                 "Supervisor", "KnowledgeManager", "SecurityOfficer", "Agent")
    items = list(db.contracts.values())
    status = request.args.get("status")
    if status:
        items = [c for c in items if c["status"] == status]
    return success_list(sort_created(items))


@app.route("/contracts/<cid>", methods=["GET"])
def get_contract(cid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst", "QualityAnalyst",
                 "Supervisor", "KnowledgeManager", "SecurityOfficer", "Agent")
    rec = db.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    return success_object(rec)


@app.route("/contracts/<cid>/transition", methods=["POST"])
def contract_transition(cid):
    user_id, _ = require_role("OpsManager")
    rec = db.contracts.get(cid)
    if rec is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if not isinstance(to_status, str):
        raise ApiError("ERR_INVALID_REQUEST", "to_status is required", 400)
    if to_status == "ACTIVE":
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Cannot activate from current state", 409)
        has_effective = any(sl for sl in db.service_levels.values()
                            if sl["contract_id"] == cid and sl["status"] == "EFFECTIVE")
        if not has_effective:
            raise ApiError("ERR_INVALID_STATE", "Contract has no EFFECTIVE service level", 409)
        rec["status"] = "ACTIVE"
        touch(rec)
        return success_object(rec)
    if to_status == "CLOSED":
        if rec["status"] == "DRAFT":
            rec["status"] = "CLOSED"
            touch(rec)
            return success_object(rec)
        if rec["status"] == "ACTIVE":
            for q in db.queues.values():
                if q["contract_id"] == cid and q["status"] == "OPEN":
                    raise ApiError("ERR_INVALID_STATE", "Contract has OPEN queues", 409)
            for inv in db.invoices.values():
                if inv["contract_id"] == cid and inv["status"] in ("DRAFT", "SUBMITTED", "APPROVED"):
                    raise ApiError("ERR_INVALID_STATE", "Contract has open invoices", 409)
            for inc in db.incidents.values():
                if inc["contract_id"] == cid and inc["status"] in ("OPEN", "CONTAINED", "RESOLVED"):
                    raise ApiError("ERR_INVALID_STATE", "Contract has open incidents", 409)
            rec["status"] = "CLOSED"
            touch(rec)
            return success_object(rec)
        raise ApiError("ERR_INVALID_STATE", "Cannot close from current state", 409)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Service Levels ----------------

@app.route("/service-levels", methods=["POST"])
def create_service_level():
    user_id, _ = require_role("OpsManager")
    body = get_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "contract_id is required", 400)
    if contract_id not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    program_code = body.get("program_code")
    metric = body.get("metric")
    target = body.get("target")
    cap_pct = body.get("cap_pct_of_gross")
    remedy = body.get("remedy_fee_cents")
    eff = body.get("effective_from")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_INVALID_REQUEST", "program_code is required", 400)
    if metric not in ("ASA", "ABANDON", "QA_AVG"):
        raise ApiError("ERR_INVALID_REQUEST", "metric must be ASA, ABANDON, or QA_AVG", 400)
    if not isinstance(target, (int, float)) or isinstance(target, bool):
        raise ApiError("ERR_INVALID_REQUEST", "target must be numeric", 400)
    if not isinstance(cap_pct, (int, float)) or isinstance(cap_pct, bool):
        raise ApiError("ERR_INVALID_REQUEST", "cap_pct_of_gross must be numeric", 400)
    if not isinstance(remedy, int) or isinstance(remedy, bool):
        raise ApiError("ERR_INVALID_REQUEST", "remedy_fee_cents must be integer", 400)
    if not isinstance(eff, str):
        raise ApiError("ERR_INVALID_REQUEST", "effective_from is required", 400)
    try:
        parse_iso(eff)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "effective_from is not a valid ISO8601 timestamp", 400)
    rec = make_service_level({"contract_id": contract_id, "program_code": program_code,
                              "metric": metric, "target": target, "cap_pct_of_gross": cap_pct,
                              "remedy_fee_cents": remedy, "effective_from": eff})
    db.service_levels[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/service-levels", methods=["GET"])
def list_service_levels():
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    items = list(db.service_levels.values())
    for f in ("contract_id", "program_code", "metric", "status"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/service-levels/<sid>", methods=["GET"])
def get_service_level(sid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    rec = db.service_levels.get(sid)
    if rec is None:
        raise ApiError("ERR_SERVICE_LEVEL_NOT_FOUND", "Service level not found", 404)
    return success_object(rec)


@app.route("/service-levels/<sid>/transition", methods=["POST"])
def service_level_transition(sid):
    user_id, _ = require_role("OpsManager")
    rec = db.service_levels.get(sid)
    if rec is None:
        raise ApiError("ERR_SERVICE_LEVEL_NOT_FOUND", "Service level not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if not isinstance(to_status, str):
        raise ApiError("ERR_INVALID_REQUEST", "to_status is required", 400)
    contract = db.contracts.get(rec["contract_id"])
    if to_status == "EFFECTIVE":
        # OCC check (priority 5) before state legality per PRD validation order.
        expected = body.get("expected_contract_version")
        if expected is None:
            raise ApiError("ERR_INVALID_REQUEST", "expected_contract_version is required", 400)
        if not isinstance(expected, int):
            raise ApiError("ERR_INVALID_REQUEST", "expected_contract_version must be integer", 400)
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
        if int(expected) != int(contract["version"]):
            raise ApiError("ERR_STALE_VERSION", "Stale contract version", 412)
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Cannot activate from current state", 409)
        if contract["status"] != "ACTIVE":
            # Bootstrap resolution: a first service level can never activate
            # against a DRAFT parent unless the parent activates first, and the
            # parent cannot activate without an EFFECTIVE service level. Break
            # the cycle by activating the DRAFT parent in the same write; a
            # non-DRAFT, non-ACTIVE parent (CLOSED) remains a hard error.
            if contract["status"] != "DRAFT":
                raise ApiError("ERR_INVALID_STATE", "Parent contract not ACTIVE", 409)
            # Activate the DRAFT parent in the same write.
            contract["status"] = "ACTIVE"
            touch(contract)
        if parse_iso(rec["effective_from"]) > now():
            raise ApiError("ERR_INVALID_STATE", "effective_from is in the future", 409)
        # Conflict: existing EFFECTIVE sibling with equal effective_from
        for sl in db.service_levels.values():
            if sl["id"] == rec["id"]:
                continue
            if sl["contract_id"] != rec["contract_id"]:
                continue
            if sl["program_code"] != rec["program_code"] or sl["metric"] != rec["metric"]:
                continue
            if sl["status"] == "EFFECTIVE" and sl["effective_from"] == rec["effective_from"]:
                raise ApiError("ERR_SL_CONFLICT", "Effective service level conflict", 409)
        # Supersede earlier EFFECTIVE siblings
        for sl in db.service_levels.values():
            if sl["id"] == rec["id"]:
                continue
            if sl["contract_id"] != rec["contract_id"]:
                continue
            if sl["program_code"] != rec["program_code"] or sl["metric"] != rec["metric"]:
                continue
            if sl["status"] == "EFFECTIVE" and parse_iso(sl["effective_from"]) < parse_iso(rec["effective_from"]):
                sl["status"] = "SUPERSEDED"
                touch(sl)
        rec["status"] = "EFFECTIVE"
        touch(rec)
        touch(contract)
        return success_object(rec)
    if to_status == "ARCHIVED":
        if rec["status"] == "EFFECTIVE":
            for line in db.invoice_lines.values():
                if line["service_level_id"] == sid:
                    inv = db.invoices.get(line["invoice_id"])
                    if inv is not None and inv["status"] in ("DRAFT", "SUBMITTED"):
                        raise ApiError("ERR_INVALID_STATE", "Service level referenced by open invoice", 409)
            rec["status"] = "ARCHIVED"
            touch(rec)
            return success_object(rec)
        if rec["status"] == "SUPERSEDED":
            rec["status"] = "ARCHIVED"
            touch(rec)
            return success_object(rec)
        raise ApiError("ERR_INVALID_STATE", "Cannot archive from current state", 409)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Agents ----------------

@app.route("/agents", methods=["POST"])
def create_agent():
    user_id, _ = require_role("OpsManager")
    body = get_body()
    full_name = body.get("full_name")
    languages = body.get("languages")
    if not isinstance(full_name, str) or not full_name:
        raise ApiError("ERR_INVALID_REQUEST", "full_name is required", 400)
    if not isinstance(languages, list) or not all(isinstance(x, str) for x in languages):
        raise ApiError("ERR_INVALID_REQUEST", "languages must be a list of strings", 400)
    rec = make_agent({"full_name": full_name, "languages": languages})
    db.agents[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/agents", methods=["GET"])
def list_agents():
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "QualityAnalyst")
    items = list(db.agents.values())
    es = request.args.get("employment_status")
    if es:
        items = [a for a in items if a["employment_status"] == es]
    return success_list(sort_created(items))


@app.route("/agents/<aid>", methods=["GET"])
def get_agent(aid):
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "QualityAnalyst")
    rec = db.agents.get(aid)
    if rec is None:
        raise ApiError("ERR_AGENT_NOT_FOUND", "Agent not found", 404)
    return success_object(rec)


@app.route("/agents/<aid>/transition", methods=["POST"])
def agent_transition(aid):
    user_id, _ = require_role("OpsManager")
    rec = db.agents.get(aid)
    if rec is None:
        raise ApiError("ERR_AGENT_NOT_FOUND", "Agent not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "INACTIVE":
        if rec["employment_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Cannot deactivate from current state", 409)
        for c in db.calls.values():
            if c.get("agent_id") == aid and c["status"] in ("ASSIGNED", "ANSWERED"):
                raise ApiError("ERR_AGENT_HAS_LIVE_CALLS", "Agent has live calls", 409)
        rec["employment_status"] = "INACTIVE"
        touch(rec)
        return success_object(rec)
    if to_status == "ACTIVE":
        if rec["employment_status"] != "INACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Cannot reactivate from current state", 409)
        n = now()
        has_standing = any(
            cert["agent_id"] == aid and calc.cert_standing_at(cert, n)
            for cert in db.certifications.values()
        )
        if not has_standing:
            raise ApiError("ERR_INVALID_STATE", "Agent holds no standing certification", 409)
        rec["employment_status"] = "ACTIVE"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Training Courses / Certifications ----------------

@app.route("/training-courses", methods=["POST"])
def create_training_course():
    user_id, _ = require_role("KnowledgeManager")
    body = get_body()
    program_code = body.get("program_code")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_INVALID_REQUEST", "program_code is required", 400)
    article_id = body.get("knowledge_article_id")
    if article_id is not None:
        if not isinstance(article_id, str):
            raise ApiError("ERR_INVALID_REQUEST", "knowledge_article_id must be a string", 400)
        if article_id not in db.knowledge_articles:
            raise ApiError("ERR_ARTICLE_NOT_FOUND", "Knowledge article not found", 404)
    required = body.get("required", True)
    if not isinstance(required, bool):
        raise ApiError("ERR_INVALID_REQUEST", "required must be boolean", 400)
    rec = make_training_course({"program_code": program_code,
                                "knowledge_article_id": article_id,
                                "required": required})
    db.training_courses[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/training-courses/<tid>", methods=["GET"])
def get_training_course(tid):
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor")
    rec = db.training_courses.get(tid)
    if rec is None:
        raise ApiError("ERR_TRAINING_COURSE_NOT_FOUND", "Training course not found", 404)
    return success_object(rec)


@app.route("/training-courses/<tid>/complete", methods=["POST"])
def complete_training_course(tid):
    user_id, _ = require_role("KnowledgeManager")
    course = db.training_courses.get(tid)
    if course is None:
        raise ApiError("ERR_TRAINING_COURSE_NOT_FOUND", "Training course not found", 404)
    body = get_body()
    agent_id = body.get("agent_id")
    if not isinstance(agent_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "agent_id is required", 400)
    if agent_id not in db.agents:
        raise ApiError("ERR_AGENT_NOT_FOUND", "Agent not found", 404)
    valid_until = body.get("valid_until")
    if not isinstance(valid_until, str):
        raise ApiError("ERR_INVALID_REQUEST", "valid_until is required", 400)
    try:
        vu = parse_iso(valid_until)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "valid_until is not a valid ISO8601 timestamp", 400)
    if vu <= now():
        raise ApiError("ERR_INVALID_REQUEST", "valid_until must be in the future", 400)
    completed_at = iso_now()
    completion = make_course_completion(tid, agent_id, completed_at)
    db.course_completions[completion["id"]] = completion
    cert = make_certification(agent_id, course["program_code"], tid, valid_until)
    db.certifications[cert["id"]] = cert
    # Re-validation cascade
    article_id = course.get("knowledge_article_id")
    if article_id:
        for c in db.certifications.values():
            if c["agent_id"] != agent_id:
                continue
            if c["program_code"] != course["program_code"]:
                continue
            if c.get("invalidated_by_article_id") == article_id:
                c["invalidated_at"] = None
                c["invalidated_by_article_id"] = None
    return success_object(completion, 200)


@app.route("/certifications", methods=["GET"])
def list_certifications():
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor")
    items = list(db.certifications.values())
    for f in ("agent_id", "program_code", "training_course_id", "invalidated_by_article_id"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/certifications/<cid>", methods=["GET"])
def get_certification(cid):
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor")
    rec = db.certifications.get(cid)
    if rec is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "Certification not found", 404)
    return success_object(rec)


@app.route("/course-completions", methods=["GET"])
def list_course_completions():
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor")
    items = list(db.course_completions.values())
    for f in ("training_course_id", "agent_id"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/course-completions/<cid>", methods=["GET"])
def get_course_completion(cid):
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor")
    rec = db.course_completions.get(cid)
    if rec is None:
        raise ApiError("ERR_CERTIFICATION_NOT_FOUND", "Course completion not found", 404)
    return success_object(rec)


# ---------------- Queues ----------------

def _validate_overflow_target(queue_rec, overflow_id):
    """Validate that overflow_id is a legitimate target for queue_rec (which may be a new dict or an existing queue)."""
    if overflow_id is None:
        return
    if not isinstance(overflow_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "overflow_queue_id must be a string", 400)
    target = db.queues.get(overflow_id)
    if target is None:
        raise ApiError("ERR_QUEUE_NOT_FOUND", "Overflow queue not found", 404)
    if target["contract_id"] != queue_rec["contract_id"]:
        raise ApiError("ERR_QUEUE_OVERFLOW_MISMATCH", "Overflow target contract mismatch", 409)
    if target["language_code"] != queue_rec["language_code"]:
        raise ApiError("ERR_QUEUE_OVERFLOW_MISMATCH", "Overflow target language mismatch", 409)
    if queue_rec["queue_type"] == "SPECIALTY":
        if target.get("specialty_tag") != queue_rec.get("specialty_tag"):
            raise ApiError("ERR_QUEUE_OVERFLOW_MISMATCH", "Overflow target specialty mismatch", 409)


@app.route("/queues", methods=["POST"])
def create_queue():
    user_id, _ = require_role("OpsManager")
    body = get_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "contract_id is required", 400)
    if contract_id not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    program_code = body.get("program_code")
    language_code = body.get("language_code")
    queue_type = body.get("queue_type")
    specialty_tag = body.get("specialty_tag")
    overflow_queue_id = body.get("overflow_queue_id")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_INVALID_REQUEST", "program_code is required", 400)
    if not isinstance(language_code, str) or not language_code:
        raise ApiError("ERR_INVALID_REQUEST", "language_code is required", 400)
    if queue_type not in ("GENERAL", "SPECIALTY"):
        raise ApiError("ERR_INVALID_REQUEST", "queue_type must be GENERAL or SPECIALTY", 400)
    if queue_type == "GENERAL":
        if specialty_tag is not None:
            raise ApiError("ERR_INVALID_REQUEST", "specialty_tag must be null for GENERAL queues", 400)
    else:
        if not isinstance(specialty_tag, str) or not specialty_tag:
            raise ApiError("ERR_INVALID_REQUEST", "specialty_tag is required for SPECIALTY queues", 400)
    rec = make_queue({"contract_id": contract_id, "program_code": program_code,
                      "language_code": language_code, "queue_type": queue_type,
                      "specialty_tag": specialty_tag, "overflow_queue_id": overflow_queue_id})
    _validate_overflow_target(rec, overflow_queue_id)
    db.queues[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/queues", methods=["GET"])
def list_queues():
    require_role("PlatformAdmin", "OpsManager", "Supervisor")
    items = list(db.queues.values())
    for f in ("contract_id", "program_code", "status", "overflow_queue_id"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/queues/<qid>", methods=["GET"])
def get_queue(qid):
    require_role("PlatformAdmin", "OpsManager", "Supervisor")
    rec = db.queues.get(qid)
    if rec is None:
        raise ApiError("ERR_QUEUE_NOT_FOUND", "Queue not found", 404)
    return success_object(rec)


@app.route("/queues/<qid>", methods=["PATCH"])
def patch_queue(qid):
    user_id, _ = require_role("OpsManager")
    rec = db.queues.get(qid)
    if rec is None:
        raise ApiError("ERR_QUEUE_NOT_FOUND", "Queue not found", 404)
    body = get_body()
    if "overflow_queue_id" not in body:
        raise ApiError("ERR_INVALID_REQUEST", "overflow_queue_id is required", 400)
    new_val = body.get("overflow_queue_id")
    if new_val is None:
        has_assigned = any(c.get("queue_id") == qid for c in db.calls.values())
        if has_assigned:
            raise ApiError("ERR_OVERFLOW_LOCKED", "Cannot clear overflow after assignments", 409)
        rec["overflow_queue_id"] = None
    else:
        _validate_overflow_target(rec, new_val)
        rec["overflow_queue_id"] = new_val
    touch(rec)
    return success_object(rec)


@app.route("/queues/<qid>/transition", methods=["POST"])
def queue_transition(qid):
    user_id, _ = require_role("OpsManager")
    rec = db.queues.get(qid)
    if rec is None:
        raise ApiError("ERR_QUEUE_NOT_FOUND", "Queue not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "PAUSED":
        if rec["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Cannot pause from current state", 409)
        rec["status"] = "PAUSED"
        touch(rec)
        return success_object(rec)
    if to_status == "OPEN":
        if rec["status"] != "PAUSED":
            raise ApiError("ERR_INVALID_STATE", "Cannot resume from current state", 409)
        rec["status"] = "OPEN"
        touch(rec)
        return success_object(rec)
    if to_status == "CLOSED":
        if rec["status"] not in ("OPEN", "PAUSED"):
            raise ApiError("ERR_INVALID_STATE", "Cannot close from current state", 409)
        for c in db.calls.values():
            if c.get("queue_id") == qid and c["status"] in ("WAITING", "ASSIGNED", "ANSWERED"):
                raise ApiError("ERR_QUEUE_NOT_EMPTY", "Queue has live calls", 409)
        rec["status"] = "CLOSED"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


@app.route("/queues/<qid>/calls", methods=["GET"])
def list_queue_calls(qid):
    require_role("PlatformAdmin", "OpsManager", "Supervisor")
    if qid not in db.queues:
        raise ApiError("ERR_QUEUE_NOT_FOUND", "Queue not found", 404)
    items = [c for c in db.calls.values() if c.get("queue_id") == qid]
    st = request.args.get("status")
    if st:
        items = [c for c in items if c["status"] == st]
    return success_list(sort_created(items))


# ---------------- Calls ----------------

@app.route("/calls", methods=["POST"])
def create_call():
    user_id, _ = require_role("Supervisor", "OpsManager")
    body = get_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "contract_id is required", 400)
    if contract_id not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    program_code = body.get("program_code")
    language_code = body.get("language_code")
    enqueued_at = body.get("enqueued_at")
    required_specialty = body.get("required_specialty")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_INVALID_REQUEST", "program_code is required", 400)
    if not isinstance(language_code, str) or not language_code:
        raise ApiError("ERR_INVALID_REQUEST", "language_code is required", 400)
    if not isinstance(enqueued_at, str):
        raise ApiError("ERR_INVALID_REQUEST", "enqueued_at is required", 400)
    try:
        parse_iso(enqueued_at)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "enqueued_at is not a valid ISO8601 timestamp", 400)
    if required_specialty is not None and not isinstance(required_specialty, str):
        raise ApiError("ERR_INVALID_REQUEST", "required_specialty must be a string", 400)
    rec = make_call({"contract_id": contract_id, "program_code": program_code,
                     "language_code": language_code, "required_specialty": required_specialty,
                     "enqueued_at": enqueued_at})
    db.calls[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/calls", methods=["GET"])
def list_calls():
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "QualityAnalyst", "BillingAnalyst")
    items = list(db.calls.values())
    for f in ("contract_id", "program_code", "status", "queue_id", "agent_id", "handled_by_agent_id"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/calls/<cid>", methods=["GET"])
def get_call(cid):
    user_id, role = require_role("PlatformAdmin", "OpsManager", "Supervisor",
                                 "QualityAnalyst", "BillingAnalyst", "Agent")
    rec = db.calls.get(cid)
    if rec is None:
        raise ApiError("ERR_CALL_NOT_FOUND", "Call not found", 404)
    if role == "Agent" and rec.get("agent_id") != user_id:
        raise ApiError("ERR_FORBIDDEN", "Agents may only view their own calls", 403)
    return success_object(rec)


@app.route("/calls/<cid>/transition", methods=["POST"])
def call_transition(cid):
    user_id, role = require_role("Supervisor", "Agent")
    rec = db.calls.get(cid)
    if rec is None:
        raise ApiError("ERR_CALL_NOT_FOUND", "Call not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "ASSIGNED":
        if role != "Supervisor":
            raise ApiError("ERR_FORBIDDEN", "Only Supervisor may route calls", 403)
        if rec["status"] != "WAITING":
            raise ApiError("ERR_INVALID_STATE", "Cannot route from current state", 409)
        contract = db.contracts.get(rec["contract_id"])
        if contract is None or contract["status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE", "Contract is not ACTIVE", 409)
        queue, agent, assigned_via, route_depth = routing.queue_selector(rec)
        rec["queue_id"] = queue["id"]
        rec["agent_id"] = agent["id"]
        rec["assigned_via"] = assigned_via
        rec["route_depth"] = route_depth
        rec["status"] = "ASSIGNED"
        touch(rec)
        return success_object(rec)
    if to_status == "ANSWERED":
        if rec["status"] != "ASSIGNED":
            raise ApiError("ERR_INVALID_STATE", "Cannot answer from current state", 409)
        if role != "Agent":
            raise ApiError("ERR_FORBIDDEN", "Only the assigned Agent may answer", 403)
        if rec.get("agent_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", "Agents may only answer their own calls", 403)
        n = now()
        rec["answered_at"] = iso_now()
        rec["answer_seconds"] = int((n - parse_iso(rec["enqueued_at"])).total_seconds())
        rec["handled_by_agent_id"] = rec["agent_id"]
        rec["status"] = "ANSWERED"
        touch(rec)
        return success_object(rec)
    if to_status == "COMPLETED":
        if rec["status"] != "ANSWERED":
            raise ApiError("ERR_INVALID_STATE", "Cannot complete from current state", 409)
        if role != "Agent":
            raise ApiError("ERR_FORBIDDEN", "Only the assigned Agent may complete", 403)
        if rec.get("agent_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", "Agents may only complete their own calls", 403)
        n = now()
        rec["ended_at"] = iso_now()
        rec["talk_seconds"] = int((n - parse_iso(rec["answered_at"])).total_seconds())
        rec["status"] = "COMPLETED"
        touch(rec)
        return success_object(rec)
    if to_status == "ABANDONED":
        if role != "Supervisor":
            raise ApiError("ERR_FORBIDDEN", "Only Supervisor may abandon calls", 403)
        if rec["status"] not in ("WAITING", "ASSIGNED"):
            raise ApiError("ERR_INVALID_STATE", "Cannot abandon from current state", 409)
        rec["abandoned_at"] = iso_now()
        rec["status"] = "ABANDONED"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Quality Reviews ----------------

AUTO_COACH_THRESHOLD = 70


def _auto_coach_cascade(review):
    """If the review final total is below threshold, create a CoachingPlan when no recent one exists."""
    if review["total_score"] >= AUTO_COACH_THRESHOLD:
        return
    call = db.calls.get(review["call_id"])
    if call is None:
        return
    agent_id = call.get("handled_by_agent_id")
    if not agent_id:
        return
    # Existing OPEN or ESCALATED plan?
    for plan in db.coaching_plans.values():
        if plan["agent_id"] == agent_id and plan["status"] in ("OPEN", "ESCALATED"):
            return
    # AUTO_QUALITY plan created within trailing 7 days?
    n = now()
    cutoff = n - timedelta(days=7)
    for plan in db.coaching_plans.values():
        if plan["agent_id"] != agent_id:
            continue
        if plan["trigger"] != "AUTO_QUALITY":
            continue
        if parse_iso(plan["created_at"]) >= cutoff:
            return
    due = n + timedelta(days=14)
    due_str = due.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due.microsecond // 1000:03d}Z"
    plan = make_coaching_plan(agent_id, "AUTO_QUALITY", due_str)
    db.coaching_plans[plan["id"]] = plan


@app.route("/quality-reviews", methods=["POST"])
def create_quality_review():
    user_id, _ = require_role("QualityAnalyst")
    body = get_body()
    call_id = body.get("call_id")
    if not isinstance(call_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "call_id is required", 400)
    call = db.calls.get(call_id)
    if call is None:
        raise ApiError("ERR_CALL_NOT_FOUND", "Call not found", 404)
    accuracy_score = body.get("accuracy_score")
    compliance_score = body.get("compliance_score")
    accuracy_weight = body.get("accuracy_weight", 0.5)
    if not isinstance(accuracy_score, int) or isinstance(accuracy_score, bool):
        raise ApiError("ERR_INVALID_REQUEST", "accuracy_score must be integer 0-100", 400)
    if not isinstance(compliance_score, int) or isinstance(compliance_score, bool):
        raise ApiError("ERR_INVALID_REQUEST", "compliance_score must be integer 0-100", 400)
    if not (0 <= accuracy_score <= 100) or not (0 <= compliance_score <= 100):
        raise ApiError("ERR_INVALID_REQUEST", "scores must be in [0, 100]", 400)
    if not isinstance(accuracy_weight, (int, float)) or isinstance(accuracy_weight, bool):
        raise ApiError("ERR_INVALID_REQUEST", "accuracy_weight must be numeric", 400)
    if not (0 < float(accuracy_weight) < 1):
        raise ApiError("ERR_INVALID_REQUEST", "accuracy_weight must lie in (0, 1)", 400)
    if call["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Call must be COMPLETED to be reviewed", 409)
    total = calc.quality_total_score(accuracy_weight, accuracy_score, compliance_score)
    rec = make_quality_review({"call_id": call_id, "accuracy_score": accuracy_score,
                               "compliance_score": compliance_score,
                               "accuracy_weight": accuracy_weight}, total)
    db.quality_reviews[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/quality-reviews", methods=["GET"])
def list_quality_reviews():
    require_role("PlatformAdmin", "OpsManager", "QualityAnalyst", "Supervisor")
    items = list(db.quality_reviews.values())
    for f in ("call_id", "status"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/quality-reviews/<rid>", methods=["GET"])
def get_quality_review(rid):
    require_role("PlatformAdmin", "OpsManager", "QualityAnalyst", "Supervisor", "Agent")
    rec = db.quality_reviews.get(rid)
    if rec is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "Quality review not found", 404)
    return success_object(rec)


@app.route("/quality-reviews/<rid>/transition", methods=["POST"])
def quality_review_transition(rid):
    user_id, role = require_role("QualityAnalyst", "Agent")
    rec = db.quality_reviews.get(rid)
    if rec is None:
        raise ApiError("ERR_REVIEW_NOT_FOUND", "Quality review not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "ACCEPTED":
        if role != "QualityAnalyst":
            raise ApiError("ERR_FORBIDDEN", "Only QualityAnalyst may accept", 403)
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Cannot accept from current state", 409)
        rec["status"] = "ACCEPTED"
        rec["final"] = True
        touch(rec)
        _auto_coach_cascade(rec)
        return success_object(rec)
    if to_status == "DISPUTED":
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Cannot dispute from current state", 409)
        if role != "Agent":
            raise ApiError("ERR_FORBIDDEN", "Only the reviewed Agent may dispute", 403)
        call = db.calls.get(rec["call_id"])
        if call is None or call.get("handled_by_agent_id") != user_id:
            raise ApiError("ERR_FORBIDDEN", "Agents may only dispute reviews of their own calls", 403)
        rec["status"] = "DISPUTED"
        touch(rec)
        return success_object(rec)
    if to_status in ("UPHELD", "OVERTURNED"):
        if role != "QualityAnalyst":
            raise ApiError("ERR_FORBIDDEN", "Only QualityAnalyst may resolve disputes", 403)
        if rec["status"] != "DISPUTED":
            raise ApiError("ERR_INVALID_STATE", "Cannot resolve from current state", 409)
        rec["status"] = to_status
        if to_status == "UPHELD":
            rec["final"] = True
            touch(rec)
            _auto_coach_cascade(rec)
        else:
            touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Coaching Plans ----------------

@app.route("/coaching-plans", methods=["POST"])
def create_coaching_plan():
    user_id, _ = require_role("Supervisor")
    body = get_body()
    agent_id = body.get("agent_id")
    due_date = body.get("due_date")
    if not isinstance(agent_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "agent_id is required", 400)
    if agent_id not in db.agents:
        raise ApiError("ERR_AGENT_NOT_FOUND", "Agent not found", 404)
    if not isinstance(due_date, str):
        raise ApiError("ERR_INVALID_REQUEST", "due_date is required", 400)
    try:
        parse_iso(due_date)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "due_date is not a valid ISO8601 timestamp", 400)
    for plan in db.coaching_plans.values():
        if plan["agent_id"] == agent_id and plan["status"] in ("OPEN", "ESCALATED"):
            raise ApiError("ERR_DUPLICATE_PLAN", "Agent already has an open coaching plan", 409)
    rec = make_coaching_plan(agent_id, "MANUAL", due_date)
    db.coaching_plans[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/coaching-plans", methods=["GET"])
def list_coaching_plans():
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "QualityAnalyst")
    items = list(db.coaching_plans.values())
    for f in ("agent_id", "status", "trigger"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/coaching-plans/<pid>", methods=["GET"])
def get_coaching_plan(pid):
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "QualityAnalyst")
    rec = db.coaching_plans.get(pid)
    if rec is None:
        raise ApiError("ERR_COACHING_PLAN_NOT_FOUND", "Coaching plan not found", 404)
    return success_object(rec)


@app.route("/coaching-plans/<pid>/transition", methods=["POST"])
def coaching_plan_transition(pid):
    user_id, _ = require_role("Supervisor")
    rec = db.coaching_plans.get(pid)
    if rec is None:
        raise ApiError("ERR_COACHING_PLAN_NOT_FOUND", "Coaching plan not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "COMPLETED":
        if rec["status"] not in ("OPEN", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE", "Cannot complete from current state", 409)
        rec["status"] = "COMPLETED"
        touch(rec)
        return success_object(rec)
    if to_status == "ESCALATED":
        if rec["status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "Cannot escalate from current state", 409)
        rec["status"] = "ESCALATED"
        touch(rec)
        return success_object(rec)
    if to_status == "CANCELLED":
        if rec["status"] not in ("OPEN", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE", "Cannot cancel from current state", 409)
        rec["status"] = "CANCELLED"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Knowledge Articles ----------------

@app.route("/knowledge-articles", methods=["POST"])
def create_knowledge_article():
    user_id, _ = require_role("KnowledgeManager")
    body = get_body()
    program_code = body.get("program_code")
    title = body.get("title")
    body_text = body.get("body")
    effective_at = body.get("effective_at")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_INVALID_REQUEST", "program_code is required", 400)
    if not isinstance(title, str):
        raise ApiError("ERR_INVALID_REQUEST", "title is required", 400)
    if not isinstance(body_text, str):
        raise ApiError("ERR_INVALID_REQUEST", "body is required", 400)
    if not isinstance(effective_at, str):
        raise ApiError("ERR_INVALID_REQUEST", "effective_at is required", 400)
    try:
        parse_iso(effective_at)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "effective_at is not a valid ISO8601 timestamp", 400)
    rec = make_knowledge_article({"program_code": program_code, "title": title,
                                  "body": body_text, "effective_at": effective_at})
    db.knowledge_articles[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/knowledge-articles", methods=["GET"])
def list_knowledge_articles():
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor", "Agent")
    items = list(db.knowledge_articles.values())
    for f in ("program_code", "status"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/knowledge-articles/<kid>", methods=["GET"])
def get_knowledge_article(kid):
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager", "Supervisor", "Agent")
    rec = db.knowledge_articles.get(kid)
    if rec is None:
        raise ApiError("ERR_ARTICLE_NOT_FOUND", "Knowledge article not found", 404)
    return success_object(rec)


@app.route("/knowledge-articles/<kid>/transition", methods=["POST"])
def knowledge_article_transition(kid):
    user_id, _ = require_role("KnowledgeManager")
    rec = db.knowledge_articles.get(kid)
    if rec is None:
        raise ApiError("ERR_ARTICLE_NOT_FOUND", "Knowledge article not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "PUBLISHED":
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Cannot publish from current state", 409)
        rec["status"] = "PUBLISHED"
        touch(rec)
        # Retraining cascade
        article_eff = parse_iso(rec["effective_at"])
        for cert in db.certifications.values():
            if cert["program_code"] != rec["program_code"]:
                continue
            completion = db.course_completions.get(cert["training_course_id"])
            # Find the grounding completion for this cert's training course + agent
            grounding = None
            for cc in db.course_completions.values():
                if cc["training_course_id"] == cert["training_course_id"] and cc["agent_id"] == cert["agent_id"]:
                    grounding = cc
                    break
            if grounding is None:
                continue
            if parse_iso(grounding["completed_at"]) < article_eff:
                cert["invalidated_at"] = iso_now()
                cert["invalidated_by_article_id"] = rec["id"]
        return success_object(rec)
    if to_status == "RETIRED":
        if rec["status"] != "PUBLISHED":
            raise ApiError("ERR_INVALID_STATE", "Cannot retire from current state", 409)
        rec["status"] = "RETIRED"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


@app.route("/knowledge-articles/<kid>/training-courses", methods=["GET"])
def list_article_courses(kid):
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager")
    if kid not in db.knowledge_articles:
        raise ApiError("ERR_ARTICLE_NOT_FOUND", "Knowledge article not found", 404)
    items = [c for c in db.training_courses.values() if c.get("knowledge_article_id") == kid]
    return success_list(sort_created(items))


# ---------------- Surge Windows ----------------

def _auto_transition_window(rec):
    n = now()
    if rec["status"] == "DECLARED" and parse_iso(rec["starts_on"]) <= n:
        rec["status"] = "ACTIVE"
        touch(rec)
    if rec["status"] == "ACTIVE" and parse_iso(rec["ends_on"]) < n:
        rec["status"] = "EXPIRED"
        touch(rec)


def _refresh_surge_windows():
    for w in db.surge_windows.values():
        _auto_transition_window(w)


@app.route("/surge-windows", methods=["POST"])
def create_surge_window():
    user_id, _ = require_role("OpsManager")
    body = get_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "contract_id is required", 400)
    if contract_id not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    program_code = body.get("program_code")
    surge_type = body.get("surge_type")
    starts_on = body.get("starts_on")
    ends_on = body.get("ends_on")
    factor = body.get("expected_volume_factor")
    if not isinstance(program_code, str) or not program_code:
        raise ApiError("ERR_INVALID_REQUEST", "program_code is required", 400)
    if surge_type not in ("ENROLLMENT_PERIOD", "POLICY_CHANGE", "PUBLIC_EVENT"):
        raise ApiError("ERR_INVALID_REQUEST", "surge_type must be a declared value", 400)
    if not isinstance(starts_on, str) or not isinstance(ends_on, str):
        raise ApiError("ERR_INVALID_REQUEST", "starts_on and ends_on are required", 400)
    try:
        s_dt = parse_iso(starts_on)
        e_dt = parse_iso(ends_on)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "starts_on/ends_on are not valid ISO8601 timestamps", 400)
    if e_dt <= s_dt:
        raise ApiError("ERR_INVALID_REQUEST", "ends_on must be strictly after starts_on", 400)
    if not isinstance(factor, (int, float)) or isinstance(factor, bool) or not (float(factor) > 1.0):
        raise ApiError("ERR_INVALID_REQUEST", "expected_volume_factor must be > 1.0", 400)
    # Overlap (adjacency-inclusive) check
    _refresh_surge_windows()
    for w in db.surge_windows.values():
        if w["contract_id"] != contract_id or w["program_code"] != program_code:
            continue
        if w["status"] not in ("DECLARED", "ACTIVE"):
            continue
        ws = parse_iso(w["starts_on"])
        we = parse_iso(w["ends_on"])
        if s_dt <= we and e_dt >= ws:
            raise ApiError("ERR_SURGE_OVERLAP", "Surge window overlaps an existing window", 409)
    initial = "ACTIVE" if now() >= s_dt else "DECLARED"
    rec = make_surge_window({"contract_id": contract_id, "program_code": program_code,
                             "surge_type": surge_type, "starts_on": starts_on,
                             "ends_on": ends_on, "expected_volume_factor": factor}, initial)
    db.surge_windows[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/surge-windows", methods=["GET"])
def list_surge_windows():
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "BillingAnalyst")
    _refresh_surge_windows()
    items = list(db.surge_windows.values())
    for f in ("contract_id", "program_code", "status"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/surge-windows/<wid>", methods=["GET"])
def get_surge_window(wid):
    require_role("PlatformAdmin", "OpsManager", "Supervisor", "BillingAnalyst")
    rec = db.surge_windows.get(wid)
    if rec is None:
        raise ApiError("ERR_SURGE_WINDOW_NOT_FOUND", "Surge window not found", 404)
    _auto_transition_window(rec)
    return success_object(rec)


@app.route("/surge-windows/<wid>/transition", methods=["POST"])
def surge_window_transition(wid):
    user_id, _ = require_role("OpsManager")
    rec = db.surge_windows.get(wid)
    if rec is None:
        raise ApiError("ERR_SURGE_WINDOW_NOT_FOUND", "Surge window not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    if to_status == "CANCELLED":
        if rec["status"] != "DECLARED":
            raise ApiError("ERR_INVALID_STATE", "Cannot cancel from current state", 409)
        if now() >= parse_iso(rec["starts_on"]):
            raise ApiError("ERR_INVALID_STATE", "Cannot cancel an activated window", 409)
        rec["status"] = "CANCELLED"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


@app.route("/contracts/<cid>/surge-windows", methods=["GET"])
def list_contract_surge_windows(cid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    if cid not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    _refresh_surge_windows()
    items = [w for w in db.surge_windows.values() if w["contract_id"] == cid]
    return success_list(sort_created(items))


# ---------------- Incidents ----------------

def _incident_with_sla(rec):
    out = dict(rec)
    if rec["severity"] == "CRITICAL":
        delta = parse_iso(rec["reported_at"]) - parse_iso(rec["occurred_at"])
        hours = delta.total_seconds() / 3600.0
        out["sla_breached"] = bool(hours > 24)
    else:
        out["sla_breached"] = False
    return out


@app.route("/incidents", methods=["POST"])
def create_incident():
    user_id, _ = require_role("SecurityOfficer")
    body = get_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "contract_id is required", 400)
    if contract_id not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    severity = body.get("severity")
    category = body.get("category")
    occurred_at = body.get("occurred_at")
    description = body.get("description")
    if severity not in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        raise ApiError("ERR_INVALID_REQUEST", "severity must be a declared value", 400)
    if category not in ("PRIVACY_BREACH", "SECURITY", "DATA_QUALITY"):
        raise ApiError("ERR_INVALID_REQUEST", "category must be a declared value", 400)
    if not isinstance(occurred_at, str):
        raise ApiError("ERR_INVALID_REQUEST", "occurred_at is required", 400)
    try:
        parse_iso(occurred_at)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "occurred_at is not a valid ISO8601 timestamp", 400)
    if not isinstance(description, str):
        raise ApiError("ERR_INVALID_REQUEST", "description is required", 400)
    rec = make_incident({"contract_id": contract_id, "severity": severity,
                         "category": category, "occurred_at": occurred_at,
                         "description": description}, iso_now())
    db.incidents[rec["id"]] = rec
    return success_object(_incident_with_sla(rec), 201)


@app.route("/incidents", methods=["GET"])
def list_incidents():
    require_role("PlatformAdmin", "OpsManager", "SecurityOfficer")
    items = list(db.incidents.values())
    for f in ("contract_id", "severity", "status"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list([_incident_with_sla(x) for x in sort_created(items)])


@app.route("/incidents/<iid>", methods=["GET"])
def get_incident(iid):
    require_role("PlatformAdmin", "OpsManager", "SecurityOfficer")
    rec = db.incidents.get(iid)
    if rec is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", "Incident not found", 404)
    return success_object(_incident_with_sla(rec))


@app.route("/incidents/<iid>/transition", methods=["POST"])
def incident_transition(iid):
    user_id, _ = require_role("SecurityOfficer")
    rec = db.incidents.get(iid)
    if rec is None:
        raise ApiError("ERR_INCIDENT_NOT_FOUND", "Incident not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    transitions = {
        ("OPEN", "CONTAINED"),
        ("CONTAINED", "RESOLVED"),
        ("RESOLVED", "CLOSED"),
        ("RESOLVED", "OPEN"),
    }
    if (rec["status"], to_status) not in transitions:
        raise ApiError("ERR_INVALID_STATE", "Invalid incident transition", 409)
    rec["status"] = to_status
    touch(rec)
    return success_object(_incident_with_sla(rec))


@app.route("/contracts/<cid>/incidents", methods=["GET"])
def list_contract_incidents(cid):
    require_role("PlatformAdmin", "OpsManager", "SecurityOfficer")
    if cid not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    items = [i for i in db.incidents.values() if i["contract_id"] == cid]
    return success_list([_incident_with_sla(x) for x in sort_created(items)])


# ---------------- Invoices ----------------

@app.route("/invoices", methods=["POST"])
def create_invoice():
    user_id, _ = require_role("BillingAnalyst")
    body = get_body()
    contract_id = body.get("contract_id")
    if not isinstance(contract_id, str):
        raise ApiError("ERR_INVALID_REQUEST", "contract_id is required", 400)
    if contract_id not in db.contracts:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
    period = body.get("period")
    if not isinstance(period, str) or len(period) != 7 or period[4] != "-":
        raise ApiError("ERR_INVALID_REQUEST", "period must be YYYY-MM", 400)
    try:
        int(period[:4])
        m = int(period[5:7])
        if not (1 <= m <= 12):
            raise ValueError
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "period must be YYYY-MM", 400)
    for inv in db.invoices.values():
        if inv["contract_id"] == contract_id and inv["period"] == period:
            raise ApiError("ERR_INVOICE_PERIOD_DUPLICATE", "Invoice period already exists", 409)
    rec = make_invoice({"contract_id": contract_id, "period": period}, user_id)
    db.invoices[rec["id"]] = rec
    return success_object(rec, 201)


@app.route("/invoices", methods=["GET"])
def list_invoices():
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    items = list(db.invoices.values())
    for f in ("contract_id", "status", "period"):
        v = request.args.get(f)
        if v:
            items = [x for x in items if x.get(f) == v]
    return success_list(sort_created(items))


@app.route("/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    rec = db.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found", 404)
    return success_object(rec)


@app.route("/invoices/<iid>/prepare", methods=["POST"])
def prepare_invoice_endpoint(iid):
    user_id, _ = require_role("BillingAnalyst")
    rec = db.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found", 404)
    if rec["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Invoice must be DRAFT to prepare", 409)
    invoice_logic.prepare_invoice(rec, user_id)
    return success_object(rec)


@app.route("/invoices/<iid>/recompute", methods=["POST"])
def recompute_invoice_endpoint(iid):
    user_id, _ = require_role("BillingAnalyst")
    rec = db.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found", 404)
    if rec["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", "Invoice must be DRAFT or REJECTED to recompute", 409)
    invoice_logic.recompute_invoice(rec)
    return success_object(rec)


@app.route("/invoices/<iid>/lines", methods=["GET"])
def list_invoice_lines(iid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    if iid not in db.invoices:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found", 404)
    items = [l for l in db.invoice_lines.values() if l["invoice_id"] == iid]
    return success_list(sort_created(items))


@app.route("/invoice-lines/<lid>", methods=["GET"])
def get_invoice_line(lid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    rec = db.invoice_lines.get(lid)
    if rec is None:
        raise ApiError("ERR_INVOICE_LINE_NOT_FOUND", "Invoice line not found", 404)
    return success_object(rec)


@app.route("/invoice-lines/<lid>/cure-periods", methods=["GET"])
def list_line_cure_periods(lid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    if lid not in db.invoice_lines:
        raise ApiError("ERR_INVOICE_LINE_NOT_FOUND", "Invoice line not found", 404)
    items = [c for c in db.cure_periods.values() if c["invoice_line_id"] == lid]
    return success_list(sort_created(items))


@app.route("/service-levels/<sid>/invoice-lines", methods=["GET"])
def list_sl_invoice_lines(sid):
    require_role("PlatformAdmin", "OpsManager", "BillingAnalyst")
    if sid not in db.service_levels:
        raise ApiError("ERR_SERVICE_LEVEL_NOT_FOUND", "Service level not found", 404)
    items = [l for l in db.invoice_lines.values() if l["service_level_id"] == sid]
    return success_list(sort_created(items))


@app.route("/cure-periods/<cid>/pay-remedy", methods=["POST"])
def pay_cure_remedy_endpoint(cid):
    user_id, _ = require_role("BillingAnalyst")
    rec = db.cure_periods.get(cid)
    if rec is None:
        raise ApiError("ERR_INVOICE_LINE_NOT_FOUND", "Cure period not found", 404)
    invoice_logic.pay_cure_remedy(rec)
    return success_object(rec)


@app.route("/invoices/<iid>/transition", methods=["POST"])
def invoice_transition(iid):
    user_id, role = require_role("BillingAnalyst", "OpsManager")
    rec = db.invoices.get(iid)
    if rec is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND", "Invoice not found", 404)
    body = get_body()
    to_status = body.get("to_status")
    contract = db.contracts.get(rec["contract_id"])
    if to_status == "SUBMITTED":
        if role != "BillingAnalyst":
            raise ApiError("ERR_FORBIDDEN", "Only BillingAnalyst may submit", 403)
        if rec["status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "Cannot submit from current state", 409)
        has_lines = any(l["invoice_id"] == iid for l in db.invoice_lines.values())
        if not has_lines:
            raise ApiError("ERR_INVALID_STATE", "Invoice has no lines", 409)
        rec["status"] = "SUBMITTED"
        touch(rec)
        return success_object(rec)
    if to_status == "APPROVED":
        if role != "OpsManager":
            raise ApiError("ERR_FORBIDDEN", "Only OpsManager may approve", 403)
        expected = body.get("expected_contract_version")
        if expected is None:
            raise ApiError("ERR_INVALID_REQUEST", "expected_contract_version is required", 400)
        if not isinstance(expected, int):
            raise ApiError("ERR_INVALID_REQUEST", "expected_contract_version must be integer", 400)
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_FOUND", "Contract not found", 404)
        if int(expected) != int(contract["version"]):
            raise ApiError("ERR_STALE_VERSION", "Stale contract version", 412)
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Cannot approve from current state", 409)
        if rec.get("auto_review") and rec.get("preparer_user_id") == user_id:
            raise ApiError("ERR_AUTO_REVIEW_REQUIRES_SECOND_APPROVER",
                           "Auto-review invoices require a second approver", 409)
        rec["status"] = "APPROVED"
        touch(rec)
        touch(contract)
        return success_object(rec)
    if to_status == "PAID":
        if role != "OpsManager":
            raise ApiError("ERR_FORBIDDEN", "Only OpsManager may mark paid", 403)
        if rec["status"] != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", "Cannot mark paid from current state", 409)
        rec["status"] = "PAID"
        touch(rec)
        return success_object(rec)
    if to_status == "REJECTED":
        if role != "OpsManager":
            raise ApiError("ERR_FORBIDDEN", "Only OpsManager may reject", 403)
        if rec["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "Cannot reject from current state", 409)
        rec["status"] = "REJECTED"
        touch(rec)
        return success_object(rec)
    if to_status == "DRAFT":
        if role != "BillingAnalyst":
            raise ApiError("ERR_FORBIDDEN", "Only BillingAnalyst may revise", 403)
        if rec["status"] != "REJECTED":
            raise ApiError("ERR_INVALID_STATE", "Cannot revise from current state", 409)
        rec["status"] = "DRAFT"
        touch(rec)
        return success_object(rec)
    raise ApiError("ERR_INVALID_REQUEST", "Unsupported to_status", 400)


# ---------------- Agent completions (reverse) ----------------

@app.route("/agents/<aid>/completions", methods=["GET"])
def list_agent_completions(aid):
    require_role("PlatformAdmin", "OpsManager", "KnowledgeManager")
    if aid not in db.agents:
        raise ApiError("ERR_AGENT_NOT_FOUND", "Agent not found", 404)
    items = [c for c in db.course_completions.values() if c["agent_id"] == aid]
    return success_list(sort_created(items))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
