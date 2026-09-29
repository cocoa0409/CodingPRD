"""Regulator inquiries and the evidence trail (PRD 3.8)."""
from flask import Blueprint

import audit
import guards
import lookups
import scoring
import standing
from core import (D, add_days, bad, db, fail, make, now, ok_list, ok_record,
                  ordered, touch)
from guards import (ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
                    authenticate, body, filter_value, get_enum, get_str,
                    pagination, require_owner)

bp = Blueprint("inquiries", __name__)

SCOPE_NOTE_MIN = 10
SCOPE_NOTE_MAX = 600
READ_ROLES = [ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR]


def _contrib(inquiry_id):
    return db.inquiry_contrib.get(inquiry_id, 0)


def _add_contrib(inquiry_id, delta):
    db.inquiry_contrib[inquiry_id] = _contrib(inquiry_id) + delta


@bp.post("/regulator-inquiries")
def open_inquiry():
    caller = authenticate([ROLE_REGULATOR])
    data = body()
    broker_id = data.get("broker_id")
    broker = None
    if isinstance(broker_id, str) and broker_id:
        broker = lookups.broker_or_404(broker_id)
    if broker is None:
        bad("broker_id is required")
    scope_note = get_str(data, "scope_note", SCOPE_NOTE_MIN, SCOPE_NOTE_MAX)
    due_at = guards.get_ts(data, "response_due_at")
    if not due_at > now():
        bad("response_due_at must be strictly after the current clock instant")

    inquiry = make(
        "RegulatorInquiry",
        broker_id=broker["id"],
        scope_note=scope_note,
        response_due_at=due_at,
        status="OPEN",
        cited_audit_event_ids=[],
        cited_event_count=0,
        coverage_bonus_applied=False,
        evidence_score=D("0.00"),
        deficiency_penalty=D("0.00"),
        late_response_penalty=D("0.00"),
        adequacy_score=D("0.00"),
        adequacy_verdict="UNRATED",
        responded_at=None,
        deficiency_code=None,
        escalation_count=0,
    )
    db.inquiries[inquiry["id"]] = inquiry
    audit.append(broker, "INQUIRY_OPENED", "INQUIRY", inquiry["id"],
                 audit.actor_direct(caller),
                 "regulator inquiry opened into the broker's request handling")
    return ok_record(inquiry, 201)


@bp.get("/regulator-inquiries")
def list_inquiries():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    broker_id = filter_value("broker_id")
    status = filter_value("status", guards.INQUIRY_STATUSES)
    verdict = filter_value("adequacy_verdict", guards.ADEQUACY_VERDICTS)
    rows = ordered(list(db.inquiries.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if verdict is not None:
        rows = [r for r in rows if r["adequacy_verdict"] == verdict]
    return ok_list(rows, limit, offset)


@bp.get("/regulator-inquiries/<inquiry_id>")
def get_inquiry(inquiry_id):
    caller = authenticate(READ_ROLES)
    inquiry = lookups.inquiry_or_404(inquiry_id)
    require_owner(caller, broker_id=inquiry["broker_id"])
    return ok_record(inquiry)


@bp.post("/regulator-inquiries/<inquiry_id>/respond")
def respond_to_inquiry(inquiry_id):
    caller = authenticate([ROLE_BROKER_ADMIN])
    inquiry = lookups.inquiry_or_404(inquiry_id)
    require_owner(caller, broker_id=inquiry["broker_id"])
    broker = db.brokers[inquiry["broker_id"]]
    data = body()

    raw = data.get("cited_audit_event_ids")
    if not isinstance(raw, list):
        bad("cited_audit_event_ids must be an array of audit event ids")
    for item in raw:
        if not isinstance(item, str) or not item:
            bad("cited_audit_event_ids entries must be non-empty strings")
    cited = [lookups.audit_event_or_404(event_id) for event_id in raw]

    if inquiry["status"] not in ("OPEN", "ESCALATED"):
        fail("ERR_INQUIRY_INVALID_STATE",
             "an inquiry may only be answered from OPEN or ESCALATED")
    for event in cited:
        if event["broker_id"] != inquiry["broker_id"]:
            fail("ERR_AUDIT_EVENT_FOREIGN",
                 "audit event %s belongs to another broker's trail"
                 % event["id"])
    clock = now()
    for event in cited:
        if clock > event["retention_expires_at"]:
            fail("ERR_CITED_EVENT_EXPIRED",
                 "audit event %s has passed its retention horizon"
                 % event["id"])
    if clock > add_days(inquiry["response_due_at"],
                        scoring.RESPONSE_GRACE_DAYS):
        fail("ERR_RESPONSE_WINDOW_CLOSED",
             "the response window including its 30-day grace has closed")

    late = clock > inquiry["response_due_at"]
    scored = scoring.adequacy(cited, late)
    inquiry["cited_audit_event_ids"] = list(raw)
    inquiry["cited_event_count"] = scored["cited_event_count"]
    inquiry["coverage_bonus_applied"] = scored["coverage_bonus_applied"]
    inquiry["evidence_score"] = scored["evidence_score"]
    inquiry["deficiency_penalty"] = scored["deficiency_penalty"]
    inquiry["late_response_penalty"] = scored["late_response_penalty"]
    inquiry["adequacy_score"] = scored["adequacy_score"]
    inquiry["adequacy_verdict"] = scored["adequacy_verdict"]
    inquiry["responded_at"] = clock
    inquiry["status"] = "RESPONDED"
    touch(inquiry)
    audit.append(broker, "INQUIRY_RESPONDED", "INQUIRY", inquiry["id"],
                 audit.actor_direct(caller),
                 "inquiry answered with %d citations scoring %s (%s)"
                 % (scored["cited_event_count"], scored["adequacy_score"],
                    scored["adequacy_verdict"]))
    if scored["adequacy_verdict"] == "DEFICIENT":
        broker["open_breach_count"] += 1
        touch(broker)
        _add_contrib(inquiry["id"], 1)
        standing.derive_standing(broker, audit.actor_system(caller))
    return ok_record(inquiry)


@bp.post("/regulator-inquiries/<inquiry_id>/escalate")
def escalate_inquiry(inquiry_id):
    caller = authenticate([ROLE_REGULATOR])
    inquiry = lookups.inquiry_or_404(inquiry_id)
    broker = db.brokers[inquiry["broker_id"]]
    data = body()
    code = get_enum(data, "deficiency_code", guards.DEFICIENCY_CODES)
    if inquiry["status"] != "RESPONDED":
        fail("ERR_INQUIRY_INVALID_STATE",
             "only a RESPONDED inquiry may be escalated")

    inquiry["status"] = "ESCALATED"
    inquiry["deficiency_code"] = code
    inquiry["escalation_count"] += 1
    touch(inquiry)
    broker["open_breach_count"] += 1
    touch(broker)
    _add_contrib(inquiry["id"], 1)
    standing.derive_standing(broker, audit.actor_system(caller))
    audit.append(broker, "INQUIRY_ESCALATED", "INQUIRY", inquiry["id"],
                 audit.actor_direct(caller),
                 "inquiry escalated for %s" % code)
    return ok_record(inquiry)


@bp.post("/regulator-inquiries/<inquiry_id>/close")
def close_inquiry(inquiry_id):
    caller = authenticate([ROLE_REGULATOR])
    inquiry = lookups.inquiry_or_404(inquiry_id)
    broker = db.brokers[inquiry["broker_id"]]
    if inquiry["status"] != "RESPONDED":
        fail("ERR_INQUIRY_INVALID_STATE",
             "only a RESPONDED inquiry may be closed")
    if inquiry["adequacy_verdict"] != "ADEQUATE":
        fail("ERR_RESPONSE_INADEQUATE",
             "an inquiry may only be closed on an ADEQUATE verdict")

    inquiry["status"] = "CLOSED"
    touch(inquiry)
    released = _contrib(inquiry["id"])
    if released:
        broker["open_breach_count"] -= released
        if broker["open_breach_count"] < 0:
            broker["open_breach_count"] = 0
        touch(broker)
        db.inquiry_contrib[inquiry["id"]] = 0
    standing.derive_standing(broker, audit.actor_system(caller))
    audit.append(broker, "INQUIRY_CLOSED", "INQUIRY", inquiry["id"],
                 audit.actor_direct(caller),
                 "inquiry closed and its %d breach contribution(s) released"
                 % released)
    return ok_record(inquiry)
