"""Non-linear lifecycles: reviewer cycles, lazy expiry, paid-then-void.

The predetermination workflow loops UNDER_REVIEW back to itself on
reassignment and decays APPROVED to EXPIRED when the clock passes the
validity window; the claim workflow forks between DENIED and PAID and
PAID can revert to VOID with the accumulator unwound.
"""

from test_helpers import factories as f
from test_helpers.api_client import same_instant
from test_helpers.assertions import validate_success
from test_helpers.constants import (
    CATEGORY_MAJOR,
    CDT_CROWN_MAJOR,
    CLAIM_ADJUDICATED,
    CLAIM_DENIED,
    CLAIM_PAID,
    CLAIM_VOID,
    DENIAL_WAITING_PERIOD,
    PREDET_APPROVED,
    PREDET_EXPIRED,
    PREDET_UNDER_REVIEW,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    approve_predetermination,
    assign_predetermination,
    claim_lines,
    create_claim,
    create_predetermination,
    pay_claim,
    read_predetermination,
    reassign_predetermination,
    set_clock,
    standard_stack,
    subscriber_accumulators,
    void_claim,
)


class TestPredeterminationReassignCycleAndExpiry:
    """UNDER_REVIEW loops on itself; APPROVED decays with the clock."""

    def _nl1_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-NL1"},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=100000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-NL1", "full_name": "Eve Prime"},
        )

    def test_reassign_loops_under_review_and_swaps_the_reviewer(self, client):
        """Reassignment stays in UNDER_REVIEW under a different reviewer.

        PRD 3.4: "A different reviewer may take it over: reassignment
        requires the payload's `clinical_reviewer_id` to equal the requesting
        reviewer's `X-User-ID` and to differ from the currently recorded
        reviewer — reassigning to oneself is a segregation-of-duties
        violation — and it recomputes the estimate against the schedule
        currently in force, without pinning anything."

        Design: Difficulty/non_linear_state_machine/predetermination_reassign_cycle_then_expiry
        """
        stack = self._nl1_stack(client)
        predet = create_predetermination(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            submitted_amount_cents=110000,
            planned_service_date="2026-06-01T00:00:00Z",
        )
        assigned = assign_predetermination(client, predet["id"], "rev-1")

        reassigned = reassign_predetermination(client, predet["id"], "rev-2")

        assert reassigned["status"] == PREDET_UNDER_REVIEW, (
            "reassign loops back to UNDER_REVIEW, got %r" % reassigned["status"]
        )
        assert reassigned["clinical_reviewer_id"] == "rev-2"
        assert reassigned["version"] == assigned["version"] + 1, (
            "each mutation increments the version"
        )

    def test_approval_then_clock_passing_expiry_decays_to_expired(self, client):
        """APPROVED decays lazily once the clock passes the validity window.

        PRD 3.4: "`expires_on` is set to the logical clock plus ninety days
        — the predetermination validity window."
        PRD 3.4: "once the logical clock passes `expires_on`, the
        predetermination lazily transitions `APPROVED → EXPIRED` on read or
        when a claim references it, releasing the pricing pin so that claims
        thereafter resolve the schedule by service date normally."

        Design: Difficulty/non_linear_state_machine/predetermination_reassign_cycle_then_expiry
        """
        stack = self._nl1_stack(client)
        predet = create_predetermination(
            client,
            stack["subscriber"]["id"],
            stack["provider"],
            submitted_amount_cents=110000,
            planned_service_date="2026-06-01T00:00:00Z",
        )
        assign_predetermination(client, predet["id"], "rev-1")
        reassigned = reassign_predetermination(client, predet["id"], "rev-2")

        approved = approve_predetermination(
            client, predet["id"], reassigned["version"], "rev-2"
        )
        assert approved["status"] == PREDET_APPROVED
        # Approval at 2026-01-01T00:00:00Z plus ninety days.
        assert same_instant(approved["expires_on"], "2026-04-01T00:00:00Z"), (
            "expires_on must be the logical clock plus ninety days, got %r"
            % approved["expires_on"]
        )
        assert approved["version"] == reassigned["version"] + 1

        set_clock(client, "2026-04-02T00:00:00Z")
        decayed = read_predetermination(client, predet["id"])
        assert decayed["status"] == PREDET_EXPIRED, (
            "reading past expires_on lazily transitions to EXPIRED, got %r"
            % decayed["status"]
        )


class TestClaimDeniedBranchAndPaidThenVoidRevert:
    """One claim forks to DENIED; another runs ADJUDICATED → PAID → VOID."""

    def _nl2_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-NL2", "major_waiting_months": 6},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=8000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-NL2", "full_name": "Fred Prime"},
        )

    def test_all_lines_denied_forks_the_claim_to_denied(self, client):
        """A claim inside the waiting period auto-denies end to end.

        PRD 3.7: "When every line denies, the claim itself transitions
        `ADJUDICATED → DENIED` automatically and no accumulator changes
        attach to it."
        PRD 3.7: "A service rendered before the earliest eligible date is
        denied with `denial_code` `WAITING_PERIOD`; a service rendered
        exactly on the eligible date is eligible — the boundary is
        inclusive."

        Design: Difficulty/non_linear_state_machine/claim_branching_denied_path_and_paid_then_void_revert
        """
        stack = self._nl2_stack(client)

        claim = adjudicated_claim(
            client,
            stack,
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="9",
                    submitted_amount_cents=8000,
                )
            ],
        )

        assert claim["status"] == CLAIM_DENIED
        line = claim_lines(client, claim["id"])[0]
        assert line["denial_code"] == DENIAL_WAITING_PERIOD
        assert line["status"] == "DENIED"

    def test_paid_claim_voids_back_and_restores_the_accumulator(self, client):
        """The PAID branch supports a revert that unwinds the accumulator.

        PRD 3.9: "A `ClaimsExaminer` may void an `ADJUDICATED` claim
        unconditionally, and may void a `PAID` claim only while the logical
        clock remains within thirty days of the claim's `updated_at` — the
        void window."
        PRD 3.9: "Voiding reverses the accumulator exactly: the voided
        claim's payable lines have their `deductible_applied_cents` sums
        subtracted from `deductible_met_cents` and their `plan_pay_cents`
        sums subtracted from `annual_max_used_cents`, and the accumulator's
        `version` increments."

        Design: Difficulty/non_linear_state_machine/claim_branching_denied_path_and_paid_then_void_revert
        """
        stack = self._nl2_stack(client)

        # Service after the six-month major waiting period adjudicates clean.
        claim = adjudicated_claim(
            client,
            stack,
            service_date="2026-08-01T00:00:00Z",
            received_date="2026-08-02T00:00:00Z",
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="9",
                    submitted_amount_cents=8000,
                )
            ],
        )
        assert claim["status"] == CLAIM_ADJUDICATED

        paid = pay_claim(client, claim["id"])
        assert paid["status"] == CLAIM_PAID

        accumulators = subscriber_accumulators(client, stack["subscriber"]["id"])
        assert accumulators[0]["annual_max_used_cents"] == 4000

        voided = void_claim(client, claim["id"], paid["version"])
        assert voided["status"] == CLAIM_VOID

        accumulators = subscriber_accumulators(client, stack["subscriber"]["id"])
        assert accumulators[0]["annual_max_used_cents"] == 0, (
            "the void unwinds the 4000 the paid line drew"
        )
