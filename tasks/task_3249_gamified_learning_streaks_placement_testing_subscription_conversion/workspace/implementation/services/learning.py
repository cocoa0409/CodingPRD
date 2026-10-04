"""Learners, the course tree, practice attempts and spaced review."""

from datetime import timedelta

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import calc, common


# ---------------------------------------------------------------- learner


def create_learner(body):
    display_name = core.as_str(core.get_field(body, "display_name"), "display_name")
    timezone_id = core.as_str(core.get_field(body, "timezone_id"), "timezone_id")
    offset = core.as_int(core.get_field(body, "local_date_offset_days"), "local_date_offset_days")
    program_tier = "FREE"
    if core.has_field(body, "program_tier"):
        program_tier = core.enum_check(
            body["program_tier"], core.VALID_PROGRAM_TIERS, "program_tier"
        )
    now = CLOCK.get()
    focus = core.focus_date_of(CLOCK, offset)
    learner = {
        "id": core.new_id(),
        "display_name": display_name,
        "timezone_id": timezone_id,
        "program_tier": program_tier,
        "streak_anchor_date": core.to_iso(focus),
        "xp_total": 0,
        "gems_balance": 0,
        "leaf_count": 0,
        "hearts_available": core.FREE_HEARTS_PER_DAY,
        "energy_units": core.ENERGY_START_UNITS,
        "energy_anchor_at": core.to_iso(now),
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.learners[learner["id"]] = learner

    streak = {
        "id": core.new_id(),
        "learner_id": learner["id"],
        "current_length": 0,
        "focus_date": core.to_iso(focus),
        "freeze_tokens": 0,
        "status": "EVALUATING",
        "last_qualified_local_date": None,
        "local_date_offset_days": offset,
        "repair_cost_gems": 0,
        "repair_purchases_this_month": 0,
        "_current_length_at_break": 0,
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.streak_states[streak["id"]] = streak

    subscription = {
        "id": core.new_id(),
        "learner_id": learner["id"],
        "plan_code": "FREE",
        "seats_total": 1,
        "status": "FREE",
        "current_period_end": None,
        "auto_renew": False,
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.subscriptions[subscription["id"]] = subscription

    calc.heart_and_energy(learner, CLOCK, persist=True)
    return learner


def patch_learner(learner_id, body, actor):
    common.learner_or_404(learner_id)
    mw.own(actor, learner_id)
    guard = core.as_int(core.get_field(body, "expected_learner_version"), "expected_learner_version")
    learner = STORE.learners[learner_id]
    if guard != int(learner["version"]):
        raise ApiError(core.ERR_STALE_VERSION)

    calendar_changed = False
    if core.has_field(body, "display_name"):
        learner["display_name"] = core.as_str(body["display_name"], "display_name")
    if core.has_field(body, "timezone_id"):
        new_tz = core.as_str(body["timezone_id"], "timezone_id")
        if new_tz != learner["timezone_id"]:
            calendar_changed = True
        learner["timezone_id"] = new_tz
    if core.has_field(body, "local_date_offset_days"):
        new_offset = core.as_int(body["local_date_offset_days"], "local_date_offset_days")
        if new_offset != _streak_offset(learner):
            calendar_changed = True
        streak = common.streak_for_learner(learner_id)
        if streak is not None:
            streak["local_date_offset_days"] = new_offset
            streak["focus_date"] = core.to_iso(core.focus_date_of(CLOCK, new_offset))
            common.touch(streak, CLOCK)
    if core.has_field(body, "program_tier"):
        learner["program_tier"] = core.enum_check(
            body["program_tier"], core.VALID_PROGRAM_TIERS, "program_tier"
        )

    common.touch(learner, CLOCK)
    calc.heart_and_energy(learner, CLOCK, persist=True)
    common.recompute_streak_anchor_date(learner)
    if calendar_changed:
        for offer in STORE.engagement_offers.values():
            if offer["learner_id"] == learner_id and offer["status"] == "ISSUED":
                offer["status"] = "EXPIRED"
                common.touch(offer, CLOCK)
    return learner


def _streak_offset(learner):
    streak = common.streak_for_learner(learner["id"])
    return int(streak["local_date_offset_days"]) if streak else 0


# ---------------------------------------------------------------- course


def create_unit(body):
    unit_index = core.as_int(core.get_field(body, "unit_index"), "unit_index")
    title = core.as_str(core.get_field(body, "title"), "title")
    cefr_band = core.enum_check(core.get_field(body, "cefr_band"), core.CEFR_BANDS, "cefr_band")
    unlock_index = core.as_int(core.get_field(body, "unlock_index"), "unlock_index")
    total_nodes = core.as_int(core.get_field(body, "total_nodes"), "total_nodes")
    now = CLOCK.get()
    unit = {
        "id": core.new_id(),
        "unit_index": unit_index,
        "title": title,
        "cefr_band": cefr_band,
        "unlock_index": unlock_index,
        "crown_count": 0,
        "total_nodes": total_nodes,
        "state": "LOCKED_UNIT",
        "created_at": core.to_iso(now),
    }
    STORE.course_units[unit["id"]] = unit
    common.prune_locked_units(CLOCK)
    return unit


def create_node(unit_id, body):
    common.unit_or_404(unit_id)
    node_index = core.as_int(core.get_field(body, "node_index"), "node_index")
    prereq = None
    if core.has_field(body, "prerequisite_node_id"):
        prereq = core.as_str(body["prerequisite_node_id"], "prerequisite_node_id")
        if prereq not in STORE.lesson_nodes:
            raise ApiError(core.ERR_LESSON_NODE_NOT_FOUND)
    now = CLOCK.get()
    node = {
        "id": core.new_id(),
        "unit_id": unit_id,
        "prerequisite_node_id": prereq,
        "node_index": node_index,
        "state": "LOCKED",
        "decay_level": 0,
        "decay_meter": 0,
        "last_reviewed_at": None,
        "review_due_at": None,
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.lesson_nodes[node["id"]] = node
    unit = STORE.course_units.get(unit_id)
    # PRD 3.1: a unit only closes COMPLETED when "every one of its lesson nodes
    # has reached BRONZE or better", so appending a fresh LOCKED node pulls a
    # COMPLETED unit back to IN_PROGRESS and the unit is once again a posture in
    # which a node may open (AVAILABLE or IN_PROGRESS).
    common.recompute_unit_posture(unit, CLOCK)
    common.prune_locked_units(CLOCK)
    if node["state"] == "LOCKED":
        common.try_unlock_node(node, CLOCK)
    common.recompute_unit_crown_count(unit)
    return node


# ---------------------------------------------------------------- practice


def submit_practice(node_id, body, actor):
    learner_id = core.get_field(body, "learner_id")
    learner_id = core.as_str(learner_id, "learner_id")
    mw.check_learner_param(actor, learner_id)
    mw.own(actor, learner_id)
    learner = common.learner_or_404(learner_id)
    node = common.node_or_404(node_id)

    recorded_at_raw = core.as_str(core.get_field(body, "recorded_at"), "recorded_at")
    recorded_at = core.parse_iso8601(recorded_at_raw)
    response_ms = core.as_int(core.get_field(body, "response_ms"), "response_ms")
    correct = core.as_bool(core.get_field(body, "correct"), "correct")
    is_placement = False
    if core.has_field(body, "is_placement_attempt"):
        is_placement = core.as_bool(body["is_placement_attempt"], "is_placement_attempt")

    # priority 8: node practiceable
    if node["state"] not in core.PRACTICEABLE_STATES:
        raise ApiError(core.ERR_NODE_LOCKED)

    # priority 15: cheat-pattern screen
    _cheat_screen(learner_id, node_id, recorded_at)

    # priority 19: prerequisite
    if not common.prerequisite_satisfied(node):
        raise ApiError(core.ERR_PREREQUISITE_NOT_MET)

    # priorities 21 / 22: hearts then energy (non-placement attempts only)
    if not is_placement:
        hearts, energy, _gate, _limits = calc.heart_and_energy(learner, CLOCK, persist=True)
        if hearts is not None and hearts < 1:
            raise ApiError(core.ERR_HEARTS_EXHAUSTED)
        if energy is not None and energy < 1:
            raise ApiError(core.ERR_ENERGY_EXHAUSTED)

    # priority 28: field range validity
    if response_ms < 0 or response_ms > 600000:
        raise ApiError(core.ERR_INVALID_REQUEST, "response_ms must lie between 0 and 600000.")

    return _apply_attempt(
        learner, node, recorded_at, response_ms, correct, is_placement
    )


def _cheat_screen(learner_id, node_id, recorded_at):
    offset = _streak_offset(STORE.learners[learner_id])
    day_start = core.focus_date_of(CLOCK, offset)
    window_end = day_start + timedelta(seconds=core.DAY_SECONDS)
    if not (day_start <= recorded_at < window_end):
        return
    count = 0
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] != learner_id:
            continue
        if attempt["lesson_node_id"] != node_id:
            continue
        if attempt.get("is_placement_attempt"):
            continue
        if int(attempt["response_ms"]) >= core.FAST_ANSWER_MS:
            continue
        when = core.parse_iso8601(attempt["recorded_at"])
        if day_start <= when < window_end:
            count += 1
    if count >= core.CHEAT_REF_THRESHOLD:
        raise ApiError(core.ERR_CHEAT_PATTERN_DETECTED)


def _apply_attempt(learner, node, recorded_at, response_ms, correct, is_placement):
    now = CLOCK.get()
    streak = common.streak_for_learner(learner["id"])
    length_before = int(streak["current_length"]) if streak else 0
    node_state_before = node["state"]
    awarded = calc.xp_award(
        node_state_before,
        response_ms,
        correct,
        length_before,
        learner["program_tier"],
    )
    attempt = {
        "id": core.new_id(),
        "learner_id": learner["id"],
        "lesson_node_id": node["id"],
        "recorded_at": core.to_iso(recorded_at),
        "response_ms": response_ms,
        "correct": correct,
        "is_placement_attempt": is_placement,
        "outcome": "ACCEPTED",
        "xp_awarded": awarded,
        "_node_state_at_attempt": node_state_before,
        "created_at": core.to_iso(now),
    }
    STORE.practice_attempts[attempt["id"]] = attempt
    learner["xp_total"] = int(learner["xp_total"]) + awarded

    if not is_placement and attempt["outcome"] == "ACCEPTED":
        calc.spend_energy(learner, CLOCK)

    if attempt["outcome"] == "ACCEPTED":
        _qualify_streak(learner, streak, recorded_at)

    if correct:
        _advance_node(node, recorded_at)

    # PRD 3.1: a unit "moves AVAILABLE -> IN_PROGRESS the first time any node
    # inside it is practised successfully", and closes IN_PROGRESS -> COMPLETED
    # once every one of its lesson nodes has reached BRONZE or better.
    common.recompute_unit_posture(STORE.course_units.get(node["unit_id"]), CLOCK)
    common.recompute_unit_crown_count(STORE.course_units.get(node["unit_id"]))
    common.recompute_leaf_count(learner["id"])
    common.prune_locked_units(CLOCK)
    common.refresh_unlocks(CLOCK)
    common.recompute_all_crown_counts()
    calc.heart_and_energy(learner, CLOCK, persist=True)
    common.touch(learner, CLOCK)
    return attempt


def _qualify_streak(learner, streak, recorded_at):
    if streak is None:
        return
    focus = calc.focus_date_of(streak, CLOCK)
    if not (focus <= recorded_at < focus + timedelta(seconds=core.DAY_SECONDS)):
        return
    status = streak["status"]
    if status in ("EVALUATING",):
        streak["current_length"] = int(streak["current_length"]) + 1
        streak["last_qualified_local_date"] = core.to_iso(focus)
        streak["status"] = "QUALIFIED"
    elif status == "BROKEN":
        streak["current_length"] = 1
        streak["last_qualified_local_date"] = core.to_iso(focus)
        streak["repair_cost_gems"] = 0
        streak["status"] = "QUALIFIED"
    elif status == "QUALIFIED":
        common.touch(streak, CLOCK)
        return
    else:
        # FROZEN / REPAIRED / ALIVE resume daily evaluation
        streak["status"] = "QUALIFIED"
        streak["last_qualified_local_date"] = core.to_iso(focus)
    common.touch(streak, CLOCK)
    common.recompute_xp_total(learner["id"])
    length = int(streak["current_length"])
    if length in (7, 30):
        calc.issue_offer(learner, "STREAK_%d" % length, CLOCK)
    common.recompute_streak_anchor_date(learner)


def _advance_node(node, recorded_at):
    state = node["state"]
    if state not in ("UNLOCKED", "BRONZE", "SILVER", "GOLD"):
        return
    if state == "GOLD":
        learner = calc.learner_for_node(node["id"])
        tier = learner["program_tier"] if learner else "FREE"
        if tier not in ("PLUS_FAMILY", "CERTIFICATION_ELITE"):
            return
    idx = core.CROWN_ORDER.index(state)
    node["state"] = core.CROWN_ORDER[idx + 1]
    node["last_reviewed_at"] = core.to_iso(recorded_at)
    node["decay_meter"] = 0
    days = min(
        core.INTERVAL_DAYS_BY_STATE.get(node["state"], core.MAX_REVIEW_DEPTH_DAYS),
        core.MAX_REVIEW_DEPTH_DAYS,
    )
    node["review_due_at"] = core.to_iso(recorded_at + timedelta(days=days))
    common.touch(node, CLOCK)


# ---------------------------------------------------------------- review


def review_node(node_id, body, actor):
    learner_id = core.as_str(core.get_field(body, "learner_id"), "learner_id")
    mw.check_learner_param(actor, learner_id)
    mw.own(actor, learner_id)
    common.learner_or_404(learner_id)
    node = common.node_or_404(node_id)

    guard = core.as_int(core.get_field(body, "expected_node_version"), "expected_node_version")
    if guard != int(node["version"]):
        raise ApiError(core.ERR_STALE_VERSION)

    if node["state"] != "DECAYED":
        raise ApiError(core.ERR_NODE_NOT_DECAYED)
    # PRD 3.2: "Attempting a review against a node already at the floor is refused
    # outright with ERR_DECAY_RETENTION_FLOOR at HTTP 409" — a node whose
    # decay_level has reached the retention floor cannot be revived, so no part of
    # the write is applied.
    if int(node["decay_level"]) >= core.DECAY_LEVEL_FLOOR:
        raise ApiError(core.ERR_DECAY_RETENTION_FLOOR)

    now = CLOCK.get()
    # A restore is an accepted review attempt: it books an attempt carrying the
    # node's decayed crown base and rebases the node's review schedule.
    node["state"] = "UNLOCKED"
    node["decay_meter"] = 0
    node["last_reviewed_at"] = core.to_iso(now)
    common.recompute_node_intervals(node)
    outcome = "ACCEPTED"

    node["version"] = int(node["version"]) + 1
    common.touch(node, CLOCK)
    attempt = {
        "id": core.new_id(),
        "learner_id": learner_id,
        "lesson_node_id": node["id"],
        "recorded_at": core.to_iso(now),
        "response_ms": 0,
        "correct": True,
        "is_placement_attempt": False,
        "outcome": outcome,
        "_node_state_at_attempt": "DECAYED",
        "created_at": core.to_iso(now),
    }
    # PRD 3.2: "the review's attempt is recorded as ACCEPTED" on a restore and
    # "recorded as REJECTED_DECAY_CAP" at the floor; a rejected attempt earns
    # nothing (§3.4).
    attempt["xp_awarded"] = 0
    STORE.practice_attempts[attempt["id"]] = attempt

    if outcome == "ACCEPTED":
        # PRD 3.2: "any dependent node that is LOCKED but whose other
        # prerequisites are satisfied is re-opened in turn" — the restored node
        # itself now counts as satisfied, so a direct dependent that was pushed
        # back to LOCKED by the demotion comes back to UNLOCKED.
        for child in common.children_of_node(node["id"]):
            if child["state"] != "LOCKED":
                continue
            unit = STORE.course_units.get(child["unit_id"])
            if unit is None or common.unit_state(unit) not in ("AVAILABLE", "IN_PROGRESS"):
                continue
            child["state"] = "UNLOCKED"
            common.touch(child, CLOCK)

    unit = STORE.course_units.get(node["unit_id"])
    common.recompute_unit_posture(unit, CLOCK)
    common.recompute_all_crown_counts()
    common.recompute_leaf_count(learner_id)
    common.prune_locked_units(CLOCK)
    common.refresh_unlocks(CLOCK)
    return node