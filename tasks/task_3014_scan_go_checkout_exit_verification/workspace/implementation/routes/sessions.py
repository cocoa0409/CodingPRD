"""Scan session and scan line endpoints."""

from flask import Blueprint, request

from db import STORE, new_entity, touch, iso_from_dt, new_id
from errors import (
    ApiError,
    ERR_CATALOG_ITEM_NOT_FOUND,
    ERR_CLUB_OFFLINE,
    ERR_CLUB_SCAN_GO_DISABLED,
    ERR_EARLY_HOURS_NOT_ELIGIBLE,
    ERR_EMPTY_CART,
    ERR_INTERCEPT_PENDING,
    ERR_INVALID_QUANTITY,
    ERR_INVALID_REQUEST,
    ERR_INVALID_WEIGHT,
    ERR_MEMBER_INACTIVE,
    ERR_MEMBER_NOT_FOUND,
    ERR_RESTRICTED_BLOCKED_EARLY_HOURS,
    ERR_RESTRICTED_BLOCKED_OFFLINE,
    ERR_SCAN_SESSION_NOT_FOUND,
    ERR_SESSION_ALREADY_ACTIVE,
    ERR_SESSION_NOT_OPEN,
    ERR_SESSION_NOT_PAID,
    ERR_SESSION_NOT_VOIDABLE,
    ERR_TENDER_DECLINED,
    ERR_VERIFICATION_METHOD_NOT_ENABLED,
)
from logic import (
    REWARD_RATE,
    SESSION_SCANNABLE,
    SESSION_TERMINAL,
    compute_gross,
    evaluate_offer,
    get_club,
    get_session,
    get_scan_line,
    is_int,
    pending_intercepts,
    recompute_session,
    reopen_session_if_clear,
    reprice_line_at_pay,
    serialize,
    session_lines,
    shopping_window,
    sort_items,
)
from middleware import (
    check_ownership,
    get_body,
    get_context,
    get_pagination,
    paginate,
    require_fields,
    require_role,
)
from response import success

bp = Blueprint("sessions", __name__)


def _own_session(user_id, session_id):
    session = get_session(session_id)
    check_ownership(user_id, session["member_id"])
    return session


@bp.post("/scan-sessions")
def create_session():
    user_id, role = get_context()
    require_role(role, ["Member"])
    body = get_body()
    require_fields(body, ["club_id"])
    club_id = body["club_id"]
    if not isinstance(club_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "club_id must be a string.", 400)
    club = get_club(club_id)
    member = STORE.members.get(user_id)
    if not member:
        raise ApiError(ERR_MEMBER_NOT_FOUND, "Member id does not exist.", 404)

    window = shopping_window(club)
    if window == "CLOSED":
        raise ApiError(ERR_EARLY_HOURS_NOT_ELIGIBLE,
                       "Shopping has not opened yet at this club.", 403)
    if window == "EARLY" and member["tier"] != "PLUS":
        raise ApiError(ERR_EARLY_HOURS_NOT_ELIGIBLE,
                       "Early-shopping window is reserved for PLUS members.", 403)
    if member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_INACTIVE, "Member is SUSPENDED.", 409)
    if not club["scan_go_enabled"]:
        raise ApiError(ERR_CLUB_SCAN_GO_DISABLED,
                       "Scan-and-Go is disabled at this club.", 409)
    if club["connectivity_posture"] == "OFFLINE_FALLBACK":
        raise ApiError(ERR_CLUB_OFFLINE,
                       "Club connectivity is OFFLINE_FALLBACK; no new scan sessions.", 409)
    for s in STORE.sessions.values():
        if s["member_id"] == member["id"] and s["club_id"] == club["id"] \
                and s["status"] not in SESSION_TERMINAL:
            raise ApiError(ERR_SESSION_ALREADY_ACTIVE,
                           "Member already has a non-terminal scan session at this club.", 409)

    session = new_entity()
    session.update({
        "member_id": member["id"],
        "club_id": club["id"],
        "status": "OPEN",
        "receipt_code": None,
        "provisional_total_cents": 0,
        "final_total_cents": None,
        "refunded_cents": 0,
        "qualifying_cents": 0,
        "rewards_contribution_cents": 0,
        "rewards_settled": False,
        "scanned_item_count": 0,
        "paid_at": None,
        "_next_scan_seq": 1,
    })
    STORE.sessions[session["id"]] = session
    return success(serialize(session), status=201)


@bp.get("/scan-sessions/<session_id>")
def get_session_route(session_id):
    get_context()
    return success(serialize(get_session(session_id)))


@bp.get("/scan-sessions")
def list_sessions():
    get_context()
    limit, offset = get_pagination(request.args)
    sessions = list(STORE.sessions.values())
    for f in ("club_id", "member_id", "status"):
        v = request.args.get(f)
        if v is not None:
            sessions = [s for s in sessions if s[f] == v]
    sessions = sort_items(sessions)
    page, page_meta = paginate(sessions, limit, offset)
    return success([serialize(s) for s in page], response_type="array", pagination=page_meta)


@bp.post("/scan-sessions/<session_id>/lines")
def scan_line(session_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    session = get_session(session_id)
    check_ownership(user_id, session["member_id"])

    body = get_body()
    require_fields(body, ["catalog_item_id"])
    catalog_item_id = body["catalog_item_id"]
    if not isinstance(catalog_item_id, str):
        raise ApiError(ERR_INVALID_REQUEST, "catalog_item_id must be a string.", 400)

    # State check before item existence: a scan on a non-scannable session is
    # rejected ERR_SESSION_NOT_OPEN regardless of the item reference.
    if session["status"] not in SESSION_SCANNABLE:
        raise ApiError(ERR_SESSION_NOT_OPEN,
                       "Session is not in a state allowing scans.", 409)

    club = STORE.clubs[session["club_id"]]
    member = STORE.members[session["member_id"]]
    window = shopping_window(club)

    item = STORE.catalog_items.get(catalog_item_id)
    if not item or item["club_id"] != session["club_id"] or item["status"] != "ACTIVE":
        raise ApiError(ERR_CATALOG_ITEM_NOT_FOUND,
                       "Catalog item does not exist, is DELISTED, or belongs to another club.",
                       404)

    restricted = item["restricted_class"] != "NONE"
    if window == "EARLY":
        if restricted:
            raise ApiError(ERR_RESTRICTED_BLOCKED_EARLY_HOURS,
                           "Restricted items cannot be scanned during the early-shopping window.",
                           409)
        if not item["early_hours_eligible"]:
            raise ApiError(ERR_CATALOG_ITEM_NOT_FOUND,
                           "Item is not eligible for early-hours scanning.", 404)
    if restricted and club["connectivity_posture"] == "OFFLINE_FALLBACK":
        raise ApiError(ERR_RESTRICTED_BLOCKED_OFFLINE,
                       "Restricted items cannot be scanned while the club is OFFLINE_FALLBACK.",
                       409)

    # Request-shape checks (rank last among business failures).
    if item["pricing_mode"] == "UNIT":
        if "quantity" not in body or body["quantity"] is None or \
                not is_int(body["quantity"]) or body["quantity"] < 1:
            raise ApiError(ERR_INVALID_QUANTITY,
                           "quantity is required for a UNIT item and must be >= 1.", 400)
        if "weight_grams" in body and body["weight_grams"] is not None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "weight_grams is inconsistent with a UNIT item.", 400)
        quantity = body["quantity"]
        weight_grams = None
    else:
        if "weight_grams" not in body or body["weight_grams"] is None or \
                not is_int(body["weight_grams"]) or body["weight_grams"] <= 0:
            raise ApiError(ERR_INVALID_WEIGHT,
                           "weight_grams is required for a WEIGHTED item and must be > 0.", 400)
        if "quantity" in body and body["quantity"] is not None:
            raise ApiError(ERR_INVALID_REQUEST,
                           "quantity is inconsistent with a WEIGHTED item.", 400)
        quantity = None
        weight_grams = body["weight_grams"]

    gross = compute_gross(item["pricing_mode"], item["unit_price_cents"],
                          item["price_per_pound_cents"], quantity, weight_grams)
    offer_id, offer_units, savings = evaluate_offer(
        club, member, item["id"], item["pricing_mode"], quantity, weight_grams)
    line_total = max(0, gross - savings)

    line = new_entity()
    line.update({
        "session_id": session["id"],
        "catalog_item_id": item["id"],
        "scan_seq": session["_next_scan_seq"],
        "pricing_mode_snapshot": item["pricing_mode"],
        "unit_price_cents_snapshot": item["unit_price_cents"],
        "price_per_pound_cents_snapshot": item["price_per_pound_cents"],
        "restricted_class_snapshot": item["restricted_class"],
        "quantity": quantity,
        "weight_grams": weight_grams,
        "line_gross_cents": gross,
        "offer_id_applied": offer_id,
        "offer_units_applied": offer_units,
        "line_savings_cents": savings,
        "line_total_cents": line_total,
        "status": "INTERCEPTED" if restricted else "SCANNED",
    })
    session["_next_scan_seq"] += 1
    STORE.scan_lines[line["id"]] = line

    if restricted:
        intercept = new_entity()
        intercept.update({
            "session_id": session["id"],
            "scan_line_id": line["id"],
            "club_id": session["club_id"],
            "restricted_class": item["restricted_class"],
            "associate_id": None,
            "decision": None,
            "status": "PENDING",
        })
        STORE.intercepts[intercept["id"]] = intercept
        if session["status"] == "OPEN":
            session["status"] = "REVIEW_HOLD"

    recompute_session(session)
    touch(session)
    return success(serialize(line), status=201)


@bp.get("/scan-sessions/<session_id>/lines")
def list_lines(session_id):
    get_context()
    session = get_session(session_id)
    limit, offset = get_pagination(request.args)
    lines = [l for l in STORE.scan_lines.values() if l["session_id"] == session["id"]]
    v = request.args.get("status")
    if v is not None:
        lines = [l for l in lines if l["status"] == v]
    lines = sort_items(lines)
    page, page_meta = paginate(lines, limit, offset)
    return success([serialize(l) for l in page], response_type="array", pagination=page_meta)


@bp.get("/scan-lines/<line_id>")
def get_line_route(line_id):
    get_context()
    return success(serialize(get_scan_line(line_id)))


@bp.post("/scan-lines/<line_id>/remove")
def remove_line(line_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    line = get_scan_line(line_id)
    session = STORE.sessions[line["session_id"]]
    check_ownership(user_id, session["member_id"])
    if session["status"] not in SESSION_SCANNABLE:
        raise ApiError(ERR_SESSION_NOT_OPEN,
                       "Session is not in a state allowing line removal.", 409)
    if line["status"] == "REMOVED":
        raise ApiError(ERR_INVALID_REQUEST, "Line is already REMOVED.", 400)
    line["status"] = "REMOVED"
    touch(line)
    recompute_session(session)
    touch(session)
    return success(serialize(line))


@bp.post("/scan-sessions/<session_id>/pay")
def pay(session_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    session = get_session(session_id)
    check_ownership(user_id, session["member_id"])

    member = STORE.members[session["member_id"]]
    club = STORE.clubs[session["club_id"]]

    if session["status"] not in ("OPEN", "REVIEW_HOLD", "OFFLINE_PAUSED"):
        raise ApiError(ERR_SESSION_NOT_OPEN,
                       "Session is not in a state allowing payment.", 409)
    if session["status"] == "OFFLINE_PAUSED" and not club["allow_offline_payment"]:
        raise ApiError(ERR_SESSION_NOT_OPEN,
                       "Offline payment is not enabled at this club.", 409)
    if member["status"] != "ACTIVE":
        raise ApiError(ERR_MEMBER_INACTIVE, "Member is SUSPENDED.", 409)
    if pending_intercepts(session["id"]):
        raise ApiError(ERR_INTERCEPT_PENDING,
                       "A restricted intercept is still pending for this session.", 409)
    lines = session_lines(session["id"])
    if not lines:
        raise ApiError(ERR_EMPTY_CART, "Payment attempted with zero non-REMOVED lines.", 409)
    if member["tender_status"] != "OK":
        raise ApiError(ERR_TENDER_DECLINED,
                       "Member's membership-linked tender is DECLINED.", 402)

    if session["status"] == "OFFLINE_PAUSED":
        final_total = session["provisional_total_cents"]
        qualifying = sum(l["line_total_cents"] for l in lines
                         if l["restricted_class_snapshot"] == "NONE")
    else:
        final_total = 0
        qualifying = 0
        for l in lines:
            lt = reprice_line_at_pay(l, club, member)
            final_total += lt
            if l["restricted_class_snapshot"] == "NONE":
                qualifying += lt

    session["final_total_cents"] = final_total
    session["qualifying_cents"] = qualifying
    session["receipt_code"] = "rc_" + new_id().replace("-", "")[:16]
    session["paid_at"] = iso_from_dt(STORE.now())
    session["status"] = "PAID"

    contribution = 0
    if member["tier"] == "PLUS":
        contribution = (qualifying * REWARD_RATE) // 100
        member["cash_rewards_pending_cents"] += contribution
    session["rewards_contribution_cents"] = contribution
    member["lifetime_charged_cents"] += final_total
    touch(member)
    touch(session)
    return success(serialize(session))


@bp.post("/scan-sessions/<session_id>/void-payment")
def void_payment(session_id):
    _, role = get_context()
    require_role(role, ["LossPreventionOfficer"])
    session = get_session(session_id)
    if session["status"] not in ("PAID", "EXIT_PENDING", "FLAGGED"):
        raise ApiError(ERR_SESSION_NOT_VOIDABLE,
                       "void-payment requires session in PAID, EXIT_PENDING, or FLAGGED.", 409)
    member = STORE.members[session["member_id"]]

    session["refunded_cents"] = session["final_total_cents"]
    member["lifetime_charged_cents"] -= session["final_total_cents"]
    member["cash_rewards_pending_cents"] = max(
        0, member["cash_rewards_pending_cents"] - session["rewards_contribution_cents"])
    session["receipt_code"] = None
    for v in STORE.exit_verifications.values():
        if v["session_id"] == session["id"] and v["status"] == "PENDING":
            v["status"] = "EXPIRED"
            touch(v)
    session["status"] = "VOIDED"
    touch(member)
    touch(session)
    return success(serialize(session))


@bp.post("/scan-sessions/<session_id>/exit-scan")
def exit_scan(session_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    session = get_session(session_id)
    check_ownership(user_id, session["member_id"])
    body = get_body()

    if session["status"] != "PAID":
        raise ApiError(ERR_SESSION_NOT_PAID,
                       "Exit verification requires a PAID session.", 409)
    club = STORE.clubs[session["club_id"]]
    method = body.get("method")
    if method is None:
        if club["exit_verification_mode"] == "BOTH":
            method = "RECEIPT_CODE"
        else:
            method = club["exit_verification_mode"]
    if method not in ("RECEIPT_CODE", "CV_ARCH"):
        raise ApiError(ERR_INVALID_REQUEST,
                       "method must be RECEIPT_CODE or CV_ARCH.", 400)
    if club["exit_verification_mode"] != "BOTH" and club["exit_verification_mode"] != method:
        raise ApiError(ERR_VERIFICATION_METHOD_NOT_ENABLED,
                       "Requested verification method is not enabled at this club.", 409)

    verification = new_entity()
    verification.update({
        "session_id": session["id"],
        "club_id": session["club_id"],
        "method": method,
        "status": "PENDING",
        "expected_item_count": session["scanned_item_count"],
        "cv_observed_item_count": None,
        "flagging_associate_id": None,
    })
    STORE.exit_verifications[verification["id"]] = verification
    session["status"] = "EXIT_PENDING"
    touch(session)
    return success(serialize(verification), status=201)


@bp.post("/scan-sessions/<session_id>/abandon")
def abandon(session_id):
    user_id, role = get_context()
    require_role(role, ["Member"])
    session = get_session(session_id)
    check_ownership(user_id, session["member_id"])
    if session["status"] not in SESSION_SCANNABLE:
        raise ApiError(ERR_SESSION_NOT_OPEN,
                       "Session is not in a state that can be abandoned.", 409)
    for line in session_lines(session["id"]):
        line["status"] = "REMOVED"
        touch(line)
    for intercept in pending_intercepts(session["id"]):
        intercept["status"] = "EXPIRED"
        touch(intercept)
    session["status"] = "ABANDONED"
    recompute_session(session)
    touch(session)
    return success(serialize(session))
