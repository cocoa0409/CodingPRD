"""Marketplace enforcement cases: intake, resolve (with dealer OCC and the
PROBATION/SUSPEND threshold cascades), and overturn."""
from datetime import timedelta
from flask import Blueprint, request

from auth import context, require_roles
from calc import dealer_infraction_points, forfeit_allocations_for_dealer
from constants import (
    INFRACTION_EXPIRY_DAYS, INFRACTION_POINTS, PROBATION_THRESHOLD,
    SUSPEND_THRESHOLD,
)
from envelope import (
    get_body, new_entity, opt_enum, opt_int, opt_str, req_enum, req_str,
    sort_created, success, success_list, touch,
)
from errors import fail
from serialize import ser_case
from store import DB, get_clock

bp = Blueprint("enforcement", __name__)

MARKETPLACES = ("AMAZON", "EBAY", "WALMART", "OTHER")
CATEGORIES = ("MAP_VIOLATION", "UNAUTHORIZED_MARKETPLACE", "BRAND_STANDARD", "CHANNEL_DIVERSION")


def load_case(case_id):
    c = DB.cases.get(case_id)
    if c is None:
        fail("ERR_CASE_NOT_FOUND", "no enforcement case with id %s" % case_id)
    return c


@bp.post("/drinkware/enforcement-cases")
def create_case():
    _, role = context()
    require_roles(role, ["ChannelManager"])
    body = get_body()
    marketplace = req_enum(body, "marketplace", MARKETPLACES)
    seller_handle = req_str(body, "seller_handle")
    listing_url = req_str(body, "listing_url")
    matched_dealer_id = opt_str(body, "matched_dealer_id")
    if matched_dealer_id is not None and matched_dealer_id not in DB.dealers:
        fail("ERR_DEALER_NOT_FOUND", "no dealer with id %s" % matched_dealer_id)
    case = new_entity({
        "marketplace": marketplace,
        "seller_handle": seller_handle,
        "listing_url": listing_url,
        "matched_dealer_id": matched_dealer_id,
        "status": "UNDER_REVIEW",
        "infraction_category": None,
        "infraction_points": 0,
        "infraction_issued_at": None,
        "infraction_expires_at": None,
        "resolution_notes": None,
    })
    DB.cases[case["id"]] = case
    return success(ser_case(case), 201)


@bp.get("/drinkware/enforcement-cases/<case_id>")
def get_case(case_id):
    _, role = context()
    require_roles(role, ["ChannelManager", "PlatformAdmin"])
    return success(ser_case(load_case(case_id)))


@bp.get("/drinkware/enforcement-cases")
def list_cases():
    _, role = context()
    require_roles(role, ["ChannelManager", "PlatformAdmin"])
    matched = request.args.get("matched_dealer_id")
    status = request.args.get("status")
    marketplace = request.args.get("marketplace")
    items = sort_created(list(DB.cases.values()))
    if matched is not None:
        items = [c for c in items if c["matched_dealer_id"] == matched]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    if marketplace is not None:
        items = [c for c in items if c["marketplace"] == marketplace]
    return success_list([ser_case(c) for c in items])


@bp.post("/drinkware/enforcement-cases/<case_id>/resolve")
def resolve_case(case_id):
    _, role = context()
    require_roles(role, ["ChannelManager"])
    case = load_case(case_id)
    body = get_body()
    outcome = req_enum(body, "outcome",
                       ("CONFIRMED_VIOLATION", "DISMISSED", "ESCALATED_LEGAL"))
    category = opt_enum(body, "infraction_category", CATEGORIES)
    notes = opt_str(body, "resolution_notes")
    expected_version = opt_int(body, "expected_dealer_version")
    matched_id = case["matched_dealer_id"]
    # Conditionally-required fields (priority 3) before state (5) and OCC (6).
    if outcome == "CONFIRMED_VIOLATION" and matched_id is not None:
        if category is None:
            fail("ERR_INVALID_REQUEST",
                 "infraction_category is required when confirming a matched case")
        if expected_version is None:
            fail("ERR_INVALID_REQUEST",
                 "expected_dealer_version is required when confirming a matched case")
    # State: target resource must permit the requested transition.
    if outcome == "ESCALATED_LEGAL":
        allowed_from = ("UNDER_REVIEW",)
    else:
        allowed_from = ("UNDER_REVIEW", "ESCALATED_LEGAL")
    if case["status"] not in allowed_from:
        fail("ERR_INVALID_STATE_TRANSITION",
             "case in status %s cannot be resolved as %s" % (case["status"], outcome))
    dealer = DB.dealers.get(matched_id) if matched_id is not None else None
    if outcome == "CONFIRMED_VIOLATION" and dealer is not None:
        if expected_version != dealer["version"]:
            fail("ERR_STALE_DEALER_VERSION",
                 "expected_dealer_version does not match the dealer's current version")

    if notes is not None:
        case["resolution_notes"] = notes
    if outcome == "ESCALATED_LEGAL":
        case["status"] = "ESCALATED_LEGAL"
        touch(case)
        return success(ser_case(case))
    if outcome == "DISMISSED":
        case["status"] = "DISMISSED"
        touch(case)
        return success(ser_case(case))

    # CONFIRMED_VIOLATION
    case["status"] = "CONFIRMED_VIOLATION"
    if category is not None:
        case["infraction_category"] = category
    if dealer is not None:
        case["infraction_points"] = INFRACTION_POINTS[category]
        case["infraction_issued_at"] = get_clock()
        case["infraction_expires_at"] = get_clock() + timedelta(days=INFRACTION_EXPIRY_DAYS)
    touch(case)
    if dealer is not None:
        # The confirmation legitimately accumulates onto the dealer's standing.
        touch(dealer)
        points = dealer_infraction_points(dealer["id"])
        # Threshold crossings only tighten standing, and only at resolve time.
        if points >= SUSPEND_THRESHOLD and dealer["status"] in ("AUTHORIZED", "PROBATION"):
            dealer["status"] = "SUSPENDED"
            forfeit_allocations_for_dealer(dealer["id"], "DEALER_SUSPENDED")
            touch(dealer)
        elif points >= PROBATION_THRESHOLD and dealer["status"] == "AUTHORIZED":
            dealer["status"] = "PROBATION"
            touch(dealer)
    return success(ser_case(case))


@bp.post("/drinkware/enforcement-cases/<case_id>/overturn")
def overturn_case(case_id):
    _, role = context()
    require_roles(role, ["ChannelManager"])
    case = load_case(case_id)
    body = get_body()
    reason = req_str(body, "reason")
    expected_version = opt_int(body, "expected_dealer_version")
    matched_id = case["matched_dealer_id"]
    dealer = DB.dealers.get(matched_id) if matched_id is not None else None
    if dealer is not None and expected_version is None:
        fail("ERR_INVALID_REQUEST",
             "expected_dealer_version is required when overturning a matched case")
    if case["status"] != "CONFIRMED_VIOLATION":
        fail("ERR_INVALID_STATE_TRANSITION",
             "only a CONFIRMED_VIOLATION case can be overturned")
    if dealer is not None and expected_version != dealer["version"]:
        fail("ERR_STALE_DEALER_VERSION",
             "expected_dealer_version does not match the dealer's current version")
    case["status"] = "OVERTURNED"
    case["resolution_notes"] = reason
    touch(case)
    if dealer is not None:
        # Points recompute excludes this case; standing is NOT auto-restored.
        touch(dealer)
    return success(ser_case(case))
