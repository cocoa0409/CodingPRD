"""Score simulation: the recursive what-if projection and the tier lookup."""

import math

from flask import Blueprint, request

import store
import models
import helpers
from auth import require
from envelope import ok, ok_list, limited
from errors import fail

bp = Blueprint("simulation", __name__)

SIM_ROLES = ["Consumer", "Referee", "PlatformAdmin"]
READ_ROLES = ["Consumer", "Referee", "PlatformAdmin"]

ACTION_CODES = ("PAY_DOWN_REVOLVING", "CLOSE_OLDEST_TRADELINE",
                "INCREASE_CREDIT_LIMIT", "OPEN_NEW_TRADELINE")

UTIL_OPEN_POINTS_PER_ACTION = 5
CLOSE_OLDEST_TRADELINE_PENALTY_POINTS = 12
LIMIT_INCREASE_BASE_BONUS = 8
LIMIT_INCREASE_STEP_BONUS = 2
OPEN_NEW_TRADELINE_PENALTY_POINTS = 9
UTIL_TERMINAL_STEP_POINTS = 3
SCORE_MIN = 300
SCORE_MAX = 850


def lookup_tier_raw(score):
    """score_tier_lookup over every ACTIVE tier, first match wins."""
    active = [t for t in store.score_tiers.values() if t["status"] == "ACTIVE"]
    active.sort(key=lambda t: (t["min_score"], t["max_score"]))
    for tier in active:
        if tier["min_score"] <= score <= tier["max_score"]:
            return tier["tier_code"]
    return None


def _group_of_ten(value):
    return int(math.floor(float(value) / 10.0))


def project(actions, snapshot, cns):
    """simulate_score_delta, applied recursively in submission order."""
    score = cns.get("current_score")
    util = cns.get("utilization_pct")
    if score is None:
        return None, None, None
    util = 0.0 if util is None else float(util)
    limit = snapshot.get("credit_limit_total_cents") or 0
    balance = snapshot.get("total_revolving_balance_cents") or 0
    original_util = util
    for action in actions:
        code = action["action_code"]
        amount = action.get("amount_cents") or 0
        if code == "PAY_DOWN_REVOLVING":
            if limit:
                util = max(0.0, util - (amount * 100.0 / float(limit)))
            score = score + UTIL_OPEN_POINTS_PER_ACTION
        elif code == "CLOSE_OLDEST_TRADELINE":
            score = score - CLOSE_OLDEST_TRADELINE_PENALTY_POINTS
        elif code == "INCREASE_CREDIT_LIMIT":
            denominator = limit + amount
            if denominator:
                util = balance * 100.0 / float(denominator)
            score = score + LIMIT_INCREASE_BASE_BONUS + \
                _group_of_ten(util) * LIMIT_INCREASE_STEP_BONUS
        elif code == "OPEN_NEW_TRADELINE":
            score = score - OPEN_NEW_TRADELINE_PENALTY_POINTS
    score = score + (_group_of_ten(util) - _group_of_ten(original_util)) * \
        UTIL_TERMINAL_STEP_POINTS
    projected = max(SCORE_MIN, min(SCORE_MAX, int(score)))
    delta = projected - cns["current_score"]
    return projected, delta, lookup_tier_raw(projected)


def validate_actions(raw):
    if not isinstance(raw, list):
        fail("ERR_INVALID_REQUEST", "actions must be an array.")
    if len(raw) < 1 or len(raw) > 5:
        fail("ERR_INVALID_REQUEST", "actions must carry between 1 and 5 entries.")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            fail("ERR_INVALID_REQUEST", "Each action must be an object.")
        code = entry.get("action_code")
        if code not in ACTION_CODES:
            fail("ERR_INVALID_REQUEST", "action_code '%s' is not recognised." % code)
        amount = entry.get("amount_cents", 0)
        if amount is None:
            amount = 0
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
            fail("ERR_INVALID_REQUEST", "amount_cents must be a non-negative integer.")
        out.append({"action_code": code, "amount_cents": amount})
    return out


@bp.route("/consumers/<cid>/simulations", methods=["POST"])
def create_simulation(cid):
    uid, role = require(["Consumer"])
    cns = helpers.consumer(cid)
    helpers.owned(cns, uid, role, field="id")
    if cns["status"] != "ACTIVE":
        fail("ERR_INVALID_STATE_TRANSITION", "Only an ACTIVE consumer may simulate.")
    if cns["score_version"] == 0:
        fail("ERR_SIMULATION_NEEDS_SNAPSHOT")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
    helpers.checkout_version(cns, data)
    actions = validate_actions(data.get("actions"))
    snap = helpers.active_snapshot(cid)
    if snap is None:
        fail("ERR_SIMULATION_NEEDS_SNAPSHOT")
    moment = store.now()
    for prior in store.score_simulations.values():
        if prior["consumer_id"] == cid and prior["status"] == "DRAFT":
            prior["status"] = "SUPERSEDED"
            prior["updated_at"] = moment
            prior["version"] = int(prior.get("version", 0)) + 1
    projected, delta, tier_code = project(actions, snap, cns)
    row = store.make_row({
        "consumer_id": cid,
        "baseline_ordinal": cns["score_version"],
        "baseline_score": cns["current_score"],
        "base_utilization_pct": cns["utilization_pct"],
        "actions": actions,
        "projected_score": projected,
        "delta_points": delta,
        "tier_code": tier_code,
        "status": "FINALIZED" if projected is not None else "FAILED",
    }, moment)
    store.score_simulations[row["id"]] = row
    helpers.bump_consumer(cns)
    return ok(models.simulation(row), store.now(), 201)


@bp.route("/consumers/<cid>/simulations", methods=["GET"])
def list_consumer_simulations(cid):
    require(SIM_ROLES)
    helpers.consumer(cid)
    rows = [r for r in store.score_simulations.values() if r["consumer_id"] == cid]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.simulation(r) for r in window], store.now(), pagination)


@bp.route("/score-simulations", methods=["GET"])
def list_simulations():
    require(SIM_ROLES)
    rows = list(store.score_simulations.values())
    cid = request.args.get("consumer_id")
    if cid:
        rows = [r for r in rows if r["consumer_id"] == cid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    window, pagination = limited(rows, request.args)
    return ok_list([models.simulation(r) for r in window], store.now(), pagination)


@bp.route("/score-simulations/<sid>", methods=["GET"])
def get_simulation(sid):
    uid, role = require(SIM_ROLES)
    row = helpers.simulation(sid)
    helpers.owned(row, uid, role, field="consumer_id")
    return ok(models.simulation(row), store.now())


@bp.route("/score-simulations/<sid>/settle", methods=["POST"])
def settle_simulation(sid):
    require(["Referee", "PlatformAdmin"])
    row = helpers.simulation(sid)
    if row["status"] != "FINALIZED":
        fail("ERR_INVALID_STATE_TRANSITION", "Only a FINALIZED simulation may be settled.")
    cns = helpers.consumer(row["consumer_id"])
    snap = helpers.active_snapshot(cns["id"])
    if snap is None:
        fail("ERR_SIMULATION_NEEDS_SNAPSHOT")
    projected, delta, tier_code = project(row["actions"], snap, cns)
    row["projected_score"] = projected
    row["delta_points"] = delta
    row["tier_code"] = tier_code
    models.touch(row)
    return ok(models.simulation(row), store.now())