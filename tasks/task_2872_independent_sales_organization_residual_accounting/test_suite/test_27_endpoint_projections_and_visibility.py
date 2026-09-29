"""Endpoint projections, computed reads and the immediacy of the posting cascade.

Every test in this module builds its own world through the public endpoints and
then reads it back through the projection the PRD promises: the amendable field
list of a processor program, the ten-field portfolio snapshot, the two-ended
reassignment link, the chargeback event collection with its composing filters,
the clock-derived vesting percentage, and the four-link post cascade that must
be final the instant the post returns.
"""

from test_helpers import (
    ADMIN_ONE,
    ANALYST_ONE,
    CONTROLLER_ONE,
    NON_EXISTENT_UUID,
    ApiErrorId,
    activate_merchant,
    add_line,
    api_client,
    assert_agent_portfolio_summary,
    assert_chargeback_event,
    assert_profitability_bottom_lines,
    assert_residual_allocation,
    assert_statement_money_lines_consistent,
    attrite_merchant,
    checksum,
    fetch_agent,
    fetch_merchant,
    fetch_line,
    fetch_statement,
    file_notice,
    fund_percent_advance,
    make_agent,
    make_batch,
    make_merchant,
    make_program,
    normalize_batch,
    post_batch,
    reassign_agent_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# The processor economics every scenario in this module is priced against.
PROGRAM_TERMS = {
    "name": "Atlantic Net Program",
    "buy_rate_bps": 45,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 13,
    "normalization_mode": "NET_REVENUE_SPLIT",
    "minimum_billing_mode": "NO_MINIMUM",
}

# A round processor file line: 100 authorizations on 1,000,000 cents of volume.
ROUND_LINE = {
    "transaction_count": 100,
    "sales_volume_cents": 1000000,
    "interchange_cents": 0,
    "assessments_cents": 0,
    "gross_income_cents": 45100,
}

AMENDABLE_PROGRAM_FIELDS = {
    "name": "Atlantic Net Program v2",
    "buy_rate_bps": 90,
    "buy_rate_per_item_cents": 6,
    "assessment_bps": 20,
    "minimum_billing_mode": "SHORTFALL_BILLED",
}

PORTFOLIO_SUMMARY_FIELDS = {
    "agent_id",
    "portfolio_merchant_count",
    "active_merchant_count",
    "attrited_merchant_count",
    "portfolio_attrition_bps",
    "residual_hold",
    "vested_pct",
    "trailing_residual_cents",
    "advance_outstanding_cents",
    "lifetime_clawback_cents",
}


class TestProgramAmendmentProjection:
    """PATCH /processor-programs/{id} touches only the declared fields."""

    def test_patch_writes_the_five_amendable_fields_and_leaves_the_variant_alone(self):
        """Amending a program moves name, both buy-rate terms, the assessment rate and the minimum billing mode, and nothing else.

        PRD: "An `IsoAdmin` may amend `name`, `buy_rate_bps`, `buy_rate_per_item_cents`, `assessment_bps` and `minimum_billing_mode` at any time"
        PRD: "it selects which of the two buy-rate normalization variants applies to each residual line, and it cannot be amended afterwards."

        Design: Corner/endpoints/program_patch_touches_only_declared_fields_and_is_never_retroactive
        """
        program = make_program(**PROGRAM_TERMS)
        assert program["version"] == 1, "a freshly registered program starts at version 1"
        assert program["status"] == "ACTIVE", "a newly registered program begins ACTIVE"
        assert program["posted_batch_count"] == 0, "posted_batch_count starts at 0"

        patched = validate_success(
            api_client.update_processor_program(
                program["id"], dict(AMENDABLE_PROGRAM_FIELDS), ADMIN_ONE
            )
        )
        assert patched["name"] == "Atlantic Net Program v2", "name is amendable"
        assert patched["buy_rate_bps"] == 90, "buy_rate_bps is amendable"
        assert patched["buy_rate_per_item_cents"] == 6, "buy_rate_per_item_cents is amendable"
        assert patched["assessment_bps"] == 20, "assessment_bps is amendable"
        assert patched["minimum_billing_mode"] == "SHORTFALL_BILLED", (
            "minimum_billing_mode is amendable"
        )
        assert patched["normalization_mode"] == "NET_REVENUE_SPLIT", (
            "normalization_mode is absent from the amendable field list, so the "
            "split variant survives the amendment untouched"
        )
        assert patched["version"] == 2, (
            f"one mutation advances version by exactly 1, got {patched['version']}"
        )
        assert patched["status"] == "ACTIVE", "an amendment is not a suspension"
        assert patched["posted_batch_count"] == 0, (
            "posted_batch_count counts posted batches, not amendments"
        )

    def test_buy_rate_amendment_never_rewrites_the_line_already_normalized(self):
        """A June line normalized at 45 bps keeps its 5,100-cent cost and its 20,000-cent allocation after the buy rate doubles, while the July line prices at 90 bps.

        PRD: "amendments are never retroactive, and residual lines that were already normalized keep the values computed at their normalization instant"

        Design: Corner/endpoints/program_patch_touches_only_declared_fields_and_is_never_retroactive
        """
        program = make_program(**PROGRAM_TERMS)
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
            equipment_lease_monthly_cents=0,
            boarded_on="2026-04-10",
        )
        activate_merchant(merchant["id"])

        june_batch = make_batch(
            program["id"],
            period_month="2026-06",
            coverage_start="2026-06-01",
            coverage_end="2026-07-01",
            file_checksum=checksum("pp-0006"),
        )
        june_line = add_line(june_batch["id"], merchant["id"], **ROUND_LINE)
        normalize_batch(june_batch["id"])
        post_batch(june_batch["id"])

        june_line = fetch_line(june_line["id"])
        assert june_line["processor_cost_cents"] == 5100, (
            "45 bps of 1,000,000 cents is 4,500 plus 6 cents on 100 authorizations"
        )
        assert june_line["normalized_net_revenue_cents"] == 40000, (
            "45,100 of fee income less the 5,100-cent processor cost"
        )

        validate_success(
            api_client.update_processor_program(
                program["id"], dict(AMENDABLE_PROGRAM_FIELDS), ADMIN_ONE
            )
        )

        july_batch = make_batch(
            program["id"],
            period_month="2026-07",
            coverage_start="2026-07-01",
            coverage_end="2026-08-01",
            file_checksum=checksum("pp-0007"),
        )
        july_line = add_line(july_batch["id"], merchant["id"], **ROUND_LINE)
        normalize_batch(july_batch["id"])
        post_batch(july_batch["id"])

        frozen = fetch_line(june_line["id"])
        assert frozen["processor_cost_cents"] == 5100, (
            "the June line keeps the cost computed at its normalization instant, "
            f"got {frozen['processor_cost_cents']}"
        )
        assert frozen["normalized_net_revenue_cents"] == 40000, (
            "the June line keeps its normalized net revenue after the amendment"
        )
        assert frozen["normalization_mode_applied"] == "NET_REVENUE_SPLIT", (
            "the mode stamped at normalization is history, not a live lookup"
        )

        repriced = fetch_line(july_line["id"])
        assert repriced["processor_cost_cents"] == 9600, (
            "90 bps of 1,000,000 cents is 9,000 plus 600 cents of per-item cost, "
            f"got {repriced['processor_cost_cents']}"
        )
        assert repriced["normalized_net_revenue_cents"] == 35500, (
            "45,100 of fee income less the 9,600-cent repriced processor cost"
        )

        june_rows, june_meta = validate_paginated(
            api_client.list_residual_allocations(
                CONTROLLER_ONE, {"agent_id": agent["id"], "period_month": "2026-06"}
            )
        )
        assert june_meta["total_count"] == 1, "one direct allocation was written for June"
        assert june_rows[0]["gross_allocation_cents"] == 20000, (
            "the June allocation stays at half of the 40,000-cent basis, "
            f"got {june_rows[0]['gross_allocation_cents']}"
        )

        july_rows, july_meta = validate_paginated(
            api_client.list_residual_allocations(
                CONTROLLER_ONE, {"agent_id": agent["id"], "period_month": "2026-07"}
            )
        )
        assert july_meta["total_count"] == 1, "one direct allocation was written for July"
        assert july_rows[0]["gross_allocation_cents"] == 17750, (
            "the July allocation is half of the 35,500-cent repriced basis, "
            f"got {july_rows[0]['gross_allocation_cents']}"
        )

        july_profit, _ = validate_paginated(
            api_client.list_merchant_profitability(
                CONTROLLER_ONE, {"residual_batch_id": july_batch["id"]}
            )
        )
        assert july_profit[0]["iso_retained_cents"] == 17750, (
            "the house keeps the half of the July basis no tier claimed"
        )

        june_statement = fetch_statement(agent["id"], "2026-06")
        july_statement = fetch_statement(agent["id"], "2026-07")
        assert june_statement["gross_after_trueup_cents"] == 20000, (
            "the June statement is unmoved by the amendment"
        )
        assert july_statement["gross_after_trueup_cents"] == 17750, (
            "the July statement carries the repriced allocation"
        )

        reread_program = validate_success(
            api_client.get_processor_program(program["id"], ADMIN_ONE)
        )
        assert reread_program["posted_batch_count"] == 2, (
            "posted_batch_count rises by one on each post, "
            f"got {reread_program['posted_batch_count']}"
        )
        assert reread_program["status"] == "ACTIVE", "the program was never suspended"
        assert fetch_agent(agent["id"])["trailing_residual_cents"] == 37750, (
            "the production KPI sums both statements' gross_after_trueup_cents"
        )


def _agent_with_mixed_portfolio() -> dict:
    """A1 with a 200,000-cent advance, one PENDING, two ACTIVE and one ATTRITED merchant.

    The attrited merchant carried a 27,000-cent boarding bonus and closed 82 days
    into its 270-day retention window, so the clawback is 18,800 cents. A July
    batch carrying only the second merchant's line is posted on top.
    """
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    advance = fund_percent_advance(
        agent["id"],
        principal_cents=200000,
        recoupment_pct=0.40,
        amortization_months=12,
        first_recoupment_month="2026-09",
        last_recoupment_month="2027-08",
        funded_on="2026-08-01",
    )

    merchants = {}
    for key, mid, bonus in (
        ("m1", "MID-9001", 0),
        ("m2", "MID-9002", 0),
        ("m3", "MID-9003", 0),
        ("m4", "MID-9004", 27000),
    ):
        merchants[key] = make_merchant(
            agent["id"],
            program["id"],
            mid=mid,
            monthly_minimum_cents=0,
            per_transaction_fee_cents=10,
            equipment_lease_monthly_cents=0,
            boarded_on="2026-04-10",
            upfront_bonus_cents=bonus,
        )
    for key in ("m2", "m3", "m4"):
        activate_merchant(merchants[key]["id"])
    attrite_merchant(merchants["m4"]["id"], "2026-07-01")

    batch = make_batch(
        program["id"],
        period_month="2026-07",
        coverage_start="2026-07-01",
        coverage_end="2026-08-01",
        file_checksum=checksum("ps-0001"),
    )
    add_line(batch["id"], merchants["m2"]["id"], **ROUND_LINE)
    normalize_batch(batch["id"])
    post_batch(batch["id"])

    return {
        "program": program,
        "agent": agent,
        "advance": advance,
        "batch": batch,
        **merchants,
    }


class TestPortfolioSummaryProjection:
    """GET /agents/{id}/portfolio-summary is computed, never stored."""

    def test_portfolio_summary_derives_all_ten_fields_on_the_fly(self):
        """One fixture pins all ten snapshot fields at once, and the two counting rules diverge: four merchants counted, three in the attrition denominator.

        PRD: "Alongside the plain agent read, the system exposes a computed portfolio snapshot for one agent, derived on the fly rather than stored."
        PRD: "The two count breakdowns are exactly what their names say — the number of the agent's merchants whose `status` is `ACTIVE`, and the number whose `status` is `ATTRITED` — while `portfolio_merchant_count` is the broader count of the agent's merchants in any of `PENDING`, `ACTIVE` or `ATTRITED`."

        Design: Corner/endpoints/portfolio_summary_derives_all_ten_fields_on_the_fly
        """
        world = _agent_with_mixed_portfolio()
        summary = validate_success(
            api_client.get_agent_portfolio_summary(world["agent"]["id"], CONTROLLER_ONE)
        )
        assert_agent_portfolio_summary(summary)
        assert set(summary) == PORTFOLIO_SUMMARY_FIELDS, (
            "the snapshot reports exactly the ten declared fields, got "
            f"{sorted(summary)}"
        )
        assert summary["agent_id"] == world["agent"]["id"], (
            "the snapshot reports the addressed agent's own id"
        )
        assert summary["portfolio_merchant_count"] == 4, (
            "PENDING, ACTIVE and ATTRITED merchants all count here, got "
            f"{summary['portfolio_merchant_count']}"
        )
        assert summary["active_merchant_count"] == 2, (
            f"two merchants are ACTIVE, got {summary['active_merchant_count']}"
        )
        assert summary["attrited_merchant_count"] == 1, (
            f"one merchant is ATTRITED, got {summary['attrited_merchant_count']}"
        )
        assert summary["portfolio_attrition_bps"] == 3333, (
            "ten thousand times one attrited over the three qualifying merchants, "
            "rounded half up, with the PENDING merchant excluded from both the "
            f"numerator and the denominator, got {summary['portfolio_attrition_bps']}"
        )
        assert summary["residual_hold"] is True, (
            "3,333 bps is at or above the 2,500-bps risk threshold"
        )
        assert summary["vested_pct"] == 50, (
            "thirty whole months from the 2024-01-15 anchor to the 2026-08-01 clock "
            f"is two completed twelve-month steps, got {summary['vested_pct']}"
        )
        assert summary["trailing_residual_cents"] == 20000, (
            "the KPI sums gross_after_trueup_cents, not net_payable_cents, got "
            f"{summary['trailing_residual_cents']}"
        )
        assert summary["advance_outstanding_cents"] == 200000, (
            "the ACTIVE advance is fully outstanding: its window has not opened yet"
        )
        assert summary["lifetime_clawback_cents"] == 18800, (
            "27,000 cents times the 188 days remaining in the 270-day window, "
            f"got {summary['lifetime_clawback_cents']}"
        )

    def test_portfolio_summary_agrees_with_the_agent_row_and_the_statement(self):
        """Every snapshot field that the agent row also carries reports the identical value, and the clawback the snapshot totals is the same one the July statement absorbed.

        PRD: "It reports the agent's own `agent_id` together with `portfolio_merchant_count`, `active_merchant_count`, `attrited_merchant_count`, `portfolio_attrition_bps`, `residual_hold`, `vested_pct`, `trailing_residual_cents`, `advance_outstanding_cents` and `lifetime_clawback_cents`."

        Design: Corner/endpoints/portfolio_summary_derives_all_ten_fields_on_the_fly
        """
        world = _agent_with_mixed_portfolio()
        agent_id = world["agent"]["id"]
        summary = validate_success(
            api_client.get_agent_portfolio_summary(agent_id, CONTROLLER_ONE)
        )
        agent_row = validate_success(api_client.get_agent(agent_id, ADMIN_ONE))

        for field in (
            "portfolio_merchant_count",
            "portfolio_attrition_bps",
            "residual_hold",
            "vested_pct",
            "trailing_residual_cents",
            "advance_outstanding_cents",
            "lifetime_clawback_cents",
        ):
            assert summary[field] == agent_row[field], (
                f"the snapshot's {field} must equal the same-named field on the "
                f"agent read: {summary[field]!r} vs {agent_row[field]!r}"
            )

        statement = fetch_statement(agent_id, "2026-07")
        assert statement is not None, "the July cascade left a statement behind"
        assert statement["adjustment_cents"] == -18800, (
            "the applied bonus clawback is the statement's only adjustment, got "
            f"{statement['adjustment_cents']}"
        )
        assert statement["gross_after_trueup_cents"] == 20000, (
            "half of the 40,000-cent basis reached the agent as a direct split"
        )
        assert statement["net_payable_cents"] == 1200, (
            "20,000 of gross less the 18,800-cent clawback, got "
            f"{statement['net_payable_cents']}"
        )
        assert_statement_money_lines_consistent(statement)
        assert summary["trailing_residual_cents"] == statement["gross_after_trueup_cents"], (
            "the trailing production KPI reads the gross line, not the payable"
        )


def _reassignment_world() -> dict:
    """A1 owning ACTIVE M1 and ATTRITED M2, A2 ACTIVE owning M3, A3 on departure notice."""
    program = make_program(**PROGRAM_TERMS)
    agents = {}
    for key, name in (("a1", "A1 Giver"), ("a2", "A2 Receiver"), ("a3", "A3 Leaving")):
        agents[key] = make_agent(
            name=name,
            split_pct=0.50,
            override_pct=0.60,
            vesting_start_date="2024-01-15",
        )

    merchants = {}
    for key, owner, mid in (
        ("m1", "a1", "MID-9001"),
        ("m2", "a1", "MID-9002"),
        ("m3", "a2", "MID-9003"),
    ):
        merchants[key] = make_merchant(
            agents[owner]["id"],
            program["id"],
            mid=mid,
            monthly_minimum_cents=0,
            per_transaction_fee_cents=10,
            equipment_lease_monthly_cents=0,
            boarded_on="2026-04-10",
        )
        activate_merchant(merchants[key]["id"])
    attrite_merchant(merchants["m2"]["id"], "2026-07-01")
    file_notice(agents["a3"]["id"], "2026-08-01")

    return {"program": program, **agents, **merchants}


class TestReassignAgentLink:
    """POST /merchants/{id}/reassign-agent validates both ends of the link."""

    def test_reassignment_checks_both_ends_before_anything_moves(self):
        """An unknown destination is a body-reference 404, a destination on departure notice is an agent-state conflict, and an attrited merchant is a merchant-state conflict.

        PRD: "An agent reference that names no agent — `parent_agent_id` on agent creation or amendment, `owning_agent_id` on merchant boarding, `new_agent_id` on reassignment, `target_agent_id` on portfolio transfer — yields `ERR_REFERENCED_AGENT_NOT_FOUND` (404)."
        PRD: "The destination agent must exist and must have `status` `ACTIVE`, otherwise `ERR_AGENT_STATE_INVALID`; the merchant itself must not be `ATTRITED`, otherwise `ERR_MERCHANT_STATE_INVALID`"

        Design: Corner/endpoints/reassign_agent_links_two_agents_and_moves_the_portfolio_counters
        """
        world = _reassignment_world()
        m1_version = fetch_merchant(world["m1"]["id"])["version"]
        m2_version = fetch_merchant(world["m2"]["id"])["version"]

        validate_error(
            api_client.reassign_merchant_agent(
                world["m1"]["id"],
                reassign_agent_payload(NON_EXISTENT_UUID, m1_version),
                ADMIN_ONE,
            ),
            ApiErrorId.ERR_REFERENCED_AGENT_NOT_FOUND.value,
        )
        validate_error(
            api_client.reassign_merchant_agent(
                world["m1"]["id"],
                reassign_agent_payload(world["a3"]["id"], m1_version),
                ADMIN_ONE,
            ),
            ApiErrorId.ERR_AGENT_STATE_INVALID.value,
        )
        validate_error(
            api_client.reassign_merchant_agent(
                world["m2"]["id"],
                reassign_agent_payload(world["a2"]["id"], m2_version),
                ADMIN_ONE,
            ),
            ApiErrorId.ERR_MERCHANT_STATE_INVALID.value,
        )

        untouched = fetch_merchant(world["m1"]["id"])
        assert untouched["version"] == m1_version, (
            "a refused reassignment mutates nothing, so the merchant's version is "
            f"still {m1_version}, got {untouched['version']}"
        )
        assert untouched["owning_agent_id"] == world["a1"]["id"], (
            "ownership stayed with the original agent through all three refusals"
        )
        still_attrited = fetch_merchant(world["m2"]["id"])
        assert still_attrited["version"] == m2_version, (
            "the attrited merchant was not mutated by the refused reassignment"
        )
        assert still_attrited["owning_agent_id"] == world["a1"]["id"], (
            "an attrited merchant keeps its owning agent"
        )

    def test_accepted_reassignment_moves_the_counters_on_both_agents(self):
        """The accepted call re-points owning_agent_id, moves portfolio_merchant_count one down and one up, and recomputes the attrition rate and hold flag on both agents.

        PRD: "On success, `owning_agent_id` becomes the new agent, `portfolio_merchant_count` falls by one on the previous owner and rises by one on the new owner, and `portfolio_attrition_bps` — with `residual_hold` alongside it — is recomputed for both agents."

        Design: Corner/endpoints/reassign_agent_links_two_agents_and_moves_the_portfolio_counters
        """
        world = _reassignment_world()
        giver_before = fetch_agent(world["a1"]["id"])
        receiver_before = fetch_agent(world["a2"]["id"])
        assert giver_before["portfolio_merchant_count"] == 2, (
            "the giver's book holds the active and the attrited merchant"
        )
        assert giver_before["portfolio_attrition_bps"] == 5000, (
            "one attrited over two qualifying merchants is 5,000 bps, got "
            f"{giver_before['portfolio_attrition_bps']}"
        )
        assert giver_before["residual_hold"] is True, "5,000 bps holds the giver"
        assert receiver_before["portfolio_merchant_count"] == 1, (
            "the receiver already owns one merchant"
        )
        assert receiver_before["portfolio_attrition_bps"] == 0, (
            "the receiver has lost nothing yet"
        )
        assert receiver_before["residual_hold"] is False, "0 bps leaves the receiver free"

        m1_version = fetch_merchant(world["m1"]["id"])["version"]
        moved = validate_success(
            api_client.reassign_merchant_agent(
                world["m1"]["id"],
                reassign_agent_payload(world["a2"]["id"], m1_version),
                ADMIN_ONE,
            )
        )
        assert moved["owning_agent_id"] == world["a2"]["id"], (
            "owning_agent_id becomes the destination agent"
        )
        assert moved["version"] == m1_version + 1, (
            f"the reassignment bumps the merchant's version to {m1_version + 1}, "
            f"got {moved['version']}"
        )

        giver_after = fetch_agent(world["a1"]["id"])
        receiver_after = fetch_agent(world["a2"]["id"])
        assert giver_after["portfolio_merchant_count"] == 1, (
            "the giver's count falls by one, got "
            f"{giver_after['portfolio_merchant_count']}"
        )
        assert giver_after["portfolio_attrition_bps"] == 10000, (
            "the only merchant left on the giver's book is attrited, so the rate is "
            f"the full 10,000 bps, got {giver_after['portfolio_attrition_bps']}"
        )
        assert giver_after["residual_hold"] is True, "10,000 bps keeps the giver held"
        assert receiver_after["portfolio_merchant_count"] == 2, (
            "the receiver's count rises by one, got "
            f"{receiver_after['portfolio_merchant_count']}"
        )
        assert receiver_after["portfolio_attrition_bps"] == 0, (
            "both of the receiver's merchants are active, so the rate stays 0"
        )
        assert receiver_after["residual_hold"] is False, (
            "the receiver was recomputed by the same single write and stays free"
        )

        rows, meta = validate_paginated(
            api_client.list_merchants(
                CONTROLLER_ONE, {"owning_agent_id": world["a2"]["id"]}
            )
        )
        assert meta["total_count"] == 2, (
            f"the destination agent's book now lists two merchants, got {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {world["m1"]["id"], world["m3"]["id"]}, (
            "the reassigned merchant joins the merchant the destination already owned"
        )


# Five events on the first merchant and one on the second: three accounting
# months and both liability values, so the list filters have something to bite on.
CHARGEBACK_SPREAD = (
    ("m1", {"amount_cents": 1000, "occurred_on": "2026-05-10", "period_month": "2026-05", "liability": "AGENT_CHARGED"}),
    ("m1", {"amount_cents": 2000, "occurred_on": "2026-06-11", "period_month": "2026-06", "liability": "ISO_ABSORBED"}),
    ("m1", {"amount_cents": 3000, "occurred_on": "2026-07-12", "period_month": "2026-07", "liability": "AGENT_CHARGED"}),
    ("m1", {"amount_cents": 4000, "occurred_on": "2026-07-13", "period_month": "2026-07", "liability": "ISO_ABSORBED"}),
    ("m1", {"amount_cents": 5000, "occurred_on": "2026-07-30", "period_month": "2026-08", "liability": "AGENT_CHARGED"}),
    ("m2", {"amount_cents": 900, "occurred_on": "2026-07-05", "period_month": "2026-07", "liability": "AGENT_CHARGED"}),
)


def _chargeback_world() -> dict:
    """Two active merchants under one agent, plus the six booked chargeback events."""
    program = make_program(**PROGRAM_TERMS)
    agent = make_agent(
        name="A1 Principal",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    merchants = {}
    for key, mid in (("m1", "MID-9001"), ("m2", "MID-9002")):
        merchants[key] = make_merchant(
            agent["id"],
            program["id"],
            mid=mid,
            monthly_minimum_cents=0,
            per_transaction_fee_cents=10,
            equipment_lease_monthly_cents=0,
            boarded_on="2026-04-10",
        )
        activate_merchant(merchants[key]["id"])

    events = []
    for owner_key, payload in CHARGEBACK_SPREAD:
        created = validate_success(
            api_client.create_chargeback_event(
                merchants[owner_key]["id"], dict(payload), ANALYST_ONE
            ),
            201,
        )
        events.append(created)
    return {"agent": agent, "events": events, **merchants}


class TestChargebackEventCollection:
    """POST /merchants/{id}/chargebacks, then the flat collection reads."""

    def test_booking_takes_the_merchant_from_the_path_and_echoes_the_event(self):
        """The immutable event carries the four posted fields plus a server-minted id and created_at, and the merchant it belongs to comes from the path rather than the body.

        PRD: "A chargeback is booked against a merchant by an `IsoAdmin` or a `ResidualAnalyst` as an immutable event carrying `amount_cents` (strictly greater than zero), the date-only `occurred_on` on which it was received, the `period_month` it is charged against, and a `liability` of either `AGENT_CHARGED` or `ISO_ABSORBED`."
        PRD: "Both `updated_at` and `version` are absent from a `ChargebackEvent` — not null, absent."

        Design: Corner/endpoints/chargeback_events_create_list_filter_and_paginate
        """
        world = _chargeback_world()
        for (owner_key, payload), created in zip(CHARGEBACK_SPREAD, world["events"]):
            assert_chargeback_event(created)
            assert created["merchant_id"] == world[owner_key]["id"], (
                "merchant_id is taken from the path segment, not from the body"
            )
            for field, expected in payload.items():
                assert created[field] == expected, (
                    f"the booked event must echo {field} as {expected!r}, got "
                    f"{created[field]!r}"
                )

        third = world["events"][2]
        fetched = validate_success(
            api_client.get_chargeback_event(third["id"], CONTROLLER_ONE)
        )
        assert_chargeback_event(fetched)
        assert fetched["id"] == third["id"], "the single read addresses the same event"
        assert fetched["amount_cents"] == 3000, (
            f"the July agent-charged event is 3,000 cents, got {fetched['amount_cents']}"
        )
        assert fetched["occurred_on"] == "2026-07-12", "occurred_on is a date-only value"
        assert fetched["period_month"] == "2026-07", "the event is charged to July"
        assert fetched["liability"] == "AGENT_CHARGED", "the liability round-trips"
        assert fetched["merchant_id"] == world["m1"]["id"], (
            "the event belongs to the merchant named in the creation path"
        )

    def test_chargeback_list_paginates_inside_the_filtered_set(self):
        """limit and offset page the five events of one merchant, total_count reports the pre-pagination match count, and has_more turns false on the last page.

        PRD: "`total_count` (the number of rows matching the filters before pagination), and `has_more` (true when rows remain beyond the current page)"

        Design: Corner/endpoints/chargeback_events_create_list_filter_and_paginate
        """
        world = _chargeback_world()
        m1_event_ids = {
            event["id"]
            for (owner_key, _), event in zip(CHARGEBACK_SPREAD, world["events"])
            if owner_key == "m1"
        }
        assert len(m1_event_ids) == 5, "five of the six events belong to the first merchant"

        page_two, meta_two = validate_paginated(
            api_client.list_chargeback_events(
                CONTROLLER_ONE, {"merchant_id": world["m1"]["id"], "limit": 2, "offset": 2}
            )
        )
        assert meta_two["total_count"] == 5, (
            f"five events match the merchant filter, got {meta_two['total_count']}"
        )
        assert meta_two["limit"] == 2, "the applied page size is echoed"
        assert meta_two["offset"] == 2, "the applied offset is echoed"
        assert meta_two["has_more"] is True, "rows remain beyond rows three and four"
        assert len(page_two) == 2, f"a page of two returns two rows, got {len(page_two)}"

        page_three, meta_three = validate_paginated(
            api_client.list_chargeback_events(
                CONTROLLER_ONE, {"merchant_id": world["m1"]["id"], "limit": 2, "offset": 4}
            )
        )
        assert meta_three["total_count"] == 5, (
            "total_count is unaffected by the window, got "
            f"{meta_three['total_count']}"
        )
        assert meta_three["offset"] == 4, "the applied offset is echoed"
        assert meta_three["has_more"] is False, "the fifth row is the last one"
        assert len(page_three) == 1, (
            f"only one row remains after an offset of four, got {len(page_three)}"
        )

        first_ids = {row["id"] for row in page_two}
        second_ids = {row["id"] for row in page_three}
        assert not first_ids & second_ids, "consecutive pages never repeat a row"
        assert len(first_ids | second_ids) == 3, (
            "the two pages together cover three distinct events"
        )
        assert (first_ids | second_ids) <= m1_event_ids, (
            "every paged row belongs to the filtered merchant"
        )
        for row in page_two + page_three:
            assert row["merchant_id"] == world["m1"]["id"], (
                "the merchant filter admits no foreign row"
            )

    def test_chargeback_filters_compose_over_merchant_period_and_liability(self):
        """period_month matches the month the event is booked to rather than the month it occurred in, and the merchant, period and liability filters narrow the collection together.

        PRD: "Booking a chargeback moves no money by itself — the event enters the ledger only when a batch for the same `period_month` is posted, and it is matched by exact equality on `period_month`, so an event booked to a different period never enters no matter when it actually occurred."
        PRD: "Most collections additionally accept the enumerated filters named in §4"

        Design: Corner/endpoints/chargeback_events_create_list_filter_and_paginate
        """
        world = _chargeback_world()
        events = world["events"]

        rows, meta = validate_paginated(
            api_client.list_chargeback_events(
                CONTROLLER_ONE,
                {"merchant_id": world["m1"]["id"], "period_month": "2026-07"},
            )
        )
        assert meta["total_count"] == 2, (
            "only the two events booked to July on that merchant match; the event "
            "that occurred on 2026-07-30 is booked to August and is excluded, got "
            f"{meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {events[2]["id"], events[3]["id"]}, (
            "the July pair on the first merchant is exactly what the filter returns"
        )

        rows, meta = validate_paginated(
            api_client.list_chargeback_events(
                CONTROLLER_ONE,
                {"period_month": "2026-07", "liability": "AGENT_CHARGED"},
            )
        )
        assert meta["total_count"] == 2, (
            "the period and liability filters compose across both merchants, got "
            f"{meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {events[2]["id"], events[5]["id"]}, (
            "the two agent-charged July events span both merchants"
        )

        rows, meta = validate_paginated(
            api_client.list_chargeback_events(CONTROLLER_ONE, {})
        )
        assert meta["total_count"] == 6, (
            f"the unfiltered collection holds all six events, got {meta['total_count']}"
        )
        assert meta["limit"] == 10, (
            f"the page size defaults to 10 when omitted, got {meta['limit']}"
        )
        assert meta["offset"] == 0, "the offset defaults to 0 when omitted"
        assert meta["has_more"] is False, "six rows fit inside the default page"
        assert len(rows) == 6, f"all six rows fit on the first page, got {len(rows)}"


def _fresh_pre_cliff_agent() -> dict:
    """An agent anchored on 2026-06-15, one whole month short of the cliff at startup."""
    return make_agent(
        name="A1 Fresh",
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2026-06-15",
    )


class TestClockCrossesTheVestingCliff:
    """POST /_clock/set_current_utc drives the derived vesting percentage."""

    def test_clock_move_crosses_the_cliff_from_zero_to_twenty_five(self):
        """The same agent reads 0 at the startup clock, still 0 on 2027-06-14 because the anchor's day-of-month has not been reached, and 25 on 2027-06-15.

        PRD: "If the elapsed month count is fewer than twelve, `vested_pct` is 0 — that is the cliff, and nothing vests before it."
        PRD: "The cliff boundary is inclusive at twelve: exactly twelve elapsed months returns 25, while eleven returns 0."

        Design: Corner/endpoints/clock_move_crosses_the_vesting_cliff_from_zero_to_twenty_five
        """
        agent = _fresh_pre_cliff_agent()
        at_startup = validate_success(api_client.get_agent(agent["id"], ADMIN_ONE))
        assert at_startup["vested_pct"] == 0, (
            "2026-06-15 to the 2026-08-01 startup clock is one whole month, far "
            f"short of the twelve-month cliff, got {at_startup['vested_pct']}"
        )
        assert at_startup["vested_pct_at_departure"] is None, (
            "nothing is frozen until the agent actually departs"
        )

        day_before = validate_success(
            api_client.set_clock("2027-06-14T00:00:00Z", ADMIN_ONE)
        )
        assert day_before["current_utc"].startswith("2027-06-14T00:00:00"), (
            f"the clock echoes the instant now in force, got {day_before['current_utc']!r}"
        )
        summary = validate_success(
            api_client.get_agent_portfolio_summary(agent["id"], ADMIN_ONE)
        )
        assert summary["vested_pct"] == 0, (
            "calendar subtraction gives twelve months but day 14 is earlier than the "
            "anchor's day 15, so one month is subtracted and eleven months vests "
            f"nothing, got {summary['vested_pct']}"
        )

        cliff_day = validate_success(
            api_client.set_clock("2027-06-15T00:00:00Z", ADMIN_ONE)
        )
        assert cliff_day["current_utc"].startswith("2027-06-15T00:00:00"), (
            f"the clock echoes the instant now in force, got {cliff_day['current_utc']!r}"
        )
        summary = validate_success(
            api_client.get_agent_portfolio_summary(agent["id"], ADMIN_ONE)
        )
        assert summary["vested_pct"] == 25, (
            "twelve elapsed months is inclusive of the cliff and pays one "
            f"twenty-five-point step, got {summary['vested_pct']}"
        )
        agent_row = validate_success(api_client.get_agent(agent["id"], ADMIN_ONE))
        assert agent_row["vested_pct"] == 25, (
            "the plain agent read and the snapshot evaluate the same schedule, got "
            f"{agent_row['vested_pct']}"
        )

    def test_clock_moves_never_write_to_the_agent_row(self):
        """vested_pct is derived from the clock on every read, so moving the clock across the cliff leaves the agent's version and its money counters exactly where they were.

        PRD: "An `IsoAdmin` may advance or rewind the clock through a dedicated test-driving capability that takes a single `current_utc` instant and returns the value now in force as `current_utc`."

        Design: Corner/endpoints/clock_move_crosses_the_vesting_cliff_from_zero_to_twenty_five
        """
        agent = _fresh_pre_cliff_agent()
        version_at_creation = agent["version"]

        for instant in ("2027-06-14T00:00:00Z", "2027-06-15T00:00:00Z"):
            validate_success(api_client.set_clock(instant, ADMIN_ONE))
            row = validate_success(api_client.get_agent(agent["id"], ADMIN_ONE))
            assert row["version"] == version_at_creation, (
                "a clock move is not a mutation of the agent, so its version stays "
                f"at {version_at_creation}, got {row['version']} after {instant}"
            )

        summary = validate_success(
            api_client.get_agent_portfolio_summary(agent["id"], ADMIN_ONE)
        )
        assert summary["vested_pct"] == 25, (
            "the derived percentage still tracks the clock, got "
            f"{summary['vested_pct']}"
        )
        for field in (
            "trailing_residual_cents",
            "advance_outstanding_cents",
            "lifetime_clawback_cents",
        ):
            assert summary[field] == 0, (
                f"{field} has no input in this world and stays 0, got {summary[field]}"
            )
        assert summary["portfolio_merchant_count"] == 0, "the agent owns no merchants"
        assert summary["portfolio_attrition_bps"] == 0, (
            "an empty qualifying book gives an attrition rate of 0"
        )
        assert summary["residual_hold"] is False, "0 bps is below the risk threshold"


def _normalized_world_ready_to_post() -> dict:
    """One normalized July line worth 13,600 cents against a 1,000-cent equipment lease."""
    program = make_program(**PROGRAM_TERMS)
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
        file_checksum=checksum("im-0001"),
    )
    line = add_line(
        batch["id"],
        merchant["id"],
        transaction_count=100,
        sales_volume_cents=1000000,
        interchange_cents=20000,
        assessments_cents=1300,
        gross_income_cents=40000,
    )
    batch = normalize_batch(batch["id"])
    return {
        "program": program,
        "agent": agent,
        "merchant": merchant,
        "batch": batch,
        "line": line,
    }


class TestPostCascadeIsImmediatelyVisible:
    """The four-link cascade is transactional with the post, not lazy."""

    def test_post_response_already_carries_the_rolled_up_batch_totals(self):
        """The post response itself reports POSTED, a posted_at taken from the logical clock and the batch's retained residue, and re-reading the batch returns the identical totals.

        PRD: "A successful post writes `posted_at` from the logical clock, raises the governing program's `posted_batch_count` by one, and then runs a four-level cascade."
        PRD: "Finally the batch itself records `iso_retained_cents` as the sum of `iso_retained_cents` over the profitability rows it produced"

        Design: Corner/consistency_model/post_cascade_is_immediately_visible_everywhere
        """
        world = _normalized_world_ready_to_post()
        posted = validate_success(
            api_client.post_residual_batch(world["batch"]["id"], CONTROLLER_ONE)
        )
        assert posted["state"] == "POSTED", (
            f"the post advances the batch to POSTED, got {posted['state']!r}"
        )
        assert posted["posted_at"] is not None, "posted_at is stamped by the post"
        assert posted["posted_at"].startswith("2026-08-01T00:00:00"), (
            "posted_at is written from the logical clock, which still reads the "
            f"startup instant, got {posted['posted_at']!r}"
        )
        assert posted["line_count"] == 1, (
            f"the batch carries one line, got {posted['line_count']}"
        )
        assert posted["gross_volume_cents"] == 1000000, (
            f"the file's only line reports 1,000,000 cents of volume, got "
            f"{posted['gross_volume_cents']}"
        )
        assert posted["total_normalized_net_revenue_cents"] == 13600, (
            "40,000 of fee income less 20,000 of interchange, 1,300 of assessments "
            f"and the 5,100-cent processor cost, got "
            f"{posted['total_normalized_net_revenue_cents']}"
        )
        assert posted["iso_retained_cents"] == 6300, (
            "the house keeps the half of the 12,600-cent basis no tier claimed, got "
            f"{posted['iso_retained_cents']}"
        )

        reread = validate_success(
            api_client.get_residual_batch(world["batch"]["id"], CONTROLLER_ONE)
        )
        for field in (
            "state",
            "posted_at",
            "line_count",
            "gross_volume_cents",
            "total_normalized_net_revenue_cents",
            "iso_retained_cents",
            "version",
        ):
            assert reread[field] == posted[field], (
                f"nothing settles after the post: {field} read back as "
                f"{reread[field]!r} but the post returned {posted[field]!r}"
            )
        program = validate_success(
            api_client.get_processor_program(world["program"]["id"], ADMIN_ONE)
        )
        assert program["posted_batch_count"] == 1, (
            f"the governing program counts the post immediately, got "
            f"{program['posted_batch_count']}"
        )

    def test_every_downstream_read_is_final_in_the_same_instant(self):
        """With no intervening write, the very next reads of profitability, allocations, the statement and the agent KPI all return their final values.

        PRD: "A large fraction of the fields in this system are derived rather than supplied, and the specification treats a derived field as wrong the instant one of its inputs changes."
        PRD: "Each statement recompute in turn refreshes `trailing_residual_cents` on that statement's agent."

        Design: Corner/consistency_model/post_cascade_is_immediately_visible_everywhere
        """
        world = _normalized_world_ready_to_post()
        validate_success(
            api_client.post_residual_batch(world["batch"]["id"], CONTROLLER_ONE)
        )

        profit_rows, profit_meta = validate_paginated(
            api_client.list_merchant_profitability(
                CONTROLLER_ONE, {"residual_batch_id": world["batch"]["id"]}
            )
        )
        assert profit_meta["total_count"] == 1, (
            f"one profitability row per line, got {profit_meta['total_count']}"
        )
        row = profit_rows[0]
        assert_profitability_bottom_lines(row)
        assert row["normalized_net_revenue_cents"] == 13600, (
            f"the row copies the line's normalized net revenue, got "
            f"{row['normalized_net_revenue_cents']}"
        )
        assert row["chargeback_cost_cents"] == 0, "no chargebacks were booked"
        assert row["agent_chargeable_chargeback_cents"] == 0, "no chargebacks were booked"
        assert row["equipment_cost_cents"] == 1000, (
            "an active merchant is charged the full monthly lease, got "
            f"{row['equipment_cost_cents']}"
        )
        assert row["profit_cents"] == 12600, (
            f"13,600 less nothing in chargebacks less 1,000 of lease, got "
            f"{row['profit_cents']}"
        )
        assert row["agent_basis_cents"] == 12600, (
            "with no agent-charged chargebacks the split basis equals the ISO view, "
            f"got {row['agent_basis_cents']}"
        )
        assert row["allocated_total_cents"] == 6300, (
            f"the single direct tier took half the basis, got "
            f"{row['allocated_total_cents']}"
        )
        assert row["iso_retained_cents"] == 6300, (
            f"the residue is the basis less the allocated total, got "
            f"{row['iso_retained_cents']}"
        )

        alloc_rows, alloc_meta = validate_paginated(
            api_client.list_residual_allocations(
                CONTROLLER_ONE, {"period_month": "2026-07"}
            )
        )
        assert alloc_meta["total_count"] == 1, (
            f"only the direct tier was paid, got {alloc_meta['total_count']}"
        )
        allocation = alloc_rows[0]
        assert_residual_allocation(allocation)
        assert allocation["allocation_type"] == "DIRECT_SPLIT", (
            "the owning agent is paid on the direct tier"
        )
        assert allocation["tier_level"] == 0, "the direct tier is tier level 0"
        assert float(allocation["applied_pct"]) == 0.50, (
            f"the owning agent's own split_pct was applied, got "
            f"{allocation['applied_pct']!r}"
        )
        assert allocation["basis_cents"] == 12600, (
            f"the allocation records the basis it was computed from, got "
            f"{allocation['basis_cents']}"
        )
        assert allocation["gross_allocation_cents"] == 6300, (
            f"half of 12,600 cents, got {allocation['gross_allocation_cents']}"
        )
        assert allocation["vesting_withheld_cents"] == 0, (
            "nothing is withheld from an agent that has not departed"
        )
        assert allocation["agent_id"] == world["agent"]["id"], (
            "the receiving agent is the merchant's owner at post time"
        )
        assert allocation["merchant_id"] == world["merchant"]["id"], (
            "the allocation names the merchant whose basis was split"
        )

        statement_rows, statement_meta = validate_paginated(
            api_client.list_agent_statements(
                CONTROLLER_ONE,
                {"agent_id": world["agent"]["id"], "period_month": "2026-07"},
            )
        )
        assert statement_meta["total_count"] == 1, (
            "the cascade created exactly one statement for the agent and month, got "
            f"{statement_meta['total_count']}"
        )
        statement = statement_rows[0]
        assert statement["lifecycle_state"] == "DRAFT", (
            "a cascade-created statement lands in DRAFT"
        )
        assert statement["settlement_state"] == "UNSETTLED", (
            "a cascade-created statement lands UNSETTLED"
        )
        assert statement["direct_residual_cents"] == 6300, (
            f"the direct allocation is the whole of the gross, got "
            f"{statement['direct_residual_cents']}"
        )
        assert statement["override_residual_cents"] == 0, "no override tier was paid"
        assert statement["minimum_true_up_cents"] == 0, (
            "the true-up is forced to zero while the statement is DRAFT"
        )
        assert statement["gross_after_trueup_cents"] == 6300, (
            f"direct plus override plus true-up, got "
            f"{statement['gross_after_trueup_cents']}"
        )
        assert statement["advance_recoupment_cents"] == 0, (
            "recoupment is forced to zero while the statement is DRAFT"
        )
        assert statement["adjustment_cents"] == 0, "no adjustment has been applied"
        assert statement["opening_deficit_cents"] == 0, (
            "there is no issued predecessor month to roll a deficit forward"
        )
        assert statement["net_payable_cents"] == 6300, (
            f"the pre-floor balance is positive and passes straight through, got "
            f"{statement['net_payable_cents']}"
        )
        assert statement["carry_forward_deficit_cents"] == 0, (
            "a positive balance leaves no deficit behind"
        )
        assert_statement_money_lines_consistent(statement)

        attached, attached_meta = validate_paginated(
            api_client.list_residual_allocations(
                CONTROLLER_ONE, {"statement_id": statement["id"]}
            )
        )
        assert attached_meta["total_count"] == 1, (
            "the allocation is already attached to the statement the post created, "
            f"got {attached_meta['total_count']}"
        )
        assert attached[0]["id"] == allocation["id"], (
            "the attached allocation is the one the waterfall wrote"
        )

        summary = validate_success(
            api_client.get_agent_portfolio_summary(world["agent"]["id"], CONTROLLER_ONE)
        )
        assert_agent_portfolio_summary(summary)
        assert summary["trailing_residual_cents"] == 6300, (
            "the KPI at the end of the four-link chain is current in the same "
            f"instant, got {summary['trailing_residual_cents']}"
        )
        assert summary["portfolio_merchant_count"] == 1, "the agent owns one merchant"
        assert summary["active_merchant_count"] == 1, "that merchant is ACTIVE"
        assert summary["attrited_merchant_count"] == 0, "nothing has attrited"
        assert summary["portfolio_attrition_bps"] == 0, (
            "no attrited merchant means an attrition rate of 0"
        )
        assert summary["residual_hold"] is False, "0 bps is below the risk threshold"
        assert summary["vested_pct"] == 50, (
            "thirty whole months from the 2024-01-15 anchor is two completed steps, "
            f"got {summary['vested_pct']}"
        )
        assert summary["advance_outstanding_cents"] == 0, "no advance was funded"
        assert summary["lifetime_clawback_cents"] == 0, "nothing was clawed back"
