"""Hospitality packages, the secondary market and gate scans."""
from datetime import timedelta

from flask import Blueprint

import calc
from core import (D, ROLE_ADMIN, ROLE_HOLDER, ROLE_REVENUE, ROLE_SALES, READ_ROLES, apply_filters,
                  bad_request, body, bump, base_fields, db, endpoint, err, find_account, find_game,
                  find_order, find_package, find_seat, find_transfer, new_id, now, ok, ok_page,
                  opt_str, pagination, paginate, req_datetime, req_enum, req_int, req_str, rhu,
                  sort_created)
from routes_accounts import gate_account_written_off, gate_holder_ownership, gate_rep_ownership
from routes_orders import gate_not_delinquent, gate_order_status
from routes_setup import gate_status

bp = Blueprint("market", __name__)


def release_package(pkg):
    pkg["package_status"] = "RELEASED"
    game = db.games.get(pkg["game_id"])
    if game is not None:
        calc.recompute_booked_headcount(game)
        calc.recompute_attendance(game)
        bump(game)
    bump(pkg)


# ---------------------------------------------------------------------------
# Hospitality packages (PRD 3.9)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/hospitality-packages", methods=["POST"])
@endpoint(ROLE_SALES)
def book_package(caller):
    data = body()
    game_id = req_str(data, "game_id")
    account_id = req_str(data, "account_id")
    suite_code = req_str(data, "suite_code")
    headcount = req_int(data, "headcount", minimum=1)
    window_start = req_datetime(data, "service_window_start_utc")
    window_end = req_datetime(data, "service_window_end_utc")
    if not (window_end > window_start):
        bad_request("Field 'service_window_end_utc' must be strictly after 'service_window_start_utc'.")

    game = find_game(game_id)
    account = find_account(account_id)
    gate_rep_ownership(caller, account)

    season = calc.season_of_game(game)
    gate_status(season, ("RENEWAL_OPEN", "GENERAL_ONSALE", "IN_SEASON"))

    if game["game_status"] != "SCHEDULED":
        err("ERR_GAME_ALREADY_PLAYED", 409, "The game has already been played.")

    gate_account_written_off(account)

    turnover = timedelta(minutes=calc.HOSPITALITY_TURNOVER_MINUTES)
    for pkg in db.packages.values():
        if pkg["game_id"] != game_id or pkg["suite_code"] != suite_code:
            continue
        if pkg["package_status"] not in ("HELD", "CONFIRMED"):
            continue
        if window_start >= pkg["service_window_end_utc"]:
            gap = window_start - pkg["service_window_end_utc"]
        elif pkg["service_window_start_utc"] >= window_end:
            gap = pkg["service_window_start_utc"] - window_end
        else:
            err("ERR_SUITE_WINDOW_CONFLICT", 409, "The suite window overlaps an existing package.")
        if gap < turnover:
            err("ERR_SUITE_WINDOW_CONFLICT", 409,
                "The suite window must be separated by at least 30 minutes of turnover.")

    if game["hospitality_booked_headcount"] + headcount > game["hospitality_headcount_cap"]:
        err("ERR_HOSPITALITY_CAPACITY_EXCEEDED", 422, "The game's hospitality headcount cap is exceeded.")

    fee = calc.hospitality_fee(game, headcount)
    row = {"id": new_id(), "game_id": game_id, "account_id": account_id, "suite_code": suite_code,
           "headcount": headcount, "service_window_start_utc": window_start,
           "service_window_end_utc": window_end, "package_status": "HELD",
           "gross_fee_cents": fee["gross_fee_cents"],
           "partner_discount_pct": fee["partner_discount_pct"],
           "service_fee_cents": fee["service_fee_cents"],
           "total_due_cents": fee["total_due_cents"]}
    row.update(base_fields())
    db.packages[row["id"]] = row

    calc.recompute_booked_headcount(game)
    calc.recompute_attendance(game)
    bump(game)
    return ok(row, 201)


@bp.route("/ticketing/hospitality-packages/<package_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_package(caller, package_id):
    return ok(find_package(package_id))


@bp.route("/ticketing/hospitality-packages", methods=["GET"])
@endpoint(*READ_ROLES)
def list_packages(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.packages.values()), [
        ("game_id", "game_id"), ("account_id", "account_id"), ("package_status", "package_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Ticket transfers (PRD 3.10)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/ticket-transfers", methods=["POST"])
@endpoint(ROLE_HOLDER)
def request_transfer(caller):
    data = body()
    order_id = req_str(data, "order_id")
    game_id = req_str(data, "game_id")
    seat_id = req_str(data, "seat_id")
    transfer_type = req_enum(data, "transfer_type", ("TRANSFER", "RESALE"))
    decision_reason = opt_str(data, "decision_reason")
    to_account_id = None
    resale_price_cents = None
    if transfer_type == "TRANSFER":
        to_account_id = req_str(data, "to_account_id")
        if data.get("resale_price_cents") is not None:
            bad_request("Field 'resale_price_cents' must be omitted for a TRANSFER.")
    else:
        resale_price_cents = req_int(data, "resale_price_cents", minimum=0)
        if data.get("to_account_id") is not None:
            bad_request("Field 'to_account_id' must be omitted for a RESALE.")

    game = find_game(game_id)
    seat = find_seat(seat_id)
    order = find_order(order_id)
    to_account = find_account(to_account_id) if to_account_id is not None else None

    gate_holder_ownership(caller, order["account_id"])
    gate_order_status(order, ("CONFIRMED",))

    if game["game_status"] != "SCHEDULED":
        err("ERR_GAME_ALREADY_PLAYED", 409, "The game has already been played.")

    gate_not_delinquent(order)

    plan = calc.plan_of(order)
    if seat_id not in order["seat_ids"] or plan is None or game_id not in plan["game_ids"]:
        err("ERR_SEAT_NOT_ENTITLED", 422, "The seat-game pair is outside the order's entitlement.")

    from_account = db.accounts.get(order["account_id"])
    if game["opponent_tier"] == "MARQUEE" and from_account["tenure_years"] < calc.MARQUEE_TRANSFER_MIN_TENURE_YEARS:
        err("ERR_TRANSFER_BLACKOUT", 422, "Marquee games are blacked out for short-tenured sellers.")

    if from_account["transfer_count_season"] >= calc.MAX_TRANSFERS_PER_ACCOUNT_PER_SEASON:
        err("ERR_TRANSFER_LIMIT_EXCEEDED", 422, "The seasonal transfer cap has been reached.")

    season = calc.season_of_order(order)
    mode = season["dynamic_pricing_mode"] if season is not None else "AGGRESSIVE"
    face_value = calc.line_cents(seat, game, mode)
    floor_price = rhu(D(face_value) * D(calc.RESALE_FLOOR_RATE))

    if transfer_type == "RESALE" and resale_price_cents < floor_price:
        err("ERR_RESALE_PRICE_BELOW_FLOOR", 422, "The asking price is below the resale floor.")

    row = {"id": new_id(), "order_id": order_id, "game_id": game_id, "seat_id": seat_id,
           "from_account_id": order["account_id"], "to_account_id": to_account_id,
           "transfer_type": transfer_type, "resale_price_cents": resale_price_cents,
           "face_value_cents": face_value, "floor_price_cents": floor_price,
           "credit_awarded_cents": 0, "transfer_status": "REQUESTED",
           "decided_by_user_id": None, "decision_reason": decision_reason}
    row.update(base_fields())
    db.transfers[row["id"]] = row

    from_account["transfer_count_season"] += 1
    bump(from_account)
    return ok(row, 201)


@bp.route("/ticketing/ticket-transfers/<transfer_id>/decision", methods=["POST"])
@endpoint(ROLE_REVENUE)
def decide_transfer(caller, transfer_id):
    data = body()
    decision = req_enum(data, "decision", ("APPROVE", "REJECT"))
    decision_reason = opt_str(data, "decision_reason")

    transfer = find_transfer(transfer_id)
    if transfer["transfer_status"] != "REQUESTED":
        err("ERR_TRANSFER_NOT_PENDING", 409, "Only a REQUESTED transfer may be decided.")

    game = db.games.get(transfer["game_id"])
    if game is not None and game["game_status"] != "SCHEDULED":
        err("ERR_GAME_ALREADY_PLAYED", 409, "The game has already been played.")

    order = db.orders.get(transfer["order_id"])
    if order is not None:
        gate_not_delinquent(order)

    from_account = db.accounts.get(transfer["from_account_id"])
    season = calc.season_of_order(order) if order is not None else None

    transfer["decided_by_user_id"] = caller.user_id
    if decision_reason is not None:
        transfer["decision_reason"] = decision_reason

    if decision == "APPROVE":
        transfer["transfer_status"] = "APPROVED"
        if transfer["transfer_type"] == "RESALE":
            credit = rhu(D(transfer["resale_price_cents"]) * D(calc.RESALE_CREDIT_RATE))
            transfer["credit_awarded_cents"] = credit
            if from_account is not None:
                from_account["loyalty_credit_cents"] += credit
                bump(from_account)
            if season is not None:
                season["secondary_market_volume_cents"] += transfer["resale_price_cents"]
        bump(transfer)
        if season is not None:
            bump(season)
    else:
        transfer["transfer_status"] = "REJECTED"
        if from_account is not None:
            from_account["transfer_count_season"] -= 1
            bump(from_account)
        bump(transfer)
    return ok(transfer)


@bp.route("/ticketing/ticket-transfers/<transfer_id>", methods=["GET"])
@endpoint(*READ_ROLES)
def get_transfer(caller, transfer_id):
    return ok(find_transfer(transfer_id))


@bp.route("/ticketing/ticket-transfers", methods=["GET"])
@endpoint(*READ_ROLES)
def list_transfers(caller):
    limit, offset = pagination()
    rows = apply_filters(list(db.transfers.values()), [
        ("order_id", "order_id"), ("game_id", "game_id"), ("seat_id", "seat_id"),
        ("from_account_id", "from_account_id"), ("to_account_id", "to_account_id"),
        ("transfer_status", "transfer_status")])
    rows = sort_created(rows)
    page, total = paginate(rows, limit, offset)
    return ok_page(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Gate scans (PRD 3.11)
# ---------------------------------------------------------------------------
@bp.route("/ticketing/games/<game_id>/scans", methods=["POST"])
@endpoint(ROLE_ADMIN)
def ingest_scan(caller, game_id):
    data = body()
    seat_id = req_str(data, "seat_id")

    game = find_game(game_id)
    seat = find_seat(seat_id)

    if game["game_status"] != "SCHEDULED":
        err("ERR_GAME_ALREADY_PLAYED", 409, "The game has already been played.")

    order = calc.confirmed_order_for(seat_id, game_id)
    transfer = calc.approved_transfer_for(seat_id, game_id, ("APPROVED",))
    if order is None and transfer is None:
        err("ERR_SEAT_NOT_ENTITLED", 422, "The seat is not entitled to this game.")

    if game_id in seat["scanned_game_ids"]:
        err("ERR_DUPLICATE_SCAN", 409, "The seat has already been admitted for this game.")

    seat["scanned_game_ids"].append(game_id)
    bump(seat)
    game["scanned_count"] += 1

    account_id = calc.entitled_account_id(seat_id, game_id)
    account = db.accounts.get(account_id) if account_id else None
    if account is not None:
        account["attended_count"] += 1

    if transfer is not None:
        transfer["transfer_status"] = "COMPLETED"
        bump(transfer)

    calc.recompute_attendance(game)
    bump(game)

    if account is not None:
        calc.recompute_rolling(account)
        bump(account)
    return ok(game, 201)
