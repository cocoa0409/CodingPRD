"""Attrition events: immutable appends that drive the clawback ledger."""

from flask import Blueprint, request

from auth import begin, guard_buyer_id, guard_deal
from calc import ATTRIBUTIONS, EVENT_TYPES
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import event_json
from services import get_account, get_deal, get_event, midnight, recompute_deal_ledger
from store import new_record, ordered, store, touch
from validators import bad, body, path_uuid, req_date, req_enum, req_id, req_int

bp = Blueprint("attrition", __name__)


@bp.post("/attrition-events")
def create_event():
    role, user_id = begin("Broker", "Buyer")
    data = body()
    if isinstance(data.get("deal_id"), str):
        existing = store.deals.get(data["deal_id"])
        if existing is not None:
            guard_buyer_id(existing["buyer_id"])

    deal_id = req_id(data, "deal_id")
    account_id = req_id(data, "account_id")
    event_type = req_enum(data, "event_type", EVENT_TYPES)
    effective_date = req_date(data, "effective_date")
    delta = req_int(data, "mrr_delta_cents")
    attributed_to = req_enum(data, "attributed_to", ATTRIBUTIONS)
    expected_version = req_int(data, "expected_deal_version")

    if delta == 0:
        bad("Field 'mrr_delta_cents' must be non-zero.")
    if event_type in ("CANCELLED", "DOWNGRADED") and delta > 0:
        bad("Field 'mrr_delta_cents' must be negative for a %s event." % event_type)
    if event_type == "RECOVERED" and delta < 0:
        bad("Field 'mrr_delta_cents' must be positive for a RECOVERED event.")

    account = get_account(account_id)
    deal = get_deal(deal_id)

    if expected_version != deal["version"]:
        raise ApiError("ERR_STALE_DEAL_VERSION",
                       "The deal has already been recomputed by an earlier append.")

    if deal["status"] == "TERMINATED":
        raise ApiError("ERR_DEAL_TERMINAL", "The deal has reached an absorbing status.")
    if deal["status"] not in ("CLOSED", "GUARANTEE_CLOSED"):
        raise ApiError("ERR_GUARANTEE_NOT_STARTED",
                       "There is no guarantee to draw on before closing.")
    if account["listing_id"] != deal["listing_id"]:
        raise ApiError("ERR_ACCOUNT_LISTING_MISMATCH",
                       "The account and the deal belong to different routes.")

    moment = midnight(effective_date)
    if not (deal["guarantee_start_utc"] <= moment < deal["guarantee_end_utc"]):
        raise ApiError("ERR_ATTRITION_OUTSIDE_GUARANTEE",
                       "The event's effective date falls outside the guarantee window.")

    record = new_record(ledger=True)
    record.update({
        "deal_id": deal_id,
        "account_id": account_id,
        "event_type": event_type,
        "effective_date": effective_date.isoformat(),
        "mrr_delta_cents": delta,
        "attributed_to": attributed_to,
        "recorded_by_role": role,
        "_recorded_by_user_id": user_id,
    })
    store.attrition_events[record["id"]] = record

    current = account["current_mrr_cents"] or 0
    if event_type == "CANCELLED":
        if account["transfer_status"] == "TRANSFERRED":
            account["transfer_status"] = "LOST"
        account["current_mrr_cents"] = 0
        touch(account)
    elif event_type == "DOWNGRADED":
        reduced = current - abs(delta)
        account["current_mrr_cents"] = reduced if reduced > 0 else 0
        touch(account)
    else:
        if account["transfer_status"] == "LOST":
            account["transfer_status"] = "TRANSFERRED"
        ceiling = account["verified_recurring_mrr_cents"] or 0
        restored = current + delta
        account["current_mrr_cents"] = restored if restored < ceiling else ceiling
        touch(account)

    recompute_deal_ledger(deal)
    return object_response(event_json(record), 201)


@bp.get("/attrition-events/<identifier>")
def read_event(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    existing = store.attrition_events.get(identifier)
    if existing is not None:
        deal = store.deals.get(existing["deal_id"])
        if deal is not None:
            guard_deal(deal, store.route_listings.get(deal["listing_id"]))
    path_uuid(identifier)
    return object_response(event_json(get_event(identifier)))


@bp.get("/attrition-events")
def list_events():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in
               ("deal_id", "account_id", "event_type", "attributed_to")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.attrition_events, keep), event_json, limit, offset)
