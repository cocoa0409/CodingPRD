"""Subscriber resource: create, read, list, cancel, suspend, resume,
consume_data, run_cycle, support_top_ups (M3 + M9 roll entry point)."""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]
LIST_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin"]
CREATE_ROLES = ["CapacityPlanner", "SupportAgent"]
AGENT = ["SupportAgent"]
PLANNER = ["CapacityPlanner"]
CANCEL_ROLES = ["Subscriber"]

CREATE_REQUIRED = ["msisdn", "full_name", "state_code"]


def _get(ident):
    return auth.get_or_404("subscribers", ident, "ERR_SUBSCRIBER_NOT_FOUND")


def register(app):
    @app.route("/carriers/subscribers", methods=["POST"])
    def create_subscriber():
        uid, role = auth.actor()
        auth.require_role(uid, role, CREATE_ROLES)
        data = auth.body()
        auth.check_fields(data, CREATE_REQUIRED)
        msisdn = auth.string(data, "msisdn")
        if len(msisdn) != 11 or not msisdn.isdigit():
            raise ApiError("ERR_INVALID_REQUEST", "msisdn must be eleven digits")
        for other in store.SUBSCRIBERS.values():
            if other["msisdn"] == msisdn and other["subscriber_status"] != "CHURNED":
                raise ApiError("ERR_INVALID_REQUEST", "msisdn is already in use")
        state_code = auth.string(data, "state_code")
        if len(state_code) != 2 or state_code.upper() != state_code:
            raise ApiError("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
        record = store.stamp({
            "msisdn": msisdn,
            "full_name": auth.string(data, "full_name"),
            "state_code": state_code,
            "subscriber_status": "PENDING_PORT",
            "allocation_status": "NONE",
            "cycle_index": 0,
            "cycles_rolled": 0,
            "data_used_mb_cycle": 0,
            "deprioritized_this_cycle": False,
            "cycle_deprioritization_days": 0,
            "support_seconds_used": 0,
            "support_seconds_budget": calcs.DEFAULT_SUPPORT_BUDGET_SECONDS,
            "self_service_deflection_count": 0,
        })
        store.SUBSCRIBERS[record["id"]] = record
        return respond.created(store.serialize("Subscriber", record))

    @app.route("/carriers/subscribers/<ident>", methods=["GET"])
    def read_subscriber(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        record = _get(ident)
        return respond.ok(store.serialize("Subscriber", record))

    @app.route("/carriers/subscribers", methods=["GET"])
    def list_subscribers():
        uid, role = auth.actor()
        auth.require_role(uid, role, LIST_ROLES)
        from flask import request
        args = request.args
        records = list(store.SUBSCRIBERS.values())
        if args.get("state_code"):
            records = [s for s in records if s["state_code"] == args["state_code"]]
        if args.get("subscriber_status"):
            records = [s for s in records if s["subscriber_status"] == args["subscriber_status"]]
        return respond.listing("Subscriber", store.by_created(records), args.get("limit"), args.get("offset"))

    @app.route("/carriers/subscribers/<ident>/cancel", methods=["POST"])
    def cancel_subscriber(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, CANCEL_ROLES)
        subscriber = _get(ident)
        auth.require_owner(uid, role, subscriber["id"], "subscriber")
        data = auth.body()
        # Priority 6: lifecycle state permits the transition.
        if subscriber["subscriber_status"] not in ("ACTIVE", "SUSPENDED"):
            raise ApiError("ERR_INVALID_STATE",
                           "subscriber is %s" % subscriber["subscriber_status"])
        # Priority 25: an in-flight port blocks churn (ACTIVE path only).
        if subscriber["subscriber_status"] == "ACTIVE":
            for activation in store.ACTIVATIONS.values():
                if activation["subscriber_id"] == subscriber["id"] \
                        and activation["port_status"] == "SUBMITTED":
                    raise ApiError("ERR_PORT_IN_FLIGHT")
        # OCC on the subscriber's own version (mandatory on this endpoint).
        if "expected_Subscriber_version" not in data:
            raise ApiError("ERR_INVALID_REQUEST", "expected_Subscriber_version is required")
        auth.version_check(subscriber, data.get("expected_Subscriber_version"))
        engine.churn_subscriber(subscriber)
        return respond.ok(store.serialize("Subscriber", subscriber))

    @app.route("/carriers/subscribers/<ident>/suspend", methods=["POST"])
    def suspend_subscriber(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        subscriber = _get(ident)
        data = auth.body()
        auth.version_check(subscriber, data.get("expected_Subscriber_version"))
        if subscriber["subscriber_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE",
                           "subscriber is %s" % subscriber["subscriber_status"])
        subscriber["subscriber_status"] = "SUSPENDED"
        store.touch(subscriber)
        # The prepaid term is still committed capacity, so the balance is untouched.
        return respond.ok(store.serialize("Subscriber", subscriber))

    @app.route("/carriers/subscribers/<ident>/resume", methods=["POST"])
    def resume_subscriber(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        subscriber = _get(ident)
        data = auth.body()
        auth.version_check(subscriber, data.get("expected_Subscriber_version"))
        if subscriber["subscriber_status"] != "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE",
                           "subscriber is %s" % subscriber["subscriber_status"])
        subscriber["subscriber_status"] = "ACTIVE"
        store.touch(subscriber)
        term = calcs.current_term(subscriber["id"])
        if term is not None:
            plan = store.PLANS.get(term["plan_id"])
            agreement = store.AGREEMENTS.get(plan["agreement_id"]) if plan else None
            if agreement is not None:
                calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Subscriber", subscriber))

    @app.route("/carriers/subscribers/<ident>/consume_data", methods=["POST"])
    def consume_data(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        subscriber = _get(ident)
        data = auth.body()
        auth.check_fields(data, ["data_mb"])
        data_mb = auth.integer(data, "data_mb")
        # Priority 15: subscriber + term must both be live.
        if subscriber["subscriber_status"] != "ACTIVE":
            raise ApiError("ERR_SUBSCRIBER_NOT_ACTIVE")
        term = calcs.current_term(subscriber["id"])
        if term is None or term["term_status"] not in calcs.LIVE_TERM:
            raise ApiError("ERR_TERM_NOT_ACTIVE")
        if subscriber["cycle_index"] < 1:
            raise ApiError("ERR_INVALID_STATE", "there is no open cycle to consume against")
        subscriber["data_used_mb_cycle"] = (subscriber.get("data_used_mb_cycle") or 0) + data_mb
        # PRD 3.4: the days counter "counts the distinct calendar days in the open cycle
        # on which deprioritized_this_cycle was true; it is incremented at most once per
        # distinct day, including the current day at the moment the threshold is first
        # met". The logical clock date is the day, so a second booking on the same
        # calendar day must not add a second day.
        if not subscriber["deprioritized_this_cycle"] and calcs.deprioritization_check(subscriber):
            subscriber["deprioritized_this_cycle"] = True
            subscriber["cycle_deprioritization_days"] = 1
        store.touch(subscriber)
        agreement = engine.agreement_of_plan(store.PLANS[term["plan_id"]])
        if agreement is not None:
            calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Subscriber", subscriber))

    @app.route("/carriers/subscribers/<ident>/run_cycle", methods=["POST"])
    def run_cycle(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        subscriber = _get(ident)
        engine.roll_cycle(subscriber)
        return respond.ok(store.serialize("Subscriber", subscriber))

    @app.route("/carriers/subscribers/<ident>/support_top_ups", methods=["POST"])
    def support_top_ups(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        subscriber = _get(ident)
        data = auth.body()
        auth.check_fields(data, ["granted_seconds"])
        granted = auth.integer(data, "granted_seconds")
        if granted < 0:
            raise ApiError("ERR_INVALID_REQUEST", "granted_seconds must not be negative")
        subscriber["support_seconds_budget"] = (subscriber.get("support_seconds_budget") or 0) + granted
        store.touch(subscriber)
        calcs.refresh_support_counters(subscriber)
        return respond.ok(store.serialize("Subscriber", subscriber))