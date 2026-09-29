"""Actions run forward and then undone, with the totals checked either side.

Two ledgers in this contract must survive being written and unwritten: a permit
account's total funds across a filing and its void, and a batch's piece ledger
across pooling a member, withdrawing it and pooling it again. Both are checked
here at every step and then proved downstream in money, because a ledger that
drifts by a single piece changes the tier the pool achieves.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_cents,
    assert_field_values,
    assert_funds_conserved,
    assert_job_state,
    assert_member_allocation,
    assert_no_content,
    assert_permit_funds,
    find_by_id,
)
from test_helpers.test_users import POSTAGE_MANAGER, PRESORT_OPERATOR

VOID_REASON = "client pulled the job from the drop"


class TestPermitFundsConservationOnSubmitThenVoid:
    """Two hundred thousand cents through a filing and back again."""

    def test_the_filing_moved_the_funds_without_changing_the_total(self, api):
        """The transfer is internal to the account.

        "For any `PermitAccount`, the sum of `balance_cents` and `reserved_cents`
        changes only when money genuinely enters or leaves the account: it grows by
        `amount_cents` on a funding deposit, and it shrinks only when postage is actually
        consumed by an accepted statement."

        Design: Difficulty/compensating_invariant/permit_funds_conservation_on_submit_then_void
        """
        world = fx.build_submitted_world(api)

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit,
            balance_cents=fx.HOUSE_FUNDING_CENTS - fx.POOLED_POSTAGE_CENTS,
            reserved_cents=fx.POOLED_POSTAGE_CENTS,
        )
        assert_funds_conserved(permit, fx.HOUSE_FUNDING_CENTS)

    def test_voiding_a_submitted_statement_restores_the_account_exactly(self, api):
        """The void is the compensating action for the filing.

        "Voiding from `SUBMITTED` is the compensating action for filing:
        `declared_postage_cents` is subtracted from the account's `reserved_cents` and
        added back to its `balance_cents`, preserving the account's total funds".

        Design: Difficulty/compensating_invariant/permit_funds_conservation_on_submit_then_void
        """
        world = fx.build_submitted_world(api)

        validate_success(
            api.void_postage_statement(
                world.statement_id, f.void_payload(VOID_REASON), POSTAGE_MANAGER
            )
        )

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=fx.HOUSE_FUNDING_CENTS, reserved_cents=0
        )
        assert_funds_conserved(permit, fx.HOUSE_FUNDING_CENTS)

    def test_the_voided_statement_keeps_its_declared_figure_and_its_reason(self, api):
        """A void is a terminal record, not an erasure.

        "A `PostageManager` may void a statement with a required `reason`, which is
        stamped into `void_reason`, and the statement moves to `VOID` from either `DRAFT`
        or `SUBMITTED`." "`VOID`, `ACCEPTED_CLEAN` and `ACCEPTED_WITH_ADJUSTMENT` are all
        terminal for a statement."

        Design: Difficulty/compensating_invariant/permit_funds_conservation_on_submit_then_void
        """
        world = fx.build_submitted_world(api)

        statement = validate_success(
            api.void_postage_statement(
                world.statement_id, f.void_payload(VOID_REASON), POSTAGE_MANAGER
            )
        )
        assert_field_values(
            statement,
            {
                "status": "VOID",
                "void_reason": VOID_REASON,
                "adjustment_cents": 0,
            },
        )
        assert_cents(statement, "declared_postage_cents", fx.POOLED_POSTAGE_CENTS)

    def test_the_void_returns_the_batch_to_sorted_with_its_pricing_intact(self, api):
        """The sortation was never in question.

        "the batch is returned `DOCUMENTED → SORTED` so that a replacement statement can
        be prepared against the same sortation. That return deliberately leaves
        `achieved_tier`, `rate_mills_per_piece`, `batch_postage_cents` and every batch
        member allocation intact — the sortation itself was never in question."

        Design: Difficulty/compensating_invariant/permit_funds_conservation_on_submit_then_void
        """
        world = fx.build_submitted_world(api)
        validate_success(
            api.void_postage_statement(
                world.statement_id, f.void_payload(VOID_REASON), POSTAGE_MANAGER
            )
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_batch_pricing(
            batch,
            status="SORTED",
            achieved_tier=fx.POOLED_TIER,
            rate_mills=fx.POOLED_RATE_MILLS,
            postage_cents=fx.POOLED_POSTAGE_CENTS,
        )

    def test_the_member_allocations_and_the_floor_are_not_unwound_by_a_void(self, api):
        """A void compensates money and batch state only.

        The allocations survive, unlike the returning verification which "deliberately
        leaves `achieved_tier`, `rate_mills_per_piece`, `batch_postage_cents` and every
        batch member allocation intact". Sortation's own effects stand: "Every member job
        moves `POOLED → PRESORTED`" and "Every container of the batch moves
        `STAGED → DOCUMENTED` and receives its `placard_id`".

        Design: Difficulty/compensating_invariant/permit_funds_conservation_on_submit_then_void
        """
        world = fx.build_submitted_world(api)
        validate_success(
            api.void_postage_statement(
                world.statement_id, f.void_payload(VOID_REASON), POSTAGE_MANAGER
            )
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

        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        assert_job_state(job_a, "PRESORTED")
        container = validate_success(
            api.get_sort_container(world.container_1_id, PRESORT_OPERATOR)
        )
        assert container["status"] == "DOCUMENTED"


def _add_member_b(api, world):
    """Pool the 1800-piece job into the batch and return the new member row."""
    return validate_success(
        api.add_batch_member(
            world.batch_id, f.batch_member_payload(world.job_b_id), PRESORT_OPERATOR
        ),
        expected_status=201,
    )


class TestBatchPieceLedgerConservationOnMemberAddThenRemove:
    """Eighteen hundred pieces in, out, and in again."""

    def test_the_ledger_equals_the_sum_of_its_attached_members(self, api):
        """The batch's counters are a view of its member rows.

        "For any `CommingleBatch`, `total_piece_count` always equals the sum of
        `contributed_piece_count` over the batch's currently attached `BatchMember` rows,
        and `member_job_count` always equals the number of those rows."

        Design: Difficulty/compensating_invariant/batch_piece_ledger_conservation_on_member_add_then_remove
        """
        world = fx.build_member_a_only_world(api)

        member_b = _add_member_b(api, world)
        assert member_b["contributed_piece_count"] == fx.JOB_B_ACCEPTED

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, PRESORT_OPERATOR)
        )
        assert batch["total_piece_count"] == sum(
            member["contributed_piece_count"] for member in members
        )
        assert_field_values(
            batch, {"total_piece_count": fx.POOLED_PIECES, "member_job_count": 2}
        )

    def test_withdrawal_subtracts_the_contribution_not_the_declaration(self, api):
        """The member's snapshot is what leaves the ledger.

        "The batch's `total_piece_count` decreases by exactly the
        `contributed_piece_count` the member had contributed and `member_job_count`
        decreases by one, restoring the batch piece ledger."

        Design: Difficulty/compensating_invariant/batch_piece_ledger_conservation_on_member_add_then_remove
        """
        world = fx.build_member_a_only_world(api)
        member_b = _add_member_b(api, world)

        assert_no_content(
            api.remove_batch_member(world.batch_id, member_b["id"], PRESORT_OPERATOR)
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        # 3000 less the member's contributed 1800 is 1200; less the job's declared 1850
        # would be 1150.
        assert_field_values(
            batch, {"total_piece_count": fx.JOB_A_ACCEPTED, "member_job_count": 1}
        )
        members, meta = validate_paginated(
            api.list_batch_members(world.batch_id, PRESORT_OPERATOR)
        )
        assert meta["total_count"] == 1
        assert [member["id"] for member in members] == [world.member_a_id]

    def test_the_withdrawn_job_is_poolable_again(self, api):
        """Withdrawal returns the job to the state pooling took it from.

        "The batch member row is deleted, the job moves `POOLED → HYGIENE_CLEARED`, its
        `commingle_batch_id` is cleared back to null and its `postage_due_cents` is reset
        to 0."

        Design: Difficulty/compensating_invariant/batch_piece_ledger_conservation_on_member_add_then_remove
        """
        world = fx.build_member_a_only_world(api)
        member_b = _add_member_b(api, world)
        assert_no_content(
            api.remove_batch_member(world.batch_id, member_b["id"], PRESORT_OPERATOR)
        )

        job_b = validate_success(api.get_mail_job(world.job_b_id, PRESORT_OPERATOR))
        assert_job_state(
            job_b,
            "HYGIENE_CLEARED",
            accepted_piece_count=fx.JOB_B_ACCEPTED,
            postage_due_cents=0,
            commingle_batch_id=None,
        )

    def test_re_pooling_the_same_job_creates_a_second_member_row(self, api):
        """The junction row is per pooling, not per job.

        "A successful pooling creates a **batch member** — the junction row that makes
        the job-to-batch relationship many-to-many over time". "At most one non-withdrawn
        batch member exists per job at any time."

        Design: Difficulty/compensating_invariant/batch_piece_ledger_conservation_on_member_add_then_remove
        """
        world = fx.build_member_a_only_world(api)
        first = _add_member_b(api, world)
        assert_no_content(
            api.remove_batch_member(world.batch_id, first["id"], PRESORT_OPERATOR)
        )

        second = _add_member_b(api, world)
        assert second["id"] != first["id"], "a withdrawn member row is not revived"
        assert second["contributed_piece_count"] == fx.JOB_B_ACCEPTED

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_field_values(
            batch, {"total_piece_count": fx.POOLED_PIECES, "member_job_count": 2}
        )
        job_b = validate_success(api.get_mail_job(world.job_b_id, PRESORT_OPERATOR))
        assert_job_state(job_b, "POOLED", commingle_batch_id=world.batch_id)

    def test_the_restored_ledger_prices_the_pool_at_the_deeper_tier(self, api):
        """A drifted ledger would be visible in the tier and the rate.

        "The comparisons are inclusive at every step, so exactly 3000 pieces qualifies
        `THREE_DIGIT` while 2999 pieces qualifies only `BASIC`." "The piece count used is
        the batch's `total_piece_count`, that is the sum of `contributed_piece_count` over
        the batch's *currently attached* members; a member that has been withdrawn
        contributes nothing."

        Design: Difficulty/compensating_invariant/batch_piece_ledger_conservation_on_member_add_then_remove
        """
        world = fx.build_member_a_only_world(api)
        first = _add_member_b(api, world)
        assert_no_content(
            api.remove_batch_member(world.batch_id, first["id"], PRESORT_OPERATOR)
        )
        second = _add_member_b(api, world)

        for zip3, level, pieces in (
            (fx.CONTAINER_1_ZIP3, "FIVE_DIGIT", fx.CONTAINER_1_PIECES),
            (fx.CONTAINER_2_ZIP3, "THREE_DIGIT", fx.CONTAINER_2_PIECES),
        ):
            validate_success(
                api.add_sort_container(
                    world.batch_id,
                    f.sort_container_payload("TRAY", zip3, level, pieces),
                    PRESORT_OPERATOR,
                ),
                expected_status=201,
            )

        batch = validate_success(api.sort_batch(world.batch_id, PRESORT_OPERATOR))
        assert_batch_pricing(
            batch,
            status="SORTED",
            achieved_tier=fx.POOLED_TIER,
            rate_mills=fx.POOLED_RATE_MILLS,
            postage_cents=fx.POOLED_POSTAGE_CENTS,
        )

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, PRESORT_OPERATOR)
        )
        assert_member_allocation(
            find_by_id(members, world.member_a_id),
            contributed_piece_count=fx.JOB_A_ACCEPTED,
            share_basis_pct=fx.MEMBER_A_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )
        assert_member_allocation(
            find_by_id(members, second["id"]),
            contributed_piece_count=fx.JOB_B_ACCEPTED,
            share_basis_pct=fx.MEMBER_B_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_B_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )
