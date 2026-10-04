"""Leagues: rounds, standings, weekly ranking and the anti-cheat settlement."""

from datetime import timedelta

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import calc, common


def _join_eligible(learner):
    from services import billing
    subscription = common.subscription_for_learner(learner["id"])
    if subscription is not None and billing.limits_removed(subscription):
        return True
    return any(
        m["member_learner_id"] == learner["id"] and m["status"] == "ACTIVE"
        for m in STORE.family_memberships.values()
    )


def create_league(body, actor):
    tier = core.enum_check(core.get_field(body, "tier"), core.VALID_LEAGUE_TIERS, "tier")
    week_start = core.parse_iso8601(
        core.as_str(core.get_field(body, "week_start"), "week_start")
    )
    learner_id = None
    if core.has_field(body, "learner_id"):
        learner_id = core.as_str(body["learner_id"], "learner_id")
        mw.check_learner_param(actor, learner_id)

    now = CLOCK.get()
    league = {
        "id": core.new_id(),
        "tier": tier,
        "week_start": core.to_iso(week_start),
        "status": "FORMING",
        "member_count": 0,
        "promotion_cutoff_rank": min(core.PROMOTION_CUTOFF_RANK, core.LEAGUE_SIZE),
        "demotion_cutoff_rank": max(1, core.LEAGUE_SIZE - core.DEMOTION_SPAN + 1),
        "settled_at": None,
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.leagues[league["id"]] = league

    if learner_id is not None:
        learner = common.learner_or_404(learner_id)
        if not _join_eligible(learner):
            raise ApiError(core.ERR_UNAUTHORIZED)
        _mint_standing(league, learner)
    return league


def _mint_standing(league, learner):
    now = CLOCK.get()
    standing = {
        "id": core.new_id(),
        "league_id": league["id"],
        "learner_id": learner["id"],
        "weekly_xp": 0,
        "standing": "GOOD_STANDING",
        "rank": None,
        "flag_reason": None,
        "settled_outcome": "NONE",
        "_attempt_count": 0,
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.league_standings[standing["id"]] = standing
    if league["status"] == "FORMING":
        league["status"] = "ACTIVE"
    league["member_count"] = len(
        [
            s
            for s in STORE.league_standings.values()
            if s["league_id"] == league["id"] and s["standing"] in ("GOOD_STANDING", "FLAGGED")
        ]
    )
    common.touch(league, CLOCK)
    return standing


def update_league(league_id, body, actor):
    league = STORE.leagues.get(league_id)
    if league is None:
        raise ApiError(core.ERR_INVALID_REQUEST, "The named league does not exist.")
    action = core.as_str(core.get_field(body, "action"), "action")

    learner_id = None
    if core.has_field(body, "learner_id"):
        learner_id = core.as_str(body["learner_id"], "learner_id")
        mw.check_learner_param(actor, learner_id)

    if action == "JOIN":
        if learner_id is None:
            raise ApiError(core.ERR_INVALID_REQUEST, "learner_id is required to join.")
        learner = common.learner_or_404(learner_id)
        if not _join_eligible(learner):
            raise ApiError(core.ERR_UNAUTHORIZED)
        _mint_standing(league, learner)
        return league

    if action == "SETTLE":
        _settle(league)
        return league

    if action == "REOPEN":
        _reopen(league)
        return league

    raise ApiError(core.ERR_INVALID_REQUEST, "Unsupported league action.")


def _settle(league):
    """Anti-cheat pass, then ranking, then promotion and demotion."""
    if league["status"] not in ("ACTIVE", "SETTLING"):
        raise ApiError(core.ERR_LEAGUE_NOT_SETTLING)

    if league["status"] == "ACTIVE":
        league["status"] = "SETTLING"
        calc.compute_league_flags(league, CLOCK, per_attempt_rounding=True)

    league["status"] = "SETTLING"
    candidates = calc.compute_league_ranking(league, CLOCK, per_attempt_rounding=True)
    league["settled_at"] = core.to_iso(CLOCK.get())
    promotion = league["promotion_cutoff_rank"]
    demotion = league["demotion_cutoff_rank"]
    for standing in candidates:
        rank = standing.get("rank") or 0
        promoted = rank <= promotion
        demoted = rank >= demotion
        if demoted:
            standing["standing"] = "DEMOTED"
            standing["settled_outcome"] = "DEMOTED"
            common.touch(standing, CLOCK)
            _apply_demotion_sting(standing)
        elif promoted:
            standing["standing"] = "PROMOTED"
            standing["settled_outcome"] = "PROMOTED"
            common.touch(standing, CLOCK)
            learner = STORE.learners.get(standing["learner_id"])
            if learner is not None:
                common.recompute_xp_total(learner["id"])
                calc.issue_offer(learner, "LEAGUE_PROMOTION", CLOCK)
        else:
            standing["settled_outcome"] = "HELD"
            common.touch(standing, CLOCK)
    league["status"] = "CLOSED"
    # PRD 3.7: a settled round's member count still reflects its participants —
    # a DEMOTED standing remains a member of the round it competed in.
    league["member_count"] = len(
        [
            s
            for s in STORE.league_standings.values()
            if s["league_id"] == league["id"]
            and s["standing"] in ("GOOD_STANDING", "FLAGGED", "PROMOTED", "DEMOTED")
        ]
    )
    common.touch(league, CLOCK)


def _apply_demotion_sting(standing):
    for node in STORE.lesson_nodes.values():
        if node["state"] not in core.CROWN_STATES:
            continue
        unit = STORE.course_units.get(node["unit_id"])
        if unit is None or unit["state"] != "COMPLETED":
            continue
        learner = calc.learner_for_node(node["id"])
        if learner is None or learner["id"] != standing["learner_id"]:
            continue
        node["decay_meter"] = min(core.DECAY_POINTS_PER_TIER, int(node["decay_meter"]) + 1)
    common.recompute_leaf_count(standing["learner_id"])


def _reopen(league):
    if league["status"] not in ("CLOSED",):
        raise ApiError(core.ERR_LEAGUE_NOT_SETTLING)
    league["week_start"] = core.to_iso(CLOCK.get())
    for standing in STORE.league_standings.values():
        if standing["league_id"] != league["id"]:
            continue
        if standing["standing"] == "DEMOTED":
            standing["standing"] = "GOOD_STANDING"
            standing["settled_outcome"] = "NONE"
            common.touch(standing, CLOCK)
        elif standing["standing"] == "FLAGGED":
            standing["standing"] = "GOOD_STANDING"
            standing["flag_reason"] = None
            common.touch(standing, CLOCK)
    league["status"] = "ACTIVE"
    league["member_count"] = len(
        [
            s
            for s in STORE.league_standings.values()
            if s["league_id"] == league["id"] and s["standing"] in ("GOOD_STANDING", "FLAGGED")
        ]
    )
    calc.compute_league_ranking(league, CLOCK, per_attempt_rounding=False)
    common.touch(league, CLOCK)


def league_week_close(clock):
    for league in list(STORE.leagues.values()):
        start = core.parse_iso8601(league["week_start"])
        if clock.get() < start + timedelta(days=core.LEAGUE_WEEK_DAYS):
            continue
        if league["status"] == "ACTIVE":
            _settle(league)
        elif league["status"] == "SETTLING":
            candidates = calc.compute_league_ranking(league, clock, per_attempt_rounding=True)
            _finish_settlement(league, candidates)


def _finish_settlement(league, candidates):
    league["settled_at"] = core.to_iso(CLOCK.get())
    for standing in candidates:
        rank = standing.get("rank") or 0
        if rank >= league["demotion_cutoff_rank"]:
            standing["standing"] = "DEMOTED"
            standing["settled_outcome"] = "DEMOTED"
            _apply_demotion_sting(standing)
        elif rank <= league["promotion_cutoff_rank"]:
            standing["standing"] = "PROMOTED"
            standing["settled_outcome"] = "PROMOTED"
            learner = STORE.learners.get(standing["learner_id"])
            if learner is not None:
                common.recompute_xp_total(learner["id"])
                calc.issue_offer(learner, "LEAGUE_PROMOTION", CLOCK)
        else:
            standing["settled_outcome"] = "HELD"
        common.touch(standing, CLOCK)
    league["status"] = "CLOSED"
    common.touch(league, CLOCK)


def league_week_open(clock):
    for league in list(STORE.leagues.values()):
        if league["status"] == "CLOSED":
            _reopen(league)