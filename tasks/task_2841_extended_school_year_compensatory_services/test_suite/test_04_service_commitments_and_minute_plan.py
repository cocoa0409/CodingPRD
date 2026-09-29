"""Service commitments: the creation gates, the pinned minute plan, activation."""

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_case_manager_headers,
    make_program_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
PC = make_program_coordinator_headers()

CLOCK = "2027-06-01T00:00:00Z"


class TestPinnedMinutePlan:
    """Rounding happens per ISO week, before the weeks are summed."""

    def test_the_canonical_calendar_pins_1376_not_the_sum_then_round_answer(self, api):
        """Per-week day counts 4,4,3,3,4,4 at 250 weekly minutes give 1376, never 1375.

        The order of operations is normative: "The second step prorates the weekly IEP
        minutes onto each calendar week, and rounds **per week, before summing**. Let
        the nominal weekday count be the number of entries in the program's
        `instructional_weekdays` — the length of a full summer week. For each ISO week
        in ascending order, that week's minute figure is the request's
        `iep_weekly_minutes` multiplied by the count of instructional dates actually
        falling in that week, divided by the nominal weekday count, rounded half up to
        a whole minute. `planned_total_minutes` is the sum of those per-week figures
        taken in week order. Rounding each week first and then adding is normative and
        is not the same answer as adding the exact per-week quotients and rounding once
        at the end; a four-weekday program running Monday through Thursday over a
        session whose last week holds only two instructional dates will show it." The
        two derived averages follow: "The third step averages the pinned total back
        down. `weekly_minutes_committed` is `planned_total_minutes` divided by the
        number of ISO weeks, rounded half up to a whole minute. `daily_minutes` is
        `weekly_minutes_committed` divided by the nominal weekday count, again rounded
        half up to a whole minute; this daily figure is what a system-generated
        day-cancellation log will later claim as scheduled minutes." The figures are
        frozen there: "Creation runs the prorated minute plan against the program
        calendar **as it reads at that instant**, and the resulting three figures are
        pinned there permanently."

        Design: Difficulty/combinatorial_formula/minute_plan_round_per_week_then_sum_beats_sum_then_round
        """
        fixtures.set_clock(api, CLOCK)
        eligible = fixtures.make_eligible_student(api)
        program = fixtures.create_program(api)

        assert program["instructional_days_count"] == 22
        assert program["instructional_week_count"] == 6

        commitment = fixtures.create_commitment(
            api, program["id"], eligible["student"]["id"], iep_weekly_minutes=250
        )

        # 250, 250, 188, 188, 250, 250 summed in week order.
        assert commitment["planned_total_minutes"] == 1376
        # The forbidden order, 250 * 22 / 4 rounded once, would answer 1375.
        assert commitment["planned_total_minutes"] != 1375
        assert commitment["weekly_minutes_committed"] == 229
        assert commitment["daily_minutes"] == 57
        assert commitment["status"] == "PLANNED"

    def test_a_second_weekly_figure_reproduces_the_one_minute_rounding_signature(
        self, api
    ):
        """At 150 weekly minutes the same calendar pins 826, not the 825 of the wrong order.

        The same normative order applies to every commitment: "For each ISO week in
        ascending order, that week's minute figure is the request's
        `iep_weekly_minutes` multiplied by the count of instructional dates actually
        falling in that week, divided by the nominal weekday count, rounded half up to
        a whole minute. `planned_total_minutes` is the sum of those per-week figures
        taken in week order." and the averages are rounded half up again: "The third
        step averages the pinned total back down. `weekly_minutes_committed` is
        `planned_total_minutes` divided by the number of ISO weeks, rounded half up to
        a whole minute. `daily_minutes` is `weekly_minutes_committed` divided by the
        nominal weekday count, again rounded half up to a whole minute; this daily
        figure is what a system-generated day-cancellation log will later claim as
        scheduled minutes."

        Design: Difficulty/combinatorial_formula/minute_plan_round_per_week_then_sum_beats_sum_then_round
        """
        fixtures.set_clock(api, CLOCK)
        eligible = fixtures.make_eligible_student(api)
        program = fixtures.create_program(api)

        commitment = fixtures.create_commitment(
            api, program["id"], eligible["student"]["id"], iep_weekly_minutes=150
        )

        # 150, 150, 113, 113, 150, 150 summed in week order.
        assert commitment["planned_total_minutes"] == 826
        # 150 * 22 / 4 rounded once would answer 825.
        assert commitment["planned_total_minutes"] != 825
        # 826 / 6 = 137.67 -> 138, then 138 / 4 = 34.5 -> 35 half up.
        assert commitment["weekly_minutes_committed"] == 138
        assert commitment["daily_minutes"] == 35

    def test_the_heaviest_week_daily_load_may_equal_the_cap_but_not_exceed_it(self, api):
        """361 weekly minutes overloads the three-day weeks; 360 lands exactly on 90.

        The ceiling test uses the worst week, not the average: "The fourth step
        enforces the program's daily load ceiling, and it deliberately uses the
        **heaviest single week rather than the average**. For each ISO week, divide
        that week's rounded minute figure by the count of instructional dates in that
        week; take the largest such quotient across all weeks. If that maximum daily
        load is greater than the program's `daily_minutes_cap`, the create fails with
        `ERR_DAILY_MINUTES_CAP_EXCEEDED`. A short final week concentrating a full
        week's minutes into two days is exactly the case this catches." The cap itself
        is a program input: "`daily_minutes_cap` fixes, between 1 and 480, the most
        service minutes any single student may be scheduled to receive on one
        instructional day."

        Design: Corner/validations/commitment_daily_minutes_cap_passes_exactly_at_the_cap
        """
        fixtures.set_clock(api, CLOCK)
        eligible = fixtures.make_eligible_student(
            api, student_overrides={"iep_weekly_minutes_total": 1500}
        )
        program = fixtures.create_program(api)
        fixtures.authorize_allocation(api, program["id"])

        # Weeks 361,361,271,271,361,361: the three-day weeks carry 271/3 = 90.33.
        over_cap = api.create_commitment(
            factories.commitment_payload(
                program["id"], eligible["student"]["id"], iep_weekly_minutes=361
            ),
            CM,
        )
        validate_error(over_cap, ApiErrorId.DAILY_MINUTES_CAP_EXCEEDED.value, 422)

        # Weeks 360,360,270,270,360,360: every week lands on exactly 90.00.
        at_cap = validate_success(
            api.create_commitment(
                factories.commitment_payload(
                    program["id"], eligible["student"]["id"], iep_weekly_minutes=360
                ),
                CM,
            ),
            201,
        )

        assert at_cap["planned_total_minutes"] == 1980
        assert at_cap["weekly_minutes_committed"] == 330
        assert at_cap["daily_minutes"] == 83
        assert at_cap["status"] == "PLANNED"

    def test_a_calendar_with_no_instructional_day_cannot_carry_a_commitment(self, api):
        """A weekend-only window with MON as the only instructional weekday yields nothing.

        The first step of the plan guards against the empty calendar: "The first step
        builds the program's instructional-day calendar exactly as §3.3 describes and
        groups the surviving dates into ascending ISO weeks. If the calendar yields no
        instructional day at all, the create fails with `ERR_NO_INSTRUCTIONAL_DAYS`."
        Membership is the §3.3 derivation: "Walk the inclusive range of dates from
        `session_start_date` through `session_end_date`; keep a date when its weekday
        name appears in `instructional_weekdays`, when it does not appear in
        `blackout_dates`, and when it does not appear in `cancelled_dates`."

        Design: Corner/errors/commitment_on_a_program_whose_calendar_has_no_instructional_days_rejected
        """
        fixtures.set_clock(api, CLOCK)
        eligible = fixtures.make_eligible_student(api)
        student = eligible["student"]
        program = fixtures.create_program(
            api,
            name="Weekend Only ESY",
            session_start_date="2027-06-19",
            session_end_date="2027-06-20",
            instructional_weekdays=["MON"],
            blackout_dates=factories.OMIT,
        )

        rejected = api.create_commitment(
            factories.commitment_payload(program["id"], student["id"]), CM
        )

        validate_error(rejected, ApiErrorId.NO_INSTRUCTIONAL_DAYS.value, 422)
        assert (
            fixtures.refresh_student(api, student["id"])["esy_eligibility_status"]
            == "ELIGIBLE"
        )
        _, meta = validate_paginated(
            api.list_commitments(CM, {"program_id": program["id"]})
        )
        assert meta["total_count"] == 0


class TestCommitmentCreationGates:
    """The eligibility gate reads another entity's derived state."""

    def test_only_an_eligible_student_may_be_committed(self, api):
        """The identical payload fails for a `NOT_DETERMINED` student and passes for an eligible one.

        Both gates are declared together: "Two hard gates guard creation: the named
        program must be in `PLANNING`, and the named student's `esy_eligibility_status`
        must read `ELIGIBLE`. A student whose eligibility reads `NOT_DETERMINED`,
        `INELIGIBLE` or `PENDING_DATA` cannot be committed, and the attempt is refused
        with `ERR_STUDENT_NOT_ESY_ELIGIBLE`." The field the gate reads has exactly one
        writer: "At registration `esy_eligibility_status` reads `NOT_DETERMINED` — the
        other possible values being `ELIGIBLE`, `INELIGIBLE` and `PENDING_DATA` — and it
        is written by exactly one event in the whole system: the finalization of an
        eligibility determination."

        Design: Corner/validations/commitment_creation_for_a_not_determined_student_rejected
        """
        fixtures.set_clock(api, CLOCK)
        eligible = fixtures.make_eligible_student(
            api, student_overrides={"student_number": "S-2841-001"}
        )
        never_assessed = fixtures.register_student(
            api,
            student_number="S-2841-002",
            first_name="Ben",
            last_name="Okafor",
            primary_disability="SPECIFIC_LEARNING_DISABILITY",
            transportation_required=factories.OMIT,
        )
        program = fixtures.create_program(api)
        fixtures.authorize_allocation(api, program["id"])

        refused = api.create_commitment(
            factories.commitment_payload(program["id"], never_assessed["id"]), CM
        )
        validate_error(refused, ApiErrorId.STUDENT_NOT_ESY_ELIGIBLE.value, 422)
        assert (
            fixtures.refresh_student(api, never_assessed["id"])[
                "esy_eligibility_status"
            ]
            == "NOT_DETERMINED"
        )

        accepted = validate_success(
            api.create_commitment(
                factories.commitment_payload(
                    program["id"], eligible["student"]["id"]
                ),
                CM,
            ),
            201,
        )

        assert accepted["status"] == "PLANNED"
        assert accepted["planned_total_minutes"] == 1376
        assert accepted["weekly_minutes_committed"] == 229
        assert accepted["daily_minutes"] == 57
        assert (
            fixtures.refresh_student(api, eligible["student"]["id"])[
                "esy_eligibility_status"
            ]
            == "ELIGIBLE"
        )


class TestActivationReadsTheProgramState:
    """`ASSIGNED → ACTIVE` is gated on the parent program, not on the commitment."""

    def test_a_staffing_locked_program_blocks_activation_and_opening_unblocks_it(
        self, api
    ):
        """Identical request body, two outcomes, decided entirely by the program's status.

        Activation names its cross-entity precondition: "Activation (`ASSIGNED →
        ACTIVE`) requires the commitment to be in `ASSIGNED` and additionally requires
        its program's `status` to read `OPEN`; a commitment cannot go live before its
        session does, and the mismatch returns `ERR_INVALID_STATE`." The same guard is
        listed among check 9's cross-entity folds: "The cross-entity guards folded into
        this check are: a commitment may only be activated while its program is `OPEN`;
        a makeup session may only be booked against an award whose negotiation dimension
        reads `AGREED` and whose delivery dimension is not `LAPSED`; and an allocation
        may only be closed while its encumbered balance is zero." Activation is not a
        fiscal event: "The release moves it `ACTIVE → RELEASED` and reverses its
        footprint exactly: `total_charge_cents` is subtracted from the
        `encumbered_amount_cents` of the allocation identified by `charged_fund_source`
        and `charged_budget_code`, so `available_cents` returns to its pre-assignment
        value; `covered_weekly_minutes` is subtracted from the provider's
        `assigned_weekly_minutes`; and if the release leaves no `ACTIVE` assignment on a
        commitment whose `status` reads `ASSIGNED`, the commitment reverts to `PLANNED`."

        Design: Difficulty/cross_entity_state_dependency/commitment_activation_requires_open_program
        """
        baseline = fixtures.setup_baseline(
            api,
            clock=CLOCK,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        program, commitment = baseline["program"], baseline["commitment"]
        validate_success(api.set_program_status(program["id"], "STAFFING_LOCKED", PC))

        assigned = fixtures.refresh_commitment(api, commitment["id"])
        assert assigned["status"] == "ASSIGNED"
        assigned_version = assigned["version"]
        encumbered = fixtures.refresh_allocation(
            api, program["id"], baseline["allocation"]["id"]
        )["encumbered_amount_cents"]
        assert encumbered == 222588

        blocked = api.set_commitment_status(commitment["id"], "ACTIVE", PC)
        validate_error(blocked, ApiErrorId.INVALID_STATE.value, 409)
        untouched = fixtures.refresh_commitment(api, commitment["id"])
        assert untouched["status"] == "ASSIGNED"
        assert untouched["version"] == assigned_version

        opened = validate_success(api.set_program_status(program["id"], "OPEN", PC))
        assert opened["status"] == "OPEN"

        activated = validate_success(
            api.set_commitment_status(commitment["id"], "ACTIVE", PC)
        )
        assert activated["status"] == "ACTIVE"
        assert activated["version"] == assigned_version + 1
        assert activated["planned_total_minutes"] == 1376
        assert activated["weekly_minutes_committed"] == 229
        assert activated["daily_minutes"] == 57
        assert (
            fixtures.refresh_allocation(
                api, program["id"], baseline["allocation"]["id"]
            )["encumbered_amount_cents"]
            == 222588
        )

    def test_activation_is_equally_blocked_while_the_program_is_still_planning(
        self, api
    ):
        """A commitment can reach `ASSIGNED` before its program leaves `PLANNING`, and still not go live.

        The gate names one permitted parent state and no others: "Activation
        (`ASSIGNED → ACTIVE`) requires the commitment to be in `ASSIGNED` and
        additionally requires its program's `status` to read `OPEN`; a commitment cannot
        go live before its session does, and the mismatch returns `ERR_INVALID_STATE`."
        Reaching `ASSIGNED` is independent of the program's own progress: "The step out
        of `PLANNED` is not a client operation at all: the moment the commitment's first
        provider assignment reaches `ACTIVE`, the system advances `PLANNED → ASSIGNED`
        and increments the commitment's `version` by one."

        Design: Difficulty/cross_entity_state_dependency/commitment_activation_requires_open_program
        """
        baseline = fixtures.setup_baseline(
            api,
            clock=CLOCK,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        program, commitment = baseline["program"], baseline["commitment"]

        assigned = fixtures.refresh_commitment(api, commitment["id"])
        assert assigned["status"] == "ASSIGNED"
        assert fixtures.refresh_program(api, program["id"])["status"] == "PLANNING"

        blocked = api.set_commitment_status(commitment["id"], "ACTIVE", PC)

        validate_error(blocked, ApiErrorId.INVALID_STATE.value, 409)
        after = fixtures.refresh_commitment(api, commitment["id"])
        assert after["status"] == "ASSIGNED"
        assert after["version"] == assigned["version"]
