"""HeatClaim routes: file (FILED -> UNDER_REVIEW in the same request), read,
list, decide (APPROVE / REJECT / REQUEST_MORE_INFO), provide-info."""

from decimal import Decimal

from flask import Blueprint, request

from db import db, touch
from domain import (
    CLAIM_REASONS, SUMMER_MONTHS, round_cents, get_claim, ser_claim,
)
from errors import (
    ApiError, ERR_SHIPMENT_NOT_FOUND, ERR_INVALID_STATE, ERR_CLAIM_EXCEEDS_SHIPMENT,
    ERR_CLAIM_AUTO_APPROVED, ERR_OWNERSHIP_MISMATCH,
)
from middleware import authorize, ROLE_RETAILER, ROLE_CLAIMS_ADJUSTER, ALL_ROLES
from programs import _create_entity
from respond import ok, created, ok_list, paginate, parse_pagination
from validate import json_body, v_str, v_int, v_enum

bp = Blueprint("heat_claims", __name__)

DECISIONS = ("APPROVE", "REJECT", "REQUEST_MORE_INFO")


def _auto_approve(product, shipment):
    """true iff heat-sensitive product, not temp-controlled, not declined by
    the retailer, and ship_on falls in a summer month (June/July/August)."""
    return (
        product["requires_temp_control"]
        and not shipment["temp_controlled"]
        and not shipment["temp_control_declined_by_retailer"]
        and shipment["_ship_dt"].month in SUMMER_MONTHS
    )


def _settlement_pct(product, shipment):
    """heat_claim_settlement: first matching branch wins, top to bottom."""
    if shipment["temp_controlled"]:
        return Decimal("1.00")
    if shipment["temp_control_declined_by_retailer"]:
        return Decimal("0.50")
    if product["requires_temp_control"] and shipment["_ship_dt"].month in SUMMER_MONTHS:
        return Decimal("1.00")
    return Decimal("0.25")


@bp.post("/confection/heat-claims")
def file_claim():
    data = json_body()
    shipment_id = v_str(data, "shipment_id")
    claimed_units = v_int(data, "claimed_units")  # < 1 handled at priority 10
    reason = v_enum(data, "reason", CLAIM_REASONS)
    evidence_note = v_str(data, "evidence_note")

    # Note: claim FILING is deliberately not ownership-guarded (PRD 2.1 lists
    # the guarded operations and filing is not among them).
    authorize(ROLE_RETAILER)

    shipment = db.shipments.get(shipment_id)
    if shipment is None:
        raise ApiError(404, ERR_SHIPMENT_NOT_FOUND,
                       "Shipment %s does not exist" % shipment_id)

    # State (priority 7): the shipment must be DELIVERED.
    if shipment["status"] != "DELIVERED":
        raise ApiError(409, ERR_INVALID_STATE,
                       "heat claims can only be filed against a DELIVERED shipment")

    # Structural (priority 10): claimed_units >= 1 and the aggregate over
    # non-REJECTED claims must not exceed shipment.units — both surface as
    # ERR_CLAIM_EXCEEDS_SHIPMENT per the error catalogue.
    if claimed_units < 1:
        raise ApiError(422, ERR_CLAIM_EXCEEDS_SHIPMENT,
                       "claimed_units must be at least 1")
    claimed_so_far = sum(c["claimed_units"] for c in db.claims.values()
                         if c["shipment_id"] == shipment_id and c["status"] != "REJECTED")
    if claimed_so_far + claimed_units > shipment["units"]:
        raise ApiError(422, ERR_CLAIM_EXCEEDS_SHIPMENT,
                       "aggregate claimed units would exceed the shipment's units")

    commitment = db.commitments[shipment["commitment_id"]]
    product = db.products[commitment["product_id"]]

    # Born FILED and immediately advanced to UNDER_REVIEW by the system within
    # the same request: persisted as UNDER_REVIEW at version 1.
    claim = _create_entity(db.claims, {
        "shipment_id": shipment_id,
        "claimed_units": claimed_units,
        "reason": reason,
        "evidence_note": evidence_note,
        "auto_approve": _auto_approve(product, shipment),
        "credit_cents": None,
        "status": "UNDER_REVIEW",
    })
    return created(ser_claim(claim))


@bp.get("/confection/heat-claims/<claim_id>")
def read_claim(claim_id):
    authorize(*ALL_ROLES)
    return ok(ser_claim(get_claim(claim_id)))


@bp.get("/confection/heat-claims")
def list_claims():
    limit, offset = parse_pagination()
    authorize(*ALL_ROLES)
    items = list(db.claims.values())
    for param in ("shipment_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [c for c in items if c[param] == val]
    page, total, limit, offset = paginate(items, limit, offset)
    return ok_list([ser_claim(c) for c in page], total, limit, offset)


@bp.post("/confection/heat-claims/<claim_id>/decide")
def decide_claim(claim_id):
    data = json_body()
    decision = v_enum(data, "decision", DECISIONS)

    authorize(ROLE_CLAIMS_ADJUSTER)
    claim = get_claim(claim_id)

    # State (priority 7): all three decisions are defined only from UNDER_REVIEW.
    if claim["status"] != "UNDER_REVIEW":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only an UNDER_REVIEW claim can be decided")

    # Safety (priority 8): an auto-approved claim may never be rejected.
    if decision == "REJECT" and claim["auto_approve"]:
        raise ApiError(422, ERR_CLAIM_AUTO_APPROVED,
                       "a claim whose auto_approve condition holds may not be rejected")

    if decision == "APPROVE":
        shipment = db.shipments[claim["shipment_id"]]
        commitment = db.commitments[shipment["commitment_id"]]
        product = db.products[commitment["product_id"]]
        program = db.programs[commitment["program_id"]]
        pct = _settlement_pct(product, shipment)
        credit = round_cents(
            Decimal(claim["claimed_units"])
            * Decimal(program["retail_price_cents"]) * pct
        )
        claim["credit_cents"] = credit
        claim["status"] = "APPROVED"
        retailer = db.retailers[commitment["retailer_id"]]
        retailer["credit_balance_cents"] += credit
        touch(retailer)
    elif decision == "REJECT":
        claim["status"] = "REJECTED"
    else:  # REQUEST_MORE_INFO
        claim["status"] = "MORE_INFO"
    touch(claim)
    return ok(ser_claim(claim))


@bp.post("/confection/heat-claims/<claim_id>/provide-info")
def provide_info(claim_id):
    data = json_body()
    evidence_note = v_str(data, "evidence_note")

    actor = authorize(ROLE_RETAILER)
    claim = get_claim(claim_id)

    # Ownership (priority 4): the acting retailer must own the underlying
    # commitment behind the claimed shipment.
    shipment = db.shipments[claim["shipment_id"]]
    commitment = db.commitments[shipment["commitment_id"]]
    if commitment["retailer_id"] != actor.user_id:
        raise ApiError(403, ERR_OWNERSHIP_MISMATCH,
                       "the acting retailer does not own the claimed shipment's commitment")

    if claim["status"] != "MORE_INFO":
        raise ApiError(409, ERR_INVALID_STATE,
                       "only a MORE_INFO claim can accept additional evidence")

    claim["evidence_note"] = evidence_note
    claim["status"] = "UNDER_REVIEW"
    touch(claim)
    return ok(ser_claim(claim))
