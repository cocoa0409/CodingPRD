"""
Everything a write does is visible the moment it answers.

There is no settlement pass, no queue and no retry loop anywhere in this contract: the money
a reservation encumbers is already in the creation response, and a read issued immediately
afterwards already shows the pool short by exactly that amount.
"""

from test_helpers import (
    REBATE_ADMIN_HEADERS,
    ClaimStatus,
    assert_cents,
    assert_ledger_conserved,
    assert_program_ledger,
    assert_quantity,
    factories,
    fixtures,
    validate_success,
)


class TestTheEncumbranceIsVisibleImmediately:
    """One reservation, and no waiting anywhere: the response body is already correct."""

    def test_the_creation_response_and_the_very_next_read_both_show_the_hold(self, api):
        """Four hundred and twenty-three thousand cents, in the 201 body and in the pool at once.

        The reservation's own response already carries the computed award and the reserved
        standing — nothing here is filled in later by a second pass. A program read issued
        straight afterwards, with no delay and no retry, already shows that exact sum held and
        the unencumbered balance reduced by it, with the immutable total still equal to the sum
        of the three buckets. The bank's version has advanced by exactly the one mutation the
        reservation performed.

        PRD 3.7: "At reservation the results are written as `basis_kwh_reserved`, `stack_ceiling_cents` and `reserved_amount_cents`, and the program pool is then encumbered: if the program's `remaining_budget_cents` is at least the reserved amount — exact equality succeeds — that amount moves out of `remaining_budget_cents` and into `reserved_budget_cents`."
        PRD 2.10: "After every single claim transition the following must hold exactly: `total_budget_cents` equals `remaining_budget_cents` plus `reserved_budget_cents` plus `paid_budget_cents`."
        PRD 4: "An operation that brings a new resource into existence answers with HTTP 201 and the created resource in `data`; that includes the expansion endpoint, which creates a new battery system, and the participation endpoint, which creates a new dispatch performance."
        PRD 2.5: "`version` (integer): a counter that increases by exactly one on every mutation of that resource."

        Design: Corner/consistency_model/claim_creation_reflects_the_program_ledger_within_the_same_request
        """
        project = fixtures.installed_project(api)
        program_id = fixtures.create_state_program(api, project)
        assert_program_ledger(
            fixtures.read_program(api, program_id),
            remaining=5000000,
            reserved=0,
            paid=0,
        )
        held_version = fixtures.system_version(api, project)

        created = validate_success(
            api.create_claim(
                factories.claim_payload(
                    project.battery_system_id, program_id, held_version
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )

        assert created["status"] == ClaimStatus.RESERVED
        assert_quantity(created, "basis_kwh_reserved", 27.0)
        assert_cents(created, "reserved_amount_cents", 423000)

        program = validate_success(
            api.get_program(program_id, headers=REBATE_ADMIN_HEADERS)
        )

        assert_program_ledger(program, remaining=4577000, reserved=423000, paid=0)
        assert_ledger_conserved(program)
        assert fixtures.system_version(api, project) == held_version + 1
