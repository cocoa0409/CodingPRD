"""Blocking a message: five links from one moderation decision."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_instant,
    create_chat_payload,
    live_show_scenario,
    make_moderator_headers,
    make_viewer_headers,
    moderate,
    read_show,
    read_viewer,
    set_clock,
    submit_chat,
    submit_question,
    validate_error,
    validate_paginated,
    validate_success,
)

MODERATOR_HEADERS = make_moderator_headers()


def _viewer_on_one_strike():
    """A live show where one viewer has two chats, a queued question and one strike."""
    scenario = live_show_scenario(activate=True)
    viewer_id = scenario.viewer_id
    first_chat = submit_chat(scenario.show_id, viewer_id, body="buy from my link instead")
    second_chat = submit_chat(scenario.show_id, viewer_id, body="buy from my link instead again")
    question = submit_question(scenario.show_id, viewer_id, body="Is the sash included?")
    moderate(question["id"], "APPROVE")
    moderate(first_chat["id"], "BLOCK", blocked_reason="OFF_PLATFORM_SOLICITATION")
    set_clock("2026-08-10T18:15:00Z")
    return scenario, first_chat, second_chat, question


def _read_interaction(interaction_id):
    return validate_success(api_client.get_interaction(interaction_id, MODERATOR_HEADERS))


def _interaction_count(show_id):
    data, _meta = validate_paginated(
        api_client.list_interactions(MODERATOR_HEADERS, params={"show_id": show_id, "limit": 100})
    )
    return len(data)


def test_a_single_block_records_a_strike_without_muting():
    """One blocked message counts a strike but leaves the shopper able to post.

    The PRD: a block increments "the strike_count of the viewer named by that
    interaction's viewer_id", and only "a strike_count that has now reached two or
    more flips that viewer's chat_status from ACTIVE to MUTED".

    Design: Difficulty/transitive_cascade/chat_block_strike_mute_withdraw_cascade
    """
    scenario, first_chat, second_chat, question = _viewer_on_one_strike()

    viewer = read_viewer(scenario.viewer_id)
    assert viewer["strike_count"] == 1
    assert viewer["chat_status"] == "ACTIVE"
    assert viewer["muted_until"] is None
    assert read_show(scenario.show_id)["pending_question_count"] == 1


def test_the_second_block_reaches_the_threshold_and_mutes_the_shopper_for_a_quarter_hour():
    """The second strike flips the shopper to muted until fifteen minutes later.

    The PRD: reaching two or more strikes "flips that viewer's chat_status from
    ACTIVE to MUTED and sets muted_until to the logical instant plus a quarter of an
    hour, meaning 15 minutes."

    Design: Difficulty/transitive_cascade/chat_block_strike_mute_withdraw_cascade
    """
    scenario, first_chat, second_chat, question = _viewer_on_one_strike()

    moderate(second_chat["id"], "BLOCK", blocked_reason="OFF_PLATFORM_SOLICITATION")

    blocked = _read_interaction(second_chat["id"])
    assert blocked["state"] == "BLOCKED"
    assert blocked["blocked_reason"] == "OFF_PLATFORM_SOLICITATION"
    assert_instant(blocked["moderated_at"], "2026-08-10T18:15:00Z", "moderated_at")

    viewer = read_viewer(scenario.viewer_id)
    assert viewer["strike_count"] == 2
    assert viewer["chat_status"] == "MUTED"
    assert_instant(viewer["muted_until"], "2026-08-10T18:30:00Z", "muted_until")


def test_the_mute_withdraws_the_shoppers_queued_question():
    """A muted shopper's whole pipeline is cleared, not merely their next message.

    The PRD: "every other interaction belonging to that viewer whose state is
    PENDING_MODERATION, QUEUED, ROUTED or DEFERRED is set to WITHDRAWN, each with
    its own version incremented — a muted viewer's whole pipeline is cleared, not
    merely their next message."

    Design: Difficulty/transitive_cascade/chat_block_strike_mute_withdraw_cascade
    """
    scenario, first_chat, second_chat, question = _viewer_on_one_strike()

    moderate(second_chat["id"], "BLOCK", blocked_reason="OFF_PLATFORM_SOLICITATION")

    assert _read_interaction(question["id"])["state"] == "WITHDRAWN"


def test_the_withdrawal_recomputes_the_shows_pending_question_count():
    """With the only queued question withdrawn the host's queue is empty.

    The PRD: "Show.pending_question_count is always the count of that show's
    interactions whose kind is QUESTION and whose state is QUEUED, ROUTED or
    DEFERRED."

    Design: Difficulty/transitive_cascade/chat_block_strike_mute_withdraw_cascade
    """
    scenario, first_chat, second_chat, question = _viewer_on_one_strike()

    moderate(second_chat["id"], "BLOCK", blocked_reason="OFF_PLATFORM_SOLICITATION")

    assert read_show(scenario.show_id)["pending_question_count"] == 0


def test_a_muted_shopper_is_refused_and_leaves_no_interaction_behind():
    """The follow-up message is rejected and no row is written for it.

    The PRD: "A viewer whose chat_status is MUTED and whose muted_until is strictly
    later than the logical instant is refused with ERR_VIEWER_MUTED."

    Design: Difficulty/transitive_cascade/chat_block_strike_mute_withdraw_cascade
    """
    scenario, first_chat, second_chat, question = _viewer_on_one_strike()

    moderate(second_chat["id"], "BLOCK", blocked_reason="OFF_PLATFORM_SOLICITATION")
    before = _interaction_count(scenario.show_id)

    response = api_client.create_interaction(
        create_chat_payload(scenario.show_id, body="let me back in"),
        make_viewer_headers(scenario.viewer_id),
    )
    validate_error(response, ApiErrorId.ERR_VIEWER_MUTED.value)

    assert _interaction_count(scenario.show_id) == before


def test_the_already_blocked_message_is_left_where_it_was():
    """The earlier decision is terminal and the second block does not revisit it.

    The PRD: "Only interactions in PENDING_MODERATION may be moderated — an
    interaction already APPROVED, already BLOCKED, already QUEUED, or in any other
    state is ERR_INVALID_INTERACTION_STATE".

    Design: Difficulty/transitive_cascade/chat_block_strike_mute_withdraw_cascade
    """
    scenario, first_chat, second_chat, question = _viewer_on_one_strike()

    moderate(second_chat["id"], "BLOCK", blocked_reason="OFF_PLATFORM_SOLICITATION")

    assert _read_interaction(first_chat["id"])["state"] == "BLOCKED"
