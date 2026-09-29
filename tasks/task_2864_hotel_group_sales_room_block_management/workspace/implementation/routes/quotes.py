"""Rate quoting and the negotiation cycle (PRD §3.4)."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import quote_json

bp = Blueprint("quotes", __name__)

QUOTE_READ_ROLES = [ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
                    ROLE_GROUP_CONTACT]


def _check_eligibility(package, peak_rooms, room_nights):
    """validations priority 26."""
    if peak_rooms < package["min_peak_rooms"] or room_nights < package["min_total_room_nights"]:
        fail("ERR_CONCESSION_INELIGIBLE",
             "The program is below the package floors of %s peak rooms and %s room nights."
             % (package["min_peak_rooms"], package["min_total_room_nights"]))


def _check_stack(package):
    """validations priority 27."""
    if discount_stack(package) > D(package["max_discount_stack_pct"]):
        fail("ERR_DISCOUNT_STACK_EXCEEDED",
             "The package's discount stack exceeds its own cap.")


@bp.route("/group-sales/rate-quotes", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER])
def create_quote():
    body = body_json()
    lead_id = v_id(body, "lead_id")
    package_id = v_id(body, "concession_package_id")
    base_rate = v_int(body, "base_rate_cents", minimum=1)
    peak_rooms = v_int(body, "quoted_peak_rooms", minimum=1)
    room_nights = v_int(body, "quoted_room_nights", minimum=1)
    expires_at = v_instant(body, "expires_at")
    expected = v_int(body, "expected_lead_version", minimum=0)
    lead = need_lead(lead_id)
    package = need_package(package_id)
    if expires_at <= store.now():
        fail("ERR_INVALID_DATE_RANGE",
             "'expires_at' must be strictly later than the current logical clock.")
    if expected != lead["version"]:
        fail("ERR_STALE_LEAD_VERSION",
             "expected_lead_version %s does not match the lead's version %s."
             % (expected, lead["version"]))
    if lead["status"] != "CLEARED":
        fail("ERR_LEAD_INVALID_STATE",
             "A quote may only be drafted against a CLEARED lead; it is %s."
             % lead["status"])
    _check_eligibility(package, peak_rooms, room_nights)
    _check_stack(package)
    net_rate = effective_net_rate(base_rate, package["room_rate_discount_pct"],
                                 package["comp_room_ratio"],
                                 package["rebate_per_room_night_cents"])
    row = new_row({
        "lead_id": lead_id,
        "concession_package_id": package_id,
        "prepared_by_user_id": actor(),
        "negotiation_round": 1,
        "status": "DRAFT",
        "base_rate_cents": base_rate,
        "quoted_peak_rooms": peak_rooms,
        "quoted_room_nights": room_nights,
        "comp_room_ratio": package["comp_room_ratio"],
        "rebate_per_room_night_cents": package["rebate_per_room_night_cents"],
        "effective_net_rate_cents": net_rate,
        "total_quote_value_cents": net_rate * room_nights,
        "expires_at": iso_instant(expires_at),
        "hold_placed": False,
        "countered_base_rate_cents": None,
        "counter_note": None,
    })
    # A newer quote supersedes a DRAFT one already sitting on the lead; a draft
    # never held rooms, so no inventory moves (PRD §3.4).
    withdraw_quotes_of_lead(lead_id, skip_quote_id=row["id"], statuses=("DRAFT",))
    store.quotes[row["id"]] = row
    return ok(quote_json(row), 201)


@bp.route("/group-sales/rate-quotes/<quote_id>", methods=["GET"])
@endpoint(QUOTE_READ_ROLES)
def read_quote(quote_id):
    quote = need_quote(quote_id)
    require_owner(owner_of_quote(quote))
    return ok(quote_json(quote))


@bp.route("/group-sales/rate-quotes", methods=["GET"])
@endpoint(QUOTE_READ_ROLES)
def list_quotes():
    limit, offset = q_pagination()
    lead_id = q_str("lead_id")
    package_id = q_str("concession_package_id")
    status = q_enum("status", QUOTE_STATUSES)
    rows = in_order(list(store.quotes.values()))
    if lead_id is not None:
        rows = [r for r in rows if r["lead_id"] == lead_id]
    if package_id is not None:
        rows = [r for r in rows if r["concession_package_id"] == package_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    rows = filter_owned(rows, owner_of_quote)
    page, total = paginate(rows, limit, offset)
    return ok_list([quote_json(r) for r in page], limit, offset, total)


@bp.route("/group-sales/rate-quotes/<quote_id>/propose", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER])
def propose_quote(quote_id):
    quote = need_quote(quote_id)
    lead = need_lead(quote["lead_id"])
    if quote["status"] != "DRAFT":
        fail("ERR_QUOTE_INVALID_STATE",
             "Propose is declared only from DRAFT; the quote is %s." % quote["status"])
    if lead["status"] != "CLEARED":
        fail("ERR_LEAD_INVALID_STATE",
             "The lead must be CLEARED to propose; it is %s." % lead["status"])
    if not lead_has_approved_analysis(lead["id"]):
        fail("ERR_DISPLACEMENT_NOT_APPROVED",
             "The lead carries no APPROVED displacement analysis.")
    days = stay_dates(lead["arrival_date"], lead["departure_date"])
    require_calendar(days)
    check_group_ceiling([(day, quote["quoted_peak_rooms"]) for day in days])
    move_held(days, quote["quoted_peak_rooms"])
    quote["status"] = "PROPOSED"
    quote["hold_placed"] = True
    touch(quote)
    lead["status"] = "QUOTED"
    touch(lead)
    return ok(quote_json(quote))


@bp.route("/group-sales/rate-quotes/<quote_id>/counter", methods=["POST"])
@endpoint([ROLE_GROUP_CONTACT])
def counter_quote(quote_id):
    body = body_json()
    countered = v_int(body, "countered_base_rate_cents", minimum=1)
    note = v_string(body, "counter_note", required=False, min_len=None,
                    max_len=500, allow_blank=True)
    quote = need_quote(quote_id)
    require_owner(owner_of_quote(quote))
    if quote["status"] != "PROPOSED":
        fail("ERR_QUOTE_INVALID_STATE",
             "Counter is declared only from PROPOSED; the quote is %s."
             % quote["status"])
    expire_quote_if_lapsed(quote)
    quote["status"] = "COUNTERED"
    quote["countered_base_rate_cents"] = countered
    quote["counter_note"] = note
    touch(quote)
    return ok(quote_json(quote))


@bp.route("/group-sales/rate-quotes/<quote_id>/revise", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER])
def revise_quote(quote_id):
    body = body_json()
    base_rate = v_int(body, "base_rate_cents", minimum=1)
    peak_rooms = v_int(body, "quoted_peak_rooms", minimum=1)
    room_nights = v_int(body, "quoted_room_nights", minimum=1)
    expires_at = v_instant(body, "expires_at")
    quote = need_quote(quote_id)
    lead = need_lead(quote["lead_id"])
    if expires_at <= store.now():
        fail("ERR_INVALID_DATE_RANGE",
             "'expires_at' must be strictly later than the current logical clock.")
    if quote["status"] != "COUNTERED":
        fail("ERR_QUOTE_INVALID_STATE",
             "Revise is declared only from COUNTERED; the quote is %s."
             % quote["status"])
    if lead["status"] != "QUOTED":
        fail("ERR_LEAD_INVALID_STATE",
             "The lead must be QUOTED to revise a quote; it is %s." % lead["status"])
    package = need_package(quote["concession_package_id"])
    _check_eligibility(package, peak_rooms, room_nights)
    old_peak = quote["quoted_peak_rooms"]
    days = quote_stay_dates(quote)
    if peak_rooms > old_peak:
        # The deal grew materially: drop the hold and send it back for review.
        release_quote_hold(quote)
        new_status = "DRAFT"
    else:
        check_group_ceiling([(day, peak_rooms) for day in days],
                            exclude_held=old_peak)
        move_held(days, peak_rooms - old_peak)
        new_status = "PROPOSED"
    net_rate = effective_net_rate(base_rate, package["room_rate_discount_pct"],
                                 quote["comp_room_ratio"],
                                 quote["rebate_per_room_night_cents"])
    quote["base_rate_cents"] = base_rate
    quote["quoted_peak_rooms"] = peak_rooms
    quote["quoted_room_nights"] = room_nights
    quote["expires_at"] = iso_instant(expires_at)
    quote["effective_net_rate_cents"] = net_rate
    quote["total_quote_value_cents"] = net_rate * room_nights
    quote["negotiation_round"] = quote["negotiation_round"] + 1
    quote["status"] = new_status
    touch(quote)
    if new_status == "DRAFT":
        lead["status"] = "DISPLACEMENT_REVIEW"
        touch(lead)
    return ok(quote_json(quote))


@bp.route("/group-sales/rate-quotes/<quote_id>/accept", methods=["POST"])
@endpoint([ROLE_GROUP_CONTACT])
def accept_quote(quote_id):
    quote = need_quote(quote_id)
    lead = need_lead(quote["lead_id"])
    require_owner(owner_of_quote(quote))
    if actor() == quote["prepared_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "The user who prepared the quote may not accept it.")
    if quote["status"] not in ("PROPOSED", "COUNTERED"):
        fail("ERR_QUOTE_INVALID_STATE",
             "Accept is declared from PROPOSED or COUNTERED; the quote is %s."
             % quote["status"])
    if lead["status"] != "QUOTED":
        fail("ERR_LEAD_INVALID_STATE",
             "The lead must be QUOTED to accept a quote; it is %s." % lead["status"])
    expire_quote_if_lapsed(quote)
    require_displacement_cleared(lead["id"])
    quote["status"] = "ACCEPTED"
    touch(quote)
    lead["status"] = "WON"
    withdraw_quotes_of_lead(lead["id"], skip_quote_id=quote["id"])
    touch(lead)
    return ok(quote_json(quote))
