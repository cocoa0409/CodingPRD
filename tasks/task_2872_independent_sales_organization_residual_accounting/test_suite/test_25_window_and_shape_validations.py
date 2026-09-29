"""Coverage-window, recoupment-window, hierarchy and uniqueness validation corners.

Every test builds all of its own state through the public endpoints. The logical
clock starts at 2026-08-01T00:00:00Z and no test in this module moves it.
"""

from test_helpers import (
    ADMIN,
    ANALYST,
    ApiErrorId,
    activate_merchant,
    add_line,
    api_client,
    attrite_merchant,
    attrite_merchant_payload,
    create_agent_payload,
    create_merchant_payload,
    create_residual_line_payload,
    fetch_agent,
    fetch_batch,
    fetch_merchant,
    list_rows,
    make_agent,
    make_batch,
    make_merchant,
    make_program,
    reactivate_merchant,
    reactivate_merchant_payload,
    validate_error,
    validate_success,
)


class TestCoverageWindowShape:
    """The half-open coverage window and the accounting-month pattern that outranks it."""

    def test_coverage_window_refused_three_ways_and_period_month_outranks_it(self):
        """The three legs of the coverage-shape rule, and the band-5 month pattern beating it.

        PRD: "Three shape conditions apply together, and any failure is
        `ERR_COVERAGE_WINDOW_INVALID` (HTTP 422): `coverage_end` must be strictly later
        than `coverage_start`; `coverage_start` must fall inside the accounting month,
        meaning on or after its first day and strictly before the first day of the
        following month; and `coverage_end` may be no later than the first day of the
        second month after `period_month`, so a file may spill at most one month past the
        period it reports."

        PRD: "every accounting-month input must match the exact four-digit-year, hyphen,
        two-digit-month shape with the month between 01 and 12 inclusive; a malformed
        value yields `ERR_INVALID_PERIOD_MONTH` (422) on batch ingest" — and that check
        sits at band 5 while the coverage window sits at band 11, where "the first band
        that produces a failure determines the response, and no later band is consulted."

        Design: Corner/validations/coverage_window_shape_is_refused_three_ways_and_period_month_outranks_it
        """
        program = make_program(
            name="Atlantic Net Program", minimum_billing_mode="NO_MINIMUM"
        )
        p1 = program["id"]

        # period_month 2026-13 is malformed AND coverage_start 2026-06-30 breaks the
        # window rule: the band-5 month pattern must be the reported failure.
        both_broken = api_client.create_residual_batch(
            {
                "processor_program_id": p1,
                "period_month": "2026-13",
                "coverage_start": "2026-06-30",
                "coverage_end": "2026-08-01",
                "file_checksum": "sha256:cw-0001",
            },
            ANALYST,
        )
        validate_error(both_broken, ApiErrorId.ERR_INVALID_PERIOD_MONTH.value)

        zero_length = api_client.create_residual_batch(
            {
                "processor_program_id": p1,
                "period_month": "2026-07",
                "coverage_start": "2026-07-01",
                "coverage_end": "2026-07-01",
                "file_checksum": "sha256:cw-0002",
            },
            ANALYST,
        )
        validate_error(zero_length, ApiErrorId.ERR_COVERAGE_WINDOW_INVALID.value)

        start_before_period = api_client.create_residual_batch(
            {
                "processor_program_id": p1,
                "period_month": "2026-07",
                "coverage_start": "2026-06-30",
                "coverage_end": "2026-08-01",
                "file_checksum": "sha256:cw-0003",
            },
            ANALYST,
        )
        validate_error(start_before_period, ApiErrorId.ERR_COVERAGE_WINDOW_INVALID.value)

        spills_too_far = api_client.create_residual_batch(
            {
                "processor_program_id": p1,
                "period_month": "2026-07",
                "coverage_start": "2026-07-01",
                "coverage_end": "2026-09-02",
                "file_checksum": "sha256:cw-0004",
            },
            ANALYST,
        )
        validate_error(spills_too_far, ApiErrorId.ERR_COVERAGE_WINDOW_INVALID.value)

        # 2026-09-01 is the first day of the second month after 2026-07: the maximal
        # legal coverage_end.
        accepted = api_client.create_residual_batch(
            {
                "processor_program_id": p1,
                "period_month": "2026-07",
                "coverage_start": "2026-07-01",
                "coverage_end": "2026-09-01",
                "file_checksum": "sha256:cw-0005",
            },
            ANALYST,
        )
        batch = validate_success(accepted, 201)
        assert batch["state"] == "RECEIVED", (
            f"a freshly ingested batch is RECEIVED, got {batch['state']!r}"
        )
        assert batch["line_count"] == 0, "line_count starts at 0"
        assert batch["gross_volume_cents"] == 0, "gross_volume_cents starts at 0"
        assert batch["total_normalized_net_revenue_cents"] == 0, (
            "total_normalized_net_revenue_cents starts at 0"
        )
        assert batch["iso_retained_cents"] == 0, "iso_retained_cents starts at 0"
        assert batch["version"] == 1, "version starts at 1 on creation"
        assert batch["coverage_end"] == "2026-09-01", (
            "the maximal legal coverage_end is stored verbatim"
        )

        _rows, meta = list_rows(
            api_client.list_residual_batches, {"processor_program_id": p1}, ANALYST
        )
        assert meta["total_count"] == 1, (
            "none of the four refused ingests may create a batch row, expected "
            f"total_count 1, got {meta['total_count']}"
        )


class TestRecoupmentWindowAndPctRange:
    """The advance recoupment window shape and the two percentage guards on funding."""

    def test_recoupment_window_shape_is_refused_three_ways(self):
        """Inverted window, pre-funding first month, and a span disagreeing with the divisor.

        PRD: "`last_recoupment_month` must be greater than or equal to
        `first_recoupment_month`; `first_recoupment_month` must be greater than or equal
        to the calendar month of `funded_on`, so an advance can never reach back before
        it was funded; and when the mode is `STRAIGHT_LINE_AMORTIZATION` the inclusive
        count of months from `first_recoupment_month` through `last_recoupment_month`
        must equal `amortization_months` exactly. Under `PERCENT_OF_RESIDUAL` the window
        may be any length. A failure on any of the three is
        `ERR_RECOUPMENT_WINDOW_INVALID` (HTTP 422)."

        Design: Corner/validations/recoupment_window_shape_is_refused_three_ways
        """
        agent = make_agent(
            name="A1 Principal",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        a1 = agent["id"]
        v1 = agent["version"]

        inverted = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "CASH_ADVANCE",
                "recoupment_mode": "PERCENT_OF_RESIDUAL",
                "principal_cents": 100000,
                "recoupment_pct": 0.30,
                "first_recoupment_month": "2026-08",
                "last_recoupment_month": "2026-07",
                "funded_on": "2026-07-15",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        validate_error(inverted, ApiErrorId.ERR_RECOUPMENT_WINDOW_INVALID.value)

        reaches_back = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "CASH_ADVANCE",
                "recoupment_mode": "PERCENT_OF_RESIDUAL",
                "principal_cents": 100000,
                "recoupment_pct": 0.30,
                "first_recoupment_month": "2026-06",
                "last_recoupment_month": "2026-12",
                "funded_on": "2026-07-15",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        validate_error(reaches_back, ApiErrorId.ERR_RECOUPMENT_WINDOW_INVALID.value)

        # [2026-08, 2026-12] spans five inclusive months, not the declared six.
        span_disagrees = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "PORTFOLIO_BUYOUT",
                "recoupment_mode": "STRAIGHT_LINE_AMORTIZATION",
                "principal_cents": 100000,
                "amortization_months": 6,
                "first_recoupment_month": "2026-08",
                "last_recoupment_month": "2026-12",
                "funded_on": "2026-07-15",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        validate_error(span_disagrees, ApiErrorId.ERR_RECOUPMENT_WINDOW_INVALID.value)

        accepted = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "PORTFOLIO_BUYOUT",
                "recoupment_mode": "STRAIGHT_LINE_AMORTIZATION",
                "principal_cents": 100000,
                "amortization_months": 5,
                "first_recoupment_month": "2026-08",
                "last_recoupment_month": "2026-12",
                "funded_on": "2026-07-15",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        advance = validate_success(accepted, 201)
        assert advance["state"] == "ACTIVE", "a funded advance starts ACTIVE"
        assert advance["outstanding_cents"] == 100000, (
            "outstanding_cents starts equal to principal_cents"
        )
        assert advance["cumulative_recouped_cents"] == 0, "cumulative_recouped_cents starts at 0"
        assert advance["months_recouped"] == 0, "months_recouped starts at 0"
        assert advance["amortization_months"] == 5, (
            "a five-month inclusive window matches amortization_months 5"
        )
        assert advance["recoupment_pct"] is None, (
            "recoupment_pct must be absent or null outside PERCENT_OF_RESIDUAL, got "
            f"{advance['recoupment_pct']!r}"
        )

        after = fetch_agent(a1)
        assert after["advance_outstanding_cents"] == 100000, (
            "the agent's advance_outstanding_cents rises by the funded principal"
        )
        assert after["version"] == v1 + 1, (
            "only the accepted funding bumps the agent version: expected "
            f"{v1 + 1}, got {after['version']}"
        )
        _rows, meta = list_rows(api_client.list_agent_advances, {"agent_id": a1}, ADMIN)
        assert meta["total_count"] == 1, (
            f"the three refused fundings created no advance row, got {meta['total_count']}"
        )

    def test_pct_range_outranks_the_recoupment_cap(self):
        """A fraction outside 0..1 reports the band-5 range error, not the band-13 cap error.

        PRD: "`split_pct`, `override_pct` and `recoupment_pct` must be decimal fractions
        inside the closed interval from 0 through 1 inclusive; a value outside that
        interval yields `ERR_INVALID_PCT_RANGE` (422) on agent creation, agent amendment
        and advance funding."

        PRD: "No single advance may be written to claim more than half of a monthly
        residual, so `recoupment_pct` may not exceed `0.5000`; a larger figure is
        `ERR_RECOUPMENT_PCT_EXCEEDS_CAP` (HTTP 422)." The range rule is band 5 and the
        cap is band 13, and "the first band that produces a failure determines the
        response, and no later band is consulted."

        Design: Corner/validations/pct_range_outranks_the_recoupment_cap
        """
        agent = make_agent(
            name="A1 Principal",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        a1 = agent["id"]
        v1 = agent["version"]

        # 1.20 is out of range (band 5), over the cap (band 13) and the window is
        # inverted (band 11): the range error must win.
        out_of_range = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "CASH_ADVANCE",
                "recoupment_mode": "PERCENT_OF_RESIDUAL",
                "principal_cents": 100000,
                "recoupment_pct": 1.20,
                "first_recoupment_month": "2026-09",
                "last_recoupment_month": "2026-08",
                "funded_on": "2026-07-01",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        validate_error(out_of_range, ApiErrorId.ERR_INVALID_PCT_RANGE.value)

        over_cap = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "CASH_ADVANCE",
                "recoupment_mode": "PERCENT_OF_RESIDUAL",
                "principal_cents": 100000,
                "recoupment_pct": 0.60,
                "first_recoupment_month": "2026-08",
                "last_recoupment_month": "2027-07",
                "funded_on": "2026-07-01",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        validate_error(over_cap, ApiErrorId.ERR_RECOUPMENT_PCT_EXCEEDS_CAP.value)

        at_cap = api_client.create_agent_advance(
            a1,
            {
                "advance_type": "CASH_ADVANCE",
                "recoupment_mode": "PERCENT_OF_RESIDUAL",
                "principal_cents": 100000,
                "recoupment_pct": 0.50,
                "first_recoupment_month": "2026-08",
                "last_recoupment_month": "2027-07",
                "funded_on": "2026-07-01",
                "expected_agent_version": v1,
            },
            ADMIN,
        )
        advance = validate_success(at_cap, 201)
        assert float(advance["recoupment_pct"]) == 0.50, (
            "the half-of-residual cap is inclusive, so 0.5000 is admitted, got "
            f"{advance['recoupment_pct']!r}"
        )

        after = fetch_agent(a1)
        assert after["version"] == v1 + 1, (
            f"only the accepted funding bumps the agent version, got {after['version']}"
        )
        assert after["advance_outstanding_cents"] == 100000, (
            "advance_outstanding_cents reflects exactly the one accepted advance"
        )


class TestHierarchyShape:
    """The three shape rules that police the agent tree."""

    def test_cycle_and_depth_are_separate_refusals_and_depth_counts_descendants(self):
        """Self- and descendant-parenting are cycles; depth is checked for every descendant.

        PRD: "A `parent_agent_id` that is the agent itself, or any agent reachable by
        following `parent_agent_id` upward from the agent — equivalently, any of the
        agent's own descendants — is `ERR_HIERARCHY_CYCLE` (HTTP 422). And the resulting
        `hierarchy_depth` of the agent, plus that of every one of its descendants after a
        re-parent, may not exceed 4; a write that would push any of them past that depth
        is `ERR_HIERARCHY_DEPTH_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/hierarchy_cycle_and_depth_are_separate_refusals_and_depth_counts_descendants
        """
        # split 0.10 / override 0.90 everywhere, so override monotonicity can never fire.
        def chain_agent(name, parent=None):
            extra = {"parent_agent_id": parent} if parent else {}
            return make_agent(
                name=name,
                split_pct=0.10,
                override_pct=0.90,
                vesting_start_date="2024-01-15",
                **extra,
            )

        a1 = chain_agent("A1 Root")
        a2 = chain_agent("A2", a1["id"])
        a3 = chain_agent("A3", a2["id"])
        a4 = chain_agent("A4", a3["id"])
        a5 = chain_agent("A5", a4["id"])
        b1 = chain_agent("B1 Other Root")
        b2 = chain_agent("B2 Child", b1["id"])

        for agent, expected_depth in ((a1, 0), (a2, 1), (a3, 2), (a4, 3), (a5, 4)):
            assert agent["hierarchy_depth"] == expected_depth, (
                f"{agent['name']} must sit at hierarchy_depth {expected_depth}, got "
                f"{agent['hierarchy_depth']}"
            )
        assert b1["hierarchy_depth"] == 0 and b2["hierarchy_depth"] == 1, (
            "the separate root B1 sits at depth 0 with its child B2 at depth 1"
        )

        self_parent = api_client.update_agent(a1["id"], {"parent_agent_id": a1["id"]}, ADMIN)
        validate_error(self_parent, ApiErrorId.ERR_HIERARCHY_CYCLE.value)

        # A3 is a descendant of A1, so the edge would close a loop.
        descendant_parent = api_client.update_agent(
            a1["id"], {"parent_agent_id": a3["id"]}, ADMIN
        )
        validate_error(descendant_parent, ApiErrorId.ERR_HIERARCHY_CYCLE.value)

        too_deep = api_client.create_agent(
            create_agent_payload(
                name="A6 Too Deep",
                split_pct=0.10,
                override_pct=0.90,
                vesting_start_date="2024-01-15",
                parent_agent_id=a5["id"],
            ),
            ADMIN,
        )
        validate_error(too_deep, ApiErrorId.ERR_HIERARCHY_DEPTH_EXCEEDED.value)

        # B1 alone would reach depth 4, but its descendant B2 would reach 5.
        descendant_too_deep = api_client.update_agent(
            b1["id"], {"parent_agent_id": a4["id"]}, ADMIN
        )
        validate_error(descendant_too_deep, ApiErrorId.ERR_HIERARCHY_DEPTH_EXCEEDED.value)

        untouched = fetch_agent(b1["id"])
        assert untouched["parent_agent_id"] is None, (
            "a refused re-parent leaves parent_agent_id null, got "
            f"{untouched['parent_agent_id']!r}"
        )
        assert untouched["hierarchy_depth"] == 0, (
            f"a refused re-parent leaves hierarchy_depth 0, got {untouched['hierarchy_depth']}"
        )

        moved = validate_success(
            api_client.update_agent(b1["id"], {"parent_agent_id": a3["id"]}, ADMIN)
        )
        assert moved["parent_agent_id"] == a3["id"], "B1 is now parented under A3"
        assert moved["hierarchy_depth"] == 3, (
            f"one greater than A3's depth of 2, got {moved['hierarchy_depth']}"
        )
        child = fetch_agent(b2["id"])
        assert child["hierarchy_depth"] == 4, (
            "a re-parent recomputes hierarchy_depth for every descendant, expected 4, got "
            f"{child['hierarchy_depth']}"
        )

        _rows, meta = list_rows(api_client.list_agents, {"parent_agent_id": a3["id"]}, ADMIN)
        assert meta["total_count"] == 2, (
            f"A3 now has exactly two children (A4 and B1), got {meta['total_count']}"
        )

    def test_override_monotonicity_refuses_the_edge_that_pays_the_upline_nothing(self):
        """The parent's override is compared against the larger of the child's two shares.

        PRD: "For every parent-child edge the write creates or moves, the parent's
        `override_pct` must be greater than or equal to the larger of the child's
        `split_pct` and the child's `override_pct`. An upline tier can never be entitled
        to a smaller cumulative share than the tier beneath it, because the differential
        walk would then pay that tier nothing at all. A violation is
        `ERR_OVERRIDE_PCT_NOT_MONOTONIC` (HTTP 422)."

        Design: Corner/validations/override_monotonicity_refuses_the_edge_that_would_pay_the_upline_nothing
        """
        parent = make_agent(
            name="P Upline",
            split_pct=0.10,
            override_pct=0.40,
            vesting_start_date="2024-01-15",
        )
        movable = make_agent(
            name="C Movable",
            split_pct=0.20,
            override_pct=0.30,
            vesting_start_date="2024-01-15",
        )
        too_rich = make_agent(
            name="D Too Rich",
            split_pct=0.60,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )

        # The child's SPLIT alone exceeds the parent's override, though its own
        # override is smaller.
        big_split = api_client.create_agent(
            create_agent_payload(
                name="E Big Split",
                split_pct=0.50,
                override_pct=0.30,
                vesting_start_date="2024-01-15",
                parent_agent_id=parent["id"],
            ),
            ADMIN,
        )
        validate_error(big_split, ApiErrorId.ERR_OVERRIDE_PCT_NOT_MONOTONIC.value)

        big_override = api_client.create_agent(
            create_agent_payload(
                name="F Big Override",
                split_pct=0.20,
                override_pct=0.45,
                vesting_start_date="2024-01-15",
                parent_agent_id=parent["id"],
            ),
            ADMIN,
        )
        validate_error(big_override, ApiErrorId.ERR_OVERRIDE_PCT_NOT_MONOTONIC.value)

        moved_edge = api_client.update_agent(
            too_rich["id"], {"parent_agent_id": parent["id"]}, ADMIN
        )
        validate_error(moved_edge, ApiErrorId.ERR_OVERRIDE_PCT_NOT_MONOTONIC.value)
        assert fetch_agent(too_rich["id"])["parent_agent_id"] is None, (
            "the refused PATCH leaves D unparented"
        )

        at_equality = validate_success(
            api_client.create_agent(
                create_agent_payload(
                    name="G At Equality",
                    split_pct=0.40,
                    override_pct=0.40,
                    vesting_start_date="2024-01-15",
                    parent_agent_id=parent["id"],
                ),
                ADMIN,
            ),
            201,
        )
        assert at_equality["parent_agent_id"] == parent["id"], (
            "equality between the parent's override and the child's larger share is admitted"
        )
        assert at_equality["hierarchy_depth"] == 1, (
            f"a child of a root sits at depth 1, got {at_equality['hierarchy_depth']}"
        )

        relocated = validate_success(
            api_client.update_agent(movable["id"], {"parent_agent_id": parent["id"]}, ADMIN)
        )
        assert relocated["parent_agent_id"] == parent["id"], "C moves under P"
        assert relocated["hierarchy_depth"] == 1, (
            f"C's recomputed depth is 1, got {relocated['hierarchy_depth']}"
        )

        _rows, meta = list_rows(
            api_client.list_agents, {"parent_agent_id": parent["id"]}, ADMIN
        )
        assert meta["total_count"] == 2, (
            "only the two admitted edges exist under P, expected total_count 2, got "
            f"{meta['total_count']}"
        )


class TestUniquenessAndProgramMembership:
    """The mid, the (batch, merchant) line pair, and the program a line may name."""

    def test_uniqueness_and_program_membership_of_lines_and_mids(self):
        """A mid is unique forever, a line is unique per batch, and a line must match the program.

        PRD: "the processor's own merchant identifier as `mid` — between 4 and 32
        characters, and unique across every merchant row regardless of status. A `mid`
        already in use is refused with `ERR_DUPLICATE_MID` (HTTP 409)."

        PRD: "A processor file states each merchant once per period, so at most one line
        may exist for a given batch and merchant pair; a second attempt is
        `ERR_DUPLICATE_LINE_FOR_MERCHANT` (HTTP 409). The merchant must also be boarded
        on the same program as the batch — its `processor_program_id` must equal the
        batch's `processor_program_id` — and a mismatch is `ERR_LINE_PROGRAM_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/uniqueness_and_program_membership_of_lines_and_mids
        """
        p1 = make_program(name="P1 Atlantic", minimum_billing_mode="NO_MINIMUM")
        p2 = make_program(
            name="P2 Pacific",
            normalization_mode="GROSS_SPLIT",
            minimum_billing_mode="NO_MINIMUM",
        )
        agent = make_agent(
            name="A1 Principal",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        terms = {
            "monthly_minimum_cents": 0,
            "per_transaction_fee_cents": 10,
            "equipment_lease_monthly_cents": 0,
            "boarded_on": "2026-04-10",
        }
        m1 = make_merchant(agent["id"], p1["id"], mid="MID-9001", **terms)
        m2 = make_merchant(agent["id"], p2["id"], mid="MID-9002", **terms)
        activate_merchant(m1["id"])
        activate_merchant(m2["id"])

        b1 = make_batch(
            p1["id"],
            period_month="2026-07",
            coverage_start="2026-07-01",
            coverage_end="2026-08-01",
            file_checksum="sha256:uq-0007",
        )
        add_line(
            b1["id"],
            m1["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=0,
            assessments_cents=0,
            gross_income_cents=45100,
        )
        b2 = make_batch(
            p1["id"],
            period_month="2026-06",
            coverage_start="2026-06-01",
            coverage_end="2026-07-01",
            file_checksum="sha256:uq-0006",
        )

        duplicate_mid = api_client.create_merchant(
            create_merchant_payload(
                agent["id"],
                p1["id"],
                mid="MID-9001",
                monthly_minimum_cents=0,
                per_transaction_fee_cents=10,
                equipment_lease_monthly_cents=0,
                boarded_on="2026-05-01",
            ),
            ADMIN,
        )
        validate_error(duplicate_mid, ApiErrorId.ERR_DUPLICATE_MID.value)

        duplicate_line = api_client.create_residual_line(
            b1["id"],
            create_residual_line_payload(
                m1["id"],
                transaction_count=5,
                sales_volume_cents=1000,
                interchange_cents=0,
                assessments_cents=0,
                gross_income_cents=100,
            ),
            ANALYST,
        )
        validate_error(duplicate_line, ApiErrorId.ERR_DUPLICATE_LINE_FOR_MERCHANT.value)

        # M2 is boarded on P2 and can never be stated in a P1 file.
        wrong_program = api_client.create_residual_line(
            b1["id"],
            create_residual_line_payload(
                m2["id"],
                transaction_count=5,
                sales_volume_cents=1000,
                interchange_cents=0,
                assessments_cents=0,
                gross_income_cents=100,
            ),
            ANALYST,
        )
        validate_error(wrong_program, ApiErrorId.ERR_LINE_PROGRAM_MISMATCH.value)

        after_refusals = fetch_batch(b1["id"])
        assert after_refusals["line_count"] == 1, (
            "none of the three refusals may append a line, expected line_count 1, got "
            f"{after_refusals['line_count']}"
        )
        assert after_refusals["state"] == "RECEIVED", "the batch is untouched and still RECEIVED"

        # The uniqueness scope is (batch, merchant), so M1 may appear in another batch.
        second_batch_line = validate_success(
            api_client.create_residual_line(
                b2["id"],
                create_residual_line_payload(
                    m1["id"],
                    transaction_count=100,
                    sales_volume_cents=1000000,
                    interchange_cents=0,
                    assessments_cents=0,
                    gross_income_cents=35100,
                ),
                ANALYST,
            ),
            201,
        )
        assert second_batch_line["residual_batch_id"] == b2["id"], (
            "the accepted line belongs to the second batch"
        )
        assert second_batch_line["merchant_id"] == m1["id"], (
            "the same merchant may be stated once per batch"
        )

        attrite_merchant(m1["id"], "2026-07-20")
        assert fetch_merchant(m1["id"])["status"] == "ATTRITED", "M1 is now ATTRITED"

        mid_still_taken = api_client.create_merchant(
            create_merchant_payload(
                agent["id"],
                p1["id"],
                mid="MID-9001",
                monthly_minimum_cents=0,
                per_transaction_fee_cents=10,
                equipment_lease_monthly_cents=0,
                boarded_on="2026-05-01",
            ),
            ADMIN,
        )
        validate_error(mid_still_taken, ApiErrorId.ERR_DUPLICATE_MID.value)

        _rows, meta = list_rows(
            api_client.list_merchants, {"owning_agent_id": agent["id"]}, ADMIN
        )
        assert meta["total_count"] == 2, (
            f"no refused boarding created a merchant row, got {meta['total_count']}"
        )


class TestMerchantLifecycleDates:
    """Attrition and reactivation are bounded on both sides by the logical clock."""

    def test_merchant_lifecycle_dates_are_clock_bounded_on_both_sides(self):
        """Four out-of-range dates are refused; a date exactly on the clock is admitted.

        PRD: "Closing a merchant moves it from `ACTIVE` to `ATTRITED` and takes an
        `attrition_date` in the payload. That date must be on or after the merchant's
        `boarded_on` and no later than the logical clock's current date; a date outside
        those bounds is `ERR_MERCHANT_DATE_OUT_OF_RANGE` (HTTP 422)."

        PRD: "The payload carries a `reactivation_date` that must be on or after the
        merchant's `attrition_date` and no later than the logical clock's current date;
        otherwise `ERR_MERCHANT_DATE_OUT_OF_RANGE`."

        Design: Corner/validations/merchant_lifecycle_dates_are_clock_bounded_on_both_sides
        """
        program = make_program(
            name="Atlantic Net Program", minimum_billing_mode="NO_MINIMUM"
        )
        agent = make_agent(
            name="A1 Principal",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        terms = {
            "monthly_minimum_cents": 0,
            "per_transaction_fee_cents": 10,
            "equipment_lease_monthly_cents": 0,
            "boarded_on": "2026-04-10",
        }
        m1 = make_merchant(agent["id"], program["id"], mid="MID-9001", **terms)
        m2 = make_merchant(agent["id"], program["id"], mid="MID-9002", **terms)
        activate_merchant(m1["id"])
        activate_merchant(m2["id"])

        before_boarding = api_client.attrite_merchant(
            m1["id"], attrite_merchant_payload("2026-04-01"), ADMIN
        )
        validate_error(before_boarding, ApiErrorId.ERR_MERCHANT_DATE_OUT_OF_RANGE.value)

        after_clock = api_client.attrite_merchant(
            m1["id"], attrite_merchant_payload("2026-09-01"), ADMIN
        )
        validate_error(after_clock, ApiErrorId.ERR_MERCHANT_DATE_OUT_OF_RANGE.value)

        untouched = fetch_merchant(m1["id"])
        assert untouched["status"] == "ACTIVE", (
            f"a refused attrition leaves the merchant ACTIVE, got {untouched['status']}"
        )
        assert untouched["attrition_date"] is None, (
            f"a refused attrition writes no date, got {untouched['attrition_date']!r}"
        )

        attrited = attrite_merchant(m1["id"], "2026-07-20")
        assert attrited["status"] == "ATTRITED", "the in-range attrition is accepted"
        assert attrited["attrition_date"] == "2026-07-20", "the supplied date is written"
        assert attrited["clawed_back_bonus_cents"] == 0, (
            "there was no upfront bonus, so nothing is clawed back"
        )
        held_agent = fetch_agent(agent["id"])
        assert held_agent["portfolio_attrition_bps"] == 5000, (
            "one attrited merchant out of two qualifying merchants is 5,000 bps, got "
            f"{held_agent['portfolio_attrition_bps']}"
        )
        assert held_agent["residual_hold"] is True, (
            "5,000 bps is at or above the 2,500-bps threshold, so the risk hold is set"
        )

        reactivate_before_attrition = api_client.reactivate_merchant(
            m1["id"], reactivate_merchant_payload("2026-07-19"), ADMIN
        )
        validate_error(
            reactivate_before_attrition, ApiErrorId.ERR_MERCHANT_DATE_OUT_OF_RANGE.value
        )

        reactivate_after_clock = api_client.reactivate_merchant(
            m1["id"], reactivate_merchant_payload("2026-09-01"), ADMIN
        )
        validate_error(
            reactivate_after_clock, ApiErrorId.ERR_MERCHANT_DATE_OUT_OF_RANGE.value
        )
        assert fetch_merchant(m1["id"])["status"] == "ATTRITED", (
            "both refused reactivations leave the merchant ATTRITED"
        )

        reactivated = reactivate_merchant(m1["id"], "2026-07-25")
        assert reactivated["status"] == "ACTIVE", "the in-range reactivation is accepted"
        assert reactivated["reactivation_date"] == "2026-07-25", (
            "the supplied reactivation date is written"
        )
        released_agent = fetch_agent(agent["id"])
        assert released_agent["portfolio_attrition_bps"] == 0, (
            "with no attrited merchants left the rate falls to 0, got "
            f"{released_agent['portfolio_attrition_bps']}"
        )
        assert released_agent["residual_hold"] is False, (
            "below 2,500 bps the agent-level risk flag clears"
        )

        # 2026-08-01 is exactly the logical clock's current date: inside the range.
        on_the_clock = attrite_merchant(m2["id"], "2026-08-01")
        assert on_the_clock["status"] == "ATTRITED", (
            "an attrition dated exactly on the clock is admitted"
        )
        assert on_the_clock["attrition_date"] == "2026-08-01", (
            f"the clock-dated attrition is stored, got {on_the_clock['attrition_date']!r}"
        )
