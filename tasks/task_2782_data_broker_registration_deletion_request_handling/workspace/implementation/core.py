"""Foundation: logical clock, in-memory store, envelope, rounding, errors.

Storage is in-memory only (plain dicts keyed by id). Nothing is persisted and
nothing is seeded at import time.
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

UTC = timezone.utc

# PRD 2.4: the logical clock starts at this fixed instant on every boot and
# never falls back to real time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------
def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    d = dt.astimezone(UTC)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (d.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 UTC timestamp. Raises ValueError when unparseable."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if not s:
        raise ValueError("empty")
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def add_days(dt, n):
    """PRD 2.7: +n days is exactly n * 24h, preserving time-of-day."""
    return dt + timedelta(days=int(n))


def whole_days(start, end):
    """Whole number of days spanned by a half-open interval."""
    return int((end - start).total_seconds() // 86400)


# --------------------------------------------------------------------------
# numeric helpers -- Decimal only, never float, round half up (PRD 2.7)
# --------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def rhu(value, places):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


TWO = 2
FOUR = 4


# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD 5 -- complete error catalogue with HTTP statuses.
ERROR_STATUS = {
    "ERR_MISSING_AUTH_HEADERS": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_ROLE_NOT_PERMITTED": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_BROKER_NOT_FOUND": 404,
    "ERR_REGISTRATION_NOT_FOUND": 404,
    "ERR_CONSUMER_NOT_FOUND": 404,
    "ERR_DELETION_REQUEST_NOT_FOUND": 404,
    "ERR_PROPAGATION_TASK_NOT_FOUND": 404,
    "ERR_RECIPIENT_NOT_FOUND": 404,
    "ERR_SUPPRESSION_ENTRY_NOT_FOUND": 404,
    "ERR_INQUIRY_NOT_FOUND": 404,
    "ERR_AUDIT_EVENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_CROSS_BROKER_REFERENCE": 422,
    "ERR_STALE_BROKER_VERSION": 412,
    "ERR_STALE_CONSUMER_VERSION": 412,
    "ERR_IDENTITY_HASH_DUPLICATE": 409,
    "ERR_DUPLICATE_DISCLOSURE_CATEGORY": 409,
    "ERR_REGISTRATION_INVALID_STATE": 409,
    "ERR_REQUEST_INVALID_STATE": 409,
    "ERR_TASK_INVALID_STATE": 409,
    "ERR_SUPPRESSION_INVALID_STATE": 409,
    "ERR_INQUIRY_INVALID_STATE": 409,
    "ERR_CONSENT_INVALID_TRANSITION": 409,
    "ERR_RECIPIENT_INVALID_STATE": 409,
    "ERR_SUPPRESSION_ACTIVE": 409,
    "ERR_SENSITIVE_CONSENT_REQUIRED": 422,
    "ERR_ASSURANCE_BELOW_THRESHOLD": 422,
    "ERR_NO_ACCEPTED_REGISTRATION": 409,
    "ERR_REQUIRED_DISCLOSURE_MISSING": 422,
    "ERR_AUDIT_EVENT_FOREIGN": 422,
    "ERR_CITED_EVENT_EXPIRED": 422,
    "ERR_DISCLOSURE_INCOMPLETE": 422,
    "ERR_OPT_OUT_SIGNAL_UNRECOGNIZED": 422,
    "ERR_RECIPIENT_NOT_ACTIVE": 409,
    "ERR_LIFT_JUSTIFICATION_REQUIRED": 422,
    "ERR_RESPONSE_INADEQUATE": 422,
    "ERR_COVERAGE_PERIOD_OVERLAP": 409,
    "ERR_SUPPRESSION_WINDOW_CONFLICT": 409,
    "ERR_COVERAGE_PERIOD_INVALID": 422,
    "ERR_RESPONSE_WINDOW_CLOSED": 409,
    "ERR_FILING_FEE_UNPAID": 402,
    "ERR_FEE_DEPOSIT_INVALID": 422,
}


def fail(error_id, message=None):
    raise ApiError(error_id, ERROR_STATUS[error_id], message)


def bad(message="request payload is invalid"):
    fail("ERR_INVALID_REQUEST", message)


# --------------------------------------------------------------------------
# in-memory store
# --------------------------------------------------------------------------
class Store(object):
    """Plain dicts keyed by id. Empty on every boot; nothing is ever seeded."""

    def __init__(self):
        self.brokers = {}
        self.registrations = {}
        self.disclosures = {}
        self.consumers = {}
        self.requests = {}
        self.attempts = {}
        self.recipients = {}
        self.tasks = {}
        self.suppressions = {}
        self.signals = {}
        self.inquiries = {}
        self.audits = {}
        # open_breach_count contributions a single inquiry is responsible for,
        # released when that inquiry is closed (PRD 3.8).
        self.inquiry_contrib = {}
        self._counter = 0
        self.clock = CLOCK_DEFAULT

    def next_seq(self):
        self._counter += 1
        return self._counter


db = Store()


def now():
    return db.clock


def new_id():
    return str(uuid.uuid4())


def make(kind, **fields):
    """Create a record. Records carry a monotonic _seq used as a stable
    tie-breaker for created_at ordering (the logical clock can repeat)."""
    rec = {"_kind": kind, "_seq": db.next_seq()}
    rec["id"] = new_id()
    rec.update(fields)
    rec["created_at"] = now()
    if kind not in NO_COMMON_FIELDS:
        rec["updated_at"] = now()
        rec["version"] = 1
    created = getattr(g, "created", None)
    if created is None:
        created = g.created = {}
    created[id(rec)] = rec
    return rec


NO_COMMON_FIELDS = {"DisclosureItem", "VerificationAttempt", "AuditEvent"}


def touch(rec):
    """Mark a record mutated. PRD 2.4/2.8: updated_at moves to the current
    clock instant and version increases by one, once per record per request."""
    if rec.get("_kind") in NO_COMMON_FIELDS:
        return
    if id(rec) in getattr(g, "created", {}):
        return
    dirty = getattr(g, "dirty", None)
    if dirty is None:
        dirty = g.dirty = {}
    dirty[id(rec)] = rec


def flush():
    dirty = getattr(g, "dirty", None)
    if not dirty:
        return
    stamp = now()
    for rec in dirty.values():
        rec["version"] = rec.get("version", 1) + 1
        rec["updated_at"] = stamp
    g.dirty = {}


def ordered(records):
    """PRD 2.3: default ordering is created_at ascending."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# --------------------------------------------------------------------------
# response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {"api_request_id": request_id(), "api_request_timestamp": fmt_ts(now())}


def _jsonable(value):
    if isinstance(value, datetime):
        return fmt_ts(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return dict((k, _jsonable(v)) for k, v in value.items())
    return value


def view(rec):
    """Serialise a record using only its declared fields (PRD 2.4 / scaffold)."""
    if rec is None:
        return None
    fields = ENTITY_FIELDS[rec["_kind"]]
    out = {}
    for name in fields:
        out[name] = _jsonable(rec.get(name))
    return out


def ok(data, status=200):
    # The deferred version/updated_at flush must land before anything is
    # serialised, so the response already carries the bumped values.
    flush()
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_record(rec, status=200):
    flush()
    return ok(view(rec), status)


def ok_list(records, limit, offset):
    flush()
    total = len(records)
    window = records[offset:offset + limit]
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(window)) < total
    body = {"meta": meta, "response_type": "array",
            "data": [view(r) for r in window]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {"meta": base_meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}


# --------------------------------------------------------------------------
# declared entity field lists (scaffold 1.1 / PRD 3)
# --------------------------------------------------------------------------
ENTITY_FIELDS = {
    "DataBroker": [
        "id", "legal_name", "primary_contact_email", "home_state_code",
        "operating_state_codes", "business_description", "registry_standing",
        "delinquent_since", "fee_deposited_cents", "fee_paid_cents",
        "fee_credit_cents", "open_breach_count", "request_intake_total",
        "request_open_count", "request_completed_count",
        "request_terminated_count", "audit_sequence_high_water",
        "created_at", "updated_at", "version",
    ],
    "Registration": [
        "id", "broker_id", "state_code", "status", "coverage_period_start",
        "coverage_period_end", "coverage_days", "business_description",
        "disclosure_completeness_score", "provisional_filing_fee_cents",
        "final_filing_fee_cents", "charged_fee_cents", "submitted_at",
        "accepted_at", "rejection_reason_code", "revision_count",
        "superseded_registration_id", "created_at", "updated_at", "version",
    ],
    "DisclosureItem": [
        "id", "registration_id", "category", "content", "content_length",
        "covers_sensitive_categories", "weight_credit", "surcharge_cents",
        "created_at",
    ],
    "Consumer": [
        "id", "broker_id", "identity_hash", "state_code",
        "sensitive_categories", "derived_profile_count", "source_label",
        "collection_status", "consent_status", "collection_event_count",
        "opt_out_sale", "opt_out_sharing", "last_purged_at",
        "created_at", "updated_at", "version",
    ],
    "DeletionRequest": [
        "id", "broker_id", "consumer_id", "intake_channel", "requested_scope",
        "status", "identity_assurance_score", "verification_attempt_count",
        "failed_attempt_count", "agent_loa_reference", "intake_user_id",
        "verification_decided_by_user_id", "executed_by_user_id",
        "propagation_required_count", "downstream_task_count",
        "acked_task_count", "waived_task_count", "abandoned_task_count",
        "outstanding_task_count", "completion_ratio", "compliance_breach",
        "executed_at", "denial_reason_code",
        "created_at", "updated_at", "version",
    ],
    "VerificationAttempt": [
        "id", "deletion_request_id", "method", "evidence_points_count",
        "document_quality_score", "platform_assertion_reference",
        "variant_applied", "raw_score", "fraud_penalty_applied",
        "assurance_score", "outcome", "recorded_by_user_id", "created_at",
    ],
    "DownstreamRecipient": [
        "id", "broker_id", "name", "contract_propagation_required",
        "ack_sla_days", "status", "on_time_ack_count", "late_ack_count",
        "fail_count", "waive_count", "reliability_score",
        "created_at", "updated_at", "version",
    ],
    "PropagationTask": [
        "id", "deletion_request_id", "recipient_id", "target_kind", "status",
        "weight", "sla_days", "due_at", "dispatched_at", "acknowledged_at",
        "ack_was_late", "dispatch_count", "failure_code", "deferral_reason",
        "waiver_justification", "created_at", "updated_at", "version",
    ],
    "SuppressionEntry": [
        "id", "broker_id", "consumer_id", "originating_request_id",
        "window_start", "window_end", "source_scope", "status",
        "lift_justification", "blocked_recollection_count",
        "created_at", "updated_at", "version",
    ],
    "OptOutSignal": [
        "id", "broker_id", "consumer_id", "signal_type", "scope",
        "gpc_header_value", "agent_reference", "status", "honor_deadline_at",
        "honored_at", "created_at", "updated_at", "version",
    ],
    "RegulatorInquiry": [
        "id", "broker_id", "scope_note", "response_due_at", "status",
        "cited_audit_event_ids", "cited_event_count", "coverage_bonus_applied",
        "evidence_score", "deficiency_penalty", "late_response_penalty",
        "adequacy_score", "adequacy_verdict", "responded_at",
        "deficiency_code", "escalation_count",
        "created_at", "updated_at", "version",
    ],
    "AuditEvent": [
        "id", "broker_id", "sequence_no", "event_type", "subject_kind",
        "subject_id", "actor_role", "actor_user_id", "summary",
        "retention_expires_at", "created_at",
    ],
}
