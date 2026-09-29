"""Permit transfers: filing, the regulator's answer and reciprocity waivers."""

from flask import Blueprint, request

from auth import begin, guard_buyer_id, guard_deal
from calc import add_days, fmt_date, parse_date
from errors import ApiError
from responses import list_response, object_response, pagination
from serializers import transfer_json
from services import get_transfer
from store import ordered, store, touch
from validators import bad, body, path_uuid, req_date, req_enum, req_str

bp = Blueprint("licenses", __name__)

OPEN_FOR_APPLY = ("NOT_STARTED", "DENIED")


def _deal_of(transfer):
    return store.deals.get(transfer["deal_id"])


def _buyer_of(transfer):
    deal = _deal_of(transfer)
    if deal is None:
        return None
    return store.buyers.get(deal["buyer_id"])


def _profile_of(transfer):
    return store.state_license_profiles.get(transfer["state_profile_id"])


def _require_profile(transfer):
    profile = _profile_of(transfer)
    if profile is None or transfer["permit_type"] not in profile["required_permit_types"]:
        raise ApiError("ERR_STATE_PROFILE_MISSING",
                       "No licensing profile exists for the listing's state, or the permit type "
                       "is not one that profile requires.")
    return profile


@bp.get("/license-transfers/<identifier>")
def read_transfer(identifier):
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    existing = store.license_transfers.get(identifier)
    if existing is not None:
        deal = _deal_of(existing)
        if deal is not None:
            guard_deal(deal, store.route_listings.get(deal["listing_id"]))
    path_uuid(identifier)
    return object_response(transfer_json(get_transfer(identifier)))


@bp.get("/license-transfers")
def list_transfers():
    begin("Broker", "PlatformAdmin", "Seller", "Buyer")
    limit, offset = pagination()
    filters = {key: request.args.get(key) for key in
               ("deal_id", "state_profile_id", "permit_type", "status")}

    def keep(row):
        for key, value in filters.items():
            if value is not None and row.get(key) != value:
                return False
        return True

    return list_response(ordered(store.license_transfers, keep), transfer_json, limit, offset)


def _window_conflict(transfer, profile, start, end):
    """Closed [applied_on, processing_window_end] intervals for the same buyer, state and
    permit type; touching conflicts and a gap below cooling_off_days conflicts."""
    buyer = _buyer_of(transfer)
    buyer_id = buyer["id"] if buyer is not None else None
    cooling = profile["cooling_off_days"]
    for other in ordered(store.license_transfers):
        if other["status"] == "CANCELLED":
            continue
        if other["applied_on"] is None or other["processing_window_end"] is None:
            continue
        if other["permit_type"] != transfer["permit_type"]:
            continue
        other_profile = _profile_of(other)
        if other_profile is None or other_profile["state_code"] != profile["state_code"]:
            continue
        other_buyer = _buyer_of(other)
        if (other_buyer["id"] if other_buyer is not None else None) != buyer_id:
            continue
        other_start = parse_date(other["applied_on"])
        other_end = parse_date(other["processing_window_end"])
        if start <= other_end and other_start <= end:
            return True
        gap = (start - other_end).days if start > other_end else (other_start - end).days
        if gap < cooling:
            return True
    return False


@bp.post("/license-transfers/<identifier>/apply")
def apply_transfer(identifier):
    begin("Buyer")
    existing = store.license_transfers.get(identifier)
    if existing is not None:
        deal = _deal_of(existing)
        if deal is not None:
            guard_buyer_id(deal["buyer_id"])
    data = body()
    applied_on = req_date(data, "applied_on")
    path_uuid(identifier)
    transfer = get_transfer(identifier)

    profile = _profile_of(transfer)
    buyer = _buyer_of(transfer)
    if profile is not None and buyer is not None:
        if buyer["license_status"] == "NONE" and not profile["provisional_operation_allowed"]:
            bad("The buyer may not operate in this state and no provisional operation is allowed.")

    if transfer["status"] not in OPEN_FOR_APPLY:
        raise ApiError("ERR_LICENSE_TRANSFER_NOT_PENDING",
                       "A filing is only available from NOT_STARTED or DENIED.")
    profile = _require_profile(transfer)

    window_end = add_days(applied_on, profile["transfer_processing_days"])
    if _window_conflict(transfer, profile, applied_on, window_end):
        raise ApiError("ERR_LICENSE_WINDOW_CONFLICT",
                       "The application collides with, or falls inside the cooling-off shadow "
                       "of, another live application.")

    retry = transfer["status"] == "DENIED"
    transfer["status"] = "APPLIED"
    transfer["applied_on"] = fmt_date(applied_on)
    transfer["processing_window_end"] = fmt_date(window_end)
    transfer["attempt_count"] += 1
    if not retry:
        transfer["decided_on"] = None
        transfer["denial_reason_code"] = None
    touch(transfer)
    return object_response(transfer_json(transfer))


@bp.post("/license-transfers/<identifier>/decide")
def decide_transfer(identifier):
    begin("PlatformAdmin")
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "DENY"))
    decided_on = req_date(data, "decided_on")
    reason = None
    if decision == "DENY":
        reason = req_str(data, "denial_reason_code", min_len=1)
    path_uuid(identifier)
    transfer = get_transfer(identifier)

    if transfer["applied_on"] is not None and decided_on < parse_date(transfer["applied_on"]):
        bad("Field 'decided_on' may not precede 'applied_on'.")
    if transfer["status"] != "APPLIED":
        raise ApiError("ERR_LICENSE_TRANSFER_NOT_PENDING",
                       "A decision is only available on an APPLIED transfer.")

    transfer["decided_on"] = fmt_date(decided_on)
    if decision == "APPROVE":
        transfer["status"] = "APPROVED"
    else:
        transfer["status"] = "DENIED"
        transfer["denial_reason_code"] = reason
    touch(transfer)
    return object_response(transfer_json(transfer))


@bp.post("/license-transfers/<identifier>/waive")
def waive_transfer(identifier):
    begin("Broker")
    body()
    path_uuid(identifier)
    transfer = get_transfer(identifier)

    if transfer["status"] != "NOT_STARTED":
        raise ApiError("ERR_LICENSE_TRANSFER_NOT_PENDING",
                       "A waiver is only available from NOT_STARTED.")
    profile = _require_profile(transfer)
    buyer = _buyer_of(transfer)
    if (buyer is None or buyer["license_status"] != "LICENSED"
            or buyer["state_code"] not in profile["reciprocity_states"]):
        raise ApiError("ERR_RECIPROCITY_NOT_AVAILABLE",
                       "The buyer's licensure does not support a reciprocity waiver.")

    transfer["status"] = "WAIVED"
    transfer["waiver_basis"] = "RECIPROCITY_" + buyer["state_code"]
    touch(transfer)
    return object_response(transfer_json(transfer))
