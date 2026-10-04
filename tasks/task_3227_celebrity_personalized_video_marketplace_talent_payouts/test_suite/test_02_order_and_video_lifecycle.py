"""Order and video lifecycle: the re-record cycle, moderation fork, caps,
and terminal lockdowns."""

from test_helpers import (
    ApiErrorId,
    create_accepted_order,
    create_active_talent,
    create_confirmed_order,
    create_delivered_order,
    create_screened_order,
    deliver_video,
    get_success_data,
    make_admin_headers,
    make_buyer_headers,
    make_moderator_headers,
    make_talent_headers,
    moderate_video_clear,
    open_dispute,
    read_buyer,
    read_order,
    register_buyer,
    register_talent,
    submit_tax_document,
    validate_error,
    validate_success,
)


def test_rerecord_cycle_reenters_delivered(api):
    """PRD §3.4: "A successful request creates a `ReRecordRequest` in `OPEN`
    status, increments `re_record_count`, and moves the order from
    `DELIVERED` to `RE_RECORD_REQUESTED`; the original `delivery_deadline` is
    not extended."
    PRD §3.4: "The upload also moves the order to `DELIVERED`, stamps
    `delivered_at`, sets (or resets) `auto_confirm_at` to the current logical
    time plus 72 hours, and closes any `OPEN` re-record request on the
    order."

    Design: Difficulty/non_linear_state_machine/order_delivery_rerecord_cycle
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    response = api.request_rerecord(
        order["id"], "mispronounced the name", headers=make_buyer_headers(buyer["id"])
    )
    rr = validate_success(response)
    assert rr["status"] == "OPEN"
    after_rr = read_order(api, order["id"])
    assert after_rr["status"] == "RE_RECORD_REQUESTED"
    assert after_rr["re_record_count"] == 1

    video2 = deliver_video(api, talent, after_rr)
    assert video2["version_no"] == 2, (
        "the re-record delivery must carry version_no 2, got {0}".format(
            video2["version_no"]
        )
    )
    after_redelivery = read_order(api, order["id"])
    assert after_redelivery["status"] == "DELIVERED", (
        "the cycle re-enters DELIVERED, not a terminal state"
    )


def test_second_buyer_rerecord_is_within_cap(api):
    """PRD §3.4: "The request requires the logical time to be strictly before
    `auto_confirm_at` (otherwise `ERR_BUYER_WINDOW_CLOSED`, HTTP 409),
    requires that no dispute is open on the order, and requires
    `re_record_count` to be below the hard cap of 2 — a third buyer-initiated
    request is rejected with `ERR_RERECORD_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/non_linear_state_machine/order_delivery_rerecord_cycle
    """
    talent = create_active_talent(api, rates_overrides={"turnaround_hours": 336})
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")
    buyer_h = make_buyer_headers(buyer["id"])

    # First re-record cycle.
    validate_success(api.request_rerecord(order["id"], "again please", headers=buyer_h))
    video2 = deliver_video(api, talent, read_order(api, order["id"]))
    moderate_video_clear(api, video2)

    # Second buyer-initiated re-record: count 1 -> 2, still below the cap.
    response = api.request_rerecord(order["id"], "one more", headers=buyer_h)
    rr = validate_success(response)
    assert rr["status"] == "OPEN"
    current = read_order(api, order["id"])
    assert current["status"] == "RE_RECORD_REQUESTED"
    assert current["re_record_count"] == 2


def test_third_buyer_rerecord_rejected_at_cap(api):
    """PRD §3.4: "The request requires the logical time to be strictly before
    `auto_confirm_at` (otherwise `ERR_BUYER_WINDOW_CLOSED`, HTTP 409),
    requires that no dispute is open on the order, and requires
    `re_record_count` to be below the hard cap of 2 — a third buyer-initiated
    request is rejected with `ERR_RERECORD_LIMIT_REACHED` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/rerecord_zero_count_vs_cap
    """
    talent = create_active_talent(api, rates_overrides={"turnaround_hours": 336})
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")
    buyer_h = make_buyer_headers(buyer["id"])

    for notes in ("again please", "one more"):
        validate_success(api.request_rerecord(order["id"], notes, headers=buyer_h))
        video = deliver_video(api, talent, read_order(api, order["id"]))
        moderate_video_clear(api, video)

    current = read_order(api, order["id"])
    assert current["status"] == "DELIVERED"
    assert current["re_record_count"] == 2

    response = api.request_rerecord(order["id"], "third redo", headers=buyer_h)
    validate_error(response, ApiErrorId.ERR_RERECORD_LIMIT_REACHED.value)
    assert read_order(api, order["id"])["re_record_count"] == 2


def test_rerecord_count_zero_allows_first_request(api):
    """PRD §3.4: "requires `re_record_count` to be below the hard cap of 2 —
    a third buyer-initiated request is rejected with
    `ERR_RERECORD_LIMIT_REACHED` (HTTP 409). A successful request creates a
    `ReRecordRequest` in `OPEN` status, increments `re_record_count`, and
    moves the order from `DELIVERED` to `RE_RECORD_REQUESTED`; the original
    `delivery_deadline` is not extended."

    Design: Difficulty/boundary_precision_check/rerecord_zero_count_vs_cap
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, _video = create_delivered_order(api, talent, buyer, moderate="CLEAR")
    assert order["re_record_count"] == 0

    response = api.request_rerecord(
        order["id"], "fix the greeting", headers=make_buyer_headers(buyer["id"])
    )
    validate_success(response)
    after = read_order(api, order["id"])
    assert after["re_record_count"] == 1
    assert after["status"] == "RE_RECORD_REQUESTED"


def test_moderation_flag_forks_delivered_order(api):
    """PRD §3.4: "Flagging requires a `flagged_reason` and moves the video to
    `FLAGGED`; when the flagged video's order is currently `DELIVERED`, the
    flag forks the order back into a re-record loop — the order transitions
    to `RE_RECORD_REQUESTED`, an `OPEN` re-record request is created whose
    `notes` are the `flagged_reason`, and the order's `re_record_count` is
    incremented."

    Design: Corner/state_machines/moderation_flag_forks_delivered_order_to_rerecord
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order, video = create_delivered_order(api, talent, buyer, moderate=None)

    response = api.moderate_video(
        video["id"], "FLAG", flagged_reason="off-brand remark", headers=make_admin_headers()
    )
    flagged = validate_success(response)
    assert flagged["moderation_status"] == "FLAGGED"
    assert flagged["flagged_reason"] == "off-brand remark"

    current = read_order(api, order["id"])
    assert current["status"] == "RE_RECORD_REQUESTED"
    assert current["re_record_count"] == 1

    rr_response = api.list_rerecord_requests(order["id"], headers=make_admin_headers())
    body = rr_response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["status"] == "OPEN"
    assert body["data"][0]["notes"] == "off-brand remark"


def test_video_terminal_lockdown_after_clear(api):
    """PRD §3.4: "Moderation runs on every upload before the buyer can act on
    it. A `PlatformAdmin` or `Moderator` reviews a `PENDING_REVIEW` video
    with a `decision` of `CLEAR` or `FLAG`. Clearing moves the video to
    `CLEARED`."

    Design: Corner/state_machines/video_double_moderation_rejected
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    _order, video = create_delivered_order(api, talent, buyer, moderate="CLEAR")

    response = api.moderate_video(
        video["id"], "FLAG", flagged_reason="late flag", headers=make_moderator_headers()
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


def test_new_entities_start_in_initial_states(api):
    """PRD §3.1: "A newly registered talent begins in `PENDING_VERIFICATION`
    status with `availability` set to `BOOKABLE`, all balances at zero, and
    `commission_tier` at `STANDARD`."
    PRD §3.1: "Each submission is stamped with `submitted_at` at the current
    logical time and begins in `SUBMITTED` status."

    Design: Corner/state_machines/initial_state_of_new_entities
    """
    talent = register_talent(api)
    assert talent["status"] == "PENDING_VERIFICATION"

    response = api.submit_tax_document(
        talent["id"],
        {"doc_type": "W8BEN", "tax_id_last4": "9007"},
        headers=make_talent_headers(talent["id"]),
    )
    doc = validate_success(response, expected_status=201)
    assert doc["status"] == "SUBMITTED"


def test_accept_from_screening_rejected(api):
    """PRD §3.3: "Accepting moves the order from `AWAITING_ACCEPTANCE` to
    `ACCEPTED`, requires the acting user to be the booked talent and the
    talent to currently be `ACTIVE`, and requires the current logical time to
    be strictly before `acceptance_deadline`; an acceptance at or after the
    deadline is rejected with `ERR_ACCEPTANCE_WINDOW_CLOSED` (HTTP 409)."
    PRD §2.8: "Fifth, the target resource's current state is checked against
    the transition being attempted (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/accept_from_screening_rejected_invalid_state
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    # Deliberately no screening attestation: the order stays in SCREENING.
    from test_helpers import create_order

    order = create_order(api, talent, buyer)
    assert order["status"] == "SCREENING"

    response = api.accept_order(order["id"], headers=make_talent_headers(talent["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_order(api, order["id"])["status"] == "SCREENING"


def test_declined_order_rejects_confirm_and_refunds_wallet(api):
    """PRD §3.3: "The talent may instead decline, which moves the order to
    `DECLINED` with a full wallet refund, exactly as a screening decline
    does."
    PRD §2.8: "Fifth, the target resource's current state is checked against
    the transition being attempted (`ERR_INVALID_STATE`, HTTP 409)."

    Design: Corner/state_machines/terminal_declined_order_rejects_confirm
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_screened_order(api, talent, buyer)
    response = api.decline_order(order["id"], headers=make_talent_headers(talent["id"]))
    declined = validate_success(response)
    assert declined["status"] == "DECLINED"

    response = api.confirm_order(order["id"], headers=make_buyer_headers(buyer["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    refreshed = read_buyer(api, buyer["id"])
    assert refreshed["wallet_credit_cents"] == 10000, (
        "the decline refunds the full gross to the buyer's wallet"
    )


def test_first_video_carries_version_no_one(api):
    """PRD §3.4: "Each upload creates a new `Video` whose `moderation_status`
    begins at `PENDING_REVIEW`, stamped with a monotonic per-order
    `version_no` — 1 for the first delivery and one higher than the previous
    video on each subsequent delivery."

    Design: Difficulty/non_linear_state_machine/order_delivery_rerecord_cycle
    """
    talent = create_active_talent(api)
    buyer = register_buyer(api)
    order = create_accepted_order(api, talent, buyer)
    video = deliver_video(api, talent, order)
    assert video["version_no"] == 1
    assert video["moderation_status"] == "PENDING_REVIEW"
    assert read_order(api, order["id"])["status"] == "DELIVERED"
