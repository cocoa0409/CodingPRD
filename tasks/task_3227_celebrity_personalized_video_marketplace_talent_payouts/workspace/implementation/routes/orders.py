"""Order endpoints and order-scoped sub-resources (videos, re-record
requests, disputes, license grants)."""
from flask import Blueprint, request

import db
import services as svc
from errors import err, parse_pagination, paginate
from middleware import (authenticate, require_role, get_json_body, req_str,
                        req_enum, req_int, req_iso, opt_int)
from response import envelope, envelope_list

bp = Blueprint("orders", __name__)

USE_TYPES = {"PERSONAL", "BUSINESS_USE", "ADVERTISING_USE"}
LICENSE_TYPES = {"BUSINESS", "ADVERTISING"}
TERRITORIES = {"DOMESTIC", "GLOBAL"}


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def order_public(o):
    out = {k: o[k] for k in (
        "id", "talent_id", "buyer_id", "use_type", "occasion",
        "script_instructions", "recipient_name", "status",
        "gross_amount_cents", "platform_commission_cents", "talent_net_cents",
        "screening_token", "screening_flags", "acceptance_deadline",
        "delivery_deadline", "delivered_at", "re_record_count",
        "auto_confirm_at", "refund_amount_cents", "platform_absorbed_cents",
        "clawback_cents", "created_at", "updated_at", "version")}
    if o["status"] == "DELIVERED":
        # Provisional commission preview at read time (not persisted).
        talent = db.talents.get(o["talent_id"])
        if talent is not None:
            commission, net = svc.commission_for(talent["commission_tier"],
                                                 o["gross_amount_cents"])
            out["provisional_platform_commission_cents"] = commission
            out["provisional_talent_net_cents"] = net
    return out


def video_public(v):
    return {k: v[k] for k in (
        "id", "order_id", "content_url", "duration_seconds", "version_no",
        "moderation_status", "flagged_reason", "created_at", "updated_at",
        "version")}


def rerecord_public(r):
    return {k: r[k] for k in (
        "id", "order_id", "notes", "status", "created_at", "updated_at",
        "version")}


def dispute_public(d):
    return {k: d[k] for k in (
        "id", "order_id", "reason", "status", "refund_to_buyer_cents",
        "resolution_notes", "created_at", "updated_at", "version")}


def license_public(l):
    return {k: l[k] for k in (
        "id", "order_id", "license_type", "territory", "channels",
        "starts_at", "ends_at", "fee_cents", "status", "created_at",
        "updated_at", "version")}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise err("ERR_NOT_FOUND", "order %s not found" % oid)
    return o


def _require_buyer_owner(order, user_id):
    if user_id != order["buyer_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "X-User-ID does not match the order buyer_id")


def _require_talent_owner(order, user_id):
    if user_id != order["talent_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "X-User-ID does not match the order talent_id")


def _latest_video(order_id):
    vids = [v for v in db.videos.values() if v["order_id"] == order_id]
    if not vids:
        return None
    return max(vids, key=lambda v: v["version_no"])


def _latest_video_cleared(order_id):
    v = _latest_video(order_id)
    return v is not None and v["moderation_status"] == "CLEARED"


def _has_open_dispute(order_id):
    return any(d["order_id"] == order_id and d["status"] == "OPEN"
               for d in db.disputes.values())


def _any_dispute(order_id):
    return any(d["order_id"] == order_id for d in db.disputes.values())


def _check_moderation_gate(order_id):
    if not _latest_video_cleared(order_id):
        raise err("ERR_VIDEO_NOT_CLEARED",
                  "latest video on the order is not CLEARED")


def _check_no_open_dispute(order_id):
    if _has_open_dispute(order_id):
        raise err("ERR_INVALID_STATE", "an open dispute exists for this order")


# ---------------------------------------------------------------------------
# Create / read orders
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders")
def create_order():
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    body = get_json_body()
    talent_id = req_str(body, "talent_id")
    buyer_id = req_str(body, "buyer_id")
    use_type = req_enum(body, "use_type", USE_TYPES)
    occasion = req_str(body, "occasion")
    script_instructions = req_str(body, "script_instructions", min_len=1, max_len=2000)
    recipient_name = req_str(body, "recipient_name")

    # existence (priority 3) for body-referenced ids
    talent = db.talents.get(talent_id)
    if talent is None:
        raise err("ERR_NOT_FOUND", "talent %s not found" % talent_id)
    buyer = db.buyers.get(buyer_id)
    if buyer is None:
        raise err("ERR_NOT_FOUND", "buyer %s not found" % buyer_id)

    if user_id != buyer_id:
        raise err("ERR_NOT_RESOURCE_OWNER",
                  "X-User-ID must equal the buyer_id of the order")

    # business rules
    if talent["status"] != "ACTIVE" or talent["availability"] != "BOOKABLE":
        raise err("ERR_TALENT_NOT_BOOKABLE",
                  "talent is not ACTIVE with BOOKABLE availability")
    if use_type in ("BUSINESS_USE", "ADVERTISING_USE") and not buyer["is_business_account"]:
        raise err("ERR_BUSINESS_ACCOUNT_REQUIRED",
                  "commercial use types require a business buyer account")
    if buyer["status"] == "BLOCKED":
        raise err("ERR_INVALID_STATE", "blocked buyers cannot place new requests")

    rate_field = {"PERSONAL": "personal_rate_cents",
                  "BUSINESS_USE": "business_rate_cents",
                  "ADVERTISING_USE": "advertising_rate_cents"}[use_type]
    gross = talent[rate_field]
    if gross is None:
        raise err("ERR_TALENT_NOT_BOOKABLE",
                  "talent has no rate set for this use_type")

    flags = []
    if svc.SCREENING_MARKER in script_instructions:
        flags.append("POLICY_VIOLATION")

    order = svc.make_record(db.orders, {
        "talent_id": talent_id,
        "buyer_id": buyer_id,
        "use_type": use_type,
        "occasion": occasion,
        "script_instructions": script_instructions,
        "recipient_name": recipient_name,
        "status": "SCREENING",
        "gross_amount_cents": gross,
        "platform_commission_cents": None,
        "talent_net_cents": None,
        "screening_token": "scr_" + db.new_id(),
        "screening_flags": flags,
        "acceptance_deadline": None,
        "delivery_deadline": None,
        "delivered_at": None,
        "re_record_count": 0,
        "auto_confirm_at": None,
        "refund_amount_cents": 0,
        "platform_absorbed_cents": 0,
        "clawback_cents": 0,
        # Internal bookkeeping for the rolling 365-day trailing GMV window
        # (PRD §3.5); not part of the serialized order resource.
        "confirmed_at": None,
    })
    return envelope(order_public(order), "object", 201)


@bp.get("/marketplace/orders/<oid>")
def get_order(oid):
    _uid, role = authenticate()
    require_role(role, ["Buyer", "Talent", "PlatformAdmin", "Moderator"])
    order = _get_order(oid)
    return envelope(order_public(order), "object", 200)


@bp.get("/marketplace/orders")
def list_orders():
    _uid, role = authenticate()
    require_role(role, ["Buyer", "Talent", "PlatformAdmin", "Moderator"])
    limit, offset = parse_pagination(request.args)
    talent_f = request.args.get("talent_id")
    buyer_f = request.args.get("buyer_id")
    status_f = request.args.get("status")
    items = [o for o in db.orders.values()
             if (talent_f is None or o["talent_id"] == talent_f)
             and (buyer_f is None or o["buyer_id"] == buyer_f)
             and (status_f is None or o["status"] == status_f)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([order_public(o) for o in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Screening
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/screening-attest")
def screening_attest(oid):
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    order = _get_order(oid)
    body = get_json_body()
    token = req_str(body, "screening_token")
    if order["status"] != "SCREENING":
        raise err("ERR_INVALID_STATE", "screening-attest requires SCREENING status")
    if token != order["screening_token"]:
        raise err("ERR_INVALID_REQUEST", "screening_token does not match")
    _require_buyer_owner(order, user_id)
    if order["screening_flags"]:
        raise err("ERR_CONTENT_POLICY_FLAGGED",
                  "screening_flags is non-empty; attestation not allowed")
    now = db.clock_now()
    order["status"] = "AWAITING_ACCEPTANCE"
    order["acceptance_deadline"] = db.iso(db.hours(now, svc.ACCEPTANCE_WINDOW_HOURS))
    svc.touch(order)
    return envelope(order_public(order), "object", 200)


@bp.post("/marketplace/orders/<oid>/screening-decline")
def screening_decline(oid):
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    order = _get_order(oid)
    get_json_body(required=False)
    if order["status"] != "SCREENING":
        raise err("ERR_INVALID_STATE", "screening-decline requires SCREENING status")
    _require_buyer_owner(order, user_id)
    order["status"] = "DECLINED"
    svc.refund_to_wallet(order)
    svc.touch(order)
    return envelope(order_public(order), "object", 200)


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/accept")
def accept_order(oid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    order = _get_order(oid)
    get_json_body(required=False)
    if order["status"] != "AWAITING_ACCEPTANCE":
        raise err("ERR_INVALID_STATE", "accept requires AWAITING_ACCEPTANCE status")
    _require_talent_owner(order, user_id)
    talent = db.talents[order["talent_id"]]
    if talent["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "accepting talent must be ACTIVE")
    now = db.clock_now()
    deadline = db.parse_iso(order["acceptance_deadline"])
    if deadline is not None and now >= deadline:
        raise err("ERR_ACCEPTANCE_WINDOW_CLOSED",
                  "current logical time is at or after acceptance_deadline")
    order["status"] = "ACCEPTED"
    order["delivery_deadline"] = db.iso(db.hours(now, talent["turnaround_hours"]))
    svc.touch(order)
    return envelope(order_public(order), "object", 200)


@bp.post("/marketplace/orders/<oid>/decline")
def decline_order(oid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    order = _get_order(oid)
    get_json_body(required=False)
    if order["status"] != "AWAITING_ACCEPTANCE":
        raise err("ERR_INVALID_STATE", "decline requires AWAITING_ACCEPTANCE status")
    _require_talent_owner(order, user_id)
    order["status"] = "DECLINED"
    svc.refund_to_wallet(order)
    svc.touch(order)
    return envelope(order_public(order), "object", 200)


# ---------------------------------------------------------------------------
# Videos
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/videos")
def upload_video(oid):
    user_id, role = authenticate()
    require_role(role, ["Talent"])
    order = _get_order(oid)
    body = get_json_body()
    content_url = req_str(body, "content_url")
    duration = req_int(body, "duration_seconds", min_v=5, max_v=600)
    if order["status"] not in ("ACCEPTED", "RE_RECORD_REQUESTED"):
        raise err("ERR_INVALID_STATE",
                  "video upload requires ACCEPTED or RE_RECORD_REQUESTED status")
    _require_talent_owner(order, user_id)
    now = db.clock_now()
    deadline = db.parse_iso(order["delivery_deadline"])
    if deadline is not None and now >= deadline:
        raise err("ERR_DELIVERY_DEADLINE_PASSED",
                  "current logical time is at or after delivery_deadline")

    prior = _latest_video(oid)
    version_no = 1 if prior is None else prior["version_no"] + 1
    video = svc.make_record(db.videos, {
        "order_id": oid,
        "content_url": content_url,
        "duration_seconds": duration,
        "version_no": version_no,
        "moderation_status": "PENDING_REVIEW",
        "flagged_reason": None,
    })

    order["status"] = "DELIVERED"
    order["delivered_at"] = db.iso(now)
    order["auto_confirm_at"] = db.iso(db.hours(now, svc.AUTO_CONFIRM_HOURS))
    svc.close_open_rerecords(oid)
    svc.touch(order)
    return envelope(video_public(video), "object", 201)


@bp.get("/marketplace/orders/<oid>/videos")
def list_videos(oid):
    _uid, role = authenticate()
    require_role(role, ["Buyer", "Talent", "PlatformAdmin", "Moderator"])
    _get_order(oid)
    limit, offset = parse_pagination(request.args)
    items = [v for v in db.videos.values() if v["order_id"] == oid]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([video_public(v) for v in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Re-record requests
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/re-record-requests")
def create_rerecord(oid):
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    order = _get_order(oid)
    body = get_json_body()
    notes = req_str(body, "notes", min_len=1, max_len=1000)
    if order["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "re-record request requires DELIVERED status")
    _require_buyer_owner(order, user_id)
    _check_moderation_gate(oid)
    now = db.clock_now()
    auto_confirm = db.parse_iso(order["auto_confirm_at"])
    if auto_confirm is not None and now >= auto_confirm:
        raise err("ERR_BUYER_WINDOW_CLOSED",
                  "current logical time is at or after auto_confirm_at")
    _check_no_open_dispute(oid)
    if order["re_record_count"] >= svc.MAX_RERECORD_PER_ORDER:
        raise err("ERR_RERECORD_LIMIT_REACHED",
                  "re_record_count has reached the hard cap of 2")

    rr = svc.make_record(db.rerecord_requests, {
        "order_id": oid,
        "notes": notes,
        "status": "OPEN",
    })
    order["re_record_count"] += 1
    order["status"] = "RE_RECORD_REQUESTED"
    svc.touch(order)
    return envelope(rerecord_public(rr), "object", 200)


@bp.get("/marketplace/orders/<oid>/re-record-requests")
def list_rerecords(oid):
    _uid, role = authenticate()
    require_role(role, ["Buyer", "Talent", "PlatformAdmin"])
    _get_order(oid)
    limit, offset = parse_pagination(request.args)
    items = [r for r in db.rerecord_requests.values() if r["order_id"] == oid]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([rerecord_public(r) for r in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# Confirm
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/confirm")
def confirm_order(oid):
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    order = _get_order(oid)
    get_json_body(required=False)
    if order["status"] != "DELIVERED":
        raise err("ERR_INVALID_STATE", "confirm requires DELIVERED status")
    _require_buyer_owner(order, user_id)
    _check_moderation_gate(oid)
    now = db.clock_now()
    auto_confirm = db.parse_iso(order["auto_confirm_at"])
    if auto_confirm is not None and now >= auto_confirm:
        raise err("ERR_BUYER_WINDOW_CLOSED",
                  "current logical time is at or after auto_confirm_at")
    _check_no_open_dispute(oid)
    order["status"] = "CONFIRMED"
    svc.run_confirm_cascade(order)
    svc.touch(order)
    return envelope(order_public(order), "object", 200)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/disputes")
def create_dispute(oid):
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    order = _get_order(oid)
    body = get_json_body()
    reason = req_str(body, "reason", min_len=1, max_len=1000)
    expected = opt_int(body, "expected_order_version")
    # OCC (priority 6) runs before business rules (§2.8).
    if expected is not None and expected != order["version"]:
        raise err("ERR_STALE_VERSION",
                  "expected_order_version does not match current order version")
    _require_buyer_owner(order, user_id)
    if _any_dispute(oid):
        raise err("ERR_DISPUTE_ALREADY_EXISTS",
                  "an order may have at most one dispute")
    if order["status"] not in ("DELIVERED", "CONFIRMED"):
        raise err("ERR_INVALID_STATE",
                  "dispute open requires DELIVERED or CONFIRMED status")
    if order["status"] == "DELIVERED":
        now = db.clock_now()
        auto_confirm = db.parse_iso(order["auto_confirm_at"])
        if auto_confirm is not None and now >= auto_confirm:
            raise err("ERR_BUYER_WINDOW_CLOSED",
                      "current logical time is at or after auto_confirm_at")

    dispute = svc.make_record(db.disputes, {
        "order_id": oid,
        "reason": reason,
        "status": "OPEN",
        "refund_to_buyer_cents": None,
        "resolution_notes": None,
    })
    order["status"] = "REFUND_PENDING"
    svc.touch(order)
    return envelope(dispute_public(dispute), "object", 201)


@bp.get("/marketplace/orders/<oid>/disputes")
def list_disputes(oid):
    _uid, role = authenticate()
    require_role(role, ["Buyer", "Talent", "PlatformAdmin"])
    _get_order(oid)
    limit, offset = parse_pagination(request.args)
    items = [d for d in db.disputes.values() if d["order_id"] == oid]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([dispute_public(d) for d in page],
                         limit, offset, total, has_more)


# ---------------------------------------------------------------------------
# License grants
# ---------------------------------------------------------------------------
@bp.post("/marketplace/orders/<oid>/license-grants")
def create_license_grant(oid):
    user_id, role = authenticate()
    require_role(role, ["Buyer"])
    order = _get_order(oid)
    body = get_json_body()
    license_type = req_enum(body, "license_type", LICENSE_TYPES)
    territory = req_enum(body, "territory", TERRITORIES)
    channels = body.get("channels")
    if not isinstance(channels, list) or not channels or \
            any((not isinstance(c, str)) or c not in svc.CHANNELS for c in channels):
        raise err("ERR_INVALID_REQUEST",
                  "channels must be a non-empty subset of SOCIAL|WEB|TV|OOH")
    starts_at = req_iso(body, "starts_at")
    ends_at = req_iso(body, "ends_at")

    if order["status"] != "CONFIRMED":
        raise err("ERR_INVALID_STATE",
                  "license grants require a CONFIRMED order")
    _require_buyer_owner(order, user_id)
    _check_moderation_gate(oid)
    if starts_at >= ends_at:
        raise err("ERR_INVALID_LICENSE_WINDOW",
                  "starts_at must be strictly before ends_at")

    # license type compatibility
    if license_type == "BUSINESS" and order["use_type"] not in ("BUSINESS_USE", "ADVERTISING_USE"):
        raise err("ERR_LICENSE_TYPE_INCOMPATIBLE",
                  "BUSINESS license requires BUSINESS_USE or ADVERTISING_USE order")
    if license_type == "ADVERTISING" and order["use_type"] != "ADVERTISING_USE":
        raise err("ERR_LICENSE_TYPE_INCOMPATIBLE",
                  "ADVERTISING license requires ADVERTISING_USE order")

    # per-type overlap check against ACTIVE grants (half-open intersection)
    for g in db.license_grants.values():
        if g["order_id"] != oid or g["license_type"] != license_type or g["status"] != "ACTIVE":
            continue
        g_start = db.parse_iso(g["starts_at"])
        g_end = db.parse_iso(g["ends_at"])
        if starts_at < g_end and g_start < ends_at:
            raise err("ERR_LICENSE_WINDOW_OVERLAP",
                      "new grant overlaps an ACTIVE grant of the same license_type")

    fee = svc.compute_license_fee(license_type, channels, territory, starts_at, ends_at)
    grant = svc.make_record(db.license_grants, {
        "order_id": oid,
        "license_type": license_type,
        "territory": territory,
        "channels": channels,
        "starts_at": db.iso(starts_at),
        "ends_at": db.iso(ends_at),
        "fee_cents": fee,
        "status": "ACTIVE",
    })

    # License fee flows entirely to the talent.
    svc.make_record(db.payout_lines, {
        "talent_id": order["talent_id"],
        "order_id": oid,
        "kind": "LICENSE_FEE_CREDIT",
        "amount_cents": fee,
        "settlement_status": "UNSETTLED",
        "payout_id": None,
    })
    talent = db.talents[order["talent_id"]]
    talent["pending_balance_cents"] += fee
    svc.touch(talent)

    return envelope(license_public(grant), "object", 201)


@bp.get("/marketplace/orders/<oid>/license-grants")
def list_license_grants(oid):
    _uid, role = authenticate()
    require_role(role, ["Buyer", "Talent", "PlatformAdmin"])
    _get_order(oid)
    limit, offset = parse_pagination(request.args)
    lt = request.args.get("license_type")
    st = request.args.get("status")
    items = [g for g in db.license_grants.values()
             if g["order_id"] == oid
             and (lt is None or g["license_type"] == lt)
             and (st is None or g["status"] == st)]
    page, total, has_more = paginate(items, limit, offset)
    return envelope_list([license_public(g) for g in page],
                         limit, offset, total, has_more)
