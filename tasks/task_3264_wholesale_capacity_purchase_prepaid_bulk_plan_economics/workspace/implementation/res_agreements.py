"""CapacityAgreement resource: create, read, lifecycle, cost book (M1)."""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]
PLANNER = ["CapacityPlanner"]
SUMMARY_ROLES = ["CapacityPlanner", "SupportAgent", "PlatformAdmin"]

CREATE_REQUIRED = ["host_network_name", "state_code", "data_rate_microcents_per_mb",
                   "voice_rate_microcents_per_min", "sms_rate_microcents_per_msg",
                   "committed_data_mb", "committed_voice_minutes", "committed_sms_messages"]
CREATE_OPTIONAL = ["congestion_active"]


def _get(ident):
    return auth.get_or_404("agreements", ident, "ERR_AGREEMENT_NOT_FOUND")


def register(app):
    @app.route("/carriers/capacity-agreements", methods=["POST"])
    def create_agreement():
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        data = auth.body()
        auth.check_fields(data, CREATE_REQUIRED, CREATE_OPTIONAL)
        committed = {}
        for name in ["committed_data_mb", "committed_voice_minutes", "committed_sms_messages"]:
            committed[name] = auth.integer(data, name)
            if committed[name] < 1:
                raise ApiError("ERR_INVALID_REQUEST", "%s must be at least 1" % name)
        state_code = auth.string(data, "state_code")
        if len(state_code) != 2 or state_code.upper() != state_code:
            raise ApiError("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
        congestion_active = data.get("congestion_active", False)
        if not isinstance(congestion_active, bool):
            raise ApiError("ERR_INVALID_REQUEST", "congestion_active must be a boolean")
        record = store.stamp({
            "host_network_name": auth.string(data, "host_network_name"),
            "state_code": state_code,
            "data_rate_microcents_per_mb": auth.integer(data, "data_rate_microcents_per_mb"),
            "voice_rate_microcents_per_min": auth.integer(data, "voice_rate_microcents_per_min"),
            "sms_rate_microcents_per_msg": auth.integer(data, "sms_rate_microcents_per_msg"),
            "committed_data_mb": committed["committed_data_mb"],
            "committed_voice_minutes": committed["committed_voice_minutes"],
            "committed_sms_messages": committed["committed_sms_messages"],
            "agreement_status": "DRAFT",
            "congestion_active": congestion_active,
            "congestion_index": 0,
            "allocated_data_mb": 0,
            "remaining_data_mb": committed["committed_data_mb"],
            # PRD 3.1: the cost book "is resolved on demand rather than stored per
            # order", so a freshly registered agreement has no resolved reading yet.
            # The forward-looking reading at zero allocation is 0, which is what the
            # row reports until the resolve-purchase capability is exercised.
            "resolved_purchase_cost_microcents": 0,
        })
        store.AGREEMENTS[record["id"]] = record
        return respond.created(store.serialize("CapacityAgreement", record))

    @app.route("/carriers/capacity-agreements/<ident>", methods=["GET"])
    def read_agreement(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        record = _get(ident)
        return respond.ok(store.serialize("CapacityAgreement", record))

    def _lifecycle(ident, allowed_from):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        record = _get(ident)
        data = auth.body()
        auth.version_check(record, data.get("expected_CapacityAgreement_version"))
        if record["agreement_status"] not in allowed_from:
            raise ApiError("ERR_INVALID_STATE",
                           "agreement is %s" % record["agreement_status"])
        return record

    @app.route("/carriers/capacity-agreements/<ident>/activate", methods=["POST"])
    def activate_agreement(ident):
        record = _lifecycle(ident, {"DRAFT"})
        offered = [p for p in store.PLANS.values()
                   if p["agreement_id"] == record["id"] and p["plan_status"] == "OFFERED"]
        if record["committed_data_mb"] < 1 or record["committed_voice_minutes"] < 1 \
                or record["committed_sms_messages"] < 1:
            raise ApiError("ERR_INVALID_STATE", "committed volumes must each be at least 1")
        if not offered:
            raise ApiError("ERR_INVALID_STATE", "at least one offered plan is required")
        record["agreement_status"] = "ACTIVE"
        calcs.settlement_clearing(record)
        return respond.ok(store.serialize("CapacityAgreement", record))

    @app.route("/carriers/capacity-agreements/<ident>/suspend", methods=["POST"])
    def suspend_agreement(ident):
        record = _lifecycle(ident, {"ACTIVE"})
        record["agreement_status"] = "SUSPENDED"
        # Endpoint side effect: a manual suspend pins remaining_data_mb to 0.
        calcs.settlement_clearing(record)
        return respond.ok(store.serialize("CapacityAgreement", record))

    @app.route("/carriers/capacity-agreements/<ident>/reactivate", methods=["POST"])
    def reactivate_agreement(ident):
        record = _lifecycle(ident, {"SUSPENDED"})
        if calcs.allocated_data_mb(record) > record["committed_data_mb"]:
            raise ApiError("ERR_INVALID_STATE", "over-allocation is not yet resolved")
        record["agreement_status"] = "ACTIVE"
        calcs.settlement_clearing(record)
        return respond.ok(store.serialize("CapacityAgreement", record))

    @app.route("/carriers/capacity-agreements/<ident>/close", methods=["POST"])
    def close_agreement(ident):
        record = _lifecycle(ident, {"ACTIVE", "SUSPENDED"})
        plans = [p for p in store.PLANS.values() if p["agreement_id"] == record["id"]]
        blocked = (calcs.PLAN_BLOCKS_CLOSE_FROM_ACTIVE if record["agreement_status"] == "ACTIVE"
                   else calcs.PLAN_BLOCKS_CLOSE_FROM_SUSPENDED)
        if record["agreement_status"] == "ACTIVE":
            if any(p["plan_status"] == "DRAFT" for p in plans):
                raise ApiError("ERR_INVALID_STATE", "a plan is still in DRAFT")
        for plan in plans:
            if engine.plan_has_terms(plan["id"], blocked):
                raise ApiError("ERR_INVALID_STATE", "a term is still pre-activation")
        record["agreement_status"] = "CLOSED"
        store.touch(record)
        for plan in plans:
            if plan["plan_status"] != "RETIRED":
                plan["plan_status"] = "RETIRED"
                store.touch(plan)
        return respond.ok(store.serialize("CapacityAgreement", record))

    @app.route("/carriers/capacity-agreements/<ident>/resolve-purchase", methods=["POST"])
    def resolve_purchase(ident):
        record = _lifecycle(ident, {"DRAFT", "ACTIVE", "SUSPENDED"})
        data_leg, committed_cost = calcs.committed_volume_cost(record)
        projected_mb, projected_cost = calcs.forward_overage(record)
        resolved = committed_cost + projected_cost
        record["resolved_purchase_cost_microcents"] = resolved
        store.touch(record)
        payload = {
            "resolved_purchase_cost_microcents": resolved,
            # PRD 3.1 names this reading twice — "the projected overage
            # `projected_overage_mb`" and "the returned projection also reports the
            # projected overage volume as `projected_overage_data_mb`" — so both
            # spellings are exposed with the same value.
            "projected_overage_mb": projected_mb,
            "projected_overage_data_mb": projected_mb,
            "projected_overage_cost_microcents": projected_cost,
            "committed_volume_cost_microcents": committed_cost,
            "monthly_committed_cost_microcents": committed_cost,
            "data_volume_cost_microcents": data_leg,
            "marginal_tier_rate_microcents": calcs.marginal_tier_rate(record),
        }
        return respond.ok(payload)

    @app.route("/carriers/capacity-agreements/<ident>/usage-summary", methods=["GET"])
    def usage_summary(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUMMARY_ROLES)
        record = _get(ident)
        data_leg, committed_cost = calcs.committed_volume_cost(record)
        _, as_incurred_overage = calcs.chronological_overage(record)
        payload = {
            "as_incurred_cost_microcents": committed_cost + as_incurred_overage,
            "as_incurred_overage_cost_microcents": as_incurred_overage,
            "committed_volume_cost_microcents": committed_cost,
            "data_volume_cost_microcents": data_leg,
            "retroactive_volume_cost_microcents": calcs.retroactive_volume_cost(record),
            "allocated_data_mb": calcs.allocated_data_mb(record),
            "remaining_data_mb": record["committed_data_mb"] - calcs.allocated_data_mb(record),
            "breakage_rate_ppm": calcs.breakage_rate_ppm(record),
            "congestion_index": calcs.congestion_index(record),
            "congestion_active": bool(record.get("congestion_active")),
        }
        return respond.ok(payload)