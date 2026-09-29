"""The same /mail call is refused twice and then accepted, with only the clock moving.

Nothing about the drop changes between the refusals and the acceptance: it sits in a
perfectly legal `PRESORTED` on an approved plan the whole time, so the 409 comes purely
from `in_home_date` being ahead of the logical clock. One day early is still early. When
the call finally lands, the two timestamps it produces deliberately disagree — `mailed_at`
is taken from the clock while the cascade's contact event is dated on the in-home date —
and the measurement dimension is left alone through both accepted transitions.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    PLANNER,
    assert_contact_event,
    assert_drop,
    assert_instant_equals,
    fetch_drop,
    iso_utc,
    set_clock,
    setup_presorted_drop,
    timestamps_equal,
    validate_error,
    validate_paginated,
    validate_success,
)

IN_HOME = iso_utc("2026-09-15")
ONE_DAY_EARLY = iso_utc("2026-09-14")
ONE_DAY_LATE = iso_utc("2026-09-16")


def _a_presorted_drop_whose_in_home_date_is_still_ahead() -> dict:
    """Drop 1 of the approved plan: in-home 2026-09-15, 64 pages, a single FIVE_DIGIT
    batch covering its 20000 allocated books, and the clock still at 2026-08-01."""
    set_clock(CLOCK_START)
    world = setup_presorted_drop()
    assert world["drop"]["production_status"] == "PRESORTED"
    assert world["drop"]["measurement_status"] == "PENDING"
    assert world["plan"]["status"] == "APPROVED"
    return world


class TestMailIsRefusedWhileTheInHomeDateIsAhead:
    def test_mailing_six_weeks_early_is_an_invalid_drop_state(self, api):
        """PRD §3.7: "Mailing takes the drop `PRESORTED → MAILED`, requires the drop's
        `in_home_date` to be at or before the logical clock's current value (an earlier
        attempt is rejected with `ERR_INVALID_DROP_STATE`), and stamps `mailed_at` with the
        logical clock's current instant."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        assert_instant_equals(world["drop"]["in_home_date"], IN_HOME, "in_home_date")

        response = api.mail_drop(world["drop"]["id"], PLANNER)
        validate_error(response, "ERR_INVALID_DROP_STATE", 409)

    def test_mailing_one_single_day_early_is_still_early(self, api):
        """PRD §3.7: "Mailing takes the drop `PRESORTED → MAILED`, requires the drop's
        `in_home_date` to be at or before the logical clock's current value (an earlier
        attempt is rejected with `ERR_INVALID_DROP_STATE`), and stamps `mailed_at` with the
        logical clock's current instant."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        set_clock(ONE_DAY_EARLY)

        response = api.mail_drop(world["drop"]["id"], PLANNER)
        validate_error(response, "ERR_INVALID_DROP_STATE", 409)

    def test_no_cascade_contact_event_exists_while_mail_keeps_being_refused(self, api):
        """PRD §3.7: "For every circulation line of this drop in status `ALLOCATED` whose
        `housefile_segment_id` is non-null, a contact event is created carrying that
        `housefile_segment_id`, this drop's identifier as its `drop_id`, a `channel` of
        `MAIL`, a `contact_date` equal to the drop's `in_home_date`, and a `source` of
        `DROP_MAIL_CASCADE`."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        drop_id = world["drop"]["id"]
        validate_error(api.mail_drop(drop_id, PLANNER), "ERR_INVALID_DROP_STATE", 409)
        set_clock(ONE_DAY_EARLY)
        validate_error(api.mail_drop(drop_id, PLANNER), "ERR_INVALID_DROP_STATE", 409)

        _, meta = validate_paginated(api.list_drop_contact_events(drop_id, ANALYST))
        assert meta["total_count"] == 0


class TestTheProductionStepCannotBeSkipped:
    def test_delivering_a_presorted_drop_is_refused_and_leaves_it_presorted(self, api):
        """PRD §3.7: "The mailed drop's own `version` increments by one as well. Delivery
        is the quiet final step: `MAILED → DELIVERED` increments the drop's `version` by
        one and does nothing else, leaving `measurement_status` deliberately untouched
        because the two dimensions never synchronise."
        PRD §2.10: "**The requested transition exists from the entity's current state**,
        on every action endpoint — otherwise the matching 409 code:
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DROP_STATE`,
        `ERR_INVALID_MEASUREMENT_STATE`, `ERR_INVALID_RENTAL_STATE`,
        `ERR_INVALID_LINE_STATE`, `ERR_INVALID_TEST_CELL_STATE` or
        `ERR_INVALID_MATCHBACK_STATE`."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()

        response = api.deliver_drop(world["drop"]["id"], PLANNER)
        validate_error(response, "ERR_INVALID_DROP_STATE", 409)
        assert fetch_drop(world["drop"]["id"], PLANNER)["production_status"] == (
            "PRESORTED"
        )


class TestTheClockReachingTheDateIsTheOnlyThingThatChanges:
    def test_mailing_a_day_after_the_in_home_date_stamps_the_clock(self, api):
        """PRD §3.7: "Mailing takes the drop `PRESORTED → MAILED`, requires the drop's
        `in_home_date` to be at or before the logical clock's current value (an earlier
        attempt is rejected with `ERR_INVALID_DROP_STATE`), and stamps `mailed_at` with the
        logical clock's current instant."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        validate_error(
            api.mail_drop(world["drop"]["id"], PLANNER), "ERR_INVALID_DROP_STATE", 409
        )
        set_clock(ONE_DAY_LATE)

        mailed = validate_success(api.mail_drop(world["drop"]["id"], PLANNER), 200)
        assert_drop(mailed)
        assert mailed["production_status"] == "MAILED"
        assert_instant_equals(mailed["mailed_at"], ONE_DAY_LATE, "mailed_at")

    def test_the_cascade_dates_its_contact_on_the_in_home_date_instead(self, api):
        """PRD §3.7: "For every circulation line of this drop in status `ALLOCATED` whose
        `housefile_segment_id` is non-null, a contact event is created carrying that
        `housefile_segment_id`, this drop's identifier as its `drop_id`, a `channel` of
        `MAIL`, a `contact_date` equal to the drop's `in_home_date`, and a `source` of
        `DROP_MAIL_CASCADE`."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        drop_id = world["drop"]["id"]
        set_clock(ONE_DAY_LATE)
        mailed = validate_success(api.mail_drop(drop_id, PLANNER), 200)

        rows, meta = validate_paginated(
            api.list_drop_contact_events(drop_id, ANALYST, params={"channel": "MAIL"})
        )
        assert meta["total_count"] == 1
        event = rows[0]
        assert_contact_event(event)
        assert event["source"] == "DROP_MAIL_CASCADE"
        assert event["channel"] == "MAIL"
        assert event["drop_id"] == drop_id
        assert event["housefile_segment_id"] == world["segment"]["id"]
        assert_instant_equals(event["contact_date"], IN_HOME, "contact_date")
        assert not timestamps_equal(event["contact_date"], mailed["mailed_at"])

    def test_delivery_follows_the_mailing_and_neither_touches_measurement(self, api):
        """PRD §3.7: "The mailed drop's own `version` increments by one as well. Delivery
        is the quiet final step: `MAILED → DELIVERED` increments the drop's `version` by
        one and does nothing else, leaving `measurement_status` deliberately untouched
        because the two dimensions never synchronise."
        PRD §3.7: "A drop's `production_status` and its `measurement_status` are two
        parallel dimensions that advance independently."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        drop_id = world["drop"]["id"]
        set_clock(ONE_DAY_LATE)

        mailed = validate_success(api.mail_drop(drop_id, PLANNER), 200)
        assert mailed["measurement_status"] == "PENDING"

        delivered = validate_success(api.deliver_drop(drop_id, PLANNER), 200)
        assert delivered["production_status"] == "DELIVERED"
        assert delivered["measurement_status"] == "PENDING"

    def test_only_the_two_accepted_transitions_moved_the_drops_version(self, api):
        """PRD §2.4: "`updated_at` is refreshed to the current instant on every mutation
        of the row, and `version` is an integer that starts at 1 on creation and increments
        by exactly 1 on every mutation — including mutations the row's owner did not
        request, such as a cascade reaching it from another aggregate."

        Design: Corner/endpoints/mail_is_allowed_only_once_the_clock_reaches_the_in_home_date
        """
        world = _a_presorted_drop_whose_in_home_date_is_still_ahead()
        drop_id = world["drop"]["id"]
        presorted_version = fetch_drop(drop_id, PLANNER)["version"]

        validate_error(api.mail_drop(drop_id, PLANNER), "ERR_INVALID_DROP_STATE", 409)
        validate_error(
            api.deliver_drop(drop_id, PLANNER), "ERR_INVALID_DROP_STATE", 409
        )
        set_clock(ONE_DAY_EARLY)
        validate_error(api.mail_drop(drop_id, PLANNER), "ERR_INVALID_DROP_STATE", 409)
        assert fetch_drop(drop_id, PLANNER)["version"] == presorted_version

        set_clock(ONE_DAY_LATE)
        mailed = validate_success(api.mail_drop(drop_id, PLANNER), 200)
        assert mailed["version"] == presorted_version + 1

        delivered = validate_success(api.deliver_drop(drop_id, PLANNER), 200)
        assert delivered["version"] == presorted_version + 2
