"""Plan resource: create, read, list, offer and withdraw (M2)."""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]
PLANNER = ["CapacityPlanner"]

CREATE_REQUIRED = ["agreement_id", "plan_code", "term_months", "intro_price_cents",
                   "renewal_price_cents", "data_allotment_mb", "voice_allotment_min",
                   "sms_allotment_msg"]
# A derived field: supplying it is ignored, but it must still be a known field.
DERIVED_FIELDS = ["deprioritization_threshold_mb"]


def _get(ident):
    return auth.get_or_404("plans", ident, "ERR_PLAN_NOT_FOUND")


def register(app):
    @app.route("/carriers/plans", methods=["POST"])
    def create_plan():
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        data = auth.body()
        auth.check_fields(data, CREATE_REQUIRED, DERIVED_FIELDS)
        # Priority 5: body foreign keys in input order.
        agreement = auth.get_or_404("agreements", auth.string(data, "agreement_id"),
                                    "ERR_AGREEMENT_NOT_FOUND")
        term_months = auth.integer(data, "term_months")
        intro = auth.integer(data, "intro_price_cents")
        renewal = auth.integer(data, "renewal_price_cents")
        allotment = auth.integer(data, "data_allotment_mb")
        if intro < 1 or allotment < 1:
            raise ApiError("ERR_INVALID_REQUEST", "intro price and data allotment must be at least 1")
        if term_months not in (3, 6, 12) or renewal <= intro:
            raise ApiError("ERR_INVALID_PLAN_TERM",
                           "term_months must be 3, 6 or 12 and renewal price must exceed the intro price")
        plan_code = auth.string(data, "plan_code")
        for other in store.PLANS.values():
            if other["agreement_id"] == agreement["id"] and other["plan_code"] == plan_code:
                raise ApiError("ERR_INVALID_REQUEST", "plan_code must be unique within the agreement")
        record = store.stamp({
            "agreement_id": agreement["id"],
            "plan_code": plan_code,
            "term_months": term_months,
            "intro_price_cents": intro,
            "renewal_price_cents": renewal,
            "data_allotment_mb": allotment,
            "voice_allotment_min": auth.integer(data, "voice_allotment_min"),
            "sms_allotment_msg": auth.integer(data, "sms_allotment_msg"),
            "deprioritization_threshold_mb": None,
            "plan_status": "DRAFT",
        })
        store.PLANS[record["id"]] = record
        calcs.settlement_clearing(agreement)
        return respond.created(store.serialize("Plan", record))

    @app.route("/carriers/plans/<ident>", methods=["GET"])
    def read_plan(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        record = _get(ident)
        return respond.ok(store.serialize("Plan", record))

    @app.route("/carriers/plans", methods=["GET"])
    def list_plans():
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        args = request_args()
        records = list(store.PLANS.values())
        if args.get("agreement_id"):
            records = [p for p in records if p["agreement_id"] == args["agreement_id"]]
        if args.get("plan_status"):
            records = [p for p in records if p["plan_status"] == args["plan_status"]]
        return respond.listing("Plan", store.by_created(records), args.get("limit"), args.get("offset"))

    @app.route("/carriers/plans/<ident>/offer", methods=["POST"])
    def offer_plan(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        plan = _get(ident)
        data = auth.body()
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        auth.version_check(agreement, data.get("expected_CapacityAgreement_version"))
        # Priority 6: the plan's own lifecycle state.
        if plan["plan_status"] != "DRAFT":
            raise ApiError("ERR_INVALID_STATE", "only a DRAFT plan can be offered")
        # Priority 9: a closed agreement or a retired plan cannot be sold.
        if agreement["agreement_status"] == "CLOSED":
            raise ApiError("ERR_AGREEMENT_CLOSED")
        if agreement["agreement_status"] not in ("DRAFT", "ACTIVE"):
            raise ApiError("ERR_INVALID_STATE", "the agreement is not DRAFT or ACTIVE")
        # Priority 19: plan term and price validity.
        if plan["term_months"] not in (3, 6, 12) or plan["renewal_price_cents"] <= plan["intro_price_cents"]:
            raise ApiError("ERR_INVALID_PLAN_TERM")
        plan["plan_status"] = "OFFERED"
        plan["deprioritization_threshold_mb"] = plan["data_allotment_mb"]
        store.touch(plan)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Plan", plan))

    @app.route("/carriers/plans/<ident>/withdraw", methods=["POST"])
    def withdraw_plan(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        plan = _get(ident)
        data = auth.body()
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        auth.version_check(agreement, data.get("expected_CapacityAgreement_version"))
        if plan["plan_status"] != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", "only an OFFERED plan can be withdrawn")
        if engine.plan_has_terms(plan["id"], calcs.PLAN_BLOCKS_WITHDRAW):
            raise ApiError("ERR_INVALID_STATE", "a live term still holds this plan")
        plan["plan_status"] = "DRAFT"
        store.touch(plan)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Plan", plan))


def request_args():
    from flask import request
    return request.args