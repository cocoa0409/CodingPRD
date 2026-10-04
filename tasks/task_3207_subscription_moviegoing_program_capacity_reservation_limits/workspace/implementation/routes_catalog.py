from datetime import timedelta

from flask import request

from core import (
    STORE, now, fmt_dt, parse_dt, get_auth, require_role, check_member_identity,
    parse_body, get_pagination, paginate, lookup, envelope_ok, ApiError,
    err_not_found, err_invalid_state, err_invalid_request, err_forbidden,
    stamp_new, touch, FORMATS, DEFAULT_DISPLACEMENT_CAP_PCT,
    HOLD_TTL_MINUTES, CANCELLATION_WINDOW_MINUTES, NO_SHOW_GRACE_MINUTES,
    CHECKIN_EARLY_MINUTES, CHECKIN_LATE_MINUTES,
)
import engine


# ================= Serializers =================

def serialize_theater(t):
    return dict(t)


def serialize_auditorium(a):
    return dict(a)


def serialize_showtime(s):
    return engine.showtime_view(s)


def serialize_reservation(r):
    out = dict(r)
    st = STORE["showtimes"].get(r["showtime_id"])
    out["is_premium_format"] = bool(st and st["format"] != "STANDARD")
    return out


def serialize_strike(s):
    return dict(s)


# ================= Theaters =================

def create_theater():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    body = parse_body(request, {
        "name": ("str", True, None),
        "timezone": ("str", True, None),
    })
    theater = {
        "name": body["name"],
        "timezone": body["timezone"],
        "status": "OPERATING",
    }
    stamp_new(theater)
    STORE["theaters"][theater["id"]] = theater
    return envelope_ok(serialize_theater(theater), "object", 201)


def get_theater(theater_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    theater = lookup("theaters", theater_id)
    return envelope_ok(serialize_theater(theater), "object", 200)


# ================= Auditoriums =================

def create_auditorium(theater_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    theater = lookup("theaters", theater_id)
    body = parse_body(request, {
        "label": ("str", True, None),
        "seat_count": ("int", True, None),
        "supported_formats": ("strlist", True, None),
    })
    for f in body["supported_formats"]:
        if f not in FORMATS:
            raise err_invalid_request(f"supported_formats must be a subset of {FORMATS}")
    auditorium = {
        "theater_id": theater["id"],
        "label": body["label"],
        "seat_count": body["seat_count"],
        "supported_formats": body["supported_formats"],
    }
    stamp_new(auditorium)
    STORE["auditoriums"][auditorium["id"]] = auditorium
    return envelope_ok(serialize_auditorium(auditorium), "object", 201)


def list_theater_auditoriums(theater_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    theater = lookup("theaters", theater_id)
    limit, offset = get_pagination(request)
    items = [a for a in STORE["auditoriums"].values() if a["theater_id"] == theater_id]
    page, meta = paginate([serialize_auditorium(a) for a in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_auditoriums():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    limit, offset = get_pagination(request)
    theater_id = request.args.get("theater_id")
    items = list(STORE["auditoriums"].values())
    if theater_id is not None:
        items = [a for a in items if a["theater_id"] == theater_id]
    page, meta = paginate([serialize_auditorium(a) for a in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def get_auditorium(auditorium_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    auditorium = lookup("auditoriums", auditorium_id)
    return envelope_ok(serialize_auditorium(auditorium), "object", 200)


# ================= Showtimes =================

def create_showtime():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    body = parse_body(request, {
        "auditorium_id": ("str", True, None),
        "film_title": ("str", True, None),
        "studio_code": ("str", True, None),
        "format": ("str", True, FORMATS),
        "starts_at": ("dt", True, None),
        "runtime_minutes": ("int", True, None),
        "base_price_cents": ("int", True, None),
        "premium_surcharge_cents": ("int", True, None),
        "opening_weekend": ("bool", True, None),
        "subscriber_displacement_cap_pct": ("int", False, None),
    })
    auditorium = lookup("auditoriums", body["auditorium_id"])
    theater = STORE["theaters"].get(auditorium["theater_id"])
    if theater is not None and theater["status"] == "DARK":
        raise err_invalid_state("DARK theaters reject new showtimes")
    if body["format"] not in auditorium["supported_formats"]:
        raise ApiError("ERR_FORMAT_UNSUPPORTED", 422,
                       "Showtime format not in auditorium.supported_formats")
    showtime = {
        "auditorium_id": auditorium["id"],
        "film_title": body["film_title"],
        "studio_code": body["studio_code"],
        "format": body["format"],
        "runtime_minutes": body["runtime_minutes"],
        "starts_at": fmt_dt(body["starts_at"]),
        "base_price_cents": body["base_price_cents"],
        "premium_surcharge_cents": body["premium_surcharge_cents"],
        "opening_weekend": body["opening_weekend"],
        "subscriber_displacement_cap_pct": (
            body["subscriber_displacement_cap_pct"]
            if body["subscriber_displacement_cap_pct"] is not None
            else DEFAULT_DISPLACEMENT_CAP_PCT
        ),
        "seats_held_subscription": 0,
        "seats_held_paid": 0,
        "status": "SCHEDULED",
    }
    stamp_new(showtime)
    STORE["showtimes"][showtime["id"]] = showtime
    return envelope_ok(serialize_showtime(showtime), "object", 201)


def get_showtime(showtime_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    showtime = lookup("showtimes", showtime_id)
    return envelope_ok(serialize_showtime(showtime), "object", 200)


def list_auditorium_showtimes(auditorium_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    auditorium = lookup("auditoriums", auditorium_id)
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = [s for s in STORE["showtimes"].values() if s["auditorium_id"] == auditorium_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate([serialize_showtime(s) for s in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_showtimes():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "TheaterStaff", "MemberServices", "Member", "StudioRep")
    limit, offset = get_pagination(request)
    auditorium_id = request.args.get("auditorium_id")
    studio_code = request.args.get("studio_code")
    status = request.args.get("status")
    items = list(STORE["showtimes"].values())
    if auditorium_id is not None:
        items = [s for s in items if s["auditorium_id"] == auditorium_id]
    if studio_code is not None:
        items = [s for s in items if s["studio_code"] == studio_code]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate([serialize_showtime(s) for s in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def open_sales(showtime_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    showtime = lookup("showtimes", showtime_id)
    if showtime["status"] != "SCHEDULED":
        raise err_invalid_state("Only a SCHEDULED showtime can open sales")
    auditorium = STORE["auditoriums"].get(showtime["auditorium_id"])
    theater = STORE["theaters"].get(auditorium["theater_id"]) if auditorium else None
    if theater is not None and theater["status"] != "OPERATING":
        raise err_invalid_state("Theater is not OPERATING")
    if parse_dt(showtime["starts_at"]) <= now():
        raise err_invalid_state("starts_at must be in the future to open sales")
    showtime["status"] = "ON_SALE"
    touch(showtime)
    return envelope_ok(serialize_showtime(showtime), "object", 200)


def cancel_showtime(showtime_id):
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin")
    showtime = lookup("showtimes", showtime_id)
    if showtime["status"] not in ("SCHEDULED", "ON_SALE"):
        raise err_invalid_state("Only a SCHEDULED or ON_SALE showtime can be cancelled")
    showtime["status"] = "CANCELLED"
    touch(showtime)
    # Force-majeure: cancel HELD/CONFIRMED with full refund regardless of deadline
    for r in list(STORE["reservations"].values()):
        if r["showtime_id"] == showtime_id and r["status"] in ("HELD", "CONFIRMED"):
            engine.cancel_reservation_system(r, refund_postures=("OPEN", "EXHAUSTED"))
    showtime["seats_held_subscription"] = 0
    showtime["seats_held_paid"] = 0
    touch(showtime)
    return envelope_ok(serialize_showtime(showtime), "object", 200)


def list_showtime_reservations(showtime_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff", "ProgramAdmin", "MemberServices")
    showtime = lookup("showtimes", showtime_id)
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = [r for r in STORE["reservations"].values() if r["showtime_id"] == showtime_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate([serialize_reservation(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


# ================= Reservations =================

def create_reservation():
    user_id, role = get_auth(request)
    require_role(role, "Member")
    body = parse_body(request, {
        "subscription_id": ("str", True, None),
        "showtime_id": ("str", True, None),
        "expected_showtime_version": ("int", True, None),
    })
    # Priority 3: existence of body FKs, left to right
    sub = lookup("subscriptions", body["subscription_id"])
    showtime = lookup("showtimes", body["showtime_id"])
    # Priority 4: entity-backed identity
    check_member_identity(user_id, role, sub["member_id"])
    # Priority 5: state admissibility
    member = STORE["members"].get(sub["member_id"])
    if member is None:
        raise err_not_found("Member does not exist")
    if sub["status"] != "ACTIVE":
        # SUSPENDED member forced their subscription PAUSED — the member gate
        # surfaces first when a suspended member attempts creation.
        if member["status"] == "SUSPENDED" and sub["status"] == "PAUSED":
            raise ApiError("ERR_MEMBER_SUSPENDED", 409,
                           "SUSPENDED members may not create reservations")
        raise err_invalid_state("Reservation creation requires an ACTIVE subscription")
    if showtime["status"] != "ON_SALE":
        if showtime["status"] in ("LOCKED", "COMPLETED", "CANCELLED"):
            raise ApiError("ERR_SHOWTIME_LOCKED", 409,
                           "Showtime is not open for new reservations")
        raise err_invalid_state("Showtime is not ON_SALE")
    # Priority 6: OCC on showtime version
    if body["expected_showtime_version"] != showtime["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_showtime_version does not match the current version")
    # Priority 7: member-level suspension gate
    if member["status"] == "SUSPENDED":
        raise ApiError("ERR_MEMBER_SUSPENDED", 409,
                       "SUSPENDED members may not create reservations")
    if member["status"] != "ACTIVE":
        raise err_invalid_state("Member account is not ACTIVE")
    plan = STORE["plans"].get(sub["plan_id"])
    if plan is None:
        raise err_not_found("Plan does not exist")
    # Priority 11: premium-format eligibility
    is_premium = showtime["format"] != "STANDARD"
    if is_premium and not plan["premium_format_allowed"]:
        raise ApiError("ERR_PREMIUM_NOT_INCLUDED", 422,
                       "Plan does not include premium formats")
    # Priority 12: weekly quota — lazily materialize current bucket
    n = now()
    engine.ensure_buckets_up_to(sub, engine.week_index_at(sub, n))
    bucket = engine.find_bucket(sub["id"], engine.week_index_at(sub, n))
    if bucket is None:
        raise ApiError("ERR_WEEKLY_QUOTA_EXHAUSTED", 422, "No current credit bucket")
    posture = engine.bucket_posture(bucket)
    if posture != "OPEN" or engine.credits_available(bucket) < 1:
        raise ApiError("ERR_WEEKLY_QUOTA_EXHAUSTED", 422,
                       "Current week bucket has no credits available")
    # Priority 13: anti-hoarding future-reservation cap
    engine.expire_strikes_for_member(member["id"])
    effective_cap = engine.effective_future_cap(member, plan)
    if engine.future_reservation_count(member["id"]) >= effective_cap:
        raise ApiError("ERR_FUTURE_RESERVATION_LIMIT", 422,
                       "Future reservation cap reached")
    # Priority 14: capacity incl. opening-weekend displacement
    auditorium = STORE["auditoriums"].get(showtime["auditorium_id"])
    if auditorium is None:
        raise err_not_found("Auditorium does not exist")
    seat_count = auditorium["seat_count"]
    seats_available = seat_count - showtime["seats_held_subscription"] - showtime["seats_held_paid"]
    if seats_available < 1:
        raise ApiError("ERR_CAPACITY_EXCEEDED", 422, "No seats available")
    if showtime["opening_weekend"]:
        cap_pct = showtime["subscriber_displacement_cap_pct"]
        if (showtime["seats_held_subscription"] + 1) * 100 > cap_pct * seat_count:
            raise ApiError("ERR_CAPACITY_EXCEEDED", 422,
                           "Opening-weekend displacement cap would be exceeded")
    # Success: create the HELD reservation
    reservation = {
        "member_id": member["id"],
        "subscription_id": sub["id"],
        "showtime_id": showtime["id"],
        "bucket_id": bucket["id"],
        "seat_count": 1,
        "credit_consumed": True,
        "status": "HELD",
        "cancel_deadline": fmt_dt(parse_dt(showtime["starts_at"])
                                  - timedelta(minutes=CANCELLATION_WINDOW_MINUTES)),
        "settlement_reported": False,
    }
    stamp_new(reservation)
    STORE["reservations"][reservation["id"]] = reservation
    bucket["credits_used"] += 1
    touch(bucket)
    showtime["seats_held_subscription"] += 1
    touch(showtime)
    return envelope_ok(serialize_reservation(reservation), "object", 201)


def get_reservation(reservation_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "TheaterStaff", "ProgramAdmin")
    reservation = lookup("reservations", reservation_id)
    check_member_identity(user_id, role, reservation["member_id"])
    return envelope_ok(serialize_reservation(reservation), "object", 200)


def list_reservations():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices", "TheaterStaff")
    limit, offset = get_pagination(request)
    member_id = request.args.get("member_id")
    subscription_id = request.args.get("subscription_id")
    showtime_id = request.args.get("showtime_id")
    bucket_id = request.args.get("bucket_id")
    status = request.args.get("status")
    items = list(STORE["reservations"].values())
    if member_id is not None:
        items = [r for r in items if r["member_id"] == member_id]
    if subscription_id is not None:
        items = [r for r in items if r["subscription_id"] == subscription_id]
    if showtime_id is not None:
        items = [r for r in items if r["showtime_id"] == showtime_id]
    if bucket_id is not None:
        items = [r for r in items if r["bucket_id"] == bucket_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate([serialize_reservation(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_member_reservations(member_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    member = lookup("members", member_id)
    check_member_identity(user_id, role, member["id"])
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = [r for r in STORE["reservations"].values() if r["member_id"] == member_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate([serialize_reservation(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_subscription_reservations(subscription_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    sub = lookup("subscriptions", subscription_id)
    check_member_identity(user_id, role, sub["member_id"])
    limit, offset = get_pagination(request)
    status = request.args.get("status")
    items = [r for r in STORE["reservations"].values() if r["subscription_id"] == subscription_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, meta = paginate([serialize_reservation(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def list_bucket_reservations(bucket_id):
    user_id, role = get_auth(request)
    require_role(role, "Member", "MemberServices", "ProgramAdmin")
    bucket = lookup("buckets", bucket_id)
    sub = STORE["subscriptions"].get(bucket["subscription_id"])
    if role == "Member" and (sub is None or sub["member_id"] != user_id):
        raise err_forbidden("Member may only act on their own resources")
    limit, offset = get_pagination(request)
    items = [r for r in STORE["reservations"].values() if r["bucket_id"] == bucket_id]
    page, meta = paginate([serialize_reservation(r) for r in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def confirm_reservation(reservation_id):
    user_id, role = get_auth(request)
    require_role(role, "Member")
    reservation = lookup("reservations", reservation_id)
    check_member_identity(user_id, role, reservation["member_id"])
    if reservation["status"] != "HELD":
        raise err_invalid_state("Only a HELD reservation can be confirmed")
    # Hold TTL: created no more than HOLD_TTL_MINUTES ago
    if parse_dt(reservation["created_at"]) + timedelta(minutes=HOLD_TTL_MINUTES) <= now():
        engine.expire_hold(reservation)
        raise err_invalid_state("Reservation hold has expired")
    showtime = STORE["showtimes"].get(reservation["showtime_id"])
    if showtime is None or showtime["status"] != "ON_SALE":
        if showtime is not None and showtime["status"] in ("LOCKED", "COMPLETED", "CANCELLED"):
            raise ApiError("ERR_SHOWTIME_LOCKED", 409,
                           "Showtime is not open for confirmations")
        raise err_invalid_state("Showtime is not ON_SALE")
    reservation["status"] = "CONFIRMED"
    touch(reservation)
    return envelope_ok(serialize_reservation(reservation), "object", 200)


def cancel_reservation(reservation_id):
    user_id, role = get_auth(request)
    require_role(role, "Member")
    reservation = lookup("reservations", reservation_id)
    check_member_identity(user_id, role, reservation["member_id"])
    if reservation["status"] not in ("HELD", "CONFIRMED"):
        raise err_invalid_state("Only a HELD or CONFIRMED reservation can be cancelled")
    # Priority 9: member-initiated cancellation window
    if now() >= parse_dt(reservation["cancel_deadline"]):
        raise ApiError("ERR_CANCEL_WINDOW_CLOSED", 409,
                       "Cancellation window has closed")
    engine.cancel_reservation_system(reservation, refund_postures=("OPEN", "EXHAUSTED"))
    return envelope_ok(serialize_reservation(reservation), "object", 200)


def check_in_reservation(reservation_id):
    user_id, role = get_auth(request)
    require_role(role, "TheaterStaff")
    reservation = lookup("reservations", reservation_id)
    showtime = STORE["showtimes"].get(reservation["showtime_id"])
    if showtime is None:
        raise err_not_found("Showtime does not exist")
    # The no-show grace is the upper bound of the check-in window, so a
    # CONFIRMED reservation whose grace has elapsed is outside the window by
    # definition; surface ERR_CHECKIN_WINDOW (and lazily fire the overdue
    # no-show sweep) before the status gate.
    starts = parse_dt(showtime["starts_at"])
    n = now()
    if not (starts - timedelta(minutes=CHECKIN_EARLY_MINUTES) <= n
            <= starts + timedelta(minutes=CHECKIN_LATE_MINUTES)):
        if (reservation["status"] == "CONFIRMED"
                and starts + timedelta(minutes=NO_SHOW_GRACE_MINUTES) <= n):
            engine.sweep_no_show(reservation)
        raise ApiError("ERR_CHECKIN_WINDOW", 409, "Check-in outside the allowed window")
    if reservation["status"] != "CONFIRMED":
        raise err_invalid_state("Only a CONFIRMED reservation can be checked in")
    if showtime["status"] not in ("ON_SALE", "LOCKED"):
        raise err_invalid_state("Showtime does not permit check-in")
    reservation["status"] = "CHECKED_IN"
    touch(reservation)
    # EARN_ADMISSION loyalty entry
    points = engine.admission_points_for(reservation["member_id"])
    engine.append_ledger(reservation["member_id"], "EARN_ADMISSION", points,
                         source_id=reservation["id"])
    return envelope_ok(serialize_reservation(reservation), "object", 200)


# ================= Strikes =================

def get_strike(strike_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices", "ProgramAdmin")
    strike = lookup("strikes", strike_id)
    return envelope_ok(serialize_strike(strike), "object", 200)


def list_strikes():
    user_id, role = get_auth(request)
    require_role(role, "ProgramAdmin", "MemberServices")
    limit, offset = get_pagination(request)
    member_id = request.args.get("member_id")
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    items = list(STORE["strikes"].values())
    if member_id is not None:
        items = [s for s in items if s["member_id"] == member_id]
    if reservation_id is not None:
        items = [s for s in items if s["reservation_id"] == reservation_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, meta = paginate([serialize_strike(s) for s in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)


def reverse_strike(strike_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices")
    strike = lookup("strikes", strike_id)
    body = parse_body(request, {"reversal_reason": ("str", True, None)})
    if strike["status"] != "ACTIVE":
        raise err_invalid_state("Only an ACTIVE strike can be reversed")
    strike["status"] = "REVERSED"
    strike["reversal_reason"] = body["reversal_reason"]
    touch(strike)
    return envelope_ok(serialize_strike(strike), "object", 200)


def list_reservation_strikes(reservation_id):
    user_id, role = get_auth(request)
    require_role(role, "MemberServices", "ProgramAdmin", "Member")
    reservation = lookup("reservations", reservation_id)
    check_member_identity(user_id, role, reservation["member_id"])
    limit, offset = get_pagination(request)
    items = [s for s in STORE["strikes"].values() if s["reservation_id"] == reservation_id]
    page, meta = paginate([serialize_strike(s) for s in items], limit, offset)
    return envelope_ok(page, "array", 200, pagination=meta)
