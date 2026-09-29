"""Figures whose inputs interact rather than add up.

Three derivations in this contract are combinatorial: the invoice service fee,
where a ceiling, a volume discount and a minimum charge each change what the
others mean; the pro-rata split, where a floor per member and one remainder cent
must still sum to the pool; and the verification surcharge walk, where each
finding's severity depends on every finding recorded before it.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_cents,
    assert_field_values,
    assert_invoice_figures,
    assert_job_state,
    assert_member_allocation,
    assert_pct_4dp,
    assert_permit_funds,
    assert_statement_figures,
    assert_sum_of_cents,
    find_by_id,
)
from test_helpers.test_users import ACCEPTANCE_CLERK, POSTAGE_MANAGER, PRESORT_OPERATOR


class TestInvoiceServiceFeeInteraction:
    """Two mailers, one billing period, two different fee branches."""

    def test_the_small_mailing_pays_the_minimum_charge_floor(self, api):
        """A ceiling on thousands then a floor on the fee.

        "Next, the billable volume is converted into whole thousands of pieces by
        dividing `billed_piece_count` by one thousand and taking the ceiling — 1
        piece and 1000 pieces both count as one thousand, 1001 pieces count as two."
        "A volume discount in basis points follows from `billed_piece_count` itself:
        below 5000 pieces the discount is 0, from 5000 up to but not including 25000
        pieces it is 500 basis points, and at 25000 pieces or more it is 1200 basis
        points, the highest satisfied threshold winning." "The invoice's
        `service_fee_cents` is then the greater of the bureau's minimum charge of
        2500 cents and that discounted fee."

        Design: Difficulty/combinatorial_formula/invoice_service_fee_ceil_tier_and_floor_interaction
        """
        world = fx.build_deposited_world(api)

        invoice = validate_success(
            api.create_client_invoice(world.acme_id, f.invoice_payload(), POSTAGE_MANAGER),
            expected_status=201,
        )
        # 1200 pieces -> 2 whole thousands, no volume discount, gross 2 * 900 = 1800,
        # which the 2500-cent minimum charge overrides.
        assert_invoice_figures(
            invoice,
            status="ISSUED",
            billed_piece_count=fx.JOB_A_ACCEPTED,
            included_job_count=1,
            postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            adjustment_cents=0,
            service_fee_cents=2500,
            total_cents=34160,
        )

    def test_the_same_thousands_bucket_can_still_beat_the_floor(self, api):
        """Identical volume, a higher per-thousand rate, a different branch.

        "The gross fee is those whole thousands multiplied by the client's
        `service_fee_rate_per_thousand_cents`." "The three inputs interact
        non-linearly, and the order above is what makes the result well defined: the
        ceiling on thousands is applied *before* the discount factor, and the
        minimum-charge floor is applied *after* it, so a small mailing can end up
        paying the 2500-cent floor while a large one pays a genuinely discounted
        rate."

        Design: Difficulty/combinatorial_formula/invoice_service_fee_ceil_tier_and_floor_interaction
        """
        world = fx.build_deposited_world(api)

        invoice = validate_success(
            api.create_client_invoice(world.bore_id, f.invoice_payload(), POSTAGE_MANAGER),
            expected_status=201,
        )
        # 1800 pieces -> the same 2 whole thousands, gross 2 * 2200 = 4400, which
        # clears the minimum charge on its own.
        assert_invoice_figures(
            invoice,
            status="ISSUED",
            billed_piece_count=fx.JOB_B_ACCEPTED,
            included_job_count=1,
            postage_cents=fx.MEMBER_B_POSTAGE_CENTS,
            adjustment_cents=0,
            service_fee_cents=4400,
            total_cents=51892,
        )

    def test_issuing_the_invoice_settles_the_job_and_the_client_ledger(self, api):
        """The invoice is what moves the jobs out of MAILED.

        "Every included job moves `MAILED → BILLED` with its `version` incremented,
        which is what makes re-issuing over the same jobs impossible — they are no
        longer in `MAILED` and so cannot be selected again." "The client's
        `unbilled_postage_cents` decreases by the invoice's `postage_cents` plus its
        `adjustment_cents`."

        Design: Difficulty/combinatorial_formula/invoice_service_fee_ceil_tier_and_floor_interaction
        """
        world = fx.build_deposited_world(api)

        validate_success(
            api.create_client_invoice(world.acme_id, f.invoice_payload(), POSTAGE_MANAGER),
            expected_status=201,
        )
        validate_success(
            api.create_client_invoice(world.bore_id, f.invoice_payload(), POSTAGE_MANAGER),
            expected_status=201,
        )

        job_a = validate_success(api.get_mail_job(world.job_a_id, POSTAGE_MANAGER))
        job_b = validate_success(api.get_mail_job(world.job_b_id, POSTAGE_MANAGER))
        assert_job_state(job_a, "BILLED")
        assert_job_state(job_b, "BILLED")

        acme = validate_success(api.get_client(world.acme_id, POSTAGE_MANAGER))
        bore = validate_success(api.get_client(world.bore_id, POSTAGE_MANAGER))
        assert_cents(acme, "unbilled_postage_cents", 0)
        assert_cents(bore, "unbilled_postage_cents", 0)


class TestProRataRemainderDistribution:
    """79152 cents split over 1200 and 1800 pieces."""

    def test_each_member_takes_the_floor_of_its_raw_share(self, api):
        """No member's share is rounded half up.

        "Each member's provisional allocation is the floor of its raw share."
        "Rounding each member's raw share half up and summing the results is
        forbidden, because it can drift from the pool by as much as one cent per
        member."

        Design: Difficulty/combinatorial_formula/pro_rata_remainder_goes_to_larger_contributor
        """
        world = fx.build_sorted_world(api)

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        member_a = find_by_id(members, world.member_a_id)
        # The raw share of the 1200-piece member is 31660.8 cents; its floor is
        # 31660, and the half-up 31661 is forbidden.
        assert_cents(member_a, "allocated_postage_cents", 31660)

    def test_the_remainder_cent_goes_to_the_larger_contributor(self, api):
        """The one leftover cent is placed, never rounded away.

        "The remainder — the pool of cents less the sum of those floors — is then a
        whole number strictly less than the number of members, and it is distributed
        one cent at a time: members are ordered by `contributed_piece_count`
        descending, and where two members contributed equally, by `created_at`
        ascending; the first *remainder*-many members in that order each receive one
        additional cent."

        Design: Difficulty/combinatorial_formula/pro_rata_remainder_goes_to_larger_contributor
        """
        world = fx.build_sorted_world(api)

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        member_a = find_by_id(members, world.member_a_id)
        member_b = find_by_id(members, world.member_b_id)
        # Floors are 31660 and 47491, leaving one cent, which goes to the 1800-piece
        # member rather than to the member created first.
        assert_cents(member_b, "allocated_postage_cents", 47492)
        assert_sum_of_cents(
            [
                member_a["allocated_postage_cents"],
                member_b["allocated_postage_cents"],
            ],
            fx.POOLED_POSTAGE_CENTS,
            what="member allocations",
        )

    def test_the_share_percentages_are_recorded_to_four_decimal_places(self, api):
        """The share is its own figure with its own rounding step.

        "Each member's `share_basis_pct` is separately recorded as its
        `contributed_piece_count` multiplied by one hundred and divided by the
        denominator, rounded half up to four decimal places."

        Design: Difficulty/combinatorial_formula/pro_rata_remainder_goes_to_larger_contributor
        """
        world = fx.build_sorted_world(api)

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        assert_pct_4dp(find_by_id(members, world.member_a_id), "share_basis_pct", 40.0000)
        assert_pct_4dp(find_by_id(members, world.member_b_id), "share_basis_pct", 60.0000)


class TestCumulativeFindingSeverity:
    """Two findings on a 3000-piece statement, in each order."""

    def test_severity_follows_the_cumulative_count_not_the_finding_alone(self, api):
        """The second finding is major because of the first one.

        "At each finding the cumulative count grows by that finding's
        `affected_piece_count`. The finding's `severity` is then `MAJOR` when the
        cumulative count of affected pieces multiplied by ten thousand is at least
        the statement's frozen `statement_piece_count` multiplied by the major
        threshold of 500 basis points — equivalently, when the running total of
        affected pieces has reached five percent of the frozen piece count — and
        `MINOR` otherwise." "That severity picks a surcharge rate in basis points:
        `MINOR` draws 2500 basis points and `MAJOR` draws 10000 basis points."

        Design: Difficulty/combinatorial_formula/cumulative_finding_severity_is_order_sensitive
        """
        world = fx.build_submitted_world(api)

        finding_1 = validate_success(
            api.create_finding(
                world.statement_id,
                f.finding_payload("CONTAINER_NOT_QUALIFIED", 120),
                ACCEPTANCE_CLERK,
            ),
            expected_status=201,
        )
        finding_2 = validate_success(
            api.create_finding(
                world.statement_id,
                f.finding_payload("SHORT_PAID", 400),
                ACCEPTANCE_CLERK,
            ),
            expected_status=201,
        )

        # 120 * 10000 is below 3000 * 500, so the first finding is still minor;
        # cumulatively 520 pieces clears the threshold for the second.
        assert_field_values(finding_1, {"severity": "MINOR", "surcharge_cents": 792})
        assert_field_values(finding_2, {"severity": "MAJOR", "surcharge_cents": 10554})

    def test_each_surcharge_is_rounded_before_the_adjustment_is_summed(self, api):
        """Two roundings, one per finding, never one at the end.

        "After each finding, the statement's `adjustment_cents` is refreshed as the
        sum of `surcharge_cents` over that same ordered walk — each finding rounded
        half up individually and the rounded amounts then summed; summing the exact
        rationals and rounding once at the end is forbidden — and
        `verification_error_count` is refreshed as the number of findings recorded."

        Design: Difficulty/combinatorial_formula/cumulative_finding_severity_is_order_sensitive
        """
        world = fx.build_submitted_world(api)

        api.create_finding(
            world.statement_id,
            f.finding_payload("CONTAINER_NOT_QUALIFIED", 120),
            ACCEPTANCE_CLERK,
        )
        api.create_finding(
            world.statement_id, f.finding_payload("SHORT_PAID", 400), ACCEPTANCE_CLERK
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        # 791.52 rounds to 792 and 10553.6 rounds to 10554, summing to 11346; one
        # rounding of the exact total would give 11345.
        assert_cents(statement, "adjustment_cents", 11346)
        assert statement["verification_error_count"] == 2

    def test_the_frozen_piece_count_and_rate_survive_the_findings(self, api):
        """The surcharge base is never eroded by the pieces it covers.

        "First, `statement_piece_count` and `rate_mills_per_piece` were frozen onto
        the statement at preparation; they are never re-read from the batch and are
        never reduced by the affected pieces."

        Design: Difficulty/combinatorial_formula/cumulative_finding_severity_is_order_sensitive
        """
        world = fx.build_submitted_world(api)

        api.create_finding(
            world.statement_id,
            f.finding_payload("CONTAINER_NOT_QUALIFIED", 120),
            ACCEPTANCE_CLERK,
        )
        api.create_finding(
            world.statement_id, f.finding_payload("SHORT_PAID", 400), ACCEPTANCE_CLERK
        )

        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_field_values(
            statement,
            {
                "statement_piece_count": fx.POOLED_PIECES,
                "rate_mills_per_piece": fx.POOLED_RATE_MILLS,
            },
        )

    def test_the_same_two_findings_in_the_opposite_order_cost_more(self, api):
        """Order sensitivity is the point of the pinned walk.

        "Severity is therefore **cumulative and order-sensitive**, which is
        intentional: on a 3000-piece statement, recording a 120-piece finding and
        then a 400-piece finding yields `MINOR` followed by `MAJOR`, while recording
        the same two findings in the opposite order yields `MAJOR` followed by
        `MAJOR` and a strictly larger total adjustment."

        Design: Difficulty/combinatorial_formula/cumulative_finding_severity_is_order_sensitive
        """
        world = fx.build_submitted_world(api)

        first = validate_success(
            api.create_finding(
                world.statement_id,
                f.finding_payload("SHORT_PAID", 400),
                ACCEPTANCE_CLERK,
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_finding(
                world.statement_id,
                f.finding_payload("CONTAINER_NOT_QUALIFIED", 120),
                ACCEPTANCE_CLERK,
            ),
            expected_status=201,
        )

        assert_field_values(first, {"severity": "MAJOR", "surcharge_cents": 10554})
        assert_field_values(second, {"severity": "MAJOR", "surcharge_cents": 3166})
        statement = validate_success(
            api.get_postage_statement(world.statement_id, POSTAGE_MANAGER)
        )
        assert_cents(statement, "adjustment_cents", 13720)
        assert statement["adjustment_cents"] > 11346, (
            "the same two findings recorded the other way round must cost more"
        )

    def test_accepting_with_the_adjustment_allocates_it_and_debits_the_balance(self, api):
        """The surcharge is split pro rata and paid out of the balance.

        "The statement's `adjustment_cents` takes the walked value and its
        `verified_postage_cents` becomes its `declared_postage_cents` plus that
        `adjustment_cents`." "Two separate movements hit the account:
        `declared_postage_cents` is subtracted from `reserved_cents`, consuming the
        reservation, and `adjustment_cents` is subtracted from `balance_cents`,
        paying the surcharge." "Every member job then has its `postage_due_cents` set
        to its member's `allocated_postage_cents` plus its
        `allocated_adjustment_cents`, and each of those amounts is added to that
        job's client's `unbilled_postage_cents`."

        Design: Difficulty/combinatorial_formula/cumulative_finding_severity_is_order_sensitive
        """
        world = fx.build_submitted_world(api)
        api.create_finding(
            world.statement_id,
            f.finding_payload("CONTAINER_NOT_QUALIFIED", 120),
            ACCEPTANCE_CLERK,
        )
        api.create_finding(
            world.statement_id, f.finding_payload("SHORT_PAID", 400), ACCEPTANCE_CLERK
        )

        statement = validate_success(
            api.verify_postage_statement(
                world.statement_id, f.verify_payload("ACCEPT"), ACCEPTANCE_CLERK
            )
        )
        assert_statement_figures(
            statement,
            status="ACCEPTED_WITH_ADJUSTMENT",
            declared_postage_cents=fx.POOLED_POSTAGE_CENTS,
            adjustment_cents=11346,
            verified_postage_cents=90498,
            verification_error_count=2,
        )

        members, _meta = validate_paginated(
            api.list_batch_members(world.batch_id, POSTAGE_MANAGER)
        )
        # 11346 over 1200 and 1800 pieces: floors 4538 and 6807, one remainder cent
        # to the larger contributor.
        assert_member_allocation(
            find_by_id(members, world.member_a_id),
            contributed_piece_count=fx.JOB_A_ACCEPTED,
            share_basis_pct=fx.MEMBER_A_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_A_POSTAGE_CENTS,
            allocated_adjustment_cents=4538,
        )
        assert_member_allocation(
            find_by_id(members, world.member_b_id),
            contributed_piece_count=fx.JOB_B_ACCEPTED,
            share_basis_pct=fx.MEMBER_B_SHARE_PCT,
            allocated_postage_cents=fx.MEMBER_B_POSTAGE_CENTS,
            allocated_adjustment_cents=6808,
        )

        job_a = validate_success(api.get_mail_job(world.job_a_id, PRESORT_OPERATOR))
        job_b = validate_success(api.get_mail_job(world.job_b_id, PRESORT_OPERATOR))
        assert_cents(job_a, "postage_due_cents", 36198)
        assert_cents(job_b, "postage_due_cents", 54300)

        permit = validate_success(
            api.get_permit_account(world.permit_house_id, POSTAGE_MANAGER)
        )
        assert_permit_funds(permit, balance_cents=109502, reserved_cents=0)
