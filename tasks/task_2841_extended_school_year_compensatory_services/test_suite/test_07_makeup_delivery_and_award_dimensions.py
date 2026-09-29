"""Makeup delivery: the two award dimensions, the outcome fork and the gates.

Every test in this module translates exactly one instance of the difficulty or
corner design index; the trailing `Design:` line of each docstring names it.
"""

from test_helpers import (
    CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT,
    CANON_AWARD_COMPUTED_MINUTES_MFM,
    CANON_AWARD_COMPUTED_MINUTES_QB,
    CANON_BUDGET_CODE,
    CANON_DELIVERY_DEADLINE_DATE,
    CANON_MAKEUP_CHARGE_30_MIN,
    CANON_MAKEUP_CHARGE_45_MIN,
    CANON_MAKEUP_CHARGE_60_MIN,
    CANON_SESSION_DATE_1,
    CANON_SESSION_DATE_2,
    CANON_SESSION_DATE_3,
    CANON_SESSION_DATE_OUT_OF_WINDOW,
    CANON_TOTAL_CHARGE_CENTS,
    ApiErrorId,
    assert_allocation_available_identity,
    assert_award,
    assert_award_remaining_identity,
    assert_makeup_session,
    factories,
    fixtures,
    make_case_manager_headers,
    make_compliance_officer_headers,
    make_parent_guardian_headers,
    make_related_service_provider_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
CO = make_compliance_officer_headers()


def _book(
    api,
    award_id,
    provider_id,
    minutes_planned,
    session_date,
    start_time,
    end_time,
    expected_award_version=None,
):
    """Raw booking call; the award's freshest `version` is used when none given."""
    if expected_award_version is None:
        expected_award_version = fixtures.refresh_award(api, award_id)["version"]
    return api.create_makeup_session(
        factories.makeup_session_payload(
            award_id,
            provider_id,
            expected_award_version,
            session_date=session_date,
            start_time=start_time,
            end_time=end_time,
            minutes_planned=minutes_planned,
        ),
        CM,
    )


def _session_count(api, award_id: str) -> int:
    _rows, meta = validate_paginated(
        api.list_makeup_sessions(CM, {"award_id": award_id, "limit": 100})
    )
    return meta["total_count"]


def _deliver(api, session_id, provider_id, minutes_delivered):
    return api.log_makeup_outcome(
        session_id,
        {"outcome": "DELIVERED", "minutes_delivered": minutes_delivered},
        make_related_service_provider_headers(provider_id),
    )


class TestAwardParallelDimensions:
    """Negotiation and delivery move independently, and the cycle runs backwards."""

    def _two_deliveries(self, api):
        """A QUALITATIVE_BENEFIT award of 105 minutes delivered as 60 then 45."""
        context = fixtures.setup_agreed_award(
            api,
            calculation_variant="QUALITATIVE_BENEFIT",
            proposed_minutes=CANON_AWARD_COMPUTED_MINUTES_QB,
        )
        award_id = context["award"]["id"]
        provider_id = context["provider"]["id"]

        first = validate_success(
            _book(api, award_id, provider_id, 60, CANON_SESSION_DATE_1, "15:00", "16:00"),
            201,
        )
        validate_success(_deliver(api, first["id"], provider_id, 60))

        second = validate_success(
            _book(api, award_id, provider_id, 45, CANON_SESSION_DATE_2, "15:00", "15:45"),
            201,
        )
        validate_success(_deliver(api, second["id"], provider_id, 45))

        context = dict(context)
        context["first_session"] = first
        context["second_session"] = second
        return context

    def test_the_second_delivery_fulfils_delivery_and_closes_the_negotiation(self, api):
        """105 agreed minutes delivered in two sittings reach FULFILLED and CLOSED.

        The first delivery of 60 against 105 owed leaves a balance, so the delivery
        dimension only advances one step: "It begins at `NOT_STARTED`, reaches
        `SCHEDULING` when the award's first session is booked, and advances
        `SCHEDULING → IN_PROGRESS` when the award's first session reaches
        `DELIVERED` while the resulting `remaining_owed_minutes` is still greater
        than zero." The second delivery of 45 empties the balance, and that pulls
        the *other* dimension with it: "From either `SCHEDULING` or `IN_PROGRESS`,
        an outcome that brings `remaining_owed_minutes` to exactly zero advances
        the dimension to `FULFILLED`, which in turn triggers the negotiation
        dimension's `AGREED → CLOSED` move." — "When the delivery dimension
        reaches either `FULFILLED` or `LAPSED`, the system moves the negotiation
        dimension `AGREED → CLOSED`, increments the award's `version`, and
        recomputes the student's `outstanding_owed_minutes` — noting that a
        `CLOSED` award still contributes its `remaining_owed_minutes`, which is
        zero for a fulfilled award and greater than zero for a lapsed one."

        Design: Difficulty/non_linear_state_machine/award_parallel_dimensions_and_fulfilled_to_in_progress_cycle
        """
        context = self._two_deliveries(api)
        award = fixtures.refresh_award(api, context["award"]["id"])
        assert_award(award)
        assert award["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_QB
        assert award["delivered_minutes"] == CANON_AWARD_COMPUTED_MINUTES_QB
        assert award["scheduled_minutes"] == 0
        assert award["remaining_owed_minutes"] == 0
        assert award["delivery_status"] == "FULFILLED"
        assert award["negotiation_status"] == "CLOSED"
        assert award["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert_award_remaining_identity(award)

        first = fixtures.refresh_session(api, context["first_session"]["id"])
        second = fixtures.refresh_session(api, context["second_session"]["id"])
        assert_makeup_session(first)
        assert first["status"] == "DELIVERED"
        assert first["minutes_delivered"] == 60
        assert first["charge_cents"] == CANON_MAKEUP_CHARGE_60_MIN
        assert second["status"] == "DELIVERED"
        assert second["minutes_delivered"] == 45
        assert second["charge_cents"] == CANON_MAKEUP_CHARGE_45_MIN

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["outstanding_owed_minutes"] == 0
        assert student["delivered_makeup_minutes_total"] == (
            CANON_AWARD_COMPUTED_MINUTES_QB
        )

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        both_charges = CANON_MAKEUP_CHARGE_60_MIN + CANON_MAKEUP_CHARGE_45_MIN
        assert allocation["expended_amount_cents"] == both_charges
        assert allocation["compensatory_expended_cents"] == both_charges
        assert allocation["encumbered_amount_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert allocation["available_cents"] == (
            CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT - both_charges
        )
        assert_allocation_available_identity(allocation)

    def test_voiding_the_last_delivery_cycles_fulfilled_back_to_in_progress(self, api):
        """The void reopens the debt on both dimensions at once.

        "First, the cycle: voiding a `DELIVERED` session against a `FULFILLED`
        award moves the delivery dimension `FULFILLED → IN_PROGRESS` whenever the
        resulting `remaining_owed_minutes` is greater than zero, and drags the
        negotiation dimension back with it from `CLOSED` to `AGREED`." The 45
        voided minutes leave every ledger they entered, because "It reverses the
        delivery precisely: the session's `minutes_delivered` leaves the award's
        `delivered_minutes`, so `remaining_owed_minutes` and the student's
        `outstanding_owed_minutes` return to their pre-delivery values; and the
        allocation's `expended_amount_cents` and `compensatory_expended_cents`
        both drop by the session's `charge_cents`, so `available_cents` returns to
        its pre-delivery value." The negotiated figure itself never moves: 105
        stays agreed and the deadline stays where the agreement put it.

        Design: Difficulty/non_linear_state_machine/award_parallel_dimensions_and_fulfilled_to_in_progress_cycle
        """
        context = self._two_deliveries(api)
        second_id = context["second_session"]["id"]

        voided = validate_success(
            api.log_makeup_outcome(
                second_id,
                {"outcome": "VOIDED", "outcome_note": "Session never took place"},
                CO,
            )
        )
        assert voided["status"] == "VOIDED"

        award = fixtures.refresh_award(api, context["award"]["id"])
        assert award["delivery_status"] == "IN_PROGRESS"
        assert award["negotiation_status"] == "AGREED"
        assert award["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_QB
        assert award["delivered_minutes"] == 60
        assert award["scheduled_minutes"] == 0
        assert award["forfeited_minutes"] == 0
        assert award["remaining_owed_minutes"] == 45
        assert award["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["outstanding_owed_minutes"] == 45
        assert student["delivered_makeup_minutes_total"] == 60

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation["expended_amount_cents"] == CANON_MAKEUP_CHARGE_60_MIN
        assert allocation["compensatory_expended_cents"] == CANON_MAKEUP_CHARGE_60_MIN
        assert allocation["available_cents"] == (
            CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT - CANON_MAKEUP_CHARGE_60_MIN
        )
        assert_allocation_available_identity(allocation)


class TestMakeupOutcomeFork:
    """Three outcomes out of SCHEDULED, three deliberately different effect sets."""

    def test_a_delivery_charges_a_fund_while_a_parent_no_show_charges_nothing(self, api):
        """Two identical 30-minute sessions diverge completely on their outcome.

        The delivered one pays a provider: "The `minutes_delivered` are credited,
        and the session is priced through the waterfall of §2.9 in expending mode:
        `charge_cents`, `charged_fund_source` and `charged_budget_code` are written
        on the session, and the selected allocation's `expended_amount_cents` and
        `compensatory_expended_cents` both rise by that charge — subject first to
        the federal compensatory cap, which answers `ERR_SUPPLANT_RESTRICTION`."
        The no-show pays nobody: "Logging a parent no-show advances
        `SCHEDULED → NO_SHOW_PARENT`, which is terminal." and "No minutes are
        credited and no fund is charged at all." It is counted, though — "The
        award's `parent_no_show_count` — which counts exactly the award's sessions
        sitting in `NO_SHOW_PARENT` — increases by one, and both the session's
        `version` and the award's `version` increment." — and with one no-show the
        forfeiture threshold has not yet been reached: "Here the forfeiture
        threshold bites: once the recomputed `parent_no_show_count` reaches two,
        this session's `minutes_planned` is added to the award's
        `forfeited_minutes`, which lowers `remaining_owed_minutes` and in turn
        lowers the student's `outstanding_owed_minutes`." Neither outcome leaves
        minutes in `scheduled_minutes`, since "Sessions in `SUPERSEDED`, `VOIDED`,
        `NO_SHOW_PARENT` or `CANCELLED_DISTRICT` contribute to neither sum."

        Design: Difficulty/non_linear_state_machine/makeup_session_branch_fork_has_divergent_side_effect_sets
        """
        context = fixtures.setup_agreed_award(
            api,
            calculation_variant="QUALITATIVE_BENEFIT",
            proposed_minutes=CANON_AWARD_COMPUTED_MINUTES_QB,
        )
        award_id = context["award"]["id"]
        provider_id = context["provider"]["id"]

        delivered_session = validate_success(
            _book(api, award_id, provider_id, 30, CANON_SESSION_DATE_1, "10:00", "10:30"),
            201,
        )
        no_show_session = validate_success(
            _book(api, award_id, provider_id, 30, CANON_SESSION_DATE_2, "10:00", "10:30"),
            201,
        )

        delivered = validate_success(
            _deliver(api, delivered_session["id"], provider_id, 30)
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["minutes_delivered"] == 30
        assert delivered["charge_cents"] == CANON_MAKEUP_CHARGE_30_MIN
        assert delivered["charged_fund_source"] == "IDEA_611_FEDERAL"
        assert delivered["charged_budget_code"] == CANON_BUDGET_CODE

        no_show = validate_success(
            api.log_makeup_outcome(
                no_show_session["id"],
                {"outcome": "NO_SHOW_PARENT", "outcome_note": "Family did not attend"},
                make_related_service_provider_headers(provider_id),
            )
        )
        assert_makeup_session(no_show)
        assert no_show["status"] == "NO_SHOW_PARENT"
        assert no_show["minutes_delivered"] == 0
        assert no_show["charge_cents"] == 0
        assert no_show["charged_fund_source"] is None
        assert no_show["charged_budget_code"] is None

        award = fixtures.refresh_award(api, award_id)
        assert award["delivered_minutes"] == 30
        assert award["scheduled_minutes"] == 0
        assert award["remaining_owed_minutes"] == 75
        assert award["parent_no_show_count"] == 1
        assert award["forfeited_minutes"] == 0
        assert award["delivery_status"] == "IN_PROGRESS"
        assert award["negotiation_status"] == "AGREED"
        assert award["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["outstanding_owed_minutes"] == 75
        assert student["delivered_makeup_minutes_total"] == 30

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation["expended_amount_cents"] == CANON_MAKEUP_CHARGE_30_MIN
        assert allocation["compensatory_expended_cents"] == CANON_MAKEUP_CHARGE_30_MIN
        assert allocation["encumbered_amount_cents"] == CANON_TOTAL_CHARGE_CENTS
        assert_allocation_available_identity(allocation)

    def test_a_district_cancellation_returns_the_minutes_and_extends_the_deadline(
        self, api
    ):
        """The third branch charges nothing and hands the minutes back for rebooking.

        "Logging a district cancellation advances
        `SCHEDULED → CANCELLED_DISTRICT`, also terminal, and is the mirror image of
        a no-show." Its ledger effect is the opposite of a forfeiture: "No minutes
        are credited and no fund is charged, but the minutes **return to the
        schedulable pool**: the session's `minutes_planned` leaves
        `scheduled_minutes` while `remaining_owed_minutes` stays exactly where it
        was, so the same minutes can be rebooked." And the district pays for its
        own failure in time: "In compensation for the district's own failure, the
        award's `delivery_deadline_date` is extended by a further thirty days." —
        2028-01-29 becomes 2028-02-28. The rebooking of the same 60 minutes proves
        the pool really did reopen.

        Design: Difficulty/non_linear_state_machine/makeup_session_branch_fork_has_divergent_side_effect_sets
        """
        context = fixtures.setup_scheduled_session(api, minutes_planned=60)
        award_id = context["award"]["id"]
        provider_id = context["provider"]["id"]

        cancelled = validate_success(
            api.log_makeup_outcome(
                context["session"]["id"],
                {
                    "outcome": "CANCELLED_DISTRICT",
                    "outcome_note": "Provider absent, district fault",
                },
                make_related_service_provider_headers(provider_id),
            )
        )
        assert cancelled["status"] == "CANCELLED_DISTRICT"
        assert cancelled["minutes_delivered"] == 0
        assert cancelled["charge_cents"] == 0
        assert cancelled["charged_fund_source"] is None

        award = fixtures.refresh_award(api, award_id)
        assert award["delivered_minutes"] == 0
        assert award["scheduled_minutes"] == 0
        assert award["forfeited_minutes"] == 0
        assert award["parent_no_show_count"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivery_deadline_date"] == "2028-02-28"
        assert award["negotiation_status"] == "AGREED"
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["outstanding_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert student["delivered_makeup_minutes_total"] == 0

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation["expended_amount_cents"] == 0
        assert allocation["compensatory_expended_cents"] == 0
        assert allocation["available_cents"] == CANON_AVAILABLE_AFTER_ONE_ASSIGNMENT

        rebooked = validate_success(
            _book(api, award_id, provider_id, 60, CANON_SESSION_DATE_3, "10:00", "11:00"),
            201,
        )
        assert rebooked["status"] == "SCHEDULED"
        assert rebooked["minutes_planned"] == 60
        assert _session_count(api, award_id) == 2


def _refresh_record(api, student_id: str, record_id: str):
    """Re-read one due-process record through the student's record list."""
    rows, _meta = validate_paginated(
        api.list_student_due_process_records(student_id, CO, {"limit": 100})
    )
    for row in rows:
        if row["id"] == record_id:
            return row
    raise AssertionError(f"record {record_id} is not listed under student {student_id}")


class TestMakeupDeliveryCascade:
    """One delivery, three cascade links: award, student, due-process record."""

    def test_a_full_delivery_resolves_the_students_open_mediation_agreement(self, api):
        """Delivering the last owed minute resolves a record nobody named.

        The delivery drives the award to zero and the student's ledger with it:
        "The student's ledger is recomputed, lowering `outstanding_owed_minutes`
        and raising `delivered_makeup_minutes_total`, with the student's `version`
        incremented by one." The third link fires off that zero alone: "And
        finally, when the recomputed `outstanding_owed_minutes` has reached exactly
        zero, every due-process record of that student whose `status` is `OPEN` and
        whose `record_type` is `MEDIATION_AGREEMENT` moves to `RESOLVED`, carrying
        `resolution_note` `OWED_MINUTES_SATISFIED` and `resolved_at` set to the
        current logical clock instant." The mediation record never raised stay-put
        in the first place, because "a `COMPLAINT` and a `DUE_PROCESS_HEARING`
        assert **stay-put** protection the moment they are filed, while a
        `MEDIATION_AGREEMENT` does not."

        Design: Difficulty/transitive_cascade/makeup_delivery_cascades_award_to_student_to_due_process_resolution
        """
        context = fixtures.setup_agreed_award(api)
        award_id = context["award"]["id"]
        student_id = context["student"]["id"]
        provider_id = context["provider"]["id"]

        record = fixtures.file_due_process_record(
            api,
            student_id,
            record_type="MEDIATION_AGREEMENT",
            allegation_summary="Mediated settlement: district to deliver 85 minutes.",
        )
        assert record["status"] == "OPEN"
        assert record["stay_put_active"] is False
        assert record["resolved_at"] is None

        student = fixtures.refresh_student(api, student_id)
        assert student["stay_put_active"] is False
        assert student["outstanding_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM

        session = validate_success(
            _book(
                api,
                award_id,
                provider_id,
                CANON_AWARD_COMPUTED_MINUTES_MFM,
                CANON_SESSION_DATE_1,
                "10:00",
                "11:25",
            ),
            201,
        )
        delivered = validate_success(
            _deliver(api, session["id"], provider_id, CANON_AWARD_COMPUTED_MINUTES_MFM)
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["minutes_delivered"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        # 85 minutes at 150 cents plus the eight-percent federal indirect rate.
        assert delivered["charge_cents"] == 13770
        assert delivered["charged_fund_source"] == "IDEA_611_FEDERAL"

        award = fixtures.refresh_award(api, award_id)
        assert award["delivered_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["remaining_owed_minutes"] == 0
        assert award["delivery_status"] == "FULFILLED"
        assert award["negotiation_status"] == "CLOSED"
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == 0
        assert student["delivered_makeup_minutes_total"] == (
            CANON_AWARD_COMPUTED_MINUTES_MFM
        )

        resolved = _refresh_record(api, student_id, record["id"])
        assert resolved["status"] == "RESOLVED"
        assert resolved["resolution_note"] == "OWED_MINUTES_SATISFIED"
        assert resolved["stay_put_active"] is False
        assert resolved["resolved_at"] is not None
        assert resolved["resolved_at"].startswith("2027-08-02T00:00:00")

    def test_a_partial_delivery_leaves_the_mediation_record_open(self, api):
        """45 of 85 owed minutes stops the cascade at link two.

        The award and the student both move — "The student's ledger is recomputed,
        lowering `outstanding_owed_minutes` and raising
        `delivered_makeup_minutes_total`, with the student's `version` incremented
        by one." — but the third link is conditioned on an exact zero: "And
        finally, when the recomputed `outstanding_owed_minutes` has reached exactly
        zero, every due-process record of that student whose `status` is `OPEN` and
        whose `record_type` is `MEDIATION_AGREEMENT` moves to `RESOLVED`, carrying
        `resolution_note` `OWED_MINUTES_SATISFIED` and `resolved_at` set to the
        current logical clock instant." With 40 minutes still owed the record stays
        exactly as filed, and the award's own dimension stops at `IN_PROGRESS`
        rather than `FULFILLED`.

        Design: Difficulty/transitive_cascade/makeup_delivery_cascades_award_to_student_to_due_process_resolution
        """
        context = fixtures.setup_agreed_award(api)
        award_id = context["award"]["id"]
        student_id = context["student"]["id"]
        provider_id = context["provider"]["id"]

        record = fixtures.file_due_process_record(
            api,
            student_id,
            record_type="MEDIATION_AGREEMENT",
            allegation_summary="Mediated settlement: district to deliver 85 minutes.",
        )

        session = validate_success(
            _book(api, award_id, provider_id, 60, CANON_SESSION_DATE_1, "10:00", "11:00"),
            201,
        )
        validate_success(_deliver(api, session["id"], provider_id, 45))

        award = fixtures.refresh_award(api, award_id)
        assert award["delivered_minutes"] == 45
        assert award["remaining_owed_minutes"] == 40
        assert award["delivery_status"] == "IN_PROGRESS"
        assert award["negotiation_status"] == "AGREED"

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == 40
        assert student["delivered_makeup_minutes_total"] == 45

        still_open = _refresh_record(api, student_id, record["id"])
        assert still_open["status"] == "OPEN"
        assert still_open["resolution_note"] is None
        assert still_open["resolved_at"] is None
        assert still_open["stay_put_active"] is False


class TestMakeupWindowBeatsOverbooking:
    """Check 19 masks check 27 on the booking endpoint."""

    def test_an_out_of_window_overbooked_booking_reports_the_window_error(self, api):
        """480 minutes on 2028-03-01 violates both gates and answers the earlier one.

        "The service therefore evaluates its checks in one fixed global order and
        returns the first violation it finds. The order below is normative; a check
        numbered lower always masks a check numbered higher." The window sits at
        nineteen — "19. The makeup session's `session_date` lies inside the award's
        delivery window — otherwise `ERR_MAKEUP_OUTSIDE_WINDOW`. Applies to
        makeup-session creation only." — and the overbooking guard at twenty-seven:
        "27. Booking the new session would not overbook the award — otherwise
        `ERR_OVERBOOKED_MAKEUP_MINUTES`. Applies to makeup-session creation only."
        The fiscal-only control isolates the masked check: an in-window request for
        the same 480 minutes draws the overbooking error, since "To book,
        `scheduled_minutes` plus the new session's `minutes_planned` must not exceed
        `remaining_owed_minutes`; exceeding it is refused with
        `ERR_OVERBOOKED_MAKEUP_MINUTES`."

        Design: Difficulty/priority_pair_validation_conflict/makeup_outside_delivery_window_beats_overbooked_minutes
        """
        context = fixtures.setup_agreed_award(api)
        award_id = context["award"]["id"]
        provider_id = context["provider"]["id"]

        award = fixtures.refresh_award(api, award_id)
        assert award["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert award["delivery_status"] == "NOT_STARTED"

        validate_error(
            _book(
                api,
                award_id,
                provider_id,
                480,
                CANON_SESSION_DATE_OUT_OF_WINDOW,
                "09:00",
                "17:00",
            ),
            ApiErrorId.MAKEUP_OUTSIDE_WINDOW,
            422,
        )

        validate_error(
            _book(api, award_id, provider_id, 480, CANON_SESSION_DATE_1, "09:00", "17:00"),
            ApiErrorId.OVERBOOKED_MAKEUP_MINUTES,
            422,
        )

        assert _session_count(api, award_id) == 0
        unchanged = fixtures.refresh_award(api, award_id)
        assert unchanged["scheduled_minutes"] == 0
        assert unchanged["delivery_status"] == "NOT_STARTED"

    def test_the_temporal_gate_fires_alone_and_a_fitting_booking_lands(self, api):
        """A 60-minute request outside the window still fails; 85 inside it succeeds.

        The date gate does not care how many minutes are asked for: "The
        `session_date` itself must fall on or after the calendar date of the current
        logical clock and on or before the award's `delivery_deadline_date`; a
        booking in the past or past the deadline is refused with
        `ERR_MAKEUP_OUTSIDE_WINDOW`." With both gates satisfied the booking lands
        and only the delivery dimension moves: "And the first session ever created
        for an award advances the delivery dimension `NOT_STARTED → SCHEDULING` —
        permitted only while `negotiation_status` reads `AGREED` — recomputing
        `scheduled_minutes` and incrementing the award's `version`." Booking is not
        delivering, so nothing is charged and the owed figure is untouched:
        "`remaining_owed_minutes` is `agreed_minutes` (treated as zero while still
        null) less `delivered_minutes` less `forfeited_minutes`, with any negative
        result clamped to zero."

        Design: Difficulty/priority_pair_validation_conflict/makeup_outside_delivery_window_beats_overbooked_minutes
        """
        context = fixtures.setup_agreed_award(api)
        award_id = context["award"]["id"]
        provider_id = context["provider"]["id"]

        validate_error(
            _book(
                api,
                award_id,
                provider_id,
                60,
                CANON_SESSION_DATE_OUT_OF_WINDOW,
                "10:00",
                "11:00",
            ),
            ApiErrorId.MAKEUP_OUTSIDE_WINDOW,
            422,
        )

        session = validate_success(
            _book(
                api,
                award_id,
                provider_id,
                CANON_AWARD_COMPUTED_MINUTES_MFM,
                CANON_SESSION_DATE_1,
                "10:00",
                "11:25",
            ),
            201,
        )
        assert_makeup_session(session)
        assert session["status"] == "SCHEDULED"
        assert session["minutes_planned"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert session["minutes_delivered"] == 0
        assert session["charge_cents"] == 0
        assert session["charged_fund_source"] is None

        award = fixtures.refresh_award(api, award_id)
        assert award["scheduled_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivered_minutes"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivery_status"] == "SCHEDULING"
        assert award["negotiation_status"] == "AGREED"
        assert_award_remaining_identity(award)
        assert _session_count(api, award_id) == 1

        allocation = fixtures.refresh_allocation(
            api, context["program"]["id"], context["allocation"]["id"]
        )
        assert allocation["expended_amount_cents"] == 0
        assert allocation["encumbered_amount_cents"] == CANON_TOTAL_CHARGE_CENTS


class TestBookingRequiresAgreedAward:
    """The award named in the body is the entity whose state gates the booking."""

    def _proposed_award(self, api):
        context = fixtures.setup_baseline(api)
        award = fixtures.open_award(
            api, context["student"]["id"], context["program"]["id"]
        )
        award = validate_success(
            api.propose_award(
                award["id"],
                {"proposed_minutes": CANON_AWARD_COMPUTED_MINUTES_MFM},
                CM,
            )
        )
        fixtures.set_clock(api, "2027-08-02T00:00:00Z")
        context = dict(context)
        context["award"] = fixtures.refresh_award(api, award["id"])
        return context

    def test_a_booking_against_a_parent_review_award_is_refused(self, api):
        """The state gate answers before the window gate, even with no deadline set.

        Booking reads the award's negotiation dimension first: "The award's
        `negotiation_status` must read `AGREED` — a draft, disputed, mediated,
        declined or closed award accepts no bookings, and the attempt returns
        `ERR_INVALID_STATE`, as does any booking against an award whose
        `delivery_status` has reached `LAPSED`." That guard is folded into check
        nine, which masks the window check at nineteen: "The cross-entity guards
        folded into this check are: a commitment may only be activated while its
        program is `OPEN`; a makeup session may only be booked against an award
        whose negotiation dimension reads `AGREED` and whose delivery dimension is
        not `LAPSED`; and an allocation may only be closed while its encumbered
        balance is zero." A `PARENT_REVIEW` award has no `delivery_deadline_date`
        at all — that date is only written on the parent's agreement — and the
        rejection is still the state error, not the window error.

        Design: Difficulty/cross_entity_state_dependency/makeup_booking_requires_agreed_award
        """
        context = self._proposed_award(api)
        award = context["award"]
        award_id = award["id"]
        provider_id = context["provider"]["id"]

        assert award["negotiation_status"] == "PARENT_REVIEW"
        assert award["proposed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["agreed_minutes"] is None
        assert award["delivery_deadline_date"] is None
        assert award["delivery_status"] == "NOT_STARTED"
        version_before = award["version"]

        validate_error(
            _book(api, award_id, provider_id, 60, CANON_SESSION_DATE_1, "10:00", "11:00"),
            ApiErrorId.INVALID_STATE,
            409,
        )

        assert _session_count(api, award_id) == 0
        unchanged = fixtures.refresh_award(api, award_id)
        assert unchanged["version"] == version_before
        assert unchanged["delivery_status"] == "NOT_STARTED"
        assert unchanged["scheduled_minutes"] == 0

    def test_the_same_booking_lands_once_the_parent_agrees(self, api):
        """The parent's AGREE opens the window and the identical body is accepted.

        "`AGREE` completes `PARENT_REVIEW → AGREED`: `agreed_minutes` is set to
        `proposed_minutes`, `delivery_deadline_date` is set to the calendar date of
        the current logical clock plus one hundred and eighty days, the student's
        `outstanding_owed_minutes` is recomputed and the student's `version`
        increments by one, and the award's `version` increments." Only then may a
        session be booked, and the booking moves the delivery dimension without
        touching the debt: "And the first session ever created for an award advances
        the delivery dimension `NOT_STARTED → SCHEDULING` — permitted only while
        `negotiation_status` reads `AGREED` — recomputing `scheduled_minutes` and
        incrementing the award's `version`."

        Design: Difficulty/cross_entity_state_dependency/makeup_booking_requires_agreed_award
        """
        context = self._proposed_award(api)
        award_id = context["award"]["id"]
        student_id = context["student"]["id"]
        provider_id = context["provider"]["id"]

        agreed = validate_success(
            api.award_parent_response(
                award_id,
                {"response": "AGREE"},
                make_parent_guardian_headers(student_id),
            )
        )
        assert agreed["negotiation_status"] == "AGREED"
        assert agreed["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert agreed["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert agreed["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM

        session = validate_success(
            _book(api, award_id, provider_id, 60, CANON_SESSION_DATE_1, "10:00", "11:00"),
            201,
        )
        assert session["status"] == "SCHEDULED"
        assert session["minutes_planned"] == 60

        award = fixtures.refresh_award(api, award_id)
        assert award["delivery_status"] == "SCHEDULING"
        assert award["scheduled_minutes"] == 60
        assert award["delivered_minutes"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert_award_remaining_identity(award)

        student = fixtures.refresh_student(api, student_id)
        assert student["outstanding_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert student["delivered_makeup_minutes_total"] == 0


class TestBookingConcurrencyAndLapse:
    """The OCC guard on the award, and the lazy lapse a plain read triggers."""

    def test_a_stale_expected_award_version_is_a_precondition_failure(self, api):
        """Re-using the version the first booking consumed draws a 412.

        "Creating a makeup session — `POST /esy/makeup-sessions` — requires the
        non-optional field `expected_award_version`, carrying the client's last
        observed `version` of the target `CompensatoryAward`." The first booking of
        60 minutes bumps that version, so the second booking's copy is obsolete:
        "A mismatch against the award's current `version` is rejected with
        `ERR_STALE_AWARD_VERSION` (HTTP 412)." Nothing else about the second
        booking is wrong — the re-read version books the same 25 minutes — which is
        exactly what the guard is for: "Nothing in the award's state machine stops a
        scheduler from booking additional minutes, so this check is the only thing
        preventing a scheduler from booking against an obsolete
        `remaining_owed_minutes`, an obsolete `delivery_deadline_date`, or an
        `agreed_minutes` figure a director has since revised."

        Design: Corner/cross_cutting_layers/stale_award_version_on_makeup_create_returns_412
        """
        context = fixtures.setup_agreed_award(api)
        award_id = context["award"]["id"]
        provider_id = context["provider"]["id"]

        stale_version = fixtures.refresh_award(api, award_id)["version"]
        first = validate_success(
            _book(
                api,
                award_id,
                provider_id,
                60,
                CANON_SESSION_DATE_1,
                "10:00",
                "11:00",
                expected_award_version=stale_version,
            ),
            201,
        )
        assert first["status"] == "SCHEDULED"

        validate_error(
            _book(
                api,
                award_id,
                provider_id,
                25,
                CANON_SESSION_DATE_2,
                "10:00",
                "10:25",
                expected_award_version=stale_version,
            ),
            ApiErrorId.STALE_AWARD_VERSION,
            412,
        )

        award = fixtures.refresh_award(api, award_id)
        assert award["scheduled_minutes"] == 60
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["version"] != stale_version
        assert _session_count(api, award_id) == 1

        second = validate_success(
            _book(api, award_id, provider_id, 25, CANON_SESSION_DATE_2, "10:00", "10:25"),
            201,
        )
        assert second["status"] == "SCHEDULED"
        assert second["minutes_planned"] == 25

        award = fixtures.refresh_award(api, award_id)
        assert award["scheduled_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivered_minutes"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivery_status"] == "SCHEDULING"
        assert _session_count(api, award_id) == 2

    def test_reading_the_award_after_the_deadline_lapses_the_delivery(self, api):
        """A plain GET at 2028-01-30 finds the award LAPSED and CLOSED.

        "Second, the lapse: from either `SCHEDULING` or `IN_PROGRESS`, when
        `remaining_owed_minutes` is greater than zero and the calendar date of the
        current logical clock is strictly later than the award's
        `delivery_deadline_date`, the delivery dimension moves to `LAPSED`, which is
        terminal, and that too triggers the negotiation dimension's
        `AGREED → CLOSED`." No request asks for that transition: "This evaluation is
        lazy: it is applied at the start of any request whose path or body references
        the award, which includes merely reading the award." The booked session is
        left alone — "Sessions already `SCHEDULED` against a lapsed award stay
        `SCHEDULED`, but no new session may be booked, and the attempt is refused
        with `ERR_MAKEUP_OUTSIDE_WINDOW`." — and the debt survives the closure, since
        a `CLOSED` award "still contributes its `remaining_owed_minutes`, which is
        zero for a fulfilled award and greater than zero for a lapsed one."

        Design: Corner/endpoints/award_delivery_lapses_once_the_clock_passes_the_deadline
        """
        context = fixtures.setup_scheduled_session(
            api,
            minutes_planned=CANON_AWARD_COMPUTED_MINUTES_MFM,
            start_time="10:00",
            end_time="11:25",
        )
        award_id = context["award"]["id"]
        session_id = context["session"]["id"]
        assert context["award"]["delivery_status"] == "SCHEDULING"

        fixtures.set_clock(api, "2028-01-30T00:00:00Z")

        award = fixtures.refresh_award(api, award_id)
        assert_award(award)
        assert award["delivery_status"] == "LAPSED"
        assert award["negotiation_status"] == "CLOSED"
        assert award["delivery_deadline_date"] == CANON_DELIVERY_DEADLINE_DATE
        assert award["agreed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert award["delivered_minutes"] == 0
        assert award["remaining_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
        assert_award_remaining_identity(award)

        session = fixtures.refresh_session(api, session_id)
        assert session["status"] == "SCHEDULED"
        assert session["minutes_delivered"] == 0

        student = fixtures.refresh_student(api, context["student"]["id"])
        assert student["outstanding_owed_minutes"] == CANON_AWARD_COMPUTED_MINUTES_MFM
