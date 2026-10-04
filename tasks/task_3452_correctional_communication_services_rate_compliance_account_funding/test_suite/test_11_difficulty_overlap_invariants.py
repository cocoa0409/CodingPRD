"""Difficulty coverage: resource temporal-overlap semantics (half-open
inmate overlap vs buffer-expanded facility capacity sweep) and the two
compensating conservation invariants (message charge/refund balance; video
booth-minutes budget) (PRD §2.10, §3.6, §3.7).
"""
from test_helpers import (
    ApiErrorId,
    book_inmate,
    cancel_session,
    confirm_session,
    create_and_confirm_session,
    create_message,
    create_session,
    deposit,
    get_account,
    get_ledger,
    get_success_data,
    get_video_availability,
    make_account_holder_headers,
    open_account,
    review_message,
    setup_active_facility,
    setup_funded_account,
    validate_error,
)


# ---------------------------------------------------------------------------
# Half-open inmate overlap: adjacency is allowed, interior overlap is not
# ---------------------------------------------------------------------------


def _half_open_env():
    """Facility (booths 5, daily limit 5) with a funded inmate account and
    one CONFIRMED session 10:00-10:30 on the target date."""
    env = setup_funded_account(
        deposit_amount=2525,
        facility_overrides={
            "video_booth_count": 5,
            "daily_session_limit_per_inmate": 5,
        },
    )
    first = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-16T10:00:00Z",
        scheduled_end="2026-09-16T10:30:00Z",
    )
    confirm_session(first["id"])
    return env


def test_back_to_back_sessions_are_not_an_overlap(api):
    """PRD §3.7: "First, the inmate must not already hold a confirmed session whose unbuffered, half-open interval overlaps this one — touching boundaries are allowed, so a session that ends exactly when another begins is not an overlap — otherwise `ERR_INMATE_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inmate_schedule_half_open_overlap_allows_back_to_back
    """
    env = _half_open_env()
    adjacent = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-16T10:30:00Z",
        scheduled_end="2026-09-16T11:00:00Z",
    )
    confirmed = confirm_session(adjacent["id"])
    assert confirmed["status"] == "CONFIRMED", (
        "10:30 == 10:30: half-open adjacency is not an overlap"
    )
    assert get_account(env["account"]["id"])["balance_cents"] == 1500


def test_interior_overlap_rejected_with_error(api, facility_staff_headers):
    """PRD §3.7: "First, the inmate must not already hold a confirmed session whose unbuffered, half-open interval overlaps this one — touching boundaries are allowed, so a session that ends exactly when another begins is not an overlap — otherwise `ERR_INMATE_SESSION_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/inmate_schedule_half_open_overlap_allows_back_to_back
    """
    env = _half_open_env()
    adjacent = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-16T10:30:00Z",
        scheduled_end="2026-09-16T11:00:00Z",
    )
    confirm_session(adjacent["id"])
    overlapping = create_session(
        env["facility"],
        env["inmate"],
        env["account"],
        as_staff=True,
        scheduled_start="2026-09-16T10:15:00Z",
        scheduled_end="2026-09-16T10:45:00Z",
    )

    resp = api.confirm_video_session(overlapping["id"], facility_staff_headers)
    validate_error(resp, ApiErrorId.ERR_INMATE_SESSION_OVERLAP)
    assert resp.status_code == 409

    reread = get_success_data(
        api.get_video_session(overlapping["id"], facility_staff_headers)
    )
    assert reread["status"] == "REQUESTED"
    assert get_account(env["account"]["id"])["balance_cents"] == 1500, (
        "exactly two 500-cent charges landed; the rejected confirm charged nothing"
    )


# ---------------------------------------------------------------------------
# Buffer-expanded facility capacity sweep
# ---------------------------------------------------------------------------


def _one_booth_env():
    """Facility with a single booth and a 10-minute turnover buffer; inmate A
    holds a CONFIRMED session 10:15-10:45 on the target date."""
    env = setup_active_facility(
        facility_overrides={
            "video_booth_count": 1,
            "daily_session_limit_per_inmate": 5,
        }
    )
    facility = env["facility"]
    inmate_a = book_inmate(facility["id"], full_name="Inmate Alpha")
    account_a = open_account(facility["id"], inmate_a["id"], owner_name="Fam A")
    deposit(account_a, 1025)
    inmate_b = book_inmate(facility["id"], full_name="Inmate Beta")
    account_b = open_account(facility["id"], inmate_b["id"], owner_name="Fam B")
    deposit(account_b, 1025)

    existing = create_session(
        facility,
        inmate_a,
        account_a,
        as_staff=True,
        scheduled_start="2026-09-17T10:15:00Z",
        scheduled_end="2026-09-17T10:45:00Z",
    )
    confirm_session(existing["id"])
    return env, inmate_b, account_b


def test_turnover_buffer_rejects_raw_disjoint_pairing(api, facility_staff_headers):
    """PRD §3.7: "Second, the buffered capacity sweep: every confirmed session of the facility is treated as occupying the half-open interval from `video_turnover_minutes` before its start to `video_turnover_minutes` after its end, and at no instant may more than `video_booth_count` of these buffered intervals — the new session included — cover the same moment, otherwise `ERR_FACILITY_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/facility_turnover_buffer_rejects_session_that_raw_intervals_would_allow
    """
    env, inmate_b, account_b = _one_booth_env()
    new_session = create_session(
        env["facility"],
        inmate_b,
        account_b,
        as_staff=True,
        scheduled_start="2026-09-17T10:50:00Z",
        scheduled_end="2026-09-17T11:20:00Z",
    )

    resp = api.confirm_video_session(new_session["id"], facility_staff_headers)
    validate_error(resp, ApiErrorId.ERR_FACILITY_CAPACITY_EXCEEDED)
    assert resp.status_code == 409, (
        "raw intervals [10:15,10:45) and [10:50,11:20) are disjoint, but the "
        "buffered [10:05,10:55) and [10:40,11:30) collide against 1 booth"
    )

    reread = get_success_data(
        api.get_video_session(new_session["id"], facility_staff_headers)
    )
    assert reread["status"] == "REQUESTED"
    assert get_account(account_b["id"])["balance_cents"] == 1000


def test_video_availability_counts_only_confirmed_minutes(api):
    """PRD §3.7: "For planning, the facility's video-availability view answers a `date` query with that `date`, the facility's `booth_count`, the `booked_minutes` already confirmed for that day, and the `bookable_minutes` remaining — computed as the booth count multiplied by the visiting window's length in minutes, minus the booked minutes — so that booked plus bookable always equals the full window budget."

    Design: Difficulty/resource_temporal_overlap/facility_turnover_buffer_rejects_session_that_raw_intervals_would_allow
    """
    env, inmate_b, account_b = _one_booth_env()
    create_session(
        env["facility"],
        inmate_b,
        account_b,
        as_staff=True,
        scheduled_start="2026-09-17T10:50:00Z",
        scheduled_end="2026-09-17T11:20:00Z",
    )  # stays REQUESTED — never confirmed

    avail = get_video_availability(env["facility"]["id"], "2026-09-17")
    assert avail["booth_count"] == 1
    assert avail["booked_minutes"] == 30, "only the confirmed 10:15-10:45 session"
    assert avail["bookable_minutes"] == 690
    assert avail["booked_minutes"] + avail["bookable_minutes"] == 1 * (1200 - 480)


# ---------------------------------------------------------------------------
# Compensating invariant: message charge/refund conserves the balance
# ---------------------------------------------------------------------------


def test_message_reject_restores_balance_exactly(api):
    """PRD §2.10: "For any message that is created and later rejected, the account's balance is identical before creation and after rejection: the message charge and its refund are equal-magnitude, opposite-sign ledger entries that net to zero over that message. The conserved quantity is the account balance."
    PRD §3.6: "A review with `decision` `REJECT` moves it to `REJECTED` and appends a `MESSAGE_REFUND` credit of exactly `price_cents` — an exact reversal, never more and never less."

    Design: Difficulty/compensating_invariant/message_charge_then_reject_refund_conserves_account_balance
    """
    env = setup_funded_account()
    account, inmate = env["account"], env["inmate"]
    balance_before = get_account(account["id"])["balance_cents"]
    assert balance_before == 1000

    message = create_message(account, inmate, "rejected letter")
    assert message["price_cents"] == 15
    rejected = review_message(
        message["id"], "REJECT", review_note="contraband keyword"
    )
    assert rejected["status"] == "REJECTED"

    assert get_account(account["id"])["balance_cents"] == balance_before, (
        "the charge-refund pair conserves the account balance exactly"
    )
    rows = get_ledger(account["id"])
    charges = [
        r
        for r in rows
        if r["type"] == "MESSAGE_CHARGE" and r["reference_id"] == message["id"]
    ]
    refunds = [
        r
        for r in rows
        if r["type"] == "MESSAGE_REFUND" and r["reference_id"] == message["id"]
    ]
    assert len(charges) == 1 and charges[0]["amount_cents"] == -15
    assert len(refunds) == 1 and refunds[0]["amount_cents"] == 15


def test_message_approve_keeps_charge_standing(api):
    """PRD §3.6: "A review with `decision` `APPROVE` moves the message to `DELIVERED`, and the charge stands. A review with `decision` `REJECT` moves it to `REJECTED` and appends a `MESSAGE_REFUND` credit of exactly `price_cents` — an exact reversal, never more and never less."

    Design: Difficulty/compensating_invariant/message_charge_then_reject_refund_conserves_account_balance
    """
    env = setup_funded_account()
    account, inmate = env["account"], env["inmate"]

    message = create_message(account, inmate, "approved letter")
    delivered = review_message(message["id"], "APPROVE")
    assert delivered["status"] == "DELIVERED"

    assert get_account(account["id"])["balance_cents"] == 985, (
        "control: without the compensating reject the 15-cent charge stands"
    )
    rows = get_ledger(account["id"])
    assert not any(r["type"] == "MESSAGE_REFUND" for r in rows)


# ---------------------------------------------------------------------------
# Compensating invariant: confirm/cancel conserves the booth-minutes budget
# ---------------------------------------------------------------------------


def test_confirm_consumes_booth_minutes_from_budget(api):
    """PRD §2.10: "For any facility and any UTC date, the sum of the `duration_minutes` of that day's confirmed sessions plus the remaining bookable minutes always equals the facility's booth count multiplied by the length of its visiting window. Confirming a session consumes booth-minutes; confirming and then cancelling the same session restores them exactly."

    Design: Difficulty/compensating_invariant/video_confirm_then_cancel_conserves_booth_minutes_budget
    """
    env = setup_funded_account()
    facility = env["facility"]

    before = get_video_availability(facility["id"], "2026-09-19")
    assert before["booth_count"] == 2
    assert before["booked_minutes"] == 0
    assert before["bookable_minutes"] == 1440, (
        "2 booths x 720 window-minutes; an uncreated session consumes nothing"
    )

    create_and_confirm_session(
        facility,
        env["inmate"],
        env["account"],
        scheduled_start="2026-09-19T10:00:00Z",
        scheduled_end="2026-09-19T10:30:00Z",
    )

    after = get_video_availability(facility["id"], "2026-09-19")
    assert after["booked_minutes"] == 30
    assert after["bookable_minutes"] == 1410
    assert after["booked_minutes"] + after["bookable_minutes"] == 1440


def test_cancel_restores_booth_minutes_to_budget(api):
    """PRD §3.7: "A successful confirmed cancellation appends a `VIDEO_REFUND` credit of the full `charge_cents`, recomputes the balance, and restores the session's booth-minutes to the facility's bookable pool exactly, as the booth-minutes invariant requires."
    PRD §2.10: "Confirming a session consumes booth-minutes; confirming and then cancelling the same session restores them exactly. The conserved quantity is booth-minute capacity."

    Design: Difficulty/compensating_invariant/video_confirm_then_cancel_conserves_booth_minutes_budget
    """
    env = setup_funded_account()
    facility, account = env["facility"], env["account"]

    session = create_and_confirm_session(
        facility,
        env["inmate"],
        account,
        scheduled_start="2026-09-19T10:00:00Z",
        scheduled_end="2026-09-19T10:30:00Z",
    )
    mid = get_video_availability(facility["id"], "2026-09-19")
    assert mid["booked_minutes"] == 30 and mid["bookable_minutes"] == 1410
    assert get_account(account["id"])["balance_cents"] == 500

    cancel_session(session, account=account)

    restored = get_video_availability(facility["id"], "2026-09-19")
    assert restored["booked_minutes"] == 0
    assert restored["bookable_minutes"] == 1440, (
        "the booth-minute budget is conserved exactly across confirm + cancel"
    )
    assert get_account(account["id"])["balance_cents"] == 1000, (
        "VIDEO_CHARGE -500 then VIDEO_REFUND +500"
    )
