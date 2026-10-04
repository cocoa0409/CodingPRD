"""Delivery schedule negotiation and delay compensation (PRD 3.9)."""
from flask import Blueprint, g

import calc
import svc
from core import (
    ApiError,
    body,
    db,
    endpoint,
    f_date,
    f_enum,
    f_int,
    new_row,
    paginate,
    parse_date,
    q_enum,
    raw_int,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("negotiations", __name__, url_prefix="/api")

COMPENSATION_VARIANTS = ("CONTRACTUAL_LIQUIDATED", "GOODWILL")
NEGOTIATION_STATUSES = ("PROPOSED", "COUNTERED", "AGREED", "EXPIRED")
LIVE_STATUSES = ("PROPOSED", "COUNTERED")


def _customer_owns(negotiation):
    """Entity-backed ownership: a Customer actor's X-User-ID must equal the
    negotiation's customer_id (PRD 2.1). Opaque roles skip this."""
    if g.role == "Customer" and g.user_id != negotiation["customer_id"]:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")


def _goodwill_credit_check(customer_id, variant):
    """GOODWILL is reserved for customers whose credit_standing is GOOD (PRD 3.9)."""
    if variant == "GOODWILL":
        customer = db.customers.get(customer_id)
        if customer is None or customer["credit_standing"] != "GOOD":
            raise ApiError("ERR_GOODWILL_REQUIRES_GOOD_CREDIT")


def _turn_check(negotiation):
    """Alternating turns: PROPOSED awaits the Customer, COUNTERED awaits the
    DeliveryManager (PRD 3.9)."""
    if negotiation["status"] == "PROPOSED" and g.role != "Customer":
        raise ApiError("ERR_NEGOTIATION_ACTOR_TURN")
    if negotiation["status"] == "COUNTERED" and g.role != "DeliveryManager":
        raise ApiError("ERR_NEGOTIATION_ACTOR_TURN")


@bp.post("/aircraft-units/<aircraft_id>/delivery-negotiations")
@endpoint("DeliveryManager")
def create_negotiation(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    payload = body()
    # rung 8 -- goodwill credit standing
    _goodwill_credit_check(aircraft["customer_id"], payload.get("compensation_variant"))
    # rung 10 -- body shape
    proposed_delivery_date = f_date(payload, "proposed_delivery_date")
    compensation_variant = f_enum(payload, "compensation_variant", COMPENSATION_VARIANTS)
    contracted = parse_date(aircraft["contracted_delivery_date"])
    days_late = calc.delay_days(proposed_delivery_date, contracted)
    negotiation = new_row(
        "DeliveryNegotiation",
        aircraft_id=aircraft["id"],
        customer_id=aircraft["customer_id"],
        proposed_delivery_date=proposed_delivery_date.isoformat(),
        compensation_variant=compensation_variant,
        days_late=days_late,
        compensation_cents=calc.compensation(
            compensation_variant, days_late, aircraft["contract_price_cents"]
        ),
        round_number=1,
        status="PROPOSED",
    )
    db.negotiations[negotiation["id"]] = negotiation
    return respond_object(svc.dump_negotiation(negotiation), 201)


@bp.get("/aircraft-units/<aircraft_id>/delivery-negotiations")
@endpoint("ProgramAdmin", "DeliveryManager", "Customer")
def list_negotiations(aircraft_id):
    svc.need_aircraft(aircraft_id)
    status = q_enum("status", NEGOTIATION_STATUSES)
    rows = [n for n in db.negotiations.values() if n["aircraft_id"] == aircraft_id]
    if status is not None:
        rows = [n for n in rows if n["status"] == status]
    return paginate(sort_created(rows), svc.dump_negotiation)


@bp.post("/delivery-negotiations/<negotiation_id>/counter")
@endpoint("DeliveryManager", "Customer")
def counter_negotiation(negotiation_id):
    negotiation = svc.need_negotiation(negotiation_id)
    _customer_owns(negotiation)
    payload = body()
    # rung 4 -- OCC: expected_negotiation_version, checked immediately after the
    # negotiation loads and before every state and business check (PRD 2.7).
    expected = payload.get("expected_negotiation_version")
    if raw_int(expected) and expected != negotiation["version"]:
        raise ApiError("ERR_STALE_VERSION")
    # rung 5 -- state gate (AGREED / EXPIRED are terminal)
    if negotiation["status"] not in LIVE_STATUSES:
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 8 -- alternating turn
    _turn_check(negotiation)
    # rung 8 -- round limit: a counter attempted at round 6 does not advance the
    # round; the attempt itself pushes the negotiation to EXPIRED (PRD 3.9).
    if negotiation["round_number"] >= calc.MAX_NEGOTIATION_ROUNDS:
        negotiation["status"] = "EXPIRED"
        touch(negotiation)
        raise ApiError("ERR_NEGOTIATION_ROUND_LIMIT")
    # rung 8 -- goodwill credit standing on the countered variant
    _goodwill_credit_check(negotiation["customer_id"], payload.get("compensation_variant"))
    # rung 10 -- body shape
    proposed_delivery_date = f_date(payload, "proposed_delivery_date")
    compensation_variant = f_enum(payload, "compensation_variant", COMPENSATION_VARIANTS)
    f_int(payload, "expected_negotiation_version")
    aircraft = svc.need_aircraft(negotiation["aircraft_id"])
    contracted = parse_date(aircraft["contracted_delivery_date"])
    days_late = calc.delay_days(proposed_delivery_date, contracted)
    negotiation["proposed_delivery_date"] = proposed_delivery_date.isoformat()
    negotiation["compensation_variant"] = compensation_variant
    negotiation["days_late"] = days_late
    negotiation["compensation_cents"] = calc.compensation(
        compensation_variant, days_late, aircraft["contract_price_cents"]
    )
    negotiation["round_number"] += 1
    negotiation["status"] = (
        "COUNTERED" if negotiation["status"] == "PROPOSED" else "PROPOSED"
    )
    touch(negotiation)
    return respond_object(svc.dump_negotiation(negotiation))


@bp.post("/delivery-negotiations/<negotiation_id>/agree")
@endpoint("DeliveryManager", "Customer")
def agree_negotiation(negotiation_id):
    negotiation = svc.need_negotiation(negotiation_id)
    _customer_owns(negotiation)
    # rung 5 -- state gate
    if negotiation["status"] not in LIVE_STATUSES:
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 8 -- the responder agrees: Customer to a PROPOSED proposal,
    # DeliveryManager to a COUNTERED counter (PRD 3.9).
    _turn_check(negotiation)
    negotiation["status"] = "AGREED"
    touch(negotiation)
    # Agreement writes the standing date onto the aircraft and locks the
    # compensation at its current value (no further recomputation).
    aircraft = svc.need_aircraft(negotiation["aircraft_id"])
    aircraft["scheduled_delivery_date"] = negotiation["proposed_delivery_date"]
    touch(aircraft)
    return respond_object(svc.dump_negotiation(negotiation))
