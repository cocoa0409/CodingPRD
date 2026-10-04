"""Overlap rules: signer double-booking and the one-UTF-per-channel rule.

Neither rule is about time arithmetic on a resource's own fields — one closes
adjacency on a half-open day window, the other scopes a conflict to the
(product line, channel) pair.
"""

from test_helpers import (
    ApiErrorId,
    approve_artwork_for_set,
    approve_card_set,
    build_packed_out_line,
    build_ready_to_ship_allocation,
    create_active_license,
    create_card_set_raw,
    create_line_ready,
    get_success_data,
    submit_card_set_for_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

SC = TEST_USERS["signing_coordinator_headers"]
PM = TEST_USERS["product_manager_headers"]
DIST = TEST_USERS["distribution_manager_headers"]

SAME_DAY = "2026-10-05T00:00:00Z"
SAME_DAY_LATER = "2026-10-05T12:00:00Z"
NEXT_DAY = "2026-10-06T00:00:00Z"


def _prepared_set(api, *, autograph_planned_count=200):
    license_obj = create_active_license(api)
    line = create_line_ready(api, license_obj["id"])
    card_set = create_card_set_raw(
        api,
        line["id"],
        set_tier="BASE",
        print_run_quantity=500,
        autograph_planned_count=autograph_planned_count,
    )
    approve_artwork_for_set(api, card_set["id"], license_obj["id"])
    card_set = submit_card_set_for_review(api, card_set["id"])
    card_set = get_success_data(approve_card_set(api, card_set["id"], card_set["version"]))
    return license_obj, line, card_set


def _book(api, license_id, card_set_id, scheduled_on, quantity, signer_name="Ken Griffey Jr",
          signer_kind="PLAYER_ASSOCIATION"):
    return get_success_data(
        api.create_signing_session(
            {
                "signer_name": signer_name,
                "signer_kind": signer_kind,
                "license_id": license_id,
                "scheduled_on": scheduled_on,
                "allocation_lines": [
                    {
                        "card_set_id": card_set_id,
                        "player_id": "kgj",
                        "quantity_delivered": quantity,
                    }
                ],
            },
            SC,
        )
    )


def test_the_first_session_prepares_and_the_same_day_clash_is_refused(api):
    """PRD §3.4: "no other session for the same `signer_name` whose status is
    `SCHEDULED`, `STOCK_PREPARED` or `STOCK_SHIPPED` may have a window that
    overlaps this one, where each session's window is the half-open day
    starting at its `scheduled_on` and ending one day later".

    Design: Difficulty/resource_temporal_overlap/two_signing_sessions_for_one_signer_on_the_same_day_collide
    """
    license_obj, line, card_set = _prepared_set(api)
    # The signer-availability rule is a "no other session" rule: it fires when
    # a second session for the same signer is prepared while the first is still
    # live in SCHEDULED/STOCK_PREPARED/STOCK_SHIPPED.  A session cannot be
    # prepared twice, so the collision is only reachable by booking the
    # companion session before the first is prepared.
    first = _book(api, license_obj["id"], card_set["id"], SAME_DAY, 100)
    prepared = validate_success(api.prepare_signing_stock(first["id"], SC))
    second = _book(api, license_obj["id"], card_set["id"], SAME_DAY_LATER, 50)

    assert prepared["status"] == "STOCK_PREPARED"

    resp = api.prepare_signing_stock(second["id"], SC)
    validate_error(resp, ApiErrorId.ERR_SIGNER_DOUBLE_BOOKED, expected_status=409)


def test_the_colliding_session_stays_scheduled_with_no_side_effect(api):
    """PRD §3.4: "An overlap is refused with `ERR_SIGNER_DOUBLE_BOOKED`, and
    this rule applies to independent signers exactly as it applies to
    association-bound ones."

    Design: Difficulty/resource_temporal_overlap/two_signing_sessions_for_one_signer_on_the_same_day_collide
    """
    license_obj, line, card_set = _prepared_set(api)
    # See test_the_first_session_prepares_and_the_same_day_clash_is_refused:
    # a session cannot be prepared while a same-signer session still overlaps
    # it, so the companion booking must already exist.
    first = _book(api, license_obj["id"], card_set["id"], SAME_DAY, 100)
    validate_success(api.prepare_signing_stock(first["id"], SC))
    second = _book(api, license_obj["id"], card_set["id"], SAME_DAY_LATER, 50)

    api.prepare_signing_stock(second["id"], SC)

    after = validate_success(api.get_signing_session(second["id"], SC))
    assert after["status"] == "SCHEDULED"
    assert after["version"] == second["version"], "the refused call wrote nothing"


def test_cancelling_the_holder_releases_the_later_booking(api):
    """PRD §3.4: "sessions already in `COMPLETED` or `CANCELLED` status are out
    of the way."

    PRD §3.4: "cancellation is available while the session is `SCHEDULED` and
    only then, its precondition being exactly that status (`ERR_INVALID_STATE`)".

    Design: Difficulty/resource_temporal_overlap/two_signing_sessions_for_one_signer_on_the_same_day_collide
    """
    license_obj, line, card_set = _prepared_set(api)
    first = _book(api, license_obj["id"], card_set["id"], SAME_DAY, 100)
    second = _book(api, license_obj["id"], card_set["id"], SAME_DAY_LATER, 50)

    cancelled = validate_success(api.cancel_signing_session(first["id"], SC))
    assert cancelled["status"] == "CANCELLED"

    released = validate_success(api.prepare_signing_stock(second["id"], SC))
    assert released["status"] == "STOCK_PREPARED"


def test_back_to_back_days_do_not_overlap(api):
    """PRD §3.4: "meaning a session on the same calendar day always overlaps,
    back-to-back days do not".

    Design: Difficulty/resource_temporal_overlap/two_signing_sessions_for_one_signer_on_the_same_day_collide
    """
    license_obj, line, card_set = _prepared_set(api)
    first = _book(api, license_obj["id"], card_set["id"], SAME_DAY, 100)
    second = _book(api, license_obj["id"], card_set["id"], NEXT_DAY, 50)
    assert validate_success(api.prepare_signing_stock(first["id"], SC))["status"] == "STOCK_PREPARED"
    assert validate_success(api.prepare_signing_stock(second["id"], SC))["status"] == "STOCK_PREPARED"


def test_preparing_stock_fails_twice_on_the_same_session(api):
    """PRD §3.4: "Passing both, the session moves to `STOCK_PREPARED` and its
    `version` advances."

    Design: Difficulty/resource_temporal_overlap/two_signing_sessions_for_one_signer_on_the_same_day_collide
    """
    license_obj, line, card_set = _prepared_set(api)
    session = _book(api, license_obj["id"], card_set["id"], SAME_DAY, 100)
    validate_success(api.prepare_signing_stock(session["id"], SC))
    resp = api.prepare_signing_stock(session["id"], SC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


def _utf_scenario(api):
    scenario = build_packed_out_line(api)
    return scenario["line"]


def _allocate(api, line_id, channel, cases, price=72000):
    return get_success_data(
        api.create_allocation(
            {
                "product_line_id": line_id,
                "channel": channel,
                "quantity_allocated": cases,
                "effective_price_cents": price,
            },
            DIST,
        )
    )


def test_the_first_hobby_allocation_can_be_marked_unable_to_fill(api):
    """PRD §3.8: "if another allocation for the same product line and the same
    channel is already in `UTF` status, the move is refused with
    `ERR_CHANNEL_ALREADY_UTF`."

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    line = _utf_scenario(api)
    first = _allocate(api, line["id"], "HOBBY", 10)
    marked = validate_success(api.mark_allocation_utf(first["id"], DIST))
    assert marked["status"] == "UTF"


def test_a_second_hobby_allocation_is_refused_the_utf_move(api):
    """PRD §3.8: "It also enforces one unable-to-fill allocation per channel
    per line".

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    line = _utf_scenario(api)
    first = _allocate(api, line["id"], "HOBBY", 10)
    second = _allocate(api, line["id"], "HOBBY", 5, price=66000)
    validate_success(api.mark_allocation_utf(first["id"], DIST))

    resp = api.mark_allocation_utf(second["id"], DIST)
    validate_error(resp, ApiErrorId.ERR_CHANNEL_ALREADY_UTF, expected_status=409)
    after = validate_success(api.get_allocation(second["id"], DIST))
    assert after["status"] == "RESERVED"


def test_a_second_channel_on_the_same_line_is_not_blocked(api):
    """PRD §3.8: "the move is refused with `ERR_CHANNEL_ALREADY_UTF`" — the
    scope is the channel, so a different channel on the same line is free.

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    line = _utf_scenario(api)
    hobby = _allocate(api, line["id"], "HOBBY", 10)
    mass = _allocate(api, line["id"], "MASS", 5, price=50000)
    direct = _allocate(api, line["id"], "DIRECT", 3, price=40000)
    validate_success(api.mark_allocation_utf(hobby["id"], DIST))
    assert validate_success(api.mark_allocation_utf(mass["id"], DIST))["status"] == "UTF"
    assert validate_success(api.mark_allocation_utf(direct["id"], DIST))["status"] == "UTF"


def test_the_two_hobby_rows_share_a_channel_but_not_an_id(api):
    """PRD §3.8: "Marking an allocation unable-to-fill is a deliberate
    admission that the channel cannot take the stock it reserved."

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    line = _utf_scenario(api)
    first = _allocate(api, line["id"], "HOBBY", 10)
    second = _allocate(api, line["id"], "HOBBY", 5, price=66000)
    assert first["id"] != second["id"]
    assert first["product_line_id"] == second["product_line_id"] == line["id"]
    assert first["channel"] == second["channel"] == "HOBBY"
    validate_success(api.mark_allocation_utf(first["id"], DIST))
    validate_error(
        api.mark_allocation_utf(second["id"], DIST), ApiErrorId.ERR_CHANNEL_ALREADY_UTF
    )


def test_marking_an_allocation_unable_to_fill_before_packout_is_refused(api):
    """PRD §3.8: "It requires the parent line to have already reached
    `PACKED_OUT`, and an attempt before that is refused with
    `ERR_PRODUCT_LINE_NOT_PACKED_OUT`."

    Design: Difficulty/resource_temporal_overlap/two_hobby_allocations_for_one_line_cannot_both_be_utf
    """
    scenario = build_ready_to_ship_allocation(
        api, pack_out_line=False, mark_utf=False
    )
    assert scenario["line"]["status"] == "IN_PRODUCTION"
    resp = api.mark_allocation_utf(scenario["allocation"]["id"], DIST)
    validate_error(resp, ApiErrorId.ERR_PRODUCT_LINE_NOT_PACKED_OUT, expected_status=409)