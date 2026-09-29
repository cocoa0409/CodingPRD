"""Weekly dues, the prize fund waterfall and award reversal (PRD 3.7)."""

from flask import Blueprint

import calc
import derive
import serialize
import shape
from auth import (authenticate, fetch, require_own_membership,
                  require_secretary, require_treasurer)
from clock import clock
from envelope import ok
from errors import ApiError
from store import store, insert, touch, apply_changes

money = Blueprint("money", __name__)


@money.post("/memberships/<membership_id>/dues-payments")
def record_dues(membership_id):
    uid, role = authenticate(["LeagueTreasurer", "Bowler"])
    membership = fetch("membership", membership_id)
    league = store.leagues[membership["league_id"]]
    require_treasurer(league, uid, role)
    if role == "Bowler":
        require_own_membership(uid, membership)
    payload = shape.body()
    week_number = shape.req_int(payload, "week_number", 1)
    if week_number > league["total_weeks"]:
        shape.bad("week_number must not exceed the league's total_weeks.")
    amount_cents = shape.req_int(payload, "amount_cents", 0, 10000)
    if membership["sanction_status"] != "SANCTIONED":
        raise ApiError("ERR_MEMBERSHIP_STATE_INVALID")
    for payment in derive.dues_of_membership(membership["id"]):
        if payment["week_number"] == week_number:
            raise ApiError("ERR_DUES_WEEK_ALREADY_PAID")
    if amount_cents != league["weekly_dues_cents"]:
        raise ApiError("ERR_DUES_AMOUNT_MISMATCH")
    row = insert(store.dues_payments, {
        "membership_id": membership["id"],
        "week_number": week_number,
        "amount_cents": amount_cents,
        "prize_share_cents": (league["weekly_dues_cents"]
                              - league["weekly_expense_cents"]),
        "expense_share_cents": league["weekly_expense_cents"],
    }, versioned=False)
    derive.recompute_dues_figures(membership)
    derive.recompute_prize_fund(league)
    return ok(serialize.dues_payment(row), 201)


def standings(league):
    candidates = [t for t in derive.teams_of_league(league["id"])
                  if t["status"] == "CONFIRMED"]
    return sorted(candidates,
                  key=lambda t: (-t["total_points"], -t["total_scratch_pins"],
                                 t["created_at"], t["_seq"]))


@money.post("/prize-funds/<fund_id>/distribution-plans")
def draft_plan(fund_id):
    uid, role = authenticate(["LeagueTreasurer"])
    fund = fetch("prize_fund", fund_id)
    league = store.leagues[fund["league_id"]]
    require_treasurer(league, uid, role)
    payload = shape.body()
    expected = shape.req_int(payload, "expected_prize_fund_version", 0)
    basis_variant = shape.req_enum(payload, "basis_variant",
                                   ["PROJECTED_SEASON_END", "CERTIFIED_TO_DATE"])
    place_count = shape.req_int(payload, "place_count", 1, 12)
    weights = league["prize_place_weights"] or []
    if place_count != len(weights):
        shape.bad("place_count must equal the length of prize_place_weights.")
    if expected != fund["version"]:
        raise ApiError("ERR_STALE_PRIZE_FUND_VERSION")
    if league["status"] not in ("IN_SEASON", "SEASON_CLOSED"):
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if fund["status"] not in ("ACCUMULATING", "PLAN_DRAFTED"):
        raise ApiError("ERR_PRIZE_FUND_STATE_INVALID")
    if len(standings(league)) < place_count:
        raise ApiError("ERR_NO_ELIGIBLE_TEAMS")
    settled = derive.settled_prize_amount(league)
    if basis_variant == "CERTIFIED_TO_DATE":
        basis = settled
    else:
        remaining = league["total_weeks"] - league["certified_week_high_water"]
        if remaining < 0:
            remaining = 0
        weekly_share = (league["weekly_dues_cents"]
                        - league["weekly_expense_cents"])
        basis = settled + remaining * league["sanctioned_member_count"] * weekly_share
    reserve, admin, net = calc.waterfall(basis)
    fund["basis_variant"] = basis_variant
    fund["place_count"] = place_count
    fund["plan_basis_cents"] = basis
    fund["reserve_cents"] = reserve
    fund["admin_fee_cents"] = admin
    fund["net_distributable_cents"] = net
    fund["plan_drafted_at"] = clock.now()
    fund["status"] = "PLAN_DRAFTED"
    touch(fund)
    return ok(serialize.prize_fund(fund))


@money.post("/prize-funds/<fund_id>/approve-plan")
def approve_plan(fund_id):
    uid, role = authenticate(["LeagueSecretary"])
    fund = fetch("prize_fund", fund_id)
    league = store.leagues[fund["league_id"]]
    require_secretary(league, uid, role)
    if league["status"] != "SEASON_CLOSED":
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if fund["status"] != "PLAN_DRAFTED":
        raise ApiError("ERR_PRIZE_FUND_STATE_INVALID")
    ranked = standings(league)
    place_count = fund["place_count"]
    if len(ranked) < place_count:
        raise ApiError("ERR_NO_ELIGIBLE_TEAMS")
    weights = league["prize_place_weights"] or []
    amounts = calc.place_amounts(fund["net_distributable_cents"], weights,
                                 place_count)
    for place in range(1, place_count + 1):
        insert(store.prize_awards, {
            "prize_fund_id": fund["id"],
            "team_id": ranked[place - 1]["id"],
            "place": place,
            "weight": weights[place - 1],
            "amount_cents": amounts[place - 1],
            "status": "PENDING",
            "reversal_reason": None,
        })
    fund["status"] = "PLAN_APPROVED"
    fund["plan_approved_by_user_id"] = uid
    touch(fund)
    return ok(serialize.prize_fund(fund))


@money.post("/prize-funds/<fund_id>/disburse")
def disburse(fund_id):
    uid, role = authenticate(["LeagueTreasurer"])
    fund = fetch("prize_fund", fund_id)
    league = store.leagues[fund["league_id"]]
    require_treasurer(league, uid, role)
    if league["status"] != "SEASON_CLOSED":
        raise ApiError("ERR_LEAGUE_STATE_INVALID")
    if fund["status"] != "PLAN_APPROVED":
        raise ApiError("ERR_PRIZE_FUND_STATE_INVALID")
    if fund["plan_approved_by_user_id"] == uid:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    awards = derive.awards_of_fund(fund["id"])
    pending = [a for a in awards if a["status"] == "PENDING"]
    total = sum(a["amount_cents"] for a in pending)
    if total > fund["undistributed_balance_cents"]:
        raise ApiError("ERR_INSUFFICIENT_PRIZE_FUND")
    for award in pending:
        apply_changes(award, {"status": "PAID"})
    fund["disbursed_at"] = clock.now()
    fund["status"] = "DISBURSED"
    touch(fund)
    derive.recompute_prize_fund(league)
    league["status"] = "PRIZES_DISBURSED"
    touch(league)
    return ok(serialize.prize_fund(fund))


@money.post("/prize-awards/<award_id>/reverse")
def reverse_award(award_id):
    uid, role = authenticate(["LeagueTreasurer"])
    award = fetch("prize_award", award_id)
    fund = store.prize_funds[award["prize_fund_id"]]
    league = store.leagues[fund["league_id"]]
    require_treasurer(league, uid, role)
    payload = shape.body()
    reason = shape.req_str(payload, "reversal_reason")
    if fund["status"] != "DISBURSED" or award["status"] != "PAID":
        raise ApiError("ERR_PRIZE_FUND_STATE_INVALID")
    award["status"] = "REVERSED"
    award["reversal_reason"] = reason
    touch(award)
    fund["status"] = "PLAN_APPROVED"
    fund["disbursed_at"] = None
    touch(fund)
    derive.recompute_prize_fund(league)
    if league["status"] == "PRIZES_DISBURSED":
        league["status"] = "SEASON_CLOSED"
        touch(league)
    return ok(serialize.prize_award(award))
