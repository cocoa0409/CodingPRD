"""Earnings corrections: review cycles, terminal states, statute bar, duplicate
constraint, and the batch expiry sweep."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_correction_request,
    create_worker,
    earnings_year_row,
    file_correction,
    make_claimant_headers,
    make_claims_specialist_headers,
    make_senior_adjudicator_headers,
    post_wage_report,
    run_batch_at,
    set_clock,
    validate_error,
    validate_success,
)

CS = TEST_USERS["claims_specialist_headers"]


class TestCorrectionReviewCycles:
    def test_evidence_request_loop_returns_to_pending_review(self, api):
        """PRD §3.2: "A `ClaimsSpecialist` may move a `PENDING_REVIEW` request to
        `EVIDENCE_REQUESTED`, optionally attaching an `evidence_note` describing
        what is needed; the requester — or a specialist on their behalf — answers
        with `evidence_detail`, returning the request to `PENDING_REVIEW`. This
        cycle may bounce between the two states any number of times before the
        deadline."

        Design: Difficulty/non_linear_state_machine/correction_evidence_and_reopen_cycles
        """
        worker = create_worker(full_name="Correction Worker")
        post_wage_report(worker["id"], 2023, 1_000_000)
        correction = file_correction(worker["id"], 2023, 1_925_000, "WAGE_STATEMENT")
        assert_correction_request(correction)
        assert correction["status"] == "PENDING_REVIEW"
        assert correction["statute_deadline"] == "2027-04-15"

        asked = validate_success(api.request_evidence(correction["id"], CS))
        assert asked["status"] == "EVIDENCE_REQUESTED"
        assert asked["version"] == correction["version"] + 1

        back = validate_success(
            api.submit_evidence(
                correction["id"], {"evidence_detail": "W-2 copy attached"},
                make_claimant_headers(worker["id"]),
            )
        )
        assert back["status"] == "PENDING_REVIEW"
        assert back["version"] == asked["version"] + 1

    def test_denial_reopen_cycle_then_approve_applies_earnings(self, api):
        """PRD §3.2: "a `SeniorAdjudicator` may reopen within sixty days of
        `decided_at` — later attempts are rejected with `ERR_REOPEN_WINDOW_EXPIRED`
        (422) — provided the adjudicator is not the operator recorded in
        `decided_by` (`ERR_SAME_ADJUDICATOR`, 409, per §2.9) and the statute has
        not run (`ERR_CORRECTION_TIME_BARRED`). Reopening returns the request to
        `PENDING_REVIEW`, clears `denial_reason`, `decided_by`, and `decided_at`,
        and records the caller's `reopen_reason`."
        PRD §3.2: "First, the earnings row for that worker and year is upserted:
        `posted_earnings_cents` becomes the claimed amount and `corrected` becomes
        true."

        Design: Difficulty/non_linear_state_machine/correction_evidence_and_reopen_cycles
        """
        worker = create_worker(full_name="Cycle Worker")
        post_wage_report(worker["id"], 2023, 1_000_000)
        correction = file_correction(worker["id"], 2023, 1_925_000, "WAGE_STATEMENT")

        denied = validate_success(
            api.deny_correction(
                correction["id"], "insufficient evidence",
                make_claims_specialist_headers("spec-1"),
            )
        )
        assert denied["status"] == "DENIED"
        assert denied["decided_by"] == "spec-1"
        assert denied["denial_reason"] == "insufficient evidence"

        reopened = validate_success(
            api.reopen_correction(
                correction["id"], "certified copy obtained",
                make_senior_adjudicator_headers("sen-9"),
            )
        )
        assert reopened["status"] == "PENDING_REVIEW"
        assert reopened["denial_reason"] is None
        assert reopened["decided_by"] is None
        assert reopened["decided_at"] is None

        approved = validate_success(api.approve_correction(correction["id"], CS))
        assert approved["status"] == "APPROVED"

        row = earnings_year_row(worker["id"], 2023)
        assert row["posted_earnings_cents"] == 1_925_000
        assert row["corrected"] is True


class TestCorrectionGuards:
    def test_correction_approve_twice_returns_invalid_state(self, api):
        """PRD §3.2: "`APPROVED` and `EXPIRED` are terminal."
        PRD §2.9: "**State-machine legality**: the target entity is in a
        from-state of the invoked transition, and terminal entities reject all
        further actions — otherwise `ERR_INVALID_STATE` (409), or
        `ERR_CLAIM_ALREADY_TERMINAL` (409) when the target claim is
        `WITHDRAWN` or `TERMINATED`."

        Design: Corner/state_machines/correction_approve_twice_returns_invalid_state
        """
        worker = create_worker(full_name="Correction Twice")
        post_wage_report(worker["id"], 2023, 1_000_000)
        correction = file_correction(worker["id"], 2023, 1_500_000, "WAGE_STATEMENT")
        validate_success(api.approve_correction(correction["id"], CS))

        resp = api.approve_correction(correction["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)

        row = earnings_year_row(worker["id"], 2023)
        assert row["posted_earnings_cents"] == 1_500_000, "no double application"

    def test_correction_time_barred_at_default_clock_rejected(self, api):
        """PRD §3.2: "And the statute binds from the first moment: a filing made
        when the logical clock is already past the `statute_deadline` is rejected
        with `ERR_CORRECTION_TIME_BARRED` (422)."
        PRD §2.4: "Before any call has set it, the logical clock starts at exactly
        2026-09-01T00:00:00Z and never falls back to wall-clock time."

        The 2022 deadline is (2022+4)-04-15 = 2026-04-15, already past at the
        default clock.

        Design: Corner/validations/correction_time_barred_at_default_clock_rejected
        """
        worker = create_worker(full_name="Time Barred")

        resp = api.create_correction_request(
            {
                "worker_id": worker["id"],
                "tax_year": 2022,
                "claimed_earnings_cents": 500_000,
                "evidence_type": "WAGE_STATEMENT",
            },
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CORRECTION_TIME_BARRED, 422)

        rows = validate_success(api.list_worker_correction_requests(worker["id"], CS))
        assert rows == [], "no correction may be persisted"

    def test_correction_without_discrepancy_rejected(self, api):
        """PRD §3.2: "The request must allege a real discrepancy: if
        `claimed_earnings_cents` equals the currently posted amount for that year —
        a missing ledger row counting as zero — the filing is rejected with
        `ERR_NO_EARNINGS_DISCREPANCY` (422)."

        Design: Corner/validations/correction_without_discrepancy_rejected
        """
        worker = create_worker(full_name="No Diff")
        post_wage_report(worker["id"], 2023, 1_000_000)

        resp = api.create_correction_request(
            {
                "worker_id": worker["id"],
                "tax_year": 2023,
                "claimed_earnings_cents": 1_000_000,
                "evidence_type": "WAGE_STATEMENT",
            },
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_EARNINGS_DISCREPANCY, 422)

    def test_batch_sweeps_time_barred_corrections(self, api):
        """PRD §3.7: "Fourth, the **correction sweep**: every correction request
        still in `PENDING_REVIEW`, `EVIDENCE_REQUESTED`, or `DENIED` whose statute
        deadline lies before the logical clock date moves to `EXPIRED`."
        PRD §3.7: "The run report carries the fields `run_month`,
        `payments_created`, `corrections_expired`, `claims_auto_resumed`,
        `overpayments_recovered` (cases that reached `RECOVERED` during the run),
        `cola_applied`, and `already_run`."

        Design: Corner/state_machines/batch_sweeps_time_barred_corrections
        """
        worker = create_worker(full_name="Expiring Worker")
        set_clock("2026-03-01T00:00:00Z")
        correction = file_correction(worker["id"], 2022, 500_000, "OTHER")
        assert correction["statute_deadline"] == "2026-04-15"

        report = run_batch_at("2026-05-01T00:00:00Z", "2026-05")
        assert report["corrections_expired"] == 1

        rows = validate_success(api.list_worker_correction_requests(worker["id"], CS))
        assert rows[0]["status"] == "EXPIRED"

        resp = api.approve_correction(correction["id"], CS)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


class TestDuplicateVersusTimeBar:
    def test_duplicate_constraint_wins_after_deadline(self, api):
        """PRD §3.2: "At most one non-terminal request may exist per worker and
        year: an existing request that is `PENDING_REVIEW`, `EVIDENCE_REQUESTED`,
        or `DENIED` but still inside its reopen window blocks a new one with
        `ERR_DUPLICATE_PENDING_CORRECTION` (409)."
        PRD §2.9: "When several rules could reject the same request, the system
        evaluates them in a fixed order and the **first failure wins** — later
        checks are not consulted once an earlier one has rejected." (uniqueness
        and capacity is layer 9; temporal windows are layer 10.)

        Design: Difficulty/priority_pair_validation_conflict/correction_duplicate_constraint_beats_time_bar
        """
        worker = create_worker(full_name="Dup Worker")
        set_clock("2026-03-01T00:00:00Z")
        first = file_correction(worker["id"], 2022, 500_000, "WAGE_STATEMENT")
        assert first["status"] == "PENDING_REVIEW"

        set_clock("2026-09-01T00:00:00Z")  # past the 2026-04-15 deadline
        resp = api.create_correction_request(
            {
                "worker_id": worker["id"],
                "tax_year": 2022,
                "claimed_earnings_cents": 600_000,
                "evidence_type": "TAX_RETURN",
            },
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PENDING_CORRECTION, 409)

        rows = validate_success(api.list_worker_correction_requests(worker["id"], CS))
        assert len(rows) == 1
        assert rows[0]["id"] == first["id"]
        assert rows[0]["status"] == "PENDING_REVIEW"

    def test_duplicate_constraint_fires_before_deadline(self, api):
        """PRD §3.2: "At most one non-terminal request may exist per worker and
        year: an existing request that is `PENDING_REVIEW`, `EVIDENCE_REQUESTED`,
        or `DENIED` but still inside its reopen window blocks a new one with
        `ERR_DUPLICATE_PENDING_CORRECTION` (409)."

        With the clock inside the statute, the duplicate guard is the only
        applicable rejection.

        Design: Difficulty/priority_pair_validation_conflict/correction_duplicate_constraint_beats_time_bar
        """
        worker = create_worker(full_name="Dup Early")
        set_clock("2026-03-01T00:00:00Z")
        first = file_correction(worker["id"], 2022, 500_000, "WAGE_STATEMENT")

        resp = api.create_correction_request(
            {
                "worker_id": worker["id"],
                "tax_year": 2022,
                "claimed_earnings_cents": 700_000,
                "evidence_type": "TAX_RETURN",
            },
            make_claimant_headers(worker["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_PENDING_CORRECTION, 409)

        rows = validate_success(api.list_worker_correction_requests(worker["id"], CS))
        assert [r["id"] for r in rows] == [first["id"]]
