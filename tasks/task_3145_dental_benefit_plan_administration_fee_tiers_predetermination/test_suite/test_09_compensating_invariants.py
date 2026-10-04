"""Compensating actions restore the conserved totals.

Adjudication moves the accumulator forward; voiding moves it back by
exactly the same amount — for the annual maximum and, separately, for the
deductible when two claims share it.
"""

from test_helpers import factories as f
from test_helpers.constants import (
    CATEGORY_BASIC,
    CATEGORY_MAJOR,
    CDT_CROWN_MAJOR,
    CDT_FILING_BASIC,
    CLAIM_PAID,
    CLAIM_VOID,
)
from test_helpers.fixtures import (
    adjudicated_claim,
    pay_claim,
    read_claim,
    standard_stack,
    subscriber_accumulators,
    void_claim,
)


class TestAdjudicateThenVoidRestoresAnnualMax:
    """annual_max_used_cents returns to its pre-claim value."""

    def test_void_restores_annual_max_used_to_zero(self, client):
        """Adjudication draws 4000; the void returns it.

        PRD 3.9: "Voiding reverses the accumulator exactly: the voided
        claim's payable lines have their `deductible_applied_cents` sums
        subtracted from `deductible_met_cents` and their `plan_pay_cents`
        sums subtracted from `annual_max_used_cents`, and the accumulator's
        `version` increments."
        PRD 3.9: "After reversal, the invariant of §2.7 holds again — the
        patient's remaining deductible and maximum are as if the claim had
        never adjudicated."

        Design: Difficulty/compensating_invariant/adjudicate_then_void_restores_annual_max_used
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-CI1"},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=8000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-CI1", "full_name": "Paul Prime"},
        )

        claim = adjudicated_claim(
            client,
            stack,
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="18",
                    submitted_amount_cents=8000,
                )
            ],
        )
        after_adjudication = subscriber_accumulators(
            client, stack["subscriber"]["id"]
        )[0]
        assert after_adjudication["annual_max_used_cents"] == 4000

        voided = void_claim(client, claim["id"], claim["version"])
        assert voided["status"] == CLAIM_VOID

        after_void = subscriber_accumulators(client, stack["subscriber"]["id"])[0]
        assert after_void["annual_max_used_cents"] == 0, (
            "the invariant is restored — the claim never adjudicated"
        )

    def test_void_leaves_the_claim_record_intact(self, client):
        """The claim's own totals remain recorded after the reversal.

        PRD 3.9: "Voiding reverses the accumulator exactly: the voided
        claim's payable lines have their `deductible_applied_cents` sums
        subtracted from `deductible_met_cents` and their `plan_pay_cents`
        sums subtracted from `annual_max_used_cents`, and the accumulator's
        `version` increments."

        Design: Difficulty/compensating_invariant/adjudicate_then_void_restores_annual_max_used
        """
        stack = standard_stack(
            client,
            plan_overrides={"plan_code": "DD-CI1b"},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_CROWN_MAJOR, allowed_cents=8000,
                    category=CATEGORY_MAJOR,
                ),
            ],
            subscriber_overrides={"member_id": "M-CI1b", "full_name": "Paul Prime"},
        )

        claim = adjudicated_claim(
            client,
            stack,
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_CROWN_MAJOR, tooth_number="18",
                    submitted_amount_cents=8000,
                )
            ],
        )
        assert claim["total_plan_pay_cents"] == 4000

        void_claim(client, claim["id"], claim["version"])

        reread = read_claim(client, claim["id"])
        assert reread["status"] == CLAIM_VOID
        assert reread["total_plan_pay_cents"] == 4000, (
            "the voided claim keeps its recorded totals"
        )


class TestVoidOfSecondClaimRestoresDeductibleToFirstClaimsLevel:
    """deductible_met_cents returns to the surviving claim's draw."""

    def _ci2_stack(self, client):
        return standard_stack(
            client,
            plan_overrides={"plan_code": "DD-CI2", "deductible_cents": 15000},
            entries=[
                f.fee_schedule_entry_payload(
                    cdt_code=CDT_FILING_BASIC, allowed_cents=10000,
                    category=CATEGORY_BASIC,
                ),
            ],
            subscriber_overrides={"member_id": "M-CI2", "full_name": "Quinn Prime"},
        )

    def _file_and_pay(self, client, stack, service_date, received_date, tooth):
        claim = adjudicated_claim(
            client,
            stack,
            service_date=service_date,
            received_date=received_date,
            lines=[
                f.claim_line_payload(
                    cdt_code=CDT_FILING_BASIC, tooth_number=tooth,
                    submitted_amount_cents=10000,
                )
            ],
        )
        return pay_claim(client, claim["id"])

    def test_voiding_the_second_claim_restores_the_first_claims_deductible(self, client):
        """Claim 1 drew 10000; claim 2 drew 5000; voiding 2 leaves 10000.

        PRD 3.9: "Voiding reverses the accumulator exactly: the voided
        claim's payable lines have their `deductible_applied_cents` sums
        subtracted from `deductible_met_cents` and their `plan_pay_cents`
        sums subtracted from `annual_max_used_cents`, and the accumulator's
        `version` increments."

        Design: Difficulty/compensating_invariant/void_of_second_claim_restores_deductible_to_first_claims_level
        """
        stack = self._ci2_stack(client)
        self._file_and_pay(client, stack, "2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z", "19")
        paid_2 = self._file_and_pay(
            client, stack, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", "20"
        )

        before = subscriber_accumulators(client, stack["subscriber"]["id"])[0]
        assert before["deductible_met_cents"] == 15000
        assert before["annual_max_used_cents"] == 4000, (
            "claim 1 paid 0 (all to deductible); claim 2 paid 4000"
        )

        void_claim(client, paid_2["id"], paid_2["version"])

        after = subscriber_accumulators(client, stack["subscriber"]["id"])[0]
        assert after["deductible_met_cents"] == 10000, (
            "claim 1's draw survives; claim 2's 5000 is reversed"
        )
        assert after["annual_max_used_cents"] == 0

    def test_voiding_the_second_claim_leaves_the_first_paid(self, client):
        """The compensation touches only the voided claim.

        PRD 3.9: "Voiding reverses the accumulator exactly: the voided
        claim's payable lines have their `deductible_applied_cents` sums
        subtracted from `deductible_met_cents` and their `plan_pay_cents`
        sums subtracted from `annual_max_used_cents`, and the accumulator's
        `version` increments."

        Design: Difficulty/compensating_invariant/void_of_second_claim_restores_deductible_to_first_claims_level
        """
        stack = self._ci2_stack(client)
        paid_1 = self._file_and_pay(
            client, stack, "2026-02-01T00:00:00Z", "2026-02-02T00:00:00Z", "19"
        )
        paid_2 = self._file_and_pay(
            client, stack, "2026-03-01T00:00:00Z", "2026-03-02T00:00:00Z", "20"
        )

        void_claim(client, paid_2["id"], paid_2["version"])

        reread_1 = read_claim(client, paid_1["id"])
        assert reread_1["status"] == CLAIM_PAID, (
            "voiding claim 2 does not disturb claim 1"
        )
