"""PrepaidTerm resource: quote, read, list, purchase, step-up, cancel (M4)."""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]
SUBSCRIBER = ["Subscriber"]
CANCEL_ROLES = ["Subscriber", "SupportAgent"]

QUOTE_REQUIRED = ["subscriber_id", "plan_id", "expected_CapacityAgreement_version"]
# A derived field: supplying it is ignored, but it must still be a known field.
QUOTE_DERIVED = ["deprioritization_threshold_mb"]

REFUNDABLE_STATUSES = {"QUOTED", "PURCHASED", "AWAITING_ACTIVATION"}


def _get(ident):
    return auth.get_or_404("terms", ident, "ERR_TERM_NOT_FOUND")


def _other_live_term(subscriber_id, exclude_id):
    for term in store.TERMS.values():
        if term["subscriber_id"] != subscriber_id:
            continue
        if term["id"] == exclude_id:
            continue
        if term["term_status"] in calcs.NON_TERMINAL_TERM:
            return term
    return None


def _sale_gate(plan, agreement, allotment_mb):
    """Validation priorities 8, 9 and 10 in that order."""
    if agreement["agreement_status"] == "SUSPENDED":
        raise ApiError("ERR_AGREEMENT_SUSPENDED")
    if agreement["agreement_status"] == "CLOSED":
        raise ApiError("ERR_AGREEMENT_CLOSED")
    if plan["plan_status"] == "RETIRED":
        raise ApiError("ERR_PLAN_RETIRED")
    allocated = calcs.allocated_data_mb(agreement)
    if allocated + allotment_mb > calcs.oversale_ceiling(agreement):
        raise ApiError("ERR_INSUFFICIENT_AGREEMENT_CAPACITY")


def register(app):
    @app.route("/carriers/prepaid-terms", methods=["POST"])
    def quote_term():
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        data = auth.body()
        auth.check_fields(data, QUOTE_REQUIRED, QUOTE_DERIVED)
        # Priority 3: a Subscriber acts only on its own rows.
        auth.require_owner(uid, role, auth.string(data, "subscriber_id"), "subscriber")
        # Priority 5: body foreign keys in input order.
        subscriber = auth.get_or_404("subscribers", auth.string(data, "subscriber_id"),
                                     "ERR_SUBSCRIBER_NOT_FOUND")
        plan = auth.get_or_404("plans", auth.string(data, "plan_id"), "ERR_PLAN_NOT_FOUND")
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        # OCC on the agreement is mandatory on this endpoint.
        auth.version_check(agreement, data.get("expected_CapacityAgreement_version"))
        _sale_gate(plan, agreement, plan["data_allotment_mb"])
        if _other_live_term(subscriber["id"], None) is not None:
            raise ApiError("ERR_DUPLICATE_ACTIVE_TERM")
        record = store.stamp({
            "subscriber_id": subscriber["id"],
            "plan_id": plan["id"],
            "term_status": "QUOTED",
            "term_price_cents": 0,
            "starts_at": None,
            "expires_at": None,
            "deferred_revenue_cents": 0,
            "earned_revenue_cents": 0,
            "breakage_days": 0,
            "breakage_cents_recognized": 0,
            "void_reason": None,
        })
        store.TERMS[record["id"]] = record
        calcs.settlement_clearing(agreement)
        return respond.created(store.serialize("PrepaidTerm", record))

    @app.route("/carriers/prepaid-terms/<ident>", methods=["GET"])
    def read_term(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        return respond.ok(store.serialize("PrepaidTerm", _get(ident)))

    @app.route("/carriers/prepaid-terms", methods=["GET"])
    def list_terms():
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        from flask import request
        args = request.args
        records = list(store.TERMS.values())
        if args.get("subscriber_id"):
            records = [t for t in records if t["subscriber_id"] == args["subscriber_id"]]
        if args.get("plan_id"):
            records = [t for t in records if t["plan_id"] == args["plan_id"]]
        if args.get("term_status"):
            records = [t for t in records if t["term_status"] == args["term_status"]]
        return respond.listing("PrepaidTerm", store.by_created(records),
                               args.get("limit"), args.get("offset"))

    @app.route("/carriers/prepaid-terms/<ident>/purchase", methods=["POST"])
    def purchase_term(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        term = _get(ident)
        auth.require_owner(uid, role, term["subscriber_id"], "term")
        data = auth.body()
        plan = store.PLANS.get(term["plan_id"])
        if plan is None:
            raise ApiError("ERR_PLAN_NOT_FOUND")
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        auth.version_check(agreement, data.get("expected_CapacityAgreement_version"))
        # Priority 6: the term's own lifecycle state, then priority 7 terminality.
        if term["term_status"] in ("REFUNDED", "VOIDED"):
            raise ApiError("ERR_TERM_ALREADY_TERMINAL")
        if term["term_status"] != "QUOTED":
            raise ApiError("ERR_INVALID_STATE", "only a QUOTED term can be purchased")
        _sale_gate(plan, agreement, plan["data_allotment_mb"])
        if _other_live_term(term["subscriber_id"], term["id"]) is not None:
            raise ApiError("ERR_DUPLICATE_ACTIVE_TERM")
        if plan["plan_status"] not in ("OFFERED", "ACTIVE"):
            raise ApiError("ERR_PLAN_RETIRED")
        if agreement["agreement_status"] != "ACTIVE":
            raise ApiError("ERR_AGREEMENT_CLOSED")
        term["term_status"] = "PURCHASED"
        term["term_price_cents"] = calcs.prepaid_term_price(term, plan)
        earned, deferred = calcs.provisional_schedule(term["term_price_cents"],
                                                     plan["term_months"], 1)
        term["earned_revenue_cents"] = earned
        term["deferred_revenue_cents"] = deferred
        store.touch(term)
        # The purchase is the capacity-allocation event: the subscriber now holds
        # the plan's allotment off the agreement (HELD = promised to them).
        subscriber = store.SUBSCRIBERS.get(term["subscriber_id"])
        if subscriber is not None and subscriber["allocation_status"] == "NONE":
            subscriber["allocation_status"] = "HELD"
            store.touch(subscriber)
        # PRD 3.5: on a successful purchase "the plan is moved from OFFERED to ACTIVE".
        if plan["plan_status"] == "OFFERED":
            plan["plan_status"] = "ACTIVE"
            store.touch(plan)
        engine.sync_plan_status(plan)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("PrepaidTerm", term))

    @app.route("/carriers/prepaid-terms/<ident>/accept_step_up", methods=["POST"])
    def accept_step_up(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        term = _get(ident)
        auth.require_owner(uid, role, term["subscriber_id"], "term")
        data = auth.body()
        plan = store.PLANS.get(term["plan_id"])
        if plan is None:
            raise ApiError("ERR_PLAN_NOT_FOUND")
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        auth.version_check(agreement, data.get("expected_CapacityAgreement_version"))
        if term["term_status"] in ("REFUNDED", "VOIDED", "EXPIRED"):
            raise ApiError("ERR_TERM_ALREADY_TERMINAL")
        if term["term_status"] != "RENEWAL_DUE":
            raise ApiError("ERR_INVALID_STATE", "only a RENEWAL_DUE term can step up")
        _sale_gate(plan, agreement, plan["data_allotment_mb"])
        if _other_live_term(term["subscriber_id"], term["id"]) is not None:
            raise ApiError("ERR_DUPLICATE_ACTIVE_TERM")
        subscriber = store.SUBSCRIBERS.get(term["subscriber_id"])
        if subscriber is None:
            raise ApiError("ERR_SUBSCRIBER_NOT_FOUND")
        term["term_status"] = "ACTIVE_RENEWAL"
        term["term_price_cents"] = plan["renewal_price_cents"]
        if term.get("expires_at"):
            term["expires_at"] = store.iso(store.add_months(store.parse_ts(term["expires_at"]),
                                                            plan["term_months"]))
        store.touch(term)
        # Reset the subscriber's cycle position and open a fresh cycle at index 1.
        subscriber["cycle_index"] = 1
        subscriber["cycles_rolled"] = 0
        subscriber["data_used_mb_cycle"] = 0
        subscriber["deprioritized_this_cycle"] = False
        subscriber["cycle_deprioritization_days"] = 0
        store.touch(subscriber)
        engine.open_term_cycles(term, store.now())
        for case in store.CASES.values():
            if case["subscriber_id"] == subscriber["id"] \
                    and case["topic_code"] == "RENEWAL_PRICING" \
                    and case["case_status"] != "CLOSED":
                case["case_status"] = "CLOSED"
                store.touch(case)
        engine.void_addons(subscriber)
        engine.sync_plan_status(plan)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("PrepaidTerm", term))

    @app.route("/carriers/prepaid-terms/<ident>/cancel", methods=["POST"])
    def cancel_term(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, CANCEL_ROLES)
        term = _get(ident)
        if role == "Subscriber":
            auth.require_owner(uid, role, term["subscriber_id"], "term")
        # Priority 7: an already-terminal term cannot be cancelled again.
        if term["term_status"] in ("REFUNDED", "VOIDED"):
            raise ApiError("ERR_TERM_ALREADY_TERMINAL")
        plan = store.PLANS.get(term["plan_id"])
        if plan is None:
            raise ApiError("ERR_PLAN_NOT_FOUND")
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        # Priority 25: an in-flight port blocks the cancel.
        for activation in store.ACTIVATIONS.values():
            if activation["subscriber_id"] == term["subscriber_id"] \
                    and activation["port_status"] == "SUBMITTED":
                raise ApiError("ERR_PORT_IN_FLIGHT")
        # Priority 26: a term is refundable only while starts_at is null.
        if term.get("starts_at") is not None:
            raise ApiError("ERR_TERM_ALREADY_STARTED")
        if term["term_status"] not in REFUNDABLE_STATUSES:
            raise ApiError("ERR_INVALID_STATE",
                           "a term in %s cannot be refunded" % term["term_status"])
        term["term_status"] = "REFUNDED"
        term["deferred_revenue_cents"] = 0
        term["earned_revenue_cents"] = 0
        store.touch(term)
        for activation in store.ACTIVATIONS.values():
            if activation["prepaid_term_id"] == term["id"]:
                activation["held_data_mb"] = 0
                store.touch(activation)
        subscriber = store.SUBSCRIBERS.get(term["subscriber_id"])
        if subscriber is not None and subscriber["subscriber_status"] == "PENDING_PORT":
            subscriber["allocation_status"] = "NONE"
            store.touch(subscriber)
        engine.sync_plan_status(plan)
        if agreement is not None:
            calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("PrepaidTerm", term))