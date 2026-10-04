"""Payload factories — one per resource, input fields only.

Only fields the PRD declares as client-supplied appear here; derived counters
are never sent.  Optional fields are omitted by default so a caller can test
their presence or absence deliberately.
"""
from .constants import TEST_DEFAULTS


# ── Earned certificates are tracked by learner id for prefix naming ──────────
def learner_payload(**overrides):
    """Registration payload for POST /learners.

    ``program_tier`` is optional; when it is not supplied the server's own
    default tier applies.
    """
    return dict(overrides)


def learner_registration_payload(
    display_name=None, timezone_id=None, local_date_offset_days=None, **overrides
):
    """Full registration payload with the three required profile fields."""
    payload = {
        "display_name": display_name or TEST_DEFAULTS["DISPLAY_NAME"],
        "timezone_id": timezone_id or TEST_DEFAULTS["TIMEZONE_UTC"],
        "local_date_offset_days": (
            TEST_DEFAULTS["OFFSET_UTC"]
            if local_date_offset_days is None
            else local_date_offset_days
        ),
    }
    payload.update(overrides)
    return payload


def learner_patch_payload(expected_learner_version, **overrides):
    """Profile-edit payload; the version guard is required."""
    payload = {"expected_learner_version": expected_learner_version}
    payload.update(overrides)
    return payload


def course_unit_payload(
    unit_index=None, title=None, cefr_band=None, unlock_index=None,
    total_nodes=None, **overrides,
):
    payload = {}
    if unit_index is not None:
        payload["unit_index"] = unit_index
    if title is not None:
        payload["title"] = title
    if cefr_band is not None:
        payload["cefr_band"] = cefr_band
    if unlock_index is not None:
        payload["unlock_index"] = unlock_index
    if total_nodes is not None:
        payload["total_nodes"] = total_nodes
    payload.update(overrides)
    return payload


def course_unit_default_payload(**overrides):
    defaults = {
        "unit_index": 1,
        "title": TEST_DEFAULTS["UNIT_TITLE"],
        "cefr_band": "A1",
        "unlock_index": 0,
        "total_nodes": 1,
    }
    defaults.update(overrides)
    return defaults


def lesson_node_payload(node_index=None, **overrides):
    payload = {}
    if node_index is not None:
        payload["node_index"] = node_index
    payload.update(overrides)
    return payload


def practice_payload(
    learner_id=None, recorded_at=None, response_ms=None, correct=None, **overrides
):
    payload = {}
    if learner_id is not None:
        payload["learner_id"] = learner_id
    if recorded_at is not None:
        payload["recorded_at"] = recorded_at
    if response_ms is not None:
        payload["response_ms"] = response_ms
    if correct is not None:
        payload["correct"] = correct
    payload.update(overrides)
    return payload


def review_payload(learner_id, expected_node_version, **overrides):
    payload = {
        "learner_id": learner_id,
        "expected_node_version": expected_node_version,
    }
    payload.update(overrides)
    return payload


def repair_payload(expected_streak_version, **overrides):
    payload = {"expected_streak_version": expected_streak_version}
    payload.update(overrides)
    return payload


def subscription_create_payload(
    learner_id, plan_code, seats_total=None, auto_renew=True, **overrides
):
    payload = {
        "learner_id": learner_id,
        "plan_code": plan_code,
        "seats_total": 1 if seats_total is None else seats_total,
        "auto_renew": auto_renew,
    }
    payload.update(overrides)
    return payload


def subscription_update_payload(expected_subscription_version, **overrides):
    payload = {"expected_subscription_version": expected_subscription_version}
    payload.update(overrides)
    return payload


def placement_test_payload(
    learner_id, course_id, administered_at, total_items, expected_learner_version,
    **overrides,
):
    payload = {
        "learner_id": learner_id,
        "course_id": course_id,
        "administered_at": administered_at,
        "total_items": total_items,
        "expected_learner_version": expected_learner_version,
    }
    payload.update(overrides)
    return payload


def placement_action_payload(action, **overrides):
    payload = {"action": action}
    payload.update(overrides)
    return payload


def league_payload(tier, week_start, **overrides):
    payload = {"tier": tier, "week_start": week_start}
    payload.update(overrides)
    return payload


def league_action_payload(action, **overrides):
    payload = {"action": action}
    payload.update(overrides)
    return payload


def certification_exam_payload(
    learner_id, product_code, proctor_user_id, proctor_window_hours,
    expected_learner_version, **overrides,
):
    payload = {
        "learner_id": learner_id,
        "product_code": product_code,
        "proctor_user_id": proctor_user_id,
        "proctor_window_hours": proctor_window_hours,
        "expected_learner_version": expected_learner_version,
    }
    payload.update(overrides)
    return payload


def exam_action_payload(action, **overrides):
    payload = {"action": action}
    payload.update(overrides)
    return payload


def score_report_payload(institution_name, institution_learner_code, **overrides):
    payload = {
        "institution_name": institution_name,
        "institution_learner_code": institution_learner_code,
    }
    payload.update(overrides)
    return payload


def engagement_offer_payload(learner_id, milestone_code, **overrides):
    payload = {"learner_id": learner_id, "milestone_code": milestone_code}
    payload.update(overrides)
    return payload