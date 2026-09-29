"""Pooling is priced inside the request that changes the membership.

There is no settling period anywhere in this workflow: the response to the write
that pools a second mailer's job must already carry the deeper tier, the lower
rate and the re-split allocation, and the allocation of the member that was
already in the pool must have moved in that same request. A read taken straight
afterwards must agree with it to the cent, and the member jobs' own ledgers must
still be untouched, because pooling never attributes postage to a job.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_ledger,
    assert_batch_pricing,
    assert_member_allocation,
    assert_row_count,
    assert_sum_of_cents,
    find_by_id,
)
from test_helpers.test_users import POSTAGE_MANAGER, PRESORT_OPERATOR

SOLO_TIER = "BASIC"
SOLO_RATE_MILLS = 28556
SOLO_POSTAGE_CENTS = 34267
SOLO_SHARE_PCT = 100.0000


def _pool(api, batch_id, mail_job_id):
    return validate_success(
        api.add_batch_member(batch_id, f.batch_member_payload(mail_job_id), PRESORT_OPERATOR),
        expected_status=201,
    )


class TestPoolingRepricesTheWholePoolInOneRequest:
    """Two adds, and the second one has to move the first member's money."""

    def test_the_first_pooling_prices_the_pool_it_has_just_created(self, api):
        """One member owns the whole pool, so it owns the whole postage.

        "Every change of membership immediately re-derives the batch's price, in a
        pinned three-stage order: first the tier, then the rate and batch postage, then
        the per-member allocation." At 1200 pieces the pool is still shallow: "failing
        that, a pool of at least 500 pieces qualifies `BASIC`". "While the batch is
        `OPEN`, this three-stage derivation writes each member's `share_basis_pct` and
        `allocated_postage_cents` from the batch's current `batch_postage_cents`."

        Design: Corner/consistency_model/immediate_pooling_response_already_shows_the_recomputed_ledger
        """
        world = fx.build_unpooled_world(api)

        member_a = _pool(api, world.batch_id, world.job_a_id)
        assert_member_allocation(
            member_a,
            contributed_piece_count=fx.JOB_A_ACCEPTED,
            share_basis_pct=SOLO_SHARE_PCT,
            allocated_postage_cents=SOLO_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_batch_pricing(
            batch,
            status="OPEN",
            achieved_tier=SOLO_TIER,
            rate_mills=SOLO_RATE_MILLS,
            postage_cents=SOLO_POSTAGE_CENTS,
        )
        assert_batch_ledger(
            batch,
            member_job_count=1,
            total_piece_count=fx.JOB_A_ACCEPTED,
            container_count=0,
        )

    def test_the_second_poolings_own_response_already_holds_the_deeper_tier(self, api):
        """The 201 that adds the second member is already priced at THREE_DIGIT.

        "Every change of membership immediately re-derives the batch's price, in a
        pinned three-stage order: first the tier, then the rate and batch postage, then
        the per-member allocation." The pooled volume crosses a threshold: "failing
        that, a pool of at least 3000 pieces qualifies `THREE_DIGIT`". The member's own
        share is recorded to four places: "Each member's `share_basis_pct` is
        separately recorded as its `contributed_piece_count` multiplied by one hundred
        and divided by the denominator, rounded half up to four decimal places."

        Design: Corner/consistency_model/immediate_pooling_response_already_shows_the_recomputed_ledger
        """
        world = fx.build_unpooled_world(api)

        _pool(api, world.batch_id, world.job_a_id)
        member_b = _pool(api, world.batch_id, world.job_b_id)

        assert_member_allocation(
            member_b,
            contributed_piece_count=fx.JOB_B_ACCEPTED,
            share_basis_pct=fx.MEMBER_B_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_B_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )

    def test_the_member_already_in_the_pool_is_re_allocated_in_the_same_cycle(self, api):
        """The first member's 34267 becomes 31660 without anyone writing to it.

        "Having priced the pool as a whole, the bureau must split it among the mailers
        who contributed to it, and the split must add up exactly." The split runs over
        the whole membership, not merely the row just inserted: "The allocation runs
        over the batch's currently attached members, with the denominator being the sum
        of their `contributed_piece_count` — which is exactly the batch's
        `total_piece_count`". "The invariant is absolute: the allocated amounts sum to
        the pool exactly, for every pool and every member set."

        Design: Corner/consistency_model/immediate_pooling_response_already_shows_the_recomputed_ledger
        """
        world = fx.build_unpooled_world(api)

        member_a = _pool(api, world.batch_id, world.job_a_id)
        assert member_a["allocated_postage_cents"] == SOLO_POSTAGE_CENTS
        member_b = _pool(api, world.batch_id, world.job_b_id)

        members, meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        assert_row_count(members, 2, "batch members")
        assert meta["total_count"] == 2

        re_allocated = find_by_id(members, member_a["id"])
        assert_member_allocation(
            re_allocated,
            contributed_piece_count=fx.JOB_A_ACCEPTED,
            share_basis_pct=fx.MEMBER_A_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            allocated_adjustment_cents=0,
        )
        assert re_allocated["allocated_postage_cents"] != SOLO_POSTAGE_CENTS, (
            "the member already in the pool must be re-priced by the second add"
        )
        still_b = find_by_id(members, member_b["id"])
        assert still_b["allocated_postage_cents"] == fx.MEMBER_B_POSTAGE_CENTS

    def test_the_batch_read_taken_next_agrees_to_the_cent(self, api):
        """No re-read delay: the pool, the rate and the two shares reconcile at once.

        "The batch's `rate_mills_per_piece` is then derived as follows: take the base
        rate in cents for the batch's mail class and multiply it by one thousand to
        express it in mills; multiply that by the tier factor, which is ten thousand
        less the tier's discount in basis points; multiply that product by the entry
        factor, which is ten thousand less the facility's `drop_ship_discount_bp`;
        divide the whole result by one hundred million; and take the floor of that
        single quotient." "The invariant is absolute: the allocated amounts sum to the
        pool exactly, for every pool and every member set."

        Design: Corner/consistency_model/immediate_pooling_response_already_shows_the_recomputed_ledger
        """
        world = fx.build_unpooled_world(api)

        _pool(api, world.batch_id, world.job_a_id)
        _pool(api, world.batch_id, world.job_b_id)

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
        assert_batch_ledger(
            batch,
            member_job_count=2,
            total_piece_count=fx.POOLED_PIECES,
            container_count=0,
        )
        assert_sum_of_cents(
            [fx.MEMBER_A_POSTAGE_CENTS, fx.MEMBER_B_POSTAGE_CENTS],
            batch["batch_postage_cents"],
            what="the two member allocations",
        )

    def test_pooling_leaves_both_member_jobs_ledgers_at_zero(self, api):
        """Postage is allocated on the membership row, never on the job.

        "While the batch is `OPEN`, this three-stage derivation writes each member's
        `share_basis_pct` and `allocated_postage_cents` from the batch's current
        `batch_postage_cents`. It does **not** write any member job's
        `postage_due_cents` — postage is not attributed to a job until an acceptance
        clerk accepts the statement covering it."

        Design: Corner/consistency_model/immediate_pooling_response_already_shows_the_recomputed_ledger
        """
        world = fx.build_unpooled_world(api)

        _pool(api, world.batch_id, world.job_a_id)
        _pool(api, world.batch_id, world.job_b_id)

        job_a = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        job_b = validate_success(api.get_mail_job(world.job_b_id, POSTAGE_MANAGER))
        assert job_a["status"] == "POOLED"
        assert job_b["status"] == "POOLED"
        assert job_a["postage_due_cents"] == 0
        assert job_b["postage_due_cents"] == 0
        assert job_a["commingle_batch_id"] == world.batch_id
        assert job_b["commingle_batch_id"] == world.batch_id
