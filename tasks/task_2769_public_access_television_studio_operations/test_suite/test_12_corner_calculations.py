"""Calculation corners: thresholds, input-set filtering, clamps and rounding."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    ADMIN_HEADERS,
    FINANCE_HEADERS,
    SCHEDULER_HEADERS,
    TRAINER_HEADERS,
)


def test_the_pass_mark_is_inclusive_so_seventy_nine_fails_and_eighty_passes(client):
    """The same course grades two producers on either side of the boundary.

    PRD 3.1: "A score of at least 80 drives `ATTENDED → PASSED`; a score below 80
    drives `ATTENDED → FAILED`. Both branches stamp `graded_at` with the current
    logical instant and record the `practical_score`."

    PRD 3.1: "Only the passing branch has consequences beyond the enrollment row:
    the course's `passed_count` rises by 1, the producer's `competency_codes` gains
    every code in that course's `grants_competency_codes`, the producer's
    `certification_level` is re-derived"

    PRD 3.1: "otherwise, if it contains `BASIC`, the level is `BASIC`; otherwise
    `NONE`."

    Design: Corner/calculations/corner_certification_pass_score_threshold_79_versus_80
    """
    first = fx.setup_active_producer(client, legal_name="Ada Lovelace")
    second = fx.setup_active_producer(client, legal_name="Grace Hopper")
    course = fx.publish_course(
        client,
        course_code="TV-101",
        tier="BASIC",
        grants_competency_codes=["STUDIO_FLOOR", "EDIT_SUITE"],
        seat_capacity=12,
        session_start_at="2026-08-05T17:00:00Z",
        session_end_at="2026-08-05T21:00:00Z",
    )
    below = fx.enroll(client, first["id"], course["id"])
    exactly = fx.enroll(client, second["id"], course["id"])
    fx.set_clock(client, "2026-08-06T00:00:00Z")
    fx.mark_attended(client, below["id"], True)
    fx.mark_attended(client, exactly["id"], True)

    failed = fx.grade(client, below["id"], 79)
    passed = fx.grade(client, exactly["id"], 80)

    assert failed["status"] == "FAILED"
    assert failed["practical_score"] == 79
    assert passed["status"] == "PASSED"
    assert passed["practical_score"] == 80

    unqualified = fx.read_producer(client, first["id"])
    assert unqualified["certification_level"] == "NONE"
    assert unqualified["competency_codes"] == []
    qualified = fx.read_producer(client, second["id"])
    assert qualified["certification_level"] == "BASIC"
    assert sorted(qualified["competency_codes"]) == ["EDIT_SUITE", "STUDIO_FLOOR"]

    after = a.data_of(client.get_training_course(course["id"], TRAINER_HEADERS))
    assert after["passed_count"] == 1
    assert after["enrolled_count"] == 2


def test_only_passed_enrollments_feed_the_competency_union(client):
    """An ATTENDED enrollment, and then a FAILED one, both contribute nothing.

    PRD 3.1: "The `competency_codes` list is a derived set, not an append log. It
    is the union of `grants_competency_codes` across every `PASSED` enrollment the
    producer holds, de-duplicated, and ordered by the `graded_at` of the enrollment
    that granted each code, earliest first."

    PRD 3.1: "Only `PASSED` enrollments feed that tier set — `ENROLLED`,
    `ATTENDED`, `FAILED` and `WITHDRAWN` enrollments contribute nothing."

    PRD 3.1: "On the failing branch only the enrollment's `version` increments, no
    competency is granted, and `certification_level` is untouched."

    Design: Corner/calculations/corner_certification_input_set_counts_only_passed_enrollments
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    assert producer["certification_level"] == "BASIC"
    advanced_course = fx.publish_course(
        client,
        course_code="TV-201",
        title="Master Control",
        tier="ADVANCED",
        grants_competency_codes=["AUDIO_BOARD"],
        seat_capacity=8,
        session_start_at="2026-08-12T17:00:00Z",
        session_end_at="2026-08-12T21:00:00Z",
    )
    enrollment = fx.enroll(client, producer["id"], advanced_course["id"])
    fx.set_clock(client, "2026-08-13T00:00:00Z")

    attended = fx.mark_attended(client, enrollment["id"], True)
    midway = fx.read_producer(client, producer["id"])
    failed = fx.grade(client, enrollment["id"], 79)
    ending = fx.read_producer(client, producer["id"])

    assert attended["status"] == "ATTENDED"
    assert midway["certification_level"] == "BASIC"
    assert sorted(midway["competency_codes"]) == ["EDIT_SUITE", "STUDIO_FLOOR"]

    assert failed["status"] == "FAILED"
    assert ending["certification_level"] == "BASIC"
    assert sorted(ending["competency_codes"]) == ["EDIT_SUITE", "STUDIO_FLOOR"]
    assert "AUDIO_BOARD" not in ending["competency_codes"]

    after_course = a.data_of(client.get_training_course(advanced_course["id"], TRAINER_HEADERS))
    assert after_course["enrolled_count"] == 1
    assert after_course["passed_count"] == 0


def test_the_deposit_hold_is_clamped_to_the_assets_replacement_value(client):
    """The clamp is the last step, so the ledger carries the clamped figure.

    PRD 3.6: "Step seven sums the three rounded lines. Step eight clamps the sum
    to the asset's `replacement_value_cents`, taking whichever is smaller, and
    stores the result as `deposit_hold_cents`."

    PRD 3.6: "A clean comparison case, with no suspension points, a two-hour
    window and no live link, gives the base 12345 plus a duration line of 617, for
    a hold of 12962 cents."

    PRD 3.6: "A successful confirmation freezes both `risk_bp` and
    `deposit_hold_cents` on the reservation — neither is ever recomputed afterwards,
    so a later suspension does not retroactively raise an existing hold — raises the
    producer's `deposit_held_cents` by the hold amount, raises the asset's
    `open_reservation_count` by 1"

    Design: Corner/calculations/corner_deposit_hold_clamped_to_resource_replacement_value
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    resource = fx.create_resource(
        client,
        resource_code="CAM-KIT",
        resource_class="FIELD_CAMERA_KIT",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=12345,
        replacement_value_cents=12500,
    )
    requested = fx.request_reservation(
        client, producer["id"], resource["id"],
        start_at="2026-08-08T10:00:00Z", end_at="2026-08-08T12:00:00Z",
    )
    a.assert_cents(requested["deposit_hold_cents"], 0, "deposit_hold_cents")

    confirmed = fx.confirm_reservation(client, requested["id"])

    assert confirmed["status"] == "CONFIRMED"
    a.assert_cents(confirmed["deposit_hold_cents"], 12500, "deposit_hold_cents")
    assert confirmed["risk_bp"] == 0
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=12500)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


def test_the_capital_share_rounds_a_half_cent_tie_upward(client):
    """The residual absorbs the cent, so the three buckets still sum to the total.

    PRD 3.8: "Step three computes `admin_reserve_cents` by multiplying
    `allocable_base_cents` by the chosen basis-point rate, dividing by ten thousand,
    and rounding half up to a whole cent."

    PRD 3.8: "the capital share is that distributable amount multiplied by 3500
    basis points, divided by ten thousand, rounded half up; `capital_allocation_cents`
    is that capital share plus `capital_grant_cents`; and `operating_allocation_cents`
    is the distributable amount less the capital share, taken as an exact residual so
    that no cent is created or lost."

    PRD 3.8: "Submission recomputes `allocable_base_cents`, `admin_reserve_cents`,
    `capital_allocation_cents`, `operating_allocation_cents` and
    `total_program_funds_cents` in the pinned order above, records
    `submitted_by_user_id` as the acting `X-User-ID`, and increments the period's
    `version` by 1."

    Design: Corner/calculations/corner_franchise_capital_share_half_up_tie_keeps_residual_invariant
    """
    period = a.created_of(
        client.create_funding_period(
            f.funding_period_payload(
                fiscal_year=2026,
                quarter=1,
                basis="ACCRUAL",
                gross_franchise_fee_cents=1100000,
                service_period_earned_cents=1000033,
                remittance_received_cents=990000,
                capital_grant_cents=0,
            ),
            FINANCE_HEADERS,
        )
    )
    a.assert_cents(period["allocable_base_cents"], 0, "allocable_base_cents")

    submitted = fx.submit_funding_report(client, period["id"])

    assert submitted["report_status"] == "SUBMITTED"
    a.assert_cents(submitted["allocable_base_cents"], 1000033, "allocable_base_cents")
    a.assert_cents(submitted["admin_reserve_cents"], 80003, "admin_reserve_cents")
    a.assert_cents(submitted["capital_allocation_cents"], 322011, "capital_allocation_cents")
    a.assert_cents(submitted["operating_allocation_cents"], 598019, "operating_allocation_cents")
    a.assert_cents(submitted["total_program_funds_cents"], 1000033, "total_program_funds_cents")
    a.assert_allocation_identity(submitted)


def test_the_impact_index_accumulates_three_components_to_two_decimals(client):
    """Reach, then volunteer credit at publication, then recorded demand.

    PRD 3.9: "The index is 100 multiplied by the weighted sum of the three
    components, with the reach component weighted 0.5, the demand component 0.3 and
    the volunteer component 0.2, and the result rounded half up to two decimal
    places and emitted as a JSON number."

    PRD 3.9: "The `PROVISIONAL` variant is what the system computes the instant a
    program airs, when no on-demand view has yet been recorded and no volunteer
    credit has yet been read: it forces both `on_demand_views` and
    `volunteer_hours_tenths` to 0, so only the reach component contributes."

    PRD 3.9: "Recording on-demand demand is likewise the `CenterAdmin`'s act: the
    caller supplies `on_demand_views` as the cumulative view total, which replaces
    the stored figure rather than adding to it, and the `FINAL` community impact
    index is immediately recomputed from it."

    Design: Corner/calculations/corner_impact_index_three_component_accumulation_rounds_to_two_places
    """
    owner = fx.setup_live_certified_producer(client, legal_name="Ada Lovelace")
    volunteer = fx.setup_active_producer(client, legal_name="Vera Rubin")
    channel = fx.create_channel(client, call_sign="PATV1", inter_program_buffer_seconds=120)
    program = fx.setup_approved_program(
        client, owner["id"], title="Long Form Documentary", runtime_seconds=11760,
        is_live=True, required_crew_roles=["CAMERA"],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")
    assert slot["occupied_seconds"] == 11880
    fx.staff_slot(client, slot["id"], volunteer["id"], "CAMERA")
    fx.set_clock(client, "2026-08-20T18:00:00Z")
    fx.air_slot(client, slot["id"], 333)
    asset = fx.list_assets_for_slot(client, slot["id"])[0]

    assert asset["volunteer_hours_tenths"] == 33
    assert asset["impact_variant"] == "PROVISIONAL"
    a.assert_index_equals(asset["community_impact_index"], 16.65)

    published = fx.publish_asset(client, asset["id"], "STANDARD_24M")

    assert published["impact_variant"] == "FINAL"
    a.assert_index_equals(published["community_impact_index"], 23.25)

    viewed = fx.record_views(client, asset["id"], 167)

    assert viewed["on_demand_views"] == 167
    a.assert_index_equals(viewed["community_impact_index"], 33.27)
    assert viewed["volunteer_hours_tenths"] == 33
    assert viewed["measured_households"] == 333


def test_seniority_is_the_earliest_date_reachable_through_the_whole_chain(client):
    """A three-deep lineage hands the grandchild the grandparent's anchor.

    PRD 3.2: "`seniority_at` is computed by walking backwards along the predecessor
    chain. The walk starts by taking the series' own `first_air_date` as the running
    seniority and marking the series itself as visited, then follows
    `predecessor_series_id` from node to node."

    PRD 3.2: "A new series opens in `PROPOSED` status with a null `seniority_at`,
    and with `hold_plan_slots_granted`, `remaining_hold_slots` and `missed_windows`
    all at 0."

    PRD 3.2: "Every proposed series is stamped with a `sequence_number` drawn from a
    monotone centre-wide counter — 1, 2, 3 and upward in creation order — and this
    number is the system's deterministic tie-break whenever two series present
    identical seniority."

    Design: Corner/calculations/corner_series_seniority_walks_full_predecessor_chain
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    original = fx.propose_series(
        client, producer["id"], title="Riverside Report",
        cadence="WEEKLY", first_air_date="2024-03-01T00:00:00Z",
    )
    middle = fx.propose_series(
        client, producer["id"], title="Riverside Report II",
        cadence="WEEKLY", first_air_date="2025-06-01T00:00:00Z",
        predecessor_series_id=original["id"],
    )
    youngest = fx.propose_series(
        client, producer["id"], title="Riverside Report III",
        cadence="WEEKLY", first_air_date="2026-09-01T00:00:00Z",
        predecessor_series_id=middle["id"],
    )

    assert youngest["status"] == "PROPOSED"
    a.assert_field_absent_or_null(original, "seniority_at")
    assert original["sequence_number"] == 1
    assert middle["sequence_number"] == 2
    assert youngest["sequence_number"] == 3

    first_active = fx.activate_series(client, original["id"])
    second_active = fx.activate_series(client, middle["id"])
    third_active = fx.activate_series(client, youngest["id"])

    a.assert_instant_equals(
        first_active["seniority_at"], "2024-03-01T00:00:00Z", "seniority_at"
    )
    a.assert_instant_equals(
        second_active["seniority_at"], "2024-03-01T00:00:00Z", "seniority_at"
    )
    a.assert_instant_equals(
        third_active["seniority_at"], "2024-03-01T00:00:00Z", "seniority_at"
    )
    assert third_active["status"] == "ACTIVE"
    assert third_active["remaining_hold_slots"] == 0
    assert third_active["missed_windows"] == 0


def _approved_half_hour_program_on_a_buffered_channel(client):
    """A PUBLIC channel closing at minute 1380 and one 1800-second program."""
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(
        client, call_sign="PATV1", tier="PUBLIC",
        daily_window_start_minute=1080, daily_window_end_minute=1380,
        inter_program_buffer_seconds=120,
    )
    program = fx.setup_approved_program(
        client, producer["id"], title="Late Slot Feature", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    return producer, channel, program


def test_a_footprint_ending_exactly_at_the_windows_close_is_admitted(client):
    """One second either side of the window is refused; the boundary itself fits.

    PRD 3.4: "To test window fit, take the requested `start_at`, convert its clock
    time into minutes after UTC midnight by multiplying its hour by 60 and adding its
    minute; this start minute must be at or after the channel's
    `daily_window_start_minute`."

    PRD 3.4: "Then take the same start expressed in seconds after UTC midnight —
    the start minute multiplied by 60, plus the start instant's seconds — and add
    `occupied_seconds`; the result must be at or below the channel's
    `daily_window_end_minute` multiplied by 60. If either comparison fails, the
    booking is refused with `ERR_SLOT_OUTSIDE_CHANNEL_WINDOW` (422)."

    PRD 3.4: "All of this arithmetic is in whole seconds with no rounding anywhere."

    Design: Corner/calculations/corner_channel_window_end_boundary_admits_footprint_ending_at_close
    """
    _producer, channel, program = _approved_half_hour_program_on_a_buffered_channel(client)

    a.error_of(
        client.create_playback_slot(
            f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T17:59:59Z"),
            SCHEDULER_HEADERS,
        ),
        e.ERR_SLOT_OUTSIDE_CHANNEL_WINDOW,
        422,
    )
    a.error_of(
        client.create_playback_slot(
            f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T22:28:01Z"),
            SCHEDULER_HEADERS,
        ),
        e.ERR_SLOT_OUTSIDE_CHANNEL_WINDOW,
        422,
    )

    slot = a.created_of(
        client.create_playback_slot(
            f.playback_slot_payload(channel["id"], program["id"], "2026-08-20T22:28:00Z"),
            SCHEDULER_HEADERS,
        )
    )

    assert slot["status"] == "SCHEDULED"
    assert slot["occupied_seconds"] == 1920
    a.assert_instant_equals(slot["end_at"], "2026-08-20T23:00:00Z", "end_at")
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 1920, 0)
    booked, _meta = a.assert_pagination_meta(
        client.list_playback_slots(SCHEDULER_HEADERS, {"channel_id": channel["id"]}), 1
    )
    a.assert_ids_equal(booked, [slot["id"]])


def test_only_a_strictly_earlier_seniority_displaces_a_first_come_incumbent(client):
    """The incumbent's own created_at is the key the challenger must beat.

    PRD 3.4: "For each displaceable incumbent, form its priority key: where the
    incumbent itself names a series, the key is that series' `seniority_at`; where
    the incumbent is an unaffiliated first-come booking, the key is the incumbent
    slot's own `created_at`. The challenger wins outright when its series'
    `seniority_at` is strictly earlier than that key."

    PRD 3.4: "In every other case the strictly-earlier requirement is unmet and the
    request is refused with `ERR_SLOT_WINDOW_CONFLICT` (409). Timestamp comparisons
    here are at second precision."

    PRD 3.4: "A displaced incumbent's own transition is more than a status change.
    `preempted_by_slot_id` is set to the challenger slot's identifier, the channel's
    `scheduled_seconds` falls by that incumbent's `occupied_seconds`"

    Design: Corner/calculations/corner_series_seniority_preempts_first_come_incumbent_by_timestamp
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(client, call_sign="PATV1")
    assert channel["preemption_enabled"] is True
    junior = fx.setup_active_series_with_hold_plan(
        client, producer["id"], 2, title="Junior Strand",
        first_air_date="2026-09-01T00:00:00Z",
    )
    senior = fx.setup_active_series_with_hold_plan(
        client, producer["id"], 2, title="Senior Strand",
        first_air_date="2024-03-01T00:00:00Z",
    )
    incumbent_program = fx.setup_approved_program(
        client, producer["id"], title="Incumbent Show", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    challenger_program = fx.setup_approved_program(
        client, producer["id"], title="Challenger Show", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    incumbent = fx.book_slot(
        client, channel["id"], incumbent_program["id"], "2026-08-20T18:00:00Z"
    )
    assert incumbent["booking_type"] == "FIRST_COME"
    a.assert_instant_equals(junior["seniority_at"], "2026-09-01T00:00:00Z", "seniority_at")
    a.assert_instant_equals(senior["seniority_at"], "2024-03-01T00:00:00Z", "seniority_at")

    refused = client.create_playback_slot(
        f.playback_slot_payload(
            channel["id"], challenger_program["id"], "2026-08-20T18:00:00Z",
            series_id=junior["id"],
        ),
        SCHEDULER_HEADERS,
    )

    a.error_of(refused, e.ERR_SLOT_WINDOW_CONFLICT, 409)
    assert fx.read_series(client, junior["id"])["remaining_hold_slots"] == 2
    assert fx.read_slot(client, incumbent["id"])["status"] == "SCHEDULED"

    challenger = a.created_of(
        client.create_playback_slot(
            f.playback_slot_payload(
                channel["id"], challenger_program["id"], "2026-08-20T18:00:00Z",
                series_id=senior["id"],
            ),
            SCHEDULER_HEADERS,
        )
    )

    assert challenger["booking_type"] == "SERIES_HOLD"
    assert fx.read_series(client, senior["id"])["remaining_hold_slots"] == 1
    displaced = fx.read_slot(client, incumbent["id"])
    assert displaced["status"] == "PREEMPTED"
    assert displaced["preempted_by_slot_id"] == challenger["id"]
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 1920, 0)


def test_retention_counts_calendar_months_and_clamps_a_leap_day(client):
    """Publishing on 29 February retains to 28 February, and the boundary is inclusive.

    PRD 3.9: "Where a month count applies, `retain_until` is `published_at` advanced
    by that many calendar months, keeping the same day-of-month and the same
    time-of-day; where the target month is too short to contain that day-of-month,
    the day clamps to that month's last day."

    PRD 3.9: "Otherwise the retention window must have elapsed, and the boundary is
    inclusive: the asset becomes purgeable at the `retain_until` instant itself, so a
    purge at one second before `retain_until` is refused with
    `ERR_RETENTION_NOT_ELAPSED` (409) while a purge at exactly `retain_until`
    succeeds."

    PRD 3.9: "The asset opens in `PENDING` on-demand status with `impact_variant`
    marked `PROVISIONAL`, with `on_demand_views` at 0, and with `retention_class`,
    `retain_until`, `published_at` and `purged_at` all null — a pending asset has no
    retention deadline at all."

    Design: Corner/calculations/corner_retention_calendar_months_clamp_to_short_month
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client, producer["id"], title="Leap Day Special", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2028-02-29T18:00:00Z")
    fx.set_clock(client, "2028-02-29T18:00:00Z")
    fx.air_slot(client, slot["id"], 500)
    asset = fx.list_assets_for_slot(client, slot["id"])[0]
    assert asset["on_demand_status"] == "PENDING"
    a.assert_field_absent_or_null(asset, "retain_until")

    published = fx.publish_asset(client, asset["id"], "STANDARD_24M")

    assert published["on_demand_status"] == "PUBLISHED"
    a.assert_instant_equals(published["published_at"], "2028-02-29T18:00:00Z", "published_at")
    a.assert_instant_equals(published["retain_until"], "2030-02-28T18:00:00Z", "retain_until")
    a.assert_index_equals(published["community_impact_index"], 25.00)

    fx.set_clock(client, "2030-02-28T17:59:59Z")
    early = client.purge_archive_asset(asset["id"], {}, ADMIN_HEADERS)

    a.error_of(early, e.ERR_RETENTION_NOT_ELAPSED, 409)
    assert fx.read_asset(client, asset["id"])["on_demand_status"] == "PUBLISHED"

    fx.set_clock(client, "2030-02-28T18:00:00Z")
    purged = fx.purge_asset(client, asset["id"])

    assert purged["on_demand_status"] == "PURGED"
    a.assert_instant_equals(purged["purged_at"], "2030-02-28T18:00:00Z", "purged_at")


def test_a_permanently_retained_asset_is_never_purgeable(client):
    """A null retention deadline is not an elapsed one, and the error says so.

    PRD 3.9: "A `STANDARD_24M` asset retains for 24 calendar months and an
    `EXTENDED_60M` asset for 60; a `PERMANENT` asset has no retention months at all
    and its `retain_until` stays null."

    PRD 3.9: "An asset whose `retention_class` is `PERMANENT` can never be purged,
    and the attempt is refused with `ERR_PERMANENT_RETENTION` (409)."

    Design: Corner/calculations/corner_permanent_retention_constant_blocks_purge_forever
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    _channel, _program, _slot, asset = fx.setup_aired_slot_with_asset(
        client, producer["id"], "2026-08-20T18:00:00Z", 500,
        title="Founders Interview", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )

    published = fx.publish_asset(client, asset["id"], "PERMANENT")

    assert published["on_demand_status"] == "PUBLISHED"
    assert published["retention_class"] == "PERMANENT"
    a.assert_field_absent_or_null(published, "retain_until")

    fx.set_clock(client, "2040-01-01T00:00:00Z")
    refused = client.purge_archive_asset(asset["id"], {}, ADMIN_HEADERS)

    a.error_of(refused, e.ERR_PERMANENT_RETENTION, 409)
    still = fx.read_asset(client, asset["id"])
    assert still["on_demand_status"] == "PUBLISHED"
    a.assert_field_absent_or_null(still, "purged_at")


def test_a_slot_with_no_declared_roles_never_needs_a_volunteer(client):
    """An empty role list short-circuits readiness, so the slot airs uncrewed.

    PRD 3.5: "When a slot's frozen `required_crew_roles` list is empty, its
    `staffing_status` is `NOT_REQUIRED` and it can never become `UNDERSTAFFED`."

    PRD 3.4: "`staffing_status` is initialised to `NOT_REQUIRED` when the frozen
    `required_crew_roles` list is empty, and to `UNDERSTAFFED` otherwise."

    PRD 3.9: "`volunteer_hours_tenths` is the sum of `credited_hours_tenths` over
    that slot's `COMPLETED` crew assignments"

    Design: Corner/calculations/corner_crew_readiness_not_required_when_no_roles_declared
    """
    producer = fx.setup_basic_certified_producer(client, score=88, legal_name="Ada Lovelace")
    channel = fx.create_channel(client, call_sign="PATV1")
    program = fx.setup_approved_program(
        client, producer["id"], title="Solo Taped Show", runtime_seconds=1800,
        is_live=False, required_crew_roles=[],
    )
    slot = fx.book_slot(client, channel["id"], program["id"], "2026-08-20T18:00:00Z")

    assert slot["required_crew_roles"] == []
    assert slot["staffing_status"] == "NOT_REQUIRED"

    crew, _meta = a.assert_pagination_meta(
        client.list_crew_assignments(SCHEDULER_HEADERS, {"slot_id": slot["id"]}), 0
    )
    assert crew == []

    fx.set_clock(client, "2026-08-20T18:00:00Z")
    aired = fx.air_slot(client, slot["id"], 500)

    assert aired["status"] == "AIRED"
    assert aired["staffing_status"] == "NOT_REQUIRED"
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), volunteer_tenths=0)
    asset = fx.list_assets_for_slot(client, slot["id"])[0]
    assert asset["volunteer_hours_tenths"] == 0
    a.assert_index_equals(asset["community_impact_index"], 25.00)
