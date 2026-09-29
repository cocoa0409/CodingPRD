"""Continued eligibility: the evidence bar, the seat competition and the version guard."""

from test_helpers import (
    EO,
    PA,
    ApiErrorId,
    accept_award,
    application_version,
    create_application,
    create_next_program_year,
    create_renewal_decision_payload,
    create_renewal_review_payload,
    create_student,
    decide_renewal_review,
    file_renewal_review,
    make_guardian_headers,
    open_window,
    read_account,
    read_application,
    read_program_year,
    read_renewal_review,
    record_determination,
    run_awarding,
    setup_open_year_and_student,
    setup_renewal_review,
    setup_submitted_application,
    submit_application,
    validate_error,
    validate_paginated,
    validate_success,
)

SECOND_STUDENT = {
    "household_id": "HH-6",
    "first_name": "Mateo",
    "last_name": "Cardenas",
    "date_of_birth": "2013-09-19",
    "category_flags": ["DISABILITY_IEP"],
}


class TestRenewalEvidenceBar:
    """Approval is conditional on the evidence the declared route requires."""

    def test_a_score_below_the_target_years_bar_refuses_the_approval(self, api):
        """PRD §3.9: "The evidence must clear the bar set by the **target** year: with
        `assessment_type` `NORM_REFERENCED_TEST` the `assessment_score` must be at least the
        target year's `min_assessment_percentile`, and with `PORTFOLIO` the
        `portfolio_artifact_count` must be at least the target year's
        `min_portfolio_artifacts`; a shortfall, or the absence of the evidence field the
        declared route requires, is refused with `ERR_ASSESSMENT_EVIDENCE_INSUFFICIENT`."

        PRD §3.9: "The review records the new application's identifier as
        `renewed_application_id`, which is null on any review that is not `APPROVED`."

        Design: Corner/endpoints/renewal_decision_without_sufficient_evidence_is_refused
        """
        env = setup_renewal_review(review_overrides={"assessment_score": 35})
        target = read_program_year(env.next_program_year_id)
        assert target["min_assessment_percentile"] == 40, (
            f"the target year sets the bar at 40, got "
            f"{target['min_assessment_percentile']}"
        )
        assert env.renewal_review["assessment_score"] == 35, (
            f"and the family declared 35, got {env.renewal_review['assessment_score']}"
        )
        assert env.renewal_review["status"] == "SUBMITTED", (
            f"the review awaits a decision, got {env.renewal_review['status']!r}"
        )

        refused = api.decide_renewal_review(
            env.renewal_review_id, create_renewal_decision_payload("APPROVED"), EO
        )
        validate_error(
            refused, ApiErrorId.ASSESSMENT_EVIDENCE_INSUFFICIENT.value, 422
        )

        review = read_renewal_review(env.renewal_review_id)
        assert review["status"] == "SUBMITTED", (
            f"the review is left where it was, got {review['status']!r}"
        )
        assert review["renewed_application_id"] is None, (
            f"and no successor application was minted, got "
            f"{review['renewed_application_id']!r}"
        )
        assert review["decided_by_user_id"] is None, (
            f"nor was a decider recorded, got {review['decided_by_user_id']!r}"
        )

        after = read_program_year(env.next_program_year_id)
        assert after["seats_committed"] == 0, (
            f"no seat in the target year was consumed, got {after['seats_committed']}"
        )
        assert after["seats_available"] == after["total_seats"], (
            f"so every seat is still free, got {after['seats_available']}"
        )
        _, meta = validate_paginated(
            api.list_applications(
                PA, params={"program_year_id": env.next_program_year_id}
            )
        )
        assert meta["total_count"] == 0, (
            f"and the target year holds no applications at all, got "
            f"{meta['total_count']}"
        )

        assert read_account(env.account_id)["status"] == "ACTIVE", (
            "the current-year account is untouched"
        )
        assert read_application(env.application_id)["status"] == "ACCEPTED", (
            "as is the application behind it"
        )


class TestRenewalSeatCompetition:
    """Renewals consume the target year's seats like any other award."""

    def test_a_renewal_into_a_full_year_is_refused_for_want_of_a_seat(self, api):
        """PRD §3.9: "And the target year must have at least one seat in `seats_available`,
        or it is refused with `ERR_NO_SEATS_AVAILABLE`."

        PRD §3.9: "Because the new application already occupies an offer, the target year's
        `seats_committed` rises by 1 and its `seats_available` falls by 1."

        Design: Corner/errors/renewal_into_a_full_next_year_returns_no_seats_available
        """
        env = setup_open_year_and_student()
        first_application = create_application(env.program_year_id, env.student_id)
        submit_application(first_application["id"], env.student_id)
        record_determination(first_application["id"])

        second_student = create_student(**SECOND_STUDENT)
        second_application = create_application(
            env.program_year_id, second_student["id"]
        )
        submit_application(second_application["id"], second_student["id"])
        record_determination(second_application["id"])

        run_awarding(env.program_year_id)
        first_acceptance = accept_award(first_application["id"], env.student_id)
        second_acceptance = accept_award(second_application["id"], second_student["id"])

        target = create_next_program_year(total_seats=1)
        open_window(target["id"])
        assert read_program_year(target["id"])["seats_available"] == 1, (
            "the successor year offers a single seat"
        )

        first_review = file_renewal_review(
            first_acceptance["account_id"],
            target["id"],
            env.student_id,
            application_version(first_application["id"]),
            assessment_score=55,
        )
        second_review = file_renewal_review(
            second_acceptance["account_id"],
            target["id"],
            second_student["id"],
            application_version(second_application["id"]),
            assessment_score=55,
        )

        first_decision = decide_renewal_review(first_review["id"], "APPROVED")
        assert first_decision["status"] == "APPROVED", (
            f"the first renewal takes the seat, got {first_decision['status']!r}"
        )
        assert first_decision["renewed_application_id"] is not None, (
            f"minting a successor application, got "
            f"{first_decision['renewed_application_id']!r}"
        )
        filled = read_program_year(target["id"])
        assert filled["seats_committed"] == 1, (
            f"the year is now fully committed, got {filled['seats_committed']}"
        )
        assert filled["seats_available"] == 0, (
            f"with no seat left, got {filled['seats_available']}"
        )

        refused = api.decide_renewal_review(
            second_review["id"], create_renewal_decision_payload("APPROVED"), EO
        )
        error = validate_error(refused, ApiErrorId.NO_SEATS_AVAILABLE.value, 409)
        assert error["error_id"] != ApiErrorId.ASSESSMENT_EVIDENCE_INSUFFICIENT.value, (
            "the evidence of 55 clears the bar of 40, so the seat check is what fires, "
            f"got {error['error_id']!r}"
        )

        review = read_renewal_review(second_review["id"])
        assert review["status"] == "SUBMITTED", (
            f"the losing review stays reviewable, got {review['status']!r}"
        )
        assert review["renewed_application_id"] is None, (
            f"and mints nothing, got {review['renewed_application_id']!r}"
        )

        after = read_program_year(target["id"])
        assert after["seats_committed"] == 1, (
            f"the seat count is untouched by the refusal, got "
            f"{after['seats_committed']}"
        )
        assert after["seats_available"] == 0, (
            f"and no seat was conjured, got {after['seats_available']}"
        )
        rows, meta = validate_paginated(
            api.list_applications(PA, params={"program_year_id": target["id"]})
        )
        assert meta["total_count"] == 1, (
            f"exactly one successor application exists, got {meta['total_count']}"
        )
        assert rows[0]["id"] == first_decision["renewed_application_id"], (
            f"and it is the one the winning renewal minted, got {rows[0]!r}"
        )


class TestRenewalVersionGuard:
    """The renewal filing is guarded on the application, not on the account."""

    def test_a_stale_application_version_is_refused_and_the_fresh_one_files(self, api):
        """PRD §2.7: "The second is filing a renewal review. That request must carry
        `expected_application_version`, a non-optional integer field holding the `version` of
        the `Application` behind the named account as the client last observed it. A mismatch
        against that application's current `version` is rejected with
        `ERR_STALE_APPLICATION_VERSION` and HTTP status 412."

        PRD §2.7: "What the guard stops is a filing built on a stale view of the
        application, whose verified attributes drive the renewed award. A successful filing
        itself advances that application's `version` by 1."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_application_version_on_renewal_review_is_rejected
        """
        env = setup_submitted_application()
        stale_version = application_version(env.application_id)

        record_determination(env.application_id)
        run_awarding(env.program_year_id)
        acceptance = accept_award(env.application_id, env.student_id)
        account_id = acceptance["account_id"]

        target = create_next_program_year()
        open_window(target["id"])

        fresh_version = application_version(env.application_id)
        assert fresh_version > stale_version, (
            "the determination, the awarding run and the acceptance have all written the "
            f"application since the read, got {fresh_version} against {stale_version}"
        )
        account = read_account(account_id)
        assert account["status"] == "ACTIVE", (
            f"yet the account itself is in a perfectly ordinary state, got "
            f"{account['status']!r}"
        )

        guardian = make_guardian_headers(env.student_id)
        refused = api.create_renewal_review(
            create_renewal_review_payload(account_id, target["id"], stale_version),
            guardian,
        )
        validate_error(refused, ApiErrorId.STALE_APPLICATION_VERSION.value, 412)

        _, meta = validate_paginated(
            api.list_renewal_reviews(PA, params={"account_id": account_id})
        )
        assert meta["total_count"] == 0, (
            f"the refused filing created no review, got {meta['total_count']}"
        )

        accepted = validate_success(
            api.create_renewal_review(
                create_renewal_review_payload(account_id, target["id"], fresh_version),
                guardian,
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED", (
            f"the retry against the current version files cleanly, got "
            f"{accepted['status']!r}"
        )
        assert accepted["account_id"] == account_id, (
            f"naming the account under renewal, got {accepted['account_id']!r}"
        )
        assert accepted["next_program_year_id"] == target["id"], (
            f"and the year it would fund, got {accepted['next_program_year_id']!r}"
        )

        application = read_application(env.application_id)
        assert application["status"] == "ACCEPTED", (
            f"the application is still the accepted award, got {application['status']!r}"
        )
        assert application["version"] == fresh_version + 1, (
            "and the successful filing advanced its version by 1, got "
            f"{application['version']}"
        )
        assert read_account(account_id)["status"] == "ACTIVE", (
            "while the account never moved at all"
        )
