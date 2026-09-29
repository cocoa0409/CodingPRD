"""The three optimistically guarded writes, and the attrition-hold threshold.

Every test builds its own state through the public endpoints only; the harness
restarts the server and empties the database before each one, and the logical
clock starts at 2026-08-01T00:00:00Z.
"""

from test_helpers import (
    ADMIN_ONE,
    ANALYST_ONE,
    CONTROLLER_ONE,
    ApiErrorId,
    api_client,
    assert_advance_principal_conserved,
    create_agent_payload,
    create_merchant_payload,
    create_percent_advance_payload,
    create_processor_program_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _make_program(name: str = "Atlantic Net Program") -> dict:
    payload = create_processor_program_payload(
        name=name,
        buy_rate_bps=45,
        buy_rate_per_item_cents=6,
        assessment_bps=13,
        normalization_mode="NET_REVENUE_SPLIT",
        minimum_billing_mode="NO_MINIMUM",
    )
    return validate_success(api_client.create_processor_program(payload, ADMIN_ONE), 201)


def _make_agent(name: str) -> dict:
    payload = create_agent_payload(
        name=name,
        split_pct=0.50,
        override_pct=0.60,
        vesting_start_date="2024-01-15",
    )
    return validate_success(api_client.create_agent(payload, ADMIN_ONE), 201)


def _board_merchant(agent_id: str, program_id: str, mid: str, **overrides) -> dict:
    terms = {
        "mid": mid,
        "monthly_minimum_cents": 0,
        "per_transaction_fee_cents": 10,
        "equipment_lease_monthly_cents": 0,
        "boarded_on": "2026-04-10",
    }
    terms.update(overrides)
    payload = create_merchant_payload(agent_id, program_id, **terms)
    return validate_success(api_client.create_merchant(payload, ADMIN_ONE), 201)


def _read_agent(agent_id: str) -> dict:
    return validate_success(api_client.get_agent(agent_id, ADMIN_ONE))


def test_occ_agent_version_guards_advance_funding():
    """A replayed agent version is the only thing that stops a second funding.

    "Advances legitimately stack on one agent, so no state precondition blocks a
    second funding request" — but "If it does not equal that agent's current
    `version`, the funding request is rejected with `ERR_STALE_AGENT_VERSION`
    (HTTP 412)". Both advances stay far under the 250,000-cent bootstrap
    exposure floor, so no fiscal ceiling can mask the guard.

    Design: Corner/cross_cutting_complexity_layers/occ_agent_version_guards_advance_funding
    """
    agent = _make_agent("OCC Agent")
    first_version = agent["version"]

    def _percent_advance(expected_version, **overrides):
        terms = {
            "principal_cents": 50000,
            "recoupment_pct": 0.20,
            "first_recoupment_month": "2026-09",
            "last_recoupment_month": "2027-02",
            "funded_on": "2026-08-01",
        }
        terms.update(overrides)
        payload = create_percent_advance_payload(expected_version, **terms)
        return api_client.create_agent_advance(agent["id"], payload, ADMIN_ONE)

    first_advance = validate_success(_percent_advance(first_version), 201)
    assert first_advance["state"] == "ACTIVE"
    assert first_advance["outstanding_cents"] == 50000, (
        f"expected outstanding_cents 50000, got {first_advance['outstanding_cents']}"
    )
    assert first_advance["cumulative_recouped_cents"] == 0
    assert first_advance["months_recouped"] == 0
    assert_advance_principal_conserved(first_advance)

    replayed = _percent_advance(first_version)
    validate_error(replayed, ApiErrorId.ERR_STALE_AGENT_VERSION.value, 412)

    refreshed = _read_agent(agent["id"])
    second_version = refreshed["version"]
    assert second_version == first_version + 1, (
        "the successful funding incremented the agent version exactly once and the "
        f"412 did not, expected {first_version + 1}, got {second_version}"
    )
    assert refreshed["advance_outstanding_cents"] == 50000, (
        "the refused funding must not have moved advance_outstanding_cents, got "
        f"{refreshed['advance_outstanding_cents']}"
    )
    _, meta = validate_paginated(
        api_client.list_agent_advances(ADMIN_ONE, {"agent_id": agent["id"]})
    )
    assert meta["total_count"] == 1, (
        f"the 412 must leave no AgentAdvance row behind, got {meta['total_count']}"
    )

    second_advance = validate_success(
        _percent_advance(second_version, funded_on="2026-08-02"), 201
    )
    assert second_advance["state"] == "ACTIVE"
    after_second = _read_agent(agent["id"])
    third_version = after_second["version"]
    assert after_second["advance_outstanding_cents"] == 100000, (
        "the two accepted fundings stack to 100000 cents, got "
        f"{after_second['advance_outstanding_cents']}"
    )
    assert third_version == second_version + 1

    # A version bump from an unrelated master-data write invalidates the read too.
    validate_success(
        api_client.update_agent(agent["id"], {"name": "OCC Agent Renamed"}, ADMIN_ONE)
    )
    after_patch = api_client.create_agent_advance(
        agent["id"],
        create_percent_advance_payload(
            third_version,
            principal_cents=10000,
            recoupment_pct=0.05,
            first_recoupment_month="2026-09",
            last_recoupment_month="2027-02",
            funded_on="2026-08-03",
        ),
        ADMIN_ONE,
    )
    validate_error(after_patch, ApiErrorId.ERR_STALE_AGENT_VERSION.value, 412)

    rows, final_meta = validate_paginated(
        api_client.list_agent_advances(ADMIN_ONE, {"agent_id": agent["id"]})
    )
    assert final_meta["total_count"] == 2, (
        "exactly the two accepted fundings exist, got "
        f"{final_meta['total_count']}"
    )
    assert {row["id"] for row in rows} == {first_advance["id"], second_advance["id"]}


def test_occ_merchant_version_guards_agent_reassignment():
    """A stale merchant version blocks a reassignment that would overwrite ownership.

    "A mismatch against the merchant's current `version` is rejected with
    `ERR_STALE_MERCHANT_VERSION` (HTTP 412)", the guard existing because "a second
    sequential reassignment to a different agent would otherwise succeed and
    silently overwrite the ownership a previous writer had established".

    Design: Corner/cross_cutting_complexity_layers/occ_merchant_version_guards_agent_reassignment
    """
    program = _make_program()
    owner = _make_agent("A1 Owner")
    target = _make_agent("A2 Target")
    merchant = _board_merchant(owner["id"], program["id"], "MID-9001")
    validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE))
    observed = validate_success(api_client.get_merchant(merchant["id"], ADMIN_ONE))
    stale_version = observed["version"]

    # A pricing-only amendment still counts as a mutation of the row.
    patched = validate_success(
        api_client.update_merchant(
            merchant["id"], {"per_transaction_fee_cents": 20}, ADMIN_ONE
        )
    )
    assert patched["per_transaction_fee_cents"] == 20
    fresh_version = patched["version"]
    assert fresh_version == stale_version + 1, (
        f"expected version {stale_version + 1}, got {fresh_version}"
    )

    refused = api_client.reassign_merchant_agent(
        merchant["id"],
        {"new_agent_id": target["id"], "expected_merchant_version": stale_version},
        ADMIN_ONE,
    )
    validate_error(refused, ApiErrorId.ERR_STALE_MERCHANT_VERSION.value, 412)

    unchanged = validate_success(api_client.get_merchant(merchant["id"], ADMIN_ONE))
    assert unchanged["owning_agent_id"] == owner["id"], (
        "the refused reassignment must leave ownership with the original agent"
    )
    assert unchanged["version"] == fresh_version, (
        "the 412 must not bump the merchant version"
    )
    owner_summary = validate_success(
        api_client.get_agent_portfolio_summary(owner["id"], ADMIN_ONE)
    )
    assert owner_summary["portfolio_merchant_count"] == 1
    assert owner_summary["active_merchant_count"] == 1
    target_before = validate_success(
        api_client.get_agent_portfolio_summary(target["id"], ADMIN_ONE)
    )
    assert target_before["portfolio_merchant_count"] == 0, (
        "the cascade is all-or-nothing with the 412, so the target gained nothing"
    )

    moved = validate_success(
        api_client.reassign_merchant_agent(
            merchant["id"],
            {"new_agent_id": target["id"], "expected_merchant_version": fresh_version},
            ADMIN_ONE,
        )
    )
    assert moved["owning_agent_id"] == target["id"]
    assert moved["version"] == fresh_version + 1, (
        f"expected version {fresh_version + 1}, got {moved['version']}"
    )

    target_after = validate_success(
        api_client.get_agent_portfolio_summary(target["id"], ADMIN_ONE)
    )
    assert target_after["portfolio_merchant_count"] == 1
    assert target_after["portfolio_attrition_bps"] == 0
    owner_after = validate_success(
        api_client.get_agent_portfolio_summary(owner["id"], ADMIN_ONE)
    )
    assert owner_after["portfolio_merchant_count"] == 0, (
        "the previous owner drops to zero merchants only on the successful move"
    )


def test_occ_statement_version_guards_adjustment_proposals():
    """A stale statement version blocks a second proposal that would otherwise coexist.

    "A mismatch against the statement's current `version` is rejected with
    `ERR_STALE_STATEMENT_VERSION` (HTTP 412)." The version moves for two distinct
    reasons: a merely PROPOSED sibling moves it without moving money — "the parent
    statement's `version` is nonetheless bumped, which is precisely why the next
    proposer must re-read the statement before submitting" — and an approval moves
    it again while recomputing the payable.

    Design: Corner/cross_cutting_complexity_layers/occ_statement_version_guards_adjustment_proposals
    """
    program = _make_program()
    agent = _make_agent("A1 Principal")
    merchant = _board_merchant(
        agent["id"], program["id"], "MID-9001", equipment_lease_monthly_cents=1000
    )
    validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE))

    batch = validate_success(
        api_client.create_residual_batch(
            {
                "processor_program_id": program["id"],
                "period_month": "2026-07",
                "coverage_start": "2026-07-01",
                "coverage_end": "2026-08-01",
                "file_checksum": "sha256:occ-0001",
            },
            ANALYST_ONE,
        ),
        201,
    )
    validate_success(
        api_client.create_residual_line(
            batch["id"],
            {
                "merchant_id": merchant["id"],
                "transaction_count": 100,
                "sales_volume_cents": 1000000,
                "interchange_cents": 20000,
                "assessments_cents": 1300,
                "gross_income_cents": 40000,
            },
            ANALYST_ONE,
        ),
        201,
    )
    validate_success(api_client.normalize_residual_batch(batch["id"], ANALYST_ONE))
    validate_success(api_client.post_residual_batch(batch["id"], CONTROLLER_ONE))

    rows, _ = validate_paginated(
        api_client.list_agent_statements(
            ANALYST_ONE, {"agent_id": agent["id"], "period_month": "2026-07"}
        )
    )
    statement = rows[0]
    statement_id = statement["id"]
    first_version = statement["version"]
    assert statement["direct_residual_cents"] == 6300, (
        f"expected direct_residual_cents 6300, got {statement['direct_residual_cents']}"
    )
    assert statement["net_payable_cents"] == 6300

    def _propose(expected_version, **overrides):
        payload = {
            "kind": "DISPUTE_CREDIT",
            "amount_cents": 500,
            "reason": "issuer reversed CB-77",
            "expected_statement_version": expected_version,
        }
        payload.update(overrides)
        return api_client.create_statement_adjustment(
            statement_id, payload, ANALYST_ONE
        )

    first_adjustment = validate_success(_propose(first_version), 201)
    assert first_adjustment["state"] == "PROPOSED"
    after_first = validate_success(
        api_client.get_agent_statement(statement_id, ANALYST_ONE)
    )
    assert after_first["adjustment_cents"] == 0, (
        "no money moves at proposal time — only APPLIED rows feed adjustment_cents"
    )
    assert after_first["net_payable_cents"] == 6300

    replayed = _propose(
        first_version, amount_cents=300, reason="issuer reversed CB-78"
    )
    validate_error(replayed, ApiErrorId.ERR_STALE_STATEMENT_VERSION.value, 412)
    _, meta_after_412 = validate_paginated(
        api_client.list_statement_adjustments(
            ANALYST_ONE, {"statement_id": statement_id}
        )
    )
    assert meta_after_412["total_count"] == 1, (
        f"the 412 must leave no adjustment row behind, got {meta_after_412['total_count']}"
    )

    second_version = after_first["version"]
    assert second_version == first_version + 1, (
        "the PROPOSED sibling alone moved the statement version, expected "
        f"{first_version + 1}, got {second_version}"
    )
    second_adjustment = validate_success(
        _propose(second_version, amount_cents=300, reason="issuer reversed CB-78"), 201
    )
    assert second_adjustment["state"] == "PROPOSED"

    validate_success(
        api_client.review_statement_adjustment(first_adjustment["id"], CONTROLLER_ONE)
    )
    applied = validate_success(
        api_client.approve_statement_adjustment(first_adjustment["id"], CONTROLLER_ONE)
    )
    assert applied["state"] == "APPLIED"
    after_apply = validate_success(
        api_client.get_agent_statement(statement_id, ANALYST_ONE)
    )
    assert after_apply["adjustment_cents"] == 500
    assert after_apply["net_payable_cents"] == 6800, (
        f"expected net_payable_cents 6800, got {after_apply['net_payable_cents']}"
    )
    assert after_apply["lifecycle_state"] == "DRAFT"
    assert after_apply["version"] > second_version, (
        "the approval's recompute bumps the statement version again"
    )

    stale_after_apply = _propose(
        second_version,
        kind="MANUAL_DEBIT",
        amount_cents=-100,
        reason="duplicate credit",
    )
    validate_error(stale_after_apply, ApiErrorId.ERR_STALE_STATEMENT_VERSION.value, 412)

    final_rows, final_meta = validate_paginated(
        api_client.list_statement_adjustments(
            ANALYST_ONE, {"statement_id": statement_id}
        )
    )
    assert final_meta["total_count"] == 2, (
        f"neither 412 left a row behind, expected 2, got {final_meta['total_count']}"
    )
    states = {row["id"]: row["state"] for row in final_rows}
    assert states[first_adjustment["id"]] == "APPLIED"
    assert states[second_adjustment["id"]] == "PROPOSED"


def _summary(agent_id: str) -> dict:
    return validate_success(api_client.get_agent_portfolio_summary(agent_id, ADMIN_ONE))


def test_attrition_threshold_is_inclusive_and_recrosses_in_both_directions():
    """The 2,500-bps hold is inclusive, PENDING-blind and re-evaluated every time.

    "The comparison is inclusive: an agent with four qualifying merchants of which
    exactly one has attrited stands at exactly 2,500 basis points and is held."
    The denominator counts only ACTIVE and ATTRITED rows — "merchants still
    `PENDING` are excluded from both the numerator and the denominator" — so
    activating the pending merchant later dilutes the same single attrition back
    below the threshold and clears the hold.

    Design: Corner/cross_cutting_complexity_layers/attrition_threshold_is_inclusive_and_recrosses_in_both_directions
    """
    program = _make_program()
    held_agent = _make_agent("A1 Four Plus Pending")
    diluted_agent = _make_agent("A2 Five Active")

    held_merchants = [
        _board_merchant(held_agent["id"], program["id"], f"MID-A10{index}")
        for index in range(1, 6)
    ]
    for merchant in held_merchants[:4]:
        validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE))
    pending_merchant = held_merchants[4]

    diluted_merchants = [
        _board_merchant(diluted_agent["id"], program["id"], f"MID-A20{index}")
        for index in range(1, 6)
    ]
    for merchant in diluted_merchants:
        validate_success(api_client.activate_merchant(merchant["id"], ADMIN_ONE))

    validate_success(
        api_client.attrite_merchant(
            held_merchants[0]["id"], {"attrition_date": "2026-07-20"}, ADMIN_ONE
        )
    )
    validate_success(
        api_client.attrite_merchant(
            diluted_merchants[0]["id"], {"attrition_date": "2026-07-20"}, ADMIN_ONE
        )
    )

    at_threshold = _summary(held_agent["id"])
    assert at_threshold["portfolio_attrition_bps"] == 2500, (
        "one attrition out of four non-PENDING merchants is exactly 2500 bps, got "
        f"{at_threshold['portfolio_attrition_bps']}"
    )
    assert at_threshold["residual_hold"] is True, (
        "the threshold comparison is inclusive, so exactly 2500 bps is held"
    )
    assert at_threshold["portfolio_merchant_count"] == 5, (
        "portfolio_merchant_count counts the PENDING merchant too, got "
        f"{at_threshold['portfolio_merchant_count']}"
    )
    assert at_threshold["active_merchant_count"] == 3
    assert at_threshold["attrited_merchant_count"] == 1

    below_threshold = _summary(diluted_agent["id"])
    assert below_threshold["portfolio_attrition_bps"] == 2000, (
        "one attrition out of five is 2000 bps, got "
        f"{below_threshold['portfolio_attrition_bps']}"
    )
    assert below_threshold["residual_hold"] is False

    # Activating the PENDING merchant changes the denominator, not the attrition.
    validate_success(api_client.activate_merchant(pending_merchant["id"], ADMIN_ONE))
    diluted = _summary(held_agent["id"])
    assert diluted["portfolio_attrition_bps"] == 2000, (
        "one attrition out of five non-PENDING merchants is 2000 bps, got "
        f"{diluted['portfolio_attrition_bps']}"
    )
    assert diluted["residual_hold"] is False, (
        "falling back under 2500 bps clears the risk flag"
    )
    assert diluted["attrited_merchant_count"] == 1

    # The trigger is re-evaluated on every membership change, never latched.
    validate_success(
        api_client.attrite_merchant(
            held_merchants[1]["id"], {"attrition_date": "2026-07-25"}, ADMIN_ONE
        )
    )
    recrossed = _summary(held_agent["id"])
    assert recrossed["portfolio_attrition_bps"] == 4000, (
        "two attritions out of five is 4000 bps, got "
        f"{recrossed['portfolio_attrition_bps']}"
    )
    assert recrossed["residual_hold"] is True
    assert recrossed["active_merchant_count"] == 3
    assert recrossed["attrited_merchant_count"] == 2

    for merchant in held_merchants[:2]:
        validate_success(
            api_client.reactivate_merchant(
                merchant["id"], {"reactivation_date": "2026-07-28"}, ADMIN_ONE
            )
        )
    reset = _summary(held_agent["id"])
    assert reset["portfolio_attrition_bps"] == 0, (
        f"zero attritions out of five is 0 bps, got {reset['portfolio_attrition_bps']}"
    )
    assert reset["residual_hold"] is False
    assert reset["active_merchant_count"] == 5
    assert reset["attrited_merchant_count"] == 0
    assert reset["portfolio_merchant_count"] == 5
