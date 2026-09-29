"""Weekly package bookings, deposits, arrival and folio settlement (PRD 3.5, 3.6)."""

from flask import Blueprint

import calc
import derive
import fields
from auth import auth
from derive import Touch, booking_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find, find_body_ref
from store import db

bp = Blueprint("bookings", __name__)

WEEKDAY_NAMES = (
    "MONDAY",
    "TUESDAY",
    "WEDNESDAY",
    "THURSDAY",
    "FRIDAY",
    "SATURDAY",
    "SUNDAY",
)
MEMBER_TYPES = ("ADULT", "CHILD")
DIETARY = ("NONE", "VEGETARIAN", "GLUTEN_FREE", "DAIRY_FREE", "NUT_ALLERGY")
BOOKING_STATUSES = ("HELD", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED")
PAYMENT_KINDS = ("DEPOSIT", "SETTLEMENT")
FOLIO_SURCHARGE_STATUSES = ("CHECKED_IN", "COMPLETED", "NO_SHOW")


def _tier(season, code):
    for tier in season["package_tiers"]:
        if tier["code"] == code:
            return tier
    return None


def _price(season, tier, members, nights, is_buyout):
    subtotal, premium, total = calc.package_charge_total(
        tier, members, nights, is_buyout, season["buyout_premium_pct"]
    )
    return total


def _validate_members(data):
    raw = fields.as_list(data, "party_members", min_len=1, max_len=12)
    cleaned = []
    for index, member in enumerate(raw):
        label = "party_members[%d]" % index
        if not isinstance(member, dict):
            fields.bad("party_members", "elements must be objects")
        for key in ("guest_id", "member_type"):
            if key not in member or member[key] is None:
                raise ApiError(
                    "ERR_MISSING_REQUIRED_FIELD",
                    "Field '%s.%s' is required." % (label, key),
                )
        guest_id = member["guest_id"]
        if not isinstance(guest_id, str) or guest_id == "":
            fields.bad(label + ".guest_id", "must be a non-empty string")
        member_type = member["member_type"]
        if member_type not in MEMBER_TYPES:
            fields.bad(label + ".member_type", "must be one of: ADULT, CHILD")
        diet = member.get("dietary_restrictions")
        if diet is None:
            diet = []
        if not isinstance(diet, list):
            fields.bad(label + ".dietary_restrictions", "must be an array")
        for value in diet:
            if not isinstance(value, str) or value not in DIETARY:
                fields.bad(
                    label + ".dietary_restrictions",
                    "may only contain: %s" % ", ".join(DIETARY),
                )
        cleaned.append(
            {
                "guest_id": guest_id,
                "member_type": member_type,
                "dietary_restrictions": list(diet),
            }
        )
    return cleaned


def _live_bookings(skip_id=None):
    out = []
    for booking in db.rows("bookings"):
        if booking["id"] == skip_id:
            continue
        if booking["booking_status"] in derive.LIVE_BOOKING_STATUSES:
            out.append(booking)
    return out


@bp.post("/bookings")
def create_booking():
    auth("ReservationsAgent")
    data = body()

    # Precedence rule 8: every payload foreign key resolves first.
    season = find_body_ref("seasons", data, "season_id")
    cabin = find_body_ref("cabins", data, "cabin_id")
    find_body_ref("guests", data, "lead_guest_id")
    if isinstance(data.get("party_members"), list):
        for member in data["party_members"]:
            if isinstance(member, dict) and isinstance(member.get("guest_id"), str):
                find("guests", member["guest_id"])

    require(
        data,
        "season_id",
        "cabin_id",
        "lead_guest_id",
        "package_tier_code",
        "arrival_date",
        "departure_date",
        "party_members",
    )
    fields.as_str(data, "season_id")
    fields.as_str(data, "cabin_id")
    lead_guest_id = fields.as_str(data, "lead_guest_id")
    tier_code = fields.as_str(data, "package_tier_code")
    arrival = fields.as_date(data, "arrival_date")
    departure = fields.as_date(data, "departure_date")
    is_buyout = fields.as_bool(data, "is_buyout", default=False)
    members = _validate_members(data)

    if season["season_status"] not in ("OPEN", "IN_SEASON"):
        raise ApiError(
            "ERR_SEASON_NOT_OPEN",
            "A booking may only be held against an OPEN or IN_SEASON season.",
        )

    nights = (departure - arrival).days
    if WEEKDAY_NAMES[arrival.weekday()] != season["arrival_weekday"]:
        raise ApiError(
            "ERR_ARRIVAL_DAY_INVALID",
            "Arrival must fall on %s." % season["arrival_weekday"],
        )
    if nights < int(season["min_stay_nights"]) or nights > int(season["max_stay_nights"]):
        raise ApiError(
            "ERR_STAY_LENGTH_INVALID",
            "A stay of %d night(s) is outside the season's bounds." % nights,
        )
    if arrival < season["season_start_date"] or departure > season["season_end_date"]:
        raise ApiError(
            "ERR_STAY_OUTSIDE_SEASON", "The stay window falls outside the season."
        )

    for other in _live_bookings():
        if other["cabin_id"] != cabin["id"]:
            continue
        if calc.dates_overlap(
            arrival, departure, other["arrival_date"], other["departure_date"]
        ):
            raise ApiError(
                "ERR_CABIN_DOUBLE_BOOKED",
                "Another live booking already occupies this cabin over that interval.",
            )
    for other in _live_bookings():
        if other["season_id"] != season["id"]:
            continue
        if not calc.dates_overlap(
            arrival, departure, other["arrival_date"], other["departure_date"]
        ):
            continue
        if is_buyout or other["is_buyout"]:
            raise ApiError(
                "ERR_BUYOUT_CONFLICT",
                "Whole-ranch exclusivity is broken over that interval.",
            )

    for member in members:
        guest = db.guests[member["guest_id"]]
        age = derive.guest_age(guest)
        if member["member_type"] == "ADULT" and age < calc.ADULT_AGE_YEARS:
            raise ApiError(
                "ERR_MEMBER_TYPE_MISMATCH",
                "An ADULT roster entry requires a guest aged 18 or over.",
            )
        if member["member_type"] == "CHILD" and age >= calc.ADULT_AGE_YEARS:
            raise ApiError(
                "ERR_MEMBER_TYPE_MISMATCH",
                "A CHILD roster entry requires a guest under 18.",
            )

    roster_ids = [m["guest_id"] for m in members]
    adults = len([m for m in members if m["member_type"] == "ADULT"])
    if lead_guest_id not in roster_ids or adults < 1:
        raise ApiError(
            "ERR_LEAD_GUEST_NOT_IN_PARTY",
            "The lead guest must appear on a roster holding at least one adult.",
        )
    if len(set(roster_ids)) != len(roster_ids):
        raise ApiError(
            "ERR_DUPLICATE_PARTY_MEMBER", "A guest may appear on the roster only once."
        )
    tier = _tier(season, tier_code)
    if tier is None:
        raise ApiError(
            "ERR_PACKAGE_TIER_UNKNOWN",
            "The season publishes no tier '%s'." % tier_code,
        )
    if len(members) > int(cabin["bed_capacity"]):
        raise ApiError(
            "ERR_CABIN_CAPACITY_EXCEEDED",
            "The party of %d exceeds the cabin's bed capacity." % len(members),
        )

    total = _price(season, tier, members, nights, is_buyout)
    row = db.insert(
        "bookings",
        {
            "season_id": season["id"],
            "cabin_id": cabin["id"],
            "lead_guest_id": lead_guest_id,
            "package_tier_code": tier_code,
            "arrival_date": arrival,
            "departure_date": departure,
            "nights": nights,
            "is_buyout": is_buyout,
            "party_members": members,
            "party_size": len(members),
            "adult_count": adults,
            "child_count": len(members) - adults,
            "dietary_briefing_ack": False,
            "booking_status": "HELD",
            "payment_status": "AWAITING_DEPOSIT",
            "provisional_package_total_cents": total,
            "deposit_required_cents": calc.deposit_required_cents(
                total, season["deposit_pct"]
            ),
            "deposit_paid_cents": 0,
            "payments_applied_cents": 0,
            "refunded_cents": 0,
            "forfeited_cents": 0,
            "activity_surcharge_total_cents": 0,
            "activity_credit_applied_cents": 0,
            "no_show_count": 0,
            "no_show_penalty_total_cents": 0,
            "gratuity_cents": 0,
            "folio_adjustment_total_cents": 0,
            "realized_nights": 0,
            "realized_subtotal_cents": 0,
            "final_folio_total_cents": 0,
            "folio_balance_cents": 0,
            "cancellation_refund_pct": 0,
            "checked_in_at": None,
            "checked_out_at": None,
            "cancelled_at": None,
        },
    )
    return created(booking_json(row))


@bp.get("/bookings/<booking_id>")
def read_booking(booking_id):
    auth("RanchManager", "ReservationsAgent", "SafetyOfficer", "Guest")
    return ok(booking_json(find("bookings", booking_id)))


@bp.get("/bookings")
def list_bookings():
    auth("RanchManager", "ReservationsAgent", "SafetyOfficer")
    rows = derive.rows_of(
        "bookings",
        season_id=fields.query_filter("season_id"),
        cabin_id=fields.query_filter("cabin_id"),
        lead_guest_id=fields.query_filter("lead_guest_id"),
        booking_status=fields.query_enum("booking_status", BOOKING_STATUSES),
    )
    return listing(rows, booking_json)


# ------------------------------------------------------------------- money
@bp.post("/bookings/<booking_id>/payments")
def post_payment(booking_id):
    auth("ReservationsAgent")
    booking = find("bookings", booking_id)
    data = body()
    require(data, "kind", "amount_cents")
    kind = data["kind"]
    amount = data["amount_cents"]
    if not isinstance(kind, str):
        fields.bad("kind", "must be a string")
    if isinstance(amount, bool) or not isinstance(amount, int):
        fields.bad("amount_cents", "must be an integer")
    if kind not in PAYMENT_KINDS or amount <= 0:
        raise ApiError(
            "ERR_INVALID_PAYMENT_AMOUNT",
            "A payment must be a positive amount of kind DEPOSIT or SETTLEMENT.",
        )
    if booking["booking_status"] not in ("HELD", "CONFIRMED"):
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "A %s booking takes no payment." % booking["booking_status"],
        )

    if kind == "DEPOSIT":
        booking["deposit_paid_cents"] = int(booking["deposit_paid_cents"]) + amount
        if (
            booking["payment_status"] == "AWAITING_DEPOSIT"
            and int(booking["deposit_paid_cents"]) >= int(booking["deposit_required_cents"])
        ):
            booking["payment_status"] = "DEPOSIT_PAID"
    else:
        booking["payments_applied_cents"] = (
            int(booking["payments_applied_cents"]) + amount
        )
    db.touch(booking)
    return ok(booking_json(booking))


@bp.post("/bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    auth("ReservationsAgent")
    booking = find("bookings", booking_id)
    season = db.seasons.get(booking["season_id"])
    if season is None or season["season_status"] not in ("OPEN", "IN_SEASON"):
        raise ApiError(
            "ERR_SEASON_NOT_OPEN",
            "Confirmation requires an OPEN or IN_SEASON season.",
        )
    if booking["booking_status"] != "HELD":
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "Only a HELD booking may be confirmed; this one is %s."
            % booking["booking_status"],
        )
    if int(booking["deposit_paid_cents"]) < int(booking["deposit_required_cents"]):
        raise ApiError(
            "ERR_DEPOSIT_INSUFFICIENT", "The deposit has not been paid in full."
        )

    booking["booking_status"] = "CONFIRMED"
    season["bed_nights_sold"] = int(season["bed_nights_sold"]) + int(
        booking["party_size"]
    ) * int(booking["nights"])
    db.touch(booking)
    db.touch(season)
    return ok(booking_json(booking))


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    auth("ReservationsAgent", "RanchManager")
    booking = find("bookings", booking_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    if booking["booking_status"] not in ("HELD", "CONFIRMED"):
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "A %s booking cannot be cancelled." % booking["booking_status"],
        )

    days_out = (booking["arrival_date"] - db.clock_date()).days
    pct, refunded, forfeited = calc.cancellation_refund_split(
        int(booking["deposit_paid_cents"]), days_out
    )
    booking["cancellation_refund_pct"] = pct
    booking["refunded_cents"] = refunded
    booking["forfeited_cents"] = forfeited
    # "A booking cancelled while nothing had yet been collected -
    # deposit_paid_cents at 0, payment_status still AWAITING_DEPOSIT - moves to
    # FORFEITED with both refunded_cents and forfeited_cents at 0, since the
    # conserved total is itself 0."  The band-to-status mapping below is framed
    # as a move out of DEPOSIT_PAID, so an unpaid hold forfeits regardless of
    # the band its arrival date selects.
    if int(booking["deposit_paid_cents"]) == 0 and (
        booking["payment_status"] == "AWAITING_DEPOSIT"
    ):
        booking["payment_status"] = "FORFEITED"
    elif pct >= 1.0:
        booking["payment_status"] = "REFUNDED"
    elif pct > 0.0:
        booking["payment_status"] = "PARTIALLY_REFUNDED"
    else:
        booking["payment_status"] = "FORFEITED"

    was_confirmed = booking["booking_status"] == "CONFIRMED"
    booking["booking_status"] = "CANCELLED"
    booking["cancelled_at"] = db.clock_iso()

    touch = Touch()
    for seat in derive.rows_of("activity_reservations", booking_id=booking["id"]):
        if seat["reservation_status"] in derive.LIVE_SEAT_STATUSES:
            derive.cancel_seat(seat, touch)
    touch.add(booking)
    season = db.seasons.get(booking["season_id"])
    if was_confirmed and season is not None:
        season["bed_nights_sold"] = int(season["bed_nights_sold"]) - int(
            booking["party_size"]
        ) * int(booking["nights"])
        touch.add(season)
    touch.finalize()
    return ok(booking_json(booking))


# ------------------------------------------------------- arrival and departure
@bp.post("/bookings/<booking_id>/check-in")
def check_in_booking(booking_id):
    auth("ReservationsAgent")
    booking = find("bookings", booking_id)
    data = body()
    require(data, "dietary_briefing_ack")
    ack = fields.as_bool(data, "dietary_briefing_ack")

    season = db.seasons.get(booking["season_id"])
    cabin = db.cabins.get(booking["cabin_id"])
    if season is None or season["season_status"] != "IN_SEASON":
        raise ApiError("ERR_SEASON_NOT_OPEN", "Arrival requires an IN_SEASON season.")
    if booking["booking_status"] != "CONFIRMED":
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "Only a CONFIRMED booking may check in; this one is %s."
            % booking["booking_status"],
        )
    if cabin is None or cabin["cabin_status"] != "READY":
        raise ApiError("ERR_CABIN_NOT_READY", "The cabin is not READY.")

    declares = False
    for member in booking["party_members"]:
        for value in member.get("dietary_restrictions") or []:
            if value != "NONE":
                declares = True
    if declares and ack is not True:
        raise ApiError(
            "ERR_DIETARY_BRIEFING_REQUIRED",
            "The kitchen must acknowledge the party's dietary requirements.",
        )
    party_size = int(booking["party_size"])
    if int(season["in_house_guest_count"]) + party_size > int(
        season["dining_seat_capacity"]
    ):
        raise ApiError(
            "ERR_DINING_CAPACITY_EXCEEDED",
            "The party does not fit the remaining single-seating capacity.",
        )

    booking["booking_status"] = "CHECKED_IN"
    booking["checked_in_at"] = db.clock_iso()
    booking["dietary_briefing_ack"] = ack
    cabin["cabin_status"] = "OCCUPIED"
    season["in_house_guest_count"] = int(season["in_house_guest_count"]) + party_size
    db.touch(booking)
    db.touch(cabin)
    db.touch(season)
    return ok(booking_json(booking))


@bp.post("/bookings/<booking_id>/check-out")
def check_out_booking(booking_id):
    auth("ReservationsAgent")
    booking = find("bookings", booking_id)
    data = body()
    require(data, "settle_payment_cents")
    settle = fields.as_cents(data, "settle_payment_cents")

    if booking["booking_status"] != "CHECKED_IN":
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "Only a CHECKED_IN booking may check out; this one is %s."
            % booking["booking_status"],
        )
    seats = derive.rows_of("activity_reservations", booking_id=booking["id"])
    for seat in seats:
        if seat["reservation_status"] not in derive.LIVE_SEAT_STATUSES:
            continue
        slot = db.activity_slots.get(seat["slot_id"])
        if slot is not None and slot["slot_status"] in derive.LIVE_SLOT_STATUSES:
            raise ApiError(
                "ERR_OPEN_ACTIVITY_RESERVATIONS",
                "A seat of this booking is still live on a live slot.",
            )

    season = db.seasons.get(booking["season_id"])
    cabin = db.cabins.get(booking["cabin_id"])
    tier = _tier(season, booking["package_tier_code"]) if season else None
    if season is None or tier is None:
        raise ApiError(
            "ERR_PACKAGE_TIER_UNKNOWN", "The booking's package tier is unknown."
        )

    # Step 1: re-price the stay over the nights actually occupied.
    realized_nights = (db.clock_date() - booking["arrival_date"]).days
    realized_subtotal = _price(
        season, tier, booking["party_members"], realized_nights, booking["is_buyout"]
    )
    # Step 2: surcharges actually incurred, less the reversals.
    surcharge_total = 0
    for seat in seats:
        if seat["reservation_status"] in FOLIO_SURCHARGE_STATUSES:
            surcharge_total += int(seat["surcharge_cents"] or 0)
        elif seat["reservation_status"] == "CANCELLED":
            surcharge_total -= int(seat["surcharge_reversed_cents"] or 0)
    # Steps 3 and 4: the included activity credit, capped by what was incurred.
    ceiling = calc.activity_credit_cap(tier, realized_subtotal)
    credit = ceiling if ceiling < surcharge_total else surcharge_total
    # Step 5: no-show penalties.
    no_show_total = int(booking["no_show_count"]) * int(season["no_show_penalty_cents"])
    # Steps 6 and 7: gratuity on the package subtotal alone.
    gratuity = calc.gratuity_cents(realized_subtotal)
    # Step 8: manual adjustments already posted.
    adjustments = int(booking["folio_adjustment_total_cents"])
    # Step 9 and 10.
    final_total = (
        realized_subtotal
        + surcharge_total
        - credit
        + no_show_total
        + gratuity
        + adjustments
    )
    payments_applied = int(booking["payments_applied_cents"]) + settle
    balance = final_total - int(booking["deposit_paid_cents"]) - payments_applied
    if balance != 0:
        raise ApiError(
            "ERR_FOLIO_BALANCE_OUTSTANDING",
            "The folio settles to %d cents rather than zero." % balance,
        )

    booking["realized_nights"] = realized_nights
    booking["realized_subtotal_cents"] = realized_subtotal
    booking["activity_surcharge_total_cents"] = surcharge_total
    booking["activity_credit_applied_cents"] = credit
    booking["no_show_penalty_total_cents"] = no_show_total
    booking["gratuity_cents"] = gratuity
    booking["folio_adjustment_total_cents"] = adjustments
    booking["final_folio_total_cents"] = final_total
    booking["payments_applied_cents"] = payments_applied
    booking["folio_balance_cents"] = 0
    booking["payment_status"] = "PAID_IN_FULL"
    booking["booking_status"] = "CHECKED_OUT"
    booking["checked_out_at"] = db.clock_iso()
    party_size = int(booking["party_size"])
    if cabin is not None:
        cabin["cabin_status"] = "TURNOVER"
        db.touch(cabin)
    season["in_house_guest_count"] = int(season["in_house_guest_count"]) - party_size
    season["gross_package_revenue_cents"] = (
        int(season["gross_package_revenue_cents"]) + final_total
    )
    db.touch(booking)
    db.touch(season)
    return ok(booking_json(booking))


@bp.post("/bookings/<booking_id>/folio-adjustments")
def folio_adjustment(booking_id):
    auth("RanchManager", "ReservationsAgent")
    booking = find("bookings", booking_id)
    data = body()
    require(data, "amount_cents", "memo", "expected_booking_version")
    amount = fields.as_int(data, "amount_cents")
    fields.as_str(data, "memo")
    pin = fields.as_int(data, "expected_booking_version")

    if pin != int(booking["version"]):
        raise ApiError(
            "ERR_STALE_BOOKING_VERSION",
            "The supplied expected_booking_version is out of date.",
        )
    if booking["booking_status"] not in ("CONFIRMED", "CHECKED_IN", "CHECKED_OUT"):
        raise ApiError(
            "ERR_BOOKING_STATE_INVALID",
            "A %s booking takes no folio adjustment." % booking["booking_status"],
        )

    booking["folio_adjustment_total_cents"] = (
        int(booking["folio_adjustment_total_cents"]) + amount
    )
    if booking["booking_status"] == "CHECKED_OUT":
        booking["final_folio_total_cents"] = (
            int(booking["final_folio_total_cents"]) + amount
        )
        booking["folio_balance_cents"] = (
            int(booking["final_folio_total_cents"])
            - int(booking["deposit_paid_cents"])
            - int(booking["payments_applied_cents"])
        )
    db.touch(booking)
    return ok(booking_json(booking))
