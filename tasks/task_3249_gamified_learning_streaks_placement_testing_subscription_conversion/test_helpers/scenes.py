"""Composite setup helpers, part 2 — scene builders used by the test suite.

Every builder returns a plain dict of the resources it minted so a test can
name the pieces it needs without positional unpacking.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import PROCTOR_WINDOW_HOURS
from .factories import (
    certification_exam_payload, placement_action_payload, placement_test_payload,
)
from .fixtures import (
    ADMIN, PROCTOR, add_seat_ok, append_lesson_node, create_course_unit,
    fire_event, get_learner, get_streak, grant_gems, list_standings, open_league,
    practice_ok, read_node, register_learner, set_clock, settle_league, subscribe,
)
from .test_users import make_learner_headers


# ── Single-learner scene: one course unit with a node chain ──────────────────

def scene_single_node(
    program_tier="FREE", unit_index=1, cefr_band="A1", total_nodes=1,
    display_name=None, local_date_offset_days=0,
):
    """One learner plus a one-unit, one-node course tree.

    Returns ``{learner, headers, unit, nodes}`` where ``nodes`` is a list of
    lesson-node payloads in node_index order.
    """
    learner = register_learner(
        display_name=display_name or "Ada",
        local_date_offset_days=local_date_offset_days,
        program_tier=program_tier,
    )
    unit = create_course_unit(
        unit_index=unit_index, cefr_band=cefr_band, total_nodes=total_nodes
    )
    nodes = [append_lesson_node(unit["id"], 1)]
    return {
        "learner": learner,
        "headers": make_learner_headers(learner["id"]),
        "unit": unit,
        "nodes": nodes,
    }


def scene_node_chain(
    length=2, program_tier="FREE", cefr_band="A1", total_nodes=None,
    display_name=None,
):
    """One learner plus one unit holding a prerequisite chain of ``length`` nodes."""
    learner = register_learner(
        display_name=display_name or "Ada", program_tier=program_tier
    )
    unit = create_course_unit(
        cefr_band=cefr_band,
        total_nodes=length if total_nodes is None else total_nodes,
    )
    nodes = []
    previous = None
    for index in range(1, length + 1):
        node = append_lesson_node(unit["id"], index, previous)
        previous = node["id"]
        nodes.append(node)
    return {
        "learner": learner,
        "headers": make_learner_headers(learner["id"]),
        "unit": unit,
        "nodes": nodes,
    }


def drive_node_to_state(node_id, learner_id, target_state, recorded_at):
    """Practice a node up the crown ladder until it reaches ``target_state``.

    ``recorded_at`` is the timestamp of the first practice; successive practices
    are spaced by one hour so they stay inside the same local day.
    """
    ladder = ["UNLOCKED", "BRONZE", "SILVER", "GOLD", "LEGENDARY"]
    if target_state not in ladder:
        raise ValueError(f"unsupported target state {target_state}")
    steps = ladder.index(target_state)
    attempt = None
    for step in range(steps):
        stamp = recorded_at if step == 0 else recorded_at
        attempt = practice_ok(node_id, learner_id, stamp, response_ms=5000,
                              correct=True)
    return attempt


# ── Placement scenes ─────────────────────────────────────────────────────────

def scene_placement_ready(
    program_tier="CERTIFICATION_ELITE", unit1_band="A1", unit1_nodes=1,
    unit2_band="B1", unit2_nodes=2, total_items=20, complete_unit1=True,
    progress_unit2=False, complete_unit2=False,
    extra_completed_units=0, extra_unit_band="A2", scored=False,
    calibrated=False, comprehension_score=200, accuracy_score=0,
    proctor_user_id=None,
):
    """A learner with a two-unit course tree plus a placement session.

    ``complete_unit1`` drives every node of unit 1 to BRONZE so unit 1 itself
    reaches COMPLETED and unit 2 opens; ``progress_unit2`` then practises unit 2's
    root so unit 2 reaches IN_PROGRESS, while ``complete_unit2`` lifts every 2's
    nodes to BRONZE so the unit closes as COMPLETED.  ``extra_completed_units``
    appends further completed units after unit 2, which raises the self-serve
    ceiling without touching unit 2's POSTURE.  ``scored`` submits sub-scores;
    ``calibrated`` then applies calibration.
    """
    learner = register_learner(
        display_name="Ada", local_date_offset_days=0,
        program_tier=program_tier,
    )
    headers = make_learner_headers(learner["id"])
    stamp = "2026-09-01T00:00:00Z"

    unit1 = create_course_unit(
        unit_index=1, cefr_band=unit1_band, unlock_index=0, total_nodes=unit1_nodes
    )
    unit1_nodes_ids = []
    previous = None
    for index in range(1, unit1_nodes + 1):
        node = append_lesson_node(unit1["id"], index, previous)
        previous = node["id"]
        unit1_nodes_ids.append(node["id"])
    if complete_unit1:
        for node_id in unit1_nodes_ids:
            practice_ok(node_id, learner["id"], stamp, response_ms=5000,
                        correct=True)

    unit2 = create_course_unit(
        unit_index=2, cefr_band=unit2_band, unlock_index=1,
        total_nodes=unit2_nodes,
    )
    unit2_node_ids = []
    previous = None
    for index in range(1, unit2_nodes + 1):
        node = append_lesson_node(unit2["id"], index, previous)
        previous = node["id"]
        unit2_node_ids.append(node["id"])
    unit2_id = unit2_node_ids[0]
    if progress_unit2 and not complete_unit2:
        # Practising one of unit 2's nodes is enough to lift the unit from
        # AVAILABLE to IN_PROGRESS (PRD §3.1) while leaving it short of
        # COMPLETED, which requires every node to reach BRONZE or better.
        practice_ok(unit2_id, learner["id"], stamp, response_ms=5000,
                    correct=True)
    if complete_unit2:
        for node_id in unit2_node_ids:
            practice_ok(node_id, learner["id"], stamp, response_ms=5000,
                        correct=True)

    # PRD §3.6: an item whose node sits in a unit beyond the probe span — the
    # larger of placed_unit_index and PLACEMENT_PROBE_SPAN (5) — is refused.  The
    # deepest unit that may legitimately hold the probed node therefore must be
    # at or below index 5; widen the declared node budget so the boundary holds.
    extra_units = []
    for offset in range(extra_completed_units):
        # PRD §3.1: a unit opens (LOCKED_UNIT → AVAILABLE) only when the count of
        # COMPLETED units with a strictly lower unit_index has reached its
        # unlock_index.  Each extra unit has at least one completed predecessor
        # by the time it is created, so unlock_index 1 leaves it open.
        unit = create_course_unit(
            unit_index=3 + offset, cefr_band=extra_unit_band, unlock_index=1,
            total_nodes=1,
        )
        node = append_lesson_node(unit["id"], 1)
        practice_ok(node["id"], learner["id"], stamp, response_ms=5000,
                    correct=True)
        extra_units.append(unit)

    refreshed = get_learner(learner["id"])
    placement = get_success_data(api_client.create_placement_test(
        placement_test_payload(
            learner_id=learner["id"],
            course_id=unit2["id"],
            administered_at="2026-09-01T02:00:00Z",
            total_items=total_items,
            expected_learner_version=refreshed["version"],
        ),
        headers,
    ))

    if scored or calibrated:
        # PRD §3.6: the sub-score submission "is admitted only once the number of
        # recorded placement attempts on nodes belonging to units up to the
        # session's placed_unit_index has reached the session's total_items".
        # Present that many items first, on a node inside the permitted probe
        # span, then submit the raw sub-scores.
        # Incorrect items are used deliberately: a placement attempt's correctness
# does not feed the sub-scores (those are submitted separately), and a wrong
# answer never crowns the probed node, so the course progression the
# calibration clamps against is left exactly as the test set it up.
        for _ in range(int(total_items)):
            get_success_data(api_client.update_placement_test(
                placement["id"],
                placement_action_payload(
                    "PRESENT_ITEM", lesson_node_id=unit2_id,
                    recorded_at="2026-09-01T02:30:00Z", response_ms=4000,
                    correct=False,
                ),
                headers,
            ))
        payload = placement_action_payload(
            "SUBMIT_SCORES",
            comprehension_score=comprehension_score,
            accuracy_score=accuracy_score,
        )
        if proctor_user_id is not None:
            payload["proctor_user_id"] = proctor_user_id
        get_success_data(
            api_client.update_placement_test(placement["id"], payload, headers)
        )
    if calibrated:
        payload = placement_action_payload("CALIBRATE")
        if proctor_user_id is not None:
            payload["proctor_user_id"] = proctor_user_id
        get_success_data(
            api_client.update_placement_test(placement["id"], payload, headers)
        )

    return {
        "learner": learner,
        "headers": headers,
        "unit1": unit1,
        "unit2": unit2,
        "unit1_nodes": unit1_nodes_ids,
        "unit2_node": unit2_id,
        "extra_units": extra_units,
        "placement": placement,
    }


def scene_certification_ready(
    comprehension_score=120, accuracy_score=80, product_code="DET_PRO",
    proctor_user_id="proctor-1", proctor_window_hours=PROCTOR_WINDOW_HOURS,
    cefr_band="B2",
):
    """A CERTIFICATION_ELITE learner holding a calibrated placement session and a
    PURCHASED certification exam.

    Setup: unit 1 (band ``cefr_band``) completed, placement scored and calibrated
    to B2/C1 with a non-empty proctor id, then the exam purchased.
    """
    learner = register_learner(
        display_name="Ada", local_date_offset_days=0,
        program_tier="CERTIFICATION_ELITE",
    )
    headers = make_learner_headers(learner["id"])
    unit1 = create_course_unit(
        unit_index=1, cefr_band=cefr_band, unlock_index=0, total_nodes=1
    )
    node = append_lesson_node(unit1["id"], 1)
    practice_ok(node["id"], learner["id"], "2026-09-01T00:00:00Z", correct=True)

    refreshed = get_learner(learner["id"])
    # PRD §3.8: the purchase consumes a session that "sits in `SCORED` state", its
    # calibrated band is B2 or C1, and the named `proctor_user_id` is non-empty.
    # Naming the proctor at create time stamps both the id and the
    # is_institution_graded flag (PRD §3.6: "the flag is true exactly when
    # `proctor_user_id` holds a non-empty operator identifier"), so the session
    # reaches SCORED directly on its sub-score submission.
    placement = get_success_data(api_client.create_placement_test(
        placement_test_payload(
            learner_id=learner["id"],
            course_id=unit1["id"],
            administered_at="2026-09-01T01:00:00Z",
            total_items=20,
            expected_learner_version=refreshed["version"],
            proctor_user_id=proctor_user_id,
        ),
        headers,
    ))
    # PRD §3.6: scoring needs total_items recorded placement attempts on nodes
    # inside the permitted probe span before the sub-scores are admitted.
    for _ in range(20):
        get_success_data(api_client.update_placement_test(
            placement["id"],
            placement_action_payload(
                "PRESENT_ITEM", lesson_node_id=node["id"],
                recorded_at="2026-09-01T01:30:00Z", response_ms=4000,
                correct=False,
            ),
            headers,
        ))
    get_success_data(api_client.update_placement_test(
        placement["id"],
        placement_action_payload(
            "SUBMIT_SCORES", comprehension_score=comprehension_score,
            accuracy_score=accuracy_score,
        ),
        headers,
    ))
    # PRD §3.8: the purchase consumes a session whose "calibrated band is `B2` or
    # `C1`" under a non-empty proctor id.  Only calibration assigns the band, so
    # the session is calibrated before the exam is purchased.
    calibrated = get_success_data(api_client.update_placement_test(
        placement["id"],
        placement_action_payload("CALIBRATE", proctor_user_id=proctor_user_id),
        headers,
    ))
    placement = calibrated

    refreshed = get_learner(learner["id"])
    exam = get_success_data(api_client.create_certification_exam(
        certification_exam_payload(
            learner_id=learner["id"],
            product_code=product_code,
            proctor_user_id=proctor_user_id,
            proctor_window_hours=proctor_window_hours,
            expected_learner_version=refreshed["version"],
        ),
        headers,
    ))
    return {
        "learner": learner,
        "headers": headers,
        "unit1": unit1,
        "node": node,
        "placement": placement,
        "exam": exam,
    }


def proctor_exam(exam_id, proctor_user_id="proctor-1", discipline_score=5):
    """Open the proctoring window on an exam."""
    return get_success_data(api_client.update_certification_exam(
        exam_id,
        {"action": "PROCTOR", "proctor_user_id": proctor_user_id,
         "discipline_score": discipline_score},
        PROCTOR,
    ))


def submit_exam_score(exam_id, learner_id, raw_score):
    return api_client.update_certification_exam(
        exam_id, {"action": "SUBMIT_SCORE", "raw_score": raw_score},
        make_learner_headers(learner_id),
    )


def finalize_exam(exam_id, discipline_penalty=None):
    payload = {"action": "FINALIZE"}
    if discipline_penalty is not None:
        payload["discipline_penalty"] = discipline_penalty
    return get_success_data(
        api_client.update_certification_exam(exam_id, payload, PROCTOR)
    )


# ── Subscription / family scenes ─────────────────────────────────────────────

def scene_plus_family_with_seat(
    seats_total=4, member_display_name="Bea", initial_plan_tier="FREE",
    offer_for_member=None, auto_renew=True,
):
    """Ada owns an ACTIVE PLUS_FAMILY subscription; Bea occupies one ACTIVE seat.

    Returns ``{owner, owner_headers, member, member_headers, subscription, seat}``.
    """
    owner = register_learner(
        display_name="Ada", local_date_offset_days=0, program_tier=initial_plan_tier
    )
    member = register_learner(
        display_name=member_display_name, local_date_offset_days=0,
        program_tier="FREE",
    )
    subscription = subscribe(
        owner["id"], "PLUS_FAMILY", seats_total=seats_total, auto_renew=auto_renew
    )
    seat = add_seat_ok(
        subscription["id"], owner["id"], member["id"], subscription["version"]
    )
    offer = None
    if offer_for_member is not None:
        offer = get_success_data(api_client.create_engagement_offer(
            {"learner_id": member["id"], "milestone_code": offer_for_member},
            ADMIN,
        ))
    return {
        "owner": owner,
        "owner_headers": make_learner_headers(owner["id"]),
        "member": member,
        "member_headers": make_learner_headers(member["id"]),
        "subscription": subscription,
        "seat": seat,
        "offer": offer,
    }


def drive_subscription_to_in_grace(subscription_id, owner_learner_id,
                                   period_end_probe="2026-10-05T00:00:00Z"):
    """Advance the clock past the period end and fire the renewal sweep so the
    subscription sits in IN_GRACE."""
    set_clock(period_end_probe)
    fire_event("SUBSCRIPTION_RENEWAL")


def expire_subscription_by_renewal_failure(subscription_id, owner_learner_id,
                                           jump_days=60):
    """Drive an auto-renewing subscription past its grace window to EXPIRED.

    The period end is read back from the subscription rather than assumed, so the
    clock jump is anchored on the server's own value; the renewal sweep is fired
    twice because one call may only open the grace window.
    """
    from datetime import datetime, timedelta

    headers = make_learner_headers(owner_learner_id)
    subscription = get_success_data(
        api_client.get_subscription(subscription_id, headers)
    )
    period_end = datetime.fromisoformat(
        subscription["current_period_end"].replace("Z", "+00:00")
    )
    beyond = period_end + timedelta(days=jump_days)
    set_clock(beyond.strftime("%Y-%m-%dT%H:%M:%SZ"))
    fire_event("SUBSCRIPTION_RENEWAL")
    fire_event("SUBSCRIPTION_RENEWAL")
    return get_success_data(api_client.get_subscription(subscription_id, headers))


def scene_broken_streak(
    gems=40, record_at="2026-09-01T00:00:00Z",
    close_clock="2026-09-01T12:00:00Z", program_tier="FREE",
):
    """Ada holds a BROKEN streak whose focus_date is the day of ``record_at``.

    The learner registers at the startup clock, a day-close sweep runs, the clock
    is moved into the next local day, and a second day-close sweep breaks the
    (unqualified) day.
    """
    learner = register_learner(
        display_name="Ada", local_date_offset_days=0, program_tier=program_tier
    )
    if gems:
        grant_gems(learner["id"], gems)
    set_clock(close_clock)
    fire_event("STREAK_DAY_CLOSE")
    set_clock("2026-09-02T12:00:00Z")
    fire_event("STREAK_DAY_CLOSE")
    streak = get_streak(learner["id"])
    return {
        "learner": learner,
        "headers": make_learner_headers(learner["id"]),
        "streak": streak,
    }


def scene_broken_streak_with_length(length=2, gems=40):
    """A BROKEN streak that was ``length`` days long immediately before the break.

    Qualifies ``length`` consecutive local days starting at 2026-09-01, then closes
    one unqualified day to break the streak.
    """
    from datetime import datetime, timedelta, timezone

    learner = register_learner(
        display_name="Ada", local_date_offset_days=0, program_tier="FREE"
    )
    grant_gems(learner["id"], gems)
    unit = create_course_unit(total_nodes=1)
    node = append_lesson_node(unit["id"], 1)

    # Walk real calendar days so long streaks (e.g. 35 days) stay in well-formed
    # dates rather than overflowing a fixed month.  The anchor is the server's
    # startup local date, since the streak row is minted against it.
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    for offset in range(length):
        day = start + timedelta(days=offset)
        set_clock(day.replace(hour=0).strftime("%Y-%m-%dT%H:%M:%SZ"))
        practice_ok(node["id"], learner["id"],
                    day.replace(hour=1).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    correct=True)
        set_clock((day + timedelta(days=1)).replace(hour=0)
                  .strftime("%Y-%m-%dT%H:%M:%SZ"))
        fire_event("STREAK_DAY_CLOSE")

    # one unqualified day closes into a break, preserving the pre-break length in
    # the computed repair price
    break_day = start + timedelta(days=length + 1)
    set_clock(break_day.replace(hour=12).strftime("%Y-%m-%dT%H:%M:%SZ"))
    fire_event("STREAK_DAY_CLOSE")
    streak = get_streak(learner["id"])
    return {
        "learner": learner,
        "headers": make_learner_headers(learner["id"]),
        "unit": unit,
        "node": node,
        "streak": streak,
    }


def scene_league_with_standing(
    tier="BRONZE", week_start="2026-09-21T00:00:00Z", program_tier="PLUS_FAMILY",
    display_name="Ada",
):
    """A league round opened for one learner, who holds a GOOD_STANDING standing.

    PRD §3.7: joining is admitted only when the learner either has
    ``limits_removed`` true on an ACTIVE paid subscription or holds an ACTIVE
    family seat, so the scene purchases the paid plan that makes the learner
    eligible before opening the round.
    """
    learner = register_learner(
        display_name=display_name, local_date_offset_days=0,
        program_tier=program_tier,
    )
    subscribe(learner["id"], "PLUS_FAMILY", seats_total=1, auto_renew=True)
    league = open_league(tier, week_start, learner_id=learner["id"])
    return {
        "learner": learner,
        "headers": make_learner_headers(learner["id"]),
        "league": league,
    }


def scene_league_with_weekly_attempts(
    attempt_dates, tier="BRONZE", week_start="2026-09-21T00:00:00Z",
    program_tier="PLUS_FAMILY", response_ms=2500, correct=True,
    node_state_target="UNLOCKED",
):
    """A league round plus a learner who booked one accepted attempt per date.

    ``attempt_dates`` is a list of ``(date, hour)`` pairs expressed as
    ``"2026-09-23T10:00:00Z"`` strings; each becomes one accepted practice attempt
    inside the league week.
    """
    learner = register_learner(
        display_name="Ada", local_date_offset_days=0,
        program_tier=program_tier,
    )
    headers = make_learner_headers(learner["id"])
    # PRD §3.7: only a learner with limits_removed or an ACTIVE family seat may
    # join a round.
    subscribe(learner["id"], "PLUS_FAMILY", seats_total=1, auto_renew=True)
    league = open_league(tier, week_start, learner_id=learner["id"])
    # A fresh root node per attempt: each root starts UNLOCKED, so every attempt
    # is priced from the same crown base (PRD §3.4), rather than walking one node
    # up the crown ladder and shrinking its base award each time.
    unit = create_course_unit(total_nodes=len(attempt_dates))
    node = None
    for offset, recorded_at in enumerate(attempt_dates):
        node = append_lesson_node(unit["id"], offset + 1)
        practice_ok(node["id"], learner["id"], recorded_at,
                    response_ms=response_ms, correct=correct)
    return {
        "learner": learner,
        "headers": headers,
        "league": league,
        "unit": unit,
        "node": node,
    }


def scene_league_demotion_mutates_crowned_node():
    """A league whose sole GOOD_STANDING learner settles as DEMOTED while holding
    one crowned node inside a COMPLETED unit, plus one node left stranded by an
    earlier decay sweep in a different unit.

    Builds two units: unit 1 is completed first so unit 2 opens, then unit 2 is
    completed as well.  A decay sweep eleven days later demotes unit 1's only node
    while unit 2's node — reviewed two days into the window — sits at four decay
    points.  The league then settles.

    Returns ``{learner, headers, league, unit1, unit2, gold_node, decayed_node,
    standing}``.
    """
    learner = register_learner(
        display_name="Ada", local_date_offset_days=0, program_tier="PLUS_FAMILY"
    )
    headers = make_learner_headers(learner["id"])
    # PRD §3.7: the JOIN path requires limits_removed or an ACTIVE family seat.
    subscribe(learner["id"], "PLUS_FAMILY", seats_total=1, auto_renew=True)

    unit1 = create_course_unit(unit_index=1, cefr_band="A1", unlock_index=0,
                               total_nodes=1)
    decayed_root = append_lesson_node(unit1["id"], 1)
    practice_ok(decayed_root["id"], learner["id"], "2026-09-01T00:00:00Z",
                response_ms=5000, correct=True)

    unit2 = create_course_unit(unit_index=2, cefr_band="B1", unlock_index=1,
                               total_nodes=1)
    crowned_root = append_lesson_node(unit2["id"], 1)

    league = open_league("GOLD", "2026-09-21T00:00:00Z", learner_id=learner["id"])

    set_clock("2026-09-02T00:00:00Z")
    for hour in (0, 1, 2):
        # Three accepted attempts on the same local day lift unit 2's only node
        # UNLOCKED → BRONZE → SILVER → GOLD and close unit 2 as COMPLETED, so its
        # node carries a GOLD crown inside a completed unit — exactly the
        # population the demotion sting targets.
        practice_ok(crowned_root["id"], learner["id"],
                    "2026-09-02T%02d:00:00Z" % hour,
                    response_ms=5000, correct=True)

    # The decay sweep runs on 2026-09-11.  Unit 1's node (reviewed 09-01, due
    # 09-02) has by then accrued a five-point meter and is demoted, pulling unit
    # 1 back to IN_PROGRESS; unit 2's node (reviewed 09-02) has accrued only
    # four points, so it keeps its GOLD crown and unit 2 stays COMPLETED.
    set_clock("2026-09-11T00:00:00Z")
    fire_event("SKILL_DECAY")

    refreshed_crowned = read_node(crowned_root["id"], learner["id"])
    refreshed_decayed = read_node(decayed_root["id"], learner["id"])

    set_clock("2026-09-28T00:00:00Z")
    settle_league(league["id"])
    standing = list_standings(learner["id"], league["id"])[0]
    return {
        "learner": learner,
        "headers": headers,
        "league": league,
        "unit1": unit1,
        "unit2": unit2,
        "gold_node": refreshed_crowned,
        "decayed_node": refreshed_decayed,
        "standing": standing,
    }
