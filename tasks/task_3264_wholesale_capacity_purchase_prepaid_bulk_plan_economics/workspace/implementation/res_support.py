"""SupportCase resource: open, read, list, assign, resolve, escalate (M10)."""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError
from store import add_hours, iso, now, parse_ts, touch

READ_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
              "Subscriber"]
LIST_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin"]
CREATE_ROLES = ["Subscriber", "SupportAgent"]
AGENT = ["SupportAgent"]
SUBSCRIBER = ["Subscriber"]

TOPICS = ("ROAMING_SETUP", "DEPRIORITIZATION_COMPLAINT", "PORT_STATUS", "REFUND_REQUEST",
          "RENEWAL_PRICING", "SIM_REPLACEMENT")

SELF_SERVICE_COOLING_SECONDS = 60


def _get(ident):
    return auth.get_or_404("cases", ident, "ERR_CASE_NOT_FOUND")


def _subscriber_of(case):
    subscriber = store.SUBSCRIBERS.get(case["subscriber_id"])
    if subscriber is None:
        raise ApiError("ERR_SUBSCRIBER_NOT_FOUND")
    return subscriber


def _check_budget(subscriber, seconds):
    """Priority 22 (checked before any state is mutated)."""
    if (subscriber.get("support_seconds_used") or 0) + seconds \
            > (subscriber.get("support_seconds_budget") or 0):
        raise ApiError("ERR_SUPPORT_BUDGET_EXCEEDED")


def _apply_booking(subscriber, case, seconds):
    case["handling_seconds"] = (case.get("handling_seconds") or 0) + seconds
    subscriber["support_seconds_used"] = (subscriber.get("support_seconds_used") or 0) + seconds
    touch(subscriber)


def _book(subscriber, case, seconds):
    _check_budget(subscriber, seconds)
    _apply_booking(subscriber, case, seconds)


def register(app):
    @app.route("/carriers/support-cases", methods=["POST"])
    def create_case():
        uid, role = auth.actor()
        auth.require_role(uid, role, CREATE_ROLES)
        data = auth.body()
        auth.check_fields(data, ["subscriber_id", "topic_code"])
        subscriber = auth.get_or_404("subscribers", auth.string(data, "subscriber_id"),
                                     "ERR_SUBSCRIBER_NOT_FOUND")
        if role == "Subscriber":
            auth.require_owner(uid, role, subscriber["id"], "subscriber")
        topic = auth.string(data, "topic_code")
        if topic not in TOPICS:
            raise ApiError("ERR_INVALID_REQUEST", "topic_code is not recognised")
        record = store.stamp({
            "subscriber_id": subscriber["id"],
            "topic_code": topic,
            "case_status": "OPEN",
            "handling_seconds": 0,
            "sla_due_at": calcs.sla_due_at(topic, store.now_iso()),
            "escalation_reason": None,
        })
        store.CASES[record["id"]] = record
        return respond.created(store.serialize("SupportCase", record))

    @app.route("/carriers/support-cases/<ident>", methods=["GET"])
    def read_case(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, READ_ROLES)
        return respond.ok(store.serialize("SupportCase", _get(ident)))

    @app.route("/carriers/support-cases", methods=["GET"])
    def list_cases():
        uid, role = auth.actor()
        auth.require_role(uid, role, LIST_ROLES)
        from flask import request
        args = request.args
        records = list(store.CASES.values())
        if args.get("subscriber_id"):
            records = [c for c in records if c["subscriber_id"] == args["subscriber_id"]]
        if args.get("case_status"):
            records = [c for c in records if c["case_status"] == args["case_status"]]
        if args.get("topic_code"):
            records = [c for c in records if c["topic_code"] == args["topic_code"]]
        return respond.listing("SupportCase", store.by_created(records),
                               args.get("limit"), args.get("offset"))

    @app.route("/carriers/support-cases/<ident>/assign", methods=["POST"])
    def assign_case(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        case = _get(ident)
        subscriber = _subscriber_of(case)
        if case["case_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "case is %s" % case["case_status"])
        _book(subscriber, case, calcs.routing_seconds(case["topic_code"]))
        case["case_status"] = "ASSIGNED"
        touch(case)
        calcs.refresh_support_counters(subscriber)
        return respond.ok(store.serialize("SupportCase", case))

    @app.route("/carriers/support-cases/<ident>/resolve_self_service", methods=["POST"])
    def resolve_self_service(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        case = _get(ident)
        auth.require_owner(uid, role, case["subscriber_id"], "case")
        subscriber = _subscriber_of(case)
        if case["case_status"] != "OPEN":
            raise ApiError("ERR_INVALID_STATE", "case is %s" % case["case_status"])
        # Priority 21: the cooling window on the logical clock.
        created = parse_ts(case.get("created_at"))
        if created is not None and (now() - created).total_seconds() < SELF_SERVICE_COOLING_SECONDS:
            raise ApiError("ERR_SELF_SERVICE_TOO_EARLY")
        case["case_status"] = "RESOLVED_SELF_SERVICE"
        # handling_seconds stays 0 so support_seconds_used gains nothing.
        touch(case)
        subscriber["self_service_deflection_count"] = \
            (subscriber.get("self_service_deflection_count") or 0) + 1
        touch(subscriber)
        calcs.refresh_support_counters(subscriber)
        return respond.ok(store.serialize("SupportCase", case))

    @app.route("/carriers/support-cases/<ident>/resolve_agent", methods=["POST"])
    def resolve_agent(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        case = _get(ident)
        data = auth.body()
        auth.check_fields(data, ["agent_seconds"])
        seconds = auth.integer(data, "agent_seconds")
        if seconds < 0:
            raise ApiError("ERR_INVALID_REQUEST", "agent_seconds must not be negative")
        subscriber = _subscriber_of(case)
        if case["case_status"] not in ("ASSIGNED", "ESCALATED"):
            raise ApiError("ERR_INVALID_STATE", "case is %s" % case["case_status"])
        _book(subscriber, case, seconds)
        case["case_status"] = "RESOLVED_AGENT"
        touch(case)
        calcs.refresh_support_counters(subscriber)
        return respond.ok(store.serialize("SupportCase", case))

    @app.route("/carriers/support-cases/<ident>/escalate", methods=["POST"])
    def escalate_case(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        case = _get(ident)
        subscriber = _subscriber_of(case)
        if case["case_status"] not in ("OPEN", "ASSIGNED"):
            raise ApiError("ERR_INVALID_STATE", "case is %s" % case["case_status"])
        # Priority 22 (budget) precedes priority 23 (the SLA gate); check both
        # before booking so no partial state is left behind on an SLA failure.
        allowance = calcs.escalation_seconds(case["topic_code"])
        _check_budget(subscriber, allowance)
        due = parse_ts(case.get("sla_due_at"))
        if due is None or now() < due:
            raise ApiError("ERR_SLA_NOT_DUE")
        _apply_booking(subscriber, case, allowance)
        case["case_status"] = "ESCALATED"
        case["escalation_reason"] = "SELF_SERVICE_FAILED"
        touch(case)
        calcs.refresh_support_counters(subscriber)
        return respond.ok(store.serialize("SupportCase", case))