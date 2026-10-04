"""Difficulty coverage: non-linear state machines (parallel status dimensions
on CoverageEnrollment; the AppealCase review cycle)."""

from test_helpers import (
    APPEALS_OFFICER_USER_ID,
    adjudicate_appeal,
    file_appeal,
    list_premium_determinations,
    respond_to_appeal,
    setup_delinquent_enrollment,
    setup_final_determination,
)


class TestCoverageEnrollmentParallelStatusDimensions:
    """One entity, two axes: the first past-due invoice moves the collection
    dimension to DELINQUENT while the coverage dimension stays ACTIVE."""

    def test_coverage_stays_active_while_collection_turns_delinquent(self, client):
        """PRD section 3.2: "The two dimensions then evolve independently,
        with one coupling: when the enrollment itself reaches a terminal
        state, the collection dimension is forced to `CLOSED`." PRD
        section 3.7: "The first `PAST_DUE` invoice on an enrollment flips its
        collection status from `DIRECT_BILL` to `DELINQUENT`."

        Design: Difficulty/non_linear_state_machine/coverage_enrollment_parallel_status_dimensions
        """
        _beneficiary, enrollment, _invoices = setup_delinquent_enrollment(
            client, past_due_count=1
        )
        assert enrollment["enrollment_status"] == "ACTIVE"
        assert enrollment["collection_status"] == "DELINQUENT"

    def test_first_past_due_invoice_coexists_with_new_issue(self, client):
        """PRD section 3.7: "Any `ISSUED` invoice whose `due_date` is strictly
        before the clock date with a positive `outstanding_cents` becomes
        `PAST_DUE`". PRD section 3.7: "A regular invoice's `due_date` is the
        last day of its `service_month`". PRD section 3.7: "When no
        determination exists, the amount falls back to an IRMAA-free figure:
        the year's base premium from the RateSchedule plus the year's
        late-penalty amount."

        Design: Difficulty/non_linear_state_machine/coverage_enrollment_parallel_status_dimensions
        """
        _beneficiary, enrollment, invoices = setup_delinquent_enrollment(
            client, past_due_count=1
        )
        by_month = {inv["service_month"]: inv for inv in invoices}
        assert set(by_month) >= {"2026-06", "2026-07"}
        june = by_month["2026-06"]
        assert june["status"] == "PAST_DUE"
        assert june["due_date"] == "2026-06-30"
        assert june["amount_cents"] == 18500
        july = by_month["2026-07"]
        assert july["status"] == "ISSUED"
        assert july["due_date"] == "2026-07-31"
        assert enrollment["enrollment_status"] == "ACTIVE"
        assert enrollment["collection_status"] == "DELINQUENT"


class TestAppealMoreInfoReviewCycle:
    """UNDER_REVIEW -> MORE_INFO_REQUESTED -> UNDER_REVIEW -> APPROVED, with
    the approval fanning out a supersede cascade on the determination."""

    def _setup_reviewable_appeal(self, client):
        beneficiary, _enrollment, determination = setup_final_determination(
            client, coverage_year=2027, tax_year=2025, magi_cents=15000000
        )
        assert determination["status"] == "FINAL"
        assert determination["irmaa_tier"] == 2
        assert determination["total_premium_cents"] == 38000
        appeal = file_appeal(client, determination)
        assert appeal["status"] == "UNDER_REVIEW"
        return beneficiary, determination, appeal

    def test_appeal_more_info_cycle_reenters_under_review(self, client):
        """PRD section 3.6: "A `MORE_INFO_REQUESTED` decision suspends the
        case in that state; the `Beneficiary` answers it by responding with a
        free-text `note`, which cycles the case back to `UNDER_REVIEW`". PRD
        section 3.6: "The case's `adjudicated_by_user_id` stays null while the
        appeal is open".

        Design: Difficulty/non_linear_state_machine/appeal_more_info_review_cycle
        """
        _beneficiary, _determination, appeal = self._setup_reviewable_appeal(client)
        more_info = adjudicate_appeal(client, appeal, "MORE_INFO_REQUESTED")
        assert more_info["status"] == "MORE_INFO_REQUESTED"
        assert more_info["adjudicated_by_user_id"] is None

        back = respond_to_appeal(client, more_info, note="award letter attached")
        assert back["status"] == "UNDER_REVIEW"
        assert back["id"] == appeal["id"]

    def test_appeal_approval_supersedes_and_recreates_determination(self, client):
        """PRD section 3.6: "the appealed `FINAL` determination becomes
        `SUPERSEDED`, and a replacement `FINAL` row is created for the same
        beneficiary, coverage year, and part, with the `irmaa_tier` recomputed
        from the appeal's `claimed_magi_cents` against the same coverage
        year's brackets, the `base_premium_cents` and `lep_cents` carried over
        unchanged, and the new row's `created_by_user_id` set to the
        adjudicating officer's id." PRD section 3.5: "The superseded row
        remains discoverable as the older of the two via `created_at`
        ordering."

        Design: Difficulty/non_linear_state_machine/appeal_more_info_review_cycle
        """
        beneficiary, determination, appeal = self._setup_reviewable_appeal(client)
        adjudicate_appeal(client, appeal, "MORE_INFO_REQUESTED")
        respond_to_appeal(client, appeal)
        approved = adjudicate_appeal(client, appeal, "APPROVED")
        assert approved["status"] == "APPROVED"
        assert approved["adjudicated_by_user_id"] == APPEALS_OFFICER_USER_ID

        determinations = list_premium_determinations(client, beneficiary)
        assert len(determinations) == 2
        superseded, replacement = determinations
        assert superseded["id"] == determination["id"], "older row first"
        assert superseded["status"] == "SUPERSEDED"
        assert replacement["status"] == "FINAL"
        assert replacement["irmaa_tier"] == 0, "claimed MAGI 9000000 -> tier 0"
        assert replacement["base_premium_cents"] == 19000
        assert replacement["lep_cents"] == 0
        assert replacement["irmaa_surcharge_cents"] == 0
        assert replacement["total_premium_cents"] == 19000
        assert replacement["created_by_user_id"] == APPEALS_OFFICER_USER_ID
