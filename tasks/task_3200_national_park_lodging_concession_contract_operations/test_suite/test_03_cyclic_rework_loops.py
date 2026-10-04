"""Cyclic loops: filings revise from REJECTED; reports rework from RETURNED.

Neither lifecycle is a linear pipeline - a rejected filing is superseded by a
fresh revision carrying ``revision_of_id`` (PRD 3.2), and a returned report
re-enters SUBMITTED with a re-supplied amount (PRD 3.5).
"""

from test_helpers import constants as C
from test_helpers import factories as f
from test_helpers.assertions import (
    assert_cents,
    get_success_data,
)
from test_helpers.fixtures import (
    accept_report,
    active_contract,
    add_room_class,
    add_study,
    approve_filing,
    contract_version,
    create_report,
    reset_clock,
    submit_filing,
    submit_report,
)
from test_helpers.test_users import (
    ACCOUNTANT_2,
    AUDITOR,
    AUDITOR_2,
    RATE_ANALYST,
    RATE_MANAGER_2,
)


class TestFilingRevisionCycle:
    """REJECTED -> revision SUBMITTED -> APPROVED, repeatably."""

    def _setup(self, client):
        """ACTIVE contract, season, room class, 25000-mean study (cap 26250)."""
        reset_clock(client)
        contract, season, _lines = active_contract(client)
        contract_id = contract["id"]
        room_class = add_room_class(client, contract_id)
        study = add_study(client, contract_id, title="S1")
        return contract_id, season["id"], room_class["id"], study["id"]

    def test_revision_of_a_rejected_filing_is_a_fresh_submission(self, client):
        """PRD 3.2: "The revision is created fresh in `SUBMITTED` status,
        while the rejected filing remains `REJECTED` — the loop from
        rejection back to submission is cyclic and may repeat."

        Design: Difficulty/non_linear_state_machine/rate_filing_rejection_revision_cycle
        """
        contract_id, season_id, room_class_id, study_id = self._setup(client)
        over = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
            submitted_rates=f.band_rates_payload(family=27000),
        )
        response = client.start_review_filing(
            contract_id, over["id"], headers=RATE_ANALYST
        )
        assert get_success_data(response)["status"] == C.FILING_UNDER_REVIEW
        rejected = get_success_data(client.reject_filing(
            contract_id, over["id"], {"reason": "FAMILY band over comparability cap"},
            headers=RATE_ANALYST,
        ))
        assert rejected["status"] == C.FILING_REJECTED

        revision = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
            submitted_rates=f.band_rates_payload(family=26250),
            revision_of_id=over["id"],
        )
        assert revision["status"] == C.FILING_SUBMITTED
        assert revision["revision_of_id"] == over["id"]
        reread = get_success_data(client.get_filing(
            contract_id, over["id"], headers=RATE_ANALYST
        ))
        assert reread["status"] == C.FILING_REJECTED, (
            "the rejected filing must remain REJECTED; the cycle continues "
            "through the NEW filing"
        )

    def test_the_revision_can_be_approved_at_the_cap_boundary(self, client):
        """PRD 3.2: "Approval freezes the filing's economics. The filing's
        `effective_date` is set to the season's `open_date`, and its
        `approved_weighted_mean_cents` is pinned to the study's
        `weighted_mean_cents` as of the approval moment."

        Design: Difficulty/non_linear_state_machine/rate_filing_rejection_revision_cycle
        """
        contract_id, season_id, room_class_id, study_id = self._setup(client)
        over = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
            submitted_rates=f.band_rates_payload(family=27000),
        )
        client.start_review_filing(contract_id, over["id"], headers=RATE_ANALYST)
        client.reject_filing(
            contract_id, over["id"], {"reason": "over cap"}, headers=RATE_ANALYST
        )
        revision = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
            submitted_rates=f.band_rates_payload(family=26250),
            revision_of_id=over["id"],
        )
        approved = approve_filing(client, contract_id, revision["id"])
        assert approved["status"] == C.FILING_APPROVED
        assert_cents(
            approved["approved_weighted_mean_cents"], 25000,
            "approved_weighted_mean_cents",
        )

    def test_the_loop_iterates_a_third_time_without_a_counter(self, client):
        """PRD 3.2: "A `ConcessionerRateManager` may submit a revision by
        creating a new filing whose `revision_of_id` references a `REJECTED`
        filing of the same contract and which covers the same season and room
        class as the rejected filing."

        Design: Corner/state_machines/cyclic_filing_can_loop_reject_revise_multiple_times
        """
        contract_id, season_id, room_class_id, study_id = self._setup(client)
        first = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
        )
        client.start_review_filing(contract_id, first["id"], headers=RATE_ANALYST)
        client.reject_filing(
            contract_id, first["id"], {"reason": "over cap"}, headers=RATE_ANALYST
        )
        second = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
            submitted_rates=f.band_rates_payload(family=26300),
            revision_of_id=first["id"],
        )
        client.start_review_filing(contract_id, second["id"], headers=RATE_ANALYST)
        client.reject_filing(
            contract_id, second["id"], {"reason": "still over cap (26300 > 26250)"},
            headers=RATE_ANALYST,
        )
        third = submit_filing(
            client, contract_id, season_id, room_class_id, study_id,
            submitted_rates=f.band_rates_payload(family=26250),
            revision_of_id=second["id"],
        )
        assert third["status"] == C.FILING_SUBMITTED
        assert third["revision_of_id"] == second["id"]
        assert get_success_data(client.get_filing(
            contract_id, first["id"], headers=RATE_ANALYST
        ))["status"] == C.FILING_REJECTED
        assert get_success_data(client.get_filing(
            contract_id, second["id"], headers=RATE_ANALYST
        ))["status"] == C.FILING_REJECTED


class TestReportReworkCycle:
    """DRAFT -> SUBMITTED -> RETURNED -> SUBMITTED -> ACCEPTED."""

    def _setup(self, client):
        reset_clock(client)
        contract, _season, lines = active_contract(client)
        contract_id = contract["id"]
        report = create_report(
            client, contract_id, lines[C.LINE_LODGING]["id"],
            gross_receipts_cents=20000,
        )
        submit_report(client, contract_id, report["id"])
        return contract_id, report

    def test_a_returned_report_resubmits_with_the_corrected_amount(self, client):
        """PRD 3.5: "A returned report re-enters the loop: the accountant
        resubmits it, re-supplying `gross_receipts_cents` in the resubmission
        body, which moves it back to `SUBMITTED` and records the new
        submitter identity. The rework loop is cyclic and may repeat."

        Design: Difficulty/non_linear_state_machine/gross_receipts_report_submit_return_resubmit_cycle
        """
        contract_id, report = self._setup(client)
        returned = get_success_data(client.return_report(
            contract_id, report["id"], {"reason": "Receipts understate POS export"},
            headers=AUDITOR,
        ))
        assert returned["status"] == C.REPORT_RETURNED
        resubmitted = submit_report(
            client, contract_id, report["id"], gross_receipts_cents=25000
        )
        assert resubmitted["status"] == C.REPORT_SUBMITTED
        assert_cents(resubmitted["gross_receipts_cents"], 25000,
                     "resubmitted gross_receipts_cents")

    def test_the_reworked_report_can_still_be_accepted(self, client):
        """PRD 3.5: "The `AgencyFinancialAuditor` may then accept the report
        or return it for rework with a `reason`; acceptance moves it to
        `ACCEPTED`, return moves it to `RETURNED`."

        Design: Difficulty/non_linear_state_machine/gross_receipts_report_submit_return_resubmit_cycle
        """
        contract_id, report = self._setup(client)
        client.return_report(
            contract_id, report["id"], {"reason": "rework"}, headers=AUDITOR
        )
        submit_report(
            client, contract_id, report["id"], submitter=ACCOUNTANT_2,
            gross_receipts_cents=25000,
        )
        accepted = accept_report(client, contract_id, report["id"], acceptor=AUDITOR_2)
        assert accepted["status"] == C.REPORT_ACCEPTED
