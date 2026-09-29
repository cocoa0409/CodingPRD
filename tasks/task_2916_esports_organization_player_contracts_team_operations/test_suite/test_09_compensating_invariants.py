"""Two ledgers that must survive being wound forward and then wound back.

The salary identity and the prize identity are each checked at three checkpoints,
and both compensating actions are deliberately partial: they conserve their own
money quantity and leave the collateral damage where it fell.
"""

from test_helpers import (
    api_client,
    fixtures,
    make_finance_officer_headers,
    make_general_manager_headers,
    make_league_admin_headers,
    make_scout_headers,
    make_sponsorship_manager_headers,
    validate_success,
)


def _executed_release_with_a_voided_deliverable():
    """Two contracts, one ASSIGNED deliverable on the second, and an EXECUTED release of it."""
    ctx = fixtures.setup_two_signed_players()
    deal_state = fixtures.setup_deal_with_deliverable(
        ctx["org"]["id"],
        ctx["contract_two"]["id"],
        deliverable_overrides={
            "deliverable_type": "APPEARANCE",
            "due_at": "2026-09-20T00:00:00Z",
        },
    )
    ctx["deal"] = deal_state["deal"]
    ctx["assignment"] = deal_state["assignment"]
    ctx["gm_headers"] = make_general_manager_headers(ctx["org"]["id"])

    ctx["before_release"] = validate_success(
        api_client.get_organization(ctx["org"]["id"], ctx["gm_headers"])
    )
    fixtures.set_clock("2026-08-20T00:00:00Z")
    ctx["move"] = fixtures.setup_executed_move(
        ctx["org"]["id"],
        ctx["player_two"]["id"],
        "RELEASE",
        ctx["contract_two"]["id"],
        effective_at="2026-08-20T00:00:00Z",
    )
    return ctx


def test_reversal_puts_back_the_same_integer_the_release_took_out():
    """The three salary checkpoints, and the budget identity at each of them.

    PRD: "Step seven takes the cap relief from the contract's frozen charge: `released_cap_cents` is
    set to the contract's `provisional_cap_charge_cents`, which is what makes a later reversal
    exact."
    PRD: "Because the reversal must re-commit the released salary, the organization's
    `uncommitted_salary_cents` must be greater than or equal to the move's `released_cap_cents` — if
    the organization has spent the freed budget elsewhere in the meantime the reversal is refused
    with `ERR_SALARY_CAP_EXCEEDED` rather than being performed partially."
    PRD: "Because the commitment moves by the same frozen integer in both directions,
    `committed_salary_cents` returns to precisely its pre-execution value and the organization's
    budget identity holds."
    PRD: "`uncommitted_salary_cents` is `annual_salary_budget_cents` less `committed_salary_cents`."

    Design: Difficulty/compensating_invariant/roster_move_reversal_restores_the_organization_salary_ledger_exactly
    """
    ctx = _executed_release_with_a_voided_deliverable()

    before = ctx["before_release"]
    assert before["committed_salary_cents"] == 22191781
    assert before["uncommitted_salary_cents"] == 27808219
    assert before["active_roster_count"] == 2
    assert (
        before["committed_salary_cents"] + before["uncommitted_salary_cents"] == 50000000
    )

    assert ctx["move"]["move_status"] == "EXECUTED"
    assert ctx["move"]["released_cap_cents"] == 9863014
    after_execute = validate_success(
        api_client.get_organization(ctx["org"]["id"], ctx["gm_headers"])
    )
    assert after_execute["committed_salary_cents"] == 12328767
    assert after_execute["uncommitted_salary_cents"] == 37671233
    assert after_execute["active_roster_count"] == 1
    assert (
        after_execute["committed_salary_cents"]
        + after_execute["uncommitted_salary_cents"]
        == 50000000
    )

    reversed_move = validate_success(
        api_client.reverse_roster_move(
            ctx["move"]["id"],
            {"reversal_reason": "release filed against the wrong player"},
            make_league_admin_headers(),
        )
    )
    assert reversed_move["move_status"] == "REVERSED"

    after_reverse = validate_success(
        api_client.get_organization(ctx["org"]["id"], ctx["gm_headers"])
    )
    assert after_reverse["committed_salary_cents"] == 22191781
    assert after_reverse["uncommitted_salary_cents"] == 27808219
    assert after_reverse["active_roster_count"] == 2


def test_reversal_restores_the_employment_but_not_the_voided_deliverable():
    """The contract, the player and the roster seat come back; the sponsor's row does not.

    PRD: "A permitted reversal records a mandatory `reversal_reason`, moves `move_status` `EXECUTED`
    → `REVERSED`, returns the contract `TERMINATED` → `ACTIVE`, returns the player `FREE_AGENT` →
    `SIGNED` with `current_organization_id` restored to the reversing move's organization and both
    `free_agency_window_ends_at` and `last_release_organization_id` cleared to null, increases
    `committed_salary_cents` by exactly `released_cap_cents` and `active_roster_count` by 1, and
    zeroes the settlement money fields."
    PRD: "The blocks cancelled by the execution stay cancelled and the deliverables voided by it stay
    voided; only the salary quantity is conserved."
    PRD: "A dedicated computed read gives the league office, the general manager and finance a single
    view of an organization's cap position: it returns `annual_salary_budget_cents`,
    `committed_salary_cents`, `uncommitted_salary_cents`, `active_roster_count`,
    `prize_payable_cents` and `wellness_flag_count` as stored, plus the two cap-charge variants side
    by side."

    Design: Difficulty/compensating_invariant/roster_move_reversal_restores_the_organization_salary_ledger_exactly
    """
    ctx = _executed_release_with_a_voided_deliverable()
    sponsor_headers = make_sponsorship_manager_headers(ctx["org"]["id"])

    voided = validate_success(
        api_client.get_deliverable_assignment(ctx["assignment"]["id"], sponsor_headers)
    )
    assert voided["assignment_status"] == "VOIDED"

    reversed_move = validate_success(
        api_client.reverse_roster_move(
            ctx["move"]["id"],
            {"reversal_reason": "release filed against the wrong player"},
            make_league_admin_headers(),
        )
    )
    assert reversed_move["move_status"] == "REVERSED"
    assert reversed_move["reversal_reason"] == "release filed against the wrong player"

    contract = validate_success(
        api_client.get_contract(ctx["contract_two"]["id"], ctx["gm_headers"])
    )
    assert contract["contract_status"] == "ACTIVE"
    assert contract["provisional_cap_charge_cents"] == 9863014

    player = validate_success(
        api_client.get_player(ctx["player_two"]["id"], make_scout_headers())
    )
    assert player["player_status"] == "SIGNED"
    assert player["current_organization_id"] == ctx["org"]["id"]
    assert player["free_agency_window_ends_at"] is None
    assert player["last_release_organization_id"] is None

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(ctx["org"]["id"], ctx["gm_headers"])
    )
    assert cap_summary["committed_salary_cents"] == 22191781
    assert cap_summary["uncommitted_salary_cents"] == 27808219
    assert cap_summary["active_roster_count"] == 2

    still_voided = validate_success(
        api_client.get_deliverable_assignment(ctx["assignment"]["id"], sponsor_headers)
    )
    assert still_voided["assignment_status"] == "VOIDED"
    deal = validate_success(
        api_client.get_sponsorship_deal(ctx["deal"]["id"], sponsor_headers)
    )
    assert deal["assigned_count"] == 0
    assert deal["deal_status"] == "ACTIVE"


def _approved_distribution_over_one_contract():
    """One ACTIVE contract and a 10,000,000-cent distribution walked DRAFT to APPROVED."""
    ctx = fixtures.setup_signed_player()
    fixtures.set_clock("2026-08-21T00:00:00Z")
    ctx["draft"] = fixtures.create_distribution(ctx["org"]["id"], ctx["league"]["id"])
    ctx["calculated"] = fixtures.calculate_distribution(ctx["draft"]["id"])
    ctx["approved"] = fixtures.approve_distribution(ctx["draft"]["id"])
    return ctx


def test_the_prize_ledger_identity_holds_in_draft_and_after_sign_off():
    """Two of the three checkpoints, plus the payable the waterfall added.

    PRD: "That ledger identity — `gross_prize_cents` equalling the sum of `association_levy_cents`,
    `org_share_cents`, `allocated_cents` and `unallocated_cents` — is recomputed and must hold exactly
    after the calculation, after the approval and after a void."
    PRD: "The calculation moves `distribution_status` `DRAFT` → `CALCULATED`, stamps
    `calculated_by_user_id` with the calling finance officer's identifier, writes one allocation row
    per eligible contract with `allocation_status` of `CALCULATED` and a `prize_distribution_id` and
    `contract_id` naming its parents, and increases the organization's `prize_payable_cents` by
    `org_share_cents`."
    PRD: "Approval moves the distribution `CALCULATED` → `APPROVED`, moves every child allocation
    `CALCULATED` → `APPROVED`, and stamps `approved_by_user_id`."
    PRD: "It does not change `prize_payable_cents`: that counter already includes every distribution
    in `CALCULATED` or `APPROVED`, so the amount was added when the waterfall ran and simply stays
    counted."

    Design: Difficulty/compensating_invariant/prize_distribution_void_restores_the_gross_prize_ledger_and_org_payable
    """
    ctx = _approved_distribution_over_one_contract()
    finance_headers = make_finance_officer_headers()

    draft = ctx["draft"]
    assert draft["distribution_status"] == "DRAFT"
    assert draft["association_levy_cents"] == 0
    assert draft["org_share_cents"] == 0
    assert draft["allocated_cents"] == 0
    assert draft["unallocated_cents"] == 10000000

    approved = ctx["approved"]
    assert approved["distribution_status"] == "APPROVED"
    assert approved["association_levy_cents"] == 250000
    assert approved["org_share_cents"] == 3412500
    assert approved["allocated_cents"] == 6337500
    assert approved["unallocated_cents"] == 0
    assert approved["withholding_total_cents"] == 950625
    assert (
        approved["association_levy_cents"]
        + approved["org_share_cents"]
        + approved["allocated_cents"]
        + approved["unallocated_cents"]
        == 10000000
    )

    rows = validate_success(
        api_client.list_prize_allocations(draft["id"], finance_headers)
    )
    assert len(rows) == 1
    assert rows[0]["allocation_status"] == "APPROVED"

    organization = validate_success(
        api_client.get_organization(ctx["org"]["id"], make_general_manager_headers(ctx["org"]["id"]))
    )
    assert organization["prize_payable_cents"] == 3412500


def test_voiding_winds_the_prize_ledger_back_and_hands_the_payable_back():
    """The third checkpoint: the four money fields collapse and the rows survive as VOIDED.

    PRD: "A mandatory `void_reason` is recorded, the distribution moves to the terminal `VOIDED`,
    every child allocation moves to `VOIDED`, and the ledger is wound back to its pre-calculation
    shape: `allocated_cents`, `withholding_total_cents`, `escrow_total_cents`, `org_share_cents` and
    `association_levy_cents` all return to 0 while `unallocated_cents` returns to the full
    `gross_prize_cents`."
    PRD: "The `org_share_cents` the calculation had added to the organization's `prize_payable_cents`
    is withdrawn again, exactly."
    PRD: "`prize_payable_cents` is the sum of `org_share_cents` over that organization's prize
    distributions whose `distribution_status` is `CALCULATED` or `APPROVED`."

    Design: Difficulty/compensating_invariant/prize_distribution_void_restores_the_gross_prize_ledger_and_org_payable
    """
    ctx = _approved_distribution_over_one_contract()
    finance_headers = make_finance_officer_headers()

    voided = validate_success(
        api_client.void_prize_distribution(
            ctx["draft"]["id"],
            {"void_reason": "tournament result overturned by the referee panel"},
            finance_headers,
        )
    )
    assert voided["distribution_status"] == "VOIDED"
    assert voided["association_levy_cents"] == 0
    assert voided["org_share_cents"] == 0
    assert voided["allocated_cents"] == 0
    assert voided["withholding_total_cents"] == 0
    assert voided["escrow_total_cents"] == 0
    assert voided["unallocated_cents"] == 10000000
    assert (
        voided["association_levy_cents"]
        + voided["org_share_cents"]
        + voided["allocated_cents"]
        + voided["unallocated_cents"]
        == 10000000
    )

    rows = validate_success(
        api_client.list_prize_allocations(ctx["draft"]["id"], finance_headers)
    )
    assert len(rows) == 1
    assert rows[0]["allocation_status"] == "VOIDED"
    assert rows[0]["gross_share_cents"] == 6337500

    cap_summary = validate_success(
        api_client.get_organization_cap_summary(ctx["org"]["id"], finance_headers)
    )
    assert cap_summary["prize_payable_cents"] == 0

    contract = validate_success(
        api_client.get_contract(
            ctx["contract"]["id"], make_general_manager_headers(ctx["org"]["id"])
        )
    )
    assert contract["contract_status"] == "ACTIVE"
    assert contract["provisional_cap_charge_cents"] == 12328767
