"""Difficulty coverage: transitive cascades (employer-coverage end fan-out;
the depth-4 equitable-relief grant chain)."""

from test_helpers import (
    FIELD_OFFICER_USER_ID,
    adjudicate_relief_case,
    assert_money_conservation,
    end_employer_coverage,
    list_enrollment_periods,
    list_invoices,
    list_payer_coordination,
    list_penalties,
    list_premium_determinations,
    read_beneficiary,
    read_enrollment,
    set_clock,
    setup_relief_case_on_paid_pair,
    setup_verified_employer_coverage,
)


class TestEmployerCoverageEndCascade:
    """Ending a verified record: the record itself moves to ENDED, an SEP
    window row appears, and the payer role flips back prospectively."""

    def _end_acme_coverage(self, client):
        beneficiary, record = setup_verified_employer_coverage(
            client,
            employer_size=50,
            employer_name="ACME",
            coverage_start_month="2024-01",
            date_of_birth="1961-03-10",
            created_at="2026-01-05T00:00:00Z",
        )
        set_clock(client, "2026-09-05T00:00:00Z")
        ended = end_employer_coverage(client, record["id"], "2026-08", "2026-09")
        return beneficiary, record, ended

    def test_employer_coverage_end_opens_sep_window(self, client):
        """PRD section 3.3: "The SEP anchors on whichever ended FIRST — the
        earlier of `employment_end_month` and `coverage_end_month` — and runs
        for eight months: from the month after the anchor through the eighth
        month after it, inclusive. The system persists this as an
        EnrollmentPeriod row with `window_type` `SEP`, its bounds set to that
        range, its `status` derived from the clock, and its
        `source_coverage_ref` carrying the id of the EmployerCoverageRecord
        whose ending opened the window."

        Design: Difficulty/transitive_cascade/employer_coverage_end_cascade
        """
        beneficiary, record, ended = self._end_acme_coverage(client)
        assert ended["record_status"] == "ENDED"
        assert ended["coverage_end_month"] == "2026-08"
        assert ended["employment_end_month"] == "2026-09"

        periods = list_enrollment_periods(client, beneficiary)
        assert periods[0]["window_type"] == "IEP"
        sep = periods[1]
        assert sep["window_type"] == "SEP"
        # anchor = min(employment end 2026-09, coverage end 2026-08) = 2026-08
        assert sep["window_start_month"] == "2026-09"
        assert sep["window_end_month"] == "2027-04"
        assert sep["status"] == "OPEN", "clock month 2026-09 is inside the SEP"
        assert sep["source_coverage_ref"] == record["id"]

    def test_employer_coverage_end_flips_payer_role_prospectively(self, client):
        """PRD section 3.3: "the open `MEDICARE_SECONDARY` interval closes at
        `coverage_end_month`, and a `MEDICARE_PRIMARY` interval with `basis`
        `NO_EMPLOYER_COVERAGE` opens at the month after `coverage_end_month`."
        PRD section 3.3: "Verification is retroactive: verifying a
        large-employer record opens the `MEDICARE_SECONDARY` interval starting
        at the record's `coverage_start_month`, not at the verification date."

        Design: Difficulty/transitive_cascade/employer_coverage_end_cascade
        """
        beneficiary, _record, _ended = self._end_acme_coverage(client)
        rows = list_payer_coordination(client, beneficiary)
        assert len(rows) == 2
        secondary, primary = rows
        assert secondary["role"] == "MEDICARE_SECONDARY"
        assert secondary["basis"] == "LARGE_EMPLOYER"
        assert secondary["effective_start_month"] == "2024-01"
        assert secondary["effective_end_month"] == "2026-08"
        assert primary["role"] == "MEDICARE_PRIMARY"
        assert primary["basis"] == "NO_EMPLOYER_COVERAGE"
        assert primary["effective_start_month"] == "2026-09"
        assert primary["effective_end_month"] is None


class TestReliefGrantDepth4Cascade:
    """GRANTED relief on a paid, penalized enrollment: enrollment moves
    earlier (1), the penalty voids (2), the determination supersedes (3), and
    the paid invoices reprice with credit (4)."""

    def _grant_paid_pair_relief(self, client):
        state = setup_relief_case_on_paid_pair(client)
        adjudicate_relief_case(client, state["relief_case"], decision="GRANTED")
        return state

    def test_relief_grant_moves_enrollment_earlier_and_voids_penalty(self, client):
        """PRD section 3.9: "The enrollment's `effective_month` then moves
        back to the requested month." PRD section 3.4: "A grant whose
        recomputed gap falls below the penalty threshold — fewer than twelve
        months for `PART_B`, or zero months for `PART_D` — moves the
        assessment to `VOIDED`, recording that the penalty should never have
        applied."

        Design: Difficulty/transitive_cascade/relief_grant_depth4_cascade
        """
        state = self._grant_paid_pair_relief(client)
        enrollment = read_enrollment(client, state["enrollment"]["id"])
        assert enrollment["effective_month"] == "2026-06"
        assert enrollment["enrollment_status"] == "ACTIVE"

        # Recomputed gap [2025-10 .. 2026-05] = 8 months -> zero full periods.
        penalties = list_penalties(client, state["beneficiary"])
        assert len(penalties) == 1
        assert penalties[0]["status"] == "VOIDED"

    def test_relief_grant_supersedes_determination_and_reprices_paid_invoices(
        self, client
    ):
        """PRD section 3.9: "Every non-`SUPERSEDED` PremiumDetermination for
        the beneficiary and part moves to `SUPERSEDED`, and a replacement
        `FINAL` row is created for each, keeping the same coverage year, part,
        and tax basis, recomputing `lep_cents` against the corrected penalty
        position, and stamping the replacement's `created_by_user_id` with the
        adjudicating officer's id." PRD section 3.9: "invoices already `PAID`
        keep their `paid_cents`, have their `applied_cents` reduced to the
        corrected amount, and the difference between what was paid and what
        now applies is credited to the beneficiary's `credit_cents`."

        Design: Difficulty/transitive_cascade/relief_grant_depth4_cascade
        """
        state = self._grant_paid_pair_relief(client)
        beneficiary = read_beneficiary(client, state["beneficiary"]["id"])

        determinations = list_premium_determinations(client, beneficiary)
        assert len(determinations) == 2
        superseded, replacement = determinations
        assert superseded["id"] == state["determination"]["id"]
        assert superseded["status"] == "SUPERSEDED"
        assert replacement["status"] == "FINAL"
        assert replacement["lep_cents"] == 0
        assert replacement["total_premium_cents"] == 19000
        assert replacement["created_by_user_id"] == FIELD_OFFICER_USER_ID

        invoices = list_invoices(client, beneficiary)
        assert len(invoices) == 2
        for invoice in invoices:
            assert invoice["status"] == "PAID"
            assert invoice["paid_cents"] == 20900
            assert invoice["applied_cents"] == 19000
        assert beneficiary["credit_cents"] == 3800
        assert_money_conservation(beneficiary, invoices)
