"""Lifecycles that loop rather than run forward.

A mail job can reach `POOLED` twice, once by being pooled and once by being
revised back into it, and a single postage statement can leave `SUBMITTED` twice
by two different exits. Both cycles are driven here end to end on one statement
id, because a forward-only state machine passes the first leg and fails the
second.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_cents,
    assert_container_state,
    assert_field_values,
    assert_job_state,
    assert_member_allocation,
    assert_permit_funds,
    assert_statement_figures,
    find_by_id,
)
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    ACCEPTANCE_CLERK_USER_ID,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)


def _return_the_statement(api, world, finding_type="CONTAINER_NOT_QUALIFIED", pieces=120):
    """Raise one finding and close verification with a return."""
    api.create_finding(
        world.statement_id, f.finding_payload(finding_type, pieces), ACCEPTANCE_CLERK
    )
    return validate_success(
        api.verify_postage_statement(
            world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
        )
    )


class TestMailJobPresortReworkCycle:
    """POOLED to PRESORTED to REWORK and back to POOLED on one job."""

    def test_a_returning_verification_drives_the_batch_and_jobs_into_rework(self, api):
        """The unwind is what makes the cycle possible.

        "Link 2: the batch moves `DOCUMENTED → REWORK`, and its `achieved_tier` is
        reset to `NONE`, its `rate_mills_per_piece` to 0 and its
        `batch_postage_cents` to 0, with its `version` incremented." "every member job
        moves `PRESORTED → REWORK`, has its `rework_count` incremented by one and its
        `postage_due_cents` reset to 0, and has its `version` incremented".

        Design: Difficulty/non_linear_state_machine/mail_job_presort_rework_cycle
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world)

        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        assert_job_state(job_a, "REWORK", rework_count=1, postage_due_cents=0)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_batch_pricing(
            batch, status="REWORK", achieved_tier="NONE", rate_mills=0, postage_cents=0
        )

    def test_revising_closes_the_cycle_back_onto_pooled(self, api):
        """Each job re-enters a state it already occupied once.

        "That same move drives every member job `REWORK → POOLED` and every container
        `RETURNED → STAGED`, clearing each container's `placard_id` back to null, with
        a `version` increment on the batch, on each job and on each container."

        Design: Difficulty/non_linear_state_machine/mail_job_presort_rework_cycle
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world)
        validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )

        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        job_b = validate_success(api.get_mail_job(world.job_b_id, PRESORT_OPERATOR))
        # The rework count is history and is not cleared by the return to POOLED.
        assert_job_state(
            job_a, "POOLED", rework_count=1, commingle_batch_id=world.batch_id
        )
        assert_job_state(
            job_b, "POOLED", rework_count=1, commingle_batch_id=world.batch_id
        )

    def test_revising_rebuilds_the_batch_price_from_the_surviving_members(self, api):
        """The reset values are re-derived, not left stale.

        "In the same operation the batch is driven `REWORK → OPEN`, which re-runs the
        full three-stage derivation of §3.4 over the surviving members — recomputing
        `achieved_tier`, then `rate_mills_per_piece` and `batch_postage_cents`, then
        every member's `share_basis_pct` and `allocated_postage_cents` — restoring the
        values the batch held before it was unwound."

        Design: Difficulty/non_linear_state_machine/mail_job_presort_rework_cycle
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world)
        validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_batch_pricing(
            batch,
            status="OPEN",
            achieved_tier=fx.POOLED_TIER,
            rate_mills=fx.POOLED_RATE_MILLS,
            postage_cents=fx.POOLED_POSTAGE_CENTS,
        )

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        assert_member_allocation(
            find_by_id(members, world.member_a_id),
            contributed_piece_count=fx.JOB_A_ACCEPTED,
            share_basis_pct=fx.MEMBER_A_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )
        assert_member_allocation(
            find_by_id(members, world.member_b_id),
            contributed_piece_count=fx.JOB_B_ACCEPTED,
            share_basis_pct=fx.MEMBER_B_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_B_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )

    def test_revising_restages_the_containers_and_clears_their_placards(self, api):
        """A re-staged tray carries no documentation until it is sorted again.

        "The container's `placard_id` starts null — documentation placards are stamped
        only at sortation — and its `status` starts at `STAGED`."

        Design: Difficulty/non_linear_state_machine/mail_job_presort_rework_cycle
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world)
        validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )

        containers, _meta = validate_paginated(
            api.list_batch_containers(world.batch_id, PRESORT_OPERATOR)
        )
        for container in containers:
            assert_container_state(
                container, status="STAGED", qualifies=True, placard_id=None
            )

    def test_revising_reopens_the_statement_and_keeps_the_findings(self, api):
        """The statement re-freezes and its history survives.

        "The statement's `revision_index` increments by one, and its
        `adjustment_cents`, `verified_postage_cents` and `verification_error_count` are
        all cleared to 0 while `submitted_by_user_id` and `verified_by_user_id` are
        cleared to null. Findings already recorded are **retained as history and never
        discarded**". "Only **after** the batch has recomputed itself does the
        statement re-freeze: `statement_piece_count` and `rate_mills_per_piece` are
        taken again from the batch's freshly recomputed values and
        `declared_postage_cents` is recomputed from them."

        Design: Difficulty/non_linear_state_machine/mail_job_presort_rework_cycle
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world)
        statement = validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )

        assert_statement_figures(
            statement,
            status="DRAFT",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=0,
            revision_index=1,
        )
        assert_field_values(
            statement,
            {
                "submitted_by_user_id": None,
                "verified_by_user_id": None,
                "statement_piece_count": fx.POOLED_PIECES,
                "rate_mills_per_piece": fx.POOLED_RATE_MILLS,
            },
        )

        findings, meta = validate_paginated(
            api.list_findings(world.statement_id, POSTAGE_MANAGER)
        )
        assert meta["total_count"] == 1, "a revision keeps the findings as history"
        assert len(findings) == 1

    def test_the_reservation_released_by_the_return_is_not_re_taken(self, api):
        """Nothing is encumbered while the mailing is back on the floor.

        "Link 1: `declared_postage_cents` is subtracted from the account's
        `reserved_cents` and added back to its `balance_cents`, so the account's total
        funds are unchanged and the encumbrance is released."

        Design: Difficulty/non_linear_state_machine/mail_job_presort_rework_cycle
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world)
        validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=fx.HOUSE_FUNDING_CENTS, reserved_cents=0
        )


class TestPostageStatementBranchingFork:
    """One statement id leaving SUBMITTED twice, by two different exits."""

    def test_the_return_fork_records_no_adjustment_and_releases_the_funds(self, api):
        """A return is not an acceptance with a zero surcharge.

        "When the outcome is `RETURN`, the statement moves `SUBMITTED →
        RETURNED_FOR_CORRECTION`, and this is only permitted when at least one finding
        has been recorded during the current filing episode". "The statement's
        `adjustment_cents` and `verified_postage_cents` are left at 0."

        Design: Difficulty/non_linear_state_machine/postage_statement_branching_fork
        """
        world = fx.build_submitted_world(api)

        statement = _return_the_statement(api, world, "SHORT_PAID", 60)
        assert_statement_figures(
            statement,
            status="RETURNED_FOR_CORRECTION",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=1,
        )

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=fx.HOUSE_FUNDING_CENTS, reserved_cents=0
        )

    def test_the_same_statement_takes_the_clean_fork_on_its_second_pass(self, api):
        """The second exit from SUBMITTED lands somewhere else entirely.

        "When the outcome is `ACCEPT` and the pinned walk resolves `adjustment_cents`
        to exactly 0, the statement moves `SUBMITTED → ACCEPTED_CLEAN`. Its
        `adjustment_cents` is set to 0 and its `verified_postage_cents` to its
        `declared_postage_cents`." The earlier finding cannot reach this episode:
        "because `verification_error_count` returns to 0, those historical findings are
        excluded from the pinned walk of any later filing episode, which considers only
        findings recorded after the revision."

        Design: Difficulty/non_linear_state_machine/postage_statement_branching_fork
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world, "SHORT_PAID", 60)
        validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        validate_success(api.sort_batch(world.batch_id, PRESORT_OPERATOR))
        validate_success(
            api.submit_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )

        statement = validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("ACCEPT"), ACCEPTANCE_CLERK
            )
        )
        assert_statement_figures(
            statement,
            status="ACCEPTED_CLEAN",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=fx.POOLED_POSTAGE_CENTS,
            verification_error_count=0,
            revision_index=1,
        )
        assert_field_values(
            statement, {"verified_by_user_id": ACCEPTANCE_CLERK_USER_ID}
        )

    def test_the_clean_acceptance_consumes_the_reservation_once(self, api):
        """Round two spends the money round one had released.

        "The reservation is consumed rather than returned: `declared_postage_cents` is
        subtracted from the account's `reserved_cents` and is not added back to
        `balance_cents`, which is the one moment postage genuinely leaves the account."

        Design: Difficulty/non_linear_state_machine/postage_statement_branching_fork
        """
        world = fx.build_submitted_world(api)
        _return_the_statement(api, world, "SHORT_PAID", 60)
        validate_success(
            api.revise_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        validate_success(api.sort_batch(world.batch_id, PRESORT_OPERATOR))
        validate_success(
            api.submit_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("ACCEPT"), ACCEPTANCE_CLERK
            )
        )

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit,
            balance_cents=fx.HOUSE_FUNDING_CENTS - fx.POOLED_POSTAGE_CENTS,
            reserved_cents=0,
        )
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "DOCUMENTED"
        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        assert_job_state(job_a, "PRESORTED", rework_count=1)
        assert_cents(job_a, "postage_due_cents", fx.MEMBER_A_POSTAGE_CENTS)
