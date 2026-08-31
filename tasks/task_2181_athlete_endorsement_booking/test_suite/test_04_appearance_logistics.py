"""The athlete's calendar: holds, travel accrual, closures and cancellations."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_accrued_fee_matches_ledger,
    assert_appearance_booking,
    assert_ledger_entry,
    assert_ledger_ordered_by_created_at,
    build_deal,
    cancel_booking,
    cancel_booking_payload,
    confirm_booking,
    create_appearance_booking_payload,
    engagement_version,
    make_brand_rep_headers,
    place_booking,
    read_engagement,
    setup_terminated_engagement_over_busy_calendar,
    validate_error,
    validate_paginated,
    validate_success,
)

AGENT = TEST_USERS["talent_agent_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def test_booking_touching_a_padded_endpoint_collides(api):
    """PRD 2.7: "Two bookings collide when the inflated interval of one touches or
    overlaps the inflated interval of the other — that is, when the new booking's
    inflated start is at or before the other's inflated end and the new booking's
    inflated end is at or after the other's inflated start. Touching endpoints
    therefore *do* count as a collision."
    PRD 3.6: "Because the intervals are closed, an intersection includes the case
    where the two inflated windows merely touch at an endpoint: the collision test is
    that the new inflated start falls at or before the other's inflated end *and* the
    new inflated end falls at or after the other's inflated start. A collision is
    refused with `ERR_BOOKING_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/athlete_booking_travel_buffer_closed_interval_conflict
    """
    deal = build_deal(
        stage="pending",
        opportunity_overrides={
            "proposed_fee_cents": 800_000, "planned_posts": 2,
            "planned_appearances": 1, "planned_shoots": 1,
        },
        term_sheet_overrides={"appearance_days": 2},
    )
    first = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(first["id"], 180_500)
    current_version = engagement_version(deal["engagement_id"])

    response = api.create_appearance_booking(
        create_appearance_booking_payload(
            deal["engagement_id"], current_version, city="Detroit",
            start_at="2026-09-11T10:00:00Z", end_at="2026-09-11T14:00:00Z",
            travel_buffer_hours=0,
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_OVERLAP.value, 409)

    rows, _meta = validate_paginated(
        api.list_appearance_bookings(AGENT, params={"engagement_id": deal["engagement_id"]})
    )
    assert len(rows) == 1, "the refused hold created nothing"


def test_booking_one_hour_past_the_padded_end_is_accepted(api):
    """PRD 3.6: "Because the intervals are closed, an intersection includes the case
    where the two inflated windows merely touch at an endpoint: the collision test is
    that the new inflated start falls at or before the other's inflated end *and* the
    new inflated end falls at or after the other's inflated start. A collision is
    refused with `ERR_BOOKING_OVERLAP`."
    PRD 3.6: "Confirming a hold moves it `HOLD → CONFIRMED` and requires the
    engagement to still be `PENDING_COUNTERSIGN` or `ACTIVE`. The call carries the
    reimbursable `travel_cost_cents` actually committed, and it derives `travel_days`:
    take the span from `start_at` to `end_at` in hours, add twice
    `travel_buffer_hours`, divide by 24 and round *up* to a whole number of days."

    Design: Difficulty/resource_temporal_overlap/athlete_booking_travel_buffer_closed_interval_conflict
    """
    deal = build_deal(
        stage="pending",
        opportunity_overrides={
            "proposed_fee_cents": 800_000, "planned_posts": 2,
            "planned_appearances": 1, "planned_shoots": 1,
        },
        term_sheet_overrides={"appearance_days": 2},
    )
    first = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirmed = confirm_booking(first["id"], 180_500)
    assert confirmed["travel_days"] == 2, "8 hours plus twice a 12-hour buffer is 32 hours"

    response = api.create_appearance_booking(
        create_appearance_booking_payload(
            deal["engagement_id"], engagement_version(deal["engagement_id"]),
            city="Detroit", start_at="2026-09-11T11:00:00Z",
            end_at="2026-09-11T15:00:00Z", travel_buffer_hours=0,
        ),
        AGENT,
    )
    second = validate_success(response, 201)
    assert_appearance_booking(second)
    assert second["status"] == "HOLD"

    rows, _meta = validate_paginated(
        api.list_appearance_bookings(AGENT, params={"engagement_id": deal["engagement_id"]})
    )
    assert len(rows) == 2


def test_travel_days_ceiling_treats_exactly_twenty_four_hours_as_one_day(api):
    """PRD 3.6: "The ceiling is exact — a padded span of exactly 24.0 hours yields 1
    day, while 24.01 hours yields 2. No spans are ever merged across bookings; each
    booking's travel days are computed from that booking alone."
    PRD 3.6: "Confirmation appends a `TRAVEL_ACCRUAL` ledger entry whose
    `amount_cents` is the positive `travel_cost_cents`, and because that entry was
    appended the engagement's `accrued_fee_cents` increases by the same amount."

    Design: Corner/calculations/travel_days_ceiling_boundary_exactly_24_hours
    """
    deal = build_deal(stage="pending")
    exactly_one_day = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T00:00:00Z", end_at="2026-09-11T00:00:00Z",
        travel_buffer_hours=0,
    )
    just_over = place_booking(
        deal["engagement_id"], city="Denver",
        start_at="2026-09-20T00:00:00Z", end_at="2026-09-21T01:00:00Z",
        travel_buffer_hours=0,
    )

    first = confirm_booking(exactly_one_day["id"], 50_000)
    second = confirm_booking(just_over["id"], 60_000)

    assert first["travel_days"] == 1
    assert second["travel_days"] == 2

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["accrued_fee_cents"] == 110_000

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert [e["entry_type"] for e in entries] == ["TRAVEL_ACCRUAL", "TRAVEL_ACCRUAL"]
    assert [e["amount_cents"] for e in entries] == [50_000, 60_000]


def test_booking_before_the_term_start_is_outside_the_term(api):
    """PRD 3.6: "The booking's calendar days must sit inside the engagement's term:
    the date of `start_at` must be on or after `term_start_date` and the date of
    `end_at` on or before `term_end_date`, both inclusive, or the request is refused
    with `ERR_BOOKING_WINDOW_OUTSIDE_TERM`."

    Design: Corner/validations/booking_outside_engagement_term_returns_window_error
    """
    deal = build_deal(stage="pending")

    response = api.create_appearance_booking(
        create_appearance_booking_payload(
            deal["engagement_id"], deal["engagement"]["version"], city="Chicago",
            start_at="2026-08-25T14:00:00Z", end_at="2026-08-25T22:00:00Z",
            travel_buffer_hours=0,
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_WINDOW_OUTSIDE_TERM.value, 422)

    rows, _meta = validate_paginated(
        api.list_appearance_bookings(AGENT, params={"engagement_id": deal["engagement_id"]})
    )
    assert rows == []


def test_booking_create_advances_the_engagement_version_by_one(api):
    """PRD 2.5: "Creating an appearance booking (`POST /appearance-bookings`) requires
    a non-optional `expected_engagement_version` field carrying the client's last
    observed `version` of the target engagement."
    PRD 2.5: "If `expected_engagement_version` does not equal the engagement's current
    `version`, the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412).
    A successful create increments the engagement's `version` by 1."

    Design: Corner/cross_cutting_complexity_layers/occ_booking_create_advances_engagement_version_by_one
    """
    deal = build_deal(stage="pending")
    observed_version = deal["engagement"]["version"]

    first = validate_success(
        api.create_appearance_booking(
            create_appearance_booking_payload(
                deal["engagement_id"], observed_version, city="Chicago",
                start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
                travel_buffer_hours=12,
            ),
            AGENT,
        ),
        201,
    )
    assert first["status"] == "HOLD"
    assert engagement_version(deal["engagement_id"]) == observed_version + 1

    replay = api.create_appearance_booking(
        create_appearance_booking_payload(
            deal["engagement_id"], observed_version, city="Denver",
            start_at="2026-09-25T14:00:00Z", end_at="2026-09-25T22:00:00Z",
            travel_buffer_hours=0,
        ),
        AGENT,
    )
    validate_error(replay, ApiErrorId.ERR_STALE_ENGAGEMENT_VERSION.value, 412)

    rows, _meta = validate_paginated(
        api.list_appearance_bookings(AGENT, params={"engagement_id": deal["engagement_id"]})
    )
    assert len(rows) == 1


def test_no_show_closure_penalises_the_engagement_and_the_athlete(api):
    """PRD 3.6: "Closing `CONFIRMED → NO_SHOW` writes the `outcome`, increments the
    athlete's `no_show_count` by 1, and appends a `PENALTY` ledger entry whose
    `amount_cents` is the negative of ten percent of the engagement's
    `binding_fee_cents`, rounded half up to whole cents; because that entry was
    appended, the engagement's `accrued_fee_cents` decreases by that amount."
    PRD 3.5: "Once written, `binding_fee_cents` is frozen — later bookings do not move
    it."

    Design: Corner/state_machines/no_show_close_writes_penalty_and_increments_no_show_count
    """
    deal = build_deal(stage="active", signed_by_reference="CS-C-0002")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 100_000)

    closed = validate_success(
        api.close_appearance_booking(booking["id"], {"outcome": "NO_SHOW"}, AGENT), 200
    )
    assert closed["status"] == "NO_SHOW"
    assert closed["outcome"] == "NO_SHOW"

    athlete = validate_success(api.get_athlete(deal["athlete_id"], AGENT))
    assert athlete["no_show_count"] == 1

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert [e["entry_type"] for e in entries] == ["TRAVEL_ACCRUAL", "PENALTY"]
    assert entries[0]["amount_cents"] == 100_000
    assert entries[1]["amount_cents"] == -262_140

    engagement = read_engagement(deal["engagement_id"])
    assert engagement["accrued_fee_cents"] == -162_140
    assert engagement["binding_fee_cents"] == 2_621_400


def test_cancelling_a_confirmed_booking_appends_the_reversal_entry(api):
    """PRD 3.6: "Cancelling from `CONFIRMED` moves it `CONFIRMED → CANCELLED` and
    appends the compensating `REVERSAL` ledger entry whose `amount_cents` is the
    negative of that booking's `travel_cost_cents`; because that entry was appended,
    the engagement's `accrued_fee_cents` returns to its pre-confirmation value."

    Design: Difficulty/compensating_invariant/booking_cancel_reverses_travel_accrual_ledger_sum_matches_accrued_fee
    """
    deal = build_deal(stage="pending")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 180_500)
    assert read_engagement(deal["engagement_id"])["accrued_fee_cents"] == 180_500

    cancelled = validate_success(
        api.cancel_appearance_booking(
            booking["id"], cancel_booking_payload("VENUE_CLOSED"), AGENT
        ),
        200,
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason_code"] == "VENUE_CLOSED"
    assert cancelled["travel_cost_cents"] == 180_500, (
        "the booking row keeps its historical travel figure"
    )

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert len(entries) == 2
    assert_ledger_ordered_by_created_at(entries)
    assert entries[0]["entry_type"] == "TRAVEL_ACCRUAL" and entries[0]["amount_cents"] == 180_500
    assert entries[1]["entry_type"] == "REVERSAL" and entries[1]["amount_cents"] == -180_500


def test_accrued_fee_equals_the_ledger_sum_after_a_reversal(api):
    """PRD 2.6: "An engagement's `accrued_fee_cents` is the running sum of the
    `amount_cents` of that engagement's entries whose `entry_type` is
    `TRAVEL_ACCRUAL`, `REVERSAL`, `PENALTY` or `BONUS`."
    PRD 3.6: "Cancelling from `CONFIRMED` moves it `CONFIRMED → CANCELLED` and appends
    the compensating `REVERSAL` ledger entry whose `amount_cents` is the negative of
    that booking's `travel_cost_cents`; because that entry was appended, the
    engagement's `accrued_fee_cents` returns to its pre-confirmation value."

    Design: Difficulty/compensating_invariant/booking_cancel_reverses_travel_accrual_ledger_sum_matches_accrued_fee
    """
    deal = build_deal(stage="pending")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 180_500)
    cancel_booking(booking["id"], "VENUE_CLOSED")

    engagement = read_engagement(deal["engagement_id"])
    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert_accrued_fee_matches_ledger(engagement, entries)
    assert engagement["accrued_fee_cents"] == 0


def test_ledger_entries_are_append_only_rows_without_version_or_updated_at(api):
    """PRD 2.4: "There is exactly one exception: a `LedgerEntry` is an immutable,
    append-only record and carries only `id` and `created_at` — it has neither
    `updated_at` nor `version`, and it is never modified once written."
    PRD 2.6: "Each movement is appended as an immutable `LedgerEntry` carrying
    `engagement_id`, an `entry_type`, a signed `amount_cents` (credits positive,
    debits negative), a human-readable `memo`, and a polymorphic source pair
    `source_entity` and `source_id`. `source_entity` records which kind of row caused
    the movement — one of `AppearanceBooking`, `Deliverable`, `PayoutStatement` or
    `RenewalOption` — and `source_id` is that row's identifier."

    Design: Corner/entities/ledger_entry_is_immutable_append_only
    """
    deal = build_deal(stage="pending")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 180_500)
    cancel_booking(booking["id"], "VENUE_CLOSED")

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert len(entries) == 2
    assert_ledger_ordered_by_created_at(entries)
    for entry in entries:
        assert_ledger_entry(entry)
        assert entry["source_entity"] == "AppearanceBooking"
    assert entries[0]["entry_type"] == "TRAVEL_ACCRUAL"
    assert entries[0]["amount_cents"] == 180_500
    assert entries[1]["entry_type"] == "REVERSAL"
    assert entries[1]["amount_cents"] == -180_500


def test_a_brand_representative_may_also_cancel_a_booking(api):
    """PRD 3.6: "Cancellation is available to both a `TalentAgent` and a `BrandRep`,
    and it records a `cancel_reason_code` from the supplied `reason_code`."
    PRD 3.6: "Cancelling from `CONFIRMED` moves it `CONFIRMED → CANCELLED` and appends
    the compensating `REVERSAL` ledger entry whose `amount_cents` is the negative of
    that booking's `travel_cost_cents`; because that entry was appended, the
    engagement's `accrued_fee_cents` returns to its pre-confirmation value."

    Design: Corner/endpoints/cancel_booking_is_shared_between_talent_agent_and_brand_rep
    """
    deal = build_deal(stage="pending")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    confirm_booking(booking["id"], 180_500)

    response = api.cancel_appearance_booking(
        booking["id"], cancel_booking_payload("BRAND_RESCHEDULE"),
        make_brand_rep_headers(deal["brand_id"]),
    )
    cancelled = validate_success(response, 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason_code"] == "BRAND_RESCHEDULE"

    assert read_engagement(deal["engagement_id"])["accrued_fee_cents"] == 0
    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert len(entries) == 2
    assert entries[-1]["entry_type"] == "REVERSAL"
    assert entries[-1]["amount_cents"] == -180_500


def test_cancelling_an_already_cancelled_booking_is_refused(api):
    """PRD 3.6: "Confirming a booking that is not `HOLD`, closing one that is not
    `CONFIRMED`, or cancelling one already in a terminal state is refused with
    `ERR_BOOKING_INVALID_STATE`."
    PRD 3.6: "Cancelling from `HOLD` moves the booking `HOLD → CANCELLED` and writes
    no ledger entry, because nothing was ever accrued against a hold."

    Design: Corner/state_machines/cancel_booking_twice_returns_booking_invalid_state
    """
    deal = build_deal(stage="pending")
    booking = place_booking(
        deal["engagement_id"], city="Chicago",
        start_at="2026-09-10T14:00:00Z", end_at="2026-09-10T22:00:00Z",
        travel_buffer_hours=12,
    )
    cancel_booking(booking["id"], "VENUE_CLOSED")

    response = api.cancel_appearance_booking(
        booking["id"], cancel_booking_payload("VENUE_CLOSED"), AGENT
    )
    validate_error(response, ApiErrorId.ERR_BOOKING_INVALID_STATE.value, 409)

    unchanged = validate_success(api.get_appearance_booking(booking["id"], AGENT))
    assert unchanged["status"] == "CANCELLED"

    entries, _meta = validate_paginated(
        api.list_ledger_entries(deal["engagement_id"], FINANCE)
    )
    assert entries == []


def test_terminated_engagement_outranks_the_calendar_collision(api):
    """PRD 2.8: "Only once all of that passes does the domain layer run, in this
    order: athlete bookability (`ERR_ATHLETE_NOT_BOOKABLE`), opportunity-screened
    (`ERR_OPPORTUNITY_NOT_SCREENED`), term-sheet from-state
    (`ERR_TERM_SHEET_INVALID_STATE`), offer expiry (`ERR_OFFER_EXPIRED`), engagement
    contract-status fitness (`ERR_ENGAGEMENT_NOT_ACTIVE`), engagement terminality for
    countersign and terminate (`ERR_ENGAGEMENT_ALREADY_TERMINAL`), booking from-state
    (`ERR_BOOKING_INVALID_STATE`), deliverable from-state
    (`ERR_DELIVERABLE_INVALID_STATE`), disclosure from-state
    (`ERR_DISCLOSURE_INVALID_STATE`), settlement billability
    (`ERR_SETTLEMENT_NOT_BILLABLE`), payout from-state (`ERR_PAYOUT_INVALID_STATE`),
    renewal window (`ERR_RENEWAL_WINDOW_CLOSED`), segregation of duties
    (`ERR_SEGREGATION_OF_DUTIES`), brand sanction (`ERR_BRAND_SANCTIONED`), disclosure
    compliance (`ERR_DISCLOSURE_NOT_COMPLIANT`), morals-tier downgrade
    (`ERR_MORALS_TIER_DOWNGRADE_FORBIDDEN`), deliverable reference coherence
    (`ERR_BOOKING_ENGAGEMENT_MISMATCH`), shoot-inside-slot-window
    (`ERR_SLOT_WINDOW_VIOLATION`), athlete calendar overlap (`ERR_BOOKING_OVERLAP`),
    slot capacity (`ERR_SLOT_CAPACITY_EXCEEDED`), booking-inside-term
    (`ERR_BOOKING_WINDOW_OUTSIDE_TERM`), exclusivity conflict
    (`ERR_EXCLUSIVITY_CONFLICT`), counter-round limit (`ERR_COUNTER_LIMIT_EXCEEDED`),
    duplicate disclosure (`ERR_DUPLICATE_DISCLOSURE`), fee cap
    (`ERR_FEE_CAP_EXCEEDED`) and finally the billable-set check
    (`ERR_NO_BILLABLE_DELIVERABLES`)."
    PRD 3.6: "The engagement must be `PENDING_COUNTERSIGN` or `ACTIVE`, or the request
    is refused with `ERR_ENGAGEMENT_NOT_ACTIVE`; the athlete must be `ACTIVE` on the
    roster, or it is refused with `ERR_ATHLETE_NOT_BOOKABLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_booking_against_terminated_engagement
    """
    pair = setup_terminated_engagement_over_busy_calendar()
    terminated = pair["deal_a"]
    version = engagement_version(terminated["engagement_id"])

    response = api.create_appearance_booking(
        create_appearance_booking_payload(
            terminated["engagement_id"], version, city="Chicago",
            start_at="2026-09-11T00:00:00Z", end_at="2026-09-11T04:00:00Z",
            travel_buffer_hours=0,
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value, 409)
    assert response.json()["data"]["error_id"] != ApiErrorId.ERR_BOOKING_OVERLAP.value


def test_rejected_booking_leaves_the_engagement_untouched(api):
    """PRD 2.8: "When more than one rule could reject the same request, the rules are
    evaluated in a fixed order and the first failure is the one reported.
    Implementations must honour this ordering, because a request can violate several
    rules at once and only one error id may be returned."
    PRD 2.4: "`version` is an integer that starts at 1 when the resource is created
    and increments by 1 on every mutation of that resource; `updated_at` is refreshed
    on the same occasions."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_temporal_on_booking_against_terminated_engagement
    """
    pair = setup_terminated_engagement_over_busy_calendar()
    terminated = pair["deal_a"]
    version_before = engagement_version(terminated["engagement_id"])

    response = api.create_appearance_booking(
        create_appearance_booking_payload(
            terminated["engagement_id"], version_before, city="Chicago",
            start_at="2026-09-11T00:00:00Z", end_at="2026-09-11T04:00:00Z",
            travel_buffer_hours=0,
        ),
        AGENT,
    )
    validate_error(response, ApiErrorId.ERR_ENGAGEMENT_NOT_ACTIVE.value, 409)

    rows, _meta = validate_paginated(
        api.list_appearance_bookings(
            AGENT, params={"engagement_id": terminated["engagement_id"]}
        )
    )
    assert rows == []
    assert engagement_version(terminated["engagement_id"]) == version_before
