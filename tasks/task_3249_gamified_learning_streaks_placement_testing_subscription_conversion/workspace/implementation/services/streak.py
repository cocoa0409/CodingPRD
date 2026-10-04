"""Streaks, freezes, repair economics and the day-close sweep."""

from datetime import timedelta

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import calc, common


def _active_family_seat(learner_id):
    return any(
        m["member_learner_id"] == learner_id and m["status"] == "ACTIVE"
        for m in STORE.family_memberships.values()
    )


def set_freezes(streak_id, body, actor):
    streak = STORE.streak_states.get(streak_id)
    if streak is None:
        raise ApiError(core.ERR_LEARNER_NOT_FOUND)
    mw.own(actor, streak["learner_id"])
    count = 1
    if core.has_field(body, "count"):
        count = core.as_int(body["count"], "count")
    elif core.has_field(body, "freeze_tokens"):
        count = core.as_int(body["freeze_tokens"], "freeze_tokens")
    if count < 0:
        raise ApiError(core.ERR_INVALID_REQUEST, "count must not be negative.")
    streak["freeze_tokens"] = int(streak["freeze_tokens"]) + count
    common.touch(streak, CLOCK)
    return streak


def repair_streak(streak_id, body, actor):
    streak = STORE.streak_states.get(streak_id)
    if streak is None:
        raise ApiError(core.ERR_LEARNER_NOT_FOUND)
    mw.check_learner_param(actor, streak["learner_id"])
    mw.own(actor, streak["learner_id"])
    learner = common.learner_or_404(streak["learner_id"])

    guard = core.as_int(core.get_field(body, "expected_streak_version"), "expected_streak_version")
    if guard != int(streak["version"]):
        raise ApiError(core.ERR_STALE_VERSION)

    if streak["status"] != "BROKEN":
        raise ApiError(core.ERR_STREAK_NOT_BROKEN)

    # PRD 2.10 places the business-safety and temporal checks — of which the
    # repair window is one — ahead of the referential and business-constraint
    # block that holds the monthly cap, so the window is evaluated first.
    focus = core.parse_iso8601(streak["focus_date"])
    if CLOCK.get() > focus + timedelta(days=core.REPAIR_WINDOW_DAYS):
        raise ApiError(core.ERR_REPAIR_WINDOW_EXPIRED)

    if int(streak["repair_purchases_this_month"]) >= core.MONTHLY_REPAIR_CAP:
        raise ApiError(core.ERR_REPAIR_MONTHLY_CAP)

    per_term = _active_family_seat(learner["id"])
    display, debit = calc.repair_cost(
        int(streak.get("_current_length_at_break") or 0),
        int(streak["repair_purchases_this_month"]),
        per_term=per_term,
    )
    if int(learner["gems_balance"]) < debit:
        raise ApiError(core.ERR_INSUFFICIENT_GEMS)

    learner["gems_balance"] = int(learner["gems_balance"]) - debit
    common.touch(learner, CLOCK)
    streak["current_length"] = int(streak.get("_current_length_at_break") or 0)
    streak["repair_purchases_this_month"] = int(streak["repair_purchases_this_month"]) + 1
    streak["repair_cost_gems"] = debit
    streak["status"] = "REPAIRED"
    common.touch(streak, CLOCK)
    calc.recompute_repair_cost(streak, learner, per_term=per_term)
    return streak


def _accepted_on_focus(learner_id, focus):
    window_end = focus + timedelta(seconds=core.DAY_SECONDS)
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] != learner_id:
            continue
        if attempt["outcome"] != "ACCEPTED":
            continue
        recorded = core.parse_iso8601(attempt["recorded_at"])
        if focus <= recorded < window_end:
            return True
    return False


def streak_day_close(clock):
    """STREAK_DAY_CLOSE: advance each learner whose local date has moved past
    their focus_date by exactly one day, applying the freeze or break outcome."""
    current_index = None
    for streak in list(STORE.streak_states.values()):
        offset = int(streak["local_date_offset_days"])
        current_index = core.local_day_index(clock, offset)
        focus = core.parse_iso8601(streak["focus_date"])
        focus_index = int(focus.timestamp()) // core.DAY_SECONDS
        if focus_index >= current_index:
            continue
        status = streak["status"]
        learner = STORE.learners.get(streak["learner_id"])
        if status in ("QUALIFIED", "FROZEN", "REPAIRED", "ALIVE"):
            streak["status"] = "EVALUATING"
            _advance_focus(streak, clock, offset)
            common.touch(streak, clock)
            continue
        if status == "BROKEN":
            continue
        # EVALUATING
        if _accepted_on_focus(streak["learner_id"], focus):
            streak["status"] = "EVALUATING"
        elif int(streak["freeze_tokens"]) >= 1:
            streak["freeze_tokens"] = int(streak["freeze_tokens"]) - 1
            streak["status"] = "FROZEN"
        else:
            streak["_current_length_at_break"] = int(streak["current_length"])
            streak["current_length"] = 0
            streak["status"] = "BROKEN"
            if learner is not None:
                calc.recompute_repair_cost(streak, learner)
                hearts, _energy, _gate, _limits = calc.heart_and_energy(learner, clock, persist=False)
                if hearts == 0:
                    calc.issue_offer(learner, "HEART_DEPLETION", clock)
        _advance_focus(streak, clock, offset)
        common.touch(streak, clock)


def _advance_focus(streak, clock, offset):
    focus = core.parse_iso8601(streak["focus_date"])
    streak["focus_date"] = core.to_iso(focus + timedelta(days=1))
    learner = STORE.learners.get(streak["learner_id"])
    if learner is not None:
        common.recompute_streak_anchor_date(learner)