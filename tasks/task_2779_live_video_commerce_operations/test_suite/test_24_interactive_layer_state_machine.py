"""Chat, questions and polls: where each kind starts and how their loops close."""

from test_helpers import (
    MODERATOR,
    ApiErrorId,
    assert_interaction,
    build_scenario,
    cast_vote,
    create_chat_payload,
    create_poll_payload,
    host_action_payload,
    make_host_headers,
    make_viewer_headers,
    moderate,
    open_poll,
    route_question,
    submit_question,
    vote_payload,
    validate_error,
    validate_success,
)


def _live_show(num_viewers=1):
    """A LIVE show at 18:10Z with registered shoppers and no flash pricing."""
    return build_scenario(num_viewers=num_viewers, offers=[], take_live=True)


def test_a_hosts_poll_opens_immediately_with_a_zero_filled_tally_map(api):
    """A poll needs no moderation: the presenter's prompt is live the moment it is
    posted, with one zero count per option and nobody having voted yet.

    PRD 3.8: "A `Host` submits a `POLL`, supplying the `show_id`, the poll prompt as
    `body`, and an `options` array of between two and four option labels; the server
    takes `host_id` from `X-User-ID`, leaves `viewer_id` null, initialises `tallies`
    to a map from each option's index — rendered as a string — to a count of zero,
    initialises `voted_viewer_ids` to an empty list and `vote_count` to 0, and places
    the poll directly in `OPEN`."

    Design: Corner/state_machines/interaction_initial_state_differs_by_kind
    """
    scenario = _live_show()

    poll = validate_success(
        api.create_interaction(
            create_poll_payload(
                scenario.show_id, body="Pick a colour", options=["Ivory", "Onyx"]
            ),
            make_host_headers(scenario.host_id),
        ),
        201,
    )

    assert_interaction(poll)
    assert poll["kind"] == "POLL"
    assert poll["state"] == "OPEN", "a poll is live without moderation"
    assert poll["host_id"] == scenario.host_id
    assert poll["viewer_id"] is None
    assert poll["show_id"] == scenario.show_id
    assert poll["vote_count"] == 0
    assert poll["tallies"] == {"0": 0, "1": 0}, "one zero count per option, keyed as text"
    assert poll["voted_viewer_ids"] == []


def test_a_viewers_chat_waits_for_moderation_on_the_same_live_show(api):
    """The same submission operation places a shopper's message in the moderation
    queue rather than on air, and the message belongs to the shopper who sent it.

    PRD 3.8: "A `Viewer` submits a `CHAT` or a `QUESTION`, supplying the `show_id`
    and the `body` text; the server takes `viewer_id` from `X-User-ID`, leaves
    `host_id` null, and places the interaction in `PENDING_MODERATION`."

    Design: Corner/state_machines/interaction_initial_state_differs_by_kind
    """
    scenario = _live_show()

    chat = validate_success(
        api.create_interaction(
            create_chat_payload(scenario.show_id, body="Loving this robe"),
            make_viewer_headers(scenario.viewer_id),
        ),
        201,
    )

    assert_interaction(chat)
    assert chat["kind"] == "CHAT"
    assert chat["state"] == "PENDING_MODERATION", "a shopper's message is screened first"
    assert chat["viewer_id"] == scenario.viewer_id
    assert chat["host_id"] is None
    assert chat["show_id"] == scenario.show_id


def test_closing_a_poll_freezes_the_tally_taken_before_the_close(api):
    """The presenter closing a poll takes a snapshot: the vote already cast is kept
    exactly as counted.

    PRD 3.8: "Closing moves the poll `OPEN → CLOSED`, freezes `tallies` and
    `vote_count`, and increments `version`."
    PRD 3.8: "A valid vote increments the `tallies` entry for that index and
    increments `vote_count`, appends the acting `X-User-ID` to `voted_viewer_ids`,
    and increments the interaction's `version`."

    Design: Corner/state_machines/poll_close_freezes_tallies_and_rejects_later_votes
    """
    scenario = _live_show(num_viewers=2)
    poll = open_poll(
        scenario.show_id,
        scenario.host_id,
        body="Pick a colour",
        options=["Ivory", "Onyx"],
    )
    cast_vote(poll["id"], scenario.viewers[0]["id"], option_index=0)

    closed = validate_success(
        api.host_action_interaction(
            poll["id"],
            host_action_payload("CLOSE_POLL"),
            make_host_headers(scenario.host_id),
        )
    )

    assert closed["state"] == "CLOSED"
    assert closed["vote_count"] == 1
    assert closed["tallies"] == {"0": 1, "1": 0}, "the tally is frozen as counted"
    assert closed["voted_viewer_ids"] == [scenario.viewers[0]["id"]]


def test_a_vote_arriving_after_the_close_is_refused_and_changes_nothing(api):
    """Once the poll is closed a late shopper cannot slip a vote in, and the frozen
    tally is not disturbed by the attempt.

    PRD 3.8: "Votes are accepted only while the poll is `OPEN`: a vote against a
    `CLOSED` poll, or against an interaction whose `kind` is not `POLL`, is
    `ERR_POLL_NOT_OPEN`."
    PRD 3.8: "Closing moves the poll `OPEN → CLOSED`, freezes `tallies` and
    `vote_count`, and increments `version`."

    Design: Corner/state_machines/poll_close_freezes_tallies_and_rejects_later_votes
    """
    scenario = _live_show(num_viewers=2)
    poll = open_poll(
        scenario.show_id,
        scenario.host_id,
        body="Pick a colour",
        options=["Ivory", "Onyx"],
    )
    cast_vote(poll["id"], scenario.viewers[0]["id"], option_index=0)
    closed = validate_success(
        api.host_action_interaction(
            poll["id"],
            host_action_payload("CLOSE_POLL"),
            make_host_headers(scenario.host_id),
        )
    )

    validate_error(
        api.cast_vote(
            poll["id"],
            vote_payload(1),
            make_viewer_headers(scenario.viewers[1]["id"]),
        ),
        ApiErrorId.ERR_POLL_NOT_OPEN,
    )

    after = validate_success(api.get_interaction(poll["id"], MODERATOR))
    assert after["state"] == "CLOSED"
    assert after["vote_count"] == 1, "the rejected vote counts for nothing"
    assert after["tallies"] == {"0": 1, "1": 0}
    assert after["version"] == closed["version"], "a refused vote bumps nothing"


def _routed_question(scenario):
    """A shopper's question approved into the queue and handed to the presenter."""
    question = submit_question(scenario.show_id, scenario.viewer_id)
    question = moderate(question["id"], "APPROVE")
    assert question["state"] == "QUEUED", "an approved question forks into the queue"
    return route_question(question["id"])


def test_each_deferral_sends_the_question_straight_back_to_the_queue(api):
    """Deferring is a single round trip: the presenter postpones the question and it
    is already back in the queue when the response arrives, two mutations later.

    PRD 3.8: "An accepted deferral moves the question `ROUTED → DEFERRED`,
    increments `defer_count` by one and increments `version`; then, unconditionally
    and in the same request, the question moves `DEFERRED → QUEUED` with `routed_at`
    cleared to null and `version` incremented a second time."
    PRD 3.8: "A single deferral request therefore returns a question in state
    `QUEUED`, with `defer_count` one higher than before and `version` **two** higher
    than before."

    Design: Corner/state_machines/question_deferral_loop_terminates_at_the_declared_limit
    """
    scenario = _live_show()
    routed = _routed_question(scenario)
    assert routed["state"] == "ROUTED"
    assert routed["defer_count"] == 0

    host_headers = make_host_headers(scenario.host_id)
    first = validate_success(
        api.host_action_interaction(routed["id"], host_action_payload("DEFER"), host_headers)
    )
    assert first["state"] == "QUEUED", "the question lands back in the queue"
    assert first["defer_count"] == 1
    assert first["routed_at"] is None
    assert first["version"] == routed["version"] + 2, "one request, two transitions"

    validate_success(api.route_interaction(routed["id"], MODERATOR))
    second = validate_success(
        api.host_action_interaction(routed["id"], host_action_payload("DEFER"), host_headers)
    )
    assert second["state"] == "QUEUED"
    assert second["defer_count"] == 2


def test_the_third_deferral_is_refused_and_the_question_must_be_answered(api):
    """A question may be postponed twice; the third attempt is refused and leaves the
    question with the presenter, who can still answer it.

    PRD 3.8: "The question must be `ROUTED`, and its `defer_count` must be
    **strictly less than two**; a deferral attempted when `defer_count` already
    equals 2 is refused with `ERR_DEFERRAL_LIMIT_REACHED`, the question stays
    `ROUTED`, and the host's only remaining option is to answer it."
    PRD 3.8: "Answering requires the question to be `ROUTED`, moves it `ROUTED →
    ANSWERED`, records the supplied `answer_body`, stamps `answered_at` with the
    logical instant, decrements the show's `pending_question_count` by one, and
    increments `version`."

    Design: Corner/state_machines/question_deferral_loop_terminates_at_the_declared_limit
    """
    scenario = _live_show()
    routed = _routed_question(scenario)
    host_headers = make_host_headers(scenario.host_id)

    for _ in range(2):
        validate_success(
            api.host_action_interaction(
                routed["id"], host_action_payload("DEFER"), host_headers
            )
        )
        validate_success(api.route_interaction(routed["id"], MODERATOR))

    validate_error(
        api.host_action_interaction(
            routed["id"], host_action_payload("DEFER"), host_headers
        ),
        ApiErrorId.ERR_DEFERRAL_LIMIT_REACHED,
    )

    still_routed = validate_success(api.get_interaction(routed["id"], MODERATOR))
    assert still_routed["state"] == "ROUTED", "the refused deferral leaves it with the host"
    assert still_routed["defer_count"] == 2

    answered = validate_success(
        api.host_action_interaction(
            routed["id"],
            host_action_payload("ANSWER", answer_body="It does not shrink"),
            host_headers,
        )
    )
    assert answered["state"] == "ANSWERED"
    assert answered["answer_body"] == "It does not shrink"
