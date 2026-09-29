"""Operations gated by the state of a resource they never name.

Each pair below runs the identical request twice, changing nothing but the status
of a third resource between the two calls — a permit account, a postage statement,
a batch. The refusal and the success therefore differ in exactly one variable, so
an implementation that ignores the far resource cannot pass both halves.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as e
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_batch_pricing,
    assert_field_values,
    assert_job_state,
    assert_statement_figures,
)
from test_helpers.test_users import (
    ACCEPTANCE_CLERK,
    BUREAU_ADMIN,
    POSTAGE_MANAGER,
    PRESORT_OPERATOR,
)


class TestPoolingRequiresActivePermitAccount:
    """A pool-ready job whose funding account is on hold."""

    def test_pooling_is_refused_while_the_funding_account_is_on_hold(self, api):
        """The account is reached through the job, not through the request.

        "19. **Funding permit active** — the `PermitAccount` funding the operation has
        status `ACTIVE`; both `HOLD` and `CLOSED` refuse. Reached through
        `MailJob.permit_account_id` on job creation, on a hygiene run and on pooling".

        Design: Difficulty/cross_entity_state_dependency/pooling_requires_active_permit_account
        """
        world = fx.build_permit_on_hold_world(api)

        validate_error(
            api.add_batch_member(
                world.batch_id, f.batch_member_payload(world.job_g_id), PRESORT_OPERATOR
            ),
            e.ERR_PERMIT_ACCOUNT_NOT_ACTIVE,
            expected_status=409,
        )

        permit = validate_success(
            api.get_permit_account(world.permit_g_id, POSTAGE_MANAGER)
        )
        assert permit["status"] == "HOLD"

    def test_the_refusal_left_the_job_and_the_batch_untouched(self, api):
        """A refused pooling creates no member and moves no counter.

        "A successful pooling creates a **batch member** — the junction row that makes
        the job-to-batch relationship many-to-many over time".

        Design: Difficulty/cross_entity_state_dependency/pooling_requires_active_permit_account
        """
        world = fx.build_permit_on_hold_world(api)
        validate_error(
            api.add_batch_member(
                world.batch_id, f.batch_member_payload(world.job_g_id), PRESORT_OPERATOR
            ),
            e.ERR_PERMIT_ACCOUNT_NOT_ACTIVE,
        )

        job = validate_success(api.get_mail_job(world.job_g_id, PRESORT_OPERATOR))
        assert_job_state(job, "HYGIENE_CLEARED", commingle_batch_id=None)
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_field_values(batch, {"member_job_count": 0, "total_piece_count": 0})

    def test_reinstating_the_account_makes_the_identical_request_succeed(self, api):
        """Only the far resource's status differed between the two calls.

        "The job's funding permit account must be `ACTIVE`." Once it is, the pooling
        proceeds: "Its `contributed_piece_count` is a snapshot of the job's
        `accepted_piece_count` taken at the instant of pooling and is **never re-read
        afterwards**".

        Design: Difficulty/cross_entity_state_dependency/pooling_requires_active_permit_account
        """
        world = fx.build_permit_on_hold_world(api)
        validate_error(
            api.add_batch_member(
                world.batch_id, f.batch_member_payload(world.job_g_id), PRESORT_OPERATOR
            ),
            e.ERR_PERMIT_ACCOUNT_NOT_ACTIVE,
        )

        validate_success(
            api.set_permit_account_status(
                world.permit_g_id, f.permit_status_payload("ACTIVE"), POSTAGE_MANAGER
            )
        )
        member = validate_success(
            api.add_batch_member(
                world.batch_id, f.batch_member_payload(world.job_g_id), PRESORT_OPERATOR
            ),
            expected_status=201,
        )
        assert member["contributed_piece_count"] == 1200

        job = validate_success(api.get_mail_job(world.job_g_id, PRESORT_OPERATOR))
        assert_job_state(job, "POOLED", commingle_batch_id=world.batch_id)
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, PRESORT_OPERATOR)
        )
        assert_field_values(batch, {"member_job_count": 1, "total_piece_count": 1200})


def _book_and_depart(api, world):
    """Book the canonical two-pallet appointment and put the truck on the road."""
    shipment = validate_success(
        api.create_drop_shipment(
            f.drop_shipment_payload(
                world.batch_id,
                world.facility_id,
                fx.SHIPMENT_WINDOW_START,
                fx.SHIPMENT_WINDOW_END,
                pallet_count=2,
            ),
            PRESORT_OPERATOR,
        ),
        expected_status=201,
    )
    validate_success(api.set_clock(fx.DEPOSIT_CLOCK_UTC, BUREAU_ADMIN))
    validate_success(api.depart_drop_shipment(shipment["id"], PRESORT_OPERATOR))
    return shipment["id"]


class TestDepositRequiresAcceptedPostageStatement:
    """A truck at the dock in front of an unverified statement."""

    def test_the_deposit_is_refused_while_the_statement_is_only_submitted(self, api):
        """The gate reads the batch's statement, not the shipment.

        "21. **Statement accepted before deposit** — the `CommingleBatch` of the
        shipment being deposited has a `PostageStatement` in `ACCEPTED_CLEAN` or
        `ACCEPTED_WITH_ADJUSTMENT`. Violation: `ERR_STATEMENT_NOT_ACCEPTED` (409)."

        Design: Difficulty/cross_entity_state_dependency/deposit_requires_accepted_postage_statement
        """
        world = fx.build_submitted_world(api)
        shipment_id = _book_and_depart(api, world)

        validate_error(
            api.deposit_drop_shipment(shipment_id, ACCEPTANCE_CLERK),
            e.ERR_STATEMENT_NOT_ACCEPTED,
            expected_status=409,
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert statement["status"] == "SUBMITTED"

    def test_the_refused_deposit_started_no_part_of_the_cascade(self, api):
        """The deposit cascade is all or nothing.

        "On success the shipment moves `IN_TRANSIT → DEPOSITED` and its
        `deposited_at_utc` is stamped from the logical clock. Link 1: the batch moves
        `DOCUMENTED → CLOSED`, which is terminal for a batch."

        Design: Difficulty/cross_entity_state_dependency/deposit_requires_accepted_postage_statement
        """
        world = fx.build_submitted_world(api)
        shipment_id = _book_and_depart(api, world)
        validate_error(
            api.deposit_drop_shipment(shipment_id, ACCEPTANCE_CLERK),
            e.ERR_STATEMENT_NOT_ACCEPTED,
        )

        shipment = validate_success(
            api.get_drop_shipment(shipment_id, PRESORT_OPERATOR)
        )
        assert_field_values(
            shipment, {"status": "IN_TRANSIT", "deposited_at_utc": None}
        )
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "DOCUMENTED"

        for container_id in (world.container_1_id, world.container_2_id):
            _records, meta = validate_paginated(
                api.list_container_service_level_records(
                    container_id, ACCEPTANCE_CLERK
                )
            )
            assert meta["total_count"] == 0

    def test_accepting_the_statement_makes_the_identical_deposit_succeed(self, api):
        """The clock and the window were the same on both attempts.

        Deposit requires "the logical clock must lie inside the appointment window
        treated as a closed interval, at or after `window_start_utc` and at or before
        `window_end_utc`, otherwise `ERR_OUTSIDE_APPOINTMENT_WINDOW`" — unchanged here —
        and the batch "must have a statement in `ACCEPTED_CLEAN` or
        `ACCEPTED_WITH_ADJUSTMENT`", which is the one thing that changed.

        Design: Difficulty/cross_entity_state_dependency/deposit_requires_accepted_postage_statement
        """
        world = fx.build_submitted_world(api)
        shipment_id = _book_and_depart(api, world)
        validate_error(
            api.deposit_drop_shipment(shipment_id, ACCEPTANCE_CLERK),
            e.ERR_STATEMENT_NOT_ACCEPTED,
        )

        statement = validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("ACCEPT"), ACCEPTANCE_CLERK
            )
        )
        assert_field_values(
            statement, {"status": "ACCEPTED_CLEAN", "adjustment_cents": 0}
        )

        shipment = validate_success(
            api.deposit_drop_shipment(shipment_id, ACCEPTANCE_CLERK)
        )
        assert shipment["status"] == "DEPOSITED"

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "CLOSED"
        for job_id in (world.job_a_id, world.job_b_id):
            job = validate_success(api.get_mail_job(job_id, PRESORT_OPERATOR))
            assert_job_state(job, "MAILED")
        for container_id in (world.container_1_id, world.container_2_id):
            _records, meta = validate_paginated(
                api.list_container_service_level_records(
                    container_id, ACCEPTANCE_CLERK
                )
            )
            assert meta["total_count"] == 1


class TestStatementPreparationRequiresSortedBatch:
    """A correct concurrency token on a batch that is not yet priced."""

    def test_preparation_is_refused_on_an_unsorted_batch(self, api):
        """The batch's state answers, not the version token.

        "A `PostageManager` prepares one against a `commingle_batch_id` naming a batch
        in `SORTED`". "A statement prepared against a batch in any status other than
        `SORTED` is refused with `ERR_INVALID_BATCH_STATE`."

        Design: Difficulty/cross_entity_state_dependency/statement_submit_requires_sorted_batch
        """
        world = fx.build_open_funded_world(api)

        validate_error(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_house_id, world.batch_v_open
                ),
                POSTAGE_MANAGER,
            ),
            e.ERR_INVALID_BATCH_STATE,
            expected_status=409,
        )

    def test_the_concurrency_token_quoted_was_the_correct_one(self, api):
        """The stale-version rung is not what refused this request.

        "17. **Batch optimistic concurrency** — `expected_batch_version` equals the
        batch's current `version`. Violation: `ERR_STALE_BATCH_VERSION` (412). Applies to
        `POST /postage-statements`."

        Design: Difficulty/cross_entity_state_dependency/statement_submit_requires_sorted_batch
        """
        world = fx.build_open_funded_world(api)

        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["version"] == world.batch_v_open, (
            "the version quoted in the refused filing is the batch's current one"
        )
        # Membership has already priced the pool provisionally — "Every change of
        # membership immediately re-derives the batch's price" — so the refusal cannot be
        # blamed on missing figures either. Only the batch's status is out of place.
        assert_batch_pricing(
            batch,
            status="OPEN",
            achieved_tier=fx.POOLED_TIER,
            rate_mills=fx.POOLED_RATE_MILLS,
            postage_cents=fx.POOLED_POSTAGE_CENTS,
        )

    def test_no_statement_row_survives_the_refusal(self, api):
        """A refused preparation is not a draft.

        "The statement opens in `DRAFT` with `adjustment_cents`,
        `verified_postage_cents`, `verification_error_count` and `revision_index` all at
        0" — and only on success.

        Design: Difficulty/cross_entity_state_dependency/statement_submit_requires_sorted_batch
        """
        world = fx.build_open_funded_world(api)
        validate_error(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_house_id, world.batch_v_open
                ),
                POSTAGE_MANAGER,
            ),
            e.ERR_INVALID_BATCH_STATE,
        )

        statements, meta = validate_paginated(
            api.list_batch_postage_statements(world.batch_id, POSTAGE_MANAGER)
        )
        assert statements == [] and meta["total_count"] == 0
        batch = validate_success(
            api.get_commingle_batch(world.batch_id, POSTAGE_MANAGER)
        )
        assert batch["status"] == "OPEN"

    def test_sorting_the_batch_makes_the_same_filing_succeed(self, api):
        """Only the batch's state changed between the two filings.

        Sortation is what freezes the figures the statement then copies: "`achieved_tier`
        is fixed from the pooled volume, `rate_mills_per_piece` and `batch_postage_cents`
        are fixed from that tier". Preparation copies them: "The statement's
        `statement_piece_count` is frozen from the batch's `total_piece_count`, its
        `rate_mills_per_piece` is frozen from the batch's `rate_mills_per_piece`, and its
        `declared_postage_cents` is set from the batch's `batch_postage_cents`."

        Design: Difficulty/cross_entity_state_dependency/statement_submit_requires_sorted_batch
        """
        world = fx.build_open_funded_world(api)
        validate_error(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_house_id, world.batch_v_open
                ),
                POSTAGE_MANAGER,
            ),
            e.ERR_INVALID_BATCH_STATE,
        )

        sorted_batch = validate_success(api.sort_batch(world.batch_id, PRESORT_OPERATOR))
        assert_batch_pricing(
            sorted_batch,
            status="SORTED",
            achieved_tier=fx.POOLED_TIER,
            rate_mills=fx.POOLED_RATE_MILLS,
            postage_cents=fx.POOLED_POSTAGE_CENTS,
        )
        assert sorted_batch["version"] > world.batch_v_open

        statement = validate_success(
            api.create_postage_statement(
                f.postage_statement_payload(
                    world.batch_id, world.permit_house_id, sorted_batch["version"]
                ),
                POSTAGE_MANAGER,
            ),
            expected_status=201,
        )
        assert_statement_figures(
            statement,
            status="DRAFT",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=0,
            verified_postage_cents=0,
            verification_error_count=0,
            revision_index=0,
        )
        assert_field_values(
            statement,
            {
                "statement_piece_count": fx.POOLED_PIECES,
                "rate_mills_per_piece": fx.POOLED_RATE_MILLS,
            },
        )
