"""Determinations, the add-on waterfall, the priority ladder and the award run."""

from test_helpers import (
    AWARD_BAND_A_IEP_AND_FOSTER,
    AWARD_BAND_B_IEP,
    AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC,
    EO,
    PA,
    ApiErrorId,
    assert_eligibility_determination,
    assert_instant_equals,
    create_application,
    create_determination_payload,
    create_program_year,
    create_student,
    open_window,
    read_application,
    read_program_year,
    record_determination,
    set_clock,
    setup_open_year_and_student,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def _submitted(program_year_id, student_overrides, claimed_band, claimed_flags):
    """Carry one fresh student's application to SUBMITTED inside the open window."""
    student = create_student(**student_overrides)
    application = create_application(
        program_year_id,
        student["id"],
        claimed_income_band=claimed_band,
        claimed_category_flags=list(claimed_flags),
    )
    submit_application(application["id"], student["id"])
    return student, read_application(application["id"])


class TestAddonWaterfall:
    """The per-flag add-on waterfall against the 0.45 aggregate cap."""

    def test_flag_meeting_the_cap_is_truncated_to_the_remainder(self, api):
        """PRD §3.2: "With a flag set whose raw percentages together exceed the cap, the
        lowest-percentage admitted flag is truncated so the running total lands exactly
        on 0.45: `BAND_A` with `DISABILITY_IEP` and `FOSTER` yields 1060676, not
        1060675."

        PRD §3.3: "The determination's `verified_income_band`,
        `verified_category_flags`, `priority_tier`, `priority_score`, and
        `annual_award_cents` are copied onto the application, and the application's
        `version` rises by 1."

        Design: Difficulty/combinatorial_formula/addon_waterfall_truncates_last_flag_and_rounds_per_component
        """
        year = create_program_year()
        open_window(year["id"])
        set_clock("2026-09-01T00:00:00Z")
        _, application = _submitted(
            year["id"],
            {
                "household_id": "HH-4",
                "first_name": "Diego",
                "last_name": "Marin",
                "date_of_birth": "2013-11-20",
                "prior_enrollment": "PRIVATE_SCHOOL",
                "income_band": "BAND_A",
                "category_flags": ["DISABILITY_IEP", "FOSTER"],
            },
            "BAND_A",
            ["DISABILITY_IEP", "FOSTER"],
        )

        determination = validate_success(
            api.create_eligibility_determination(
                application["id"],
                create_determination_payload(
                    verified_income_band="BAND_A",
                    verified_prior_enrollment="PRIVATE_SCHOOL",
                    verified_category_flags=["DISABILITY_IEP", "FOSTER"],
                ),
                EO,
            ),
            expected_status=201,
        )
        assert_eligibility_determination(determination)

        assert determination["outcome"] == "ELIGIBLE", (
            f"both checks pass and the band is BAND_A, got {determination['outcome']!r}"
        )
        assert determination["annual_award_cents"] == AWARD_BAND_A_IEP_AND_FOSTER, (
            "FOSTER is truncated to the 0.075 cap remainder rather than dropped, so the "
            f"figure is 1060676, got {determination['annual_award_cents']}"
        )
        assert determination["annual_award_cents"] != 1060675, (
            "1060675 is what summing the percentages before applying them to the base "
            "would produce, and that order is wrong"
        )
        assert determination["round_number"] == 1, (
            "round_number is 1 for the first determination on an application, got "
            f"{determination['round_number']}"
        )
        assert determination["decided_by_user_id"] == EO["X-User-ID"], (
            "the row captures the officer's own X-User-ID as decided_by_user_id, got "
            f"{determination['decided_by_user_id']!r}"
        )
        assert determination["priority_tier"] == 4, (
            "prior enrolment is PRIVATE_SCHOOL so tier 3 cannot match and the confirmed "
            f"flags land the application in tier 4, got {determination['priority_tier']}"
        )
        assert determination["priority_score"] == 170, (
            "the income term is 100 for BAND_A and the category term adds 40 and 30, "
            f"giving 170, got {determination['priority_score']}"
        )
        assert determination["denial_reason_code"] is None, (
            "on an eligible outcome denial_reason_code is null, got "
            f"{determination['denial_reason_code']!r}"
        )

        after = read_application(application["id"])
        assert after["status"] == "ELIGIBLE", (
            f"an ELIGIBLE outcome advances SUBMITTED to ELIGIBLE, got {after['status']!r}"
        )
        assert after["annual_award_cents"] == AWARD_BAND_A_IEP_AND_FOSTER, (
            f"annual_award_cents is copied onto the application, got "
            f"{after['annual_award_cents']}"
        )
        assert after["priority_tier"] == 4 and after["priority_score"] == 170, (
            f"tier and score are copied onto the application, got {after!r}"
        )
        assert after["provisional_award_cents"] == AWARD_BAND_A_IEP_AND_FOSTER, (
            "the claimed variant reads the very same band and flags here, so it agrees "
            f"at 1060676, got {after['provisional_award_cents']}"
        )
        assert after["version"] == application["version"] + 1, (
            f"the application's version rises by 1, got {after['version']} from "
            f"{application['version']}"
        )

    def test_third_flag_contributes_nothing_and_components_round_individually(self, api):
        """PRD §3.2: "For each flag in the order fixed by step two, the percentage
        actually allowed is the smaller of that flag's own percentage and the cap less
        the running total. If the allowed percentage is zero or less, consumption stops
        and the remaining flags contribute nothing."

        PRD §3.2: "The two orders genuinely differ: for `BAND_B` with the flags
        `DISABILITY_IEP` and `PRIOR_PUBLIC_SCHOOL`, rounding each component before
        summing yields 978382 cents, whereas summing the percentages first would yield
        978381."

        Design: Difficulty/combinatorial_formula/addon_waterfall_truncates_last_flag_and_rounds_per_component
        """
        year = create_program_year(total_seats=5)
        open_window(year["id"])
        set_clock("2026-09-01T00:00:00Z")

        _, saturated = _submitted(
            year["id"],
            {
                "household_id": "HH-6",
                "first_name": "Iris",
                "last_name": "Navarro",
                "date_of_birth": "2013-02-14",
                "prior_enrollment": "PRIVATE_SCHOOL",
                "income_band": "BAND_A",
                "category_flags": ["DISABILITY_IEP", "FOSTER", "MILITARY"],
            },
            "BAND_A",
            ["DISABILITY_IEP", "FOSTER", "MILITARY"],
        )
        _, rounded = _submitted(
            year["id"],
            {
                "household_id": "HH-7",
                "first_name": "Omar",
                "last_name": "Peña",
                "date_of_birth": "2012-03-30",
                "prior_enrollment": "PUBLIC_SCHOOL_FULL_YEAR",
                "income_band": "BAND_B",
                "category_flags": ["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"],
            },
            "BAND_B",
            ["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"],
        )

        saturated_determination = record_determination(
            saturated["id"],
            verified_income_band="BAND_A",
            verified_prior_enrollment="PRIVATE_SCHOOL",
            verified_category_flags=["DISABILITY_IEP", "FOSTER", "MILITARY"],
        )
        assert saturated_determination["annual_award_cents"] == AWARD_BAND_A_IEP_AND_FOSTER, (
            "DISABILITY_IEP consumes 0.375 and FOSTER the remaining 0.075, so MILITARY "
            "meets a zero remainder and contributes nothing, leaving 1060676, got "
            f"{saturated_determination['annual_award_cents']}"
        )
        assert saturated_determination["priority_score"] == 185, (
            "the score is unaffected by the money cap: 100 plus 40 plus 30 plus 15 is "
            f"185, got {saturated_determination['priority_score']}"
        )

        rounded_determination = record_determination(
            rounded["id"],
            verified_income_band="BAND_B",
            verified_prior_enrollment="PUBLIC_SCHOOL_FULL_YEAR",
            verified_category_flags=["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"],
        )
        assert rounded_determination["annual_award_cents"] == AWARD_BAND_B_IEP_AND_PRIOR_PUBLIC, (
            "rounding each component before summing yields 978382 cents, got "
            f"{rounded_determination['annual_award_cents']}"
        )
        assert rounded_determination["annual_award_cents"] != 978381, (
            "978381 is the figure that summing the percentages first would give"
        )
        assert rounded_determination["priority_tier"] == 4, (
            "tier 3 needs BAND_A alongside the prior public schooling, so this lands in "
            f"tier 4, got {rounded_determination['priority_tier']}"
        )
        assert rounded_determination["priority_score"] == 110, (
            "the income term is 60 for BAND_B and the category term adds 40 and 10, "
            f"giving 110, got {rounded_determination['priority_score']}"
        )


class TestDeterminationAuthority:
    """The determination is exclusive to the eligibility officer."""

    def test_guardian_cannot_self_certify_their_own_application(self, api):
        """PRD §3.3: "An `EligibilityOfficer` adjudicates a submitted application by
        recording a **determination**, which is append-only evidence: each determination
        is a new row and no earlier row is ever edited."

        PRD §2.1: "When both headers are well formed but the declared role is not among
        the roles permitted for the endpoint being called, the rejection is
        `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/guardian_cannot_record_an_eligibility_determination
        """
        env = setup_submitted_application()

        response = api.create_eligibility_determination(
            env.application_id,
            create_determination_payload(
                verified_income_band="BAND_A",
                verified_category_flags=["DISABILITY_IEP", "FOSTER"],
            ),
            env.guardian,
        )
        validate_error(response, ApiErrorId.FORBIDDEN_ROLE.value, 403)

        application = read_application(env.application_id)
        assert application["status"] == "SUBMITTED", (
            f"the refused determination leaves the application in SUBMITTED, got "
            f"{application['status']!r}"
        )
        assert application["annual_award_cents"] == 0, (
            "an application whose eligibility has not been adjudicated still carries 0, "
            f"got {application['annual_award_cents']}"
        )
        assert application["priority_tier"] == 0, (
            "because tier and score are stamped only by a determination, an application "
            f"still sitting in SUBMITTED carries 0 for both, got "
            f"{application['priority_tier']}"
        )
        _, meta = validate_paginated(
            api.list_eligibility_determinations(env.application_id, PA)
        )
        assert meta["total_count"] == 0, (
            f"no determination row was written, got {meta['total_count']}"
        )


class TestAwardRun:
    """One run offers the best-ranked candidates and waitlists the overflow."""

    def test_two_seats_offer_the_top_two_and_waitlist_the_third(self, api):
        """PRD §3.4: "Working down that ranked list, the first `seats_available`
        candidates move `ELIGIBLE → AWARD_OFFERED`; each one stamps
        `acceptance_deadline_at` at the current logical instant plus the year's
        `acceptance_deadline_days` days, raises `seats_committed` by 1, lowers
        `seats_available` by 1, and has its own `version` incremented. Every candidate
        beyond that point moves `ELIGIBLE → WAITLISTED` and receives a
        `waitlist_position` of 1, 2, 3 and so on in the very same rank order"

        PRD §3.3: "When the eligible pool is later ranked, the ordering is by
        `priority_tier` ascending first, then by `priority_score` descending, then by
        `submitted_at` ascending, and finally by `created_at` ascending."

        Design: Corner/endpoints/awarding_run_awards_by_rank_and_waitlists_the_overflow
        """
        year = create_program_year(total_seats=2)
        open_window(year["id"])
        set_clock("2026-09-01T00:00:00Z")

        _, a1 = _submitted(
            year["id"], {}, "BAND_B", ["DISABILITY_IEP", "PRIOR_PUBLIC_SCHOOL"]
        )
        d1 = record_determination(
            a1["id"],
            verified_income_band="BAND_B",
            verified_prior_enrollment="PUBLIC_SCHOOL_FULL_YEAR",
            verified_category_flags=["DISABILITY_IEP"],
        )

        _, a5 = _submitted(
            year["id"],
            {
                "household_id": "HH-5",
                "first_name": "Elena",
                "last_name": "Cordova",
                "date_of_birth": "2013-05-09",
                "income_band": "BAND_A",
                "category_flags": ["DISABILITY_IEP"],
            },
            "BAND_A",
            ["DISABILITY_IEP"],
        )
        d5 = record_determination(
            a5["id"],
            verified_income_band="BAND_A",
            verified_prior_enrollment="PUBLIC_SCHOOL_FULL_YEAR",
            verified_category_flags=["DISABILITY_IEP"],
        )

        _, a2 = _submitted(
            year["id"],
            {
                "household_id": "HH-2",
                "first_name": "Beto",
                "last_name": "Salas",
                "date_of_birth": "2012-07-19",
                "prior_enrollment": "PRIVATE_SCHOOL",
                "category_flags": [],
            },
            "BAND_B",
            [],
        )
        d2 = record_determination(
            a2["id"],
            verified_income_band="BAND_B",
            verified_prior_enrollment="PRIVATE_SCHOOL",
            verified_category_flags=[],
        )

        assert (d1["priority_tier"], d1["priority_score"]) == (4, 100), (
            f"BAND_B with a confirmed flag is tier 4 scoring 100, got {d1!r}"
        )
        assert (d5["priority_tier"], d5["priority_score"]) == (3, 140), (
            "BAND_A with prior public schooling is tier 3 scoring 140, got "
            f"{(d5['priority_tier'], d5['priority_score'])!r}"
        )
        assert (d2["priority_tier"], d2["priority_score"]) == (5, 60), (
            "BAND_B with no confirmed flags is tier 5 scoring 60, got "
            f"{(d2['priority_tier'], d2['priority_score'])!r}"
        )

        run = validate_success(api.run_awarding(year["id"], PA))

        assert run["awarded_count"] == 2, (
            f"the two best-ranked candidates take the two seats, got "
            f"{run['awarded_count']}"
        )
        assert run["waitlisted_count"] == 1, (
            f"the third candidate is waitlisted rather than refused, got "
            f"{run['waitlisted_count']}"
        )
        assert run["awarded_application_ids"] == [a5["id"], a1["id"]], (
            "the tier ladder drives the order, so the tier 3 application is offered "
            f"ahead of the tier 4 one, got {run['awarded_application_ids']!r}"
        )
        assert run["waitlist_ordered_application_ids"] == [a2["id"]], (
            f"the tier 5 application is the only waitlisted one, got "
            f"{run['waitlist_ordered_application_ids']!r}"
        )
        assert run["program_year_status"] == "ACTIVE", (
            f"the run carries the year through to ACTIVE, got "
            f"{run['program_year_status']!r}"
        )
        assert run["seats_committed"] == 2 and run["seats_available"] == 0, (
            "seats_committed is the count of applications now in AWARD_OFFERED or "
            f"ACCEPTED and seats_available is total_seats less that count, got "
            f"committed {run['seats_committed']} / available {run['seats_available']}"
        )

        offered = read_application(a5["id"])
        assert offered["status"] == "AWARD_OFFERED", (
            f"the top-ranked candidate holds an offer, got {offered['status']!r}"
        )
        assert_instant_equals(
            offered["acceptance_deadline_at"],
            "2026-09-15T00:00:00Z",
            "acceptance_deadline_at is the logical instant plus 14 days",
        )
        assert read_application(a1["id"])["status"] == "AWARD_OFFERED", (
            "the second-ranked candidate holds the other offer"
        )
        waitlisted = read_application(a2["id"])
        assert waitlisted["status"] == "WAITLISTED", (
            f"the overflow candidate is waitlisted, got {waitlisted['status']!r}"
        )
        assert waitlisted["waitlist_position"] == 1, (
            f"the first overflow candidate receives waitlist_position 1, got "
            f"{waitlisted['waitlist_position']}"
        )


class TestEmptyEligiblePool:
    """A run over an empty candidate set is valid and still activates the year."""

    def test_run_with_no_eligible_candidate_returns_zero_counts(self, api):
        """PRD §3.4: "When the year has no eligible candidates at all the run is still
        valid and still succeeds: nothing is offered, nothing is waitlisted, and the year
        still reaches `ACTIVE`."

        PRD §3.3: "And because tier and score are stamped only by a determination, an
        application still sitting in `SUBMITTED` carries 0 for both and simply is not in
        the ranked pool at all."

        Design: Difficulty/boundary_precision_check/awarding_run_over_an_empty_eligible_set_returns_zero_counts
        """
        env = setup_submitted_application()
        before = read_program_year(env.program_year_id)
        assert before["seats_committed"] == 0 and before["seats_available"] == 2, (
            f"the seat pool is untouched before the run, got {before!r}"
        )

        response = api.run_awarding(env.program_year_id, PA)
        assert response.status_code == 200, (
            "the run over an empty candidate set is still valid and still succeeds, got "
            f"HTTP {response.status_code}"
        )
        run = validate_success(response)

        assert run["awarded_count"] == 0, (
            f"nothing is offered, got awarded_count {run['awarded_count']}"
        )
        assert run["waitlisted_count"] == 0, (
            f"nothing is waitlisted, got waitlisted_count {run['waitlisted_count']}"
        )
        assert run["awarded_application_ids"] == [], (
            f"the offered list is empty, got {run['awarded_application_ids']!r}"
        )
        assert run["waitlist_ordered_application_ids"] == [], (
            f"the waitlist is empty, got {run['waitlist_ordered_application_ids']!r}"
        )
        assert run["seats_committed"] == 0 and run["seats_available"] == 2, (
            "no seat is consumed by an empty run, got committed "
            f"{run['seats_committed']} / available {run['seats_available']}"
        )
        assert run["program_year_status"] == "ACTIVE", (
            f"the year still reaches ACTIVE, got {run['program_year_status']!r}"
        )

        application = read_application(env.application_id)
        assert application["status"] == "SUBMITTED", (
            "the undetermined application is not in the ranked pool at all and is not "
            f"awarded, got {application['status']!r}"
        )
        assert application["waitlist_position"] is None, (
            f"it is not waitlisted either, got {application['waitlist_position']!r}"
        )
        assert application["priority_score"] == 0, (
            "an application still sitting in SUBMITTED carries 0 for both tier and "
            f"score, got {application['priority_score']}"
        )
        _, meta = validate_paginated(
            api.list_accounts(PA, params={"program_year_id": env.program_year_id})
        )
        assert meta["total_count"] == 0, (
            f"no account is opened by an empty run, got {meta['total_count']}"
        )

    def test_empty_run_still_closes_intake_and_refuses_a_replay(self, api):
        """PRD §3.4: "The year must be in `WINDOW_OPEN` when the run starts, or the run
        is refused with `ERR_INVALID_STATE_TRANSITION`."

        PRD §3.4: "Every later submission attempt fails with
        `ERR_APPLICATION_WINDOW_CLOSED`, because the year is no longer `WINDOW_OPEN` —
        independently of whether the logical clock has yet reached `window_close_at`."

        Design: Difficulty/boundary_precision_check/awarding_run_over_an_empty_eligible_set_returns_zero_counts
        """
        env = setup_open_year_and_student()
        _, late = _submitted(env.program_year_id, {
            "household_id": "HH-8",
            "first_name": "Sara",
            "last_name": "Cruz",
            "date_of_birth": "2011-12-01",
        }, "BAND_B", ["DISABILITY_IEP"])
        draft = create_application(env.program_year_id, env.student_id)

        run = validate_success(api.run_awarding(env.program_year_id, PA))
        assert run["awarded_count"] == 0 and run["waitlisted_count"] == 0, (
            "no determination was ever recorded, so the candidate set is empty, got "
            f"{run!r}"
        )

        year = read_program_year(env.program_year_id)
        assert year["status"] == "ACTIVE", (
            f"the year still reaches ACTIVE, got {year['status']!r}"
        )
        assert year["current_quarter"] == 0, (
            f"no disbursement has run yet, got {year['current_quarter']}"
        )
        assert year["seats_available"] == 2, (
            f"the whole seat pool is still available, got {year['seats_available']}"
        )

        late_submit = api.submit_application(draft["id"], env.guardian)
        validate_error(late_submit, ApiErrorId.APPLICATION_WINDOW_CLOSED.value, 409)

        replay = api.run_awarding(env.program_year_id, PA)
        validate_error(replay, ApiErrorId.INVALID_STATE_TRANSITION.value, 409)
        assert read_program_year(env.program_year_id)["status"] == "ACTIVE", (
            "the refused replay leaves the year in ACTIVE"
        )
        assert read_application(late["id"])["provisional_award_cents"] == AWARD_BAND_B_IEP, (
            "the earlier submission keeps the provisional figure it was stamped with"
        )
