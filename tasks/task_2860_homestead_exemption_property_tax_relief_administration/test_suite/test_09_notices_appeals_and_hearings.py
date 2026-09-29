"""Statutory notices and the road from an adverse decision to a hearing.

Every adverse decision is mailed as a notice carrying its own appeal deadline, and
two independent rules then stand between a filed appeal and a hearing: the
requested interval must stay more than a quarter of an hour clear of every slot
already held on that docket, and the docket must still have room in its capacity.
The two fail with different errors, and only one can be undone by a continuance.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_APPEAL_ALREADY_EXISTS,
    ERR_APPEAL_DEADLINE_PASSED,
    ERR_APPEAL_NOT_SCHEDULABLE,
    ERR_APPEAL_NOT_SCHEDULED,
    ERR_CONTINUANCE_LIMIT_REACHED,
    ERR_DOCKET_CAPACITY_REACHED,
    ERR_DOCKET_CLOSED,
    ERR_DUPLICATE_GRANT,
    ERR_HEARING_SLOT_CONFLICT,
    ERR_STALE_PARCEL_VERSION,
)
from test_helpers.assertions import (
    assert_grant,
    assert_instant,
    assert_parcel_decomposition,
    ids_of,
)
from test_helpers.test_users import (
    ANALYST,
    CLERK,
    HEARING_CLERK,
    HEARING_OFFICER,
    HEARING_OFFICER_USER_ID,
    REVIEWER,
    REVIEWER_2,
)


def _docket_with_one_booked_hearing(api, capacity=4):
    """Two filed appeals and a docket on which the first already holds an hour.

    The session runs from 09:00Z to 17:00Z on 2026-09-10 and the booked hearing
    takes 10:00Z to 11:00Z, leaving the whole afternoon free.
    """
    world = fx.appeal_world(api, claimants=2, capacity=capacity)
    first, second = world["appeals"]
    world["first_appeal"] = fx.schedule(
        api,
        first["id"],
        world["docket"]["id"],
        "2026-09-10T10:00:00Z",
        "2026-09-10T11:00:00Z",
    )
    world["second_appeal"] = second
    return world


def test_a_gap_of_exactly_fifteen_minutes_collides_with_the_booked_hearing(api):
    """PRD §3.9: "It must also keep clear of every other slot already held on that
    docket by **more than** a fifteen-minute buffer on each side: expanding the
    requested interval by fifteen minutes at each end must not touch another slot's
    interval, so a gap of exactly fifteen minutes collides. A geometry failure ...
    is refused with `ERR_HEARING_SLOT_CONFLICT`."

    Design: Difficulty/boundary_precision_check/hearing_buffer_gap_of_exactly_fifteen_minutes_collides_sixteen_clears
    """
    world = _docket_with_one_booked_hearing(api)
    docket_id = world["docket"]["id"]
    second_id = world["second_appeal"]["id"]

    # 11:15Z pulled back by the fifteen-minute buffer touches the 11:00Z end.
    validate_error(
        api.schedule_appeal(
            second_id,
            f.hearing_slot(
                docket_id, "2026-09-10T11:15:00Z", "2026-09-10T12:15:00Z"
            ),
            HEARING_CLERK,
        ),
        ERR_HEARING_SLOT_CONFLICT,
        expected_status=409,
    )

    appeal = validate_success(api.get_appeal(second_id, HEARING_CLERK))
    assert appeal["status"] == "FILED", (
        f"the refused request must leave the appeal undocketed, got {appeal['status']}"
    )
    assert appeal["docket_id"] is None, (
        f"no docket may have been written, got {appeal['docket_id']}"
    )
    assert appeal["hearing_start_utc"] is None, (
        f"no interval may have been reserved, got {appeal['hearing_start_utc']}"
    )

    docket = validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))
    assert docket["scheduled_appeal_count"] == 1, (
        f"only the booked hearing consumes a slot, got {docket['scheduled_appeal_count']}"
    )


def test_a_gap_of_sixteen_minutes_clears_the_buffer_on_the_same_docket(api):
    """PRD §3.9: "On success the appeal's `docket_id`, `hearing_start_utc` and
    `hearing_end_utc` are written, its `status` becomes `SCHEDULED`, and the docket's
    `scheduled_appeal_count` is re-derived one higher with the docket's `version`
    incremented by 1."

    Design: Difficulty/boundary_precision_check/hearing_buffer_gap_of_exactly_fifteen_minutes_collides_sixteen_clears
    """
    world = _docket_with_one_booked_hearing(api)
    docket_id = world["docket"]["id"]
    second_id = world["second_appeal"]["id"]

    validate_error(
        api.schedule_appeal(
            second_id,
            f.hearing_slot(
                docket_id, "2026-09-10T11:15:00Z", "2026-09-10T12:15:00Z"
            ),
            HEARING_CLERK,
        ),
        ERR_HEARING_SLOT_CONFLICT,
        expected_status=409,
    )

    # One minute later the buffered interval no longer touches the booked hour.
    scheduled = validate_success(
        api.schedule_appeal(
            second_id,
            f.hearing_slot(
                docket_id, "2026-09-10T11:16:00Z", "2026-09-10T12:16:00Z"
            ),
            HEARING_CLERK,
        )
    )
    assert scheduled["status"] == "SCHEDULED", (
        f"a sixteen-minute gap must be accepted, got {scheduled['status']}"
    )
    assert scheduled["docket_id"] == docket_id, (
        f"the appeal must name the docket it was scheduled on, got {scheduled['docket_id']}"
    )
    assert_instant(scheduled, "hearing_start_utc", "2026-09-10T11:16:00Z")
    assert_instant(scheduled, "hearing_end_utc", "2026-09-10T12:16:00Z")

    docket = validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))
    assert docket["scheduled_appeal_count"] == 2, (
        f"both hearings now hold slots, got {docket['scheduled_appeal_count']}"
    )
    assert docket["capacity"] == 4, (
        "the capacity of four was never the binding constraint, got "
        f"{docket['capacity']}"
    )

    # The neighbour that forced the buffer is untouched by either attempt.
    first = validate_success(api.get_appeal(world["first_appeal"]["id"], HEARING_CLERK))
    assert first["status"] == "SCHEDULED", (
        f"the booked hearing keeps its slot, got {first['status']}"
    )
    assert_instant(first, "hearing_start_utc", "2026-09-10T10:00:00Z")
    assert_instant(first, "hearing_end_utc", "2026-09-10T11:00:00Z")

    rows, meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, docket_id=docket_id)
    )
    assert meta["total_count"] == 2, (
        f"the docket carries exactly two appeals, got {meta['total_count']}"
    )
    assert ids_of(rows) == [world["first_appeal"]["id"], second_id], (
        f"unexpected docket roster: {ids_of(rows)}"
    )


def test_a_full_docket_refuses_an_afternoon_slot_that_touches_no_hearing(api):
    """PRD §3.9: "Finally, the docket's `scheduled_appeal_count` must still be below
    its `capacity`, or the request is refused with `ERR_DOCKET_CAPACITY_REACHED`."
    PRD §2.10 orders the geometry check at 18 and the capacity check at 27, and "the
    **first** failure decides the response".

    Design: Difficulty/resource_temporal_overlap/docket_aggregate_capacity_blocks_a_slot_no_other_hearing_touches
    """
    world = _docket_with_one_booked_hearing(api, capacity=1)
    docket_id = world["docket"]["id"]
    second_id = world["second_appeal"]["id"]

    # Three clear hours after the only booked hearing: nothing but the count blocks.
    response = api.schedule_appeal(
        second_id,
        f.hearing_slot(docket_id, "2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z"),
        HEARING_CLERK,
    )
    validate_error(response, ERR_DOCKET_CAPACITY_REACHED, expected_status=409)
    assert ERR_HEARING_SLOT_CONFLICT not in response.text, (
        "the interval geometry is sound, so no conflict may be reported: "
        f"{response.text}"
    )

    appeal = validate_success(api.get_appeal(second_id, HEARING_CLERK))
    assert appeal["status"] == "FILED", (
        f"the refused request leaves the appeal undocketed, got {appeal['status']}"
    )
    assert appeal["docket_id"] is None, (
        f"no docket may have been written, got {appeal['docket_id']}"
    )

    docket = validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))
    assert docket["capacity"] == 1, f"capacity of one, got {docket['capacity']}"
    assert docket["scheduled_appeal_count"] == 1, (
        f"the single slot is still consumed, got {docket['scheduled_appeal_count']}"
    )


def test_a_continuance_releases_the_slot_so_the_identical_request_succeeds(api):
    """PRD §3.9: "A **continuance** postpones rather than decides:
    `continuance_count` increments by 1, the appeal's `docket_id`,
    `hearing_start_utc` and `hearing_end_utc` are all reset to null, its `status`
    becomes `CONTINUED`, and the released slot re-derives the former docket's
    `scheduled_appeal_count` one lower, freeing the buffer window for another
    appeal."

    Design: Difficulty/resource_temporal_overlap/docket_aggregate_capacity_blocks_a_slot_no_other_hearing_touches
    """
    world = _docket_with_one_booked_hearing(api, capacity=1)
    docket_id = world["docket"]["id"]
    second_id = world["second_appeal"]["id"]

    validate_error(
        api.schedule_appeal(
            second_id,
            f.hearing_slot(docket_id, "2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z"),
            HEARING_CLERK,
        ),
        ERR_DOCKET_CAPACITY_REACHED,
        expected_status=409,
    )

    continued = validate_success(
        api.decide_appeal(
            world["first_appeal"]["id"],
            f.appeal_decision(
                "CONTINUE",
                "Appellant requested more time to gather utility records.",
            ),
            HEARING_OFFICER,
        )
    )
    assert continued["status"] == "CONTINUED", (
        f"the postponed appeal leaves the docket, got {continued['status']}"
    )
    assert continued["continuance_count"] == 1, (
        f"the first postponement counts once, got {continued['continuance_count']}"
    )
    assert continued["docket_id"] is None, (
        f"the released appeal names no docket, got {continued['docket_id']}"
    )
    assert continued["hearing_start_utc"] is None, (
        f"the reserved interval is given back, got {continued['hearing_start_utc']}"
    )

    released = validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))
    assert released["scheduled_appeal_count"] == 0, (
        f"the released slot is re-derived away, got {released['scheduled_appeal_count']}"
    )

    # Byte-identical to the request that was refused a moment ago.
    scheduled = validate_success(
        api.schedule_appeal(
            second_id,
            f.hearing_slot(docket_id, "2026-09-10T14:00:00Z", "2026-09-10T15:00:00Z"),
            HEARING_CLERK,
        )
    )
    assert scheduled["status"] == "SCHEDULED", (
        "the same request succeeds once the count falls, proving the count and not "
        f"the clock was the blocker, got {scheduled['status']}"
    )
    assert_instant(scheduled, "hearing_start_utc", "2026-09-10T14:00:00Z")

    docket = validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))
    assert docket["scheduled_appeal_count"] == 1, (
        f"the freed slot is consumed again, got {docket['scheduled_appeal_count']}"
    )
    assert docket["capacity"] == 1, f"capacity is unchanged, got {docket['capacity']}"

    rows, meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, docket_id=docket_id)
    )
    assert meta["total_count"] == 1, (
        f"only the newly scheduled appeal is on the docket, got {meta['total_count']}"
    )
    assert ids_of(rows) == [second_id], f"unexpected docket roster: {ids_of(rows)}"


def test_a_denial_mails_a_notice_whose_deadline_sits_thirty_days_out(api):
    """PRD §3.4: "a notice is created with `notice_type` `DENIAL`, `subject_type`
    `EXEMPTION_APPLICATION`, `subject_id` equal to the application's own
    identifier, `taxpayer_id` copied from the application, `mailed_at` stamped from
    the logical clock and `appealable` true; and that notice's `appeal_deadline` is
    computed as its `mailed_at` instant plus a thirty-day appeal window". PRD §3.4
    adds: "As with a request for information, a denial does not increment the
    parcel's `version`."

    Design: Corner/entities/denial_notice_appeal_deadline_is_thirty_days_after_mailing
    """
    world = fx.denial_notice_world(api, claimants=1)
    application = world["applications"][0]
    taxpayer = world["taxpayers"][0]

    assert application["status"] == "DENIED", (
        f"the determination refused the claim, got {application['status']}"
    )
    assert application["denial_reason"], (
        f"a denial records its ground, got {application['denial_reason']!r}"
    )

    rows, meta = validate_paginated(
        api.list_notices(taxpayer["id"], CLERK, notice_type="DENIAL")
    )
    assert meta["total_count"] == 1, (
        f"one denial mails exactly one notice, got {meta['total_count']}"
    )
    notice = rows[0]

    # The clock stood at 2026-08-01T00:00:00Z, so the window closes on 08-31.
    assert_instant(notice, "mailed_at", "2026-08-01T00:00:00.000Z")
    assert_instant(notice, "appeal_deadline", "2026-08-31T00:00:00.000Z")
    assert notice["appealable"] is True, (
        f"a denial is an adverse action and is appealable, got {notice['appealable']!r}"
    )
    assert notice["subject_type"] == "EXEMPTION_APPLICATION", (
        f"the notice is mailed against the application, got {notice['subject_type']}"
    )
    assert notice["subject_id"] == application["id"], (
        f"the notice names the denied application, got {notice['subject_id']}"
    )
    assert notice["taxpayer_id"] == taxpayer["id"], (
        f"the notice is addressed to the claimant, got {notice['taxpayer_id']}"
    )
    assert notice["notice_type"] == "DENIAL", (
        f"the notice type is the denial, got {notice['notice_type']}"
    )

    parcel = validate_success(api.get_parcel(world["parcel"]["id"], ANALYST))
    assert parcel["version"] == world["parcel"]["version"], (
        "a denial mints no grant and so must not touch the parcel, got version "
        f"{parcel['version']} against {world['parcel']['version']}"
    )


def test_an_undocketed_appeal_cannot_be_decided_from_the_file(api):
    """PRD §3.9: "A `HearingOfficer` decides a `SCHEDULED` appeal — any other status
    is refused with `ERR_APPEAL_NOT_SCHEDULED` — by supplying an `action` of `GRANT`,
    `DENY`, `DISMISS` or `CONTINUE`, optionally with `findings`. Every decision
    records the acting `X-User-ID` in `decided_by_user_id`".

    Design: Corner/state_machines/appeal_decision_requires_the_appeal_to_be_scheduled_first
    """
    world = fx.denial_notice_world(api, claimants=1)
    application = world["applications"][0]
    appeal = fx.file_appeal(
        api,
        world["notices"][0]["id"],
        world["taxpayers"][0]["id"],
        grounds=(
            "Occupancy has been continuous since 2019 and the registry record is "
            "stale."
        ),
    )
    assert appeal["status"] == "FILED", (
        f"a freshly filed appeal waits for a docket, got {appeal['status']}"
    )

    validate_error(
        api.decide_appeal(
            appeal["id"],
            f.appeal_decision("DENY", "Decided from the file without a hearing."),
            HEARING_OFFICER,
        ),
        ERR_APPEAL_NOT_SCHEDULED,
        expected_status=409,
    )

    refused = validate_success(api.get_appeal(appeal["id"], HEARING_CLERK))
    assert refused["status"] == "FILED", (
        f"the refused decision leaves the appeal filed, got {refused['status']}"
    )
    assert refused["docket_id"] is None, (
        f"the appeal was never docketed, got {refused['docket_id']}"
    )
    assert refused["decided_by_user_id"] is None, (
        f"no officer may be recorded as having decided it, got {refused['decided_by_user_id']!r}"
    )
    assert refused["continuance_count"] == 0, (
        f"nothing was postponed either, got {refused['continuance_count']}"
    )

    # The adverse decision under appeal is untouched by the refused request.
    denied = validate_success(api.get_application(application["id"], REVIEWER))
    assert denied["status"] == "DENIED", (
        f"the denial still stands, got {denied['status']}"
    )


def test_an_appeal_filed_at_the_deadline_instant_is_timely_and_a_day_later_is_not(api):
    """PRD §3.9: "Where a notice is appealable, its `appeal_deadline` is its
    `mailed_at` instant plus a thirty-day appeal window, and the boundary is
    inclusive — an appeal filed at exactly the deadline instant is still timely, while
    one filed strictly after it is refused with `ERR_APPEAL_DEADLINE_PASSED`."

    Design: Corner/validations/appeal_at_exactly_the_deadline_instant_is_timely_one_day_later_is_not
    """
    world = fx.denial_notice_world(api, claimants=2)
    first_notice, second_notice = world["notices"]
    first_taxpayer, second_taxpayer = world["taxpayers"]
    assert_instant(first_notice, "mailed_at", "2026-08-01T00:00:00.000Z")
    assert_instant(first_notice, "appeal_deadline", "2026-08-31T00:00:00.000Z")
    assert_instant(second_notice, "appeal_deadline", "2026-08-31T00:00:00.000Z")

    # Exactly the deadline instant: the window is closed at its upper end.
    fx.set_clock(api, "2026-08-31T00:00:00Z")
    filed = validate_success(
        api.create_appeal(
            f.appeal(first_notice["id"]),
            fx.make_taxpayer_headers(first_taxpayer["id"]),
        ),
        expected_status=201,
    )
    assert filed["status"] == "FILED", (
        f"an appeal lodged on the deadline is timely, got {filed['status']}"
    )
    assert_instant(filed, "filed_at", "2026-08-31T00:00:00.000Z")

    # One day past the deadline, on the sibling notice mailed at the same instant.
    fx.set_clock(api, "2026-09-01T00:00:00Z")
    validate_error(
        api.create_appeal(
            f.appeal(second_notice["id"]),
            fx.make_taxpayer_headers(second_taxpayer["id"]),
        ),
        ERR_APPEAL_DEADLINE_PASSED,
        expected_status=422,
    )

    late_rows, late_meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, notice_id=second_notice["id"])
    )
    assert late_meta["total_count"] == 0, (
        f"the late filing must persist nothing, got {late_meta['total_count']}"
    )
    assert late_rows == [], f"unexpected appeals on the second notice: {late_rows}"

    timely_rows, timely_meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, notice_id=first_notice["id"])
    )
    assert timely_meta["total_count"] == 1, (
        f"the timely appeal survives the later refusal, got {timely_meta['total_count']}"
    )
    assert ids_of(timely_rows) == [filed["id"]], (
        f"unexpected appeals on the first notice: {ids_of(timely_rows)}"
    )


def test_one_notice_admits_one_appeal_a_closed_docket_admits_none_and_a_decision_ends_it(api):
    """PRD §3.9: "Only one appeal may exist per notice; a second attempt is refused
    with `ERR_APPEAL_ALREADY_EXISTS`." PRD §3.9 on closure: "the docket's `status`
    becomes `CLOSED` and its `version` increments by 1, appeals already holding slots
    keep them and remain `SCHEDULED` with the count unchanged, and every later attempt
    to schedule onto that docket is refused with `ERR_DOCKET_CLOSED`." And on
    schedulability: "The appeal must be `FILED` or `CONTINUED`; any other status is
    refused with `ERR_APPEAL_NOT_SCHEDULABLE`."

    Design: Corner/errors/appeal_filing_and_scheduling_lifecycle_guards_return_4xx
    """
    world = fx.denial_notice_world(api, claimants=1)
    notice = world["notices"][0]
    taxpayer_headers = fx.make_taxpayer_headers(world["taxpayers"][0]["id"])

    appeal = validate_success(
        api.create_appeal(
            f.appeal(notice["id"], grounds="Occupancy was continuous since 2019."),
            taxpayer_headers,
        ),
        expected_status=201,
    )
    assert appeal["status"] == "FILED", (
        f"a filed appeal waits for a docket, got {appeal['status']}"
    )
    assert appeal["docket_id"] is None, (
        f"and names no docket yet, got {appeal['docket_id']}"
    )

    validate_error(
        api.create_appeal(
            f.appeal(notice["id"], grounds="Second filing on the same notice."),
            taxpayer_headers,
        ),
        ERR_APPEAL_ALREADY_EXISTS,
        expected_status=409,
    )
    rows, meta = validate_paginated(
        api.list_appeals(HEARING_CLERK, notice_id=notice["id"])
    )
    assert meta["total_count"] == 1, (
        f"the notice still carries exactly one appeal, got {meta['total_count']}"
    )
    assert ids_of(rows) == [appeal["id"]], f"unexpected appeals: {ids_of(rows)}"

    cancelled = fx.open_docket(
        api,
        docket_date="2026-09-08",
        session_start_utc="2026-09-08T09:00:00Z",
        session_end_utc="2026-09-08T17:00:00Z",
        capacity=5,
    )
    shut = validate_success(
        api.close_hearing_docket(
            cancelled["id"], HEARING_CLERK, {"reason": "Session cancelled."}
        )
    )
    assert shut["status"] == "CLOSED", (
        f"the cancelled session is closed, got {shut['status']}"
    )
    live = fx.open_docket(api, capacity=5)

    validate_error(
        api.schedule_appeal(
            appeal["id"],
            f.hearing_slot(
                cancelled["id"], "2026-09-08T09:00:00Z", "2026-09-08T10:00:00Z"
            ),
            HEARING_CLERK,
        ),
        ERR_DOCKET_CLOSED,
        expected_status=409,
    )
    assert (
        validate_success(api.get_hearing_docket(cancelled["id"], HEARING_CLERK))[
            "scheduled_appeal_count"
        ]
        == 0
    ), "a closed docket may not gain a slot"

    scheduled = fx.schedule(
        api,
        appeal["id"],
        live["id"],
        "2026-09-10T09:00:00Z",
        "2026-09-10T10:00:00Z",
    )
    assert scheduled["status"] == "SCHEDULED", (
        f"the open docket accepts the hearing, got {scheduled['status']}"
    )
    assert scheduled["docket_id"] == live["id"], (
        f"the appeal names the open docket, got {scheduled['docket_id']}"
    )

    decided = validate_success(
        api.decide_appeal(
            appeal["id"],
            f.appeal_decision("DENY", "The denial stands."),
            HEARING_OFFICER,
        )
    )
    assert decided["status"] == "DENIED", (
        f"the hearing was held and the appeal refused, got {decided['status']}"
    )
    assert decided["decided_by_user_id"] == HEARING_OFFICER_USER_ID, (
        f"the deciding officer is stamped, got {decided['decided_by_user_id']!r}"
    )
    held = validate_success(api.get_hearing_docket(live["id"], HEARING_CLERK))
    assert held["scheduled_appeal_count"] == 1, (
        f"a decided appeal keeps consuming its slot, got {held['scheduled_appeal_count']}"
    )

    # A decided appeal is neither FILED nor CONTINUED, so it cannot be re-listed.
    validate_error(
        api.schedule_appeal(
            appeal["id"],
            f.hearing_slot(live["id"], "2026-09-10T11:00:00Z", "2026-09-10T12:00:00Z"),
            HEARING_CLERK,
        ),
        ERR_APPEAL_NOT_SCHEDULABLE,
        expected_status=409,
    )
    final = validate_success(api.get_appeal(appeal["id"], HEARING_CLERK))
    assert final["status"] == "DENIED", (
        f"the refused re-listing leaves the decision standing, got {final['status']}"
    )


def test_the_third_continuance_is_refused_with_the_counter_frozen_at_two(api):
    """PRD §3.9: "An appeal may be continued at most twice: the counter must be below
    2 when the continuance is issued, and a third attempt is refused with
    `ERR_CONTINUANCE_LIMIT_REACHED`." PRD §3.9 adds: "Re-docketing an appeal that had
    been continued works identically and against the same interval, buffer, capacity
    and session-window conditions, moving it from `CONTINUED` back to `SCHEDULED` and
    re-deriving the new docket's count."

    Design: Corner/errors/third_continuance_on_one_appeal_returns_4xx
    """
    world = fx.appeal_world(api, claimants=1, capacity=5)
    appeal_id = world["appeals"][0]["id"]
    docket_id = world["docket"]["id"]
    fx.schedule(
        api, appeal_id, docket_id, "2026-09-10T09:00:00Z", "2026-09-10T10:00:00Z"
    )

    postponement = f.appeal_decision("CONTINUE", "Claimant requested more time.")
    first = validate_success(api.decide_appeal(appeal_id, postponement, HEARING_OFFICER))
    assert first["continuance_count"] == 1, (
        f"the first postponement counts once, got {first['continuance_count']}"
    )
    assert first["status"] == "CONTINUED", (
        f"the appeal leaves the docket, got {first['status']}"
    )
    assert first["docket_id"] is None, (
        f"and releases its slot, got {first['docket_id']}"
    )
    assert first["hearing_start_utc"] is None, (
        f"with the interval given back, got {first['hearing_start_utc']}"
    )
    assert (
        validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))[
            "scheduled_appeal_count"
        ]
        == 0
    ), "the released slot must be re-derived away"

    relisted = fx.schedule(
        api, appeal_id, docket_id, "2026-09-10T11:00:00Z", "2026-09-10T12:00:00Z"
    )
    assert relisted["status"] == "SCHEDULED", (
        f"a continued appeal is re-docketable, got {relisted['status']}"
    )

    second = validate_success(
        api.decide_appeal(
            appeal_id,
            f.appeal_decision("CONTINUE", "Second continuance granted."),
            HEARING_OFFICER,
        )
    )
    assert second["continuance_count"] == 2, (
        f"the counter reaches the ceiling, got {second['continuance_count']}"
    )
    assert second["status"] == "CONTINUED", (
        f"and the slot is released again, got {second['status']}"
    )

    third_listing = fx.schedule(
        api, appeal_id, docket_id, "2026-09-10T13:00:00Z", "2026-09-10T14:00:00Z"
    )
    assert_instant(third_listing, "hearing_start_utc", "2026-09-10T13:00:00Z")

    # The counter is no longer below two, so no third postponement is admissible.
    validate_error(
        api.decide_appeal(
            appeal_id,
            f.appeal_decision("CONTINUE", "Third continuance requested."),
            HEARING_OFFICER,
        ),
        ERR_CONTINUANCE_LIMIT_REACHED,
        expected_status=409,
    )

    frozen = validate_success(api.get_appeal(appeal_id, HEARING_CLERK))
    assert frozen["continuance_count"] == 2, (
        f"the refused request must not advance the counter, got {frozen['continuance_count']}"
    )
    assert frozen["status"] == "SCHEDULED", (
        f"the appeal keeps the slot it holds, got {frozen['status']}"
    )
    assert frozen["docket_id"] == docket_id, (
        f"on the docket it was listed on, got {frozen['docket_id']}"
    )
    assert (
        validate_success(api.get_hearing_docket(docket_id, HEARING_CLERK))[
            "scheduled_appeal_count"
        ]
        == 1
    ), "and the docket still counts that held slot"


def _denied_claim_whose_slot_was_taken(api):
    """A denied claim, a second claim approved on the same triple, and a live appeal.

    The first application was denied before any ownership record existed. The
    evidence was then put in order and a second application on the identical
    parcel, programme and tax year was approved, so the exclusivity slot for that
    triple is occupied by a live grant before the first denial is ever revisited.
    """
    world = fx.denial_notice_world(api, claimants=1)
    parcel = world["parcel"]
    taxpayer_id = world["taxpayers"][0]["id"]
    fx.add_ownership(api, parcel["id"], taxpayer_id)
    fx.inject_matching_residency(api, taxpayer_id)
    # PRD §3.3: "A `MISMATCH` that was subsequently corrected by a fresh check
    # therefore does not block approval." The denied application's only voter row
    # read `NO_RECORD`, so fresh matching rows are recorded against it too; the
    # reopened claim is then held up by nothing but the exclusivity slot.
    fx.run_checks(
        api, world["applications"][0]["id"], ["VOTER_REGISTRY", "DEED_REGISTRY"]
    )

    second = fx.application_ready_for_approval(
        api, parcel["id"], taxpayer_id, world["program"]["id"]
    )
    approved = validate_success(
        api.determine_application(
            second["id"], f.approve_determination(parcel["version"]), REVIEWER
        )
    )
    world["second_application"] = approved
    world["second_grant_id"] = approved["resulting_grant_id"]

    docket = fx.open_docket(
        api,
        docket_date="2026-08-20",
        session_start_utc="2026-08-20T09:00:00Z",
        session_end_utc="2026-08-20T17:00:00Z",
        capacity=5,
    )
    appeal = fx.file_appeal(
        api,
        world["notices"][0]["id"],
        taxpayer_id,
        grounds="The occupancy evidence was complete.",
    )
    world["docket"] = docket
    world["appeal"] = fx.schedule(
        api,
        appeal["id"],
        docket["id"],
        "2026-08-20T09:00:00Z",
        "2026-08-20T10:00:00Z",
    )
    return world


def test_a_granted_appeal_revives_a_claim_whose_exclusivity_slot_is_already_taken(api):
    """PRD §3.9: "On a `DENIAL` notice, the `DENIED` application returns to
    `UNDER_REVIEW` and its `determined_by_user_id` is cleared to null, putting the
    claim back in front of a different reviewer." PRD §3.2 adds that the reopening
    also clears the ground: "should a hearing officer later grant an appeal against
    that denial notice, the application returns from `DENIED` to `UNDER_REVIEW`, its
    `denial_reason` is cleared back to null and its `determined_by_user_id` is cleared
    back to null as well". PRD §3.4 then closes the door: "Grant exclusivity forbids
    approval when a grant already exists for the same `parcel_id`, `program_id` and
    `effective_tax_year` whose `benefit_status` is `ACTIVE` or `SUSPENDED` — a
    suspended grant still occupies the slot — and the collision is reported as
    `ERR_DUPLICATE_GRANT`."

    Design: Corner/errors/granted_appeal_reopens_a_denied_application_into_a_duplicate_grant_conflict
    """
    world = _denied_claim_whose_slot_was_taken(api)
    denied_id = world["applications"][0]["id"]
    parcel_id = world["parcel"]["id"]

    granted = validate_success(
        api.decide_appeal(
            world["appeal"]["id"],
            f.appeal_decision(
                "GRANT",
                "The denial is reversed and the application returns to review.",
            ),
            HEARING_OFFICER,
        )
    )
    assert granted["status"] == "GRANTED", (
        f"the hearing officer reversed the denial, got {granted['status']}"
    )
    assert granted["decided_by_user_id"] == HEARING_OFFICER_USER_ID, (
        f"the deciding officer is stamped, got {granted['decided_by_user_id']!r}"
    )

    revived = validate_success(api.get_application(denied_id, REVIEWER))
    assert revived["status"] == "UNDER_REVIEW", (
        f"the reversed denial puts the claim back in review, got {revived['status']}"
    )
    assert revived["denial_reason"] is None, (
        f"the recorded ground is cleared, got {revived['denial_reason']!r}"
    )
    assert revived["determined_by_user_id"] is None, (
        "the reviewer whose denial was reversed is no longer the decider, got "
        f"{revived['determined_by_user_id']!r}"
    )

    reopened_parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert reopened_parcel["version"] == 2, (
        "creation and the second application's approval are the only two parcel "
        f"mutations, got version {reopened_parcel['version']}"
    )

    # The revived claim is honestly in review and quotes the parcel version it
    # just read, so nothing but the occupied exclusivity slot can refuse it.
    response = api.determine_application(
        denied_id,
        f.approve_determination(reopened_parcel["version"]),
        REVIEWER_2,
    )
    validate_error(response, ERR_DUPLICATE_GRANT, expected_status=409)
    assert ERR_STALE_PARCEL_VERSION not in response.text, (
        "the determination carried the current parcel version, so the refusal must "
        f"be the exclusivity collision and not a stale-version proof: {response.text}"
    )

    still_open = validate_success(api.get_application(denied_id, REVIEWER))
    assert still_open["status"] == "UNDER_REVIEW", (
        f"the refused approval leaves the claim in review, got {still_open['status']}"
    )
    assert still_open["resulting_grant_id"] is None, (
        f"no second grant was minted for it, got {still_open['resulting_grant_id']!r}"
    )

    assert_grant(
        validate_success(api.get_grant(world["second_grant_id"], REVIEWER)),
        benefit_status="ACTIVE",
        benefit_amount_cents=8400000,
        applied_exempt_value_cents=8400000,
    )
    rows, meta = validate_paginated(api.list_grants(REVIEWER, parcel_id=parcel_id))
    assert meta["total_count"] == 1, (
        f"the parcel still carries exactly one grant, got {meta['total_count']}"
    )
    assert ids_of(rows) == [world["second_grant_id"]], (
        f"unexpected grants on the parcel: {ids_of(rows)}"
    )

    parcel = validate_success(api.get_parcel(parcel_id, ANALYST))
    assert_parcel_decomposition(
        parcel,
        assessed_value_cents=33600000,
        exempt_value_cents=8400000,
        taxable_value_cents=25200000,
        exemption_status="PARTIALLY_EXEMPT",
    )
    assert parcel["version"] == 2, (
        f"the refused approval is not a parcel mutation, got version {parcel['version']}"
    )
