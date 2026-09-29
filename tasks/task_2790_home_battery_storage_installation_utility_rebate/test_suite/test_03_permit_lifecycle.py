"""
The permit correction loop: one status, two visits, one counter.

A permit re-enters the submitted state from corrections, so the status alone cannot say
whether a permit is on its first or second pass. The round counter is what carries that
history, and it advances on the authority's decision rather than on the resubmission.
"""

from test_helpers import (
    AHJ_HEADERS,
    CLOCK_EPOCH,
    JurisdictionCode,
    PermitStatus,
    assert_stamped_from_clock,
    factories,
    fixtures,
    validate_success,
)


def _submitted_county_permit(api):
    """A design-locked bank whose county permit has been submitted once."""
    project = fixtures.design_locked_project(api)
    return fixtures.submitted_permit(
        api,
        project,
        jurisdiction_code=JurisdictionCode.AHJ_COUNTY,
        plan_set_ref="PS-2790-R0",
    )


class TestPermitCorrectionRoundTrip:
    """Corrections send the permit back and the counter records the round."""

    def test_corrections_return_the_permit_to_submitted_and_count_the_round(self, api):
        """The counter advances on the authority's decision, not on the resubmission.

        Requesting corrections moves the permit out of the submitted state and raises the
        round count to one; the installer's answering resubmission returns it to submitted
        with the revised plan-set reference stored and the counter still at one.

        PRD 3.4: "`REQUEST_CORRECTIONS` moves the permit `SUBMITTED → CORRECTIONS_REQUIRED` and increments `correction_round_count` by one; the counter advances on the review decision, not on the installer's resubmission."
        PRD 3.4: "The same submission action serves the correction loop, moving a permit `CORRECTIONS_REQUIRED → SUBMITTED` with the same optional plan-set replacement."

        Design: Difficulty/non_linear_state_machine/permit_corrections_cycle_returns_to_submitted_then_issues
        """
        project = _submitted_county_permit(api)

        sent_back = validate_success(
            api.review_permit(
                project.permit_id,
                factories.permit_corrections_payload(
                    inspection_findings="Label the disconnect."
                ),
                headers=AHJ_HEADERS,
            )
        )
        assert sent_back["status"] == PermitStatus.CORRECTIONS_REQUIRED
        assert sent_back["correction_round_count"] == 1

        resubmitted = validate_success(
            api.submit_permit(
                project.permit_id,
                factories.permit_resubmission_payload(plan_set_ref="PS-2790-R1"),
                headers=project.installer_headers,
            )
        )
        assert resubmitted["status"] == PermitStatus.SUBMITTED
        assert resubmitted["correction_round_count"] == 1
        assert resubmitted["plan_set_ref"] == "PS-2790-R1"

    def test_the_second_visit_to_submitted_issues_with_one_round_on_record(self, api):
        """After one round trip the issued permit carries exactly one correction round.

        The permit reaches the submitted state twice in a single lifecycle, and the issued
        record distinguishes the second visit from the first by carrying a round count of
        one — neither the zero it opened with nor a second increment from the resubmission.

        PRD 3.4: "On issuance the permit moves `SUBMITTED → ISSUED`, `issued_at` is stamped from the logical clock and `expires_on` takes the supplied value."
        PRD 3.4: "The permit opens in `DRAFT` with `correction_round_count` at zero and with `issued_at`, `expires_on` and `inspection_findings` all unset."

        Design: Difficulty/non_linear_state_machine/permit_corrections_cycle_returns_to_submitted_then_issues
        """
        project = _submitted_county_permit(api)
        validate_success(
            api.review_permit(
                project.permit_id,
                factories.permit_corrections_payload(
                    inspection_findings="Label the disconnect."
                ),
                headers=AHJ_HEADERS,
            )
        )
        validate_success(
            api.submit_permit(
                project.permit_id,
                factories.permit_resubmission_payload(plan_set_ref="PS-2790-R1"),
                headers=project.installer_headers,
            )
        )

        issued = validate_success(
            api.review_permit(
                project.permit_id,
                factories.permit_issue_payload(expires_on="2027-06-30T00:00:00.000Z"),
                headers=AHJ_HEADERS,
            )
        )

        assert issued["status"] == PermitStatus.ISSUED
        assert issued["correction_round_count"] == 1
        assert issued["correction_round_count"] != 0
        assert issued["correction_round_count"] != 2
        assert issued["plan_set_ref"] == "PS-2790-R1"
        assert issued["expires_on"] == "2027-06-30T00:00:00.000Z"
        assert_stamped_from_clock(issued, "issued_at", CLOCK_EPOCH)
