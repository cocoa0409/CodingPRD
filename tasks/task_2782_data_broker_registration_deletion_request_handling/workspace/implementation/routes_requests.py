"""Deletion request intake, identity verification and execution
(PRD 3.4, 3.5)."""
from flask import Blueprint

import audit
import guards
import lookups
import propagation
import scoring
from core import (D, bad, db, fail, make, now, ok_list, ok_record, ordered,
                  rhu, touch)
from guards import (ROLE_BROKER_ADMIN, ROLE_CONSUMER, ROLE_INTAKE_AGENT,
                    ROLE_PLATFORM_ADMIN, ROLE_PRIVACY_REVIEWER, ROLE_REGULATOR,
                    ROLE_STATE_PLATFORM, authenticate, body, filter_value,
                    get_decimal, get_enum, get_int, get_str, pagination,
                    require_owner)

bp = Blueprint("requests", __name__)

READ_ROLES = [ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
              ROLE_PRIVACY_REVIEWER, ROLE_INTAKE_AGENT, ROLE_STATE_PLATFORM,
              ROLE_CONSUMER]
ATTEMPT_STATES = ("RECEIVED", "VERIFICATION_PENDING", "VERIFICATION_FAILED")


def _terminate(request_rec, broker):
    broker["request_open_count"] -= 1
    broker["request_terminated_count"] += 1
    touch(broker)


@bp.post("/deletion-requests")
def create_deletion_request():
    caller = authenticate([ROLE_INTAKE_AGENT, ROLE_STATE_PLATFORM,
                           ROLE_CONSUMER])
    data = body()
    consumer_id = data.get("consumer_id")
    if isinstance(consumer_id, str) and consumer_id:
        require_owner(caller, consumer_id=consumer_id)
    broker_id = data.get("broker_id")
    broker = None
    consumer = None
    if isinstance(broker_id, str) and broker_id:
        broker = lookups.broker_or_404(broker_id)
    if isinstance(consumer_id, str) and consumer_id:
        consumer = lookups.consumer_or_404(consumer_id)
    if broker is not None and consumer is not None and consumer["broker_id"] != broker["id"]:
        fail("ERR_CROSS_BROKER_REFERENCE",
             "consumer_id does not belong to broker_id")
    if broker is None:
        bad("broker_id is required")
    if consumer is None:
        bad("consumer_id is required")

    intake_channel = get_enum(data, "intake_channel", guards.INTAKE_CHANNELS)
    requested_scope = get_enum(data, "requested_scope", guards.REQUESTED_SCOPES,
                               required=False, default="DELETE_ALL")
    agent_loa = get_str(data, "agent_loa_reference", 1, 80, required=False,
                        default=None)
    if intake_channel == "AUTHORIZED_AGENT" and agent_loa is None:
        bad("agent_loa_reference is required for the AUTHORIZED_AGENT channel")
    expected = get_int(data, "expected_consumer_version", lo=0)
    if expected != consumer["version"]:
        fail("ERR_STALE_CONSUMER_VERSION",
             "expected_consumer_version %s does not match %s"
             % (expected, consumer["version"]))

    request_rec = make(
        "DeletionRequest",
        broker_id=broker["id"],
        consumer_id=consumer["id"],
        intake_channel=intake_channel,
        requested_scope=requested_scope,
        status="RECEIVED",
        identity_assurance_score=D("0.00"),
        verification_attempt_count=0,
        failed_attempt_count=0,
        agent_loa_reference=agent_loa,
        intake_user_id=caller.user_id,
        verification_decided_by_user_id=None,
        executed_by_user_id=None,
        propagation_required_count=0,
        downstream_task_count=0,
        acked_task_count=0,
        waived_task_count=0,
        abandoned_task_count=0,
        outstanding_task_count=0,
        completion_ratio=D("0.0000"),
        compliance_breach=False,
        executed_at=None,
        denial_reason_code=None,
    )
    db.requests[request_rec["id"]] = request_rec
    touch(consumer)
    broker["request_intake_total"] += 1
    broker["request_open_count"] += 1
    touch(broker)

    for other in ordered([r for r in db.requests.values()
                          if r["consumer_id"] == consumer["id"]
                          and r["id"] != request_rec["id"]]):
        if other["status"] in ATTEMPT_STATES:
            other_broker = db.brokers[other["broker_id"]]
            other["status"] = "SUPERSEDED"
            touch(other)
            _terminate(other, other_broker)
            audit.append(other_broker, "DELETION_REQUEST_SUPERSEDED",
                         "DELETION_REQUEST", other["id"],
                         audit.actor_system(caller),
                         "deletion request superseded by a newer intake")
    audit.append(broker, "DELETION_REQUEST_RECEIVED", "DELETION_REQUEST",
                 request_rec["id"], audit.actor_direct(caller),
                 "deletion request received through %s" % intake_channel)
    return ok_record(request_rec, 201)


@bp.get("/deletion-requests")
def list_deletion_requests():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    broker_id = filter_value("broker_id")
    consumer_id = filter_value("consumer_id")
    status = filter_value("status", guards.REQUEST_STATUSES)
    intake_channel = filter_value("intake_channel", guards.INTAKE_CHANNELS)
    rows = ordered(list(db.requests.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if consumer_id is not None:
        rows = [r for r in rows if r["consumer_id"] == consumer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if intake_channel is not None:
        rows = [r for r in rows if r["intake_channel"] == intake_channel]
    return ok_list(rows, limit, offset)


@bp.get("/deletion-requests/<request_id>")
def get_deletion_request(request_id):
    caller = authenticate(READ_ROLES)
    request_rec = lookups.request_or_404(request_id)
    require_owner(caller, broker_id=request_rec["broker_id"],
                  consumer_id=request_rec["consumer_id"])
    return ok_record(request_rec)


@bp.post("/deletion-requests/<request_id>/verification-attempts")
def record_verification_attempt(request_id):
    caller = authenticate([ROLE_INTAKE_AGENT, ROLE_STATE_PLATFORM,
                           ROLE_PRIVACY_REVIEWER])
    request_rec = lookups.request_or_404(request_id)
    broker = db.brokers[request_rec["broker_id"]]
    data = body()
    method = get_enum(data, "method", guards.VERIFICATION_METHODS)
    evidence_points = get_int(data, "evidence_points_count", 0, 10)
    quality = rhu(get_decimal(data, "document_quality_score", "0.00",
                              "100.00"), 2)
    reference = get_str(data, "platform_assertion_reference", 1, 80,
                        required=False, default=None)
    if method == "AGENT_LOA" and request_rec["agent_loa_reference"] is None:
        bad("an AGENT_LOA attempt requires the request to carry an "
            "agent_loa_reference")
    if request_rec["status"] not in ATTEMPT_STATES:
        fail("ERR_REQUEST_INVALID_STATE",
             "verification attempts are only accepted from RECEIVED, "
             "VERIFICATION_PENDING or VERIFICATION_FAILED")

    computed = scoring.assurance(
        method, evidence_points, quality,
        request_rec["failed_attempt_count"], reference,
        request_rec["intake_channel"])
    attempt = make(
        "VerificationAttempt",
        deletion_request_id=request_rec["id"],
        method=method,
        evidence_points_count=evidence_points,
        document_quality_score=quality,
        platform_assertion_reference=reference,
        variant_applied=computed["variant_applied"],
        raw_score=computed["raw_score"],
        fraud_penalty_applied=computed["fraud_penalty_applied"],
        assurance_score=computed["assurance_score"],
        outcome=computed["outcome"],
        recorded_by_user_id=caller.user_id,
    )
    db.attempts[attempt["id"]] = attempt

    request_rec["verification_attempt_count"] += 1
    if computed["outcome"] == "FAIL":
        request_rec["failed_attempt_count"] += 1
    best = D("0.00")
    for row in db.attempts.values():
        if row["deletion_request_id"] == request_rec["id"]:
            if D(row["assurance_score"]) > best:
                best = D(row["assurance_score"])
    request_rec["identity_assurance_score"] = best
    request_rec["status"] = "VERIFICATION_PENDING"
    touch(request_rec)
    audit.append(broker, "VERIFICATION_ATTEMPT_RECORDED",
                 "VERIFICATION_ATTEMPT", attempt["id"],
                 audit.actor_direct(caller),
                 "verification attempt by %s scored %s (%s)"
                 % (method, computed["assurance_score"], computed["outcome"]))
    return ok_record(attempt, 201)


@bp.get("/deletion-requests/<request_id>/verification-attempts")
def list_verification_attempts(request_id):
    caller = authenticate([ROLE_PRIVACY_REVIEWER, ROLE_BROKER_ADMIN,
                           ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
                           ROLE_INTAKE_AGENT, ROLE_STATE_PLATFORM])
    request_rec = lookups.request_or_404(request_id)
    require_owner(caller, broker_id=request_rec["broker_id"])
    limit, offset = pagination()
    outcome = filter_value("outcome", guards.VERIFICATION_OUTCOMES)
    method = filter_value("method", guards.VERIFICATION_METHODS)
    rows = ordered([a for a in db.attempts.values()
                    if a["deletion_request_id"] == request_rec["id"]])
    if outcome is not None:
        rows = [r for r in rows if r["outcome"] == outcome]
    if method is not None:
        rows = [r for r in rows if r["method"] == method]
    return ok_list(rows, limit, offset)


@bp.post("/deletion-requests/<request_id>/decide-verification")
def decide_verification(request_id):
    caller = authenticate([ROLE_PRIVACY_REVIEWER])
    request_rec = lookups.request_or_404(request_id)
    broker = db.brokers[request_rec["broker_id"]]
    data = body()
    decision = get_enum(data, "decision", guards.VERIFICATION_DECISIONS)
    if request_rec["status"] != "VERIFICATION_PENDING":
        fail("ERR_REQUEST_INVALID_STATE",
             "verification may only be decided from VERIFICATION_PENDING")
    if decision == "VERIFIED" and D(request_rec["identity_assurance_score"]) < scoring.ASSURANCE_PASS_THRESHOLD:
        fail("ERR_ASSURANCE_BELOW_THRESHOLD",
             "identity assurance %s is below the verification threshold"
             % request_rec["identity_assurance_score"])

    request_rec["verification_decided_by_user_id"] = caller.user_id
    request_rec["status"] = "VERIFIED" if decision == "VERIFIED" else "VERIFICATION_FAILED"
    touch(request_rec)
    audit.append(broker, "VERIFICATION_DECIDED", "DELETION_REQUEST",
                 request_rec["id"], audit.actor_direct(caller),
                 "identity verification decided as %s" % decision)
    return ok_record(request_rec)


@bp.post("/deletion-requests/<request_id>/execute")
def execute_deletion(request_id):
    caller = authenticate([ROLE_PRIVACY_REVIEWER, ROLE_BROKER_ADMIN])
    request_rec = lookups.request_or_404(request_id)
    require_owner(caller, broker_id=request_rec["broker_id"])
    broker = db.brokers[request_rec["broker_id"]]
    consumer = db.consumers[request_rec["consumer_id"]]

    if request_rec["status"] != "VERIFIED":
        fail("ERR_REQUEST_INVALID_STATE",
             "only a VERIFIED request may be executed")
    if consumer["sensitive_categories"] and consumer["consent_status"] == "CONSENT_PENDING":
        fail("ERR_SENSITIVE_CONSENT_REQUIRED",
             "a consumer carrying sensitive categories may not be purged while "
             "consent is still pending")
    if caller.user_id == request_rec["verification_decided_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the user who decided verification may not execute the deletion")
    if lookups.accepted_registration_for(broker["id"],
                                         consumer["state_code"]) is None:
        fail("ERR_NO_ACCEPTED_REGISTRATION",
             "the broker holds no accepted filing covering %s at this instant"
             % consumer["state_code"])

    request_rec["status"] = "EXECUTING"
    request_rec["executed_by_user_id"] = caller.user_id
    request_rec["executed_at"] = now()
    if consumer["collection_status"] in ("ACTIVE", "REACQUIRED"):
        consumer["collection_status"] = "PURGE_PENDING"
        touch(consumer)
    propagation.fork(request_rec, consumer)
    touch(request_rec)
    audit.append(broker, "DELETION_EXECUTED", "DELETION_REQUEST",
                 request_rec["id"], audit.actor_direct(caller),
                 "deletion executed and %d propagation tasks forked"
                 % request_rec["propagation_required_count"])
    return ok_record(request_rec)


@bp.post("/deletion-requests/<request_id>/deny")
def deny_deletion(request_id):
    caller = authenticate([ROLE_PRIVACY_REVIEWER])
    request_rec = lookups.request_or_404(request_id)
    broker = db.brokers[request_rec["broker_id"]]
    data = body()
    reason = get_enum(data, "denial_reason_code", guards.DENIAL_REASON_CODES)
    if request_rec["status"] not in ATTEMPT_STATES:
        fail("ERR_REQUEST_INVALID_STATE",
             "only a request that has not yet been verified may be denied")
    request_rec["status"] = "DENIED"
    request_rec["denial_reason_code"] = reason
    touch(request_rec)
    _terminate(request_rec, broker)
    audit.append(broker, "DELETION_DENIED", "DELETION_REQUEST",
                 request_rec["id"], audit.actor_direct(caller),
                 "deletion request denied for %s" % reason)
    return ok_record(request_rec)


@bp.post("/deletion-requests/<request_id>/withdraw")
def withdraw_deletion(request_id):
    caller = authenticate([ROLE_CONSUMER, ROLE_INTAKE_AGENT,
                           ROLE_STATE_PLATFORM])
    request_rec = lookups.request_or_404(request_id)
    require_owner(caller, consumer_id=request_rec["consumer_id"])
    broker = db.brokers[request_rec["broker_id"]]
    if request_rec["status"] not in ("RECEIVED", "VERIFICATION_PENDING",
                                     "VERIFIED", "VERIFICATION_FAILED"):
        fail("ERR_REQUEST_INVALID_STATE",
             "the request may no longer be withdrawn")
    request_rec["status"] = "WITHDRAWN"
    touch(request_rec)
    _terminate(request_rec, broker)
    audit.append(broker, "DELETION_WITHDRAWN", "DELETION_REQUEST",
                 request_rec["id"], audit.actor_direct(caller),
                 "deletion request withdrawn before execution")
    return ok_record(request_rec)
