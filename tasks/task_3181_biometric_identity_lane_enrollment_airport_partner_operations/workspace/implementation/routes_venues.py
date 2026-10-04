"""Venues, venue events, venue access, lane verifications, settlements."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import store, fmt_dt, _parse_dt, _parse_date
from errors import ApiError
from middleware import require_roles, body, require_field, pagination_params, paginate
from models import new_entity, touch
from response import success
from serializers import present, present_list
import services

bp = Blueprint("venues", __name__)


def _sorted(collection):
    return sorted(collection, key=lambda e: (e["created_at"], e["id"]))


# ---------------- venues ----------------

@bp.post("/venues")
@require_roles("VenueOps")
def create_venue():
    data = body()
    name = require_field(data, "name")
    venue_type = require_field(data, "venue_type")
    city = require_field(data, "city")
    state_code = require_field(data, "state_code")
    mode = data.get("access_rule_mode", "AGE_18_PLUS")
    if venue_type not in ("STADIUM", "ARENA", "OTHER"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid venue_type")
    if mode not in ("AGE_18_PLUS", "AGE_21_PLUS", "ALL_MEMBERS"):
        raise ApiError("ERR_VALIDATION", 400, "Invalid access_rule_mode")
    v = new_entity()
    v.update({
        "name": name,
        "venue_type": venue_type,
        "city": city,
        "state_code": state_code,
        "access_rule_mode": mode,
        "status": "ACTIVE",
    })
    store.venues[v["id"]] = v
    return success(present(v), status_code=201)


@bp.get("/venues")
@require_roles("OpsAdmin", "VenueOps", "Member")
def list_venues():
    limit, offset = pagination_params()
    items = _sorted(store.venues.values())
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/venues/<vid>")
@require_roles("OpsAdmin", "VenueOps", "Member")
def get_venue(vid):
    v = store.venues.get(vid)
    if v is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    return success(present(v))


# ---------------- venue events ----------------

@bp.post("/venue-events")
@require_roles("VenueOps")
def create_venue_event():
    data = body()
    venue_id = require_field(data, "venue_id")
    name = require_field(data, "name")
    start_time = require_field(data, "start_time")
    end_time = require_field(data, "end_time")
    buffer_hours = data.get("buffer_hours", 0)
    venue = store.venues.get(venue_id)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    if not isinstance(buffer_hours, int) or not (0 <= buffer_hours <= 12):
        raise ApiError("ERR_VALIDATION", 400, "buffer_hours must be within 0..12")
    try:
        start = _parse_dt(start_time)
        end = _parse_dt(end_time)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "start_time/end_time must be ISO datetimes")
    if end <= start:
        raise ApiError("ERR_VALIDATION", 400, "end_time must be strictly after start_time")
    if start <= store.now():
        raise ApiError("ERR_VALIDATION", 400, "start_time must be in the future")
    c_start = start - timedelta(hours=buffer_hours)
    c_end = end + timedelta(hours=buffer_hours)
    for e in store.venue_events.values():
        if e["venue_id"] != venue_id or e["status"] == "CANCELLED":
            continue
        e_start = _parse_dt(e["start_time"]) - timedelta(hours=e.get("buffer_hours", 0))
        e_end = _parse_dt(e["end_time"]) + timedelta(hours=e.get("buffer_hours", 0))
        if c_start < e_end and e_start < c_end:
            raise ApiError("ERR_EVENT_WINDOW_CONFLICT", 409,
                           "Event window conflicts with an existing event")
    e = new_entity()
    e.update({
        "venue_id": venue_id,
        "name": name,
        "start_time": fmt_dt(start),
        "end_time": fmt_dt(end),
        "buffer_hours": buffer_hours,
        "status": "SCHEDULED",
    })
    store.venue_events[e["id"]] = e
    return success(present(e), status_code=201)


@bp.get("/venue-events")
@require_roles("OpsAdmin", "VenueOps", "Member")
def list_venue_events():
    limit, offset = pagination_params()
    items = _sorted(store.venue_events.values())
    vid = request.args.get("venue_id")
    if vid is not None:
        items = [e for e in items if e["venue_id"] == vid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/venue-events/<eid>")
@require_roles("OpsAdmin", "VenueOps", "Member")
def get_venue_event(eid):
    e = store.venue_events.get(eid)
    if e is None:
        raise ApiError("ERR_VENUE_EVENT_NOT_FOUND", 404, "Venue event not found")
    return success(present(e))


@bp.post("/venue-events/<eid>/cancel")
@require_roles("VenueOps")
def cancel_venue_event(eid):
    e = store.venue_events.get(eid)
    if e is None:
        raise ApiError("ERR_VENUE_EVENT_NOT_FOUND", 404, "Venue event not found")
    if e["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "Event is not SCHEDULED")
    if store.now() >= _parse_dt(e["start_time"]):
        raise ApiError("ERR_EVENT_ALREADY_STARTED", 409, "Event already started")
    e["status"] = "CANCELLED"
    touch(e)
    return success(present(e))


# ---------------- venue access ----------------

@bp.post("/venue-access")
@require_roles("Member")
def venue_access():
    data = body()
    venue_id = require_field(data, "venue_id")
    member_id = require_field(data, "member_id")
    venue = store.venues.get(venue_id)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    if request.user_role == "Member" and request.user_id != member_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only record their own access")
    outcome = "ADMITTED"
    reject_reason = None
    http_error = None
    if venue["status"] != "ACTIVE":
        outcome, reject_reason = "REJECTED", "VENUE_SUSPENDED"
    elif member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not ACTIVE")
    else:
        now = store.now()
        covering = any(
            e for e in store.venue_events.values()
            if e["venue_id"] == venue_id and e["status"] == "SCHEDULED"
            and _parse_dt(e["start_time"]) <= now <= _parse_dt(e["end_time"])
        )
        if not covering:
            raise ApiError("ERR_NO_ACTIVE_EVENT", 409, "No active event covers this time")
        age = services.member_age_years(member, now.date())
        mode = venue["access_rule_mode"]
        if mode == "AGE_18_PLUS" and age < 18:
            outcome, reject_reason = "REJECTED", "AGE_RULE"
            http_error = ("ERR_AGE_RULE_VIOLATION", 422, "Age gate not satisfied")
        elif mode == "AGE_21_PLUS" and age < 21:
            outcome, reject_reason = "REJECTED", "AGE_RULE"
            http_error = ("ERR_AGE_RULE_VIOLATION", 422, "Age gate not satisfied")
    ev = new_entity()
    ev.update({
        "venue_id": venue_id,
        "member_id": member_id,
        "accessed_at": fmt_dt(store.now()),
        "outcome": outcome,
        "reject_reason": reject_reason,
    })
    store.venue_access_events[ev["id"]] = ev
    if http_error is not None:
        raise ApiError(*http_error)
    return success(present(ev), status_code=201)


@bp.get("/venue-access-events")
@require_roles("OpsAdmin", "VenueOps")
def list_access_events():
    limit, offset = pagination_params()
    items = _sorted(store.venue_access_events.values())
    vid = request.args.get("venue_id")
    mid = request.args.get("member_id")
    if vid is not None:
        items = [e for e in items if e["venue_id"] == vid]
    if mid is not None:
        items = [e for e in items if e["member_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/venues/<vid>/access-events")
@require_roles("OpsAdmin", "VenueOps")
def venue_access_events(vid):
    if store.venues.get(vid) is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    limit, offset = pagination_params()
    items = [e for e in _sorted(store.venue_access_events.values()) if e["venue_id"] == vid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/members/<mid>/venue-access-events")
@require_roles("OpsAdmin", "VenueOps", "ComplianceOfficer")
def member_access_events(mid):
    if store.members.get(mid) is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    limit, offset = pagination_params()
    items = [e for e in _sorted(store.venue_access_events.values()) if e["member_id"] == mid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


# ---------------- lane verifications ----------------

@bp.post("/lane-verifications")
@require_roles("Member")
def create_lane_verification():
    data = body()
    member_id = require_field(data, "member_id")
    lane_id = require_field(data, "lane_id")
    ambassador_id = require_field(data, "ambassador_id")
    member = store.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", 404, "Member not found")
    lane = store.lanes.get(lane_id)
    if lane is None:
        raise ApiError("ERR_LANE_NOT_FOUND", 404, "Lane not found")
    ambassador = store.ambassadors.get(ambassador_id)
    if ambassador is None:
        raise ApiError("ERR_AMBASSADOR_NOT_FOUND", 404, "Ambassador not found")
    if request.user_role == "Member" and request.user_id != member_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Members may only check in themselves")
    if member_id in store.purged_members:
        raise ApiError("ERR_BIOMETRIC_PURGED", 409,
                       "Member's biometric data has been purged; re-enroll first")
    if lane["status"] != "OPEN":
        raise ApiError("ERR_LANE_NOT_OPEN", 409, "Lane is not OPEN")
    if member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE", 409, "Member is not ACTIVE")
    sub = None
    if member.get("subscription_id"):
        sub = store.subscriptions.get(member["subscription_id"])
    if sub is None or sub["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_SUBSCRIPTION_NOT_ACTIVE", 409,
                       "Subscription is not ACTIVE or PAST_DUE")
    ag = store.partner_agreements.get(lane["agreement_id"])
    if ag is None or ag["status"] != "ACTIVE":
        raise ApiError("ERR_AGREEMENT_NOT_ACTIVE", 409, "Agreement is not ACTIVE")
    if ambassador["status"] != "ACTIVE" or ambassador["airport_id"] != lane["airport_id"]:
        raise ApiError("ERR_WRONG_AMBASSADOR", 409,
                       "Ambassador is not ACTIVE or is homed at a different airport")
    # federal_program: agreement federal_integration AND member document type eligible
    doc_type = None
    for e in store.enrollments.values():
        if e["member_id"] == member_id and e["status"] == "COMPLETED":
            doc_type = e["document_type"]
    federal = bool(ag.get("federal_integration")) and doc_type in ("PASSPORT", "DRIVERS_LICENSE")
    now = store.now()
    lv = new_entity()
    lv.update({
        "member_id": member_id,
        "lane_id": lane_id,
        "ambassador_id": ambassador_id,
        "verified_at": fmt_dt(now),
        "federal_program": federal,
        "escort_status": "PENDING",
        "outcome": "VERIFIED",
        "reject_reason": None,
        "version_confirmed": member["version"],
        "expires_at": fmt_dt(now + timedelta(minutes=services.ESCORT_WINDOW_MINUTES)),
    })
    store.lane_verifications[lv["id"]] = lv
    return success(present(lv), status_code=201)


@bp.get("/lane-verifications")
@require_roles("OpsAdmin", "Member", "Ambassador")
def list_lane_verifications():
    limit, offset = pagination_params()
    items = _sorted(store.lane_verifications.values())
    mid = request.args.get("member_id")
    lid = request.args.get("lane_id")
    aid = request.args.get("ambassador_id")
    if mid is not None:
        items = [v for v in items if v["member_id"] == mid]
    if lid is not None:
        items = [v for v in items if v["lane_id"] == lid]
    if aid is not None:
        items = [v for v in items if v["ambassador_id"] == aid]
    page, meta = paginate(items, limit, offset)
    return success(present_list(page), is_array=True, pagination=meta)


@bp.get("/lane-verifications/<vid>")
@require_roles("OpsAdmin", "Member", "Ambassador")
def get_lane_verification(vid):
    lv = store.lane_verifications.get(vid)
    if lv is None:
        raise ApiError("ERR_LANE_VERIFICATION_NOT_FOUND", 404, "Lane verification not found")
    return success(present(lv))


@bp.post("/lane-verifications/<vid>/escort")
@require_roles("Ambassador")
def escort(vid):
    lv = store.lane_verifications.get(vid)
    if lv is None:
        raise ApiError("ERR_LANE_VERIFICATION_NOT_FOUND", 404, "Lane verification not found")
    data = body()
    expected = require_field(data, "expected_member_version")
    if not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", 400, "expected_member_version must be an integer")
    if request.user_id != lv["ambassador_id"]:
        raise ApiError("ERR_WRONG_AMBASSADOR", 409,
                       "Only the ambassador named on the verification may escort")
    if lv["escort_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Verification is not PENDING")
    if store.now() > _parse_dt(lv["expires_at"]):
        raise ApiError("ERR_ESCORT_WINDOW_EXPIRED", 409, "Escort window expired")
    member = store.members.get(lv["member_id"])
    if member is None or expected != lv["version_confirmed"] or expected != member["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "Stale member version")
    lv["escort_status"] = "ESCORTED"
    touch(lv)
    if lv["federal_program"] and member.get("verification_level") != "FEDERAL_TRUSTED":
        member["verification_level"] = "FEDERAL_TRUSTED"
        touch(member)
    return success(present(lv))


# ---------------- settlements ----------------

def _parse_period(data):
    period_start = require_field(data, "period_start")
    period_end = require_field(data, "period_end")
    try:
        ps = _parse_date(period_start)
        pe = _parse_date(period_end)
    except Exception:
        raise ApiError("ERR_VALIDATION", 400, "period_start/period_end must be ISO dates")
    if pe <= ps:
        raise ApiError("ERR_VALIDATION", 400, "period_end must be after period_start")
    return period_start, period_end


def _nonneg_int(data, field):
    value = require_field(data, field)
    if not isinstance(value, int) or value < 0:
        raise ApiError("ERR_VALIDATION", 400, f"{field} must be an integer >= 0")
    return value


@bp.post("/partner-agreements/<aid>/settlements")
@require_roles("PartnerManager")
def create_airport_settlement(aid):
    ag = store.partner_agreements.get(aid)
    if ag is None:
        raise ApiError("ERR_AGREEMENT_NOT_FOUND", 404, "Agreement not found")
    data = body()
    period_start, period_end = _parse_period(data)
    mrr = _nonneg_int(data, "attributable_mrr_cents")
    rev = _nonneg_int(data, "verification_revenue_cents")
    s = new_entity()
    s.update({
        "agreement_id": aid,
        "venue_id": None,
        "period_start": period_start,
        "period_end": period_end,
        "attributable_mrr_cents": mrr,
        "verification_revenue_cents": rev,
        "events_count": 0,
        "calculation_variant": "AIRPORT",
        "status": "DRAFT",
        "fee_cents": None,
    })
    store.agreement_settlements[s["id"]] = s
    s["fee_cents"] = _compute_fee(s)
    return success(_settlement_view(s), status_code=201)


@bp.post("/venues/<vid>/payout-settlements")
@require_roles("VenueOps")
def create_venue_settlement(vid):
    venue = store.venues.get(vid)
    if venue is None:
        raise ApiError("ERR_VENUE_NOT_FOUND", 404, "Venue not found")
    data = body()
    period_start, period_end = _parse_period(data)
    rev = _nonneg_int(data, "verification_revenue_cents")
    events_count = _nonneg_int(data, "events_count")
    capacity_seats = _nonneg_int(data, "venue_capacity_seats")
    s = new_entity()
    s.update({
        "agreement_id": None,
        "venue_id": vid,
        "period_start": period_start,
        "period_end": period_end,
        "attributable_mrr_cents": 0,
        "verification_revenue_cents": rev,
        "events_count": events_count,
        "venue_capacity_seats": capacity_seats,
        "calculation_variant": "VENUE",
        "status": "DRAFT",
        "fee_cents": None,
    })
    store.agreement_settlements[s["id"]] = s
    s["fee_cents"] = _compute_fee(s)
    return success(_settlement_view(s), status_code=201)


def _compute_fee(s):
    if s["calculation_variant"] == "AIRPORT":
        ag = store.partner_agreements.get(s["agreement_id"])
        mrr_share = services.round_half_up_2(
            Decimal(s["attributable_mrr_cents"]) * Decimal(str(ag["subscription_share_rate"])))
        rev_share = services.round_half_up_2(
            Decimal(s["verification_revenue_cents"]) * Decimal(str(ag["rev_share_rate"])))
        variable = mrr_share + rev_share
        return int(max(Decimal(ag["monthly_minimum_cents"]), variable))
    capacity_value = Decimal(s.get("venue_capacity_seats", 0)) * Decimal(services.VENUE_BASE_SEAT_CENTS)
    variable = services.round_half_up_2(capacity_value * services.VENUE_REVENUE_SHARE)
    if s["events_count"] >= services.VENUE_EVENT_THRESHOLD:
        variable += Decimal(s["events_count"]) * Decimal(services.VENUE_PER_EVENT_CENTS)
    return int(max(Decimal(services.VENUE_MINIMUM_CENTS), variable))


def _settlement_view(s):
    view = present(s)
    if s["status"] == "DRAFT":
        view["fee_cents"] = _compute_fee(s)
    return view


@bp.get("/agreement-settlements")
@require_roles("OpsAdmin", "PartnerManager", "VenueOps")
def list_settlements():
    limit, offset = pagination_params()
    items = _sorted(store.agreement_settlements.values())
    aid = request.args.get("agreement_id")
    vid = request.args.get("venue_id")
    if aid is not None:
        items = [s for s in items if s.get("agreement_id") == aid]
    if vid is not None:
        items = [s for s in items if s.get("venue_id") == vid]
    page, meta = paginate(items, limit, offset)
    return success([_settlement_view(s) for s in page], is_array=True, pagination=meta)


@bp.get("/agreement-settlements/<sid>")
@require_roles("OpsAdmin", "PartnerManager", "VenueOps")
def get_settlement(sid):
    s = store.agreement_settlements.get(sid)
    if s is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND", 404, "Settlement not found")
    return success(_settlement_view(s))


@bp.post("/agreement-settlements/<sid>/finalize")
@require_roles("PartnerManager")
def finalize_settlement(sid):
    s = store.agreement_settlements.get(sid)
    if s is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND", 404, "Settlement not found")
    if s["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Settlement is not DRAFT")
    if _parse_date(s["period_end"]) > store.now().date():
        raise ApiError("ERR_PERIOD_NOT_ENDED", 409, "Settlement period has not ended")
    s["fee_cents"] = _compute_fee(s)
    s["status"] = "FINALIZED"
    touch(s)
    return success(present(s))


@bp.post("/agreement-settlements/<sid>/mark-paid")
@require_roles("PartnerManager")
def mark_paid(sid):
    s = store.agreement_settlements.get(sid)
    if s is None:
        raise ApiError("ERR_SETTLEMENT_NOT_FOUND", 404, "Settlement not found")
    if s["status"] != "FINALIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Settlement is not FINALIZED")
    s["status"] = "PAID"
    touch(s)
    return success(present(s))
