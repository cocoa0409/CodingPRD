"""The ops checkpoint: phases P1 through P10 (PRD 2.11, 3.7, 3.9, 3.11)."""
from flask import Blueprint

import calc
from core import (ROLE_ADMIN, bump, days, db, endpoint, find_season, floor_days_between, iso, now,
                  ok)

bp = Blueprint("ops", __name__)


class Run(object):
    def __init__(self, season):
        self.season = season
        self.instant = now()
        self.touched = set()
        self.counters = {
            "expired_hold_count": 0,
            "played_game_count": 0,
            "released_package_count": 0,
            "settled_package_count": 0,
            "delinquent_order_count": 0,
            "at_risk_account_count": 0,
            "churned_account_count": 0,
            "written_off_account_count": 0,
        }

    def touch(self, account_id):
        if account_id:
            self.touched.add(account_id)


def _season_hold_rows(season_id):
    out = []
    for hold in db.holds.values():
        seat = db.seats.get(hold["seat_id"])
        if seat is not None and seat["season_id"] == season_id:
            out.append(hold)
    return out


def _season_order_rows(season_id):
    out = []
    for order in db.orders.values():
        plan = calc.plan_of(order)
        if plan is not None and plan["season_id"] == season_id:
            out.append(order)
    return out


def _season_game_rows(season_id):
    return [g for g in db.games.values() if g["season_id"] == season_id]


def _drop_renewal_flag(run, account):
    """A departing RENEWAL_HOLD may clear renewal_priority_active."""
    if account is None:
        return False
    before = account["renewal_priority_active"]
    calc.refresh_renewal_priority(account)
    return before and not account["renewal_priority_active"]


# ---------------------------------------------------------------------------
# P2 - expire holds
# ---------------------------------------------------------------------------
def phase_expire_holds(run):
    season = run.season
    rows = [h for h in _season_hold_rows(season["id"])
            if h["hold_status"] == "ACTIVE" and h["hold_window_end_utc"] <= run.instant]
    rows.sort(key=lambda h: (h["hold_window_end_utc"], h["created_at"], h["id"]))
    accounts = []
    for hold in rows:
        hold["hold_status"] = "EXPIRED"
        bump(hold)
        run.counters["expired_hold_count"] += 1
        accounts.append(hold["account_id"])
        run.touch(hold["account_id"])
    for account_id in dict.fromkeys(accounts):
        account = db.accounts.get(account_id)
        if _drop_renewal_flag(run, account):
            bump(account)


# ---------------------------------------------------------------------------
# P4 - settle games
# ---------------------------------------------------------------------------
def phase_settle_games(run):
    season = run.season
    rows = [g for g in _season_game_rows(season["id"])
            if g["game_status"] == "SCHEDULED" and g["game_date_utc"] <= run.instant]
    rows.sort(key=lambda g: (g["game_date_utc"], g["created_at"], g["id"]))
    for game in rows:
        game["game_status"] = "PLAYED"
        seat_ids = calc.entitled_seat_ids(game["id"])
        seats = [db.seats[s] for s in seat_ids if s in db.seats]
        seats.sort(key=lambda s: (s["section_code"], s["row_label"], s["seat_number"]))
        for seat in seats:
            if game["id"] in seat["scanned_game_ids"]:
                continue
            account_id = calc.entitled_account_id(seat["id"], game["id"])
            account = db.accounts.get(account_id) if account_id else None
            if account is None:
                continue
            account["no_show_count"] += 1
            account["season_no_show_count"] += 1
            bump(account)
            run.touch(account["id"])
        calc.recompute_attendance(game)
        for transfer in db.transfers.values():
            if transfer["game_id"] == game["id"] and transfer["transfer_status"] == "APPROVED":
                transfer["transfer_status"] = "COMPLETED"
                bump(transfer)
        bump(game)
        run.counters["played_game_count"] += 1


# ---------------------------------------------------------------------------
# P5 - hospitality
# ---------------------------------------------------------------------------
def phase_hospitality(run):
    season = run.season
    packages = []
    for pkg in db.packages.values():
        game = db.games.get(pkg["game_id"])
        if game is not None and game["season_id"] == season["id"]:
            packages.append(pkg)
    packages.sort(key=lambda p: (p["created_at"], p["id"]))

    lead = days(calc.HOSPITALITY_RELEASE_LEAD_DAYS)
    for pkg in packages:
        game = db.games.get(pkg["game_id"])
        if pkg["package_status"] != "HELD" or game is None:
            continue
        if run.instant >= game["game_date_utc"] - lead:
            pkg["package_status"] = "RELEASED"
            bump(pkg)
            calc.recompute_booked_headcount(game)
            calc.recompute_attendance(game)
            bump(game)
            run.counters["released_package_count"] += 1
            run.touch(pkg["account_id"])
            calc.recompute_lifetime_value(db.accounts.get(pkg["account_id"]))

    for pkg in packages:
        game = db.games.get(pkg["game_id"])
        if pkg["package_status"] != "CONFIRMED" or game is None:
            continue
        if game["game_status"] == "PLAYED":
            pkg["package_status"] = "SETTLED"
            bump(pkg)
            run.counters["settled_package_count"] += 1
            run.touch(pkg["account_id"])


# ---------------------------------------------------------------------------
# P6 - payment delinquency
# ---------------------------------------------------------------------------
def phase_delinquency(run):
    orders = [o for o in _season_order_rows(run.season["id"])
              if o["order_status"] == "CONFIRMED" and o["payment_status"] in ("SCHEDULED", "PARTIALLY_PAID")]
    orders.sort(key=lambda o: (o["created_at"], o["id"]))
    grace = days(calc.PAYMENT_GRACE_DAYS)
    for order in orders:
        earliest = calc.earliest_unpaid(order)
        if earliest is None:
            continue
        if run.instant < earliest["due_date_utc"] + grace:
            continue
        order["payment_status"] = "DELINQUENT"
        bump(order)
        run.counters["delinquent_order_count"] += 1
        account = db.accounts.get(order["account_id"])
        run.touch(order["account_id"])
        if account is not None and account["billing_status"] == "CURRENT":
            account["billing_status"] = "PAST_DUE"
            account["past_due_since_utc"] = run.instant
            calc.recompute_rolling(account)
            bump(account)


# ---------------------------------------------------------------------------
# P7 - account billing ageing and the write-off cascade
# ---------------------------------------------------------------------------
def write_off_cascade(run, account):
    seasons = set()
    for hold in list(db.holds.values()):
        if hold["account_id"] == account["id"] and hold["hold_status"] == "ACTIVE":
            hold["hold_status"] = "RELEASED"
            hold["released_reason"] = "ACCOUNT_WRITTEN_OFF"
            bump(hold)
            seat = db.seats.get(hold["seat_id"])
            if seat is not None:
                seasons.add(seat["season_id"])
    for order in list(db.orders.values()):
        if order["account_id"] == account["id"] and order["order_status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED"):
            order["order_status"] = "CANCELLED"
            order["cancelled_reason"] = "ACCOUNT_WRITTEN_OFF"
            bump(order)
    for pkg in list(db.packages.values()):
        if pkg["account_id"] == account["id"] and pkg["package_status"] == "HELD":
            pkg["package_status"] = "RELEASED"
            bump(pkg)
            game = db.games.get(pkg["game_id"])
            if game is not None:
                calc.recompute_booked_headcount(game)
                calc.recompute_attendance(game)
                bump(game)
    calc.refresh_renewal_priority(account)
    seasons.add(run.season["id"])
    for season_id in seasons:
        calc.run_census(db.seasons.get(season_id))


def phase_billing_ageing(run):
    accounts = sorted(db.accounts.values(), key=lambda a: (a["created_at"], a["id"]))
    for account in accounts:
        anchor = account.get("past_due_since_utc")
        if anchor is None:
            continue
        if account["billing_status"] == "PAST_DUE" and run.instant >= anchor + days(calc.LAPSE_AFTER_DAYS):
            account["billing_status"] = "LAPSED"
            calc.recompute_rolling(account)
            bump(account)
            run.touch(account["id"])
        if account["billing_status"] == "LAPSED" and run.instant >= anchor + days(calc.WRITE_OFF_AFTER_DAYS):
            account["billing_status"] = "WRITTEN_OFF"
            write_off_cascade(run, account)
            calc.recompute_rolling(account)
            bump(account)
            run.counters["written_off_account_count"] += 1
            run.touch(account["id"])


# ---------------------------------------------------------------------------
# P8 - season status advance
# ---------------------------------------------------------------------------
def _renewal_close_cascade(run):
    season = run.season
    rows = [h for h in _season_hold_rows(season["id"])
            if h["hold_status"] == "ACTIVE" and h["hold_type"] == "RENEWAL_HOLD"]
    rows.sort(key=lambda h: (h["hold_window_end_utc"], h["created_at"], h["id"]))
    account_ids = []
    for hold in rows:
        hold["hold_status"] = "EXPIRED"
        hold["released_reason"] = "RENEWAL_WINDOW_CLOSED"
        bump(hold)
        run.counters["expired_hold_count"] += 1
        account_ids.append(hold["account_id"])
        run.touch(hold["account_id"])

    calc.run_census(season)

    for account_id in dict.fromkeys(account_ids):
        account = db.accounts.get(account_id)
        if account is None:
            continue
        if not _drop_renewal_flag(run, account):
            continue
        moved = False
        if (account["service_status"] in ("PROSPECT", "ACTIVE")
                and not calc.has_confirmed_order_in_season(account["id"], season["id"])):
            account["service_status"] = "AT_RISK"
            account["at_risk_since_utc"] = run.instant
            calc.recompute_campaign(account, season)
            run.counters["at_risk_account_count"] += 1
            moved = True
        bump(account)
        if moved:
            run.touch(account["id"])


def _archive_cascade(run):
    season = run.season
    for plan in db.plans.values():
        if plan["season_id"] == season["id"] and plan["plan_status"] == "PUBLISHED":
            plan["plan_status"] = "CLOSED"
            bump(plan)
    rows = [h for h in _season_hold_rows(season["id"]) if h["hold_status"] == "ACTIVE"]
    rows.sort(key=lambda h: (h["hold_window_end_utc"], h["created_at"], h["id"]))
    account_ids = []
    for hold in rows:
        hold["hold_status"] = "EXPIRED"
        hold["released_reason"] = "SEASON_ARCHIVED"
        bump(hold)
        run.counters["expired_hold_count"] += 1
        account_ids.append(hold["account_id"])
        run.touch(hold["account_id"])
    for order in _season_order_rows(season["id"]):
        if order["order_status"] in ("DRAFT", "PENDING_APPROVAL", "APPROVED"):
            order["order_status"] = "CANCELLED"
            order["cancelled_reason"] = "SEASON_ARCHIVED"
            bump(order)
            run.touch(order["account_id"])
    calc.run_census(season)
    for account_id in dict.fromkeys(account_ids):
        account = db.accounts.get(account_id)
        if _drop_renewal_flag(run, account):
            bump(account)


def phase_season_advance(run):
    season = run.season
    games = _season_game_rows(season["id"])
    for _ in range(3):
        status = season["season_status"]
        if status == "RENEWAL_OPEN" and run.instant >= season["renewal_deadline_utc"]:
            _renewal_close_cascade(run)
            season["season_status"] = "GENERAL_ONSALE"
            bump(season)
            continue
        if status == "GENERAL_ONSALE" and games:
            earliest = min(g["game_date_utc"] for g in games)
            if run.instant >= earliest:
                season["season_status"] = "IN_SEASON"
                bump(season)
                continue
        if status == "IN_SEASON" and games:
            latest = max(g["game_date_utc"] for g in games)
            if run.instant >= latest + days(calc.SEASON_ARCHIVE_GRACE_DAYS):
                _archive_cascade(run)
                season["season_status"] = "ARCHIVED"
                bump(season)
                continue
        break


# ---------------------------------------------------------------------------
# P9 - campaign scoring
# ---------------------------------------------------------------------------
def phase_campaign_scoring(run):
    season = run.season
    accounts = sorted(db.accounts.values(), key=lambda a: (a["created_at"], a["id"]))
    for account in accounts:
        calc.recompute_campaign(account, season)

    if season["season_status"] == "RENEWAL_OPEN":
        for account in accounts:
            if account["service_status"] not in ("PROSPECT", "ACTIVE"):
                continue
            anchor = account.get("last_touchpoint_at_utc") or account["created_at"]
            if floor_days_between(run.instant, anchor) < calc.TOUCHPOINT_CADENCE_DAYS:
                continue
            if calc.has_confirmed_order_in_season(account["id"], season["id"]):
                continue
            account["service_status"] = "AT_RISK"
            account["at_risk_since_utc"] = run.instant
            calc.recompute_campaign(account, season)
            bump(account)
            run.counters["at_risk_account_count"] += 1
            run.touch(account["id"])

    if season["season_status"] in ("GENERAL_ONSALE", "IN_SEASON", "ARCHIVED"):
        for account in accounts:
            if account["service_status"] != "AT_RISK":
                continue
            anchor = account.get("at_risk_since_utc")
            if anchor is None or run.instant < anchor + days(calc.CHURN_DECLARATION_DAYS):
                continue
            if calc.has_confirmed_order_in_season(account["id"], season["id"]):
                continue
            account["service_status"] = "CHURNED"
            calc.recompute_campaign(account, season)
            bump(account)
            run.counters["churned_account_count"] += 1
            run.touch(account["id"])


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------
@bp.route("/ticketing/seasons/<season_id>/run-ops", methods=["POST"])
@endpoint(ROLE_ADMIN)
def run_ops(caller, season_id):
    season = find_season(season_id)
    run = Run(season)

    phase_expire_holds(run)                 # P2
    calc.run_census(season)                 # P3
    phase_settle_games(run)                 # P4
    phase_hospitality(run)                  # P5
    phase_delinquency(run)                  # P6
    phase_billing_ageing(run)               # P7
    phase_season_advance(run)               # P8
    phase_campaign_scoring(run)             # P9

    for account_id in run.touched:          # P10
        calc.recompute_rolling(db.accounts.get(account_id))

    season["last_ops_run_at_utc"] = run.instant
    bump(season)

    summary = {"ops_run_at_utc": iso(run.instant), "season_status": season["season_status"]}
    summary.update(run.counters)
    return ok(summary)
