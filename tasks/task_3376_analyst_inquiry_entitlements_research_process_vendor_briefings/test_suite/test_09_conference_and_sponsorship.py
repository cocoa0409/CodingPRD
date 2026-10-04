"""Conference programming, the sponsor minute share and sponsorship revenue."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    api_client,
    append_session,
    activate_sponsorship,
    cancel_sponsorship,
    create_event,
    create_sponsorship,
    create_vendor,
    get_event,
    get_success_data,
    lock_agenda,
    set_clock,
    validate_error,
)


def test_terminal_sponsorship_state_precedes_the_event_state_check():
    """PRD §2.11: "Target state: the resource named by the request is in a state from
    which the requested transition exists, and a resource in a terminal state rejects
    every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §2.11: "Referenced entity state: the seat must be `ACTIVE` and its account
    `ACTIVE` before an inquiry may be submitted (`ERR_SEAT_NOT_ACTIVE`, HTTP 409), and
    the linked conference event must still be `DRAFT` or `PROGRAMMING` before a
    sponsorship may be activated (`ERR_EVENT_AGENDA_LOCKED`, HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_referential_on_sponsorship_activation
    """
    set_clock("2026-09-01T00:00:00Z")
    first_vendor = create_vendor()
    second_vendor = create_vendor(
        vendor_name="Bluepeak Systems", hq_region="EMEA", employee_count_band="MIDMARKET"
    )
    event = create_event()
    gold = create_sponsorship(event, first_vendor, tier="GOLD", amount_cents=2_500_000)
    activate_sponsorship(gold)
    cancel_sponsorship(gold)
    assert get_event(event)["sponsorship_revenue_cents"] == 0

    pending = create_sponsorship(event, second_vendor, tier="SILVER", amount_cents=400_000)
    append_session(event, session_title="Opening research keynote",
                   session_kind="RESEARCH_SESSION", duration_minutes=60)
    lock_agenda(event)

    # Activation is authorized to EventProgrammer and SalesRep only (PRD 4), so
    # the default PlatformAdmin identity never reaches the state checks.
    terminal = api_client.activate_sponsorship(
        gold["id"], TEST_USERS["event_programmer_headers"]
    )
    validate_error(terminal, ApiErrorId.ERR_INVALID_STATE)

    locked = api_client.activate_sponsorship(
        pending["id"], TEST_USERS["event_programmer_headers"]
    )
    validate_error(locked, ApiErrorId.ERR_EVENT_AGENDA_LOCKED)

    unchanged = get_success_data(api_client.get_sponsorship(pending["id"]))
    assert unchanged["status"] == "PENDING"


def test_terminal_sponsorship_state_is_reported_alone_on_a_live_event():
    """PRD §2.11: "Target state: the resource named by the request is in a state from
    which the requested transition exists, and a resource in a terminal state rejects
    every further transition. Failure is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_precedes_referential_on_sponsorship_activation
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    sponsorship = create_sponsorship(event, vendor, tier="GOLD", amount_cents=2_500_000)
    activate_sponsorship(sponsorship)
    cancel_sponsorship(sponsorship)

    resp = api_client.activate_sponsorship(
        sponsorship["id"], TEST_USERS["event_programmer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    unchanged = get_success_data(api_client.get_sponsorship(sponsorship["id"]))
    assert unchanged["status"] == "CANCELLED"
    assert get_event(event)["sponsorship_revenue_cents"] == 0


def test_sponsor_share_accepts_exactly_the_ceiling_and_refuses_the_next_row():
    """PRD §2.8: "A sponsor keynote row is accepted only when the share recomputed on
    the post-append state is at most 0.4000 — exactly 0.4000 is allowed and 0.4001 is
    rejected with `ERR_SPONSOR_SHARE_EXCEEDED` (HTTP 409)."
    PRD §2.8: "the sponsor minutes are the sum of `duration_minutes` across the rows
    whose `session_kind` is `SPONSOR_KEYNOTE`."

    Design: Difficulty/boundary_precision_check/sponsor_minute_share_exact_ceiling
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    for index in range(4):
        append_session(event, session_title=f"Research keynote {index + 1}",
                       session_kind="RESEARCH_SESSION", duration_minutes=30)
    append_session(event, session_title="Sponsor showcase 1", session_kind="SPONSOR_KEYNOTE",
                   duration_minutes=40, sponsor_vendor_id=vendor["id"])

    at_ceiling = append_session(
        event, session_title="Sponsor showcase 2", session_kind="SPONSOR_KEYNOTE",
        duration_minutes=40, sponsor_vendor_id=vendor["id"],
    )
    assert at_ceiling["sponsor_minute_share"] == 0.4
    assert at_ceiling["sponsor_session_minutes"] == 80
    assert at_ceiling["research_session_minutes"] == 120

    # duration_minutes must be at least 15 (PRD 3.9); a shorter row would be
    # refused by the request-shape check before the share ceiling is reached.
    # 15 minutes still pushes the post-append share to 95/215 = 0.4419 > 0.4000.
    resp = api_client.append_session(
        event["id"],
        {"session_title": "Sponsor showcase 3", "session_kind": "SPONSOR_KEYNOTE",
         "duration_minutes": 15, "sponsor_vendor_id": vendor["id"]},
        TEST_USERS["event_programmer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SPONSOR_SHARE_EXCEEDED)

    unchanged = get_event(event)
    assert unchanged["sponsor_minute_share"] == 0.4
    assert len(unchanged["sessions"]) == 6


def test_sponsor_share_ceiling_holds_on_a_different_agenda_mix():
    """PRD §2.8: "When there are no agenda rows the share is 0; otherwise
    `sponsor_minute_share` is the sponsor minutes divided by the total minutes, rounded
    half up to 4 decimal places."
    PRD §2.8: "A sponsor keynote row is accepted only when the share recomputed on the
    post-append state is at most 0.4000".

    Design: Difficulty/boundary_precision_check/sponsor_minute_share_exact_ceiling
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    append_session(event, session_title="Research plenary", session_kind="RESEARCH_SESSION",
                   duration_minutes=45)
    append_session(event, session_title="Research deep dive", session_kind="RESEARCH_SESSION",
                   duration_minutes=45)
    append_session(event, session_title="Sponsor keynote", session_kind="SPONSOR_KEYNOTE",
                   duration_minutes=60, sponsor_vendor_id=vendor["id"])
    assert get_event(event)["sponsor_minute_share"] == 0.4

    resp = api_client.append_session(
        event["id"],
        {"session_title": "Extra sponsor slot", "session_kind": "SPONSOR_KEYNOTE",
         "duration_minutes": 15, "sponsor_vendor_id": vendor["id"]},
        TEST_USERS["event_programmer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SPONSOR_SHARE_EXCEEDED)


def test_only_platinum_windows_occupy_the_event_exclusivity_resource():
    """PRD §3.9: "`PLATINUM` windows are exclusive, and a new `PLATINUM` sponsorship
    whose window overlaps another `ACTIVE` `PLATINUM` window on the same event is
    rejected with `ERR_SPONSOR_EXCLUSIVITY_OVERLAP` (HTTP 409)."
    PRD §3.9: "The exclusivity window is half-open: its start instant is included and
    its end instant is excluded."

    Design: Difficulty/resource_temporal_overlap/platinum_exclusivity_window_overlap_on_the_event
    """
    set_clock("2026-09-01T00:00:00Z")
    first_vendor = create_vendor()
    second_vendor = create_vendor(
        vendor_name="Bluepeak Systems", hq_region="EMEA", employee_count_band="MIDMARKET"
    )
    event = create_event()
    first = create_sponsorship(
        event, first_vendor, tier="PLATINUM", amount_cents=9_000_000,
        exclusivity_start_utc="2026-10-01T00:00:00Z",
        exclusivity_end_utc="2026-10-05T00:00:00Z",
    )
    activate_sponsorship(first)

    overlapping = api_client.create_sponsorship(
        {
            "conference_event_id": event["id"],
            "vendor_id": second_vendor["id"],
            "tier": "PLATINUM",
            "amount_cents": 8_000_000,
            "exclusivity_start_utc": "2026-10-04T00:00:00Z",
            "exclusivity_end_utc": "2026-10-08T00:00:00Z",
            "expected_conference_event_version": get_event(event)["version"],
        },
        TEST_USERS["sales_rep_headers"],
    )
    validate_error(overlapping, ApiErrorId.ERR_SPONSOR_EXCLUSIVITY_OVERLAP)

    adjacent = create_sponsorship(
        event, second_vendor, tier="PLATINUM", amount_cents=8_000_000,
        exclusivity_start_utc="2026-10-05T00:00:00Z",
        exclusivity_end_utc="2026-10-08T00:00:00Z",
    )
    assert adjacent["status"] == "PENDING"

    gold = create_sponsorship(
        event, second_vendor, tier="GOLD", amount_cents=2_000_000,
        exclusivity_start_utc="2026-10-04T00:00:00Z",
        exclusivity_end_utc="2026-10-08T00:00:00Z",
    )
    assert gold["status"] == "PENDING"

    assert get_event(event)["sponsorship_revenue_cents"] == 9_000_000


def test_platinum_overlap_is_refused_while_a_gold_window_may_overlap():
    """PRD §3.9: "`PLATINUM` windows are exclusive, and a new `PLATINUM` sponsorship
    whose window overlaps another `ACTIVE` `PLATINUM` window on the same event is
    rejected with `ERR_SPONSOR_EXCLUSIVITY_OVERLAP` (HTTP 409)."
    PRD §3.9: "A `Sponsorship` names the `conference_event_id`, the `vendor_id`, a
    `tier` of `PLATINUM`, `GOLD` or `SILVER`, an `amount_cents` of at least 0, an
    `exclusivity_start_utc` and an `exclusivity_end_utc`, and the
    `expected_conference_event_version` the client last observed for the event."

    Design: Difficulty/resource_temporal_overlap/platinum_exclusivity_window_overlap_on_the_event
    """
    set_clock("2026-09-01T00:00:00Z")
    first_vendor = create_vendor()
    second_vendor = create_vendor(
        vendor_name="Bluepeak Systems", hq_region="EMEA", employee_count_band="MIDMARKET"
    )
    event = create_event()
    platinum = create_sponsorship(
        event, first_vendor, tier="PLATINUM", amount_cents=9_000_000,
        exclusivity_start_utc="2026-10-01T00:00:00Z",
        exclusivity_end_utc="2026-10-05T00:00:00Z",
    )
    activate_sponsorship(platinum)

    gold = create_sponsorship(
        event, second_vendor, tier="GOLD", amount_cents=1_500_000,
        exclusivity_start_utc="2026-10-02T00:00:00Z",
        exclusivity_end_utc="2026-10-04T00:00:00Z",
    )
    assert gold["status"] == "PENDING"

    silver = create_sponsorship(
        event, second_vendor, tier="SILVER", amount_cents=500_000,
        exclusivity_start_utc="2026-10-02T00:00:00Z",
        exclusivity_end_utc="2026-10-04T00:00:00Z",
    )
    assert silver["status"] == "PENDING"

    overlapping = api_client.create_sponsorship(
        {
            "conference_event_id": event["id"],
            "vendor_id": second_vendor["id"],
            "tier": "PLATINUM",
            "amount_cents": 7_000_000,
            "exclusivity_start_utc": "2026-10-04T23:59:59Z",
            "exclusivity_end_utc": "2026-10-09T00:00:00Z",
            "expected_conference_event_version": get_event(event)["version"],
        },
        TEST_USERS["sales_rep_headers"],
    )
    validate_error(overlapping, ApiErrorId.ERR_SPONSOR_EXCLUSIVITY_OVERLAP)


def test_sponsorship_revenue_returns_to_zero_after_the_compensating_cancel():
    """PRD §3.9: "Activation sets the sponsorship to `ACTIVE`, stamps `activated_at`
    with the clock reading, sets `sponsor_slot_counted` true, increments the
    sponsorship's `version`, and books the revenue: the event's
    `sponsorship_revenue_cents` is incremented by the sponsorship's `amount_cents` and
    the event's `version` is incremented."
    PRD §3.9: "Cancellation accepts an optional `cancel_reason`, moves the sponsorship
    to the terminal `CANCELLED` state, stamps `cancelled_at` with the clock reading,
    sets `sponsor_slot_counted` false, increments the sponsorship's `version`, and
    reverses the revenue by decrementing the event's `sponsorship_revenue_cents` by
    the sponsorship's `amount_cents` while incrementing the event's `version`."

    Design: Difficulty/compensating_invariant/sponsorship_revenue_conserved_across_activate_and_cancel
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    sponsorship = create_sponsorship(
        event, vendor, tier="PLATINUM", amount_cents=9_000_000,
        exclusivity_start_utc="2026-10-01T00:00:00Z",
        exclusivity_end_utc="2026-10-05T00:00:00Z",
    )
    assert get_event(event)["sponsorship_revenue_cents"] == 0

    activated = activate_sponsorship(sponsorship)
    assert activated["sponsor_slot_counted"] is True
    assert get_event(event)["sponsorship_revenue_cents"] == 9_000_000

    cancelled = cancel_sponsorship(sponsorship, "Vendor pulled out before the agenda locked")
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["sponsor_slot_counted"] is False
    assert get_event(event)["sponsorship_revenue_cents"] == 0


def test_sponsorship_revenue_is_conserved_across_a_second_activate_cancel_cycle():
    """PRD §3.9: "the event's `sponsorship_revenue_cents` is incremented by the
    sponsorship's `amount_cents` and the event's `version` is incremented."
    PRD §3.9: "Cancellation accepts an optional `cancel_reason`, moves the sponsorship
    to the terminal `CANCELLED` state, stamps `cancelled_at` with the clock reading,
    sets `sponsor_slot_counted` false, increments the sponsorship's `version`, and
    reverses the revenue by decrementing the event's `sponsorship_revenue_cents` by
    the sponsorship's `amount_cents` while incrementing the event's `version`."

    Design: Difficulty/compensating_invariant/sponsorship_revenue_conserved_across_activate_and_cancel
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    first = create_sponsorship(event, vendor, tier="GOLD", amount_cents=2_500_000)
    second = create_sponsorship(event, vendor, tier="SILVER", amount_cents=400_000)

    activate_sponsorship(first)
    activate_sponsorship(second)
    assert get_event(event)["sponsorship_revenue_cents"] == 2_900_000

    cancel_sponsorship(first)
    assert get_event(event)["sponsorship_revenue_cents"] == 400_000

    cancel_sponsorship(second)
    assert get_event(event)["sponsorship_revenue_cents"] == 0


def test_cancelled_sponsorship_cannot_be_reactivated():
    """PRD §3.9: "Cancellation accepts an optional `cancel_reason`, moves the sponsorship
    to the terminal `CANCELLED` state, stamps `cancelled_at` with the clock reading,
    sets `sponsor_slot_counted` false, increments the sponsorship's `version`, and
    reverses the revenue by decrementing the event's `sponsorship_revenue_cents` by
    the sponsorship's `amount_cents` while incrementing the event's `version`."
    PRD §2.11: "a resource in a terminal state rejects every further transition.
    Failure is `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/sponsorship_activate_from_cancelled_is_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    sponsorship = create_sponsorship(event, vendor, tier="GOLD", amount_cents=2_500_000)
    activate_sponsorship(sponsorship)
    cancel_sponsorship(sponsorship)

    resp = api_client.activate_sponsorship(
        sponsorship["id"], TEST_USERS["event_programmer_headers"]
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    unchanged = get_success_data(api_client.get_sponsorship(sponsorship["id"]))
    assert unchanged["status"] == "CANCELLED"
    assert get_event(event)["sponsorship_revenue_cents"] == 0


def test_event_read_recomputes_the_agenda_mix_from_the_session_rows():
    """PRD §2.8: "The total session minutes are the sum of `duration_minutes` across
    all agenda rows, and the sponsor minutes are the sum of `duration_minutes` across
    the rows whose `session_kind` is `SPONSOR_KEYNOTE`."
    PRD §3.9: "Each accepted row is appended, `research_session_minutes`,
    `sponsor_session_minutes` and `sponsor_minute_share` are recomputed, and the
    event's `version` is incremented."

    Design: Corner/endpoints/conference_event_read_recomputes_the_sponsor_share
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    append_session(event, session_title="Research keynote 1", session_kind="RESEARCH_SESSION",
                   duration_minutes=30)
    append_session(event, session_title="Research keynote 2", session_kind="RESEARCH_SESSION",
                   duration_minutes=30)
    append_session(event, session_title="Sponsor showcase", session_kind="SPONSOR_KEYNOTE",
                   duration_minutes=20, sponsor_vendor_id=vendor["id"])

    data = get_event(event)
    assert data["research_session_minutes"] == 60
    assert data["sponsor_session_minutes"] == 20
    assert data["sponsor_minute_share"] == 0.25
    assert data["status"] == "PROGRAMMING"
    assert len(data["sessions"]) == 3


def test_selling_a_sponsorship_does_not_book_revenue_until_activation():
    """PRD §3.9: "A successful sale is created in `PENDING` with
    `sponsor_slot_counted` false, and the event's `version` is incremented."
    PRD §2.10: "Fields that record a lifecycle instant are null until the event that
    stamps them occurs".

    Design: Corner/endpoints/sponsorship_create_leaves_event_revenue_untouched_until_activation
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    version_before = event["version"]

    sponsorship = create_sponsorship(
        event, vendor, tier="PLATINUM", amount_cents=9_000_000,
        exclusivity_start_utc="2026-10-01T00:00:00Z",
        exclusivity_end_utc="2026-10-05T00:00:00Z",
    )
    assert sponsorship["status"] == "PENDING"
    assert sponsorship["sponsor_slot_counted"] is False
    assert sponsorship["activated_at"] is None
    assert sponsorship["cancelled_at"] is None

    event_after = get_event(event)
    assert event_after["sponsorship_revenue_cents"] == 0
    assert event_after["version"] == version_before + 1


def test_sponsor_row_cannot_reopen_a_locked_agenda():
    """PRD §3.9: "a `SPONSOR_KEYNOTE` row appended to a locked agenda is refused with
    `ERR_AGENDA_LOCKED` (HTTP 409), because sponsor rows alone never reopen an agenda."

    Design: Corner/errors/sponsor_row_on_a_locked_agenda_returns_agenda_locked
    """
    set_clock("2026-09-01T00:00:00Z")
    vendor = create_vendor()
    event = create_event()
    append_session(event, session_title="Opening research keynote",
                   session_kind="RESEARCH_SESSION", duration_minutes=60)
    lock_agenda(event)

    resp = api_client.append_session(
        event["id"],
        {"session_title": "Late sponsor slot", "session_kind": "SPONSOR_KEYNOTE",
         "duration_minutes": 20, "sponsor_vendor_id": vendor["id"]},
        TEST_USERS["event_programmer_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_AGENDA_LOCKED)

    unchanged = get_event(event)
    assert unchanged["status"] == "AGENDA_LOCKED"
    assert len(unchanged["sessions"]) == 1
