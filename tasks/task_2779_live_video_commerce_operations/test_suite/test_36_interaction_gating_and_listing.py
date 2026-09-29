"""Mute gating, one vote per viewer, and filtered windows over the interaction log."""

from test_helpers import (
    MODERATOR,
    ApiErrorId,
    api_client,
    assert_instant,
    assert_interaction,
    cast_vote,
    create_chat_payload,
    live_show_scenario,
    make_viewer_headers,
    moderate,
    open_poll_on,
    read_viewer,
    set_clock,
    submit_chat,
    submit_question,
    validate_error,
    validate_paginated,
    validate_success,
    vote_payload,
)


def _read_interaction(interaction_id):
    return validate_success(api_client.get_interaction(interaction_id, MODERATOR))


def test_a_muted_viewer_is_silenced_until_the_mute_lapses_and_speaks_again_on_the_minute():
    """A second blocked message mutes the viewer for a quarter of an hour; a message
    inside that window is refused, and one at the very instant the mute lapses is
    accepted because the viewer is auto-unmuted.

    PRD 3.8: "a `strike_count` that has now reached **two or more** flips that
    viewer's `chat_status` from `ACTIVE` to `MUTED` and sets `muted_until` to the
    logical instant plus a quarter of an hour, meaning 15 minutes." PRD 3.8: "An
    acting viewer must have `chat_status` of `ACTIVE`, or else a `muted_until` at or
    before the logical instant — in which case the mute has lapsed, the viewer is
    **auto-unmuted** back to `ACTIVE` on that first submission issued at or after
    `muted_until`, and the request proceeds. A viewer whose `chat_status` is `MUTED`
    and whose `muted_until` is strictly later than the logical instant is refused
    with `ERR_VIEWER_MUTED`."

    Design: Corner/validations/muted_viewer_blocked_then_auto_unmuted_at_the_mute_expiry
    """
    scenario = live_show_scenario()
    viewer_id = scenario.viewer_id

    first = submit_chat(scenario.show_id, viewer_id, body="first bad message")
    moderate(first["id"], "BLOCK", blocked_reason="ABUSE")
    after_one = read_viewer(viewer_id)
    assert after_one["strike_count"] == 1, "one block is one strike"
    assert after_one["chat_status"] == "ACTIVE", "one strike is below the mute threshold"

    second = submit_chat(scenario.show_id, viewer_id, body="second bad message")
    moderate(second["id"], "BLOCK", blocked_reason="ABUSE")
    muted = read_viewer(viewer_id)
    assert muted["strike_count"] == 2, "the second block is the second strike"
    assert muted["chat_status"] == "MUTED", "two strikes mute the viewer"
    assert_instant(muted["muted_until"], "2026-08-10T18:25:00Z", "muted_until")

    silenced = api_client.create_interaction(
        create_chat_payload(scenario.show_id, body="let me back in"),
        make_viewer_headers(viewer_id),
    )
    validate_error(silenced, ApiErrorId.ERR_VIEWER_MUTED)
    _, meta = validate_paginated(
        api_client.list_interactions(MODERATOR, {"viewer_id": viewer_id})
    )
    assert meta["total_count"] == 2, "the refused message created no interaction"

    set_clock("2026-08-10T18:25:00Z")
    back_on_air = submit_chat(scenario.show_id, viewer_id, body="back on air")
    assert_interaction(back_on_air)
    assert back_on_air["state"] == "PENDING_MODERATION", "the message is submitted for screening"
    assert back_on_air["viewer_id"] == viewer_id

    unmuted = read_viewer(viewer_id)
    assert unmuted["chat_status"] == "ACTIVE", (
        "a submission at the mute's own expiry auto-unmutes the viewer"
    )
    assert unmuted["strike_count"] == 2, "auto-unmuting forgives nothing"


def test_a_viewer_votes_at_most_once_on_a_poll():
    """A viewer who has already voted cannot vote again, not even on a different
    option, and the tallies do not move.

    PRD 3.8: "A viewer votes at most once per poll — if the acting `X-User-ID` is
    already present in `voted_viewer_ids` the vote is refused with
    `ERR_DUPLICATE_VOTE`." PRD 3.8 on the accepted vote: "A valid vote increments the
    `tallies` entry for that index and increments `vote_count`, appends the acting
    `X-User-ID` to `voted_viewer_ids`, and increments the interaction's `version`."

    Design: Corner/errors/second_vote_by_the_same_viewer_returns_duplicate_vote
    """
    scenario = live_show_scenario()
    poll = open_poll_on(scenario, body="Ivory or onyx?", options=["Ivory", "Onyx"])
    assert poll["state"] == "OPEN", "a poll opens straight into voting"

    voted = cast_vote(poll["id"], scenario.viewer_id, option_index=0)
    assert voted["vote_count"] == 1
    assert voted["tallies"] == {"0": 1, "1": 0}

    duplicate = api_client.cast_vote(
        poll["id"], vote_payload(option_index=1), make_viewer_headers(scenario.viewer_id)
    )
    validate_error(duplicate, ApiErrorId.ERR_DUPLICATE_VOTE)

    after = _read_interaction(poll["id"])
    assert after["state"] == "OPEN", "the poll is still taking other viewers' votes"
    assert after["vote_count"] == 1, "the refused vote was not counted"
    assert after["tallies"] == {"0": 1, "1": 0}, "and no tally moved"
    assert after["voted_viewer_ids"].count(scenario.viewer_id) == 1, (
        "the viewer appears in the roll of voters exactly once"
    )
    assert after["version"] == voted["version"], "the refused vote wrote nothing"


def test_the_interaction_log_pages_within_a_filter_rather_than_across_everything():
    """Filters narrow the population before the window is applied, so the reported
    total counts only the matching rows and the pages together return each once.

    PRD 2.3: "List responses populate four pagination fields inside `meta`: `limit`
    and `offset` echo the effective values used for the query, `total_count` is the
    number of rows matching the filters before the window is applied, and `has_more`
    is true when rows remain beyond the returned window." PRD 2.6 names the filters:
    "interactions by `show_id`, `viewer_id`, `host_id`, `kind` and `state`".

    Design: Corner/cross_cutting_complexity_layers/interaction_listing_combines_filtering_with_pagination
    """
    scenario = live_show_scenario(num_viewers=2)
    first_viewer = scenario.viewer_id
    second_viewer = scenario.viewers[1]["id"]

    approved_chat = submit_chat(scenario.show_id, first_viewer, body="chat one")
    moderate(approved_chat["id"], "APPROVE")
    blocked_chat = submit_chat(scenario.show_id, first_viewer, body="chat two")
    moderate(blocked_chat["id"], "BLOCK", blocked_reason="SPAM")
    other_chat = submit_chat(scenario.show_id, second_viewer, body="chat three")
    poll = open_poll_on(scenario, body="Ivory or onyx?", options=["Ivory", "Onyx"])
    question = submit_question(scenario.show_id, first_viewer, body="Does it shrink?")

    every_chat = {approved_chat["id"], blocked_chat["id"], other_chat["id"]}

    page_one, meta_one = validate_paginated(
        api_client.list_interactions(
            MODERATOR,
            {"show_id": scenario.show_id, "kind": "CHAT", "limit": 2, "offset": 0},
        )
    )
    assert meta_one["limit"] == 2 and meta_one["offset"] == 0, "the window echoes back"
    assert meta_one["total_count"] == 3, "three of the five interactions are chats"
    assert meta_one["has_more"] is True, "a third chat waits beyond the window"
    assert len(page_one) == 2

    page_two, meta_two = validate_paginated(
        api_client.list_interactions(
            MODERATOR,
            {"show_id": scenario.show_id, "kind": "CHAT", "limit": 2, "offset": 2},
        )
    )
    assert meta_two["total_count"] == 3, "the filtered population is unchanged by the window"
    assert meta_two["has_more"] is False, "nothing waits beyond the second page"
    assert len(page_two) == 1
    assert {row["id"] for row in page_one} | {row["id"] for row in page_two} == every_chat, (
        "the two pages together return every chat exactly once"
    )
    assert not {row["id"] for row in page_one} & {row["id"] for row in page_two}, (
        "and no chat appears on both pages"
    )

    mine, meta_mine = validate_paginated(
        api_client.list_interactions(
            MODERATOR,
            {"show_id": scenario.show_id, "viewer_id": first_viewer, "kind": "CHAT"},
        )
    )
    assert meta_mine["total_count"] == 2, "two of the three chats are the first viewer's"
    assert {row["id"] for row in mine} == {approved_chat["id"], blocked_chat["id"]}

    struck, meta_struck = validate_paginated(
        api_client.list_interactions(
            MODERATOR, {"show_id": scenario.show_id, "state": "BLOCKED"}
        )
    )
    assert meta_struck["total_count"] == 1, "exactly one message was blocked"
    assert struck[0]["id"] == blocked_chat["id"]
    assert struck[0]["blocked_reason"] == "SPAM"
    viewer = read_viewer(first_viewer)
    assert viewer["strike_count"] == 1, "the block laid one strike"
    assert viewer["chat_status"] == "ACTIVE", "one strike is below the mute threshold"

    hosted, meta_hosted = validate_paginated(
        api_client.list_interactions(
            MODERATOR, {"show_id": scenario.show_id, "host_id": scenario.host_id}
        )
    )
    assert meta_hosted["total_count"] == 1, (
        "only the poll carries a host, so the unfiltered population of five never leaks"
    )
    assert hosted[0]["id"] == poll["id"]
    assert question["state"] == "PENDING_MODERATION", (
        "the question was never touched by any of these filters"
    )
