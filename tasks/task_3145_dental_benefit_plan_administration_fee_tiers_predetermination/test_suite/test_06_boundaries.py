"""Boundary precision at the waiting-period and annual-maximum edges.

A service rendered exactly on the earliest eligible date is covered while
one day earlier is not; an approval estimate exactly equal to the remaining
annual maximum succeeds while one over it is refused.
"""

from test_helpers import factories as f
from test_helpers.api_errors import ERR_ANNUAL_MAX_EXCEEDED
from test_helpers.assertions import validate_error
from test_helpers.constants import (
    CATEGORY_MAJOR,
    CDT_CROWN_MAJOR,
    CLAIM_DENIED,
    DENIAL_WAITING_PERIOD,
    PREDET_APPROVED,
    PREDET_UNDER_REVIEW,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    assign_predetermination,
    claim_lines,
    create_predetermination,
    read_predetermination,
    standard_stack,
)
from test_helpers.test_users import make_reviewer_headers


class TestWaitingPeriodBoundaryIsInclusive:
    """Six months of major waiting from a January 1 effective date."""

    def _bp1_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-BP1", "major_waiting_months": 6},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=8000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-BP1", "full_name": "Kate Prime"},
        )

    def test_service_one_day_before_the_eligible_date_is_denied(self, client):
        """2026-06-30 is one day short of the six-month mark.

        PRD 3.7: "A service rendered before the earliest eligible date is
        denied with `denial_code` `WAITING_PERIOD`; a service rendered
        exactly on the eligible date is eligible — the boundary is
        inclusive."

        Design: Difficulty/boundary_precision_check/waiting_period_boundary_service_on_earliest_eligible_date_is_covered
        """
        stack = self._bp1_stack(client)

        claim = adjudicated_claim(
            client,
            stack,
            service_date="2026-06-30T00:00:00Z",
            received_date="2026-07-02T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="30",
                    submitted_amount_cents=8000,
                )
            ],
        )

        assert claim["status"] == CLAIM_DENIED
        line = claim_lines(client, claim["id"])[0]
        assert line["denial_code"] == DENIAL_WAITING_PERIOD

    def test_service_exactly_on_the_eligible_date_is_covered(self, client):
        """2026-07-01 is exactly effective_date + 6 months — covered.

        PRD 3.7: "basic lines wait `basic_waiting_months` calendar months
        from the subscriber's `effective_date`, and major lines wait
        `major_waiting_months`. A service rendered before the earliest
        eligible date is denied with `denial_code` `WAITING_PERIOD`; a
        service rendered exactly on the eligible date is eligible — the
        boundary is inclusive."

        Design: Difficulty/boundary_precision_check/waiting_period_boundary_service_on_earliest_eligible_date_is_covered
        """
        stack = self._bp1_stack(client)

        claim = adjudicated_claim(
            client,
            stack,
            service_date="2026-07-01T00:00:00Z",
            received_date="2026-07-02T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="30",
                    submitted_amount_cents=8000,
                )
            ],
        )

        line = claim_lines(client, claim["id"])[0]
        assert line["status"] == "PAYABLE"
        assert line["plan_pay_cents"] == 4000, (
            "floor(8000 * 50/100) == 4000, got %r" % line["plan_pay_cents"]
        )


class TestApproveAgainstTheRemainingAnnualMaximum:
    """A five-thousand-cent cap against estimates at and over it."""

    def _bp2_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-BP2", "annual_maximum_cents": 5000},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=30000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-BP2", "full_name": "Liam Prime"},
        )

    def test_estimate_equal_to_the_remaining_maximum_approves(self, client):
        """Estimated plan pay of 5000 against 5000 remaining is allowed.

        PRD 3.4: "if the freshly computed `estimated_plan_pay_cents` would
        exceed the plan's remaining annual maximum for the patient — the
        plan's `annual_maximum_cents` minus the accumulator's current
        `annual_max_used_cents` — the approval is refused with
        `ERR_ANNUAL_MAX_EXCEEDED` (HTTP 422), so a clinician can never
        promise payment the plan cannot deliver."

        Design: Difficulty/boundary_precision_check/predet_approve_annual_max_remaining_exact_equality_allowed
        """
        stack = self._bp2_stack(client)
        predet = create_predetermination(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            submitted_amount_cents=10000,
            planned_service_date="2026-03-01T00:00:00Z",
        )
        assigned = assign_predetermination(client, predet["id"], "rev-1")
        # allowed == 10000; est plan pay == floor(10000*50/100) == 5000 == cap.
        assert assigned["estimated_plan_pay_cents"] == 5000

        resp = client.approve_predetermination(
            predet["id"],
            {"expected_predetermination_version": assigned["version"]},
            headers=make_reviewer_headers("rev-1"),
        )

        assert resp.status_code == 200, resp.text
        assert resp.json()["data"]["status"] == PREDET_APPROVED

    def test_estimate_over_the_remaining_maximum_is_refused(self, client):
        """Estimated plan pay of 15000 against 5000 remaining is refused.

        PRD 3.4: "if the freshly computed `estimated_plan_pay_cents` would
        exceed the plan's remaining annual maximum for the patient — the
        plan's `annual_maximum_cents` minus the accumulator's current
        `annual_max_used_cents` — the approval is refused with
        `ERR_ANNUAL_MAX_EXCEEDED` (HTTP 422), so a clinician can never
        promise payment the plan cannot deliver."

        Design: Difficulty/boundary_precision_check/predet_approve_annual_max_remaining_exact_equality_allowed
        """
        stack = self._bp2_stack(client)
        predet = create_predetermination(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            submitted_amount_cents=30000,
            planned_service_date="2026-03-01T00:00:00Z",
        )
        assigned = assign_predetermination(client, predet["id"], "rev-1")
        assert assigned["estimated_plan_pay_cents"] == 15000

        resp = client.approve_predetermination(
            predet["id"],
            {"expected_predetermination_version": assigned["version"]},
            headers=make_reviewer_headers("rev-1"),
        )

        validate_error(resp, ERR_ANNUAL_MAX_EXCEEDED, expected_status=422)
        still_open = read_predetermination(client, predet["id"])
        assert still_open["status"] == PREDET_UNDER_REVIEW, (
            "a refused approval leaves the predetermination UNDER_REVIEW"
        )
