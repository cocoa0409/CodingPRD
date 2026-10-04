"""Claim adjudication, member share and the reversal route (PRD 3.9)."""

from flask import request

from body import body, opt, require
from bp import api
from clock import (
    APPEAL_WINDOW_DAYS,
    REVERSAL_WINDOW_DAYS,
    parse_dt,
)
from db import db
from errors import APIError
from helpers import (
    bundle_of_preauth,
    plan_of_preauth,
    recompute_bundle,
    recompute_pharmacy_from_claims,
    recompute_preauth_consumption,
)
from calculations import (
    claim_allowed_amount,
    member_accumulator_before,
    member_cost_share,
)
from listing import apply_filters, ordered, paginate
from lookups import claim as claim_lookup
from middleware import require_member_ownership, resolve_actor
from response import ok, created
from serializers import serialize


def _order_for_claim(claim):
    """The specialty order the claim settles, if one exists on the same authorization."""
    for order in db.all("medication_orders"):
        if order["preauthorization_id"] != claim["preauthorization_id"]:
            continue
        if order["member_id"] != claim["member_id"]:
            continue
        if order["pharmacy_status"] in ("DISPENSING", "DISPENSED", "SHIPPED", "DELIVERED"):
            return order
    return None


def _provisional_share(claim, billed_cents, member_cost_share_pct):
    return member_cost_share(
        billed_cents,
        member_cost_share_pct or 0,
        claim["member_accumulator_before_cents"],
        claim["service_category"],
        "PROVISIONAL",
    )


@api.route("/claims", methods=["POST"])
def create_claim():
    resolve_actor()
    data = body()
    member_id = require(data, "member_id")
    preauth_id = require(data, "preauthorization_id")
    cycle_id = opt(data, "treatment_cycle_id")
    service_category = require(data, "service_category")
    if service_category not in ("CLINIC_BUNDLE", "MEDICATION", "LAB", "STORAGE", "DONOR_MATERIAL", "SURROGACY_FEE"):
        raise APIError("ERR_INVALID_REQUEST", "service_category is outside its declared enumeration.")
    billed_cents = require(data, "billed_cents")
    service_date_iso = require(data, "service_date_iso")

    # Priority 6: every foreign key supplied in the body must resolve.
    member = db.find("members", member_id)
    if member is None:
        raise APIError("ERR_NOT_FOUND", "The member_id does not resolve.")
    pa = db.find("preauthorizations", preauth_id)
    if pa is None:
        raise APIError("ERR_NOT_FOUND", "The preauthorization_id does not resolve.")
    if cycle_id is not None:
        cycle = db.find("treatment_cycles", cycle_id)
        if cycle is None:
            raise APIError("ERR_NOT_FOUND", "The treatment_cycle_id does not resolve.")

    # Priority 8: the authorization's validity window must cover the service instant.
    service_instant = parse_dt(service_date_iso)
    start = parse_dt(pa["effective_from"]) if pa["review_status"] == "APPROVED" else None
    end = parse_dt(pa["effective_to"]) if pa["review_status"] == "APPROVED" else None
    if start is None or end is None or not (start <= service_instant < end):
        raise APIError("ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE",
                       "The billed service instant is outside the authorization's validity window.")

    # Priority 15: a pinned bundle price and a positive billed charge.
    plan = plan_of_preauth(db, pa)
    if not plan or not plan.get("selected_bundle_price_cents"):
        raise APIError("ERR_BUNDLE_PRICE_UNPINNED", "No bundle price has been pinned for this plan.")
    if not isinstance(billed_cents, int) or billed_cents <= 0:
        raise APIError("ERR_BUNDLE_PRICE_UNPINNED", "The billed charge must be a positive amount.")

    # The claim is adjudicated against an approved authorization.
    if pa["review_status"] != "APPROVED":
        raise APIError("ERR_INVALID_STATE", "The authorization is not APPROVED.")

    accumulator = member_accumulator_before(db, member_id)

    row = db.common()
    row.update({
        "_collection": "claims",
        "_service_date": service_instant,
        "_paid_at": None,
        "_adjudicated_at": None,
        "member_id": member_id,
        "preauthorization_id": preauth_id,
        "treatment_cycle_id": cycle_id,
        "service_category": service_category,
        "billed_cents": billed_cents,
        "claim_status": "RECEIVED",
        "allowed_cents": 0,
        "member_cost_share_cents": 0,
        "plan_paid_cents": 0,
        "member_accumulator_before_cents": accumulator,
        "member_accumulator_after_cents": accumulator,
        "adjudication_basis": None,
        "pended_reason": None,
        # PRD 2.1: the decision actor is recorded on the resource. It is seeded with
        # the submitting operator so a later appeal cannot be decided by that same
        # identity.
        "_last_decision_actor": (request.headers.get("X-User-ID") or None),
    })
    row["member_cost_share_cents"] = _provisional_share(row, billed_cents, pa.get("member_cost_share_pct"))
    db.add(row)
    return created(serialize("claims", row))


@api.route("/claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    actor = resolve_actor()
    row = claim_lookup(claim_id)
    require_member_ownership(actor, row["member_id"])
    return ok(serialize("claims", row))


@api.route("/claims", methods=["GET"])
def list_claims():
    actor = resolve_actor()
    rows = ordered(db.all("claims"))
    if actor.role == "Member":
        rows = [r for r in rows if r["member_id"] == actor.user_id]
    rows = apply_filters(rows, {
        "member_id": "member_id",
        "preauthorization_id": "preauthorization_id",
        "treatment_cycle_id": "treatment_cycle_id",
        "service_category": "service_category",
        "claim_status": "claim_status",
    })
    return paginate(rows, "claims")


def _adjudicate(claim, pa, plan, actor_user_id=None):
    if claim["service_category"] == "MEDICATION":
        order = _order_for_claim(claim)
        medication_plan_paid = order["plan_paid_cents"] if order is not None else claim["billed_cents"]
    else:
        medication_plan_paid = 0

    allowed, basis = claim_allowed_amount(
        claim["service_category"],
        claim["billed_cents"],
        plan.get("selected_bundle_price_cents") or 0,
        medication_plan_paid,
    )

    claim["allowed_cents"] = allowed
    claim["adjudication_basis"] = basis
    claim["member_cost_share_cents"] = member_cost_share(
        allowed,
        pa.get("member_cost_share_pct") or 0,
        claim["member_accumulator_before_cents"],
        claim["service_category"],
        "FINAL",
    )
    claim["plan_paid_cents"] = max(0, allowed - claim["member_cost_share_cents"])
    claim["member_accumulator_after_cents"] = (
        claim["member_accumulator_before_cents"] + claim["member_cost_share_cents"]
    )
    claim["claim_status"] = "ADJUDICATED"
    claim["_adjudicated_at"] = db.now()
    claim["pended_reason"] = None
    if actor_user_id is not None:
        claim["_last_decision_actor"] = actor_user_id
    db.touch(claim)


@api.route("/claims/<claim_id>/adjudicate", methods=["POST"])
def adjudicate(claim_id):
    actor = resolve_actor()
    claim = claim_lookup(claim_id)
    data = request.get_json(silent=True) or {}

    if claim["claim_status"] not in ("RECEIVED", "PENDED"):
        raise APIError("ERR_INVALID_STATE", "The claim is not RECEIVED or PENDED.")

    if claim["claim_status"] == "PENDED" and not data.get("service_date_iso"):
        raise APIError("ERR_INVALID_STATE", "A pended claim requires a resolving service_date_iso.")

    pa = db.find("preauthorizations", claim["preauthorization_id"])
    if pa is None or pa["review_status"] != "APPROVED":
        raise APIError("ERR_INVALID_STATE", "The claim's authorization is not APPROVED.")

    plan = plan_of_preauth(db, pa)

    service_instant = parse_dt(data["service_date_iso"]) if data.get("service_date_iso") else claim.get("_service_date")
    start = parse_dt(pa["effective_from"])
    end = parse_dt(pa["effective_to"])
    if start is None or end is None or not (start <= service_instant < end):
        raise APIError("ERR_PREAUTH_WINDOW_OUTSIDE_COVERAGE",
                       "The billed service instant is outside the authorization's validity window.")

    if not plan or not plan.get("selected_bundle_price_cents"):
        raise APIError("ERR_BUNDLE_PRICE_UNPINNED", "No bundle price has been pinned for this plan.")

    _adjudicate(claim, pa, plan, actor_user_id=actor.user_id)
    return ok(serialize("claims", claim))


@api.route("/claims/<claim_id>/deny", methods=["POST"])
def deny_claim(claim_id):
    resolve_actor()
    claim = claim_lookup(claim_id)
    if claim["claim_status"] not in ("RECEIVED", "PENDED"):
        raise APIError("ERR_INVALID_STATE", "The claim is not RECEIVED or PENDED.")

    pa = db.find("preauthorizations", claim["preauthorization_id"])
    if pa is None or pa.get("effective_to") is None:
        raise APIError("ERR_INVALID_STATE", "The claim's authorization carries no validity window.")
    if db.now() < parse_dt(pa["effective_to"]):
        raise APIError("ERR_INVALID_STATE", "The authorization's validity window is still open.")

    claim["claim_status"] = "DENIED"
    claim["plan_paid_cents"] = 0
    claim["member_cost_share_cents"] = 0
    claim["member_accumulator_after_cents"] = claim["member_accumulator_before_cents"]
    db.touch(claim)
    return ok(serialize("claims", claim))


@api.route("/claims/<claim_id>/pay", methods=["POST"])
def pay_claim(claim_id):
    resolve_actor()
    claim = claim_lookup(claim_id)
    data = request.get_json(silent=True) or {}

    if claim["claim_status"] != "ADJUDICATED":
        raise APIError("ERR_INVALID_STATE", "The claim is not ADJUDICATED.")

    pa = db.find("preauthorizations", claim["preauthorization_id"])
    if "expected_preauthorization_version" not in data or data["expected_preauthorization_version"] is None:
        raise APIError("ERR_INVALID_REQUEST",
                       "The required input 'expected_preauthorization_version' is missing.")
    if int(data["expected_preauthorization_version"]) != int(pa["version"]):
        raise APIError("ERR_PREAUTH_VERSION_STALE",
                       "The authorization's version has advanced since it was observed.")

    claim["claim_status"] = "PAID"
    claim["_paid_at"] = db.now()
    db.touch(claim)

    if claim["service_category"] == "MEDICATION":
        bundle = bundle_of_preauth(db, pa)
        if bundle is not None:
            recompute_pharmacy_from_claims(db, bundle)

    db.touch(pa)
    return ok(serialize("claims", claim))


@api.route("/claims/<claim_id>/appeal", methods=["POST"])
def appeal_claim(claim_id):
    resolve_actor()
    claim = claim_lookup(claim_id)
    if claim["claim_status"] != "DENIED":
        raise APIError("ERR_INVALID_STATE", "The claim is not DENIED.")

    pa = db.find("preauthorizations", claim["preauthorization_id"])
    from datetime import timedelta
    deadline = parse_dt(pa["effective_to"]) + timedelta(days=APPEAL_WINDOW_DAYS)
    if db.now() >= deadline:
        raise APIError("ERR_INVALID_STATE", "The appeal window has closed.")

    claim["claim_status"] = "APPEALED"
    db.touch(claim)
    return ok(serialize("claims", claim))


@api.route("/claims/<claim_id>/appeal-decide", methods=["POST"])
def appeal_decide(claim_id):
    actor = resolve_actor()
    claim = claim_lookup(claim_id)
    if claim["claim_status"] != "APPEALED":
        raise APIError("ERR_INVALID_STATE", "The claim is not APPEALED.")

    if claim.get("_last_decision_actor") and actor.user_id == claim["_last_decision_actor"]:
        raise APIError("ERR_SOD_CONFLICT", "The reviewer already adjudicated this claim.")

    pa = db.find("preauthorizations", claim["preauthorization_id"])
    plan = plan_of_preauth(db, pa)
    _adjudicate(claim, pa, plan, actor_user_id=actor.user_id)
    db.touch(claim)
    return ok(serialize("claims", claim))


@api.route("/claims/<claim_id>/reverse", methods=["POST"])
def reverse_claim(claim_id):
    resolve_actor()
    claim = claim_lookup(claim_id)
    if claim["claim_status"] != "PAID":
        raise APIError("ERR_INVALID_STATE", "The claim is not PAID.")

    from datetime import timedelta
    paid_at = claim.get("_paid_at") or db.created_key(claim)
    if db.now() >= paid_at + timedelta(days=REVERSAL_WINDOW_DAYS):
        raise APIError("ERR_REVERSAL_WINDOW_CLOSED", "The reversal window has closed.")

    claim["claim_status"] = "REVERSED"
    claim["member_accumulator_after_cents"] = claim["member_accumulator_before_cents"]
    # The compensation releases the pool draw the corresponding order made.
    order = _order_for_claim(claim)
    if order is not None:
        claim["_released_cents"] = order.get("plan_paid_cents") or 0
    else:
        claim["_released_cents"] = claim.get("plan_paid_cents") or 0
    # The released amount is read off the pool before the claim's own paid reading is
    # zeroed below; recomputing the pool is itself a ledger move, so the entitlement's
    # version must advance even when the claim carried no allowance of its own.
    claim["plan_paid_cents"] = 0
    claim["member_cost_share_cents"] = 0
    db.touch(claim)

    # Return the cycle the claim belonged to from consumed back to UNCONSUMED.
    if claim.get("treatment_cycle_id"):
        cycle = db.find("treatment_cycles", claim["treatment_cycle_id"])
        if cycle is not None:
            cycle["consumption_marker"] = "UNCONSUMED"
            db.touch(cycle)

    pa = db.find("preauthorizations", claim["preauthorization_id"])
    if pa is not None:
        recompute_preauth_consumption(db, pa)
        db.touch(pa)
        bundle = bundle_of_preauth(db, pa)
        if bundle is not None:
            recompute_pharmacy_from_claims(db, bundle)
            recompute_bundle(db, bundle, force=True)
    return ok(serialize("claims", claim))