"""The gates that stand between cleaned mail and a priced, sorted pool.

Pooling is the most heavily gated operation in the bureau, and closing sortation
is the second: each has a fixed order of checks whose refusals must leave the
pool exactly as it was. These tests drive a gate to its refusal, prove the
refusal changed nothing, and where a corrective step exists, drive the same call
to success afterwards.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_ADDRESS_QUALITY_BELOW_MINIMUM,
    ERR_BATCH_HAS_NO_CONTAINERS,
    ERR_COMMINGLE_OPT_OUT,
    ERR_CONTAINER_NOT_QUALIFIED,
    ERR_CONTAINER_PIECE_MISMATCH,
)
from test_helpers.assertions import (
    assert_batch_ledger,
    assert_batch_pricing,
    assert_container_state,
    assert_field_values,
    assert_job_state,
    assert_pct_2dp,
)
from test_helpers.test_users import PRESORT_OPERATOR

# The per-piece rate a single-tenant MARKETING_MAIL pool earns at the BASIC tier
# when it is entered at the canonical SCF offering 300 basis points: 32 cents in
# mills, less 800 basis points for the tier and 300 for the entry point, floored
# once over the whole expression.
BASIC_SCF_RATE_MILLS = 32 * 1000 * (10000 - 800) * (10000 - 300) // 100_000_000


class TestAddressQualityFloorBlocksPooling:
    """A 94.90 percent job at the 95.00 percent floor, then corrected."""

    def _job_just_below_the_floor(self, api):
        owner = fx.setup_client_with_permit(
            api,
            name="Floorline Mail",
            client_code="FLOOR",
            permit_number="PI-310310",
            payment_method="METER",
        )
        facility = fx.setup_facility(api)
        job = fx.create_mail_job(
            api,
            f.mail_job_payload(
                owner.client_id,
                owner.permit_id,
                declared_piece_count=1000,
                declared_weight_oz_per_piece=1.0,
            ),
        )
        run = validate_success(
            api.create_hygiene_run(
                job["id"],
                f.hygiene_run_payload(
                    submitted_piece_count=1000,
                    cass_matched_count=949,
                    ncoa_move_updated_count=30,
                    undeliverable_removed_count=0,
                    move_update_age_days=30,
                ),
                PRESORT_OPERATOR,
            ),
            201,
        )
        batch = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        return owner, job, run, batch

    def test_a_job_at_ninety_four_ninety_is_refused_at_the_floor(self, api):
        """The hygiene pass itself is accepted; only the pooling is refused.

        A hygiene run records whatever the address work achieved, and 949 CASS
        matches out of 1000 submitted is a legitimate result. Pooling is where the
        standard bites: "The job's `address_quality_pct` must be at least 95.00
        percent, otherwise `ERR_ADDRESS_QUALITY_BELOW_MINIMUM` — a job at exactly
        95.00 passes, a job at 94.99 does not."

        Design: Corner/validations/violation_to_error_address_quality_below_the_floor_blocks_pooling
        """
        _owner, job, run, batch = self._job_just_below_the_floor(api)

        assert_pct_2dp(run, "address_quality_pct", 94.90)
        assert run["move_update_compliant"] is True, (
            "the move-update data is 30 days old, so only the quality gate can bite"
        )

        validate_error(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job["id"]), PRESORT_OPERATOR
            ),
            ERR_ADDRESS_QUALITY_BELOW_MINIMUM,
            422,
        )

    def test_the_refused_pooling_leaves_the_job_and_the_pool_untouched(self, api):
        """A refusal is not a partial pooling.

        "A partial cascade is never an acceptable outcome: if any precondition of the
        driving operation fails, nothing at all changes." The pool's ledger is defined
        by its members alone: "For any `CommingleBatch`, `total_piece_count` always
        equals the sum of `contributed_piece_count` over the batch's currently
        attached `BatchMember` rows, and `member_job_count` always equals the number
        of those rows."

        Design: Corner/validations/violation_to_error_address_quality_below_the_floor_blocks_pooling
        """
        _owner, job, _run, batch = self._job_just_below_the_floor(api)

        validate_error(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job["id"]), PRESORT_OPERATOR
            ),
            ERR_ADDRESS_QUALITY_BELOW_MINIMUM,
            422,
        )

        after_job = validate_success(api.get_mail_job(job["id"], PRESORT_OPERATOR))
        assert_job_state(
            after_job,
            status="HYGIENE_CLEARED",
            accepted_piece_count=1000,
            commingle_batch_id=None,
        )

        after_batch = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            after_batch, member_job_count=0, total_piece_count=0, container_count=0
        )
        assert after_batch["achieved_tier"] == "NONE"

    def test_a_corrective_pass_lifts_the_job_over_the_floor_and_it_pools(self, api):
        """The newest pass replaces the old verdict outright.

        "Earlier runs are retained as history and are never averaged in; a corrective
        pass therefore fully replaces its predecessor's verdict." A second pass at
        96.00 percent therefore clears the floor, and the same pooling call that was
        refused now succeeds; "Its `contributed_piece_count` is a snapshot of the
        job's `accepted_piece_count` taken at the instant of pooling".

        Design: Corner/validations/violation_to_error_address_quality_below_the_floor_blocks_pooling
        """
        _owner, job, _run, batch = self._job_just_below_the_floor(api)
        validate_error(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job["id"]), PRESORT_OPERATOR
            ),
            ERR_ADDRESS_QUALITY_BELOW_MINIMUM,
            422,
        )

        corrective = validate_success(
            api.create_hygiene_run(
                job["id"],
                f.hygiene_run_payload(
                    submitted_piece_count=1000,
                    cass_matched_count=960,
                    ncoa_move_updated_count=30,
                    undeliverable_removed_count=0,
                    move_update_age_days=30,
                ),
                PRESORT_OPERATOR,
            ),
            201,
        )
        assert corrective["run_index"] == 1
        assert_pct_2dp(corrective, "address_quality_pct", 96.00)

        member = validate_success(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job["id"]), PRESORT_OPERATOR
            ),
            201,
        )
        assert member["contributed_piece_count"] == 1000

        pooled_batch = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            pooled_batch, member_job_count=1, total_piece_count=1000, container_count=0
        )
        assert pooled_batch["achieved_tier"] == "BASIC"


class TestAddressQualityExactlyAtTheFloor:
    """Exactly 95.00 percent and exactly 95 days old: both pass."""

    def _job_exactly_at_the_floor(self, api):
        owner = fx.setup_client_with_permit(
            api,
            name="Exactly Ninety Five",
            client_code="EXACT",
            permit_number="PI-320320",
            payment_method="METER",
        )
        facility = fx.setup_facility(api)
        job = fx.create_mail_job(
            api,
            f.mail_job_payload(
                owner.client_id,
                owner.permit_id,
                declared_piece_count=1000,
                declared_weight_oz_per_piece=1.0,
            ),
        )
        run = validate_success(
            api.create_hygiene_run(
                job["id"],
                f.hygiene_run_payload(
                    submitted_piece_count=1000,
                    cass_matched_count=950,
                    ncoa_move_updated_count=30,
                    undeliverable_removed_count=40,
                    move_update_age_days=95,
                ),
                PRESORT_OPERATOR,
            ),
            201,
        )
        batch = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        return owner, job, run, batch

    def test_the_run_lands_exactly_on_both_boundaries(self, api):
        """950 of 1000 is 95.00 percent, and 95 days old is still compliant.

        "Its `move_update_compliant` is true when `move_update_age_days` is less than
        or equal to the maximum permitted age of 95 days, so a data set exactly 95
        days old is compliant while one 96 days old is not." The net volume drops
        away from the submitted one: "Its `net_piece_count` is the
        `submitted_piece_count` less the `undeliverable_removed_count`."

        Design: Corner/validations/satisfaction_to_pass_address_quality_exactly_at_the_floor_pools
        """
        _owner, _job, run, _batch = self._job_exactly_at_the_floor(api)

        assert_pct_2dp(run, "address_quality_pct", 95.00)
        assert_field_values(
            run, {"net_piece_count": 960, "move_update_compliant": True}
        )

    def test_a_job_exactly_at_the_floor_pools_and_contributes_its_net_volume(self, api):
        """95.00 passes, and what it contributes is the accepted count, not the submitted one.

        "The job's `address_quality_pct` must be at least 95.00 percent, otherwise
        `ERR_ADDRESS_QUALITY_BELOW_MINIMUM` — a job at exactly 95.00 passes, a job at
        94.99 does not." What lands in the pool is the surviving mail: "Its
        `contributed_piece_count` is a snapshot of the job's `accepted_piece_count`
        taken at the instant of pooling and is **never re-read afterwards**". "The job
        itself moves `HYGIENE_CLEARED → POOLED` and has its denormalized
        `commingle_batch_id` pointer set to the batch."

        Design: Corner/validations/satisfaction_to_pass_address_quality_exactly_at_the_floor_pools
        """
        _owner, job, _run, batch = self._job_exactly_at_the_floor(api)

        member = validate_success(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job["id"]), PRESORT_OPERATOR
            ),
            201,
        )
        assert member["contributed_piece_count"] == 960, (
            "the pool receives the 960 pieces that survived hygiene, not 1000"
        )

        after_job = validate_success(api.get_mail_job(job["id"], PRESORT_OPERATOR))
        assert_job_state(
            after_job,
            status="POOLED",
            accepted_piece_count=960,
            commingle_batch_id=batch["id"],
        )

        after_batch = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            after_batch, member_job_count=1, total_piece_count=960, container_count=0
        )
        assert after_batch["achieved_tier"] == "BASIC"


class TestCommingleOptInGatesPooling:
    """Two identical mailings, one from a mailer who opted out of pooling."""

    def _two_mailers_one_pool(self, api):
        opted_out = fx.setup_client_with_permit(
            api,
            name="Solo Mailer Co",
            client_code="OPTOUT",
            permit_number="PI-330330",
            payment_method="METER",
            commingle_opt_in=False,
        )
        opted_in = fx.setup_client_with_permit(
            api,
            name="Shared Pool Mailer",
            client_code="OPTIN",
            permit_number="PI-340340",
            payment_method="METER",
        )
        facility = fx.setup_facility(api)
        job_out = fx.setup_cleared_job(
            api,
            opted_out.client_id,
            opted_out.permit_id,
            declared_piece_count=1000,
            submitted_piece_count=1000,
            cass_matched_count=990,
            ncoa_move_updated_count=30,
            undeliverable_removed_count=0,
            move_update_age_days=10,
        )
        job_in = fx.setup_cleared_job(
            api,
            opted_in.client_id,
            opted_in.permit_id,
            declared_piece_count=1000,
            submitted_piece_count=1000,
            cass_matched_count=990,
            ncoa_move_updated_count=30,
            undeliverable_removed_count=0,
            move_update_age_days=10,
        )
        batch = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        return opted_out, opted_in, job_out, job_in, batch

    def test_an_opted_out_mailers_job_cannot_be_pooled(self, api):
        """Choosing to stay out of shared pools is enforced at pooling.

        "`commingle_opt_in` is a boolean that defaults to true when omitted, and a
        mailer that sets it false has chosen to keep its mail out of shared pools."
        The pooling gate honours that choice: "The job's client must be `ACTIVE` and
        must have `commingle_opt_in` true, otherwise the request is refused with
        `ERR_CLIENT_SUSPENDED` or `ERR_COMMINGLE_OPT_OUT` respectively."

        Design: Corner/validations/conditional_validation_commingle_opt_in_flag_gates_pooling
        """
        opted_out, _opted_in, job_out, _job_in, batch = self._two_mailers_one_pool(api)

        assert opted_out.client["commingle_opt_in"] is False
        assert job_out.job["status"] == "HYGIENE_CLEARED", (
            "the mailing is perfectly clean; only the mailer's own choice blocks it"
        )

        validate_error(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job_out.job_id), PRESORT_OPERATOR
            ),
            ERR_COMMINGLE_OPT_OUT,
            422,
        )

        after_job = validate_success(api.get_mail_job(job_out.job_id, PRESORT_OPERATOR))
        assert_job_state(
            after_job, status="HYGIENE_CLEARED", commingle_batch_id=None
        )
        after_batch = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            after_batch, member_job_count=0, total_piece_count=0, container_count=0
        )

    def test_the_same_mailing_from_an_opted_in_mailer_pools(self, api):
        """The flag defaults to true, so an ordinary mailer needs no opt-in step.

        "`commingle_opt_in` is a boolean that defaults to true when omitted, and a
        mailer that sets it false has chosen to keep its mail out of shared pools."
        With everything else about the two mailings identical, the pooling succeeds
        and "On the batch side, `total_piece_count` grows by the new member's
        `contributed_piece_count` and `member_job_count` grows by one."

        Design: Corner/validations/conditional_validation_commingle_opt_in_flag_gates_pooling
        """
        _opted_out, opted_in, job_out, job_in, batch = self._two_mailers_one_pool(api)

        assert opted_in.client["commingle_opt_in"] is True
        validate_error(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job_out.job_id), PRESORT_OPERATOR
            ),
            ERR_COMMINGLE_OPT_OUT,
            422,
        )

        member = validate_success(
            api.add_batch_member(
                batch["id"], f.batch_member_payload(job_in.job_id), PRESORT_OPERATOR
            ),
            201,
        )
        assert member["contributed_piece_count"] == 1000

        after_job = validate_success(api.get_mail_job(job_in.job_id, PRESORT_OPERATOR))
        assert_job_state(after_job, status="POOLED", commingle_batch_id=batch["id"])
        after_batch = validate_success(
            api.get_commingle_batch(batch["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            after_batch, member_job_count=1, total_piece_count=1000, container_count=0
        )
        assert after_batch["achieved_tier"] == "BASIC"


class TestSortationGatesFireInTheirFixedOrder:
    """Empty pool, then an undersized tray, then a tray that does not reconcile."""

    def _two_pools_ready_to_be_sorted(self, api):
        owner = fx.setup_client_with_permit(
            api,
            name="Gateway Presort",
            client_code="GATES",
            permit_number="PI-350350",
            payment_method="METER",
        )
        facility = fx.setup_facility(api)
        job_1 = fx.setup_cleared_job(
            api, owner.client_id, owner.permit_id, declared_piece_count=1000
        )
        job_2 = fx.setup_cleared_job(
            api, owner.client_id, owner.permit_id, declared_piece_count=1000
        )
        batch_1 = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        batch_2 = fx.create_batch(api, f.commingle_batch_payload(facility["id"]))
        return owner, job_1, job_2, batch_1, batch_2

    def test_an_empty_pool_cannot_be_sorted_at_all(self, api):
        """With nothing pooled and nothing containerized there is nothing to freeze.

        "The batch must have at least one member and at least one container — a batch
        whose `member_job_count` or `container_count` is 0 is refused with
        `ERR_BATCH_HAS_NO_CONTAINERS`."

        Design: Corner/validations/cascading_validation_sort_gates_run_empty_then_qualification_then_pieces
        """
        _owner, _job_1, _job_2, batch_1, _batch_2 = self._two_pools_ready_to_be_sorted(
            api
        )

        assert_batch_ledger(
            batch_1, member_job_count=0, total_piece_count=0, container_count=0
        )
        validate_error(
            api.sort_batch(batch_1["id"], PRESORT_OPERATOR),
            ERR_BATCH_HAS_NO_CONTAINERS,
            422,
        )

        after = validate_success(
            api.get_commingle_batch(batch_1["id"], PRESORT_OPERATOR)
        )
        assert after["status"] == "OPEN"

    def test_an_undersized_tray_is_reported_before_the_piece_reconciliation(self, api):
        """A 100-piece deep tray fails qualification, and that is the error returned.

        "Every container on the batch must have `qualifies` true, or the request is
        refused with `ERR_CONTAINER_NOT_QUALIFIED`." The tray is short because "A
        `TRAY` built at the deep levels `THREE_DIGIT` or `FIVE_DIGIT` must hold at
        least 150 pieces." Its 100 pieces also fail to reconcile against the pooled
        1000, but "The server therefore evaluates checks in one fixed, strictly
        ascending order and returns the error of the **first** rule violated; no later
        rule can mask an earlier one, and no earlier rule can be skipped because a
        later one also fails."

        Design: Corner/validations/cascading_validation_sort_gates_run_empty_then_qualification_then_pieces
        """
        _owner, job_1, _job_2, batch_1, _batch_2 = self._two_pools_ready_to_be_sorted(
            api
        )
        fx.add_member(api, batch_1["id"], job_1.job_id)
        container = fx.add_container(
            api,
            batch_1["id"],
            f.sort_container_payload("TRAY", "021", "FIVE_DIGIT", 100),
        )
        assert_container_state(
            container,
            status="STAGED",
            qualifies=False,
            placard_id=None,
            sequence_index=0,
        )

        validate_error(
            api.sort_batch(batch_1["id"], PRESORT_OPERATOR),
            ERR_CONTAINER_NOT_QUALIFIED,
            422,
        )

        after = validate_success(
            api.get_commingle_batch(batch_1["id"], PRESORT_OPERATOR)
        )
        assert_batch_ledger(
            after, member_job_count=1, total_piece_count=1000, container_count=1
        )
        # Membership already priced this pool while it is OPEN, and the refused
        # sortation neither froze nor discarded that price.
        assert_batch_pricing(
            after,
            status="OPEN",
            achieved_tier="BASIC",
            rate_mills=BASIC_SCF_RATE_MILLS,
            postage_cents=28556,
        )

    def test_a_qualifying_tray_that_does_not_reconcile_is_refused_on_the_pieces(
        self, api
    ):
        """900 physical pieces against a 1000-piece pooled ledger.

        "And the sum of `piece_count` over the batch's containers must equal the
        batch's `total_piece_count` exactly, or the request is refused with
        `ERR_CONTAINER_PIECE_MISMATCH` — the physical mail on the floor must reconcile
        against the pooled ledger to the piece." The tray itself is beyond reproach:
        "The comparison is inclusive: a `TRAY` at `FIVE_DIGIT` holding exactly 150
        pieces qualifies, one holding 149 does not."

        Design: Corner/validations/cascading_validation_sort_gates_run_empty_then_qualification_then_pieces
        """
        _owner, _job_1, job_2, _batch_1, batch_2 = self._two_pools_ready_to_be_sorted(
            api
        )
        fx.add_member(api, batch_2["id"], job_2.job_id)
        container = fx.add_container(
            api,
            batch_2["id"],
            f.sort_container_payload("TRAY", "021", "FIVE_DIGIT", 900),
        )
        assert_container_state(
            container,
            status="STAGED",
            qualifies=True,
            placard_id=None,
            sequence_index=0,
        )

        validate_error(
            api.sort_batch(batch_2["id"], PRESORT_OPERATOR),
            ERR_CONTAINER_PIECE_MISMATCH,
            422,
        )

        after_batch = validate_success(
            api.get_commingle_batch(batch_2["id"], PRESORT_OPERATOR)
        )
        assert after_batch["status"] == "OPEN"
        after_container = validate_success(
            api.get_sort_container(container["id"], PRESORT_OPERATOR)
        )
        assert_container_state(
            after_container, status="STAGED", qualifies=True, placard_id=None
        )
        after_job = validate_success(api.get_mail_job(job_2.job_id, PRESORT_OPERATOR))
        assert_job_state(after_job, status="POOLED", postage_due_cents=0)
