"""Non-linear state machines: screening fail-reopen cycle, appeal evidence cycle."""

from test_helpers import (
    TEST_USERS,
    set_clock,
    register_driver,
    latest_screening_id,
    begin_screening_review,
    decide_screening,
    onboard_active_driver,
    deactivate_driver,
    submit_appeal,
    submit_evidence,
    request_evidence,
    decide_appeal,
    get_driver,
    make_driver_headers,
    api_client,
    get_success_data,
)


class TestScreeningFailReopenCycle:
    def test_screening_fail_reopen_review_cycle_twice(self, api):
        """PRD §3.1: "Failure is not final: the affected driver may reopen their own
        screening, moving it from `FAILED` back to `IN_REVIEW` and clearing
        `failure_reason` to null, and this fail–reopen loop may repeat without bound."
        PRD §3.1: "A clearing decision moves the screening to `CLEARED`, records the
        logical-clock instant in `decided_at`, and leaves `failure_reason` null."

        Design: Difficulty/non_linear_state_machine/screening_fail_reopen_review_cycle_twice
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])

        begin_screening_review(sc)
        first_fail = decide_screening(sc, "FAILED", failure_reason="MVR check failed")
        assert first_fail["status"] == "FAILED"

        # Reopen lands directly in IN_REVIEW — no new begin-review needed.
        reopened = get_success_data(
            api_client.reopen_screening(sc, make_driver_headers(driver["id"]))
        )
        assert reopened["status"] == "IN_REVIEW"
        assert reopened["failure_reason"] is None

        second_fail = decide_screening(sc, "FAILED", failure_reason="insufficient history")
        assert second_fail["status"] == "FAILED"

        reopened_again = get_success_data(
            api_client.reopen_screening(sc, make_driver_headers(driver["id"]))
        )
        assert reopened_again["status"] == "IN_REVIEW"

        cleared = decide_screening(sc, "CLEARED")
        assert cleared["status"] == "CLEARED"
        assert cleared["failure_reason"] is None

    def test_screening_fail_reopen_loop_is_not_one_shot(self, api):
        """PRD §3.1: "Failure is not final: the affected driver may reopen their own
        screening, moving it from `FAILED` back to `IN_REVIEW` and clearing
        `failure_reason` to null, and this fail–reopen loop may repeat without bound."

        Design: Difficulty/non_linear_state_machine/screening_fail_reopen_review_cycle_twice
        """
        set_clock()
        driver = register_driver()
        sc = latest_screening_id(driver["id"])

        begin_screening_review(sc)
        decide_screening(sc, "FAILED", failure_reason="MVR check failed")
        get_success_data(api_client.reopen_screening(sc, make_driver_headers(driver["id"])))
        decide_screening(sc, "FAILED", failure_reason="insufficient history")
        reopened = get_success_data(
            api_client.reopen_screening(sc, make_driver_headers(driver["id"]))
        )
        # A second reopen must still succeed: the loop repeats without bound.
        assert reopened["status"] == "IN_REVIEW"
        assert reopened["failure_reason"] is None


class TestAppealEvidenceCycle:
    def test_appeal_evidence_request_under_review_cycle(self, api):
        """PRD §3.8: "The driver builds the case by submitting evidence with an
        `evidence_note`, each submission incrementing `evidence_count` and moving the
        appeal from `SUBMITTED` — or from `EVIDENCE_REQUESTED` — to `UNDER_REVIEW`. An
        `AppealsReviewer` may push the appeal back from `UNDER_REVIEW` to
        `EVIDENCE_REQUESTED` with an optional `request_note`, and this
        request-and-resubmit loop may repeat without bound."
        PRD §3.8: "Deciding `UPHELD` terminates the appeal and leaves the driver
        `DEACTIVATED`."

        Design: Difficulty/non_linear_state_machine/appeal_evidence_request_under_review_cycle
        """
        set_clock()
        driver, vehicle, _s = onboard_active_driver()
        deactivate_driver(driver["id"], reason="repeated customer complaints")
        appeal = submit_appeal(driver["id"], reason="complaints were fabricated")

        s1 = submit_evidence(appeal["id"], driver["id"], note="dashcam footage link")
        assert s1["status"] == "UNDER_REVIEW"
        assert s1["evidence_count"] == 1

        s2 = request_evidence(appeal["id"], note="need GPS logs")
        assert s2["status"] == "EVIDENCE_REQUESTED"

        s3 = submit_evidence(appeal["id"], driver["id"], note="GPS logs attached")
        assert s3["status"] == "UNDER_REVIEW"
        assert s3["evidence_count"] == 2

        s4 = request_evidence(appeal["id"], note="need station statement")
        assert s4["status"] == "EVIDENCE_REQUESTED"

        s5 = submit_evidence(appeal["id"], driver["id"], note="station statement attached")
        assert s5["status"] == "UNDER_REVIEW"
        assert s5["evidence_count"] == 3

        s6 = decide_appeal(appeal["id"], "UPHELD", reason="evidence insufficient")
        assert s6["status"] == "UPHELD"

        profile = get_driver(driver["id"])
        assert profile["status"] == "DEACTIVATED"

    def test_appeal_evidence_loop_progresses_counts(self, api):
        """PRD §3.8: "The driver builds the case by submitting evidence with an
        `evidence_note`, each submission incrementing `evidence_count` and moving the
        appeal from `SUBMITTED` — or from `EVIDENCE_REQUESTED` — to `UNDER_REVIEW`."

        Design: Difficulty/non_linear_state_machine/appeal_evidence_request_under_review_cycle
        """
        set_clock()
        driver, vehicle, _s = onboard_active_driver()
        deactivate_driver(driver["id"], reason="repeated customer complaints")
        appeal = submit_appeal(driver["id"], reason="complaints were fabricated")
        assert appeal["status"] == "SUBMITTED"
        assert appeal["evidence_count"] == 0

        a1 = submit_evidence(appeal["id"], driver["id"], note="dashcam footage link")
        request_evidence(appeal["id"], note="need GPS logs")
        a2 = submit_evidence(appeal["id"], driver["id"], note="GPS logs attached")

        assert a1["evidence_count"] == 1
        assert a2["evidence_count"] == 2
        assert a2["status"] == "UNDER_REVIEW"
