"""Lifecycle rules: invalid transitions, preconditions, cascades, routing.

Approving an unassigned predetermination, paying a pended claim,
withdrawing an approved quote, and terminating busy providers or
subscribers with open claims are all refused; terminating a quiet
subscriber cascades to dependents and open predeterminations.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_INVALID_STATE,
    ERR_PROVIDER_BUSY,
)
from test_helpers.assertions import get_success_data, validate_error
from test_helpers.constants import (
    CLAIM_ADJUDICATED,
    CLAIM_PENDED_REVIEW,
    DEPENDENT_TERMINATED,
    PREDET_APPROVED,
    PREDET_SUBMITTED,
    PREDET_UNDER_REVIEW,
    PREDET_WITHDRAWN,
    PROVIDER_ACTIVE,
    SUBSCRIBER_ACTIVE,
    SUBSCRIBER_TERMINATED,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    approved_predetermination,
    claim_lines,
    create_claim,
    create_dependent,
    create_predetermination,
    read_dependent,
    read_predetermination,
    read_provider,
    read_subscriber,
    standard_stack,
    under_review_predetermination,
)
from test_helpers.test_users import (
    ADMIN,
    EXAMINER,
    NETWORK,
    make_member_headers,
    make_provider_headers,
    make_reviewer_headers,
)


class TestInvalidTransitions:
    def test_predet_approve_from_submitted_returns_invalid_state(self, client):
        """Approval is declared only from UNDER_REVIEW.

        PRD 3.4: "Approval is the load-bearing transition. The reviewer of
        record approves with `expected_predetermination_version` matching the
        predetermination's current `version` per §2.9."

        Design: Corner/state_machines/predet_approve_from_submitted_returns_invalid_state
        """
        stack = standard_stack(client)
        predet = create_predetermination(
            client, stack["subscriber"]["id"], stack["provider"]
        )

        resp = client.approve_predetermination(
            predet["id"],
            {"expected_predetermination_version": predet["version"]},
            headers=make_reviewer_headers("rev-1"),
        )

        validate_error(resp, ERR_INVALID_STATE, expected_status=409)
        reread = read_predetermination(client, predet["id"])
        assert reread["status"] == PREDET_SUBMITTED

    def test_pay_pended_review_claim_returns_invalid_state(self, client):
        """Payment is declared only from ADJUDICATED.

        PRD 3.9: "An adjudicated claim becomes payable when a
        `ClaimsExaminer` marks it paid, moving `ADJUDICATED → PAID`."
        PRD 3.5: "Otherwise, if the subscriber's `cob_priority` is
        `SECONDARY`, the claim moves `RECEIVED → PENDED_REVIEW` to await
        examiner confirmation of the primary carrier's payment."

        Design: Corner/state_machines/pay_pended_review_claim_returns_invalid_state
        """
        stack = standard_stack(
            client,
            subscriber_overrides={
                "member_id": "M-SEC",
                "full_name": "Sadie Secondary",
                "cob_priority": "SECONDARY",
                "other_plan_external_id": "EXT-9",
            },
        )
        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    cdt_code="D2391", tooth_number="19",
                    submitted_amount_cents=10000,
                )
            ],
        )
        assert claim["status"] == CLAIM_PENDED_REVIEW

        resp = client.pay_claim(claim["id"], headers=EXAMINER)

        validate_error(resp, ERR_INVALID_STATE, expected_status=409)
        reread = get_success_data(client.get_claim(claim["id"], headers=EXAMINER))
        assert reread["status"] == CLAIM_PENDED_REVIEW

    def test_withdraw_approved_predet_returns_invalid_state(self, client):
        """Withdrawal is declared only from SUBMITTED and UNDER_REVIEW.

        PRD 3.4: "A member may withdraw their own predetermination from
        either `SUBMITTED` or `UNDER_REVIEW`, moving it to `WITHDRAWN`; the
        caller's `X-User-ID` must be the subscriber who owns it."

        Design: Corner/state_machines/withdraw_approved_predet_returns_invalid_state
        """
        stack = standard_stack(client)
        approved = approved_predetermination(client, stack)
        assert approved["status"] == PREDET_APPROVED

        resp = client.withdraw_predetermination(
            approved["id"], headers=make_member_headers(stack["subscriber"]["id"])
        )

        validate_error(resp, ERR_INVALID_STATE, expected_status=409)
        reread = read_predetermination(client, approved["id"])
        assert reread["status"] == PREDET_APPROVED


class TestTerminationPreconditionsAndCascade:
    def test_subscriber_terminate_with_open_claim_returns_invalid_state(self, client):
        """An unpaid adjudicated claim blocks subscriber termination.

        PRD 3.3: "It is refused while the subscriber has any claim in
        `RECEIVED`, `PENDED_ATTACHMENTS`, `PENDED_REVIEW`, or `ADJUDICATED`
        — such claims must first reach `PAID`, `DENIED`, or `VOID`."

        Design: Corner/state_machines/subscriber_terminate_with_open_claim_returns_invalid_state
        """
        stack = standard_stack(client)
        claim = adjudicated_claim(client, stack)
        assert claim["status"] == CLAIM_ADJUDICATED

        resp = client.terminate_subscriber(stack["subscriber"]["id"], headers=ADMIN)

        validate_error(resp, ERR_INVALID_STATE, expected_status=409)
        reread = read_subscriber(client, stack["subscriber"]["id"])
        assert reread["status"] == SUBSCRIBER_ACTIVE

    def test_provider_terminate_with_under_review_predet_returns_provider_busy(self, client):
        """An in-flight predetermination blocks provider termination.

        PRD 3.2: "Terminating a provider (`ACTIVE → TERMINATED`) is blocked
        while the provider has any predetermination in `UNDER_REVIEW` or any
        claim in `PENDED_REVIEW`; the attempt fails with `ERR_PROVIDER_BUSY`
        (HTTP 409)."

        Design: Corner/state_machines/provider_terminate_with_under_review_predet_returns_provider_busy
        """
        stack = standard_stack(client)
        under_review_predetermination(client, stack)

        resp = client.terminate_provider(stack["provider"]["id"], headers=NETWORK)

        validate_error(resp, ERR_PROVIDER_BUSY, expected_status=409)
        reread = read_provider(client, stack["provider"]["id"])
        assert reread["status"] == PROVIDER_ACTIVE

    def test_subscriber_terminate_cascades_to_dependents_and_open_predets(self, client):
        """Termination sweeps dependents and open predeterminations along.

        PRD 3.3: "When termination proceeds, every dependent of the
        subscriber transitions `ACTIVE → TERMINATED`, and every
        predetermination of the subscriber still in `SUBMITTED` or
        `UNDER_REVIEW` transitions to `WITHDRAWN`."

        Design: Corner/state_machines/subscriber_terminate_cascades_to_dependents_and_open_predets
        """
        stack = standard_stack(client)
        dependent = create_dependent(client, stack["subscriber"]["id"])
        predet = create_predetermination(
            client, stack["subscriber"]["id"], stack["provider"]
        )

        resp = client.terminate_subscriber(stack["subscriber"]["id"], headers=ADMIN)
        terminated = get_success_data(resp)

        assert terminated["status"] == SUBSCRIBER_TERMINATED
        assert read_dependent(client, dependent["id"])["status"] == DEPENDENT_TERMINATED
        assert read_predetermination(client, predet["id"])["status"] == PREDET_WITHDRAWN


class TestClaimRoutingAndResume:
    def test_attachment_completion_moves_claim_from_pended_to_adjudicated(self, client):
        """The last attachment runs the full pipeline in the same request.

        PRD 3.5: "If any line's fee schedule entry is flagged
        `requires_attachment` and no matching attachment exists yet, the
        claim moves `RECEIVED → PENDED_ATTACHMENTS` and the
        attachment-requiring lines stay in `PENDING`."
        PRD 3.5: "When an upload completes the last missing attachment on a
        `PENDED_ATTACHMENTS` claim, the claim re-evaluates its routing: a
        secondary-coverage claim proceeds `PENDED_ATTACHMENTS →
        PENDED_REVIEW`, while a primary or single-coverage claim proceeds
        `PENDED_ATTACHMENTS → ADJUDICATED` and adjudicates immediately."

        Design: Corner/state_machines/attachment_completion_moves_claim_from_pended_to_adjudicated
        """
        entries = [
            f.fee_schedule_entry_payload(
                cdt_code="D2740", allowed_cents=10000, category="MAJOR",
                requires_attachment=True,
            ),
        ]
        stack = standard_stack(client, entries=entries)

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                lines=[
                    f.claim_line_payload(
                        cdt_code="D2740", tooth_number="14",
                        submitted_amount_cents=9000,
                    )
                ],
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )
        claim = get_success_data(resp)
        assert claim["status"] == "PENDED_ATTACHMENTS"
        line_id = claim_lines(client, claim["id"])[0]["id"]

        resp = client.create_claim_attachment(
            claim["id"],
            f.create_attachment_payload(
                line_id, attachment_kind="RADIOGRAPH", blob_ref="blob://xray-14"
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )
        assert resp.status_code == 201

        reread = get_success_data(client.get_claim(claim["id"], headers=EXAMINER))
        assert reread["status"] == CLAIM_ADJUDICATED
        assert reread["total_allowed_cents"] == 9000
        assert reread["total_plan_pay_cents"] == 4500, (
            "floor(9000 * 50/100) == 4500, got %r" % reread["total_plan_pay_cents"]
        )

    def test_cob_pended_claim_adjudicates_on_cob_confirm(self, client):
        """Examiner confirmation runs the pipeline including the waterfall.

        PRD 3.5: "Otherwise, if the subscriber's `cob_priority` is
        `SECONDARY`, the claim moves `RECEIVED → PENDED_REVIEW` to await
        examiner confirmation of the primary carrier's payment."
        PRD 3.5: "For claims waiting on coordination of benefits, a
        `ClaimsExaminer` confirms the primary carrier's payment by supplying
        `cob_other_plan_paid_cents` (zero or more), moving the claim
        `PENDED_REVIEW → ADJUDICATED` and running the full pipeline including
        the COB waterfall of §3.8."

        Design: Corner/state_machines/cob_pended_claim_adjudicates_on_cob_confirm
        """
        stack = standard_stack(
            client,
            subscriber_overrides={
                "member_id": "M-SEC2",
                "full_name": "Sid Secondary",
                "cob_priority": "SECONDARY",
                "other_plan_external_id": "EXT-9",
            },
        )
        claim = create_claim(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            lines=[
                f.claim_line_payload(
                    cdt_code="D2391", tooth_number="19",
                    submitted_amount_cents=10000,
                )
            ],
        )
        assert claim["status"] == CLAIM_PENDED_REVIEW

        resp = client.cob_confirm_claim(
            claim["id"], {"cob_other_plan_paid_cents": 7000}, headers=EXAMINER
        )
        confirmed = get_success_data(resp)

        assert confirmed["status"] == CLAIM_ADJUDICATED
        assert confirmed["cob_other_plan_paid_cents"] == 7000
