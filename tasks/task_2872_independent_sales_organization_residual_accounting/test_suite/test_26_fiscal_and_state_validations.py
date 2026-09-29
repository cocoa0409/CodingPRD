"""Fiscal ceilings, sign discipline, state precedence and the payout floor.

Every test builds all of its own state through the public endpoints. The logical
clock starts at 2026-08-01T00:00:00Z and no test in this module moves it.
"""

from test_helpers import (
    ADMIN,
    ANALYST_ONE,
    ANALYST_ONE_ID,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_merchant,
    add_line,
    api_client,
    attrite_merchant,
    create_adjustment_payload,
    depart_agent,
    fetch_advance,
    fetch_agent,
    fetch_merchant,
    fetch_statement,
    fetch_statement_by_id,
    file_notice,
    issue_statement,
    list_rows,
    make_agent,
    make_batch,
    make_merchant,
    make_program,
    make_residual_controller_headers,
    normalize_batch,
    post_batch,
    settle_payload,
    transfer_portfolio_payload,
    validate_error,
    validate_success,
)

CONTROLLER_APPROVER = make_residual_controller_headers("controller-1")

MERCHANT_TERMS = {
    "monthly_minimum_cents": 0,
    "per_transaction_fee_cents": 10,
    "equipment_lease_monthly_cents": 0,
    "boarded_on": "2026-04-10",
}


def _percent_advance(**overrides) -> dict:
    payload = {
        "advance_type": "CASH_ADVANCE",
        "recoupment_mode": "PERCENT_OF_RESIDUAL",
        "principal_cents": 100000,
        "recoupment_pct": 0.40,
        "first_recoupment_month": "2026-08",
        "last_recoupment_month": "2027-07",
        "funded_on": "2026-07-01",
    }
    payload.update(overrides)
    return payload


class TestAdvanceExposureCeiling:
    """The aggregate exposure ceiling and its bootstrap floor."""

    def test_exposure_ceiling_is_aggregate_and_lands_exactly_on_the_bootstrap_floor(self):
        """A trivially small second advance is refused for the portfolio total, 250,000 admitted.

        PRD: "And the agent's total exposure is capped: the sum of `outstanding_cents`
        over that agent's advances whose `state` is `ACTIVE`, plus the new
        `principal_cents`, may not exceed the larger of a bootstrap floor of 250,000
        cents — two thousand five hundred dollars, the allowance that lets a brand-new
        agent with no production history be funded at all — and six times the agent's
        `trailing_residual_cents`. Exceeding it is `ERR_ADVANCE_EXPOSURE_EXCEEDED`
        (HTTP 409)."

        Design: Corner/validations/advance_exposure_ceiling_is_aggregate_and_lands_exactly_on_the_bootstrap_floor
        """
        agent = make_agent(
            name="A1 Principal",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        a1 = agent["id"]
        assert agent["trailing_residual_cents"] == 0, (
            "a brand-new agent has no production history, so the ceiling is the "
            "250,000-cent bootstrap floor rather than six times zero"
        )

        first = validate_success(
            api_client.create_agent_advance(
                a1,
                _percent_advance(
                    principal_cents=200000, expected_agent_version=agent["version"]
                ),
                ADMIN,
            ),
            201,
        )
        assert first["outstanding_cents"] == 200000, "the first advance is fully outstanding"

        after_first = fetch_agent(a1)
        v2 = after_first["version"]
        assert after_first["trailing_residual_cents"] == 0, (
            "funding an advance does not create production, so the ceiling stays 250,000"
        )

        # 60,000 is individually trivial, but 200,000 + 60,000 = 260,000 in aggregate.
        over_ceiling = api_client.create_agent_advance(
            a1, _percent_advance(principal_cents=60000, expected_agent_version=v2), ADMIN
        )
        validate_error(over_ceiling, ApiErrorId.ERR_ADVANCE_EXPOSURE_EXCEEDED.value)
        assert fetch_agent(a1)["version"] == v2, (
            "the refused funding must not bump the agent version, which is why the next "
            "request may reuse the same expected_agent_version"
        )

        # 200,000 + 50,000 lands exactly on the ceiling, and the comparison is inclusive.
        accepted = validate_success(
            api_client.create_agent_advance(
                a1, _percent_advance(principal_cents=50000, expected_agent_version=v2), ADMIN
            ),
            201,
        )
        assert accepted["principal_cents"] == 50000, "the admitted principal is 50,000 cents"
        assert accepted["outstanding_cents"] == 50000, (
            "outstanding_cents starts equal to principal_cents"
        )
        assert accepted["state"] == "ACTIVE", "a funded advance starts ACTIVE"

        final_agent = fetch_agent(a1)
        assert final_agent["advance_outstanding_cents"] == 250000, (
            "exposure exactly at the ceiling is admitted, expected 250000, got "
            f"{final_agent['advance_outstanding_cents']}"
        )

        rows, meta = list_rows(
            api_client.list_agent_advances, {"agent_id": a1, "state": "ACTIVE"}, ADMIN
        )
        assert meta["total_count"] == 2, (
            f"only the two admitted advances exist, got {meta['total_count']}"
        )
        assert [row["outstanding_cents"] for row in rows] == [200000, 50000], (
            "list results are ordered by created_at ascending, so the 200,000 advance "
            f"comes first, got {[row['outstanding_cents'] for row in rows]}"
        )


class TestAdjustmentFiscalGuards:
    """Sign discipline and the clawback-reversal ceiling on a proposal."""

    def test_adjustment_sign_discipline_owns_the_zero_case(self):
        """A wrong sign either way, and amount_cents 0, all report the sign error.

        PRD: "Sign discipline is absolute and is checked on every proposal.
        `amount_cents` may never be zero. It must be strictly positive for
        `DISPUTE_CREDIT`, `CLAWBACK_REVERSAL` and `VESTED_BUYOUT`, and strictly negative
        for `MANUAL_DEBIT` and `BONUS_CLAWBACK`. A zero amount, or a sign that
        contradicts the kind, is `ERR_ADJUSTMENT_SIGN_INVALID` (HTTP 422)."

        PRD: "No money moves at proposal time — the statement's `adjustment_cents` counts
        only `APPLIED` rows — but the parent statement's `version` is nonetheless bumped".

        Design: Corner/validations/adjustment_sign_discipline_owns_the_zero_case
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
        merchant = make_merchant(
            agent["id"],
            program["id"],
            mid="MID-9001",
            monthly_minimum_cents=0,
            per_transaction_fee_cents=10,
            equipment_lease_monthly_cents=1000,
            boarded_on="2026-04-10",
        )
        activate_merchant(merchant["id"])
        batch = make_batch(
            program["id"],
            period_month="2026-07",
            coverage_start="2026-07-01",
            coverage_end="2026-08-01",
            file_checksum="sha256:sg-0001",
        )
        add_line(
            batch["id"],
            merchant["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=20000,
            assessments_cents=1300,
            gross_income_cents=40000,
        )
        normalize_batch(batch["id"])
        post_batch(batch["id"])

        statement = fetch_statement(agent["id"], "2026-07")
        assert statement is not None, "the posting cascade creates the agent's DRAFT statement"
        st = statement["id"]
        sv = statement["version"]
        assert statement["direct_residual_cents"] == 6300, (
            "the direct split of this period, expected 6300, got "
            f"{statement['direct_residual_cents']}"
        )

        wrong_sign_credit = api_client.create_statement_adjustment(
            st,
            create_adjustment_payload(
                sv, kind="DISPUTE_CREDIT", amount_cents=-500, reason="wrong direction"
            ),
            ANALYST_ONE,
        )
        validate_error(wrong_sign_credit, ApiErrorId.ERR_ADJUSTMENT_SIGN_INVALID.value)

        wrong_sign_debit = api_client.create_statement_adjustment(
            st,
            create_adjustment_payload(
                sv, kind="MANUAL_DEBIT", amount_cents=500, reason="wrong direction"
            ),
            ANALYST_ONE,
        )
        validate_error(wrong_sign_debit, ApiErrorId.ERR_ADJUSTMENT_SIGN_INVALID.value)

        # Zero is a well-typed integer, so the non-zero clause of the sign rule is what
        # refuses it.
        zero_amount = api_client.create_statement_adjustment(
            st,
            create_adjustment_payload(
                sv, kind="DISPUTE_CREDIT", amount_cents=0, reason="no amount"
            ),
            ANALYST_ONE,
        )
        validate_error(zero_amount, ApiErrorId.ERR_ADJUSTMENT_SIGN_INVALID.value)

        accepted = validate_success(
            api_client.create_statement_adjustment(
                st,
                create_adjustment_payload(
                    sv,
                    kind="DISPUTE_CREDIT",
                    amount_cents=500,
                    reason="chargeback reversed by issuer",
                ),
                ANALYST_ONE,
            ),
            201,
        )
        assert accepted["state"] == "PROPOSED", (
            f"a client-proposed adjustment is created PROPOSED, got {accepted['state']}"
        )
        assert accepted["amount_cents"] == 500, "the admitted amount is +500 cents"
        assert accepted["created_by_user_id"] == ANALYST_ONE_ID, (
            "created_by_user_id records the proposing principal, expected "
            f"{ANALYST_ONE_ID!r}, got {accepted['created_by_user_id']!r}"
        )
        assert accepted["approved_by_user_id"] is None, (
            "no approver has acted yet, so approved_by_user_id is null"
        )
        assert accepted["version"] == 1, "a freshly created adjustment carries version 1"

        after = fetch_statement_by_id(st)
        assert after["adjustment_cents"] == 0, (
            "only APPLIED adjustments feed adjustment_cents, got "
            f"{after['adjustment_cents']}"
        )
        assert after["net_payable_cents"] == 6300, (
            f"a PROPOSED adjustment moves no money, expected 6300, got {after['net_payable_cents']}"
        )
        assert after["direct_residual_cents"] == 6300, "the direct residual is unchanged"
        assert after["version"] == sv + 1, (
            "only the accepted proposal bumps the statement version, expected "
            f"{sv + 1}, got {after['version']}"
        )

    def test_clawback_reversal_may_not_exceed_lifetime_clawback(self):
        """One cent over the agent's lifetime clawback is refused; exactly the figure applies.

        PRD: "One further ceiling guards the reversal kind: a `CLAWBACK_REVERSAL` may not
        give back more than was taken, so its `amount_cents` may not exceed the owning
        agent's `lifetime_clawback_cents`; a larger figure is
        `ERR_CLAWBACK_REVERSAL_EXCEEDS_CLAWBACK` (HTTP 409)."

        Design: Corner/validations/clawback_reversal_may_not_exceed_lifetime_clawback
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
        merchant = make_merchant(
            agent["id"],
            program["id"],
            mid="MID-9001",
            upfront_bonus_cents=27000,
            **MERCHANT_TERMS,
        )
        activate_merchant(merchant["id"])
        # 82 active days inside the 270-day retention window.
        attrite_merchant(merchant["id"], "2026-07-01")

        assert fetch_merchant(merchant["id"])["clawed_back_bonus_cents"] == 18800, (
            "the merchant's clawed-back bonus is 18800 cents"
        )
        assert fetch_agent(agent["id"])["lifetime_clawback_cents"] == 18800, (
            "the agent-level counter matches the single clawback, expected 18800"
        )

        statement = fetch_statement(agent["id"], "2026-07")
        assert statement is not None, (
            "the clawback cascade upserts the agent's statement for the attrition month"
        )
        st = statement["id"]
        sv = statement["version"]

        one_cent_over = api_client.create_statement_adjustment(
            st,
            create_adjustment_payload(
                sv,
                kind="CLAWBACK_REVERSAL",
                amount_cents=18801,
                reason="merchant re-signed, one cent too much",
            ),
            ANALYST_ONE,
        )
        validate_error(
            one_cent_over, ApiErrorId.ERR_CLAWBACK_REVERSAL_EXCEEDS_CLAWBACK.value
        )

        proposed = validate_success(
            api_client.create_statement_adjustment(
                st,
                create_adjustment_payload(
                    sv,
                    kind="CLAWBACK_REVERSAL",
                    amount_cents=18800,
                    reason="merchant re-signed under a new MID",
                ),
                ANALYST_ONE,
            ),
            201,
        )
        assert proposed["kind"] == "CLAWBACK_REVERSAL", "the admitted kind is the reversal"
        assert proposed["amount_cents"] == 18800, (
            "exactly the lifetime figure is admitted, so the ceiling is inclusive"
        )
        assert proposed["state"] == "PROPOSED", "the reversal enters the review cycle"

        validate_success(
            api_client.review_statement_adjustment(proposed["id"], CONTROLLER_APPROVER)
        )
        applied = validate_success(
            api_client.approve_statement_adjustment(proposed["id"], CONTROLLER_APPROVER)
        )
        assert applied["state"] == "APPLIED", f"the approval applies it, got {applied['state']}"
        assert applied["approved_by_user_id"] == "controller-1", (
            "approved_by_user_id records the approving principal, got "
            f"{applied['approved_by_user_id']!r}"
        )

        after = fetch_statement_by_id(st)
        assert after["adjustment_cents"] == 0, (
            "the -18800 clawback and the +18800 reversal net to zero, got "
            f"{after['adjustment_cents']}"
        )
        assert after["net_payable_cents"] == 0, "there is nothing left to pay"
        assert after["carry_forward_deficit_cents"] == 0, (
            "the earlier deficit is erased, got "
            f"{after['carry_forward_deficit_cents']}"
        )
        assert fetch_agent(agent["id"])["lifetime_clawback_cents"] == 0, (
            "the agent-level counter nets back to 0"
        )


class TestRestructurePrecedence:
    """The state check, the conditional shape rule and the window rule on one endpoint."""

    def test_restructure_reports_advance_state_before_the_conditional_shape_rule(self):
        """A RECOUPED advance reports its state even when the patch is also shape-incomplete.

        PRD: "An advance whose `state` is `RECOUPED` is closed and may not be
        restructured: that is `ERR_ADVANCE_STATE_INVALID` (HTTP 409), and it is reported
        ahead of any shape complaint about the patch itself. For an advance that is
        `ACTIVE`, a shape rule then applies to the *result* of the patch: if the resulting
        `recoupment_mode` is `STRAIGHT_LINE_AMORTIZATION` the advance must have an
        `amortization_months` after the patch is applied, and if it is
        `PERCENT_OF_RESIDUAL` the advance must have a `recoupment_pct` after the patch is
        applied; a patch that leaves the advance without the field its mode requires is
        `ERR_INVALID_REQUEST`. The window shape rule and the half-of-residual cap are both
        re-evaluated against the restructured terms."

        Design: Corner/validations/restructure_reports_advance_state_before_the_conditional_shape_rule
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
        a1 = agent["id"]

        advance_a = validate_success(
            api_client.create_agent_advance(
                a1,
                _percent_advance(
                    principal_cents=5000,
                    recoupment_pct=0.50,
                    first_recoupment_month="2026-07",
                    last_recoupment_month="2027-06",
                    funded_on="2026-06-01",
                    expected_agent_version=agent["version"],
                ),
                ADMIN,
            ),
            201,
        )
        advance_b = validate_success(
            api_client.create_agent_advance(
                a1,
                _percent_advance(
                    principal_cents=100000,
                    recoupment_pct=0.30,
                    first_recoupment_month="2026-09",
                    last_recoupment_month="2027-08",
                    funded_on="2026-08-01",
                    expected_agent_version=fetch_agent(a1)["version"],
                ),
                ADMIN,
            ),
            201,
        )

        merchant = make_merchant(a1, program["id"], mid="MID-9001", **MERCHANT_TERMS)
        activate_merchant(merchant["id"])
        batch = make_batch(
            program["id"],
            period_month="2026-07",
            coverage_start="2026-07-01",
            coverage_end="2026-08-01",
            file_checksum="sha256:rs-0001",
        )
        add_line(
            batch["id"],
            merchant["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=0,
            assessments_cents=0,
            gross_income_cents=45100,
        )
        normalize_batch(batch["id"])
        post_batch(batch["id"])
        statement = issue_statement(fetch_statement(a1, "2026-07")["id"])

        recouped = fetch_advance(advance_a["id"])
        assert recouped["state"] == "RECOUPED", (
            f"the issue repaid the first advance in full, got {recouped['state']}"
        )
        assert recouped["outstanding_cents"] == 0, "nothing is left outstanding"
        assert recouped["cumulative_recouped_cents"] == 5000, (
            f"the whole 5000-cent principal was taken, got {recouped['cumulative_recouped_cents']}"
        )
        assert recouped["months_recouped"] == 1, "one accounting month has been recouped from"
        assert statement["advance_recoupment_cents"] == 5000, (
            f"the statement gave up 5000 cents, got {statement['advance_recoupment_cents']}"
        )
        assert statement["net_payable_cents"] == 15000, (
            f"20000 gross less 5000 recouped, got {statement['net_payable_cents']}"
        )

        still_active = fetch_advance(advance_b["id"])
        assert still_active["state"] == "ACTIVE", (
            "the second advance's window opens in 2026-09, so it contributed nothing"
        )
        assert still_active["outstanding_cents"] == 100000, "its principal is untouched"
        assert still_active["months_recouped"] == 0, "it has never been recouped from"

        # The same shape-incomplete patch: state first on the RECOUPED advance...
        state_wins = api_client.restructure_agent_advance(
            advance_a["id"], {"recoupment_mode": "STRAIGHT_LINE_AMORTIZATION"}, ADMIN
        )
        validate_error(state_wins, ApiErrorId.ERR_ADVANCE_STATE_INVALID.value)

        # ...and the shape rule on the ACTIVE one.
        shape_fails = api_client.restructure_agent_advance(
            advance_b["id"], {"recoupment_mode": "STRAIGHT_LINE_AMORTIZATION"}, ADMIN
        )
        validate_error(shape_fails, ApiErrorId.ERR_INVALID_REQUEST.value)

        restructured = validate_success(
            api_client.restructure_agent_advance(
                advance_b["id"],
                {
                    "recoupment_mode": "STRAIGHT_LINE_AMORTIZATION",
                    "amortization_months": 12,
                    "last_recoupment_month": "2027-08",
                },
                ADMIN,
            )
        )
        assert restructured["recoupment_mode"] == "STRAIGHT_LINE_AMORTIZATION", (
            "the advance switched variant"
        )
        assert restructured["amortization_months"] == 12, (
            "[2026-09, 2027-08] is exactly twelve inclusive months"
        )
        assert restructured["last_recoupment_month"] == "2027-08", (
            "the window end is unchanged by the switch"
        )

        window_fails = api_client.restructure_agent_advance(
            advance_b["id"], {"amortization_months": 11}, ADMIN
        )
        validate_error(window_fails, ApiErrorId.ERR_RECOUPMENT_WINDOW_INVALID.value)

        untouched = fetch_advance(advance_a["id"])
        assert untouched["recoupment_mode"] == "PERCENT_OF_RESIDUAL", (
            "the refused restructure never mutated the closed advance"
        )
        assert float(untouched["recoupment_pct"]) == 0.50, (
            f"its recoupment_pct is still 0.50, got {untouched['recoupment_pct']!r}"
        )


class TestPayoutFloor:
    """The settlement floor, one cent either side of it."""

    def test_payout_floor_refuses_one_cent_below_and_admits_the_floor_exactly(self):
        """2,499 cents cannot be settled; 2,500 cents can.

        PRD: "And the statement's `net_payable_cents` must be at least 2,500 cents —
        twenty-five dollars — or the settlement is `ERR_BELOW_MIN_PAYOUT` (HTTP 409);
        balances below the floor stay unsettled and roll into the next period through the
        opening-deficit mechanism."

        Design: Corner/validations/payout_floor_refuses_one_cent_below_and_admits_the_floor_exactly
        """
        program = make_program(
            name="Atlantic Net Program", minimum_billing_mode="NO_MINIMUM"
        )
        below = make_agent(
            name="A1 Below Floor",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        at_floor = make_agent(
            name="A2 At Floor",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        m1 = make_merchant(below["id"], program["id"], mid="MID-9001", **MERCHANT_TERMS)
        m2 = make_merchant(at_floor["id"], program["id"], mid="MID-9002", **MERCHANT_TERMS)
        activate_merchant(m1["id"])
        activate_merchant(m2["id"])

        batch = make_batch(
            program["id"],
            period_month="2026-07",
            coverage_start="2026-07-01",
            coverage_end="2026-08-01",
            file_checksum="sha256:fl-0001",
        )
        # Identical processor cost on both lines, so the gross income difference of two
        # cents is the whole difference between the two split bases.
        add_line(
            batch["id"],
            m1["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=0,
            assessments_cents=0,
            gross_income_cents=10098,
        )
        add_line(
            batch["id"],
            m2["id"],
            transaction_count=100,
            sales_volume_cents=1000000,
            interchange_cents=0,
            assessments_cents=0,
            gross_income_cents=10100,
        )
        normalize_batch(batch["id"])
        post_batch(batch["id"])

        st1 = issue_statement(fetch_statement(below["id"], "2026-07")["id"])
        st2 = issue_statement(fetch_statement(at_floor["id"], "2026-07")["id"])
        assert st1["net_payable_cents"] == 2499, (
            f"one cent under the floor, got {st1['net_payable_cents']}"
        )
        assert st2["net_payable_cents"] == 2500, (
            f"exactly the floor, got {st2['net_payable_cents']}"
        )
        for statement in (st1, st2):
            assert statement["lifecycle_state"] == "ISSUED", "both statements are ISSUED"
            assert statement["settlement_state"] == "UNSETTLED", "both are still UNSETTLED"

        refused = api_client.settle_agent_statement(
            st1["id"], settle_payload("2026-08-01"), CONTROLLER_APPROVER
        )
        validate_error(refused, ApiErrorId.ERR_BELOW_MIN_PAYOUT.value)

        unchanged = fetch_statement_by_id(st1["id"])
        assert unchanged["settlement_state"] == "UNSETTLED", (
            "the refused settlement leaves the payment dimension alone, got "
            f"{unchanged['settlement_state']}"
        )
        assert unchanged["paid_on"] is None, (
            f"no payment date is recorded, got {unchanged['paid_on']!r}"
        )
        assert unchanged["lifecycle_state"] == "ISSUED", "the authoring dimension is untouched"
        assert unchanged["carry_forward_deficit_cents"] == 0, (
            "an unsettleable positive balance is not turned into a deficit by the attempt, "
            f"got {unchanged['carry_forward_deficit_cents']}"
        )

        settled = validate_success(
            api_client.settle_agent_statement(
                st2["id"], settle_payload("2026-08-01"), CONTROLLER_APPROVER
            )
        )
        assert settled["settlement_state"] == "SETTLED", (
            f"the floor is inclusive, got {settled['settlement_state']}"
        )
        assert settled["paid_on"] == "2026-08-01", (
            f"the supplied payment date is recorded, got {settled['paid_on']!r}"
        )


class TestTransferTarget:
    """The three legs of the transfer-target rule, and the reference rule that outranks it."""

    def test_transfer_target_must_be_a_different_active_agent(self):
        """Self and non-ACTIVE targets are refused; a missing one is refused earlier.

        PRD: "The target must exist, must have `status` `ACTIVE`, and must not be the
        departing agent itself; any of those failures is `ERR_TRANSFER_TARGET_INVALID`
        (HTTP 422). The transfer is only available from `DEPARTED` — from anywhere else it
        is `ERR_AGENT_STATE_INVALID` — and it does not change the departing agent's status,
        which stays `DEPARTED`. The cascade is conditional: every merchant owned by the
        departing agent whose `status` is `PENDING` or `ACTIVE` has its `owning_agent_id`
        re-pointed to the target and its `version` bumped, while merchants whose `status`
        is `ATTRITED` deliberately keep the departing agent for audit."

        Design: Corner/validations/transfer_target_must_be_a_different_active_agent
        """
        program = make_program(
            name="Atlantic Net Program", minimum_billing_mode="NO_MINIMUM"
        )
        departing = make_agent(
            name="A1 Departing",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        receiver = make_agent(
            name="A2 Receiver",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        also_leaving = make_agent(
            name="A3 Also Leaving",
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )
        a1, a2, a3 = departing["id"], receiver["id"], also_leaving["id"]

        merchant = make_merchant(a1, program["id"], mid="MID-9001", **MERCHANT_TERMS)
        activate_merchant(merchant["id"])

        file_notice(a3, "2026-08-01")
        file_notice(a1, "2026-08-01")
        depart_agent(a1)

        assert fetch_agent(a1)["status"] == "DEPARTED", "the book being handed over is departed"
        assert fetch_agent(a2)["status"] == "ACTIVE", "only the receiver is ACTIVE"
        assert fetch_agent(a3)["status"] == "DEPARTURE_NOTICE", (
            f"the third agent is mid-notice, got {fetch_agent(a3)['status']}"
        )

        to_itself = api_client.transfer_agent_portfolio(
            a1, transfer_portfolio_payload(a1), ADMIN
        )
        validate_error(to_itself, ApiErrorId.ERR_TRANSFER_TARGET_INVALID.value)

        to_non_active = api_client.transfer_agent_portfolio(
            a1, transfer_portfolio_payload(a3), ADMIN
        )
        validate_error(to_non_active, ApiErrorId.ERR_TRANSFER_TARGET_INVALID.value)

        # A target that names no agent at all is caught by the body-reference rule, which
        # is consulted before the target rule.
        to_nobody = api_client.transfer_agent_portfolio(
            a1, transfer_portfolio_payload(NON_EXISTENT_UUID), ADMIN
        )
        validate_error(to_nobody, ApiErrorId.ERR_REFERENCED_AGENT_NOT_FOUND.value)

        still_owned = fetch_merchant(merchant["id"])
        assert still_owned["owning_agent_id"] == a1, (
            "none of the three refusals moved the merchant, got "
            f"{still_owned['owning_agent_id']}"
        )
        version_before = still_owned["version"]

        validate_success(
            api_client.transfer_agent_portfolio(
                a1, transfer_portfolio_payload(a2), ADMIN
            )
        )
        moved = fetch_merchant(merchant["id"])
        assert moved["owning_agent_id"] == a2, (
            f"the ACTIVE merchant is re-pointed to the receiver, got {moved['owning_agent_id']}"
        )
        assert moved["version"] == version_before + 1, (
            f"the moved merchant's version is bumped, expected {version_before + 1}, "
            f"got {moved['version']}"
        )
        assert fetch_agent(a1)["portfolio_merchant_count"] == 0, (
            "the departing agent's book is empty after the transfer"
        )
        assert fetch_agent(a2)["portfolio_merchant_count"] == 1, (
            "the receiver now carries the merchant"
        )
        assert fetch_agent(a1)["status"] == "DEPARTED", (
            "the transfer leaves the departing agent DEPARTED"
        )
