"""Format banned-list updates, rotation epochs, and the two different
sequence breaks behind the format-legality rule."""
from test_helpers import (
    TEST_USERS,
    api_client,
    create_event_application_payload,
    get_allocation,
    get_application,
    get_distribution,
    get_format,
    make_store_organizer_headers,
    pass_distribution,
    propose_distribution,
    set_clock,
    setup_application,
    setup_release_context,
    transition_payload,
    validate_error,
)


def test_banning_a_card_denies_the_application_and_closes_its_pool(api):
    """PRD §3.8: "What such an update does do is deny every approved event
    application that cites the format, since the legality of the format has
    changed underneath an event that was already sanctioned — and each of those
    denied applications has its still-open prize pool closed."
    PRD §3.5: "It moves to `CLOSED` when the format the event cited takes an
    update that denies the parent application, or when the cited set release is
    retired; closing a pool voids every distribution that had passed under it and
    re-derives the restored total so the invariant returns to the figure it held
    before the close."

    Design: Difficulty/transitive_cascade/ban_list_denial_three_hop_cascade
    """
    store, _set_release, fmt, application, allocation = setup_application(
        tier="QUALIFIER"
    )
    distribution = propose_distribution(
        allocation["id"], store["id"], quantity=30, recipient_ref="PLAYER-31"
    )
    pass_distribution(distribution["id"])
    assert get_allocation(allocation["id"])["remaining_tp"] == 18

    bans = api_client.transition_format(
        fmt["id"],
        transition_payload("BAN_CARD", card_ref="TST-118", list_kind="BANNED"),
        TEST_USERS["ops_admin_headers"],
    )
    bans.raise_for_status()

    assert "TST-118" in get_format(fmt["id"])["banned_card_refs"]
    assert get_application(application["id"])["status"] == "DENIED"
    closed = get_allocation(allocation["id"])
    assert closed["status"] == "CLOSED"
    assert get_distribution(distribution["id"])["status"] == "VOIDED"
    assert closed["total_drawn_tp"] == 30
    assert closed["total_restored_tp"] == 30
    assert closed["remaining_tp"] == 48


def test_a_ban_list_update_is_a_self_loop_on_the_epoch_axis(api):
    """PRD §3.8: "Ban and restriction updates travel on the same operator action
    but behave quite differently, because a list update is a self-loop on the
    epoch axis rather than a step along it."
    PRD §2.6: "Appending to either list does not advance `current_epoch` — a list
    update is a self-loop on the epoch axis."

    Design: Difficulty/transitive_cascade/ban_list_denial_three_hop_cascade
    """
    store, _set_release, fmt, application, allocation = setup_application(
        tier="LOCAL"
    )

    before = get_format(fmt["id"])
    assert before["current_epoch"] == 0

    api_client.transition_format(
        fmt["id"],
        transition_payload("BAN_CARD", card_ref="TST-200", list_kind="BANNED"),
        TEST_USERS["ops_admin_headers"],
    ).raise_for_status()

    after = get_format(fmt["id"])
    assert after["current_epoch"] == 0, "a banned-list update never advances the epoch"
    assert "TST-200" in after["banned_card_refs"]
    assert get_application(application["id"])["status"] == "DENIED"


def test_format_legality_breaks_on_a_code_mismatch_and_on_a_rotation_lock(api):
    """PRD §3.3: "The supplied `format_code` must equal the `format_code` carried
    by the format named by `format_id`, and that format must not have rotated past
    the epoch in which the cited set release was legalized; a mismatch or a
    rotated-past format is rejected with `ERR_FORMAT_CODE_NOT_LEGAL`."
    PRD §3.8: "Rotation is an operator action available only on or after
    `2026-10-15T00:00:00Z` and only to a format that has a card pool to rotate,
    meaning at least one set release has already reached `RELEASED`."

    Design: Corner/validations/banning_a_card_code_and_rotating_use_different_sequence_breaks
    """
    store, set_release, fmt = setup_release_context()

    mismatch = api_client.create_event_application(
        create_event_application_payload(
            store["id"], set_release["id"], fmt["id"],
            format_code="WILDCARD", tier="LOCAL",
            scheduled_date="2026-09-27T18:00:00Z", expected_headcount=12,
        ),
        make_store_organizer_headers(store["id"]),
    )
    validate_error(
        mismatch, "ERR_FORMAT_CODE_NOT_LEGAL", expected_status=422
    )

    early_rotation = api_client.transition_format(
        fmt["id"], transition_payload("ROTATE"), TEST_USERS["ops_admin_headers"]
    )
    validate_error(early_rotation, "ERR_INVALID_STATE", expected_status=409)
    assert get_format(fmt["id"])["current_epoch"] == 0

    set_clock("2026-10-16T00:00:00Z")
    api_client.transition_format(
        fmt["id"], transition_payload("ROTATE"), TEST_USERS["ops_admin_headers"]
    ).raise_for_status()
    assert get_format(fmt["id"])["current_epoch"] == 1