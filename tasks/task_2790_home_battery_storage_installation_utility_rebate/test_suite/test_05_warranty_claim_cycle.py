"""
The warranty review loop: one status reached from two different predecessors.

An alert under manufacturer review can arrive there from the installer's first filing or
from a re-filing that answers a request for information. The round counter is what tells
the two apart, and it advances every time the alert enters review.
"""

from test_helpers import (
    WARRANTY_AGENT_HEADERS,
    AlertCode,
    AlertSeverity,
    AlertStatus,
    WarrantyStatus,
    factories,
    fixtures,
    validate_success,
)


def _alert_awaiting_information(api):
    """A warranted bank whose critical alert has been claimed once and sent back."""
    project = fixtures.commissioned_project(api)
    fixtures.register_warranty(api, project)

    alert = validate_success(
        api.create_alert(
            factories.alert_payload(
                project.battery_system_id,
                alert_code=AlertCode.FIRMWARE_UPDATE_FAILED,
                severity=AlertSeverity.CRITICAL,
            ),
            headers=WARRANTY_AGENT_HEADERS,
        ),
        expected_status=201,
    )
    alert_id = alert["id"]
    validate_success(api.acknowledge_alert(alert_id, headers=project.installer_headers))
    filed = validate_success(
        api.file_warranty_claim(
            alert_id,
            factories.file_claim_payload(
                claimed_component="GATEWAY", resolution_notes="Update loop on boot."
            ),
            headers=project.installer_headers,
        )
    )
    sent_back = validate_success(
        api.review_warranty_claim(
            alert_id,
            factories.warranty_claim_info_request_payload(
                resolution_notes="Send the gateway log bundle."
            ),
            headers=WARRANTY_AGENT_HEADERS,
        )
    )
    return project, alert_id, filed, sent_back


class TestWarrantyClaimInformationLoop:
    """Review is reachable twice, and the counter records each entry."""

    def test_the_first_filing_enters_review_and_counts_that_entry(self, api):
        """Filing a claim moves the alert into review and raises the counter to one.

        The alert was acknowledged by the accountable installer and then claimed against an
        active warranty, so it entered review for the first time; the request for information
        moves it out of review again without touching the counter.

        PRD 3.8: "Filing moves the alert `ACKNOWLEDGED → UNDER_REVIEW`, requires the bank's `warranty_status` to be `ACTIVE` — a bank whose warranty is `UNREGISTERED` or `VOID` is rejected with `ERR_WARRANTY_NOT_ACTIVE` — records the `claimed_component` named on the filing, may carry `resolution_notes` giving the reviewer context, and increments `claim_round_count` by one."
        PRD 3.8: "That counter tracks how many times the alert has entered `UNDER_REVIEW`, so it advances on the initial filing and again on every re-filing."

        Design: Difficulty/non_linear_state_machine/warranty_claim_info_request_cycle_increments_only_on_refile
        """
        _, _, filed, sent_back = _alert_awaiting_information(api)

        assert filed["status"] == AlertStatus.UNDER_REVIEW
        assert filed["claim_round_count"] == 1
        assert filed["claimed_component"] == "GATEWAY"
        assert sent_back["status"] == AlertStatus.INFO_REQUESTED
        assert sent_back["claim_round_count"] == 1

    def test_the_refiling_enters_review_a_second_time_before_approval(self, api):
        """The second entry into review raises the counter again and then terminates.

        Answering the information request re-files the claim, which is the alert's second
        entry into review and therefore its second counted round; the manufacturer's approval
        then moves it to a terminal outcome with the claimed component still on record and
        the bank's warranty still active.

        PRD 3.8: "`REQUEST_INFO` moves it `UNDER_REVIEW → INFO_REQUESTED`, from which the installer files again — supplying the requested information, again subject to the bank's warranty being `ACTIVE`, again recording `claimed_component` and again incrementing `claim_round_count` — returning the alert to `UNDER_REVIEW`."
        PRD 3.8: "`APPROVE` moves the alert `UNDER_REVIEW → CLAIM_APPROVED` and `DENY` moves it `UNDER_REVIEW → CLAIM_DENIED`; both are terminal."

        Design: Difficulty/non_linear_state_machine/warranty_claim_info_request_cycle_increments_only_on_refile
        """
        project, alert_id, _, _ = _alert_awaiting_information(api)

        refiled = validate_success(
            api.file_warranty_claim(
                alert_id,
                factories.file_claim_payload(
                    claimed_component="GATEWAY", resolution_notes="Log bundle attached."
                ),
                headers=project.installer_headers,
            )
        )
        assert refiled["status"] == AlertStatus.UNDER_REVIEW
        assert refiled["claim_round_count"] == 2

        approved = validate_success(
            api.review_warranty_claim(
                alert_id,
                factories.warranty_claim_approval_payload(
                    resolution_notes="Gateway replacement authorised."
                ),
                headers=WARRANTY_AGENT_HEADERS,
            )
        )

        assert approved["status"] == AlertStatus.CLAIM_APPROVED
        assert approved["claim_round_count"] == 2
        assert approved["claimed_component"] == "GATEWAY"
        system = fixtures.read_system(api, project)
        assert system["warranty_status"] == WarrantyStatus.ACTIVE
