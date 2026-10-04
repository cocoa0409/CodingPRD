"""Routes: shipments, itineraries, policies, claims, outcomes, chain breaks."""

from flask import Blueprint, request

import constants as C
from db import store, parse_iso
from errors import (
    err_invalid_request,
    err_invalid_state,
    err_center_suspended,
    err_organ_not_ready,
    err_flight_window,
    err_no_protection_policy,
    err_claim_exceeds_cap,
    err_segregation_of_duties,
    err_reconstruction_not_viable,
)
from middleware import (
    actor,
    get_body,
    req_field,
    opt_field,
    req_enum,
    opt_enum,
    paginate,
    get_or_404,
    require_center_match,
)
from response import success_response
from services import (
    chain_offers,
    cold_ischemia_hours,
    create_chain_break,
    recompute_center_active_chain_count,
    recompute_donor_travel,
    recompute_reputation,
    recompute_all_active_chain_counts,
    serialize_shipment,
    serialize_itinerary,
    serialize_policy,
    serialize_claim,
    serialize_outcome,
    serialize_chain_break,
    travel_estimate_cents,
)

bp = Blueprint("logistics", __name__, url_prefix="/nkr")

SHIPMENT_MODES = ("COMMERCIAL_FLIGHT", "CHARTER", "GROUND_COURIER")
CONTINGENCY_REASONS = ("WEATHER", "MECHANICAL", "ATC", "COURIER_BREAKDOWN")
CANCEL_REASONS = ("NONE", "CHAIN_BROKEN", "DONOR_UNAVAILABLE", "SCHEDULE_MOVED")
CLAIM_KINDS = ("COMPLICATION", "LOST_WAGES", "TRAVEL", "PRIORITY_KIDNEY")
OUTCOME_KINDS = ("SUCCESS", "DELAYED_GRAFT_FUNCTION", "PRIMARY_NON_FUNCTION", "REJECTED_30D", "FAILED")
FOLLOWUP_DAYS = (30, 90, 180, 365)


# ---------------------------------------------------------------------------
# Shipments
# ---------------------------------------------------------------------------

@bp.route("/shipments", methods=["POST"])
def create_shipment():
    actor("shipments", None)
    body = get_body()
    offer_id = req_field(body, "match_offer_id", str)
    offer = get_or_404(store.offers, offer_id)
    mode = req_enum(body, "shipment_mode", SHIPMENT_MODES)
    dep_s = req_field(body, "scheduled_departure_utc", str)
    arr_s = req_field(body, "scheduled_arrival_utc", str)
    try:
        dep = parse_iso(dep_s)
        arr = parse_iso(arr_s)
    except Exception:
        raise err_invalid_request("scheduled timestamps must be ISO-8601")
    max_hours = opt_field(body, "cold_ischemia_max_hours", int, C.COLD_ISCHEMIA_MAX_HOURS)
    from db import iso_z

    rec = {
        "match_offer_id": offer["id"],
        "origin_center_id": offer["donor_center_id"],
        "destination_center_id": offer["recipient_center_id"],
        "shipment_mode": mode,
        "scheduled_departure_utc": iso_z(dep),
        "scheduled_arrival_utc": iso_z(arr),
        "actual_departure_utc": None,
        "actual_arrival_utc": None,
        "cold_ischemia_hours_actual": None,
        "cold_ischemia_max_hours": max_hours,
        "cold_ischemia_violation": False,
        "shipment_state": "PLANNED",
        "contingency_reason": "NONE",
        "routing_sequence": 0,
    }
    store.insert(store.shipments, rec)
    return success_response(serialize_shipment(rec), 201)


@bp.route("/shipments", methods=["GET"])
def list_shipments():
    actor("shipments", None)
    rows = list(store.shipments.values())
    for param in ("match_offer_id", "origin_center_id", "destination_center_id", "shipment_state"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_shipment(r) for r in page], 200, meta)


@bp.route("/shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    actor("shipments", "get")
    s = get_or_404(store.shipments, shipment_id)
    return success_response(serialize_shipment(s))


@bp.route("/shipments/<shipment_id>/depart", methods=["POST"])
def depart_shipment(shipment_id):
    actor("shipments", "depart")
    s = get_or_404(store.shipments, shipment_id)
    offer = get_or_404(store.offers, s["match_offer_id"])
    origin = get_or_404(store.centers, s["origin_center_id"])
    if origin["participation_status"] != "ACTIVE":
        raise err_center_suspended()
    if s["shipment_state"] != "PLANNED":
        raise err_invalid_state()
    if offer["offer_state"] != "DONOR_SURGERY_DONE":
        raise err_organ_not_ready()
    s["shipment_state"] = "DEPARTED"
    s["actual_departure_utc"] = store.now_iso()
    store.touch(s)
    return success_response(serialize_shipment(s))


@bp.route("/shipments/<shipment_id>/delay", methods=["POST"])
def delay_shipment(shipment_id):
    actor("shipments", "delay")
    s = get_or_404(store.shipments, shipment_id)
    body = get_body()
    reason = req_enum(body, "contingency_reason", CONTINGENCY_REASONS)
    if s["shipment_state"] != "DEPARTED":
        raise err_invalid_state()
    s["shipment_state"] = "DELAYED"
    s["contingency_reason"] = reason
    store.touch(s)
    return success_response(serialize_shipment(s))


@bp.route("/shipments/<shipment_id>/reroute", methods=["POST"])
def reroute_shipment(shipment_id):
    actor("shipments", "reroute")
    s = get_or_404(store.shipments, shipment_id)
    if s["shipment_state"] not in ("DEPARTED", "DELAYED"):
        raise err_invalid_state()
    body = get_body()
    new_arr = req_field(body, "new_scheduled_arrival_utc", str)
    try:
        dt = parse_iso(new_arr)
    except Exception:
        raise err_invalid_request("new_scheduled_arrival_utc must be ISO-8601")
    from db import iso_z

    s["shipment_state"] = "REROUTED"
    s["routing_sequence"] = s.get("routing_sequence", 0) + 1
    s["scheduled_arrival_utc"] = iso_z(dt)
    store.touch(s)
    return success_response(serialize_shipment(s))


@bp.route("/shipments/<shipment_id>/deliver", methods=["POST"])
def deliver_shipment(shipment_id):
    actor("shipments", "deliver")
    s = get_or_404(store.shipments, shipment_id)
    offer = get_or_404(store.offers, s["match_offer_id"])
    dest = get_or_404(store.centers, s["destination_center_id"])
    origin = get_or_404(store.centers, s["origin_center_id"])
    if dest["participation_status"] == "SUSPENDED" or origin["participation_status"] == "SUSPENDED":
        raise err_center_suspended()
    if s["shipment_state"] not in ("DEPARTED", "DELAYED", "REROUTED"):
        raise err_invalid_state()
    s["shipment_state"] = "DELIVERED"
    s["actual_arrival_utc"] = store.now_iso()
    donor = store.donors.get(offer["donor_id"])
    neph_ts = donor.get("nephrectomy_completed_at_utc") if donor else None
    if neph_ts is None:
        neph_ts = donor["updated_at"] if donor else s["actual_arrival_utc"]
    s["cold_ischemia_hours_actual"] = cold_ischemia_hours(neph_ts, s["actual_arrival_utc"])
    s["cold_ischemia_violation"] = s["cold_ischemia_hours_actual"] > s["cold_ischemia_max_hours"]
    store.touch(s)

    # Successful delivery credits the origin center's shipped count.
    origin["shipped_organ_count"] = origin.get("shipped_organ_count", 0) + 1
    recompute_reputation(origin)
    store.touch(origin)

    if s["cold_ischemia_violation"]:
        dest["probed_cold_ischemia_violations"] = dest.get("probed_cold_ischemia_violations", 0) + 1
        recompute_reputation(dest)
        store.touch(dest)
        offer["offer_state"] = "OFFER_FAILED"
        offer["offer_failure_reason"] = "COLD_ISCHEMIA"
        store.touch(offer)
        chain = store.chains.get(offer["chain_id"])
        if chain is not None and chain["chain_state"] in ("SCHEDULED", "EXECUTING"):
            create_chain_break(chain, offer, "ORGAN_LOST_IN_TRANSIT")
    else:
        if offer["offer_state"] == "DONOR_SURGERY_DONE":
            offer["offer_state"] = "ORGAN_SHIPPED"
            store.touch(offer)
    return success_response(serialize_shipment(s))


@bp.route("/shipments/<shipment_id>/cancel", methods=["POST"])
def cancel_shipment(shipment_id):
    actor("shipments", "cancel")
    s = get_or_404(store.shipments, shipment_id)
    if s["shipment_state"] not in ("PLANNED", "DEPARTED", "DELAYED", "REROUTED"):
        raise err_invalid_state()
    was_departed = s["shipment_state"] in ("DEPARTED", "DELAYED", "REROUTED")
    s["shipment_state"] = "CANCELLED"
    store.touch(s)
    if was_departed:
        offer = store.offers.get(s["match_offer_id"])
        if offer is not None:
            chain = store.chains.get(offer["chain_id"])
            if chain is not None and chain["chain_state"] in ("SCHEDULED", "EXECUTING"):
                create_chain_break(chain, offer, "ORGAN_LOST_IN_TRANSIT")
            else:
                offer["offer_state"] = "OFFER_FAILED"
                offer["offer_failure_reason"] = "ORGAN_LOST_IN_TRANSIT"
                store.touch(offer)
    return success_response(serialize_shipment(s))


# ---------------------------------------------------------------------------
# Travel itineraries
# ---------------------------------------------------------------------------

@bp.route("/itineraries", methods=["POST"])
def create_itinerary():
    actor("itineraries", None)
    body = get_body()
    donor_id = req_field(body, "donor_id", str)
    get_or_404(store.donors, donor_id)
    origin = req_field(body, "origin_airport_code", str)
    dest = req_field(body, "destination_airport_code", str)
    dep_s = req_field(body, "depart_utc", str)
    arr_s = req_field(body, "arrive_utc", str)
    try:
        dep = parse_iso(dep_s)
        arr = parse_iso(arr_s)
    except Exception:
        raise err_invalid_request("flight timestamps must be ISO-8601")
    if not (arr > dep):
        raise err_invalid_request("arrive_utc must be after depart_utc")
    miles = req_field(body, "segment_miles", int)
    nights = req_field(body, "lodging_nights", int)
    if nights < 0 or nights > 7:
        raise err_invalid_request("lodging_nights must be 0..7")
    from db import iso_z

    rec = {
        "donor_id": donor_id,
        "origin_airport_code": origin,
        "destination_airport_code": dest,
        "depart_utc": iso_z(dep),
        "arrive_utc": iso_z(arr),
        "segment_miles": miles,
        "lodging_nights": nights,
        "itinerary_state": "DRAFT",
        "estimated_cost_cents": None,
        "cancelled_reason": "NONE",
    }
    store.insert(store.itineraries, rec)
    return success_response(serialize_itinerary(rec), 201)


@bp.route("/itineraries", methods=["GET"])
def list_itineraries():
    actor("itineraries", None)
    rows = list(store.itineraries.values())
    for param in ("donor_id", "itinerary_state"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_itinerary(r) for r in page], 200, meta)


@bp.route("/itineraries/<itinerary_id>", methods=["GET"])
def get_itinerary(itinerary_id):
    actor("itineraries", "get")
    it = get_or_404(store.itineraries, itinerary_id)
    return success_response(serialize_itinerary(it))


@bp.route("/itineraries/<itinerary_id>/confirm", methods=["POST"])
def confirm_itinerary(itinerary_id):
    actor("itineraries", "confirm")
    it = get_or_404(store.itineraries, itinerary_id)
    if it["itinerary_state"] != "DRAFT":
        raise err_invalid_state()
    donor = store.donors.get(it["donor_id"])
    it["estimated_cost_cents"] = travel_estimate_cents(
        donor["donor_kind"] if donor else "PAIRED",
        it["segment_miles"],
        it["lodging_nights"],
    )
    it["itinerary_state"] = "CONFIRMED"
    store.touch(it)
    if donor is not None:
        recompute_donor_travel(donor)
    return success_response(serialize_itinerary(it))


@bp.route("/itineraries/<itinerary_id>/cancel", methods=["POST"])
def cancel_itinerary(itinerary_id):
    actor("itineraries", "cancel")
    it = get_or_404(store.itineraries, itinerary_id)
    if it["itinerary_state"] != "CONFIRMED":
        raise err_invalid_state()
    if store.now() >= parse_iso(it["depart_utc"]):
        raise err_flight_window()
    body = get_body()
    reason = opt_enum(body, "cancelled_reason", CANCEL_REASONS, "NONE")
    it["itinerary_state"] = "CANCELLED"
    it["cancelled_reason"] = reason
    store.touch(it)
    donor = store.donors.get(it["donor_id"])
    if donor is not None:
        recompute_donor_travel(donor)
    return success_response(serialize_itinerary(it))


@bp.route("/itineraries/<itinerary_id>/reimburse", methods=["POST"])
def reimburse_itinerary(itinerary_id):
    actor("itineraries", "reimburse")
    it = get_or_404(store.itineraries, itinerary_id)
    if it["itinerary_state"] != "CONFIRMED":
        raise err_invalid_state()
    if store.now() < parse_iso(it["arrive_utc"]):
        raise err_flight_window()
    donor = store.donors.get(it["donor_id"])
    policy = None
    if donor is not None and donor.get("protection_policy_id"):
        policy = store.policies.get(donor["protection_policy_id"])
    if policy is None or policy["policy_state"] != "ACTIVE":
        raise err_no_protection_policy()
    it["itinerary_state"] = "REIMBURSED"
    store.touch(it)
    claim = {
        "policy_id": policy["id"],
        "donor_id": donor["id"],
        "claim_kind": "TRAVEL",
        "requested_amount_cents": it["estimated_cost_cents"],
        "approved_amount_cents": it["estimated_cost_cents"],
        "claim_state": "APPROVED",
        "adjudicator_user_id": None,
        "submitter_user_id": None,
        "submitted_at_utc": store.now_iso(),
        "resolved_at_utc": store.now_iso(),
        "denial_reason": None,
    }
    store.insert(store.claims, claim)
    policy["travel_reimbursed_cents"] = policy.get("travel_reimbursed_cents", 0) + it["estimated_cost_cents"]
    store.touch(policy)
    return success_response(serialize_itinerary(it))


# ---------------------------------------------------------------------------
# Policies
# ---------------------------------------------------------------------------

@bp.route("/policies", methods=["GET"])
def list_policies():
    actor("policies", None)
    rows = list(store.policies.values())
    for param in ("donor_id", "policy_state"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_policy(r) for r in page], 200, meta)


@bp.route("/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    actor("policies", "get")
    p = get_or_404(store.policies, policy_id)
    return success_response(serialize_policy(p))


# ---------------------------------------------------------------------------
# Claims
# ---------------------------------------------------------------------------

@bp.route("/donors/<donor_id>/claims", methods=["POST"])
def submit_claim(donor_id):
    user_id, role = actor("donors", "claims")
    donor = get_or_404(store.donors, donor_id)
    body = get_body()
    kind = req_enum(body, "claim_kind", CLAIM_KINDS)
    amount = None
    if kind != "PRIORITY_KIDNEY":
        amount = req_field(body, "requested_amount_cents", int)
        if amount <= 0:
            raise err_invalid_request("requested_amount_cents must be > 0")
    else:
        amount = opt_field(body, "requested_amount_cents", int, 0)
    policy = None
    if donor.get("protection_policy_id"):
        policy = store.policies.get(donor["protection_policy_id"])
    if policy is None or policy["policy_state"] != "ACTIVE":
        raise err_no_protection_policy()
    rec = {
        "policy_id": policy["id"],
        "donor_id": donor["id"],
        "claim_kind": kind,
        "requested_amount_cents": amount,
        "approved_amount_cents": None,
        "claim_state": "SUBMITTED",
        "adjudicator_user_id": None,
        "submitter_user_id": user_id,
        "submitted_at_utc": store.now_iso(),
        "resolved_at_utc": None,
        "denial_reason": None,
    }
    store.insert(store.claims, rec)
    return success_response(serialize_claim(rec), 201)


@bp.route("/claims", methods=["GET"])
def list_claims():
    actor("claims", None)
    rows = list(store.claims.values())
    for param in ("policy_id", "claim_kind", "claim_state"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_claim(r) for r in page], 200, meta)


@bp.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    actor("claims", "get")
    c = get_or_404(store.claims, claim_id)
    return success_response(serialize_claim(c))


@bp.route("/claims/<claim_id>/start-review", methods=["POST"])
def start_review(claim_id):
    user_id, role = actor("claims", "start-review")
    c = get_or_404(store.claims, claim_id)
    if c["claim_state"] != "SUBMITTED":
        raise err_invalid_state()
    c["claim_state"] = "UNDER_REVIEW"
    c["adjudicator_user_id"] = user_id
    store.touch(c)
    return success_response(serialize_claim(c))


def _bucket_headroom(policy, kind):
    if kind == "COMPLICATION":
        return policy["covered_complication_max_cents"] - policy.get("complications_paid_cents", 0)
    if kind == "LOST_WAGES":
        return policy["covered_lost_wages_max_cents"] - policy.get("lost_wages_paid_cents", 0)
    if kind == "TRAVEL":
        return None  # unlimited bucket
    return None


def _debit_bucket(policy, kind, amount):
    if kind == "COMPLICATION":
        policy["complications_paid_cents"] = policy.get("complications_paid_cents", 0) + amount
        donor = store.donors.get(policy["donor_id"])
        if donor is not None:
            donor["complications_recorded"] = donor.get("complications_recorded", 0) + 1
            store.touch(donor)
    elif kind == "LOST_WAGES":
        policy["lost_wages_paid_cents"] = policy.get("lost_wages_paid_cents", 0) + amount
    elif kind == "TRAVEL":
        policy["travel_reimbursed_cents"] = policy.get("travel_reimbursed_cents", 0) + amount
    store.touch(policy)


def _check_sod(claim, user_id):
    if claim.get("submitter_user_id") is not None and claim["submitter_user_id"] == user_id:
        raise err_segregation_of_duties()


@bp.route("/claims/<claim_id>/approve", methods=["POST"])
def approve_claim(claim_id):
    user_id, role = actor("claims", "approve")
    c = get_or_404(store.claims, claim_id)
    if c["claim_state"] != "UNDER_REVIEW":
        raise err_invalid_state()
    _check_sod(c, user_id)
    policy = get_or_404(store.policies, c["policy_id"])
    if c["claim_kind"] != "PRIORITY_KIDNEY":
        headroom = _bucket_headroom(policy, c["claim_kind"])
        if headroom is not None and c["requested_amount_cents"] > headroom:
            raise err_claim_exceeds_cap()
        c["approved_amount_cents"] = c["requested_amount_cents"]
        _debit_bucket(policy, c["claim_kind"], c["requested_amount_cents"])
    else:
        if not policy.get("priority_kidney_claim_available", False):
            raise err_claim_exceeds_cap()
        policy["priority_kidney_claim_available"] = False
        store.touch(policy)
        c["approved_amount_cents"] = 0
    c["claim_state"] = "APPROVED"
    c["adjudicator_user_id"] = user_id
    c["resolved_at_utc"] = store.now_iso()
    store.touch(c)
    return success_response(serialize_claim(c))


@bp.route("/claims/<claim_id>/partial-approve", methods=["POST"])
def partial_approve_claim(claim_id):
    user_id, role = actor("claims", "partial-approve")
    c = get_or_404(store.claims, claim_id)
    if c["claim_state"] != "UNDER_REVIEW":
        raise err_invalid_state()
    body = get_body()
    amount = req_field(body, "approved_amount_cents", int)
    if not (0 < amount < (c["requested_amount_cents"] or 0)):
        raise err_invalid_request("approved_amount_cents must be 0 < a < requested")
    _check_sod(c, user_id)
    policy = get_or_404(store.policies, c["policy_id"])
    c["approved_amount_cents"] = amount
    _debit_bucket(policy, c["claim_kind"], amount)
    c["claim_state"] = "PARTIALLY_APPROVED"
    c["adjudicator_user_id"] = user_id
    c["resolved_at_utc"] = store.now_iso()
    store.touch(c)
    return success_response(serialize_claim(c))


@bp.route("/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    user_id, role = actor("claims", "deny")
    c = get_or_404(store.claims, claim_id)
    if c["claim_state"] != "UNDER_REVIEW":
        raise err_invalid_state()
    _check_sod(c, user_id)
    body = get_body()
    reason = opt_field(body, "denial_reason", str, None)
    c["claim_state"] = "DENIED"
    c["denial_reason"] = reason
    c["adjudicator_user_id"] = user_id
    c["resolved_at_utc"] = store.now_iso()
    store.touch(c)
    return success_response(serialize_claim(c))


@bp.route("/claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    user_id, role = actor("claims", "pay")
    c = get_or_404(store.claims, claim_id)
    if c["claim_state"] not in ("APPROVED", "PARTIALLY_APPROVED"):
        raise err_invalid_state()
    c["claim_state"] = "PAID"
    store.touch(c)
    return success_response(serialize_claim(c))


# ---------------------------------------------------------------------------
# Transplant outcomes
# ---------------------------------------------------------------------------

@bp.route("/outcomes", methods=["POST"])
def create_outcome():
    actor("outcomes", None)
    body = get_body()
    offer_id = req_field(body, "match_offer_id", str)
    get_or_404(store.offers, offer_id)
    kind = req_enum(body, "outcome_kind", OUTCOME_KINDS)
    followup = req_field(body, "followup_days", int)
    if followup not in FOLLOWUP_DAYS:
        raise err_invalid_request("followup_days must be one of 30, 90, 180, 365")
    rec = {
        "match_offer_id": offer_id,
        "outcome_kind": kind,
        "reported_at_utc": store.now_iso(),
        "followup_days": followup,
        "outcome_state": "REPORTED",
        "attributed_center_id": None,
    }
    store.insert(store.outcomes, rec)
    return success_response(serialize_outcome(rec), 201)


@bp.route("/outcomes", methods=["GET"])
def list_outcomes():
    actor("outcomes", None)
    rows = list(store.outcomes.values())
    for param in ("match_offer_id", "outcome_kind", "outcome_state", "attributed_center_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_outcome(r) for r in page], 200, meta)


@bp.route("/outcomes/<outcome_id>", methods=["GET"])
def get_outcome(outcome_id):
    actor("outcomes", "get")
    o = get_or_404(store.outcomes, outcome_id)
    return success_response(serialize_outcome(o))


@bp.route("/outcomes/<outcome_id>/attribute", methods=["POST"])
def attribute_outcome(outcome_id):
    actor("outcomes", "attribute")
    oc = get_or_404(store.outcomes, outcome_id)
    if oc["outcome_state"] != "REPORTED":
        raise err_invalid_state()
    offer = get_or_404(store.offers, oc["match_offer_id"])
    body = get_body()
    cid = opt_field(body, "attributed_center_id", str, None)
    if cid is None:
        cid = offer["recipient_center_id"]
    else:
        get_or_404(store.centers, cid)
    oc["attributed_center_id"] = cid
    oc["outcome_state"] = "ATTRIBUTED_TO_CENTER"
    store.touch(oc)
    if oc["outcome_kind"] == "FAILED":
        center = store.centers.get(cid)
        if center is not None:
            center["failed_outcome_count"] = center.get("failed_outcome_count", 0) + 1
            recompute_reputation(center)
            store.touch(center)
    return success_response(serialize_outcome(oc))


@bp.route("/outcomes/<outcome_id>/appeal", methods=["POST"])
def appeal_outcome(outcome_id):
    user_id, role = actor("outcomes", "appeal")
    oc = get_or_404(store.outcomes, outcome_id)
    if oc["outcome_state"] != "ATTRIBUTED_TO_CENTER":
        raise err_invalid_state()
    require_center_match(user_id, role, oc["attributed_center_id"])
    oc["outcome_state"] = "APPEALED"
    store.touch(oc)
    return success_response(serialize_outcome(oc))


@bp.route("/outcomes/<outcome_id>/resolve-appeal", methods=["POST"])
def resolve_appeal(outcome_id):
    actor("outcomes", "resolve-appeal")
    oc = get_or_404(store.outcomes, outcome_id)
    if oc["outcome_state"] != "APPEALED":
        raise err_invalid_state()
    body = get_body()
    new_cid = opt_field(body, "new_attributed_center_id", str, None)
    if new_cid is not None:
        get_or_404(store.centers, new_cid)
    old_cid = oc["attributed_center_id"]
    if new_cid is not None and new_cid != old_cid:
        oc["attributed_center_id"] = new_cid
        if oc["outcome_kind"] == "FAILED":
            old_center = store.centers.get(old_cid)
            new_center = store.centers.get(new_cid)
            if old_center is not None:
                old_center["failed_outcome_count"] = max(0, old_center.get("failed_outcome_count", 0) - 1)
                recompute_reputation(old_center)
                store.touch(old_center)
            if new_center is not None:
                new_center["failed_outcome_count"] = new_center.get("failed_outcome_count", 0) + 1
                recompute_reputation(new_center)
                store.touch(new_center)
    oc["outcome_state"] = "FINAL"
    store.touch(oc)
    return success_response(serialize_outcome(oc))


@bp.route("/outcomes/<outcome_id>/finalize", methods=["POST"])
def finalize_outcome(outcome_id):
    actor("outcomes", "finalize")
    oc = get_or_404(store.outcomes, outcome_id)
    if oc["outcome_state"] != "ATTRIBUTED_TO_CENTER":
        raise err_invalid_state()
    oc["outcome_state"] = "FINAL"
    store.touch(oc)
    return success_response(serialize_outcome(oc))


# ---------------------------------------------------------------------------
# Chain break events
# ---------------------------------------------------------------------------

@bp.route("/chain-breaks", methods=["GET"])
def list_chain_breaks():
    actor("chain-breaks", None)
    rows = list(store.chain_breaks.values())
    for param in ("chain_id", "event_state", "trigger_kind", "broken_at_offer_id", "bridge_donor_id"):
        v = request.args.get(param)
        if v is not None:
            rows = [r for r in rows if str(r.get(param)) == v]
    page, meta = paginate(rows)
    return success_response([serialize_chain_break(r) for r in page], 200, meta)


@bp.route("/chain-breaks/<event_id>", methods=["GET"])
def get_chain_break(event_id):
    actor("chain-breaks", "get")
    ev = get_or_404(store.chain_breaks, event_id)
    return success_response(serialize_chain_break(ev))


@bp.route("/chain-breaks/<event_id>/reconstruct", methods=["POST"])
def reconstruct_chain_break(event_id):
    actor("chain-breaks", "reconstruct")
    ev = get_or_404(store.chain_breaks, event_id)
    if ev["event_state"] != "CASCADED":
        raise err_invalid_state()
    # A new executed run must exist that was created after this event.
    viable = any(
        r["run_state"] in ("EXECUTED", "PUBLISHED") and r["created_at"] >= ev["created_at"]
        for r in store.chain_runs.values()
    )
    if not viable:
        raise err_reconstruction_not_viable()
    ev["event_state"] = "RECONSTRUCTED"
    store.touch(ev)
    return success_response(serialize_chain_break(ev))
