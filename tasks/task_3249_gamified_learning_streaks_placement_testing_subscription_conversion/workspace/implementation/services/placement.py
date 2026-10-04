"""Placement sessions: item presentation, scoring and calibration."""

from datetime import timedelta

import core
import middleware as mw
import serialize
from core import ApiError
from db import STORE
from runtime import CLOCK
from services import calc, common


def create_placement(body, actor):
    learner_id = core.as_str(core.get_field(body, "learner_id"), "learner_id")
    mw.check_learner_param(actor, learner_id)
    mw.own(actor, learner_id)
    learner = common.learner_or_404(learner_id)
    course_id = core.as_str(core.get_field(body, "course_id"), "course_id")
    common.unit_or_404(course_id)
    administered_at = core.parse_iso8601(
        core.as_str(core.get_field(body, "administered_at"), "administered_at")
    )
    total_items = core.as_int(core.get_field(body, "total_items"), "total_items")
    guard = core.as_int(core.get_field(body, "expected_learner_version"), "expected_learner_version")

    if total_items < 5 or total_items > 50:
        raise ApiError(core.ERR_PLACEMENT_UNIT_OUT_OF_RANGE)
    if guard != int(learner["version"]):
        raise ApiError(core.ERR_STALE_VERSION)

    if learner["program_tier"] == "FREE":
        for test in STORE.placement_tests.values():
            if test["learner_id"] == learner_id and test.get("free_probe_used"):
                raise ApiError(core.ERR_PLACEMENT_PROBE_USED)

    proctor_user_id = None
    if core.has_field(body, "proctor_user_id"):
        proctor_user_id = core.as_str(body["proctor_user_id"], "proctor_user_id")
    now = CLOCK.get()
    test = {
        "id": core.new_id(),
        "learner_id": learner_id,
        "course_id": course_id,
        "status": "CREATED",
        "administered_at": core.to_iso(administered_at),
        "graded_at": None,
        "total_items": total_items,
        "comprehension_score": None,
        "accuracy_score": None,
        "calibrated_cefr_band": None,
        "placed_unit_index": None,
        "free_probe_used": False,
        "is_institution_graded": bool(proctor_user_id),
        "proctor_user_id": proctor_user_id,
        "created_at": core.to_iso(now),
        "updated_at": core.to_iso(now),
        "version": 1,
    }
    STORE.placement_tests[test["id"]] = test
    common.touch(learner, CLOCK)
    return test


def _placement_items_count(test):
    """Placement attempts recorded on nodes parented by units up to the session's
    current placed index or the probe span."""
    ceiling = test.get("placed_unit_index")
    if ceiling is None:
        ceiling = core.PLACEMENT_PROBE_SPAN
    count = 0
    for attempt in STORE.practice_attempts.values():
        if not attempt.get("is_placement_attempt"):
            continue
        if attempt["learner_id"] != test["learner_id"]:
            continue
        node = STORE.lesson_nodes.get(attempt["lesson_node_id"])
        if node is None:
            continue
        unit = STORE.course_units.get(node["unit_id"])
        if unit is None:
            continue
        if unit["unit_index"] <= ceiling:
            count += 1
    return count


def update_placement(test_id, body, actor):
    test = STORE.placement_tests.get(test_id)
    if test is None or test["status"] not in core.VALID_PLACEMENT_STATUSES[:4]:
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)
    mw.own(actor, test["learner_id"])
    learner = common.learner_or_404(test["learner_id"])
    action = core.as_str(core.get_field(body, "action"), "action")

    if action == "PRESENT_ITEM":
        return _present_item(test, learner, body)
    if action in ("SUBMIT_SCORES", "SCORE"):
        return _submit_scores(test, learner, body)
    if action == "CALIBRATE":
        return _calibrate(test, learner, body)
    if action in ("ABANDON", "CANCEL"):
        if test["status"] == "CREATED":
            test["status"] = "ABANDONED"
            test["free_probe_used"] = False
            common.touch(test, CLOCK)
            return test
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)
    raise ApiError(core.ERR_INVALID_REQUEST, "Unsupported placement action.")


def _present_item(test, learner, body):
    node_id = core.as_str(core.get_field(body, "lesson_node_id"), "lesson_node_id")
    node = common.node_or_404(node_id)
    if test["status"] not in ("CREATED", "IN_PROGRESS"):
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)
    recorded_at = core.parse_iso8601(
        core.as_str(core.get_field(body, "recorded_at"), "recorded_at")
    )
    response_ms = core.as_int(core.get_field(body, "response_ms"), "response_ms")
    correct = core.as_bool(core.get_field(body, "correct"), "correct")
    if response_ms < 0 or response_ms > 600000:
        raise ApiError(core.ERR_INVALID_REQUEST, "response_ms must lie between 0 and 600000.")

    present_ceiling = max(test.get("placed_unit_index") or 0, core.PLACEMENT_PROBE_SPAN)
    unit = STORE.course_units.get(node["unit_id"])
    if unit is None or unit["unit_index"] > present_ceiling:
        raise ApiError(core.ERR_PLACEMENT_UNIT_OUT_OF_RANGE)
    if _placement_items_count(test) >= int(test["total_items"]):
        raise ApiError(core.ERR_PLACEMENT_UNIT_OUT_OF_RANGE)

    from services import learning

    attempt = learning._apply_attempt(
        learner, node, recorded_at, response_ms, correct, True
    )
    test["status"] = "IN_PROGRESS"
    test["free_probe_used"] = True
    common.touch(test, CLOCK)
    return test


def _submit_scores(test, learner, body):
    if test["status"] not in ("IN_PROGRESS", "CALIBRATED"):
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)
    comprehension = core.as_int(core.get_field(body, "comprehension_score"), "comprehension_score")
    accuracy = core.as_int(core.get_field(body, "accuracy_score"), "accuracy_score")
    if _placement_items_count(test) < int(test["total_items"]):
        raise ApiError(core.ERR_PLACEMENT_UNIT_OUT_OF_RANGE)
    was_calibrated = test["status"] == "CALIBRATED"
    test["comprehension_score"] = comprehension
    test["accuracy_score"] = accuracy
    test["status"] = "SCORED"
    # PRD 3.6: a resubmission that reopens a calibrated session "clears
    # `calibrated_cefr_band` and re-evaluates the band from the stored
    # sub-scores", so the re-evaluated band is written back and the already
    # assigned position is kept monotonic.  A fresh IN_PROGRESS → SCORED
    # submission only records the sub-scores and `graded_at`, because calibration
    # is a separate step.
    if was_calibrated:
        # PRD 3.6: a resubmission that reopens a calibrated session "clears
        # `calibrated_cefr_band`", leaving the session SCORED until calibration is
        # applied again; the already-assigned position is retained so the
        # monotonic guarantee survives the loop.
        test["calibrated_cefr_band"] = None
    test["graded_at"] = core.to_iso(CLOCK.get())
    common.touch(test, CLOCK)
    common.recompute_xp_total(learner["id"])
    return test


def _calibrate(test, learner, body):
    if test["status"] not in ("SCORED", "CALIBRATED"):
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)
    if core.has_field(body, "proctor_user_id"):
        proctor = core.as_str(body["proctor_user_id"], "proctor_user_id")
        test["proctor_user_id"] = proctor
        test["is_institution_graded"] = bool(proctor)
    if test["comprehension_score"] is None or test["accuracy_score"] is None:
        raise ApiError(core.ERR_PLACEMENT_NOT_ACTIVE)

    band, index = calc.placement_band(test)
    test["calibrated_cefr_band"] = band
    existing = test.get("placed_unit_index")
    if existing is not None:
        index = max(int(existing), int(index))
    test["placed_unit_index"] = index
    test["status"] = "CALIBRATED"
    test["graded_at"] = core.to_iso(CLOCK.get())
    common.touch(test, CLOCK)

    for node in list(STORE.lesson_nodes.values()):
        unit = STORE.course_units.get(node["unit_id"])
        if unit is None:
            continue
        if unit["unit_index"] < int(test["placed_unit_index"]) and node["state"] == "LOCKED":
            common.try_unlock_node(node, CLOCK)
    common.prune_locked_units(CLOCK)
    common.refresh_unlocks(CLOCK)
    common.recompute_all_crown_counts()
    common.recompute_leaf_count(learner["id"])
    if int(test["placed_unit_index"]) >= 5:
        calc.issue_offer(learner, "PLACEMENT_SKIP", CLOCK)
    return test