"""Cascades whose later links are caused by their earlier ones.

Two operations in this contract reach four and three links deep. A returning
verification releases money, unwinds a batch, reworks its members and containers,
and finally suspends the mailers whose address files sent the work back twice; a
deposit closes a batch, deposits its containers, opens a service-level record
behind each one, mails the member jobs and grows each client's lifetime volume.
Each link is asserted separately below, because an implementation that stops one
link short still passes the first assertion.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_field_values,
    assert_job_state,
    assert_member_allocation,
    assert_permit_funds,
    find_by_id,
)
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)


def _second_return(api, world):
    """Raise one more finding on the re-submitted statement and return it."""
    api.create_finding(
        world.statement_id, f.finding_payload("SHORT_PAID", 90), ACCEPTANCE_CLERK
    )
    return validate_success(
        api.verify_postage_statement(
            world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
        )
    )


class TestStatementReturnCascadeDepthFour:
    """A second return on the same statement, four links deep."""

    def test_link_one_releases_the_encumbrance_without_spending_it(self, api):
        """The money goes back where it came from.

        "No money leaves the permit account and the entire batch is unwound, in four
        numbered links. Link 1: `declared_postage_cents` is subtracted from the
        account's `reserved_cents` and added back to its `balance_cents`, so the
        account's total funds are unchanged and the encumbrance is released."

        Design: Difficulty/transitive_cascade/statement_return_cascade_depth_four
        """
        world = fx.build_second_cycle_submitted_world(api)

        statement = _second_return(api, world)
        assert statement["status"] == "RETURNED_FOR_CORRECTION"

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(
            permit, balance_cents=fx.HOUSE_FUNDING_CENTS, reserved_cents=0
        )

    def test_link_two_strips_the_batch_of_its_tier_rate_and_postage(self, api):
        """The unwind reaches the batch because the statement returned.

        "Link 2: the batch moves `DOCUMENTED → REWORK`, and its `achieved_tier` is
        reset to `NONE`, its `rate_mills_per_piece` to 0 and its `batch_postage_cents`
        to 0, with its `version` incremented."

        Design: Difficulty/transitive_cascade/statement_return_cascade_depth_four
        """
        world = fx.build_second_cycle_submitted_world(api)
        _second_return(api, world)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert_batch_pricing(
            batch, status="REWORK", achieved_tier="NONE", rate_mills=0, postage_cents=0
        )

    def test_link_three_zeroes_the_members_and_reworks_jobs_and_containers(self, api):
        """The batch's own unwind is what reaches its members.

        "Link 3, caused by link 2: every batch member has its
        `allocated_postage_cents` and `allocated_adjustment_cents` reset to 0 and its
        `share_basis_pct` reset to null; every member job moves `PRESORTED → REWORK`,
        has its `rework_count` incremented by one and its `postage_due_cents` reset to
        0, and has its `version` incremented; and every container of the batch moves
        `DOCUMENTED → RETURNED` with its `version` incremented."

        Design: Difficulty/transitive_cascade/statement_return_cascade_depth_four
        """
        world = fx.build_second_cycle_submitted_world(api)
        _second_return(api, world)

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        assert_member_allocation(
            find_by_id(members, world.member_a_id),
            contributed_piece_count=fx.JOB_A_ACCEPTED,
            share_basis_pct=None,
            allocated_postage_cents=0,
            allocated_adjustment_cents=0,
        )
        assert_member_allocation(
            find_by_id(members, world.member_b_id),
            contributed_piece_count=fx.JOB_B_ACCEPTED,
            share_basis_pct=None,
            allocated_postage_cents=0,
            allocated_adjustment_cents=0,
        )

        # The first cycle already took each job to a rework count of 1.
        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        job_b = validate_success(api.get_mail_job(world.job_b_id, PRESORT_OPERATOR))
        assert_job_state(job_a, "REWORK", rework_count=2, postage_due_cents=0)
        assert_job_state(job_b, "REWORK", rework_count=2, postage_due_cents=0)

        containers, _cmeta = validate_paginated(
            api.list_batch_containers(world.batch_id, PRESORT_OPERATOR)
        )
        assert [container["status"] for container in containers] == [
            "RETURNED",
            "RETURNED",
        ]

    def test_link_four_suspends_every_mailer_that_reached_two_reworks(self, api):
        """Each client is suspended through its own job, not its pool-mate's.

        "Link 4, caused by link 3: for any member job whose `rework_count` has now
        reached 2 or more, that job's client is driven `ACTIVE → SUSPENDED` with
        `suspension_reason` set to the fixed string `REPEATED_PRESORT_REWORK` and its
        `version` incremented".

        Design: Difficulty/transitive_cascade/statement_return_cascade_depth_four
        """
        world = fx.build_second_cycle_submitted_world(api)
        _second_return(api, world)

        for client_id in (world.acme_id, world.bore_id):
            client = validate_success(api.get_client(client_id, BUREAU_ADMIN))
            assert_field_values(
                client,
                {
                    "status": "SUSPENDED",
                    "suspension_reason": "REPEATED_PRESORT_REWORK",
                },
            )

    def test_link_four_does_not_reach_the_client_that_owns_no_member_job(self, api):
        """The account holder is not a mailer in this batch.

        The cascade reaches a client only through a job: "for any member job whose
        `rework_count` has now reached 2 or more, that job's client is driven
        `ACTIVE → SUSPENDED`".

        Design: Difficulty/transitive_cascade/statement_return_cascade_depth_four
        """
        world = fx.build_second_cycle_submitted_world(api)
        _second_return(api, world)

        house = validate_success(api.get_client(world.house_id, BUREAU_ADMIN))
        assert_field_values(house, {"status": "ACTIVE", "suspension_reason": None})

    def test_the_first_return_of_the_cycle_left_both_mailers_trading(self, api):
        """One rework is not two, and the threshold is not retroactive.

        The suspension link fires only "for any member job whose `rework_count` has
        now reached 2 or more".

        Design: Difficulty/transitive_cascade/statement_return_cascade_depth_four
        """
        world = fx.build_submitted_world(api)
        api.create_finding(
            world.statement_id,
            f.finding_payload("CONTAINER_NOT_QUALIFIED", 90),
            ACCEPTANCE_CLERK,
        )
        validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("RETURN"), ACCEPTANCE_CLERK
            )
        )

        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        assert_job_state(job_a, "REWORK", rework_count=1)
        for client_id in (world.acme_id, world.bore_id):
            client = validate_success(api.get_client(client_id, BUREAU_ADMIN))
            assert_field_values(
                client, {"status": "ACTIVE", "suspension_reason": None}
            )


class TestDepositCascadeDepthThree:
    """One deposit, three links, five kinds of resource moved."""

    def test_link_one_closes_the_batch_and_stamps_the_deposit_instant(self, api):
        """The clock, not the caller, decides when the mail was tendered.

        "On success the shipment moves `IN_TRANSIT → DEPOSITED` and its
        `deposited_at_utc` is stamped from the logical clock. Link 1: the batch moves
        `DOCUMENTED → CLOSED`, which is terminal for a batch."

        Design: Difficulty/transitive_cascade/deposit_cascade_depth_three
        """
        world = fx.build_departed_world(api)

        shipment = validate_success(
            api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK)
        )
        assert_field_values(
            shipment,
            {"status": "DEPOSITED", "deposited_at_utc": fx.DEPOSIT_CLOCK_UTC},
        )

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "CLOSED"

    def test_link_two_deposits_every_documented_container(self, api):
        """The containers move because the batch closed.

        "Link 2, caused by link 1: every container of the batch still in `DOCUMENTED`
        moves `DOCUMENTED → DEPOSITED`, which is terminal for a container."

        Design: Difficulty/transitive_cascade/deposit_cascade_depth_three
        """
        world = fx.build_departed_world(api)
        validate_success(api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK))

        for container_id in (world.container_1_id, world.container_2_id):
            container = validate_success(
                api.get_sort_container(container_id, PRESORT_OPERATOR)
            )
            assert container["status"] == "DEPOSITED"

    def test_link_three_opens_exactly_one_unscanned_record_per_container(self, api):
        """Each deposited container gets its own service commitment on file.

        "Link 3, caused by link 2: each newly deposited container opens exactly one
        **service-level record**, created in ascending container `sequence_index`
        order, carrying that container's `sort_container_id`, its `zone`, its
        `committed_days` and its `piece_count`, with its own `deposited_at_utc` set
        from the logical clock and its `actual_delivery_days`, `scanned_at_utc` and
        `on_time` all null."

        Design: Difficulty/transitive_cascade/deposit_cascade_depth_three
        """
        world = fx.build_departed_world(api)
        validate_success(api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK))

        records_1, meta_1 = validate_paginated(
            api.list_container_service_level_records(
                world.container_1_id, ACCEPTANCE_CLERK
            )
        )
        assert meta_1["total_count"] == 1
        assert_field_values(
            records_1[0],
            {
                "sort_container_id": world.container_1_id,
                "zone": 2,
                "committed_days": 4,
                "piece_count": fx.CONTAINER_1_PIECES,
                "deposited_at_utc": fx.DEPOSIT_CLOCK_UTC,
                "actual_delivery_days": None,
                "scanned_at_utc": None,
                "on_time": None,
            },
        )

        records_2, meta_2 = validate_paginated(
            api.list_container_service_level_records(
                world.container_2_id, ACCEPTANCE_CLERK
            )
        )
        assert meta_2["total_count"] == 1
        assert_field_values(
            records_2[0],
            {
                "sort_container_id": world.container_2_id,
                "zone": 8,
                "committed_days": 7,
                "piece_count": fx.CONTAINER_2_PIECES,
                "deposited_at_utc": fx.DEPOSIT_CLOCK_UTC,
                "actual_delivery_days": None,
                "scanned_at_utc": None,
                "on_time": None,
            },
        )

    def test_link_three_mails_every_presorted_member_job(self, api):
        """The jobs are mailed by the batch closing, not by their own transition.

        "Also link 3, caused by link 1: every member job of the batch still in
        `PRESORTED` moves `PRESORTED → MAILED` and has its `mailed_at_utc` stamped
        from the logical clock."

        Design: Difficulty/transitive_cascade/deposit_cascade_depth_three
        """
        world = fx.build_departed_world(api)
        validate_success(api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK))

        for job_id in (world.job_a_id, world.job_b_id):
            job = validate_success(api.get_mail_job(job_id, PRESORT_OPERATOR))
            assert_job_state(job, "MAILED")
            assert_field_values(job, {"mailed_at_utc": fx.DEPOSIT_CLOCK_UTC})

    def test_the_lifetime_counter_grows_by_accepted_not_declared_pieces(self, api):
        """The deepest link counts the mail that actually went, per owner.

        "Link 4, caused by link 3: each newly mailed job's `accepted_piece_count` is
        added to that job's client's `lifetime_pieces_mailed`." That counter "counts
        accepted pieces on the client's jobs that have reached `MAILED`".

        Design: Difficulty/transitive_cascade/deposit_cascade_depth_three
        """
        world = fx.build_departed_world(api)
        validate_success(api.deposit_drop_shipment(world.shipment_id, ACCEPTANCE_CLERK))

        acme = validate_success(api.get_client(world.acme_id, BUREAU_ADMIN))
        bore = validate_success(api.get_client(world.bore_id, BUREAU_ADMIN))
        # 1200 and 1800 accepted, against 1250 and 1850 declared.
        assert acme["lifetime_pieces_mailed"] == fx.JOB_A_ACCEPTED
        assert bore["lifetime_pieces_mailed"] == fx.JOB_B_ACCEPTED

        house = validate_success(api.get_client(world.house_id, BUREAU_ADMIN))
        assert house["lifetime_pieces_mailed"] == 0, (
            "the account holder owns no mail in this batch"
        )
