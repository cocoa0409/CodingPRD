"""
Examination booking: interval semantics, band precedence and the slot ledger.

Every site here is configured explicitly, because capacity and the trailing
buffer are what decide whether a block overlaps.
"""

import pytest
from test_helpers import (
    CLOCK_START_INSTANT,
    assert_exact_whole,
    assert_pct_2dp,
    book_appointment,
    cancel_appointment_action,
    complete_appointment_action,
    complete_prep_action,
    conditions,
    create_active_representative,
    create_claim_in_evidence_development,
    create_exam_site,
    create_represented_veteran,
    exam_appointment_payload,
    instant,
    read_claim,
    read_claim_evidence,
    read_exam_site,
    set_clock,
    set_clock_date,
    validate_error,
    validate_success,
)


def _single_condition_claim(api):
    """A claim in EVIDENCE_DEVELOPMENT with no evidence on file yet."""
    preparer = create_active_representative(
        api, accreditation_type="COUNTY_CVSO", accreditation_expires_on="2029-12-31"
    )
    base = create_represented_veteran(api, designee=preparer)
    return create_claim_in_evidence_development(
        api, base, claimed_conditions=conditions("tinnitus")
    )


@pytest.fixture
def past_booking_at_a_full_site(api):
    """A capacity-one site holding one appointment that the clock has moved past."""
    set_clock(api, CLOCK_START_INSTANT)
    ctx = _single_condition_claim(api)
    site = create_exam_site(api, concurrent_capacity=1, buffer_minutes=15)
    book_appointment(
        api,
        ctx["claim"]["id"],
        site["id"],
        instant("2026-08-20", "09:00:00"),
        instant("2026-08-20", "10:00:00"),
        ctx["officer_headers"],
    )
    set_clock_date(api, "2026-09-01", "08:00:00")
    return {"ctx": ctx, "site_id": site["id"]}


@pytest.fixture
def two_capacity_site(api):
    """A capacity-two site with two overlapping appointments already booked."""
    set_clock(api, CLOCK_START_INSTANT)
    ctx = _single_condition_claim(api)
    site = create_exam_site(api, concurrent_capacity=2, buffer_minutes=15)
    first = book_appointment(
        api,
        ctx["claim"]["id"],
        site["id"],
        instant("2026-09-01", "09:00:00"),
        instant("2026-09-01", "10:00:00"),
        ctx["officer_headers"],
    )
    second = book_appointment(
        api,
        ctx["claim"]["id"],
        site["id"],
        instant("2026-09-01", "09:30:00"),
        instant("2026-09-01", "10:30:00"),
        ctx["officer_headers"],
    )
    return {"ctx": ctx, "site_id": site["id"], "first": first, "second": second}


@pytest.fixture
def single_slot_site(api):
    """A capacity-one site with its only slot taken."""
    set_clock(api, CLOCK_START_INSTANT)
    ctx = _single_condition_claim(api)
    site = create_exam_site(api, concurrent_capacity=1, buffer_minutes=15)
    appointment = book_appointment(
        api,
        ctx["claim"]["id"],
        site["id"],
        instant("2026-08-20", "09:00:00"),
        instant("2026-08-20", "10:00:00"),
        ctx["officer_headers"],
    )
    return {"ctx": ctx, "site_id": site["id"], "appointment": appointment}


class TestPastBookingBeatsCapacity:
    """A past start is a band-six refusal, ahead of the band-eight capacity test."""

    def test_a_past_start_is_refused_before_capacity_is_consulted(
        self, api, past_booking_at_a_full_site
    ):
        """
        "The `starts_at` instant must be at or after the logical-clock instant: an examination may not be booked into the past, and the attempt is refused with `ERR_APPOINTMENT_IN_PAST` at HTTP 409."

        Design: Difficulty/priority_pair_validation_conflict/booking_past_appointment_into_full_site_returns_appointment_in_past
        """
        ctx = past_booking_at_a_full_site["ctx"]
        response = api.create_exam_appointment(
            exam_appointment_payload(
                ctx["claim"]["id"],
                past_booking_at_a_full_site["site_id"],
                instant("2026-08-20", "09:30:00"),
                instant("2026-08-20", "10:30:00"),
            ),
            ctx["officer_headers"],
        )
        validate_error(response, "ERR_APPOINTMENT_IN_PAST", 409)

    def test_the_capacity_refusal_never_surfaces_for_a_past_window(
        self, api, past_booking_at_a_full_site
    ):
        """
        The requested window would also have exhausted the single slot, but the
        capacity test lives in "**Band 8 — constraint satisfaction.**" behind
        "**Band 6 — temporal rules.**", so the temporal code is the answer.

        Design: Difficulty/priority_pair_validation_conflict/booking_past_appointment_into_full_site_returns_appointment_in_past
        """
        ctx = past_booking_at_a_full_site["ctx"]
        error = validate_error(
            api.create_exam_appointment(
                exam_appointment_payload(
                    ctx["claim"]["id"],
                    past_booking_at_a_full_site["site_id"],
                    instant("2026-08-20", "09:30:00"),
                    instant("2026-08-20", "10:30:00"),
                ),
                ctx["officer_headers"],
            ),
            "ERR_APPOINTMENT_IN_PAST",
            409,
        )
        assert error["error_id"] != "ERR_EXAM_SITE_CAPACITY_EXCEEDED"

    def test_the_site_ledger_is_left_at_its_single_booking(
        self, api, past_booking_at_a_full_site
    ):
        """
        A refused booking writes nothing, and a successful one
        "increments the site's `booked_slot_count` by 1 and the site's `version` by 1".

        Design: Difficulty/priority_pair_validation_conflict/booking_past_appointment_into_full_site_returns_appointment_in_past
        """
        ctx = past_booking_at_a_full_site["ctx"]
        api.create_exam_appointment(
            exam_appointment_payload(
                ctx["claim"]["id"],
                past_booking_at_a_full_site["site_id"],
                instant("2026-08-20", "09:30:00"),
                instant("2026-08-20", "10:30:00"),
            ),
            ctx["officer_headers"],
        )
        site = read_exam_site(api, past_booking_at_a_full_site["site_id"])
        assert_exact_whole(site["booked_slot_count"], 1, "booked_slot_count")


class TestTouchingBlocksAndTheThirdConcurrentBooking:
    """A block starting exactly at a buffered end fits; the one that makes three does not."""

    def test_a_block_starting_at_a_buffered_end_is_admitted(self, api, two_capacity_site):
        """
        "Because both comparisons are strict, a new appointment beginning at exactly the instant a previous block ends — that is, exactly at the earlier appointment's `ends_at` plus the buffer — does **not** overlap it."

        Design: Difficulty/resource_temporal_overlap/exam_site_admits_touching_block_then_rejects_the_one_that_makes_three_concurrent
        """
        ctx = two_capacity_site["ctx"]
        third = validate_success(
            api.create_exam_appointment(
                exam_appointment_payload(
                    ctx["claim"]["id"],
                    two_capacity_site["site_id"],
                    instant("2026-09-01", "10:15:00"),
                    instant("2026-09-01", "11:00:00"),
                ),
                ctx["officer_headers"],
            ),
            201,
        )
        assert third["status"] == "SCHEDULED"
        assert third["prep_session_completed"] is False
        site = read_exam_site(api, two_capacity_site["site_id"])
        assert_exact_whole(site["booked_slot_count"], 3, "booked_slot_count")

    def test_the_booking_that_makes_three_concurrent_is_refused(
        self, api, two_capacity_site
    ):
        """
        "Count the overlapping `SCHEDULED` appointments; if that count is greater than or equal to the site's `concurrent_capacity` the booking is refused with `ERR_EXAM_SITE_CAPACITY_EXCEEDED` at HTTP 409."

        Design: Difficulty/resource_temporal_overlap/exam_site_admits_touching_block_then_rejects_the_one_that_makes_three_concurrent
        """
        ctx = two_capacity_site["ctx"]
        validate_success(
            api.create_exam_appointment(
                exam_appointment_payload(
                    ctx["claim"]["id"],
                    two_capacity_site["site_id"],
                    instant("2026-09-01", "10:15:00"),
                    instant("2026-09-01", "11:00:00"),
                ),
                ctx["officer_headers"],
            ),
            201,
        )
        response = api.create_exam_appointment(
            exam_appointment_payload(
                ctx["claim"]["id"],
                two_capacity_site["site_id"],
                instant("2026-09-01", "09:45:00"),
                instant("2026-09-01", "10:05:00"),
            ),
            ctx["officer_headers"],
        )
        validate_error(response, "ERR_EXAM_SITE_CAPACITY_EXCEEDED", 409)

    def test_the_refused_third_overlap_leaves_the_ledger_at_three(
        self, api, two_capacity_site
    ):
        """
        "A capacity of 2 therefore admits a second concurrent examination and refuses the third."
        The admitted touching block still counts as a booking of the site.

        Design: Difficulty/resource_temporal_overlap/exam_site_admits_touching_block_then_rejects_the_one_that_makes_three_concurrent
        """
        ctx = two_capacity_site["ctx"]
        validate_success(
            api.create_exam_appointment(
                exam_appointment_payload(
                    ctx["claim"]["id"],
                    two_capacity_site["site_id"],
                    instant("2026-09-01", "10:15:00"),
                    instant("2026-09-01", "11:00:00"),
                ),
                ctx["officer_headers"],
            ),
            201,
        )
        api.create_exam_appointment(
            exam_appointment_payload(
                ctx["claim"]["id"],
                two_capacity_site["site_id"],
                instant("2026-09-01", "09:45:00"),
                instant("2026-09-01", "10:05:00"),
            ),
            ctx["officer_headers"],
        )
        site = read_exam_site(api, two_capacity_site["site_id"])
        assert_exact_whole(site["booked_slot_count"], 3, "booked_slot_count")


class TestCancellationFreesTheSlot:
    """Cancelling restores the ledger, so the identical window can be rebooked."""

    def test_the_taken_slot_refuses_an_identical_window(self, api, single_slot_site):
        """
        The occupied block is computed the same way for both sides, and
        "Each existing appointment at the same site whose `status` is `SCHEDULED` occupies a block computed the same way, from its own `starts_at` up to but not including its own `ends_at` plus the same `buffer_minutes`."

        Design: Difficulty/compensating_invariant/cancelling_an_appointment_frees_the_slot_so_the_same_window_can_be_rebooked_and_closed_out
        """
        ctx = single_slot_site["ctx"]
        site = read_exam_site(api, single_slot_site["site_id"])
        assert_exact_whole(site["booked_slot_count"], 1, "booked_slot_count")
        response = api.create_exam_appointment(
            exam_appointment_payload(
                ctx["claim"]["id"],
                single_slot_site["site_id"],
                instant("2026-08-20", "09:00:00"),
                instant("2026-08-20", "10:00:00"),
            ),
            ctx["officer_headers"],
        )
        validate_error(response, "ERR_EXAM_SITE_CAPACITY_EXCEEDED", 409)

    def test_cancelling_returns_the_ledger_and_admits_the_rebooking(
        self, api, single_slot_site
    ):
        """
        Cancelling "sets `status` to `CANCELLED` and likewise decrements `booked_slot_count` by 1, restoring the site's ledger to its pre-booking value",
        and "Appointments in `COMPLETED`, `NO_SHOW` or `CANCELLED` free their block immediately and are never considered."

        Design: Difficulty/compensating_invariant/cancelling_an_appointment_frees_the_slot_so_the_same_window_can_be_rebooked_and_closed_out
        """
        ctx = single_slot_site["ctx"]
        cancelled = validate_success(
            api.exam_appointment_status(
                single_slot_site["appointment"]["id"],
                cancel_appointment_action("Later date requested"),
                ctx["officer_headers"],
            )
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["cancellation_reason"] == "Later date requested"
        assert_exact_whole(
            read_exam_site(api, single_slot_site["site_id"])["booked_slot_count"],
            0,
            "booked_slot_count",
        )
        rebooked = validate_success(
            api.create_exam_appointment(
                exam_appointment_payload(
                    ctx["claim"]["id"],
                    single_slot_site["site_id"],
                    instant("2026-08-20", "09:00:00"),
                    instant("2026-08-20", "10:00:00"),
                ),
                ctx["officer_headers"],
            ),
            201,
        )
        assert rebooked["status"] == "SCHEDULED"
        assert_exact_whole(
            read_exam_site(api, single_slot_site["site_id"])["booked_slot_count"],
            1,
            "booked_slot_count",
        )

    def test_closing_the_rebooked_examination_releases_the_slot_again(
        self, api, single_slot_site
    ):
        """
        "All three exits are terminal, and every one of them releases exactly one slot, which is why the slot invariant of §2.8 holds no matter which path an appointment takes"
        — the completion path included.

        Design: Difficulty/compensating_invariant/cancelling_an_appointment_frees_the_slot_so_the_same_window_can_be_rebooked_and_closed_out
        """
        ctx = single_slot_site["ctx"]
        validate_success(
            api.exam_appointment_status(
                single_slot_site["appointment"]["id"],
                cancel_appointment_action("Later date requested"),
                ctx["officer_headers"],
            )
        )
        rebooked = validate_success(
            api.create_exam_appointment(
                exam_appointment_payload(
                    ctx["claim"]["id"],
                    single_slot_site["site_id"],
                    instant("2026-08-20", "09:00:00"),
                    instant("2026-08-20", "10:00:00"),
                ),
                ctx["officer_headers"],
            ),
            201,
        )
        set_clock_date(api, "2026-08-20", "12:00:00")
        validate_success(
            api.exam_appointment_status(
                rebooked["id"], complete_prep_action(), ctx["officer_headers"]
            )
        )
        completed = validate_success(
            api.exam_appointment_status(
                rebooked["id"],
                complete_appointment_action("2026-08-20"),
                ctx["officer_headers"],
            )
        )
        assert completed["status"] == "COMPLETED"
        assert_exact_whole(
            read_exam_site(api, single_slot_site["site_id"])["booked_slot_count"],
            0,
            "booked_slot_count",
        )

    def test_completion_synthesizes_exactly_one_received_examination_report(
        self, api, single_slot_site
    ):
        """
        Completion "**synthesizes a new evidence item on the linked claim**: `evidence_type` `DBQ`, `status` `RECEIVED`, `received_on` equal to the appointment's `completed_on`, `nexus_opinion_strength` `NONE`, and `auto_generated` true."

        Design: Difficulty/compensating_invariant/cancelling_an_appointment_frees_the_slot_so_the_same_window_can_be_rebooked_and_closed_out
        """
        ctx = single_slot_site["ctx"]
        set_clock_date(api, "2026-08-20", "12:00:00")
        validate_success(
            api.exam_appointment_status(
                single_slot_site["appointment"]["id"],
                complete_prep_action(),
                ctx["officer_headers"],
            )
        )
        validate_success(
            api.exam_appointment_status(
                single_slot_site["appointment"]["id"],
                complete_appointment_action("2026-08-20"),
                ctx["officer_headers"],
            )
        )
        items = read_claim_evidence(api, ctx["claim"]["id"], ctx["officer_headers"])
        synthesized = [item for item in items if item["auto_generated"] is True]
        assert len(synthesized) == 1
        assert synthesized[0]["evidence_type"] == "DBQ"
        assert synthesized[0]["status"] == "RECEIVED"
        assert synthesized[0]["received_on"] == "2026-08-20"
        claim = read_claim(api, ctx["claim"]["id"], ctx["officer_headers"])
        assert_pct_2dp(claim["evidence_completeness_pct"], 31.82)
