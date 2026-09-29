"""Suppression windows and recognised opt-out preference signals (PRD 3.7)."""
from flask import Blueprint

import audit
import guards
import lookups
from core import (add_days, bad, db, fail, make, now, ok_list, ok_record,
                  ordered, touch)
from guards import (ROLE_BROKER_ADMIN, ROLE_CONSUMER, ROLE_INTAKE_AGENT,
                    ROLE_PLATFORM_ADMIN, ROLE_PRIVACY_REVIEWER, ROLE_REGULATOR,
                    ROLE_STATE_PLATFORM, authenticate, body, filter_value,
                    get_enum, get_int, get_str, get_ts, pagination,
                    require_owner)

bp = Blueprint("suppression", __name__)

DEFAULT_WINDOW_DAYS = 730
HONOR_DEADLINE_DAYS = 45
LIFT_JUSTIFICATION_MIN = 20
LIFT_JUSTIFICATION_MAX = 400

SUPPRESSION_READ_ROLES = [ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN,
                          ROLE_REGULATOR, ROLE_PRIVACY_REVIEWER,
                          ROLE_INTAKE_AGENT]
SIGNAL_READ_ROLES = [ROLE_BROKER_ADMIN, ROLE_PLATFORM_ADMIN, ROLE_REGULATOR,
                     ROLE_PRIVACY_REVIEWER, ROLE_CONSUMER, ROLE_STATE_PLATFORM]


# ------------------------------------------------------- suppression entries
@bp.post("/suppression-entries")
def create_suppression_entry():
    caller = authenticate([ROLE_BROKER_ADMIN, ROLE_PRIVACY_REVIEWER])
    data = body()
    broker_id = data.get("broker_id")
    consumer_id = data.get("consumer_id")
    if isinstance(broker_id, str) and broker_id:
        require_owner(caller, broker_id=broker_id)
    if isinstance(consumer_id, str) and consumer_id:
        require_owner(caller, consumer_id=consumer_id)

    broker = None
    consumer = None
    origin = None
    if isinstance(broker_id, str) and broker_id:
        broker = lookups.broker_or_404(broker_id)
    if isinstance(consumer_id, str) and consumer_id:
        consumer = lookups.consumer_or_404(consumer_id)
    origin_id = data.get("originating_request_id")
    if isinstance(origin_id, str) and origin_id:
        origin = lookups.request_or_404(origin_id)

    if broker is not None:
        if consumer is not None and consumer["broker_id"] != broker["id"]:
            fail("ERR_CROSS_BROKER_REFERENCE",
                 "consumer_id does not belong to broker_id")
        if origin is not None and origin["broker_id"] != broker["id"]:
            fail("ERR_CROSS_BROKER_REFERENCE",
                 "originating_request_id does not belong to broker_id")
    if broker is None:
        bad("broker_id is required")
    if consumer is None:
        bad("consumer_id is required")
    if origin_id is not None and origin is None:
        bad("originating_request_id must be a string or null")

    source_scope = get_enum(data, "source_scope", guards.SOURCE_SCOPES)
    start = get_ts(data, "window_start", required=False, default=None)
    if start is None:
        start = now()
    end = get_ts(data, "window_end", required=False, default=None)
    if end is None:
        end = add_days(start, DEFAULT_WINDOW_DAYS)

    if lookups.conflicting_suppression(consumer["id"], start, end) is not None:
        fail("ERR_SUPPRESSION_WINDOW_CONFLICT",
             "the buffered window touches an active suppression entry for "
             "this consumer")
    if not start < end:
        fail("ERR_COVERAGE_PERIOD_INVALID",
             "window_start must be strictly before window_end")

    entry = make(
        "SuppressionEntry",
        broker_id=broker["id"],
        consumer_id=consumer["id"],
        originating_request_id=origin["id"] if origin is not None else None,
        window_start=start,
        window_end=end,
        source_scope=source_scope,
        status="ACTIVE",
        lift_justification=None,
        blocked_recollection_count=0,
    )
    db.suppressions[entry["id"]] = entry
    audit.append(broker, "SUPPRESSION_CREATED", "SUPPRESSION_ENTRY",
                 entry["id"], audit.actor_direct(caller),
                 "suppression entry opened with a %s window" % source_scope)
    return ok_record(entry, 201)


@bp.get("/suppression-entries")
def list_suppression_entries():
    authenticate(SUPPRESSION_READ_ROLES)
    limit, offset = pagination()
    broker_id = filter_value("broker_id")
    consumer_id = filter_value("consumer_id")
    origin_id = filter_value("originating_request_id")
    status = filter_value("status", guards.SUPPRESSION_STATUSES)
    source_scope = filter_value("source_scope", guards.SOURCE_SCOPES)
    rows = ordered(list(db.suppressions.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if consumer_id is not None:
        rows = [r for r in rows if r["consumer_id"] == consumer_id]
    if origin_id is not None:
        rows = [r for r in rows if r["originating_request_id"] == origin_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if source_scope is not None:
        rows = [r for r in rows if r["source_scope"] == source_scope]
    return ok_list(rows, limit, offset)


@bp.get("/suppression-entries/<entry_id>")
def get_suppression_entry(entry_id):
    caller = authenticate(SUPPRESSION_READ_ROLES)
    entry = lookups.suppression_or_404(entry_id)
    require_owner(caller, broker_id=entry["broker_id"],
                  consumer_id=entry["consumer_id"])
    return ok_record(entry)


@bp.post("/suppression-entries/<entry_id>/lift")
def lift_suppression_entry(entry_id):
    caller = authenticate([ROLE_PRIVACY_REVIEWER, ROLE_PLATFORM_ADMIN])
    entry = lookups.suppression_or_404(entry_id)
    broker = db.brokers[entry["broker_id"]]
    data = body()
    if entry["status"] != "ACTIVE":
        fail("ERR_SUPPRESSION_INVALID_STATE",
             "only an ACTIVE suppression entry may be lifted")
    justification = data.get("lift_justification")
    if (not isinstance(justification, str)
            or len(justification) < LIFT_JUSTIFICATION_MIN
            or len(justification) > LIFT_JUSTIFICATION_MAX):
        fail("ERR_LIFT_JUSTIFICATION_REQUIRED",
             "lift_justification must be a string of %d to %d characters"
             % (LIFT_JUSTIFICATION_MIN, LIFT_JUSTIFICATION_MAX))

    entry["status"] = "LIFTED"
    entry["lift_justification"] = justification
    touch(entry)
    audit.append(broker, "SUPPRESSION_LIFTED", "SUPPRESSION_ENTRY",
                 entry["id"], audit.actor_direct(caller),
                 "suppression entry lifted, re-opening the consumer to "
                 "collection")
    return ok_record(entry)


# ---------------------------------------------------------- opt-out signals
def honor_signal(signal, actor, summary):
    """Move a RECEIVED signal to HONORED and push its scope onto the consumer's
    two opt-out flags. Shared by the creating request and the sweep (PRD 3.7,
    3.9 step 4)."""
    consumer = db.consumers[signal["consumer_id"]]
    broker = db.brokers[signal["broker_id"]]
    signal["status"] = "HONORED"
    signal["honored_at"] = now()
    touch(signal)
    if signal["scope"] in ("SALE", "SALE_AND_SHARING"):
        consumer["opt_out_sale"] = True
    if signal["scope"] in ("SHARING", "SALE_AND_SHARING"):
        consumer["opt_out_sharing"] = True
    touch(consumer)
    audit.append(broker, "OPT_OUT_HONORED", "OPT_OUT_SIGNAL", signal["id"],
                 actor, summary)


@bp.post("/opt-out-signals")
def create_opt_out_signal():
    caller = authenticate([ROLE_CONSUMER, ROLE_STATE_PLATFORM,
                           ROLE_INTAKE_AGENT])
    data = body()
    broker_id = data.get("broker_id")
    consumer_id = data.get("consumer_id")
    if isinstance(broker_id, str) and broker_id:
        require_owner(caller, broker_id=broker_id)
    if isinstance(consumer_id, str) and consumer_id:
        require_owner(caller, consumer_id=consumer_id)

    broker = None
    consumer = None
    if isinstance(broker_id, str) and broker_id:
        broker = lookups.broker_or_404(broker_id)
    if isinstance(consumer_id, str) and consumer_id:
        consumer = lookups.consumer_or_404(consumer_id)
    if (broker is not None and consumer is not None
            and consumer["broker_id"] != broker["id"]):
        fail("ERR_CROSS_BROKER_REFERENCE",
             "consumer_id does not belong to broker_id")
    if broker is None:
        bad("broker_id is required")
    if consumer is None:
        bad("consumer_id is required")

    signal_type = get_enum(data, "signal_type", guards.SIGNAL_TYPES)
    scope = get_enum(data, "scope", guards.SIGNAL_SCOPES)
    gpc = get_str(data, "gpc_header_value", 1, 8, required=False, default=None)
    agent_reference = get_str(data, "agent_reference", 1, 80, required=False,
                              default=None)
    expected = get_int(data, "expected_consumer_version", lo=0)

    if expected != consumer["version"]:
        fail("ERR_STALE_CONSUMER_VERSION",
             "expected_consumer_version %s does not match %s"
             % (expected, consumer["version"]))
    if (scope != "SALE_AND_SHARING" and consumer["sensitive_categories"]
            and consumer["consent_status"] != "CONSENT_GRANTED"):
        fail("ERR_SENSITIVE_CONSENT_REQUIRED",
             "a signal narrower than SALE_AND_SHARING requires granted "
             "sensitive-data consent")
    if signal_type == "GPC_BROWSER" and gpc != "1":
        fail("ERR_OPT_OUT_SIGNAL_UNRECOGNIZED",
             "a GPC_BROWSER signal must carry gpc_header_value 1")
    if signal_type == "AGENT_SUBMITTED" and not agent_reference:
        fail("ERR_OPT_OUT_SIGNAL_UNRECOGNIZED",
             "an AGENT_SUBMITTED signal must carry an agent_reference")

    signal = make(
        "OptOutSignal",
        broker_id=broker["id"],
        consumer_id=consumer["id"],
        signal_type=signal_type,
        scope=scope,
        gpc_header_value=gpc,
        agent_reference=agent_reference,
        status="RECEIVED",
        honor_deadline_at=add_days(now(), HONOR_DEADLINE_DAYS),
        honored_at=None,
    )
    db.signals[signal["id"]] = signal
    touch(consumer)

    for other in ordered([s for s in db.signals.values()
                          if s["broker_id"] == broker["id"]
                          and s["consumer_id"] == consumer["id"]
                          and s["id"] != signal["id"]]):
        if other["status"] in ("RECEIVED", "HONORED"):
            other["status"] = "SUPERSEDED"
            touch(other)
    audit.append(broker, "OPT_OUT_RECEIVED", "OPT_OUT_SIGNAL", signal["id"],
                 audit.actor_direct(caller),
                 "opt-out signal received through %s for %s"
                 % (signal_type, scope))
    if signal_type == "PLATFORM_BULK" or (signal_type == "GPC_BROWSER"
                                          and gpc == "1"):
        honor_signal(signal, audit.actor_direct(caller),
                     "machine-readable opt-out honored inside the receiving "
                     "request")
    return ok_record(signal, 201)


@bp.get("/opt-out-signals")
def list_opt_out_signals():
    authenticate(SIGNAL_READ_ROLES)
    limit, offset = pagination()
    broker_id = filter_value("broker_id")
    consumer_id = filter_value("consumer_id")
    signal_type = filter_value("signal_type", guards.SIGNAL_TYPES)
    scope = filter_value("scope", guards.SIGNAL_SCOPES)
    status = filter_value("status", guards.SIGNAL_STATUSES)
    rows = ordered(list(db.signals.values()))
    if broker_id is not None:
        rows = [r for r in rows if r["broker_id"] == broker_id]
    if consumer_id is not None:
        rows = [r for r in rows if r["consumer_id"] == consumer_id]
    if signal_type is not None:
        rows = [r for r in rows if r["signal_type"] == signal_type]
    if scope is not None:
        rows = [r for r in rows if r["scope"] == scope]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return ok_list(rows, limit, offset)


@bp.get("/opt-out-signals/<signal_id>")
def get_opt_out_signal(signal_id):
    caller = authenticate(SIGNAL_READ_ROLES)
    signal = lookups.signal_or_404(signal_id)
    require_owner(caller, broker_id=signal["broker_id"],
                  consumer_id=signal["consumer_id"])
    return ok_record(signal)
