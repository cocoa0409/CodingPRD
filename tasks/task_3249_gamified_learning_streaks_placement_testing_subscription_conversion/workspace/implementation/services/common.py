"""Shared lookup, recomputation and access helpers."""

from datetime import timedelta

import core
from core import ApiError
from db import STORE


# ---------------------------------------------------------------- lookups


def learner_or_404(learner_id):
    row = STORE.learners.get(learner_id)
    if row is None:
        raise ApiError(core.ERR_LEARNER_NOT_FOUND)
    return row


def node_or_404(node_id):
    row = STORE.lesson_nodes.get(node_id)
    if row is None:
        raise ApiError(core.ERR_LESSON_NODE_NOT_FOUND)
    return row


def unit_or_404(unit_id):
    row = STORE.course_units.get(unit_id)
    if row is None:
        raise ApiError(core.ERR_UNIT_NOT_FOUND)
    return row


def subscription_or_404(subscription_id):
    row = STORE.subscriptions.get(subscription_id)
    if row is None:
        raise ApiError(core.ERR_SUBSCRIPTION_NOT_FOUND)
    return row


def streak_for_learner(learner_id):
    for row in STORE.streak_states.values():
        if row["learner_id"] == learner_id:
            return row
    return None


def subscription_for_learner(learner_id):
    """The subscription record that governs a learner's gate."""
    rows = [r for r in STORE.subscriptions.values() if r["learner_id"] == learner_id]
    if not rows:
        return None
    for row in rows:
        if row["status"] in ("ACTIVE", "IN_GRACE"):
            return row
    return rows[0]


def owner_learner_of(subscription):
    return STORE.learners.get(subscription["learner_id"])


# ---------------------------------------------------------------- touch/version


def touch(row, clock):
    """Refresh updated_at and bump version on a versioned resource (PRD 2.4)."""
    if row is None:
        return
    if "updated_at" in row:
        row["updated_at"] = core.to_iso(clock.get())
    if "version" in row:
        row["version"] = int(row.get("version", 1)) + 1


def touch_children(rows, clock):
    for row in rows:
        touch(row, clock)


# ---------------------------------------------------------------- recompute


def recompute_node_intervals(node):
    """Rebase review_due_at from last_reviewed_at and the crown state interval."""
    if node.get("last_reviewed_at"):
        base = core.parse_iso8601(node["last_reviewed_at"])
        days = core.INTERVAL_DAYS_BY_STATE.get(node["state"], core.MAX_REVIEW_DEPTH_DAYS)
        days = min(days, core.MAX_REVIEW_DEPTH_DAYS)
        node["review_due_at"] = core.to_iso(base + timedelta(days=days))


def recompute_unit_crown_count(unit):
    if unit is None:
        return
    count = 0
    for node in STORE.lesson_nodes.values():
        if node["unit_id"] == unit["id"] and node["state"] in core.CROWN_STATES:
            count += 1
    unit["crown_count"] = count


def held_node_ids(learner_id):
    """Nodes the learner holds: those carrying an accepted attempt of theirs."""
    held = set()
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] != learner_id:
            continue
        if attempt["outcome"] not in ("ACCEPTED", "REJECTED_DECAY_CAP"):
            continue
        held.add(attempt["lesson_node_id"])
    return held


def recompute_leaf_count(learner_id):
    learner = STORE.learners.get(learner_id)
    if learner is None:
        return
    count = 0
    for node_id in held_node_ids(learner_id):
        node = STORE.lesson_nodes.get(node_id)
        if node is not None and node["state"] in core.CROWN_STATES:
            count += 1
    learner["leaf_count"] = count


def recompute_leaf_count_for_unit(unit_id):
    for learner in STORE.learners.values():
        recompute_leaf_count(learner["id"])


def recompute_xp_total(learner_id):
    learner = STORE.learners.get(learner_id)
    if learner is None:
        return
    total = 0
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] == learner_id:
            total += int(attempt.get("xp_awarded") or 0)
    learner["xp_total"] = total


def recompute_all_crown_counts():
    for unit in STORE.course_units.values():
        recompute_unit_crown_count(unit)


def recompute_offer_scored_tier(offer):
    subscription = subscription_for_learner(offer["learner_id"])
    seats_total = subscription["seats_total"] if subscription else 1
    offer["scored_tier"] = "PLUS_FAMILY" if seats_total >= 2 else "PLUS"


def recompute_scored_tier_for_learner(learner_id):
    for offer in STORE.engagement_offers.values():
        if offer["learner_id"] == learner_id and offer["status"] == "ISSUED":
            recompute_offer_scored_tier(offer)


def recompute_streak_anchor_date(learner):
    streak = streak_for_learner(learner["id"])
    if streak is None:
        return
    focus = streak["focus_date"]
    learner["streak_anchor_date"] = focus if isinstance(focus, str) else core.to_iso(focus)


# ---------------------------------------------------------------- units/tree


def units_sorted():
    return sorted(STORE.course_units.values(), key=lambda u: u["unit_index"])


def completed_unit_count_below(unit_index):
    return len(
        [
            u
            for u in STORE.course_units.values()
            if u["state"] == "COMPLETED" and u["unit_index"] < unit_index
        ]
    )


def unit_state(unit):
    if unit["state"] == "COMPLETED":
        return "COMPLETED"
    if unit["state"] == "IN_PROGRESS":
        return "IN_PROGRESS"
    if completed_unit_count_below(unit["unit_index"]) >= unit["unlock_index"]:
        return "AVAILABLE"
    return "LOCKED_UNIT"


def children_of_node(node_id):
    return [n for n in STORE.lesson_nodes.values() if n.get("prerequisite_node_id") == node_id]


def recompute_unit_posture(unit, clock):
    """Derived posture: COMPLETED once every child holds a crown, otherwise the
    posture follows the unlock count and child progress (PRD 3.1)."""
    if unit is None:
        return
    nodes = [n for n in STORE.lesson_nodes.values() if n["unit_id"] == unit["id"]]
    if nodes and len(nodes) >= int(unit.get("total_nodes") or 0) and all(
        n["state"] in ("BRONZE", "SILVER", "GOLD", "LEGENDARY") for n in nodes
    ):
        unit["state"] = "COMPLETED"
        recompute_unit_crown_count(unit)
        return
    if unit["state"] == "COMPLETED":
        unit["state"] = "IN_PROGRESS"
    if any(n["state"] in core.CROWN_STATES for n in nodes):
        unit["state"] = "IN_PROGRESS"
    recompute_unit_crown_count(unit)


def prerequisite_satisfied(node):
    pid = node.get("prerequisite_node_id")
    if not pid:
        return True
    prereq = STORE.lesson_nodes.get(pid)
    if prereq is None:
        return True
    return prereq["state"] in core.CROWN_STATES


def try_unlock_node(node, clock):
    """LOCKED -> UNLOCKED when the unit is open and the prerequisite is met."""
    if node["state"] != "LOCKED":
        return False
    unit = STORE.course_units.get(node["unit_id"])
    if unit is None:
        return False
    if unit_state(unit) not in ("AVAILABLE", "IN_PROGRESS"):
        return False
    if not prerequisite_satisfied(node):
        return False
    node["state"] = "UNLOCKED"
    touch(node, clock)
    return True


def refresh_unlocks(clock):
    """A node opens when its unit is in AVAILABLE or IN_PROGRESS and either it
    has no prerequisite or the prerequisite has reached BRONZE or better."""
    for node in list(STORE.lesson_nodes.values()):
        if node["state"] == "LOCKED":
            try_unlock_node(node, clock)


def prune_locked_units(clock):
    """Derived unit posture: a unit advances when its children advance and is
    pulled backwards when a child is demoted by decay (PRD 2.6 / 3.1)."""
    for unit in units_sorted():
        live = unit_state(unit)
        if live == "LOCKED_UNIT":
            continue
        if unit["state"] == "LOCKED_UNIT":
            unit["state"] = "AVAILABLE"
            for node in list(STORE.lesson_nodes.values()):
                if node["unit_id"] == unit["id"] and not node.get("prerequisite_node_id"):
                    try_unlock_node(node, clock)
            recompute_leaf_count_for_unit(unit["id"])
    # completion bubbles up
    changed = True
    guard = 0
    while changed and guard < 50:
        changed = False
        guard += 1
        for unit in units_sorted():
            if unit["state"] in ("AVAILABLE", "IN_PROGRESS", "LOCKED_UNIT"):
                nodes = [n for n in STORE.lesson_nodes.values() if n["unit_id"] == unit["id"]]
                if nodes and all(n["state"] in ("BRONZE", "SILVER", "GOLD", "LEGENDARY") for n in nodes):
                    unit["state"] = "COMPLETED"
                    changed = True
                    recompute_unit_crown_count(unit)
                    recompute_all_crown_counts()
                    for other in units_sorted():
                        if other["state"] == "LOCKED_UNIT" and unit_state(other) == "AVAILABLE":
                            other["state"] = "AVAILABLE"
                            for node in list(STORE.lesson_nodes.values()):
                                if node["unit_id"] == other["id"] and not node.get("prerequisite_node_id"):
                                    try_unlock_node(node, clock)
                            changed = True
    for unit in STORE.course_units.values():
        recompute_unit_crown_count(unit)
    for learner in STORE.learners.values():
        recompute_leaf_count(learner["id"])