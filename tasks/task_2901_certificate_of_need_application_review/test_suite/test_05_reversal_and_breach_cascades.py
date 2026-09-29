"""Transitive cascades: the five-link reversal chain and the three-link breach chain."""

from test_helpers import (
    api_client,
    validate_paginated,
)
from test_helpers.fixtures import (
    ADMIN,
    decide_appeal,
    file_progress_report,
    refresh_applicant,
    refresh_application,
    refresh_certificate,
    refresh_cycle,
    refresh_health_service_area,
    seed_heard_appeal_with_certificate,
    seed_issued_certificate,
)


class TestAppealReversalCascade:
    def test_reversal_denies_the_application_and_revokes_the_certificate(self):
        """Links 1 to 3: appeal, application and certificate all move.

        PRD §3.9: "Link 1 is the appeal's own transition to `REVERSED`."
        PRD §3.9: "Link 2 is the appealed application: an application in
        `APPROVED` or `APPROVED_WITH_CONDITIONS` moves to `DENIED` with
        `denial_reason` set to `APPEAL_REVERSED`, its held beds released — the
        released count is its `allocated_bed_count`, which is then set to 0, and
        the cycle's `unallocated_bed_need` is increased by that released count —
        and its `version` increased by 1; whereas an application in `DENIED`
        moves the other way, to `DEEMED_COMPLETE`, with `denial_reason`,
        `decision_at` and `appeal_window_closes_at` all cleared to null and its
        `version` increased by 1."
        PRD §3.9: "Link 3 is caused by that `DENIED` write: any certificate of
        that application whose `lifecycle_status` is `ISSUED`, `IMPLEMENTED` or
        `SUSPENDED` moves to `REVOKED`, with its `version` increased by 1."

        Design: Difficulty/transitive_cascade/appeal_reversed_depth_five_vacate_cascade
        """
        world = seed_heard_appeal_with_certificate()

        appeal = decide_appeal(world["appeal"], "REVERSED", "Need finding vacated")

        assert appeal["status"] == "REVERSED"
        assert appeal["disposition"] == "REVERSED"
        assert appeal["litigation_hold_active"] is False
        assert appeal["decided_by_user_id"] == "board-1"

        application = refresh_application(world["application"]["id"])
        assert application["status"] == "DENIED"
        assert application["denial_reason"] == "APPEAL_REVERSED"
        assert application["allocated_bed_count"] == 0

        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["lifecycle_status"] == "REVOKED"

    def test_reversal_debits_the_ledgers_and_reopens_the_cycle(self):
        """Links 4 and 5: the planning-area books unwind and the batch reopens.

        PRD §3.9: "Link 4 is caused by the revocation: the planning area's
        `approved_unimplemented_beds` is debited by the revoked certificate's
        `authorized_bed_count` and its `capital_authorization_committed_cents` is
        debited by that certificate's `approved_expenditure_limit_cents`."
        PRD §3.9: "Link 5 is caused by link 4 restoring the cycle's need pool
        above 0: the batching cycle moves from `DECIDED` back to
        `COMPARATIVE_REVIEW` with its `version` increased by 1, every score sheet
        in that cycle whose `status` is `ACTIVE` becomes `STALE`, and every
        *other* application of the cycle whose `status` is `DENIED` with
        `denial_reason` `INSUFFICIENT_NEED` moves to `DEEMED_COMPLETE` — the
        losers of the original waterfall are put back in contention because the
        beds they lost by are available again."

        Design: Difficulty/transitive_cascade/appeal_reversed_depth_five_vacate_cascade
        """
        world = seed_heard_appeal_with_certificate()

        decide_appeal(world["appeal"], "REVERSED", "Need finding vacated")

        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["approved_unimplemented_beds"] == 0
        assert hsa["capital_authorization_committed_cents"] == 0

        cycle = refresh_cycle(world["cycle"]["id"])
        assert cycle["status"] == "COMPARATIVE_REVIEW"
        assert cycle["unallocated_bed_need"] == 19

    def test_reversal_stales_every_active_sheet_and_clears_the_score(self):
        """Staling the sheets forces a fresh review before a second decision.

        PRD §3.9: "Staling the sheets is what forces the batch to be re-reviewed
        rather than re-decided on the old grades: because only `ACTIVE` sheets
        contribute, an application all of whose sheets have become `STALE` has
        its `score_sheet_count` back at 0 and its `comparative_score` back to
        null, so the reopened cycle cannot be decided again until reviewers file
        fresh sheets and each candidate once more carries at least 2 of them."

        Design: Difficulty/transitive_cascade/appeal_reversed_depth_five_vacate_cascade
        """
        world = seed_heard_appeal_with_certificate()

        decide_appeal(world["appeal"], "REVERSED", "Need finding vacated")

        sheets, _ = validate_paginated(
            api_client.list_score_sheets(world["application"]["id"], ADMIN)
        )
        assert {sheet["status"] for sheet in sheets} == {"STALE"}

        application = refresh_application(world["application"]["id"])
        assert application["score_sheet_count"] == 0
        assert application["comparative_score"] is None


class TestProgressReportBreachCascade:
    def test_breach_suspends_the_certificate_and_strikes_the_applicant(self):
        """One accepted report drives breach, suspension and a strike in turn.

        PRD §3.8: "The money axis is then set from a three-way comparison:
        `expenditure_status` becomes `WITHIN_LIMIT` when the governing figure is
        less than or equal to `approved_expenditure_limit_cents`;
        `OVER_LIMIT_PENDING_AMENDMENT` when it exceeds the limit but is still
        less than or equal to `expenditure_ceiling_cents`; and `LIMIT_BREACHED`
        when it exceeds the ceiling."
        PRD §3.8: "When instead the money axis reaches `LIMIT_BREACHED` and the
        certificate's `lifecycle_status` is `ISSUED` or `IMPLEMENTED`, that
        breached value is itself the cause of a lifecycle suspension:
        `lifecycle_status_before_suspension` is set to whatever the lifecycle
        status currently is, `lifecycle_status` becomes `SUSPENDED`, the
        certificate's `version` increases by 1, and the applicant's
        `compliance_strike_count` increases by 1 — which in turn is what can flip
        that applicant's `standing` to `RESTRICTED` at 2 strikes or `BARRED` at
        4."

        Design: Difficulty/transitive_cascade/progress_report_breach_depth_three_suspension_strike_cascade
        """
        world = seed_issued_certificate(certificate={"expenditure_basis": "ACCRUAL"})

        report = file_progress_report(
            world["certificate"],
            world["applicant"],
            period_end_date="2026-11-30",
            disbursed_cents=600000000,
            obligated_cents=600000000,
            physical_completion_pct=30,
        )

        assert report["status"] == "ACCEPTED"
        certificate = refresh_certificate(world["certificate"]["id"])
        assert certificate["cumulative_expenditure_cash_cents"] == 600000000
        assert certificate["cumulative_expenditure_accrual_cents"] == 1200000000
        assert certificate["expenditure_status"] == "LIMIT_BREACHED"
        assert certificate["lifecycle_status"] == "SUSPENDED"
        assert certificate["lifecycle_status_before_suspension"] == "ISSUED"

    def test_a_single_strike_leaves_standing_good_and_the_ledger_intact(self):
        """One strike is short of the two that restrict, and money stays committed.

        PRD §3.1: "`compliance_strike_count` starts at 0 and counts the
        certificate expenditure-limit breaches and lapses charged to that
        organisation."
        PRD §3.1: "The two fields are linked by a fixed rule: `standing` flips to
        `RESTRICTED` when `compliance_strike_count` reaches 2 and to `BARRED`
        when it reaches 4."
        PRD §3.8: "On the planning area, `approved_unimplemented_beds` is
        increased by the certificate's `authorized_bed_count` and
        `capital_authorization_committed_cents` is increased by its
        `approved_expenditure_limit_cents`."

        Design: Difficulty/transitive_cascade/progress_report_breach_depth_three_suspension_strike_cascade
        """
        world = seed_issued_certificate(certificate={"expenditure_basis": "ACCRUAL"})

        file_progress_report(
            world["certificate"],
            world["applicant"],
            period_end_date="2026-11-30",
            disbursed_cents=600000000,
            obligated_cents=600000000,
            physical_completion_pct=30,
        )

        applicant = refresh_applicant(world["applicant"]["id"])
        assert applicant["compliance_strike_count"] == 1
        assert applicant["standing"] == "GOOD"

        hsa = refresh_health_service_area(world["hsa"]["id"])
        assert hsa["capital_authorization_committed_cents"] == 1000000000
