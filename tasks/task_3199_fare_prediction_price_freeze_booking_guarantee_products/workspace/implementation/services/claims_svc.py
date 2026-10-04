"""GuaranteeClaim machine (rule A + G) under segregation of duties."""

from datetime import timedelta

from db import DB, dec, new_row, touch
from errors import fail
from flask import g
from middleware import as_int, as_str
from services import calc
from services.freeze_svc import accrue, stamp_integrity
from services.routes_svc import arrival_fare, derive_route, rebalance_route

CLAIM_STATUSES = ("FILED", "UNDER_REVIEW", "APPROVED", "SETTLED_WITH_PURCHASE",
                  "REJECTED", "WITHDRAWN")


def claim_or_404(claim_id):
    claim = DB.claims.get(claim_id)
    if claim is None:
        fail("ERR_RESOURCE_NOT_FOUND", "no guarantee claim %s" % claim_id)
    return claim


def recompute_claim(claim, freeze, route):
    """guarantee_claim_settlement, both variants."""
    itinerary = DB.itineraries[freeze["itinerary_id"]]
    arrival = arrival_fare(itinerary["id"])
    market = int(claim["market_price_cents"])
    result = calc.claim_settlement(route, freeze, market, arrival)
    claim["overshoot_cents"] = result["overshoot_cents"]
    claim["capped_impact_cents"] = result["capped_impact_cents"]
    claim["guaranteed_ceiling_test_cents"] = result["guaranteed_ceiling_test_cents"]
    claim["payout_cents"] = result["payout_cents"]
    claim["transaction_value_pre_cents"] = result["transaction_value_pre_cents"]
    claim["transaction_value_final_cents"] = result["transaction_value_final_cents"]
    claim["transaction_value_cents"] = (
        result["transaction_value_final_cents"]
        if claim["claim_status"] == "SETTLED_WITH_PURCHASE"
        else result["transaction_value_pre_cents"])

    depth = calc.depth_ratio(int(freeze.get("unhedged_exposure_cents") or 0),
                             int(freeze.get("capped_impact_cents") or 0))
    claim["depth_ratio"] = float(depth)
    # PRD §3.5: the continuum term is a share of the FREEZE's own exposure chain
    # ("the guaranteed ceiling covers the capped impact, so the continuum absorbs
    # exactly the capped impact divided by 1.25"); its depth ratio is the
    # claimed freeze's unhedged/capped ratio.
    claim["continuum_absorbed_cents"] = calc.continuum_absorbed_cents(
        int(freeze.get("overshoot_cents") or 0), depth)

    claim["audit_ready"] = bool(
        claim.get("approver_user_id") and
        claim["approver_user_id"] != claim["filer_user_id"])
    # PRD §3.5: the claim's `status` dimension is exactly `claim_status`; both
    # names refer to the same field, so both are published.
    claim["status"] = claim["claim_status"]
    return claim


def claim_window_open(freeze):
    if freeze.get("_expires_dt") is None:
        return True
    limit = freeze["_expires_dt"] + timedelta(days=14)
    return DB.clock.now() <= limit


def file_claim(freeze_id, data):
    freeze = DB.price_freezes.get(freeze_id)
    if freeze is None:
        fail("ERR_FREEZE_NOT_FOUND", "no price freeze %s" % freeze_id)
    market_price = as_int(data, "market_price_cents")
    if market_price < 1:
        fail("ERR_INVALID_REQUEST", "market_price_cents must be at least 1 cent")

    route = DB.routes[freeze["_route_id"]]
    itinerary = DB.itineraries[freeze["itinerary_id"]]

    if not claim_window_open(freeze):
        fail("ERR_CLAIM_WINDOW_CLOSED",
             "the claim window closed 14 days after the freeze's own window ended")

    if freeze["status"] != "FROZEN":
        fail("ERR_INVALID_STATE",
             "a claim may only be filed against a FROZEN freeze")
    if int(freeze.get("overshoot_cents") or 0) <= 0:
        fail("ERR_NO_OVERSHOOT", "the frozen fare did not rise above the live base fare")

    claim = new_row(
        freeze_id=freeze["id"],
        itinerary_id=itinerary["id"],
        _itinerary_id=itinerary["id"],
        _route_id=route["id"],
        filer_user_id=g.actor_id,
        approver_user_id=None,
        market_price_cents=market_price,
        claim_status="FILED",
        overshoot_cents=0,
        capped_impact_cents=0,
        payout_cents=0,
        transaction_value_cents=0,
        transaction_value_pre_cents=0,
        transaction_value_final_cents=0,
        guaranteed_ceiling_test_cents=0,
        audit_ready=False,
        depth_ratio=0.0,
        continuum_absorbed_cents=0,
        review_note=None,
        approval_note=None,
        rejection_reason=None,
        withdrawal_reason=None,
        reconsideration_reason=None,
    )
    DB.insert("claims", claim)
    recompute_claim(claim, freeze, route)

    freeze["status"] = "CLAIM_PENDING"
    touch(freeze)
    derive_route(route)
    return claim


def _sod_gate(claim):
    """Priority 7: the acting identity must differ from filer and approver."""
    if claim["filer_user_id"] == g.actor_id:
        fail("ERR_SOD_VIOLATION", "the filer may not act on this claim")
    if claim.get("approver_user_id") and claim["approver_user_id"] == g.actor_id:
        fail("ERR_SOD_VIOLATION", "the recorded approver may not act on this claim")


def review(claim_id, data):
    claim = claim_or_404(claim_id)
    # The §1.2 table carries UNDER_REVIEW -> APPROVED on the reviews endpoint
    # ("the review step") as well as on the approvals endpoint.
    if claim["claim_status"] == "UNDER_REVIEW":
        return approve(claim_id, data)
    _sod_gate(claim)
    if claim["claim_status"] not in ("FILED", "APPROVED"):
        fail("ERR_INVALID_STATE",
             "a claim in %s cannot be moved into review" % claim["claim_status"])

    claim["claim_status"] = "UNDER_REVIEW"
    claim["status"] = "UNDER_REVIEW"
    claim["approver_user_id"] = g.actor_id
    claim["review_note"] = data.get("review_note")
    freeze = DB.price_freezes[claim["freeze_id"]]
    recompute_claim(claim, freeze, DB.routes[freeze["_route_id"]])
    claim["audit_ready"] = True
    touch(claim)
    return claim


def approve(claim_id, data):
    claim = claim_or_404(claim_id)
    _sod_gate(claim)
    if claim["claim_status"] not in ("FILED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE",
             "a claim in %s cannot be approved" % claim["claim_status"])

    freeze = DB.price_freezes[claim["freeze_id"]]
    route = DB.routes[freeze["_route_id"]]
    recompute_claim(claim, freeze, route)
    if int(claim["payout_cents"]) != int(freeze.get("capped_impact_cents") or 0):
        fail("ERR_CLAIM_NON_CONFORMANT",
             "payout_cents does not equal the freeze's capped_impact_cents")

    claim["claim_status"] = "APPROVED"
    claim["status"] = "APPROVED"
    claim["approver_user_id"] = g.actor_id
    claim["approval_note"] = data.get("approval_note")
    claim["audit_ready"] = True
    touch(claim)
    derive_route(route)
    return claim


def reject(claim_id, data):
    claim = claim_or_404(claim_id)
    reason = as_str(data, "rejection_reason")
    if claim["claim_status"] not in ("FILED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE",
             "a claim in %s cannot be rejected" % claim["claim_status"])

    claim["claim_status"] = "REJECTED"
    claim["status"] = "REJECTED"
    claim["rejection_reason"] = reason
    freeze = DB.price_freezes[claim["freeze_id"]]
    freeze["status"] = "FROZEN"
    touch(freeze)
    touch(claim)
    rebalance_route(DB.routes[freeze["_route_id"]])
    return claim


def withdraw(claim_id, data):
    claim = claim_or_404(claim_id)
    if claim["claim_status"] not in ("FILED", "UNDER_REVIEW"):
        fail("ERR_INVALID_STATE",
             "a claim in %s cannot be withdrawn" % claim["claim_status"])

    itinerary = DB.itineraries[claim["_itinerary_id"]]
    if itinerary["traveler_user_id"] != g.actor_id:
        fail("ERR_FORBIDDEN_FOR_ACTOR",
             "the acting traveler does not own this claim's itinerary")

    claim["claim_status"] = "WITHDRAWN"
    claim["status"] = "WITHDRAWN"
    claim["withdrawal_reason"] = data.get("withdrawal_reason")
    freeze = DB.price_freezes[claim["freeze_id"]]
    freeze["status"] = "FROZEN"
    touch(freeze)
    touch(claim)
    rebalance_route(DB.routes[freeze["_route_id"]])
    return claim


def reconsider(claim_id, data):
    claim = claim_or_404(claim_id)
    reason = as_str(data, "reconsideration_reason")
    if claim["claim_status"] not in ("APPROVED", "REJECTED"):
        fail("ERR_INVALID_STATE",
             "a claim in %s cannot be reconsidered" % claim["claim_status"])

    freeze = DB.price_freezes[claim["freeze_id"]]
    if not claim_window_open(freeze):
        fail("ERR_CLAIM_WINDOW_CLOSED",
             "the reconsideration window has closed")

    claim["claim_status"] = "UNDER_REVIEW"
    claim["status"] = "UNDER_REVIEW"
    claim["reconsideration_reason"] = reason
    touch(claim)
    return claim


def settle(claim_id, data):
    claim = claim_or_404(claim_id)
    # Priority: the segregation audit outranks every state check (PRD §2.5), and
    # it lives here rather than in the endpoint's role gate because the role's
    # entitlement and the claim's own filer/approver record are distinct checks.
    _sod_gate(claim)
    # Role entitlement: settlement is the claims desk's operation (PRD §4).
    if g.actor_role != "ClaimsAdjuster":
        fail("ERR_FORBIDDEN_FOR_ACTOR",
             "role %s is not entitled to settle a guarantee claim" % g.actor_role)
    expected = as_int(data, "expected_claim_version")
    freeze = DB.price_freezes[claim["freeze_id"]]
    route = DB.routes[freeze["_route_id"]]

    # Priority 7 — segregation audit before any state check.
    _sod_gate(claim)
    if not claim.get("approver_user_id"):
        fail("ERR_INVALID_STATE",
             "the claim carries no recorded approver, so the settlement state check fails")

    if claim["claim_status"] != "APPROVED":
        fail("ERR_INVALID_STATE",
             "a claim in %s cannot be settled" % claim["claim_status"])

    recompute_claim(claim, freeze, route)

    # Priority 12 — custody backing gate (PRD §3.5). The tier test is whether
    # the guarantee ceiling is re-evaluated against the ACTIVE route base fare
    # (the `guaranteed_ceiling_test_cents`) equals the freeze's own
    # `guaranteed_ceiling_cents` — i.e. whether the chain was built inside one
    # insurance tier — and the backing alternative is the freeze's
    # custody_return_pending_cents meeting the payout.
    custody_ok = int(freeze["custody_return_pending_cents"]) >= int(claim["payout_cents"])
    if not int(claim["guaranteed_ceiling_test_cents"]) == int(
            freeze.get("guaranteed_ceiling_cents") or 0):
        if not custody_ok:
            fail("ERR_CUSTODY_INSUFFICIENT",
                 "no matching insurance tier and insufficient custody backing")

    # Priority 11 — route risk profile gate: the freeze's capped impact must not
    # exceed the route's available exposure.
    derive_route(route)
    if int(freeze.get("capped_impact_cents") or 0) > int(route["available_exposure_cents"]):
        fail("ERR_ROUTE_EXPOSURE_PROFILE",
             "the freeze's capped impact exceeds the route's available exposure")

    # Priority 19 — price-field completeness.
    if claim.get("market_price_cents") is None:
        fail("ERR_PRICE_FIELD_MISSING", "market_price_cents is absent")

    if int(claim["version"]) != expected:
        fail("ERR_STALE_VERSION", "expected_claim_version does not match the claim version")

    claim["claim_status"] = "SETTLED_WITH_PURCHASE"
    claim["status"] = "SETTLED_WITH_PURCHASE"
    claim["transaction_value_cents"] = claim["transaction_value_final_cents"]
    claim["audit_ready"] = True
    freeze["status"] = "CLAIMED"
    route["open_freeze_count"] = max(0, int(route["open_freeze_count"]) - 1)

    freeze["custody_held_cents"] = (
        float(freeze["custody_held_cents"]) + float(claim["payout_cents"]))
    accrue(freeze, route)
    stamp_integrity(freeze)

    for payment in DB.all("payments"):
        if payment["claim_id"] == claim["id"] and payment["status"] not in (
                "RETIRED", "FORFEITED"):
            payment["status"] = "RETIRED"
            payment["retired_reason"] = "CLAIM_SETTLED"
            touch(payment)

    touch(freeze)
    touch(claim)
    rebalance_route(route)
    return claim