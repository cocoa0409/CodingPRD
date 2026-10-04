"""Role gates and segregation of duties.

Exclusive operations refuse the wrong role with 403; entity-backed callers
(Member, Provider) are refused when they act on someone else's aggregate;
and the clinical review workflow refuses to let the estimate change hands
implicitly.
"""

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.assertions import get_success_data, validate_error
from test_helpers.constants import (
    CLAIM_ADJUDICATED,
    PREDET_SUBMITTED,
    PREDET_UNDER_REVIEW,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    assign_predetermination,
    create_predetermination,
    create_provider,
    create_subscriber,
    read_predetermination,
    standard_stack,
)
from test_helpers.test_users import (
    ADMIN,
    EXAMINER,
    make_member_headers,
    make_provider_headers,
    make_reviewer_headers,
)


class TestRoleExclusiveDenials:
    def test_member_cannot_create_plan_returns_unauthorized(self, client):
        """Plan authoring belongs to the PlanAdmin alone.

        PRD 2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorized role list; a role that is recognized but
        not permitted on the endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD 3.1: "A `PlanAdmin` authors a benefit plan by supplying its
        `plan_code` — a globally unique human-readable identifier such as
        DD-PRIME-100 — together with the financial skeleton:"

        Design: Corner/rbac/member_cannot_create_plan_returns_unauthorized
        """
        resp = client.create_plan(
            f.create_plan_payload(plan_code="DD-RBAC"),
            headers=make_member_headers("8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"),
        )

        validate_error(resp, ERR_UNAUTHORIZED, expected_status=403)

    def test_clinical_reviewer_cannot_pay_claim_returns_unauthorized(self, client):
        """Claim payment belongs to the ClaimsExaminer alone.

        PRD 2.1: "Once authenticated, the caller's role is checked against
        the endpoint's authorized role list; a role that is recognized but
        not permitted on the endpoint is rejected with `ERR_UNAUTHORIZED`
        (HTTP 403)."
        PRD 3.9: "An adjudicated claim becomes payable when a
        `ClaimsExaminer` marks it paid, moving `ADJUDICATED → PAID`."

        Design: Corner/rbac/clinical_reviewer_cannot_pay_claim_returns_unauthorized
        """
        stack = standard_stack(client)
        claim = adjudicated_claim(client, stack)
        assert claim["status"] == CLAIM_ADJUDICATED

        resp = client.pay_claim(
            claim["id"], headers=make_reviewer_headers("rev-1")
        )

        validate_error(resp, ERR_UNAUTHORIZED, expected_status=403)
        reread = get_success_data(client.get_claim(claim["id"], headers=EXAMINER))
        assert reread["status"] == CLAIM_ADJUDICATED


class TestOwnershipGates:
    def test_member_cannot_submit_predet_for_other_subscriber(self, client):
        """A member files for themselves or their own dependents only.

        PRD 3.4: "A `Provider` caller may submit only for themselves — the
        payload's `provider_id` must equal their `X-User-ID` — and a `Member`
        caller may submit only for themselves or their own dependents; either
        ownership violation draws `ERR_UNAUTHORIZED`."

        Design: Corner/rbac/member_cannot_submit_predet_for_other_subscriber
        """
        stack = standard_stack(client)
        other = create_subscriber(
            client,
            stack["plan"]["id"],
            member_id="M-OTHER2",
            full_name="Omar Other",
        )

        resp = client.create_predetermination(
            f.create_predetermination_payload(
                other["id"], stack["provider"]["id"]
            ),
            headers=make_member_headers(stack["subscriber"]["id"]),
        )

        validate_error(resp, ERR_UNAUTHORIZED, expected_status=403)

    def test_provider_cannot_file_claim_for_other_provider(self, client):
        """A provider files under their own identity only.

        PRD 3.5: "A claim arrives from the rendering `Provider` — whose
        `X-User-ID` must equal the payload's `provider_id` — or from a
        `ClaimsExaminer` filing on the provider's behalf."

        Design: Corner/rbac/provider_cannot_file_claim_for_other_provider
        """
        stack = standard_stack(client)
        other_provider = create_provider(
            client, legal_name="Other Dental"
        )

        resp = client.create_claim(
            f.create_claim_payload(
                stack["subscriber"]["id"], other_provider["id"]
            ),
            headers=make_provider_headers(stack["provider"]["id"]),
        )

        validate_error(resp, ERR_UNAUTHORIZED, expected_status=403)


class TestSegregationOfDuties:
    def test_approve_by_non_assigned_reviewer_returns_segregation_of_duties(self, client):
        """Only the reviewer of record may approve.

        PRD 3.4: "denial is permitted only to the reviewer of record, so
        `X-User-ID` must equal the stored `clinical_reviewer_id`."

        Design: Corner/rbac/approve_by_non_assigned_reviewer_returns_segregation_of_duties
        """
        stack = standard_stack(client)
        predet = create_predetermination(
            client, stack["subscriber"]["id"], stack["provider"]
        )
        assigned = assign_predetermination(client, predet["id"], "rev-1")

        resp = client.approve_predetermination(
            predet["id"],
            {"expected_predetermination_version": assigned["version"]},
            headers=make_reviewer_headers("rev-2"),
        )

        validate_error(resp, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        reread = read_predetermination(client, predet["id"])
        assert reread["status"] == PREDET_UNDER_REVIEW
        assert reread["clinical_reviewer_id"] == "rev-1"

    def test_assign_with_payload_reviewer_mismatch_returns_segregation_of_duties(self, client):
        """Assignment is self-assignment; naming someone else is refused.

        PRD 3.4: "A `ClinicalReviewer` takes ownership by submitting a
        `clinical_reviewer_id` in the assign payload that must equal their
        own `X-User-ID` — a reviewer cannot be assigned by anyone else, and
        any mismatch is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/rbac/assign_with_payload_reviewer_mismatch_returns_segregation_of_duties
        """
        stack = standard_stack(client)
        predet = create_predetermination(
            client, stack["subscriber"]["id"], stack["provider"]
        )

        resp = client.assign_predetermination(
            predet["id"],
            {"clinical_reviewer_id": "rev-2"},
            headers=make_reviewer_headers("rev-1"),
        )

        validate_error(resp, ERR_SEGREGATION_OF_DUTIES, expected_status=403)
        reread = read_predetermination(client, predet["id"])
        assert reread["status"] == PREDET_SUBMITTED
