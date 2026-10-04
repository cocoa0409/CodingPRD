"""RetailPartner and SimInventory resources (M7, M8)."""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError
from store import add_days, iso, now, parse_ts, touch

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]
INVENTORY_LIST_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator",
                        "PlatformAdmin", "RetailPartner"]
PLANNER = ["CapacityPlanner"]
PLANNER_OR_PARTNER = ["CapacityPlanner", "RetailPartner"]
FULFILLMENT = ["FulfillmentOperator"]

PARTNER_REQUIRED = ["partner_name", "partner_state_codes"]
PARTNER_OPTIONAL = ["shipment_sla_days"]
INVENTORY_REQUIRED = ["state_code", "sim_media_type", "unit_count"]
INVENTORY_OPTIONAL = ["retail_partner_id"]

MEDIA_TYPES = ("PHYSICAL_SIM", "ESIM_PROFILE")
RETURNABLE = ("RESERVED_PREPAID", "SHIPPED", "DELIVERED", "DEPLETED")


def _partner(ident):
    return auth.get_or_404("partners", ident, "ERR_PARTNER_NOT_FOUND")


def _inventory(ident):
    return auth.get_or_404("inventory", ident, "ERR_SIM_INVENTORY_NOT_FOUND")


def register(app):
    @app.route("/carriers/retail-partners", methods=["POST"])
    def create_partner():
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        data = auth.body()
        auth.check_fields(data, PARTNER_REQUIRED, PARTNER_OPTIONAL)
        name = auth.string(data, "partner_name")
        for other in store.PARTNERS.values():
            if other["partner_name"] == name:
                raise ApiError("ERR_INVALID_REQUEST", "partner_name must be unique")
        states = data["partner_state_codes"]
        if not isinstance(states, list) or not states:
            raise ApiError("ERR_INVALID_REQUEST", "partner_state_codes must be a non-empty list")
        for code in states:
            if not isinstance(code, str) or len(code) != 2 or code.upper() != code:
                raise ApiError("ERR_INVALID_REQUEST", "state codes must be two uppercase letters")
        sla = data.get("shipment_sla_days", 2)
        if isinstance(sla, bool) or not isinstance(sla, int) or sla < 0:
            raise ApiError("ERR_INVALID_REQUEST", "shipment_sla_days must be a non-negative integer")
        record = store.stamp({
            "partner_name": name,
            "partner_status": "ACTIVE",
            "partner_state_codes": list(states),
            "shipment_sla_days": sla,
        })
        store.PARTNERS[record["id"]] = record
        return respond.created(store.serialize("RetailPartner", record))

    @app.route("/carriers/retail-partners/<ident>", methods=["GET"])
    def read_partner(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        return respond.ok(store.serialize("RetailPartner", _partner(ident)))

    @app.route("/carriers/retail-partners/<ident>/suspend", methods=["POST"])
    def suspend_partner(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        partner = _partner(ident)
        data = auth.body()
        auth.version_check(partner, data.get("expected_RetailPartner_version"))
        if partner["partner_status"] == "SUSPENDED":
            raise ApiError("ERR_INVALID_STATE", "partner is already SUSPENDED")
        partner["partner_status"] = "SUSPENDED"
        touch(partner)
        return respond.ok(store.serialize("RetailPartner", partner))

    @app.route("/carriers/retail-partners/<ident>/reinstate", methods=["POST"])
    def reinstate_partner(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        partner = _partner(ident)
        data = auth.body()
        auth.version_check(partner, data.get("expected_RetailPartner_version"))
        if partner["partner_status"] != "DEFLECTED":
            raise ApiError("ERR_INVALID_STATE", "only a DEFLECTED partner can be reinstated")
        at_dt = now()
        for block in store.INVENTORY.values():
            if block.get("retail_partner_id") != partner["id"]:
                continue
            if block["inventory_status"] != "SHIPPED":
                continue
            sla = block.get("shipment_sla_days")
            shipped_at = parse_ts(block.get("_shipped_at"))
            if sla is not None and shipped_at is not None and at_dt >= add_days(shipped_at, sla):
                raise ApiError("ERR_INVALID_STATE", "a shipment is still past its SLA window")
        partner["partner_status"] = "ACTIVE"
        touch(partner)
        return respond.ok(store.serialize("RetailPartner", partner))

    @app.route("/carriers/sim-inventories", methods=["POST"])
    def create_inventory():
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER_OR_PARTNER)
        data = auth.body()
        auth.check_fields(data, INVENTORY_REQUIRED, INVENTORY_OPTIONAL)
        state_code = auth.string(data, "state_code")
        if len(state_code) != 2 or state_code.upper() != state_code:
            raise ApiError("ERR_INVALID_REQUEST", "state_code must be two uppercase letters")
        media = auth.string(data, "sim_media_type")
        if media not in MEDIA_TYPES:
            raise ApiError("ERR_INVALID_REQUEST", "sim_media_type must be PHYSICAL_SIM or ESIM_PROFILE")
        units = auth.integer(data, "unit_count")
        if units < 1:
            raise ApiError("ERR_INVALID_REQUEST", "unit_count must be at least 1")
        partner_id = data.get("retail_partner_id")
        partner = None
        if partner_id is not None:
            partner = auth.get_or_404("partners", auth.string(data, "retail_partner_id"),
                                      "ERR_PARTNER_NOT_FOUND")
        # Priority 3: a RetailPartner may register only its own blocks.
        if role == "RetailPartner" and partner_id != uid:
            raise ApiError("ERR_NOT_RESOURCE_OWNER",
                           "a retail partner may register only its own inventory")
        # Priority 12: partner authorization for the state.
        if partner is not None:
            if partner["partner_status"] in ("DEFLECTED", "SUSPENDED"):
                raise ApiError("ERR_PARTNER_SUSPENDED")
            if state_code not in partner["partner_state_codes"]:
                raise ApiError("ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE")
        record = store.stamp({
            "retail_partner_id": partner["id"] if partner else None,
            "reserved_for_activation_id": None,
            "sim_media_type": media,
            "state_code": state_code,
            "unit_count": units,
            "inventory_status": "AVAILABLE",
            "reserved_count": 0,
            "shipment_channel": None,
            "units_shipped": 0,
            "shipment_sla_days": None,
        })
        store.INVENTORY[record["id"]] = record
        return respond.created(store.serialize("SimInventory", record))

    @app.route("/carriers/sim-inventories/<ident>", methods=["GET"])
    def read_inventory(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        return respond.ok(store.serialize("SimInventory", _inventory(ident)))

    @app.route("/carriers/sim-inventories", methods=["GET"])
    def list_inventory():
        uid, role = auth.actor()
        auth.require_role(uid, role, INVENTORY_LIST_ROLES)
        from flask import request
        args = request.args
        records = list(store.INVENTORY.values())
        for field in ("state_code", "sim_media_type", "inventory_status",
                      "retail_partner_id", "reserved_for_activation_id"):
            wanted = args.get(field)
            if wanted:
                records = [b for b in records if b.get(field) == wanted]
        return respond.listing("SimInventory", store.by_created(records),
                               args.get("limit"), args.get("offset"))

    @app.route("/carriers/sim-inventories/<ident>/return", methods=["POST"])
    def return_inventory(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, FULFILLMENT)
        block = _inventory(ident)
        data = auth.body()
        auth.version_check(block, data.get("expected_SimInventory_version"))
        if block["inventory_status"] not in RETURNABLE:
            raise ApiError("ERR_INVALID_STATE",
                           "block is %s" % block["inventory_status"])
        activation_id = block.get("reserved_for_activation_id")
        # PRD 3.8: returning "moves it to RETURNED, reopens reserved_count by
        # units_shipped, and zeroes units_shipped".
        block["inventory_status"] = "RETURNED"
        block["reserved_count"] = (block.get("reserved_count") or 0) + (block.get("units_shipped") or 0)
        block["units_shipped"] = 0
        block["reserved_for_activation_id"] = None
        touch(block)
        # The media can no longer serve the waiting activation (M8 to_RETURNED).
        activation = store.ACTIVATIONS.get(activation_id) if activation_id else None
        if activation is None:
            # The reservation had already migrated into units_shipped, so match
            # the block's most recent PROVISIONED activation instead.
            candidates = [a for a in store.ACTIVATIONS.values()
                          if a.get("_block_id") == block["id"]
                          and a["activation_status"] == "PROVISIONED"]
            candidates.sort(key=lambda a: (a.get("created_at") or "", a["id"]))
            activation = candidates[-1] if candidates else None
        if activation is not None and activation["activation_status"] == "PROVISIONED":
            activation["activation_status"] = "FAILED"
            touch(activation)
            subscriber = store.SUBSCRIBERS.get(activation["subscriber_id"])
            if subscriber is not None:
                subscriber["subscriber_status"] = "GRACE"
                # PRD 3.8: the media "can no longer serve the waiting activation", so
                # the failed term releases the allotment it was holding.
                subscriber["allocation_status"] = "NONE"
                touch(subscriber)
            term = store.TERMS.get(activation["prepaid_term_id"])
            if term is not None:
                # PRD 3.8: returning the media fails the activation "exactly as the
                # failure path of 3.7 does", so the term goes back to its purchased state.
                term["term_status"] = "PURCHASED"
                touch(term)
            plan = store.PLANS.get(term["plan_id"]) if term else None
            agreement = store.AGREEMENTS.get(plan["agreement_id"]) if plan else None
            if agreement is not None:
                calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("SimInventory", block))