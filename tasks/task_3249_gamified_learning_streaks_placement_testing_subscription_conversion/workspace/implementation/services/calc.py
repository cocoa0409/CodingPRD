"""Every calculation rule from SCAFFOLD.yaml calculations[] and PRD 3.x."""

from datetime import timedelta

import core
from core import ApiError
from db import STORE
from services import common


# ------------------------------------------------- streak day boundary


def focus_date_of(streak, clock):
    return core.focus_date_of(clock, streak["local_date_offset_days"])


def day_close_due(streak, clock):
    offset = int(streak["local_date_offset_days"])
    local_seconds = int(clock.get().timestamp()) + offset * core.DAY_SECONDS
    focus_midnight = local_seconds - (local_seconds % core.DAY_SECONDS)
    elapsed = local_seconds - focus_midnight
    remaining = core.DAY_SECONDS - elapsed
    return remaining <= core.STREAK_DAY_CLOSE_BUFFER_SECONDS


# ------------------------------------------------- heart and energy limits


def heart_and_energy(learner, clock, persist=True):
    """ComputeHeartAndEnergyLimits. Returns (hearts, energy, gate, limits_removed)."""
    subscription = common.subscription_for_learner(learner["id"])
    limits_removed = bool(
        subscription
        and subscription["status"] == "ACTIVE"
        and subscription["plan_code"] != "FREE"
    )
    if learner["program_tier"] in ("PLUS_FAMILY", "CERTIFICATION_ELITE") and limits_removed:
        return None, None, "UNLIMITED", limits_removed

    streak = common.streak_for_learner(learner["id"])
    if streak is None:
        focus = core.focus_date_of(clock, 0)
    else:
        focus = focus_date_of(streak, clock)
    window_end = focus + timedelta(seconds=core.DAY_SECONDS)

    hearts_used = 0
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] != learner["id"]:
            continue
        if attempt["correct"]:
            continue
        if attempt.get("is_placement_attempt"):
            continue
        recorded = core.parse_iso8601(attempt["recorded_at"])
        if focus <= recorded < window_end:
            hearts_used += 1
    hearts = max(0, core.FREE_HEARTS_PER_DAY - hearts_used)

    energy, anchor = accrue_energy(learner, clock, subscription, persist=persist)
    gate = "EXAM_ALLOWED" if (hearts >= 1 and energy >= 1) else "EXAM_BLOCKED"
    return hearts, energy, gate, limits_removed


def accrue_energy(learner, clock, subscription=None, persist=True):
    anchor = core.parse_iso8601(learner["energy_anchor_at"])
    now = clock.get()
    elapsed = int((now - anchor).total_seconds())
    if elapsed < 0:
        elapsed = 0
    units = int(learner["energy_units"])

    quantized = bool(
        subscription
        and subscription["plan_code"] == "CERTIFICATION_ELITE"
        and subscription["status"] == "IN_GRACE"
    )
    interval = core.DAY_SECONDS if quantized else core.ENERGY_REGEN_SECONDS
    intervals = elapsed // interval
    if intervals > 0:
        units = min(core.ENERGY_CAP, units + intervals * core.ENERGY_UNITS_PER_INTERVAL)
        anchor = anchor + timedelta(seconds=intervals * interval)
        learner["energy_anchor_at"] = core.to_iso(anchor)
    if persist:
        learner["energy_units"] = units
    return units, anchor


def spend_energy(learner, clock):
    subscription = common.subscription_for_learner(learner["id"])
    units, _ = accrue_energy(learner, clock, subscription, persist=True)
    learner["energy_units"] = max(0, units - 1)
    learner["energy_anchor_at"] = core.to_iso(clock.get())


def refresh_learner_limits(learner, clock):
    limit = compute_gate_learner(learner, clock)
    learner["hearts_available"] = limit


def compute_gate_learner(learner, clock):
    hearts, energy, gate, _ = heart_and_energy(learner, clock, persist=False)
    return hearts


# ------------------------------------------------- practice xp award


def streak_multiplier(current_length, program_tier):
    # PRD 3.4: "Free learners are capped at the neutral 1.00 multiplier no matter
    # how long their streak" — the cap keys on program_tier alone, so a learner
    # holding a paid plan reads the tiered ladder even before subscribing.
    if program_tier not in ("PLUS_FAMILY", "CERTIFICATION_ELITE"):
        return core.to_decimal("1.00")
    if current_length >= 100:
        return core.to_decimal("1.50")
    if current_length >= 10:
        return core.to_decimal("1.25")
    if current_length >= 2:
        return core.to_decimal("1.10")
    return core.to_decimal("1.00")


def speed_bonus(response_ms):
    if response_ms < core.FAST_MS:
        return 3
    if response_ms < core.MEDIUM_MS:
        return 1
    return 0


def xp_award(node_state, response_ms, correct, current_length, program_tier):
    if not correct:
        return 0
    base = core.BASE_BY_STATE.get(node_state, 0)
    bonus = speed_bonus(response_ms)
    mult = streak_multiplier(current_length, program_tier)
    exact = core.to_decimal(base + bonus) * mult
    return core.round_half_up(exact)


def exact_attempt_xp(attempt, multiplier):
    base = core.BASE_BY_STATE.get(attempt.get("_node_state_at_attempt", "UNLOCKED"), 0)
    bonus = speed_bonus(int(attempt["response_ms"]))
    return core.to_decimal(base + bonus) * multiplier


# ------------------------------------------------- skill decay


def decay_points_for(node, learner, clock):
    last = core.parse_iso8601(node["last_reviewed_at"]) if node.get("last_reviewed_at") else clock.get()
    days_since = int((clock.get() - last).total_seconds()) // core.DAY_SECONDS
    subscription = common.subscription_for_learner(learner["id"]) if learner else None
    if subscription and subscription["status"] == "EXPIRED":
        return core.DECAY_POINTS_PER_TIER - 1
    return min(core.DECAY_POINTS_PER_TIER, days_since // core.DECAY_GRACE_DAYS)


def review_due_at(node, learner_or_none=None):
    if not node.get("last_reviewed_at"):
        return None
    base = core.parse_iso8601(node["last_reviewed_at"])
    days = min(
        core.INTERVAL_DAYS_BY_STATE.get(node["state"], core.MAX_REVIEW_DEPTH_DAYS),
        core.MAX_REVIEW_DEPTH_DAYS,
    )
    return base + timedelta(days=days)


def learner_for_node(node_id):
    for attempt in STORE.practice_attempts.values():
        if attempt["lesson_node_id"] == node_id:
            return STORE.learners.get(attempt["learner_id"])
    return None


def run_skill_decay_sweep(clock):
    from services import common as _common
    in_scope = ["UNLOCKED", "BRONZE", "SILVER", "GOLD", "LEGENDARY"]
    for node in list(STORE.lesson_nodes.values()):
        if node["state"] not in in_scope:
            continue
        learner = learner_for_node(node["id"])
        points = decay_points_for(node, learner, clock)
        due = review_due_at(node)
        if due is not None:
            node["review_due_at"] = core.to_iso(due)
        # PRD 3.2: "the meter is capped at five points" and the sweep demotes the
        # node only "When a node's decay_meter has reached the five-point ceiling
        # and the clock is at or past its review_due_at". Below that ceiling the
        # accrued meter is retained, not zeroed.
        node["decay_meter"] = points
        if points >= core.DECAY_POINTS_PER_TIER and due is not None and clock.get() >= due:
            was_crowned = node["state"] in core.CROWN_STATES
            node["state"] = "DECAYED"
            node["decay_level"] = min(core.DECAY_LEVEL_FLOOR, node["decay_level"] + 1)
            node["decay_meter"] = 0
            common.touch(node, clock)
            if was_crowned:
                relock_dependents(node, clock)
            common.recompute_unit_crown_count(STORE.course_units.get(node["unit_id"]))
            common.recompute_leaf_count_for_unit(node["unit_id"])
        else:
            common.touch(node, clock)
    _common.prune_locked_units(clock)
    _common.refresh_unlocks(clock)
    common.recompute_all_crown_counts()


def relock_dependents(node, clock):
    """Decay is contagious down the chain (PRD 3.2)."""
    for child in common.children_of_node(node["id"]):
        if child["state"] == "UNLOCKED" and not common.prerequisite_satisfied(child):
            child["state"] = "LOCKED"
            common.touch(child, clock)


# ------------------------------------------------- placement


def placement_sub_score(comprehension, accuracy, total_items, institution_graded):
    combined = comprehension + accuracy
    if institution_graded:
        unit_credit = -((-combined) // core.SUBSCORE_DIVISOR)
    else:
        unit_credit = combined // core.SUBSCORE_DIVISOR
    count_credit = total_items // core.ITEMS_PER_UNIT
    return min(core.PLACEMENT_MAX_UNIT_INDEX, unit_credit + count_credit)


def candidate_band(combined):
    for band, cutoff in core.BAND_CUTOFFS_COMBINED:
        if combined >= cutoff:
            return band
    return "A1"


def placement_band(test):
    combined = int(test["comprehension_score"] or 0) + int(test["accuracy_score"] or 0)
    band = candidate_band(combined)
    raw_index = placement_sub_score(
        int(test["comprehension_score"] or 0),
        int(test["accuracy_score"] or 0),
        int(test["total_items"]),
        bool(test["is_institution_graded"]),
    )
    completed = [u for u in STORE.course_units.values() if u["state"] == "COMPLETED"]
    if test["is_institution_graded"]:
        anchors = [
            u for u in STORE.course_units.values() if u["state"] in ("COMPLETED", "IN_PROGRESS")
        ]
    else:
        anchors = completed
    if anchors:
        hard_cap = max(u["unit_index"] for u in anchors)
    else:
        hard_cap = core.PLACEMENT_MAX_UNIT_INDEX
    if hard_cap >= raw_index:
        return band, min(raw_index, hard_cap)
    # PRD 3.6: "when the ceiling falls short of the provisional index the learner
    # is placed at the ceiling and the calibrated band becomes that ceiling unit's
    # own cefr_band instead."  The ceiling unit is the anchor that fixed hard_cap,
    # which for an institution-graded session may be an IN_PROGRESS unit.
    for anchor in anchors:
        if anchor["unit_index"] == hard_cap:
            band = anchor["cefr_band"]
            break
    return band, hard_cap


# ------------------------------------------------- streak repair pricing


def repair_cost(_current_length_at_break, purchases_this_month, per_term=False):
    segment = min(4, int(_current_length_at_break) // 30)
    tier_rate = core.TIER_RATE_GEMS[segment]
    bonus = core.round_half_up((int(_current_length_at_break) % 30) * core.LENGTH_BONUS_RATE)
    undiscounted = tier_rate + bonus
    display = min(core.MONTHLY_REPAIR_CAP_GEMS, undiscounted)
    inflation = core.to_decimal(1) + core.REPAIR_INFLATION_RATE * int(purchases_this_month)
    if per_term:
        inflated = core.round_half_up(core.to_decimal(tier_rate) * inflation) + core.round_half_up(
            core.to_decimal(bonus) * inflation
        )
    else:
        inflated = core.round_half_up(core.to_decimal(undiscounted) * inflation)
    debit = min(core.MONTHLY_REPAIR_CAP_GEMS, inflated)
    return display, debit


def recompute_repair_cost(streak, learner, per_term=False):
    display, _debit = repair_cost(
        int(streak.get("_current_length_at_break") or 0),
        int(streak.get("repair_purchases_this_month") or 0),
        per_term=per_term,
    )
    streak["repair_cost_gems"] = display
    return display


# ------------------------------------------------- league ranking


def league_week_attempts(learner_id, week_start):
    start = core.parse_iso8601(week_start)
    end = start + timedelta(days=core.LEAGUE_WEEK_DAYS)
    rows = []
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] != learner_id:
            continue
        recorded = core.parse_iso8601(attempt["recorded_at"])
        if start <= recorded < end:
            rows.append(attempt)
    return rows


def weekly_xp_for(standing, league, per_attempt_rounding=True):
    learner = STORE.learners.get(standing["learner_id"])
    tier = learner["program_tier"] if learner else "FREE"
    streak = common.streak_for_learner(standing["learner_id"])
    length = int(streak["current_length"]) if streak else 0
    mult = streak_multiplier(length, tier)
    attempts = league_week_attempts(standing["learner_id"], league["week_start"])
    if per_attempt_rounding:
        total = 0
        for attempt in attempts:
            total += core.round_half_up(exact_attempt_xp(attempt, mult))
        return total, len(attempts)
    total = core.to_decimal(0)
    for attempt in attempts:
        total += exact_attempt_xp(attempt, mult)
    return core.round_half_up(total), len(attempts)


def eligible_standings(league):
    return [
        s for s in STORE.league_standings.values()
        if s["league_id"] == league["id"] and s["standing"] == "GOOD_STANDING"
    ]


def compute_league_flags(league, clock, per_attempt_rounding=True):
    """ComputeLeagueFlags: freeze the candidate set, derive the aggression and
    fast-reference figures, flag the preliminary top learner when condemned."""
    candidates = eligible_standings(league)
    for standing in candidates:
        standing["weekly_xp"], standing["_attempt_count"] = weekly_xp_for(
            standing, league, per_attempt_rounding=per_attempt_rounding
        )
    stats = {}
    for standing in candidates:
        stats[standing["id"]] = (
            standing["weekly_xp"],
            standing.get("_attempt_count", 0),
        )
    median_xp = _median([stats[s["id"]][0] for s in candidates])
    top = None
    if candidates:
        top = sorted(
            candidates,
            key=lambda s: (-stats[s["id"]][0], -stats[s["id"]][1], s["created_at"]),
        )[0]
    for standing in candidates:
        flag_reason = None
        if top is not None and standing["id"] == top["id"]:
            reason = _flag_for_top(top, league, median_xp, stats, clock)
            if reason:
                flag_reason = reason
        if flag_reason:
            standing["standing"] = "FLAGGED"
            standing["flag_reason"] = flag_reason
            common.touch(standing, clock)
    league["member_count"] = len(
        [
            s
            for s in STORE.league_standings.values()
            if s["league_id"] == league["id"] and s["standing"] in ("GOOD_STANDING", "FLAGGED")
        ]
    )


def _median(values):
    if not values:
        return 0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _flag_for_top(top, league, median_xp, stats, clock):
    top_xp = stats[top["id"]][0]
    aggression = core.round_half_up(
        core.to_decimal(1000) * core.to_decimal(top_xp) / core.to_decimal(1 + median_xp)
    )
    attempts = league_week_attempts(top["learner_id"], league["week_start"])
    benchmark_node_id = None
    for attempt in sorted(attempts, key=lambda a: _node_index(a["lesson_node_id"])):
        benchmark_node_id = attempt["lesson_node_id"]
        break
    ref_count = 0
    for attempt in attempts:
        if attempt["lesson_node_id"] == benchmark_node_id and int(attempt["response_ms"]) < core.FAST_ANSWER_MS:
            ref_count += 1
    correct_count = len([a for a in attempts if a["correct"]])
    accuracy_break = correct_count / max(1, len(attempts))
    if ref_count >= core.CHEAT_REF_THRESHOLD and aggression >= core.AGGRESSION_MIN:
        return "HIGH_ASYMMETRY_FAST_REFERENCES"
    if aggression >= core.AGGRESSION_MIN and accuracy_break < core.ACCURACY_BREAK_MIN:
        return "HIGH_ASYMMETRY_FAST_REFERENCES"
    return None


def _node_index(node_id):
    node = STORE.lesson_nodes.get(node_id)
    return node["node_index"] if node else 0


def compute_league_ranking(league, clock, per_attempt_rounding=True):
    candidates = eligible_standings(league)
    for standing in candidates:
        standing["weekly_xp"], standing["_attempt_count"] = weekly_xp_for(
            standing, league, per_attempt_rounding=per_attempt_rounding
        )
    member_count = league["member_count"] or len(candidates)
    league["promotion_cutoff_rank"] = min(core.PROMOTION_CUTOFF_RANK, member_count)
    league["demotion_cutoff_rank"] = max(1, member_count - core.DEMOTION_SPAN + 1)
    for standing in candidates:
        beating = 0
        for other in candidates:
            if other["id"] == standing["id"]:
                continue
            if other["weekly_xp"] > standing["weekly_xp"]:
                beating += 1
            elif other["weekly_xp"] == standing["weekly_xp"]:
                if other.get("_attempt_count", 0) > standing.get("_attempt_count", 0):
                    beating += 1
                elif (
                    other.get("_attempt_count", 0) == standing.get("_attempt_count", 0)
                    and other["created_at"] < standing["created_at"]
                ):
                    beating += 1
        standing["rank"] = 1 + beating
    return candidates


# ------------------------------------------------- certification


def certification_band(raw_score, discipline_penalty, proctored):
    raw = int(raw_score)
    penalty = int(discipline_penalty or 0)
    if proctored and penalty > core.ONE_STEP_DEMOTION_PENALTY:
        normalized = max(0, min(100, raw + penalty))
        for band, cutoff in core.BAND_CUTOFFS_CERT:
            if normalized >= cutoff:
                return band
        return "NOT_CERTIFIED"
    for band, cutoff in core.BAND_CUTOFFS_CERT:
        if raw >= cutoff:
            base = band
            break
    else:
        base = "NOT_CERTIFIED"
    if penalty <= core.ONE_STEP_DEMOTION_PENALTY:
        idx = core.CERT_BAND_ORDER.index(base)
        base = core.CERT_BAND_ORDER[max(0, idx - 1)]
    return base


# ------------------------------------------------- conversion discount


def discount_percent(learner, milestone_code, subscription):
    streak = common.streak_for_learner(learner["id"])
    length = int(streak["current_length"]) if streak else 0
    milestone_bonus = core.MILESTONE_DISCOUNT.get(milestone_code, 0)
    streak_bonus = min(
        core.STREAK_BONUS_CAP_PCT,
        (max(0, length - 7) // 7) * core.STREAK_BONUS_STEP_PCT,
    )
    return min(
        core.MAX_DISCOUNT_PCT,
        core.BASE_DISCOUNT_PCT + milestone_bonus + streak_bonus,
    )


def _total_due_cents(discount_pct, seats_total):
    exact = (
        core.to_decimal(core.BASE_MONTHLY_FEE_CENTS)
        * core.to_decimal(int(seats_total))
        * core.to_decimal(100 - int(discount_pct))
        / core.to_decimal(100)
    )
    return core.round_half_up(exact)


def scored_tier(seats_total):
    return "PLUS_FAMILY" if int(seats_total) >= 2 else "PLUS"


# ------------------------------------------------- notification cadence


def notification_cadence(learner, clock):
    streak = common.streak_for_learner(learner["id"])
    status = streak["status"] if streak else "EVALUATING"
    quota = core.NOTIFY_BASE_DAILY_CAP
    if learner["program_tier"] == "CERTIFICATION_ELITE":
        quota += 2
    if any(
        o["learner_id"] == learner["id"] and o["status"] == "ISSUED"
        for o in STORE.engagement_offers.values()
    ):
        quota += 1
    if status == "BROKEN":
        window_start = clock.get() - timedelta(hours=24)
        window_end = clock.get()
    else:
        if streak is not None:
            window_start = focus_date_of(streak, clock)
        else:
            window_start = core.focus_date_of(clock, 0)
        window_end = window_start + timedelta(seconds=core.DAY_SECONDS)
    used = 0
    for attempt in STORE.practice_attempts.values():
        if attempt["learner_id"] != learner["id"]:
            continue
        recorded = core.parse_iso8601(attempt["recorded_at"])
        if window_start <= recorded < window_end:
            used += 1
    remaining = max(0, quota - used)
    return "ALLOWED" if remaining >= 1 else "SUPPRESSED"


def urgency_rank(learner, clock):
    streak = common.streak_for_learner(learner["id"])
    status = streak["status"] if streak else "EVALUATING"
    if status == "BROKEN":
        return 0
    if streak is not None and int(streak["freeze_tokens"]) == 0 and status == "EVALUATING":
        return 1
    hearts = learner.get("hearts_available")
    if hearts is not None and hearts <= 1:
        return 2
    return 3


def issue_offer(learner, milestone_code, clock):
    """Mint a conversion offer: priced, then cadence-gated (PRD 3.9)."""
    if milestone_code not in core.VALID_MILESTONES:
        raise ApiError(core.ERR_INVALID_REQUEST)
    subscription = common.subscription_for_learner(learner["id"])
    pct = discount_percent(learner, milestone_code, subscription)
    seats = subscription["seats_total"] if subscription else 1
    now = clock.get()
    cadence = notification_cadence(learner, clock)
    offer = {
        "id": core.new_id(),
        "learner_id": learner["id"],
        "milestone_code": milestone_code,
        "discount_pct": pct,
        "status": "SUPPRESSED" if cadence == "SUPPRESSED" else "ISSUED",
        "issued_at": core.to_iso(now),
        "expires_at": core.to_iso(now + timedelta(days=core.OFFER_WINDOW_DAYS)),
        "scored_tier": scored_tier(seats),
        "_total_due_cents": _total_due_cents(pct, seats),
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.engagement_offers[offer["id"]] = offer
    return offer