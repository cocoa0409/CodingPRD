"""Client organizations, the house calendar, concession design and the clock."""

from flask import Blueprint

from core import *  # noqa: F401,F403
from logic import *  # noqa: F401,F403
from serialize import account_json, inventory_day_json, lead_json, package_json

bp = Blueprint("catalog", __name__)

READ_ALL = [ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
            ROLE_ACCOUNTING_CLERK, ROLE_GROUP_CONTACT]


# ------------------------------------------------------------------ accounts

@bp.route("/group-sales/accounts", methods=["POST"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER])
def create_account():
    body = body_json()
    name = v_string(body, "name", min_len=1, max_len=120)
    segment = v_enum(body, "market_segment", MARKET_SEGMENTS)
    email = v_string(body, "billing_contact_email", min_len=1, max_len=320)
    if "@" not in email:
        fail("ERR_INVALID_REQUEST", "Field 'billing_contact_email' must contain '@'.")
    credit_hold = v_bool(body, "credit_hold", required=False, default=False)
    row = new_row({
        "name": name,
        "market_segment": segment,
        "billing_contact_email": email,
        "credit_hold": credit_hold,
    })
    store.accounts[row["id"]] = row
    return ok(account_json(row), 201)


@bp.route("/group-sales/accounts/<account_id>", methods=["GET"])
@endpoint(READ_ALL)
def read_account(account_id):
    row = need_account(account_id)
    require_owner(row["id"])
    return ok(account_json(row))


@bp.route("/group-sales/accounts/<account_id>/leads", methods=["GET"])
@endpoint(READ_ALL)
def list_account_leads(account_id):
    limit, offset = q_pagination()
    status = q_enum("status", LEAD_STATUSES)
    row = need_account(account_id)
    require_owner(row["id"])
    rows = leads_of_account(account_id)
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return ok_list([lead_json(r) for r in page], limit, offset, total)


# --------------------------------------------------------- concession packages

@bp.route("/group-sales/concession-packages", methods=["POST"])
@endpoint([ROLE_REVENUE_MANAGER])
def create_package():
    body = body_json()
    row = new_row({
        "name": v_string(body, "name", min_len=1, max_len=60),
        "room_rate_discount_pct": v_number(body, "room_rate_discount_pct",
                                           minimum=0, maximum=0.5),
        "comp_room_ratio": v_int(body, "comp_room_ratio", minimum=1),
        "rebate_per_room_night_cents": v_int(body, "rebate_per_room_night_cents",
                                             minimum=0),
        "banquet_discount_pct": v_number(body, "banquet_discount_pct",
                                         minimum=0, maximum=0.5),
        "av_discount_pct": v_number(body, "av_discount_pct", minimum=0, maximum=0.5),
        "parking_discount_pct": v_number(body, "parking_discount_pct",
                                         minimum=0, maximum=0.5),
        "min_peak_rooms": v_int(body, "min_peak_rooms", minimum=0),
        "min_total_room_nights": v_int(body, "min_total_room_nights", minimum=0),
        "max_discount_stack_pct": v_number(body, "max_discount_stack_pct",
                                           exclusive_min=0, maximum=1),
    })
    stack = discount_stack(row)
    row["discount_stack_pct"] = float(stack)
    if stack > D(row["max_discount_stack_pct"]):
        fail("ERR_DISCOUNT_STACK_EXCEEDED",
             "The four discount fractions sum to %s, above the cap of %s."
             % (stack, row["max_discount_stack_pct"]))
    store.packages[row["id"]] = row
    return ok(package_json(row), 201)


@bp.route("/group-sales/concession-packages/<package_id>", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_ACCOUNTING_CLERK])
def read_package(package_id):
    return ok(package_json(need_package(package_id)))


# ----------------------------------------------------------- inventory days

@bp.route("/group-sales/inventory-days", methods=["POST"])
@endpoint([ROLE_REVENUE_MANAGER])
def create_inventory_day():
    body = body_json()
    stay_date = v_date(body, "stay_date")
    total_rooms = v_int(body, "total_rooms", minimum=1)
    ceiling = v_int(body, "group_ceiling_rooms", minimum=0)
    demand = v_int(body, "transient_demand_rooms", minimum=0)
    adr = v_int(body, "transient_adr_cents", minimum=0)
    hist_rooms = v_int(body, "historical_pickup_rooms", minimum=0)
    hist_adr = v_int(body, "historical_adr_cents", minimum=0)
    if ceiling > total_rooms:
        fail("ERR_INVALID_REQUEST",
             "Field 'group_ceiling_rooms' may not exceed 'total_rooms'.")
    key = iso_date(stay_date)
    existing = store.inventory_by_date.get(key)
    if existing is not None:
        existing.update({
            "total_rooms": total_rooms,
            "group_ceiling_rooms": ceiling,
            "transient_demand_rooms": demand,
            "transient_adr_cents": adr,
            "historical_pickup_rooms": hist_rooms,
            "historical_adr_cents": hist_adr,
        })
        touch(existing)
        return ok(inventory_day_json(existing), 201)
    row = new_row({
        "stay_date": key,
        "total_rooms": total_rooms,
        "group_ceiling_rooms": ceiling,
        "transient_demand_rooms": demand,
        "transient_adr_cents": adr,
        "historical_pickup_rooms": hist_rooms,
        "historical_adr_cents": hist_adr,
        "held_group_rooms": 0,
        "committed_group_rooms": 0,
    })
    store.inventory_days[row["id"]] = row
    store.inventory_by_date[key] = row
    return ok(inventory_day_json(row), 201)


@bp.route("/group-sales/inventory-days", methods=["GET"])
@endpoint([ROLE_SALES_MANAGER, ROLE_REVENUE_MANAGER, ROLE_CONTRACT_ADMIN,
           ROLE_ACCOUNTING_CLERK])
def list_inventory_days():
    limit, offset = q_pagination()
    from_date = q_date("from_date")
    to_date = q_date("to_date")
    rows = sorted(store.inventory_days.values(), key=lambda r: r["stay_date"])
    if from_date is not None:
        rows = [r for r in rows if r["stay_date"] >= iso_date(from_date)]
    if to_date is not None:
        rows = [r for r in rows if r["stay_date"] < iso_date(to_date)]
    page, total = paginate(rows, limit, offset)
    return ok_list([inventory_day_json(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------- the clock

@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint([ROLE_SYSTEM_OPERATOR])
def set_clock():
    body = body_json()
    moment = v_instant(body, "to_iso8601")
    store.clock = moment
    return ok({"current_utc": iso_instant(moment)})
