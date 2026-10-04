"""ListingEvent recording and the case transitions it drives (PRD 3.7)."""
from flask import Blueprint

from auth import require_roles
from calc import days_between
from db import store
from envelope import success_obj
from errors import (
    ApiError,
    ERR_DUPLICATE_LISTED_EVENT,
    ERR_INVALID_STATE,
    ERR_LISTING_EVENT_ORDER,
    ERR_LISTING_WINDOW_NOT_ELAPSED,
)
from logic import (
    bump,
    case_listing_events,
    get_or_404,
    list_response,
    new_record,
    recompute_posture,
    serialize,
)
from validate import body_json, opt_bool, opt_int, req_dt, req_enum, req_int

from .closing import create_closing_statement

bp = Blueprint("listing_events", __name__)

EVENT_KINDS = ("LISTED", "PRICE_REDUCED", "OFFER_ACCEPTED", "CLOSED_SOLD", "CLOSED_UNSOLD", "DELISTED")
PRICE_REQUIRED_KINDS = ("LISTED", "PRICE_REDUCED", "OFFER_ACCEPTED", "CLOSED_SOLD")


@bp.post("/concierge/cases/<caseId>/listing-events")
@require_roles("ListingAgent")
def create_listing_event(caseId):
    case = get_or_404(store.cases, caseId, "ConciergeCase")
    body = body_json(required=True)
    kind = req_enum(body, "event_kind", EVENT_KINDS)
    event_at = req_dt(body, "event_at")
    if kind in PRICE_REQUIRED_KINDS:
        price = req_int(body, "price_cents", min_value=1)
    else:
        price = opt_int(body, "price_cents", None, min_value=1)
    risk = opt_bool(body, "market_risk_flag", False)

    events = case_listing_events(caseId)
    if kind == "LISTED":
        if any(e["event_kind"] == "LISTED" for e in events):
            raise ApiError(ERR_DUPLICATE_LISTED_EVENT, "A LISTED event already exists for this case", 409)
        if case["status"] != "READY_TO_LIST":
            raise ApiError(ERR_INVALID_STATE, "Case is not READY_TO_LIST", 409)
    elif kind == "OFFER_ACCEPTED":
        if case["status"] != "LISTED":
            raise ApiError(ERR_LISTING_EVENT_ORDER, "OFFER_ACCEPTED requires a LISTED case", 409)
    elif kind == "CLOSED_SOLD":
        if case["status"] != "UNDER_CONTRACT":
            raise ApiError(ERR_LISTING_EVENT_ORDER, "CLOSED_SOLD requires an UNDER_CONTRACT case", 409)
    elif kind == "CLOSED_UNSOLD":
        if case["status"] != "LISTED":
            raise ApiError(ERR_LISTING_EVENT_ORDER, "CLOSED_UNSOLD requires a LISTED case", 409)
        if days_between(case["listed_at"], event_at) < case["listing_window_days"]:
            raise ApiError(ERR_LISTING_WINDOW_NOT_ELAPSED, "The listing window has not elapsed", 409)
    else:  # PRICE_REDUCED, DELISTED — recorded without a case transition
        if case["status"] not in ("LISTED", "UNDER_CONTRACT"):
            raise ApiError(ERR_LISTING_EVENT_ORDER, "Event out of sequence for this case", 409)

    rec = new_record({
        "concierge_case_id": case["id"],
        "event_kind": kind,
        "event_at": event_at,
        "price_cents": price,
        "market_risk_flag": risk,
    })
    store.listing_events[rec["id"]] = rec

    if kind == "LISTED":
        case["status"] = "LISTED"
        case["listed_at"] = event_at
        bump(case)
    elif kind == "OFFER_ACCEPTED":
        case["status"] = "UNDER_CONTRACT"
        bump(case)
    elif kind == "CLOSED_SOLD":
        case["status"] = "CLOSED_SOLD"
        case["closed_at"] = event_at
        bump(case)
        create_closing_statement(case, sold=True, gross_sale_price=price)
    elif kind == "CLOSED_UNSOLD":
        case["status"] = "CLOSED_UNSOLD"
        case["closed_at"] = event_at
        bump(case)
        create_closing_statement(case, sold=False, gross_sale_price=None)

    recompute_posture(case)
    return success_obj(serialize(rec), 201)


@bp.get("/concierge/cases/<caseId>/listing-events")
@require_roles("Any")
def list_listing_events(caseId):
    get_or_404(store.cases, caseId, "ConciergeCase")
    return list_response(case_listing_events(caseId))
