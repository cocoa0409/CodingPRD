"""Validation order: the first failing layer decides the error.

Both probes here violate a state-layer rule and a later business rule in
the same request; the PRD fixes the layering, so the state error must be
the one that surfaces.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_PLAN_NOT_ACTIVE
from test_helpers.assertions import validate_error
from test_helpers.fixtures import standard_stack
from test_helpers.test_users import ADMIN, make_provider_headers


class TestPlanStateBeatsClaimTemporalRules:
    """A suspended plan rejects before timely filing is even examined."""

    def test_suspended_plan_and_stale_received_date_yields_plan_not_active(self, client):
        """The state layer fires before the timely-filing business rule.

        PRD 2.10: "Every request passes through validation layers in a fixed
        order, and the first failing layer determines the error returned."
        PRD 2.10: "Only then are required-field presence, types, and enum
        membership validated, failing with `ERR_INVALID_REQUEST` (HTTP 400),
        followed by state-transition legality (`ERR_INVALID_STATE`, HTTP 409)
        and finally the business rules described in §3."
        PRD 3.1: "An active plan may be suspended (`ACTIVE → SUSPENDED`),
        which blocks new subscriber enrollment and new claim submission
        against it with `ERR_PLAN_NOT_ACTIVE` (HTTP 409) while leaving
        already-adjudicated-but-unpaid claims payable."

        Design: Difficulty/priority_pair_validation_conflict/claim_on_suspended_plan_with_stale_received_date_state_beats_temporal
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-PP1"},
            subscriber_overrides={"member_id": "M-PP1", "full_name": "Ivy Prime"},
        )
        resp = client.suspend_plan(stack["plan"]["id"], headers=ADMIN)
        assert resp.status_code == 200

        # received_date is 392 days after service_date — also untimely.
        resp = client.create_claim(
            {
                "subscriber_id": stack["subscriber"]["id"],
                "provider_id": stack["provider"]["id"],
                "service_date": "2026-01-05T00:00:00Z",
                "received_date": "2027-02-01T00:00:00Z",
                "lines": [
                    {
                        "line_number": 1,
                        "cdt_code": "D0120",
                        "tooth_number": "",
                        "submitted_amount_cents": 5000,
                    }
                ],
            },
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_PLAN_NOT_ACTIVE, expected_status=409)

    def test_suspended_plan_rejects_even_a_timely_claim(self, client):
        """The plan state alone is sufficient for the 409.

        PRD 3.1: "An active plan may be suspended (`ACTIVE → SUSPENDED`),
        which blocks new subscriber enrollment and new claim submission
        against it with `ERR_PLAN_NOT_ACTIVE` (HTTP 409) while leaving
        already-adjudicated-but-unpaid claims payable."

        Design: Difficulty/priority_pair_validation_conflict/claim_on_suspended_plan_with_stale_received_date_state_beats_temporal
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-PP1b"},
            subscriber_overrides={"member_id": "M-PP1b", "full_name": "Ivy Prime"},
        )
        resp = client.suspend_plan(stack["plan"]["id"], headers=ADMIN)
        assert resp.status_code == 200

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"], stack["provider"]["id"]
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_PLAN_NOT_ACTIVE, expected_status=409)


class TestPlanStateBeatsEnrollmentReferentialRules:
    """A suspended plan rejects before the COB pairing is examined."""

    def test_suspended_plan_and_bad_cob_pairing_yields_plan_not_active(self, client):
        """The state layer fires before the COB referential rule.

        PRD 2.10: "Every request passes through validation layers in a fixed
        order, and the first failing layer determines the error returned."
        PRD 3.3: "Enrollment against a plan that is not `ACTIVE` fails with
        `ERR_PLAN_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/subscriber_create_on_suspended_plan_with_bad_cob_state_beats_referential
        """
        stack = standard_stack(client, plan_overrides={"plan_code": "DD-PP2"})
        resp = client.suspend_plan(stack["plan"]["id"], headers=ADMIN)
        assert resp.status_code == 200

        # cob_priority SECONDARY without other_plan_external_id — also invalid.
        resp = client.create_subscriber(
            {
                "plan_id": stack["plan"]["id"],
                "member_id": "M-PP2",
                "full_name": "Jack Prime",
                "date_of_birth": "1991-04-04T00:00:00Z",
                "effective_date": "2026-01-01T00:00:00Z",
                "cob_priority": "SECONDARY",
            },
            headers=ADMIN,
        )

        validate_error(resp, ERR_PLAN_NOT_ACTIVE, expected_status=409)

    def test_suspended_plan_rejects_even_a_valid_enrollment(self, client):
        """The plan state alone is sufficient for the 409 at enrollment.

        PRD 3.3: "Enrollment against a plan that is not `ACTIVE` fails with
        `ERR_PLAN_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/subscriber_create_on_suspended_plan_with_bad_cob_state_beats_referential
        """
        stack = standard_stack(client, plan_overrides={"plan_code": "DD-PP2b"})
        resp = client.suspend_plan(stack["plan"]["id"], headers=ADMIN)
        assert resp.status_code == 200

        resp = client.create_subscriber(
            f.create_subscriber_payload(
                stack["plan"]["id"], member_id="M-PP2b", full_name="Jack Prime"
            ),
            headers=ADMIN,
        )

        validate_error(resp, ERR_PLAN_NOT_ACTIVE, expected_status=409)
