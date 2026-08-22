"""Settlement offers: drafting, the authority ladder and the response cycle."""

from decimal import Decimal

from flask import Blueprint

from core import (
    ApiError, db, now, base_record, touch, ok, paginated, qp, order_by,
    authenticate, get_body, bad, add_days, party_of,
    req_string, opt_string, req_enum, opt_enum, req_int, opt_int, opt_number,
    req_id, opt_id, opt_bool,
    ROLE_UNION_STEWARD, ROLE_ANALYST, ROLE_DIRECTOR, ROLE_NEGOTIATOR, READ_ROLES,
)
import derive
from derive import (
    GRIEVANCE_TERMINAL, OFFER_PARTIES, REMEDY_TERMS, DECISIONS,
    OFFER_VALIDITY_DAYS, ser_offer,
)
import services

bp = Blueprint("settlement", __name__)

AUTHORITY_CEILING = {
    ROLE_DIRECTOR: ("ANALYST", "DIRECTOR"),
    ROLE_NEGOTIATOR: ("ANALYST", "DIRECTOR", "NEGOTIATOR"),
}


def _price(offer):
    """Run calculations.settlement_exposure_authority_tier over a stored offer."""
    grievance = db.grievances[offer["grievance_id"]]
    grievant = db.employees[grievance["grievant_id"]]
    clause = db.contract_clauses[grievance["clause_id"]]
    unit = db.bargaining_units[grievance["bargaining_unit_id"]]
    precedent = None
    if offer["precedent_case_id"] is not None:
        precedent = db.precedent_cases.get(offer["precedent_case_id"])
    return derive.settlement_exposure(offer, grievant, clause, unit, precedent)


def _apply_pricing(offer):
    pricing = _price(offer)
    offer["exposure_cents"] = pricing["exposure_cents"]
    offer["authority_tier"] = pricing["authority_tier"]
    offer["precedent_deviation_bps"] = pricing["precedent_deviation_bps"]
    return pricing


def _new_offer(grievance, offering_party, monetary_cents, back_pay_hours, remedy_terms,
               precedent_setting, precedent_case_id, round_number, prepared_by):
    offer = base_record()
    offer.update({
        "grievance_id": grievance["id"],
        "precedent_case_id": precedent_case_id,
        "offering_party": offering_party,
        "monetary_cents": monetary_cents,
        "back_pay_hours": back_pay_hours,
        "remedy_terms": remedy_terms,
        "precedent_setting": precedent_setting,
        "round_number": round_number,
        "exposure_cents": 0,
        "authority_tier": "ANALYST",
        "precedent_deviation_bps": None,
        "status": "DRAFT",
        "prepared_by_user_id": prepared_by,
        "authorized_by_user_id": None,
        "authorized_at": None,
        "expires_at": None,
    })
    db.settlement_offers[offer["id"]] = offer
    _apply_pricing(offer)
    return offer


# --------------------------------------------------------------------------
# Drafting (PRD 3.4)
# --------------------------------------------------------------------------
@bp.post("/grievances/<grievance_id>/settlement-offers")
def draft_settlement_offer(grievance_id):
    user_id, role = authenticate([ROLE_ANALYST, ROLE_UNION_STEWARD])
    grievance = services.find_grievance(grievance_id)
    body = get_body()

    offering_party = req_enum(body, "offering_party", OFFER_PARTIES)
    monetary_cents = req_int(body, "monetary_cents", minimum=0)
    back_pay_hours = opt_number(body, "back_pay_hours", Decimal(0), minimum=0)
    remedy_terms = opt_enum(body, "remedy_terms", REMEDY_TERMS, "NONE")
    precedent_setting = opt_bool(body, "precedent_setting", False)
    precedent_case_id = opt_id(body, "precedent_case_id")

    precedent = None
    if precedent_case_id is not None:
        precedent = services.find_precedent(precedent_case_id)

    if grievance["status"] in GRIEVANCE_TERMINAL:
        raise ApiError("ERR_INVALID_GRIEVANCE_STATE",
                       "Settlement terms may not be drafted on a terminal grievance.")

    if precedent is not None and precedent["clause_id"] != grievance["clause_id"]:
        raise ApiError("ERR_PRECEDENT_CLAUSE_MISMATCH",
                       "The cited precedent construes a different clause.")

    if party_of(role) != offering_party:
        raise ApiError("ERR_PARTY_ROLE_MISMATCH",
                       "The acting role's party must equal offering_party.")

    offer = _new_offer(grievance, offering_party, monetary_cents, back_pay_hours,
                       remedy_terms, precedent_setting, precedent_case_id, 1, user_id)
    return ok(ser_offer(offer), 201)


@bp.get("/settlement-offers/<offer_id>")
def read_settlement_offer(offer_id):
    authenticate(READ_ROLES)
    offer = services.find_offer(offer_id)
    return ok(ser_offer(offer))


@bp.get("/settlement-offers")
def list_settlement_offers():
    authenticate(READ_ROLES)
    rows = list(db.settlement_offers.values())
    for field in ("grievance_id", "precedent_case_id", "status", "offering_party"):
        value = qp(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows = order_by(rows, "round_number", "created_at")
    return paginated(rows, ser_offer)


# --------------------------------------------------------------------------
# Authorization (PRD 3.4, 2.7, 2.11)
# --------------------------------------------------------------------------
@bp.post("/settlement-offers/<offer_id>/authorize")
def authorize_settlement_offer(offer_id):
    user_id, role = authenticate([ROLE_DIRECTOR, ROLE_NEGOTIATOR])
    offer = services.find_offer(offer_id)
    grievance = db.grievances[offer["grievance_id"]]
    body = get_body()

    expected_version = req_int(body, "expected_grievance_version")
    opt_string(body, "authorization_note")

    # ladder 8 — optimistic concurrency sits ahead of every state check
    if expected_version != grievance["version"]:
        raise ApiError("ERR_STALE_GRIEVANCE_VERSION",
                       "expected_grievance_version does not match the grievance.")

    # ladder 9
    if offer["status"] != "DRAFT":
        raise ApiError("ERR_OFFER_NOT_DRAFT", "Only a DRAFT offer may be authorized.")

    # ladder 13 — segregation of duties
    for step in derive.steps_of(grievance["id"]):
        if step["responded_by_user_id"] == user_id:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The operator who answered a step may not authorize a settlement "
                           "on the same grievance.")

    pricing = _apply_pricing(offer)

    # ladder 39 — the authority ceiling
    if pricing["authority_tier"] not in AUTHORITY_CEILING.get(role, ()):
        raise ApiError("ERR_AUTHORITY_EXCEEDED",
                       "The offer's authority tier exceeds the acting role's ceiling.")

    # ladder 40 — precedent review is compulsory above the lowest tier
    if offer["precedent_case_id"] is None and pricing["base_tier"] != "ANALYST":
        raise ApiError("ERR_PRECEDENT_REVIEW_REQUIRED",
                       "An offer whose base tier is DIRECTOR or above must cite a precedent.")

    instant = now()
    offer["status"] = "AUTHORIZED"
    offer["authorized_by_user_id"] = user_id
    offer["authorized_at"] = instant
    offer["expires_at"] = add_days(instant, OFFER_VALIDITY_DAYS)
    touch(offer)

    for other in derive.offers_of(grievance["id"]):
        if other["id"] != offer["id"] and other["status"] == "AUTHORIZED":
            other["status"] = "LAPSED"
            touch(other)

    touch(grievance)
    derive.refresh_timeliness(grievance)
    return ok(ser_offer(offer))


# --------------------------------------------------------------------------
# Response (PRD 3.4, 3.5)
# --------------------------------------------------------------------------
@bp.post("/settlement-offers/<offer_id>/respond")
def respond_settlement_offer(offer_id):
    user_id, role = authenticate([ROLE_UNION_STEWARD, ROLE_DIRECTOR])
    offer = services.find_offer(offer_id)
    grievance = db.grievances[offer["grievance_id"]]

    if role == ROLE_UNION_STEWARD:
        services.require_filing_steward(grievance, user_id)

    body = get_body()
    decision = req_enum(body, "decision", DECISIONS)
    counter_monetary = None
    if decision == "COUNTER":
        counter_monetary = req_int(body, "counter_monetary_cents", minimum=0)
    else:
        counter_monetary = opt_int(body, "counter_monetary_cents", None, minimum=0)
    counter_back_pay = opt_number(body, "counter_back_pay_hours", Decimal(0), minimum=0)
    counter_terms = opt_enum(body, "counter_remedy_terms", REMEDY_TERMS, "NONE")
    counter_precedent_setting = opt_bool(body, "counter_precedent_setting", False)
    opt_string(body, "response_note")

    # ladder 9
    if offer["status"] != "AUTHORIZED":
        raise ApiError("ERR_OFFER_NOT_AUTHORIZED",
                       "Only an AUTHORIZED offer may be responded to.")

    # ladder 20 — the responder must speak for the other side of the table
    opposite = "UNION" if offer["offering_party"] == "EMPLOYER" else "EMPLOYER"
    if party_of(role) != opposite:
        raise ApiError("ERR_PARTY_ROLE_MISMATCH",
                       "Only the receiving party may respond to this offer.")

    # ladder 38
    if offer["expires_at"] is not None and now() > offer["expires_at"]:
        raise ApiError("ERR_OFFER_EXPIRED", "The offer has expired.")

    if decision == "ACCEPT":
        offer["status"] = "ACCEPTED"
        touch(offer)
        grievance["settled_amount_cents"] = offer["exposure_cents"]
        services.terminal_cascade(grievance, "SETTLED", accepted_offer_id=offer["id"])
        touch(grievance)
    elif decision == "REJECT":
        offer["status"] = "REJECTED"
        touch(offer)
    else:
        offer["status"] = "COUNTERED"
        touch(offer)
        flipped = "UNION" if offer["offering_party"] == "EMPLOYER" else "EMPLOYER"
        _new_offer(grievance, flipped, counter_monetary, counter_back_pay, counter_terms,
                   counter_precedent_setting, None, offer["round_number"] + 1, user_id)

    return ok(ser_offer(offer))
