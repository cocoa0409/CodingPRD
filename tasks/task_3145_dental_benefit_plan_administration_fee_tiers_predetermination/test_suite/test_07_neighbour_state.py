"""A claim's admissibility depends on its neighbours' lifecycle state.

The same claim payload succeeds while the plan is ACTIVE and fails once it
is SUSPENDED; the same payload fails once the rendering provider is
TERMINATED even though the plan is untouched.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_PLAN_NOT_ACTIVE, ERR_PROVIDER_TERMINATED
from test_helpers.assertions import validate_error, validate_success
from test_helpers.constants import CLAIM_ADJUDICATED
from test_helpers.fixtures import (
    adjudicated_claim,
    claim_lines,
    standard_stack,
)
from test_helpers.test_users import ADMIN, NETWORK, make_provider_headers


class TestClaimDependsOnPlanState:
    """Claim → Plan: suspension closes the intake door."""

    def test_claim_adjudicates_while_the_plan_is_active(self, client):
        """The identical payload succeeds before the suspension.

        PRD 3.1: "only an `ACTIVE` plan is referenceable when enrolling
        subscribers."
        PRD 3.5: "Otherwise the claim moves directly `RECEIVED →
        ADJUDICATED` and the adjudication pipeline of §3.7 runs immediately."

        Design: Difficulty/cross_entity_state_dependency/claim_submission_depends_on_plan_state
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-XD1"},
            subscriber_overrides={"member_id": "M-XD1", "full_name": "Mia Prime"},
        )

        claim = adjudicated_claim(client, stack)

        assert claim["status"] == CLAIM_ADJUDICATED
        line = claim_lines(client, claim["id"])[0]
        assert line["plan_pay_cents"] == 5000

    def test_claim_is_rejected_once_the_plan_is_suspended(self, client):
        """Suspension rejects the identical payload with the state error.

        PRD 3.1: "An active plan may be suspended (`ACTIVE → SUSPENDED`),
        which blocks new subscriber enrollment and new claim submission
        against it with `ERR_PLAN_NOT_ACTIVE` (HTTP 409) while leaving
        already-adjudicated-but-unpaid claims payable."

        Design: Difficulty/cross_entity_state_dependency/claim_submission_depends_on_plan_state
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-XD1b"},
            subscriber_overrides={"member_id": "M-XD1b", "full_name": "Mia Prime"},
        )

        before = adjudicated_claim(client, stack)
        assert before["status"] == CLAIM_ADJUDICATED

        resp = client.suspend_plan(stack["plan"]["id"], headers=ADMIN)
        assert resp.status_code == 200

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"],
                stack["provider"]["id"],
                service_date="2026-02-03T00:00:00Z",
                received_date="2026-02-04T00:00:00Z",
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_PLAN_NOT_ACTIVE, expected_status=409)


class TestClaimDependsOnProviderState:
    """Claim → Provider: termination closes the intake door."""

    def test_claim_is_rejected_once_the_provider_is_terminated(self, client):
        """The plan stays ACTIVE; only the provider flipped state.

        PRD 3.2: "Once terminated, any future claim or predetermination
        naming that `provider_id` is rejected with `ERR_PROVIDER_TERMINATED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/claim_submission_depends_on_provider_state
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-XD2"},
            subscriber_overrides={"member_id": "M-XD2", "full_name": "Nina Prime"},
        )
        resp = client.terminate_provider(stack["provider"]["id"], headers=NETWORK)
        assert resp.status_code == 200

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"], stack["provider"]["id"]
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_PROVIDER_TERMINATED, expected_status=409)

    def test_claim_succeeds_while_the_provider_is_active(self, client):
        """The identical payload adjudicates before termination.

        PRD 3.2: "Once terminated, any future claim or predetermination
        naming that `provider_id` is rejected with `ERR_PROVIDER_TERMINATED`
        (HTTP 409)."
        PRD 3.5: "Otherwise the claim moves directly `RECEIVED →
        ADJUDICATED` and the adjudication pipeline of §3.7 runs immediately."

        Design: Difficulty/cross_entity_state_dependency/claim_submission_depends_on_provider_state
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-XD2b"},
            subscriber_overrides={"member_id": "M-XD2b", "full_name": "Nina Prime"},
        )

        claim = adjudicated_claim(client, stack)

        assert claim["status"] == CLAIM_ADJUDICATED
        resp = client.terminate_provider(stack["provider"]["id"], headers=NETWORK)
        assert resp.status_code == 200, resp.text
