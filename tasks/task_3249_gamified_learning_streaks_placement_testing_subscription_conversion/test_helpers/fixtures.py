"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (and therefore empties the
database) before every individual test.  Setup calls use the framework's lenient
``get_success_data`` so a broken prerequisite reports "Setup failed: <error_id>"
rather than a confusing assertion failure deep inside the test.

Learner calls that are ownership-gated always use ``make_learner_headers`` with
the learner's own id, never the shared learner constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    course_unit_default_payload, engagement_offer_payload,
    learner_registration_payload, lesson_node_payload, practice_payload,
    subscription_create_payload, subscription_update_payload,
)
from .test_users import TEST_USERS, make_learner_headers

ADMIN = TEST_USERS["admin_headers"]
PROCTOR = TEST_USERS["proctor_headers"]


# ── Tier 1: registration and clock ───────────────────────────────────────────

def register_learner(
    display_name=None, timezone_id=None, local_date_offset_days=None,
    program_tier=None,
):
    """Register a learner (Anonymous) and return the learner payload."""
    payload = learner_registration_payload(
        display_name=display_name,
        timezone_id=timezone_id,
        local_date_offset_days=local_date_offset_days,
    )
    if program_tier is not None:
        payload["program_tier"] = program_tier
    return get_success_data(api_client.create_learner(payload, None))


def register_learner_headers(
    display_name=None, timezone_id=None, local_date_offset_days=None,
    program_tier=None,
):
    """Register a learner and return ``(learner, headers)``."""
    learner = register_learner(
        display_name=display_name,
        timezone_id=timezone_id,
        local_date_offset_days=local_date_offset_days,
        program_tier=program_tier,
    )
    return learner, make_learner_headers(learner["id"])


def set_clock(to_iso8601):
    """Set the logical clock.  Returns nothing; the call is its own effect."""
    get_success_data(api_client.set_clock(to_iso8601, ADMIN))


def fire_event(event_type):
    """Fire a system sweep."""
    get_success_data(api_client.fire_event(event_type, ADMIN))


def grant_gems(learner_id, gems):
    """Support grant: adds to the learner's gem balance."""
    return get_success_data(api_client.inject_gems(learner_id, gems, ADMIN))


def record_payment_outcome(subscription_id, outcome):
    return get_success_data(
        api_client.inject_payment_outcome(subscription_id, outcome, ADMIN)
    )


def get_learner(learner_id):
    return get_success_data(
        api_client.get_learner(learner_id, make_learner_headers(learner_id))
    )


# ── Tier 2: course tree construction ─────────────────────────────────────────

def create_course_unit(
    unit_index=1, title=None, cefr_band="A1", unlock_index=0, total_nodes=1,
):
    return get_success_data(api_client.create_course_unit(
        course_unit_default_payload(
            unit_index=unit_index,
            title=title or TEST_DEFAULTS["UNIT_TITLE"],
            cefr_band=cefr_band,
            unlock_index=unlock_index,
            total_nodes=total_nodes,
        ),
        ADMIN,
    ))


def append_lesson_node(unit_id, node_index, prerequisite_node_id=None):
    payload = lesson_node_payload(node_index=node_index)
    if prerequisite_node_id is not None:
        payload["prerequisite_node_id"] = prerequisite_node_id
    return get_success_data(
        api_client.create_lesson_node(unit_id, payload, ADMIN)
    )


def build_chain(unit_id, length):
    """Append ``length`` lesson nodes to ``unit_id``, each chained to the last.

    Returns the list of node payloads in node_index order.
    """
    nodes = []
    previous_id = None
    for index in range(1, length + 1):
        node = append_lesson_node(unit_id, index, previous_id)
        previous_id = node["id"]
        nodes.append(node)
    return nodes


def read_node(node_id, learner_id):
    return get_success_data(
        api_client.get_lesson_node(node_id, make_learner_headers(learner_id))
    )


def list_unit_nodes(unit_id, learner_id):
    data = get_success_data(
        api_client.list_unit_nodes(unit_id, make_learner_headers(learner_id))
    )
    return data


def list_streaks(learner_id):
    data = get_success_data(
        api_client.list_streak_states(
            make_learner_headers(learner_id), {"learner_id": learner_id}
        )
    )
    return data


def get_streak(learner_id):
    """The learner's single streak row."""
    return list_streaks(learner_id)[0]


def list_standings(learner_id, league_id):
    data = get_success_data(api_client.list_league_standings(
        make_learner_headers(learner_id),
        {"league_id": league_id, "learner_id": learner_id},
    ))
    return data


def practice(node_id, learner_id, recorded_at=None, response_ms=None, correct=None,
             is_placement_attempt=None, payload=None, headers=None):
    """Submit a practice attempt.

    Two call shapes are supported, matching the two forms the suite uses:

    * keyword form — ``practice(node_id, learner_id, recorded_at,
      response_ms=..., correct=...)``;
    * inline-body form — ``practice(node_id, body_dict, headers)``, used by the
      validation-ordering and boundary tests that construct the body (including
      deliberately malformed or extra fields) directly.

    ``learner_id`` may be ``None`` in the inline-body form; the request identity
    is then taken from the supplied headers.
    """
    if isinstance(learner_id, dict):
        body = learner_id
        request_headers = recorded_at
        return api_client.practice(node_id, body, request_headers)
    body = practice_payload(
        learner_id=learner_id, recorded_at=recorded_at,
        response_ms=response_ms, correct=correct,
    )
    if is_placement_attempt is not None:
        body["is_placement_attempt"] = is_placement_attempt
    return api_client.practice(
        node_id, body, headers or make_learner_headers(learner_id)
    )


def practice_ok(node_id, learner_id, recorded_at, response_ms=5000, correct=True):
    return get_success_data(
        practice(node_id, learner_id, recorded_at, response_ms, correct)
    )


def review(node_id, learner_id, expected_node_version):
    return api_client.review(
        node_id,
        {"learner_id": learner_id, "expected_node_version": expected_node_version},
        make_learner_headers(learner_id),
    )


def list_subscriptions(learner_id):
    return get_success_data(api_client.list_subscriptions(
        make_learner_headers(learner_id), {"learner_id": learner_id}
    ))


def get_free_subscription(learner_id):
    """The FREE subscription row minted at registration."""
    return list_subscriptions(learner_id)[0]


def subscribe(learner_id, plan_code, seats_total=1, auto_renew=True):
    return get_success_data(api_client.create_subscription(
        subscription_create_payload(
            learner_id=learner_id, plan_code=plan_code,
            seats_total=seats_total, auto_renew=auto_renew,
        ),
        make_learner_headers(learner_id),
    ))


def add_seat(subscription_id, owner_learner_id, member_learner_id,
             expected_subscription_version):
    return api_client.update_subscription(
        subscription_id,
        subscription_update_payload(
            expected_subscription_version,
            add_seat_learner_id=member_learner_id,
        ),
        make_learner_headers(owner_learner_id),
    )


def add_seat_ok(subscription_id, owner_learner_id, member_learner_id,
                expected_subscription_version):
    return get_success_data(add_seat(
        subscription_id, owner_learner_id, member_learner_id,
        expected_subscription_version,
    ))


def remove_seat(subscription_id, owner_learner_id, member_learner_id,
                expected_subscription_version):
    return api_client.update_subscription(
        subscription_id,
        subscription_update_payload(
            expected_subscription_version,
            remove_seat_learner_id=member_learner_id,
        ),
        make_learner_headers(owner_learner_id),
    )


def issue_offer(learner_id, milestone_code):
    return get_success_data(api_client.create_engagement_offer(
        engagement_offer_payload(learner_id, milestone_code), ADMIN
    ))


def open_league(tier, week_start, learner_id=None):
    payload = {"tier": tier, "week_start": week_start}
    headers = ADMIN
    if learner_id is not None:
        payload["learner_id"] = learner_id
        headers = make_learner_headers(learner_id)
    return get_success_data(api_client.create_league(payload, headers))


def settle_league(league_id):
    return get_success_data(api_client.update_league(
        league_id, {"action": "SETTLE"}, ADMIN
    ))


def join_league(league_id, learner_id):
    return api_client.update_league(
        league_id, {"action": "JOIN", "learner_id": learner_id}, ADMIN
    )