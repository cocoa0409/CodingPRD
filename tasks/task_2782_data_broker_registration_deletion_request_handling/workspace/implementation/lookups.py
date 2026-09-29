"""Existence resolution (PRD 2.6 rules 5-13, 2.9) and the suppression /
registration-coverage predicates shared across routes."""
import audit
from core import add_days, db, fail, now, ordered, touch

SUPPRESSION_CONFLICT_BUFFER_DAYS = 30


def broker_or_404(broker_id):
    rec = db.brokers.get(broker_id)
    if rec is None:
        fail("ERR_BROKER_NOT_FOUND", "broker %s does not exist" % broker_id)
    return rec


def registration_or_404(registration_id):
    rec = db.registrations.get(registration_id)
    if rec is None:
        fail("ERR_REGISTRATION_NOT_FOUND",
             "registration %s does not exist" % registration_id)
    return rec


def consumer_or_404(consumer_id):
    rec = db.consumers.get(consumer_id)
    if rec is None:
        fail("ERR_CONSUMER_NOT_FOUND",
             "consumer %s does not exist" % consumer_id)
    return rec


def request_or_404(request_id):
    rec = db.requests.get(request_id)
    if rec is None:
        fail("ERR_DELETION_REQUEST_NOT_FOUND",
             "deletion request %s does not exist" % request_id)
    return rec


def task_or_404(task_id):
    rec = db.tasks.get(task_id)
    if rec is None:
        fail("ERR_PROPAGATION_TASK_NOT_FOUND",
             "propagation task %s does not exist" % task_id)
    return rec


def recipient_or_404(recipient_id):
    rec = db.recipients.get(recipient_id)
    if rec is None:
        fail("ERR_RECIPIENT_NOT_FOUND",
             "downstream recipient %s does not exist" % recipient_id)
    return rec


def suppression_or_404(entry_id):
    rec = db.suppressions.get(entry_id)
    if rec is None:
        fail("ERR_SUPPRESSION_ENTRY_NOT_FOUND",
             "suppression entry %s does not exist" % entry_id)
    return rec


def signal_or_404(signal_id):
    rec = db.signals.get(signal_id)
    if rec is None:
        fail("ERR_SUPPRESSION_ENTRY_NOT_FOUND",
             "opt-out signal %s does not exist" % signal_id)
    return rec


def inquiry_or_404(inquiry_id):
    rec = db.inquiries.get(inquiry_id)
    if rec is None:
        fail("ERR_INQUIRY_NOT_FOUND", "inquiry %s does not exist" % inquiry_id)
    return rec


def audit_event_or_404(event_id):
    rec = db.audits.get(event_id)
    if rec is None:
        fail("ERR_AUDIT_EVENT_NOT_FOUND",
             "audit event %s does not exist" % event_id)
    return rec


# ------------------------------------------------------------------ coverage
def accepted_registration_for(broker_id, state_code):
    """An ACCEPTED filing of this broker whose half-open coverage interval
    contains the clock and whose state_code matches (PRD 3.3/3.5)."""
    clock = now()
    for reg in ordered(list(db.registrations.values())):
        if (reg["broker_id"] == broker_id
                and reg["state_code"] == state_code
                and reg["status"] == "ACCEPTED"
                and reg["coverage_period_start"] <= clock < reg["coverage_period_end"]):
            return reg
    return None


def overlapping_registration(broker_id, state_code, start, end,
                             exclude_id=None):
    """No SUBMITTED or ACCEPTED filing of the same broker and state may hold an
    intersecting half-open interval; touching endpoints do not intersect."""
    for reg in ordered(list(db.registrations.values())):
        if reg["broker_id"] != broker_id or reg["state_code"] != state_code:
            continue
        if exclude_id is not None and reg["id"] == exclude_id:
            continue
        if reg["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if start < reg["coverage_period_end"] and reg["coverage_period_start"] < end:
            return reg
    return None


def disclosures_of(registration_id):
    return ordered([d for d in db.disclosures.values()
                    if d["registration_id"] == registration_id])


# --------------------------------------------------------------- suppression
def conflicting_suppression(consumer_id, start, end, exclude_id=None):
    """Buffered conflict test: an entry conflicts when window_start is at or
    before the other window_end plus 30 days and window_end plus 30 days is at
    or after the other window_start (PRD 3.7)."""
    for entry in ordered(list(db.suppressions.values())):
        if entry["consumer_id"] != consumer_id or entry["status"] != "ACTIVE":
            continue
        if exclude_id is not None and entry["id"] == exclude_id:
            continue
        other_start = entry["window_start"]
        other_end = entry["window_end"]
        if (start <= add_days(other_end, SUPPRESSION_CONFLICT_BUFFER_DAYS)
                and add_days(end, SUPPRESSION_CONFLICT_BUFFER_DAYS) >= other_start):
            return entry
    return None


def _entry_single_source_label(entry):
    """The source_label the consumer carried on the originating request."""
    consumer = db.consumers.get(entry["consumer_id"])
    return consumer["source_label"] if consumer else None


def blocking_suppression(consumer_id, source_label):
    """An ACTIVE entry whose closed window contains the clock blocks according
    to its source_scope (PRD 3.7)."""
    clock = now()
    for entry in ordered(list(db.suppressions.values())):
        if entry["consumer_id"] != consumer_id or entry["status"] != "ACTIVE":
            continue
        if not (entry["window_start"] <= clock <= entry["window_end"]):
            continue
        if entry["source_scope"] == "ALL_SOURCES":
            return entry
        if source_label is not None and source_label == _entry_single_source_label(entry):
            return entry
    return None


def record_recollection_block(entry, broker, consumer_id, actor):
    """Durable state on a 4xx: the counter moves and RECOLLECTION_BLOCKED is
    appended even though the call is refused (PRD 3.7)."""
    entry["blocked_recollection_count"] += 1
    touch(entry)
    audit.append(broker, "RECOLLECTION_BLOCKED", "CONSUMER", consumer_id,
                 actor, "re-collection refused by an active suppression entry")
    fail("ERR_SUPPRESSION_ACTIVE",
         "an active suppression entry blocks this collection")
