"""Contesting an application denial: the one genuine cycle and its round cap."""

from test_helpers import (
    APPEAL_ROUND_CAP,
    AWARD_BAND_B_ONLY,
    AO,
    ELIGIBILITY_OFFICER_USER_ID,
    PA,
    ApiErrorId,
    assert_appeal,
    create_application_denial_appeal_payload,
    decide_appeal,
    file_application_denial_appeal,
    make_appeals_officer_headers,
    read_appeal,
    read_application,
    record_determination,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)

DENIED_STUDENT = {
    "household_id": "HH-3",
    "first_name": "Nora",
    "last_name": "Vega",
    "date_of_birth": "2012-09-11",
    "prior_enrollment": "PRIVATE_SCHOOL",
    "income_band": "BAND_B",
    "category_flags": [],
}

FAILED_FINDINGS = {
    "residency_check": "FAIL",
    "verified_prior_enrollment": "PRIVATE_SCHOOL",
    "verified_category_flags": [],
}

CLEAN_FINDINGS = {
    "verified_prior_enrollment": "PRIVATE_SCHOOL",
    "verified_category_flags": [],
}


def _denied_application():
    """A BAND_B application denied on a failed residency check by user eo-1."""
    env = setup_submitted_application(
        student_overrides=DENIED_STUDENT,
        application_overrides={"claimed_category_flags": []},
    )
    env["first_determination"] = record_determination(
        env.application_id, **FAILED_FINDINGS
    )
    env["application"] = read_application(env.application_id)
    return env


class TestDenialAppealCycle:
    """The application re-enters SUBMITTED, a state it had already left."""

    def test_overturned_appeal_returns_the_application_to_the_pipeline(self, api):
        """PRD §3.9: "`APPLICATION_DENIAL` moves the application `UNDER_APPEAL →
        SUBMITTED`, putting it back into the pipeline so that a fresh determination can
        be recorded with an incremented `round_number`. Its `verified_income_band`,
        `verified_category_flags`, `annual_award_cents`, `priority_tier`, and
        `priority_score` are all reset to their defaults — the band back to null, the
        flags back to the empty list, and the three numbers back to 0 — because the
        earlier verification no longer stands."

        PRD §3.3: "The row records `denial_reason_code` by strict first-match order:
        `RESIDENCY` when `residency_check` is `FAIL`; otherwise `PRIOR_ENROLLMENT` when
        `prior_enrollment_check` is `FAIL`; otherwise `INCOME_OR_CATEGORY`."

        Design: Difficulty/non_linear_state_machine/denied_application_cycles_back_to_submitted_on_overturned_appeal
        """
        env = _denied_application()
        assert env.first_determination["outcome"] == "INELIGIBLE", (
            "a failed residency check produces an INELIGIBLE outcome, got "
            f"{env.first_determination['outcome']!r}"
        )
        assert env.first_determination["denial_reason_code"] == "RESIDENCY", (
            "RESIDENCY is the first-match reason when residency_check is FAIL, got "
            f"{env.first_determination['denial_reason_code']!r}"
        )
        denied = env.application
        assert denied["status"] == "DENIED", (
            f"an INELIGIBLE outcome advances SUBMITTED to DENIED, got {denied['status']!r}"
        )
        assert denied["appeal_round_count"] == 0, (
            f"no appeal has been filed yet, got {denied['appeal_round_count']}"
        )

        appeal = file_application_denial_appeal(env.application_id, env.student_id)
        assert_appeal(appeal)
        assert appeal["status"] == "FILED", (
            f"every appeal is created in FILED, got {appeal['status']!r}"
        )
        assert appeal["round_number"] == 1, (
            f"the appeal's round_number is set to the new count, got "
            f"{appeal['round_number']}"
        )
        assert appeal["misuse_case_id"] is None and appeal["provider_id"] is None, (
            "APPLICATION_DENIAL requires application_id and leaves both misuse_case_id "
            f"and provider_id null, got {appeal!r}"
        )
        under_appeal = read_application(env.application_id)
        assert under_appeal["status"] == "UNDER_APPEAL", (
            f"filing moves the application DENIED to UNDER_APPEAL, got "
            f"{under_appeal['status']!r}"
        )
        assert under_appeal["appeal_round_count"] == 1, (
            f"appeal_round_count rises by 1 on the filing, got "
            f"{under_appeal['appeal_round_count']}"
        )

        decided = decide_appeal(
            appeal["id"],
            "OVERTURNED",
            "The residency documentation names the correct Texas address.",
        )
        assert decided["status"] == "OVERTURNED", (
            f"the appeal moves FILED to OVERTURNED, got {decided['status']!r}"
        )

        cycled = read_application(env.application_id)
        assert cycled["status"] == "SUBMITTED", (
            "the application cycles back into a state it had already left, got "
            f"{cycled['status']!r}"
        )
        assert cycled["verified_income_band"] is None, (
            f"the band goes back to null, got {cycled['verified_income_band']!r}"
        )
        assert cycled["verified_category_flags"] == [], (
            f"the flags go back to the empty list, got "
            f"{cycled['verified_category_flags']!r}"
        )
        assert cycled["annual_award_cents"] == 0, (
            f"annual_award_cents goes back to 0, got {cycled['annual_award_cents']}"
        )
        assert cycled["priority_tier"] == 0 and cycled["priority_score"] == 0, (
            f"tier and score go back to 0, got {cycled!r}"
        )
        assert cycled["appeal_round_count"] == 1, (
            "the round count is not reset by the overturn, got "
            f"{cycled['appeal_round_count']}"
        )

        redetermination = record_determination(env.application_id, **CLEAN_FINDINGS)
        assert redetermination["round_number"] == 2, (
            "a fresh determination is recorded with an incremented round_number, got "
            f"{redetermination['round_number']}"
        )
        assert redetermination["outcome"] == "ELIGIBLE", (
            f"both checks now pass on a BAND_B band, got {redetermination['outcome']!r}"
        )

        final = read_application(env.application_id)
        assert final["status"] == "ELIGIBLE", (
            f"the second determination carries it to ELIGIBLE, got {final['status']!r}"
        )
        assert final["annual_award_cents"] == AWARD_BAND_B_ONLY, (
            "with no admitted flags the annual figure equals the base component, which "
            f"is 658350 for BAND_B against the default base, got "
            f"{final['annual_award_cents']}"
        )
        assert final["priority_tier"] == 5 and final["priority_score"] == 60, (
            "no ladder rung matches, so tier 5 with the bare BAND_B income term of 60, "
            f"got tier {final['priority_tier']} score {final['priority_score']}"
        )

        rows, meta = validate_paginated(
            api.list_eligibility_determinations(env.application_id, PA)
        )
        assert meta["total_count"] == 2, (
            "each determination is a new row and no earlier row is ever edited, so two "
            f"rows exist, got {meta['total_count']}"
        )
        assert [row["round_number"] for row in rows] == [1, 2], (
            f"the history is returned oldest round first, got {rows!r}"
        )

    def test_the_cycle_can_be_travelled_a_second_time(self, api):
        """PRD §3.9: "This is the programme's one genuine cycle: an application can
        travel `DENIED → UNDER_APPEAL → SUBMITTED → DENIED` twice before the round cap
        bites."

        PRD §3.9: "On success `appeal_round_count` rises by 1, the appeal's
        `round_number` is set to that new count, and the application's `version` rises by
        1."

        Design: Difficulty/non_linear_state_machine/denied_application_cycles_back_to_submitted_on_overturned_appeal
        """
        env = _denied_application()

        first_appeal = file_application_denial_appeal(env.application_id, env.student_id)
        decide_appeal(
            first_appeal["id"], "OVERTURNED", "The first denial rested on a stale record."
        )
        assert read_application(env.application_id)["status"] == "SUBMITTED", (
            "the first overturn returns the application to SUBMITTED"
        )

        second_denial = record_determination(env.application_id, **FAILED_FINDINGS)
        assert second_denial["round_number"] == 2, (
            f"the re-determination carries round_number 2, got "
            f"{second_denial['round_number']}"
        )
        assert read_application(env.application_id)["status"] == "DENIED", (
            "the second failed determination denies the application again"
        )

        second_appeal = file_application_denial_appeal(env.application_id, env.student_id)
        assert second_appeal["round_number"] == 2, (
            "the appeal's round_number is set to the new count, got "
            f"{second_appeal['round_number']}"
        )
        second_round = read_application(env.application_id)
        assert second_round["status"] == "UNDER_APPEAL", (
            f"the second filing moves it back to UNDER_APPEAL, got "
            f"{second_round['status']!r}"
        )
        assert second_round["appeal_round_count"] == 2, (
            f"appeal_round_count rises by 1 again, got "
            f"{second_round['appeal_round_count']}"
        )

        decide_appeal(
            second_appeal["id"],
            "OVERTURNED",
            "The second denial repeated the same documentation error.",
        )
        cycled_twice = read_application(env.application_id)
        assert cycled_twice["status"] == "SUBMITTED", (
            "the application travels the cycle a second time, got "
            f"{cycled_twice['status']!r}"
        )
        assert cycled_twice["appeal_round_count"] == APPEAL_ROUND_CAP, (
            "two rounds have now been consumed against the cap of 2, got "
            f"{cycled_twice['appeal_round_count']}"
        )
        assert cycled_twice["version"] > second_round["version"], (
            "the subject record's version rises with the appeal decision, got "
            f"{cycled_twice['version']} against {second_round['version']}"
        )

        third_determination = record_determination(env.application_id, **CLEAN_FINDINGS)
        assert third_determination["round_number"] == 3, (
            "each post-appeal re-determination is one round higher, got "
            f"{third_determination['round_number']}"
        )
        assert read_application(env.application_id)["status"] == "ELIGIBLE", (
            "the third determination finally admits the application"
        )


class TestAppealRoundCap:
    """The denial-appeal loop is bounded, not infinite."""

    def test_third_filing_after_two_rounds_is_refused(self, api):
        """PRD §3.9: "and its `appeal_round_count` must be strictly below the
        programme-wide appeal round cap, which is fixed at 2, or the filing is refused
        with `ERR_APPEAL_ROUNDS_EXHAUSTED`."

        Design: Corner/validations/third_application_appeal_is_blocked_by_the_round_limit
        """
        env = _denied_application()

        first_appeal = file_application_denial_appeal(env.application_id, env.student_id)
        decide_appeal(
            first_appeal["id"], "OVERTURNED", "The first denial rested on a stale record."
        )
        record_determination(env.application_id, **FAILED_FINDINGS)
        second_appeal = file_application_denial_appeal(env.application_id, env.student_id)
        decide_appeal(
            second_appeal["id"],
            "OVERTURNED",
            "The second denial repeated the same documentation error.",
        )
        record_determination(env.application_id, **FAILED_FINDINGS)

        before = read_application(env.application_id)
        assert before["status"] == "DENIED", (
            f"the third determination denies the application again, got "
            f"{before['status']!r}"
        )
        assert before["appeal_round_count"] == 2, (
            f"both appeal rounds have been used, got {before['appeal_round_count']}"
        )

        response = api.create_appeal(
            create_application_denial_appeal_payload(env.application_id),
            env.guardian,
        )
        validate_error(response, ApiErrorId.APPEAL_ROUNDS_EXHAUSTED.value, 409)

        after = read_application(env.application_id)
        assert after["appeal_round_count"] == 2, (
            "the refused filing leaves the round count untouched, got "
            f"{after['appeal_round_count']}"
        )
        assert after["status"] == "DENIED", (
            f"the application stays DENIED, got {after['status']!r}"
        )
        rows, meta = validate_paginated(
            api.list_appeals(PA, params={"application_id": env.application_id})
        )
        assert meta["total_count"] == 2, (
            f"only the two decided appeals exist, got {meta['total_count']}"
        )
        assert [row["status"] for row in rows] == ["OVERTURNED", "OVERTURNED"], (
            f"both of them were overturned, got {rows!r}"
        )


class TestAppealSegregationOfDuties:
    """The same operator wearing a second hat is still blocked."""

    def test_determination_author_cannot_decide_the_appeal(self, api):
        """PRD §3.9: "Segregation of duties is subject-specific: on an
        `APPLICATION_DENIAL` appeal the acting `X-User-ID` must differ from the
        `decided_by_user_id` of the latest eligibility determination on that application,
        and on a `CLAWBACK` appeal it must differ from the case's
        `adjudicated_by_user_id`; a match is refused with `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/rbac/denial_author_cannot_decide_the_appeal_they_wrote
        """
        env = _denied_application()
        assert env.first_determination["decided_by_user_id"] == ELIGIBILITY_OFFICER_USER_ID, (
            "the denial was authored by the eligibility officer eo-1, got "
            f"{env.first_determination['decided_by_user_id']!r}"
        )

        appeal = file_application_denial_appeal(env.application_id, env.student_id)

        refused = api.decide_appeal(
            appeal["id"],
            {
                "decision": "OVERTURNED",
                "rationale": "I reviewed my own determination and now disagree with it.",
            },
            make_appeals_officer_headers(ELIGIBILITY_OFFICER_USER_ID),
        )
        validate_error(refused, ApiErrorId.SEGREGATION_OF_DUTIES.value, 403)

        assert read_appeal(appeal["id"])["status"] == "FILED", (
            "the refused decision leaves the appeal in FILED"
        )
        assert read_application(env.application_id)["status"] == "UNDER_APPEAL", (
            "and leaves the application in UNDER_APPEAL"
        )

        allowed = validate_success(
            api.decide_appeal(
                appeal["id"],
                {
                    "decision": "OVERTURNED",
                    "rationale": "The residency documentation names the correct address.",
                },
                AO,
            )
        )
        assert allowed["status"] == "OVERTURNED", (
            "a different operator in the same role decides it, got "
            f"{allowed['status']!r}"
        )
        assert allowed["decided_by_user_id"] == AO["X-User-ID"], (
            f"the deciding operator is recorded, got {allowed['decided_by_user_id']!r}"
        )
        cycled = read_application(env.application_id)
        assert cycled["status"] == "SUBMITTED", (
            f"the overturn cascades onto the application, got {cycled['status']!r}"
        )
        assert cycled["appeal_round_count"] == 1, (
            f"one appeal round has been consumed, got {cycled['appeal_round_count']}"
        )
