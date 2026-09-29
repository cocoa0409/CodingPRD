"""Downstream recipients and propagation tasks (PRD 3.6)."""
from flask import Blueprint

import audit
import guards
import lookups
import propagation
import scoring
from core import (D, bad, db, fail, make, now, ok_list, ok_record, ordered,
                  touch)
from guards import (ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN,
                    ROLE_PRIVACY_REVIEWER, ROLE_REGULATOR, ROLE_STATE_PLATFORM,
                    authenticate, body, filter_bool, filter_value, get_bool,
                    get_enum, get_int, get_str, pagination, require_owner)

bp = Blueprint("propagation", __name__)

TASK_READ_ROLES = [ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
                   ROLE_PRIVACY_REVIEWER, ROLE_STATE_PLATFORM]
RECIPIENT_READ_ROLES = [ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR]


# ------------------------------------------------------------- recipients
@bp.post("/downstream-recipients")
def create_recipient():
    caller = authenticate([ROLE_BROKER_ADMIN])
    data = body()
    broker_id = data.get("broker_id")
    broker = None
    if isinstance(broker_id, str) and broker_id:
        require_owner(caller, broker_id=broker_id)
        broker = lookups.broker_or_404(broker_id)
    if broker is None:
        bad("broker_id is required")
    name = get_str(data, "name", 1, 160)
    sla_days = get_int(data, "ack_sla_days", 1, 90)
    required = get_bool(data, "contract_propagation_required", default=True)

    recipient = make(
        "DownstreamRecipient",
        broker_id=broker["id"],
        name=name,
        contract_propagation_required=required,
        ack_sla_days=sla_days,
        status="ACTIVE",
        on_time_ack_count=0,
        late_ack_count=0,
        fail_count=0,
        waive_count=0,
        reliability_score=D("90.00"),
    )
    db.recipients[recipient["id"]] = recipient
    audit.append(broker, "RECIPIENT_REGISTERED", "RECIPIENT", recipient["id"],
                 audit.actor_direct(caller),
                 "downstream recipient %s registered" % name)
    return ok_record(recipient, 201)


@bp.get("/downstream-recipients")
def list_recipients():
    authenticate(RECIPIENT_READ_ROLES)
    limit, offset = pagination()
    broker_id = guards.filter_value("broker_id")
    status = filter_value("status", guards.RECIPIENT_STATUSES)
    required = filter_bool("contract_propagation_required")
    rows = ordered(list(db.recipients.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if required is not None:
        rows = [r for r in rows
                if r["contract_propagation_required"] == required]
    return ok_list(rows, limit, offset)


@bp.get("/downstream-recipients/<recipient_id>")
def get_recipient(recipient_id):
    caller = authenticate(RECIPIENT_READ_ROLES)
    recipient = lookups.recipient_or_404(recipient_id)
    require_owner(caller, broker_id=recipient["broker_id"])
    return ok_record(recipient)


@bp.post("/downstream-recipients/<recipient_id>/status")
def change_recipient_status(recipient_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN])
    recipient = lookups.recipient_or_404(recipient_id)
    require_owner(caller, broker_id=recipient["broker_id"])
    broker = db.brokers[recipient["broker_id"]]
    data = body()
    target = get_enum(data, "status", guards.RECIPIENT_STATUSES)
    current = recipient["status"]

    if target == "SUSPENDED":
        if current != "ACTIVE":
            fail("ERR_RECIPIENT_INVALID_STATE",
                 "only an ACTIVE recipient may be suspended")
        propagation.suspend_recipient(
            recipient, broker, audit.actor_direct(caller),
            "recipient suspended by the broker")
    elif target == "ACTIVE":
        if current != "SUSPENDED":
            fail("ERR_RECIPIENT_INVALID_STATE",
                 "only a SUSPENDED recipient may be restored")
        if broker["registry_standing"] == "SUSPENDED":
            fail("ERR_RECIPIENT_INVALID_STATE",
                 "a recipient may not be restored while the broker's registry "
                 "standing is SUSPENDED")
        recipient["status"] = "ACTIVE"
        touch(recipient)
        audit.append(broker, "RECIPIENT_STATUS_CHANGED", "RECIPIENT",
                     recipient["id"], audit.actor_direct(caller),
                     "recipient restored to ACTIVE")
        for task in ordered([t for t in db.tasks.values()
                             if t["recipient_id"] == recipient["id"]]):
            if task["status"] == "DEFERRED":
                task["status"] = "PENDING"
                task["deferral_reason"] = None
                touch(task)
    else:
        if current not in ("ACTIVE", "SUSPENDED"):
            fail("ERR_RECIPIENT_INVALID_STATE",
                 "a TERMINATED recipient may not change status again")
        recipient["status"] = "TERMINATED"
        touch(recipient)
        audit.append(broker, "RECIPIENT_STATUS_CHANGED", "RECIPIENT",
                     recipient["id"], audit.actor_direct(caller),
                     "recipient terminated")
        for task in ordered([t for t in db.tasks.values()
                             if t["recipient_id"] == recipient["id"]]):
            if task["status"] in propagation.OPEN_TASK_STATES:
                propagation.abandon_task(
                    task, audit.actor_system(caller),
                    "propagation abandoned because the recipient was "
                    "terminated")
    return ok_record(recipient)


# ------------------------------------------------------- propagation tasks
def _task_owner_guard(caller, task):
    request_rec = db.requests[task["deletion_request_id"]]
    require_owner(caller, broker_id=request_rec["broker_id"])
    return request_rec


@bp.get("/propagation-tasks")
def list_tasks():
    authenticate(TASK_READ_ROLES)
    limit, offset = pagination()
    request_id = filter_value("deletion_request_id")
    recipient_id = filter_value("recipient_id")
    status = filter_value("status", guards.TASK_STATUSES)
    target_kind = filter_value("target_kind", guards.TASK_TARGET_KINDS)
    rows = ordered(list(db.tasks.values()))
    if request_id is not None:
        rows = [r for r in rows if r["deletion_request_id"] == request_id]
    if recipient_id is not None:
        rows = [r for r in rows if r["recipient_id"] == recipient_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if target_kind is not None:
        rows = [r for r in rows if r["target_kind"] == target_kind]
    return ok_list(rows, limit, offset)


@bp.get("/propagation-tasks/<task_id>")
def get_task(task_id):
    caller = authenticate(TASK_READ_ROLES)
    task = lookups.task_or_404(task_id)
    _task_owner_guard(caller, task)
    return ok_record(task)


@bp.post("/propagation-tasks/<task_id>/dispatch")
def dispatch_task(task_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PRIVACY_REVIEWER])
    task = lookups.task_or_404(task_id)
    request_rec = _task_owner_guard(caller, task)
    broker = db.brokers[request_rec["broker_id"]]

    if task["status"] not in ("PENDING", "FAILED"):
        fail("ERR_TASK_INVALID_STATE",
             "only a PENDING or FAILED task may be dispatched")
    if request_rec["status"] != "EXECUTING":
        fail("ERR_REQUEST_INVALID_STATE",
             "no task may be worked before the fork or after the join")
    if task["target_kind"] == "DOWNSTREAM_RECIPIENT":
        recipient = db.recipients[task["recipient_id"]]
        if recipient["status"] != "ACTIVE":
            fail("ERR_RECIPIENT_NOT_ACTIVE",
                 "the downstream recipient is not ACTIVE")

    task["failure_code"] = None
    task["status"] = "DISPATCHED"
    task["dispatched_at"] = now()
    task["dispatch_count"] += 1
    touch(task)
    audit.append(broker, "PROPAGATION_DISPATCHED", "PROPAGATION_TASK",
                 task["id"], audit.actor_direct(caller),
                 "deletion instruction dispatched to %s" % task["target_kind"])
    return ok_record(task)


@bp.post("/propagation-tasks/<task_id>/ack")
def ack_task(task_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PRIVACY_REVIEWER,
                           ROLE_STATE_PLATFORM])
    task = lookups.task_or_404(task_id)
    request_rec = _task_owner_guard(caller, task)
    broker = db.brokers[request_rec["broker_id"]]
    if task["status"] != "DISPATCHED":
        fail("ERR_TASK_INVALID_STATE",
             "only a DISPATCHED task may be acknowledged")

    task["acknowledged_at"] = now()
    task["ack_was_late"] = task["acknowledged_at"] > task["due_at"]
    task["status"] = "ACKED"
    touch(task)
    if task["recipient_id"] is not None:
        recipient = db.recipients[task["recipient_id"]]
        if task["ack_was_late"]:
            recipient["late_ack_count"] += 1
        else:
            recipient["on_time_ack_count"] += 1
        propagation.rescore_recipient(recipient, broker,
                                      audit.actor_system(caller))
    request_rec["acked_task_count"] += 1
    request_rec["outstanding_task_count"] -= 1
    propagation.recompute_ratio(request_rec)
    touch(request_rec)
    audit.append(broker, "PROPAGATION_ACKED", "PROPAGATION_TASK", task["id"],
                 audit.actor_direct(caller),
                 "propagation acknowledged%s"
                 % (" after the deadline" if task["ack_was_late"] else ""))
    propagation.evaluate_join(request_rec, audit.actor_system(caller))
    return ok_record(task)


@bp.post("/propagation-tasks/<task_id>/fail")
def fail_task(task_id):
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PRIVACY_REVIEWER])
    task = lookups.task_or_404(task_id)
    request_rec = _task_owner_guard(caller, task)
    broker = db.brokers[request_rec["broker_id"]]
    data = body()
    failure_code = get_enum(data, "failure_code", guards.TASK_FAILURE_CODES)
    if task["status"] != "DISPATCHED":
        fail("ERR_TASK_INVALID_STATE",
             "only a DISPATCHED task may be marked failed")

    task["status"] = "FAILED"
    task["failure_code"] = failure_code
    touch(task)
    if task["recipient_id"] is not None:
        recipient = db.recipients[task["recipient_id"]]
        recipient["fail_count"] += 1
        propagation.rescore_recipient(recipient, broker,
                                      audit.actor_system(caller))
    audit.append(broker, "PROPAGATION_FAILED", "PROPAGATION_TASK", task["id"],
                 audit.actor_direct(caller),
                 "propagation failed with %s" % failure_code)
    return ok_record(task)


@bp.post("/propagation-tasks/<task_id>/waive")
def waive_task(task_id):
    caller = authenticate([ROLE_BROKER_ADMIN])
    task = lookups.task_or_404(task_id)
    request_rec = _task_owner_guard(caller, task)
    broker = db.brokers[request_rec["broker_id"]]
    data = body()
    justification = get_str(data, "waiver_justification", 10, 400)
    if task["status"] != "FAILED":
        fail("ERR_TASK_INVALID_STATE", "only a FAILED task may be waived")
    if caller.user_id == request_rec["executed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "the user who executed the deletion may not waive its propagation")

    task["status"] = "WAIVED"
    task["waiver_justification"] = justification
    touch(task)
    if task["recipient_id"] is not None:
        recipient = db.recipients[task["recipient_id"]]
        recipient["waive_count"] += 1
        propagation.rescore_recipient(recipient, broker,
                                      audit.actor_system(caller))
    request_rec["waived_task_count"] += 1
    request_rec["outstanding_task_count"] -= 1
    propagation.recompute_ratio(request_rec)
    touch(request_rec)
    audit.append(broker, "PROPAGATION_WAIVED", "PROPAGATION_TASK", task["id"],
                 audit.actor_direct(caller),
                 "propagation obligation waived")
    propagation.evaluate_join(request_rec, audit.actor_system(caller))
    return ok_record(task)
