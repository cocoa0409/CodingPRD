"""Activation resource: request, provision, complete, fail, porting (M5, M6, M8).

Two independent state dimensions live on one row: activation_status and
port_status. Each transition here touches only the dimension it owns.
"""

import auth
import calcs
import engine
import respond
import store
from errors import ApiError
from store import add_days, add_months, iso, now, parse_ts, stamp, touch

ALL_ROLES = ["CapacityPlanner", "SupportAgent", "FulfillmentOperator", "PlatformAdmin",
             "Subscriber", "RetailPartner"]
SUBSCRIBER = ["Subscriber"]
AGENT = ["SupportAgent"]
PLANNER = ["CapacityPlanner"]
COMPLETE_ROLES = ["Subscriber", "SupportAgent"]

CREATE_REQUIRED = ["subscriber_id", "prepaid_term_id", "activation_channel"]
CREATE_OPTIONAL = ["retail_partner_id", "porting_msisdn", "losing_carrier",
                   "account_number_last4"]

RESERVABLE_STATUSES = ("AVAILABLE", "RESERVED_PREPAID", "SHIPPED")


def _get(ident):
    return auth.get_or_404("activations", ident, "ERR_ACTIVATION_NOT_FOUND")


def _subscriber_of(activation):
    subscriber = store.SUBSCRIBERS.get(activation["subscriber_id"])
    if subscriber is None:
        raise ApiError("ERR_SUBSCRIBER_NOT_FOUND")
    return subscriber


def _term_of(activation):
    term = store.TERMS.get(activation["prepaid_term_id"])
    if term is None:
        raise ApiError("ERR_TERM_NOT_FOUND")
    return term


def _plan_of(activation):
    term = _term_of(activation)
    plan = store.PLANS.get(term["plan_id"])
    if plan is None:
        raise ApiError("ERR_PLAN_NOT_FOUND")
    return plan


def _agreement_of(activation):
    plan = _plan_of(activation)
    agreement = store.AGREEMENTS.get(plan["agreement_id"])
    if agreement is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND")
    return agreement


def _find_block(state_code, partner_id=None, partner_only=False, include_reserved_full=False):
    """First block scoped to the state that still has a free unit.

    SIM media is state-scoped absolutely: a block in another state is never a
    candidate. The partner hint only orders candidates, it never broadens them,
    so a partner with no state-matched block simply finds nothing.

    `include_reserved_full` additionally admits a block whose aggregate reservation
    total has already reached its unit_count. That block carries no free unit — the
    caller still refuses it with `ERR_SIM_INVENTORY_DEPLETED` — but it must be found
    for the refusal to be distinguishable from "this state owns no media at all",
    which is the separate `ERR_NO_ACTIVATABLE_SIM_MEDIA` condition of PRD 3.8.
    """
    def servable(block):
        return (block["inventory_status"] in RESERVABLE_STATUSES
                and (block.get("unit_count") or 0) - (block.get("reserved_count") or 0) >= 1)

    def reserved_full(block):
        return (block["inventory_status"] in RESERVABLE_STATUSES
                and (block.get("unit_count") or 0) - (block.get("reserved_count") or 0) <= 0)

    # PRD 3.8: a block "reaches DEPLETED on its own once every unit has shipped, that
    # is once unit_count minus reserved_count equals 0". DEPLETED is the observable
    # form of the reserved-full reading.
    def depleted(block):
        return block["inventory_status"] == "DEPLETED"

    if include_reserved_full:
        candidates = [block for block in store.INVENTORY.values()
                      if block["state_code"] == state_code
                      and (servable(block) or reserved_full(block) or depleted(block))]
    else:
        candidates = [block for block in store.INVENTORY.values()
                      if block["state_code"] == state_code and servable(block)]
    if partner_only and partner_id:
        preferred = [b for b in candidates if b.get("retail_partner_id") == partner_id]
        others = [b for b in candidates if b.get("retail_partner_id") != partner_id]
        candidates = preferred + others
    if not candidates:
        return None
    # Prefer a block that can actually serve this reservation; fall back to a
    # reserved-full one only so the caller can raise ERR_SIM_INVENTORY_DEPLETED
    # rather than the no-media error.
    candidates.sort(key=lambda b: (0 if servable(b) else 1,
                                   b.get("created_at") or "", b["id"]))
    return candidates[0]


def _state_is_reserved_full(state_code):
    """A block scoped to this state whose aggregate reservation total has reached its
    unit_count.

    PRD 3.8 separates two refusals at the provisioning step: a reservation
    "attempted against a block with no free unit" is `ERR_SIM_INVENTORY_DEPLETED`
    (409), while a provisioning request that "cannot find any block in the
    subscriber's state with a free unit" is `ERR_NO_ACTIVATABLE_SIM_MEDIA` (422).
    A state that still holds such a block is the reserved-full reading.
    """
    return any(block["state_code"] == state_code
               and block["inventory_status"] in ("AVAILABLE", "RESERVED_PREPAID", "SHIPPED",
                                                 "DEPLETED")
               and (block.get("unit_count") or 0) - (block.get("reserved_count") or 0) <= 0
               for block in store.INVENTORY.values())


def _has_media(state_code):
    return _find_block(state_code) is not None


def _check_partner_authorization(partner, state_code):
    if partner["partner_status"] in ("DEFLECTED", "SUSPENDED"):
        raise ApiError("ERR_PARTNER_SUSPENDED")
    if state_code not in partner["partner_state_codes"]:
        raise ApiError("ERR_PARTNER_NOT_AUTHORIZED_FOR_STATE")


def _release_hold(activation, subscriber):
    activation["held_data_mb"] = 0
    touch(activation)


def _ensure_plan_active(plan):
    if plan["plan_status"] == "OFFERED":
        plan["plan_status"] = "ACTIVE"
        touch(plan)


def register(app):
    @app.route("/carriers/activations", methods=["POST"])
    def create_activation():
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        data = auth.body()
        auth.check_fields(data, CREATE_REQUIRED, CREATE_OPTIONAL)
        auth.require_owner(uid, role, auth.string(data, "subscriber_id"), "subscriber")
        # Priority 5: body foreign keys, in the order the input list declares them.
        subscriber = auth.get_or_404("subscribers", auth.string(data, "subscriber_id"),
                                     "ERR_SUBSCRIBER_NOT_FOUND")
        term = auth.get_or_404("terms", auth.string(data, "prepaid_term_id"),
                               "ERR_TERM_NOT_FOUND")
        partner = None
        if data.get("retail_partner_id") is not None:
            partner = auth.get_or_404("partners", auth.string(data, "retail_partner_id"),
                                      "ERR_PARTNER_NOT_FOUND")
        plan = store.PLANS.get(term["plan_id"])
        if plan is None:
            raise ApiError("ERR_PLAN_NOT_FOUND")
        agreement = store.AGREEMENTS.get(plan["agreement_id"])
        if agreement is None:
            raise ApiError("ERR_AGREEMENT_NOT_FOUND")
        channel = auth.string(data, "activation_channel")
        if channel not in ("DIGITAL", "RETAIL_PARTNER"):
            raise ApiError("ERR_INVALID_REQUEST", "activation_channel must be DIGITAL or RETAIL_PARTNER")
        # Priority 6: the parent term must be PURCHASED; a term parked in GRACE may
# also retry its activation, which is how the grace path is re-driven.
        if term["term_status"] not in ("PURCHASED", "GRACE"):
            raise ApiError("ERR_INVALID_STATE",
                           "term is %s" % term["term_status"])
        for other in store.ACTIVATIONS.values():
            if other["prepaid_term_id"] == term["id"] \
                    and other["activation_status"] not in ("COMPLETED", "FAILED"):
                raise ApiError("ERR_INVALID_STATE", "this term already has a live activation")
        # Priority 8: no capacity may be allocated against a suspended agreement.
        if agreement["agreement_status"] == "SUSPENDED":
            raise ApiError("ERR_AGREEMENT_SUSPENDED")
        # Priority 9: a closed agreement or retired plan cannot sell or extend.
        if agreement["agreement_status"] == "CLOSED":
            raise ApiError("ERR_AGREEMENT_CLOSED")
        if plan["plan_status"] == "RETIRED":
            raise ApiError("ERR_PLAN_RETIRED")
        # Priority 10: capacity admission. PRD 3.5 already committed this term's allotment
        # to the subscriber at purchase (the subscriber moves to HELD), so the
        # activation gate must not count the same allotment twice: a subscriber already
        # holding it adds nothing further to the balance.
        held = calcs.allocated_data_mb(agreement)
        already_counted = (subscriber["allocation_status"] in calcs.OCCUPYING_ALLOCATION
                           and calcs.current_term(subscriber["id"]) is term)
        projected = held if already_counted else held + plan["data_allotment_mb"]
        if projected > calcs.oversale_ceiling(agreement):
            raise ApiError("ERR_INSUFFICIENT_AGREEMENT_CAPACITY")
        # Priority 12: retail-partner authorization for the state.
        if channel == "RETAIL_PARTNER" and partner is not None:
            _check_partner_authorization(partner, subscriber["state_code"])
        # Priority 13: activatable SIM media in the subscriber's state.
        if not _has_media(subscriber["state_code"]):
            raise ApiError("ERR_NO_ACTIVATABLE_SIM_MEDIA")
        # Priority 24: retail-channel consistency.
        if channel == "RETAIL_PARTNER" and partner is None:
            raise ApiError("ERR_RETAIL_CHANNEL_MISMATCH",
                           "retail_partner_id is required for a RETAIL_PARTNER activation")
        if channel == "DIGITAL" and partner is not None:
            raise ApiError("ERR_RETAIL_CHANNEL_MISMATCH",
                           "retail_partner_id is not allowed for a DIGITAL activation")
        record = stamp({
            "subscriber_id": subscriber["id"],
            "prepaid_term_id": term["id"],
            "retail_partner_id": partner["id"] if partner else None,
            "activation_channel": channel,
            "activation_status": "REQUESTED",
            "port_status": "NONE",
            "porting_msisdn": data.get("porting_msisdn"),
            "losing_carrier": data.get("losing_carrier"),
            "account_number_last4": data.get("account_number_last4"),
            "rejection_code": None,
            "held_data_mb": 0,
            "provisioned_msisdn": None,
            "accepted_msisdn": None,
        })
        store.ACTIVATIONS[record["id"]] = record
        if term["term_status"] == "PURCHASED":
            term["term_status"] = "AWAITING_ACTIVATION"
            touch(term)
        return respond.created(store.serialize("Activation", record))

    @app.route("/carriers/activations/<ident>", methods=["GET"])
    def read_activation(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        return respond.ok(store.serialize("Activation", _get(ident)))

    @app.route("/carriers/activations", methods=["GET"])
    def list_activations():
        uid, role = auth.actor()
        auth.require_role(uid, role, ALL_ROLES)
        from flask import request
        args = request.args
        records = list(store.ACTIVATIONS.values())
        for field in ("subscriber_id", "prepaid_term_id", "retail_partner_id",
                      "activation_status", "port_status"):
            wanted = args.get(field)
            if wanted:
                records = [a for a in records if a.get(field) == wanted]
        return respond.listing("Activation", store.by_created(records),
                               args.get("limit"), args.get("offset"))

    @app.route("/carriers/activations/<ident>/provision", methods=["POST"])
    def provision_activation(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, PLANNER)
        activation = _get(ident)
        if activation["activation_status"] in ("COMPLETED", "FAILED"):
            raise ApiError("ERR_ACTIVATION_ALREADY_TERMINAL")
        if activation["activation_status"] != "REQUESTED":
            raise ApiError("ERR_INVALID_STATE",
                           "activation is %s" % activation["activation_status"])
        subscriber = _subscriber_of(activation)
        plan = _plan_of(activation)
        agreement = _agreement_of(activation)
        partner = None
        if activation["activation_channel"] == "RETAIL_PARTNER":
            partner = store.PARTNERS.get(activation.get("retail_partner_id"))
            if partner is None:
                raise ApiError("ERR_PARTNER_NOT_FOUND")
            _check_partner_authorization(partner, subscriber["state_code"])
        # A block with a free unit is the fast path; a reserved-full block is still returned
        # so the refusal can be the aggregate one rather than the no-media one.
        block = _find_block(subscriber["state_code"],
                            partner["id"] if partner else None,
                            partner_only=partner is not None,
                            include_reserved_full=True)
        if block is None or (block["unit_count"] - block["reserved_count"]) < 1:
            if _state_is_reserved_full(subscriber["state_code"]) or block is not None:
                raise ApiError("ERR_SIM_INVENTORY_DEPLETED")
            raise ApiError("ERR_NO_ACTIVATABLE_SIM_MEDIA")
        block["reserved_count"] = (block.get("reserved_count") or 0) + 1
        block["reserved_for_activation_id"] = activation["id"]
        block["inventory_status"] = "RESERVED_PREPAID"
        activation["activation_status"] = "PROVISIONED"
        activation["provisioned_msisdn"] = subscriber["msisdn"]
        # PRD 3.8: provisioning *reserves* the unit on either channel and, on the retail
# channel only, "additionally sets the block's shipment_channel to
# RETAIL_PARTNER_STOCK and copies the receiving partner's shipment_sla_days onto
# the block". The move to SHIPPED belongs to the separate shipment release, so the
# block stays RESERVED_PREPAID here and reserved_count holds the aggregate.
        block["shipment_channel"] = ("RETAIL_PARTNER_STOCK" if partner is not None
                                     else "DIRECT_TO_SUBSCRIBER")
        block["shipment_sla_days"] = (partner.get("shipment_sla_days")
                                      if partner is not None else None)
        activation["_block_id"] = block["id"]
        # M8 to_DEPLETED: reaches DEPLETED once reserved_count reaches unit_count.
        if (block.get("reserved_count") or 0) >= block["unit_count"]:
            block["inventory_status"] = "DEPLETED"
        touch(block)
        subscriber["allocation_status"] = "HELD"
        touch(subscriber)
        touch(activation)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/activations/<ident>/complete", methods=["POST"])
    def complete_activation(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, COMPLETE_ROLES)
        activation = _get(ident)
        if role == "Subscriber":
            auth.require_owner(uid, role, activation["subscriber_id"], "activation")
        if activation["activation_status"] in ("COMPLETED", "FAILED"):
            raise ApiError("ERR_ACTIVATION_ALREADY_TERMINAL")
        subscriber = _subscriber_of(activation)
        term = _term_of(activation)
        plan = _plan_of(activation)
        agreement = _agreement_of(activation)
        if activation["activation_status"] != "PROVISIONED":
            raise ApiError("ERR_INVALID_STATE",
                           "activation is %s" % activation["activation_status"])
        if term["term_status"] != "AWAITING_ACTIVATION":
            raise ApiError("ERR_INVALID_STATE", "term is %s" % term["term_status"])
        port = activation["port_status"]
        if port not in ("NONE", "CANCELLED", "CONFIRMED", "REJECTED"):
            raise ApiError("ERR_INVALID_STATE", "port is %s" % port)
        activation["activation_status"] = "COMPLETED"
        if port == "CONFIRMED":
            activation["accepted_msisdn"] = activation.get("porting_msisdn")
            activation["port_status"] = "NONE"
        else:
            activation["accepted_msisdn"] = activation.get("provisioned_msisdn")
        activation["held_data_mb"] = 0
        touch(activation)
        subscriber["subscriber_status"] = "ACTIVE"
        subscriber["allocation_status"] = "ALLOCATED"
        subscriber["cycle_index"] = 1
        subscriber["data_used_mb_cycle"] = 0
        subscriber["deprioritized_this_cycle"] = False
        subscriber["cycle_deprioritization_days"] = 0
        touch(subscriber)
        started = now()
        term["term_status"] = "ACTIVE"
        term["starts_at"] = iso(started)
        term["expires_at"] = iso(add_months(started, plan["term_months"]))
        touch(term)
        engine.open_term_cycles(term, started)
        _ensure_plan_active(plan)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/activations/<ident>/fail", methods=["POST"])
    def fail_activation(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        activation = _get(ident)
        data = auth.body()
        auth.check_fields(data, ["failure_reason"])
        auth.string(data, "failure_reason")
        if activation["activation_status"] in ("COMPLETED", "FAILED"):
            raise ApiError("ERR_ACTIVATION_ALREADY_TERMINAL")
        subscriber = _subscriber_of(activation)
        term = _term_of(activation)
        agreement = _agreement_of(activation)
        status = activation["activation_status"]
        if status == "REQUESTED":
            if _has_media(subscriber["state_code"]):
                raise ApiError("ERR_INVALID_STATE",
                               "activatable SIM media still exists for this state")
            engine.release_reservation(_reserving_block(activation))
        elif status == "PROVISIONED":
            block = store.INVENTORY.get(activation.get("_block_id")) or _reserving_block(activation)
            if block is not None:
                status = block["inventory_status"]
                if status in ("SHIPPED", "DELIVERED"):
                    # PRD 3.7: the media was released to the partner and the shipment
                    # window elapsed without delivery — the block goes back to RETURNED
                    # and its reserved units are reopened.
                    sla = block.get("shipment_sla_days")
                    shipped_at = parse_ts(block.get("_shipped_at"))
                    if sla is None or shipped_at is None or now() < add_days(shipped_at, sla):
                        raise ApiError("ERR_INVALID_STATE", "the shipment window has not elapsed")
                    block["inventory_status"] = "RETURNED"
                    block["reserved_count"] = (block.get("reserved_count") or 0) + (block.get("units_shipped") or 0)
                    block["units_shipped"] = 0
                    block["reserved_for_activation_id"] = None
                    touch(block)
                else:
                    # The media is still held or already back: PRD 3.8's returned-media
                    # path fails the waiting activation, releasing the reservation.
                    engine.release_reservation(block)
            else:
                engine.release_reservation(_reserving_block(activation))
        else:
            raise ApiError("ERR_INVALID_STATE", "activation is %s" % status)
        activation["activation_status"] = "FAILED"
        touch(activation)
        subscriber["subscriber_status"] = "GRACE"
        # PRD 3.7: "its recompute of allocated_data_mb and remaining_data_mb is what
        # releases the hold" — the failed term commits nothing, so the subscriber
        # stops counting toward the agreement's allocated volume.
        subscriber["allocation_status"] = "NONE"
        touch(subscriber)
        # PRD 3.7: "Both paths move the activation to FAILED, send the subscriber to
        # GRACE, and push the term back to PURCHASED". The term returns to its
        # pre-activation state and parks there — "a purchased term cannot go live until
        # it is activated" — so it commits no capacity while the subscriber waits.
        term["term_status"] = "PURCHASED"
        touch(term)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/activations/<ident>/submit-port", methods=["POST"])
    def submit_port(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        activation = _get(ident)
        auth.require_owner(uid, role, activation["subscriber_id"], "activation")
        data = auth.body()
        auth.check_fields(data, ["porting_msisdn", "losing_carrier", "account_number_last4"])
        porting_msisdn = auth.string(data, "porting_msisdn")
        losing_carrier = auth.string(data, "losing_carrier")
        last4 = auth.string(data, "account_number_last4")
        if activation["port_status"] in ("REJECTED", "CANCELLED"):
            raise ApiError("ERR_PORT_ALREADY_TERMINAL")
        if activation["activation_status"] not in ("PROVISIONED", "COMPLETED"):
            raise ApiError("ERR_INVALID_STATE",
                           "activation is %s" % activation["activation_status"])
        if activation["port_status"] != "NONE":
            raise ApiError("ERR_INVALID_STATE", "port is %s" % activation["port_status"])
        # Priority 16: no other activation already holds this losing-carrier account.
        for other in store.ACTIVATIONS.values():
            if other["id"] == activation["id"]:
                continue
            if other["port_status"] != "SUBMITTED":
                continue
            if other.get("losing_carrier") == losing_carrier \
                    and other.get("account_number_last4") == last4:
                raise ApiError("ERR_MSISDN_ALREADY_IN_FLIGHT")
        # Priority 17: the submitted number must be the subscriber's own.
        subscriber = _subscriber_of(activation)
        if activation["activation_status"] == "PROVISIONED" \
                and subscriber["msisdn"] != porting_msisdn:
            raise ApiError("ERR_MSISDN_MISMATCH")
        plan = _plan_of(activation)
        agreement = _agreement_of(activation)
        activation["port_status"] = "SUBMITTED"
        activation["porting_msisdn"] = porting_msisdn
        activation["losing_carrier"] = losing_carrier
        activation["account_number_last4"] = last4
        activation["held_data_mb"] = plan["data_allotment_mb"]
        touch(activation)
        subscriber["allocation_status"] = "HELD"
        touch(subscriber)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/activations/<ident>/confirm-port", methods=["POST"])
    def confirm_port(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        activation = _get(ident)
        if activation["port_status"] in ("REJECTED", "CANCELLED"):
            raise ApiError("ERR_PORT_ALREADY_TERMINAL")
        if activation["port_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "port is %s" % activation["port_status"])
        subscriber = _subscriber_of(activation)
        agreement = _agreement_of(activation)
        activation["port_status"] = "CONFIRMED"
        touch(activation)
        subscriber["subscriber_status"] = "ACTIVE"
        subscriber["allocation_status"] = "ALLOCATED"
        touch(subscriber)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/activations/<ident>/reject-port", methods=["POST"])
    def reject_port(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        activation = _get(ident)
        data = auth.body()
        auth.check_fields(data, ["rejection_code"])
        rejection_code = auth.string(data, "rejection_code")
        if activation["port_status"] in ("REJECTED", "CANCELLED"):
            raise ApiError("ERR_PORT_ALREADY_TERMINAL")
        port = activation["port_status"]
        if port not in ("SUBMITTED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", "port is %s" % port)
        if port == "CONFIRMED" and activation["activation_status"] == "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", "a settled port cannot be rejected")
        subscriber = _subscriber_of(activation)
        agreement = _agreement_of(activation)
        activation["port_status"] = "REJECTED"
        activation["rejection_code"] = rejection_code
        activation["held_data_mb"] = 0
        touch(activation)
        if port == "SUBMITTED":
            if activation["activation_status"] == "PROVISIONED":
                # PRD 3.7: rejection "sends the subscriber to GRACE"; the term is still
                # AWAITING_ACTIVATION and still holds its allotment, so the balance is
                # unchanged and only the in-flight hold is cleared.
                subscriber["subscriber_status"] = "GRACE"
                subscriber["allocation_status"] = "HELD"
            else:
                # PRD 3.7: "on a live activation (COMPLETED) the subscriber stays
                # ACTIVE with allocation_status ALLOCATED because the live term still
                # holds its capacity".
                subscriber["subscriber_status"] = "ACTIVE"
                subscriber["allocation_status"] = "ALLOCATED"
        else:
            # PRD 3.7: "A confirmed port can also be rejected while the activation is
            # not COMPLETED, which clears the hold and sets allocation_status to NONE."
            if activation["activation_status"] == "COMPLETED":
                subscriber["subscriber_status"] = "ACTIVE"
                subscriber["allocation_status"] = "ALLOCATED"
            else:
                subscriber["allocation_status"] = "NONE"
        touch(subscriber)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/activations/<ident>/cancel-port", methods=["POST"])
    def cancel_port(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        activation = _get(ident)
        auth.require_owner(uid, role, activation["subscriber_id"], "activation")
        if activation["port_status"] in ("REJECTED", "CANCELLED"):
            raise ApiError("ERR_PORT_ALREADY_TERMINAL")
        if activation["port_status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", "port is %s" % activation["port_status"])
        subscriber = _subscriber_of(activation)
        agreement = _agreement_of(activation)
        activation["port_status"] = "CANCELLED"
        activation["held_data_mb"] = 0
        touch(activation)
        # PRD 3.7: cancelling a port "clears held_data_mb, leaving allocation_status at HELD
        # when the activation is still PROVISIONED but at ALLOCATED when it is
        # COMPLETED" — the term keeps its allotment either way.
        if activation["activation_status"] == "PROVISIONED":
            subscriber["allocation_status"] = "HELD"
        else:
            subscriber["allocation_status"] = "ALLOCATED"
        touch(subscriber)
        calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Activation", activation))

    @app.route("/carriers/subscribers/<ident>/resume_activation", methods=["POST"])
    def resume_activation(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, AGENT)
        subscriber = auth.get_or_404("subscribers", ident, "ERR_SUBSCRIBER_NOT_FOUND")
        term = calcs.current_term(subscriber["id"])
        if term is None or term["term_status"] != "PURCHASED":
            raise ApiError("ERR_INVALID_STATE", "the subscriber's term is not in PURCHASED")
        activation = None
        for candidate in store.ACTIVATIONS.values():
            if candidate["subscriber_id"] == subscriber["id"] \
                    and candidate["activation_status"] in ("REQUESTED", "PROVISIONED"):
                activation = candidate
                break
        if activation is None:
            raise ApiError("ERR_INVALID_STATE",
                           "no activation is REQUESTED or PROVISIONED for this subscriber")
        subscriber["subscriber_status"] = "PENDING_PORT"
        subscriber["allocation_status"] = "HELD"
        touch(subscriber)
        term["term_status"] = "AWAITING_ACTIVATION"
        touch(term)
        plan = store.PLANS.get(term["plan_id"])
        if plan is not None:
            agreement = store.AGREEMENTS.get(plan["agreement_id"])
            if agreement is not None:
                calcs.settlement_clearing(agreement)
        return respond.ok(store.serialize("Subscriber", subscriber))

    @app.route("/carriers/subscribers/<ident>/keep_requested_msisdn", methods=["POST"])
    def keep_requested_msisdn(ident):
        uid, role = auth.actor()
        auth.require_role(uid, role, SUBSCRIBER)
        subscriber = auth.get_or_404("subscribers", ident, "ERR_SUBSCRIBER_NOT_FOUND")
        auth.require_owner(uid, role, subscriber["id"], "subscriber")
        for activation in store.ACTIVATIONS.values():
            if activation["subscriber_id"] != subscriber["id"]:
                continue
            if activation["port_status"] == "REJECTED" and activation.get("porting_msisdn"):
                activation["accepted_msisdn"] = activation["porting_msisdn"]
                activation["held_data_mb"] = 0
                subscriber["msisdn"] = activation["porting_msisdn"]
                touch(activation)
        touch(subscriber)
        return respond.ok(store.serialize("Subscriber", subscriber))


def _reserving_block(activation):
    for block in store.INVENTORY.values():
        if block.get("reserved_for_activation_id") == activation["id"]:
            return block
    for block in store.INVENTORY.values():
        if block.get("retail_partner_id") == activation.get("retail_partner_id") \
                and block.get("shipment_channel") == "RETAIL_PARTNER_STOCK":
            return block
    return None