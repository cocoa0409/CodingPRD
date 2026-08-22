"""Executing: writ feasibility, the levy hold, occupation windows and release."""

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_custody_conservation,
    create_enforcement_action_payload,
    create_verified_finding,
    draft_enforcement_action,
    make_case_manager_headers,
    make_enforcement_officer_headers,
    read_action,
    read_finding,
    read_judgment,
    setup_perfected_judgment,
    setup_requested_bank_levy,
    setup_served_bank_levy,
    setup_drafted_wage_garnishment,
    setup_stayed_judgment,
    validate_error,
    validate_success,
)

CM = make_case_manager_headers()
EO = make_enforcement_officer_headers("eo-1")


# ==========================================================================
# The three-way minimum on a wage garnishment
# ==========================================================================
def test_the_head_of_household_percentage_cap_binds_on_a_large_judgment(api):
    """PRD §3.5: "The first is the percentage cap: the debtor's
    `weekly_disposable_earnings_cents` multiplied by a cap rate and divided by ten
    thousand, rounded down to a whole cent."
    PRD §3.5: "That cap rate is normally 2,500 basis points — a quarter of
    disposable earnings — but drops to 1,000 basis points, a tenth, when the
    debtor's `head_of_household` flag is true **and** their `state_code` is `FL`;
    both conditions must hold for the lower cap to apply."
    PRD §3.5: "The withholding is the minimum of those three."

    Design: Difficulty/combinatorial_formula/garnishment_three_way_min_with_head_of_household_branch
    """
    ctx = setup_drafted_wage_garnishment(
        100_000,
        debtor_overrides={"full_name": "Marco Vela", "state_code": "FL",
                          "head_of_household": True},
        filing_overrides={"county_code": "FL-DUVAL", "state_code": "FL", "fee_cents": 0},
        court_case_number="CV-2026-0101",
        state_code="FL",
        original_principal_cents=5_000_000,
        interest_rate_bps=1_000,
        filing_costs_cents=45_000,
    )

    granted = validate_success(api.request_writ(ctx["action"]["id"], EO))
    assert granted["status"] == "WRIT_REQUESTED"
    assert granted["weekly_withholding_cents"] == 10_000, (
        "1,000 bps of 100,000 cents binds below both the federal floor cap of "
        "78,250 and the 5,335,411-cent payoff"
    )
    assert read_action(ctx["action"]["id"])["weekly_withholding_cents"] == 10_000


def test_the_outstanding_payoff_binds_when_the_debt_is_tiny(api):
    """PRD §3.5: "The third is the outstanding debt itself: the judgment's
    `total_payoff_cents` from a payoff replay as of the current clock date."
    PRD §3.5: "Which of the three caps binds shifts non-linearly with the debtor's
    earnings, the head-of-household branch, and the outstanding payoff."

    Design: Difficulty/combinatorial_formula/garnishment_three_way_min_with_head_of_household_branch
    """
    ctx = setup_drafted_wage_garnishment(
        100_000,
        debtor_overrides={"full_name": "Marco Vela", "state_code": "FL",
                          "head_of_household": True},
        filing_overrides={"county_code": "FL-DUVAL", "state_code": "FL", "fee_cents": 0},
        court_case_number="CV-2026-0102",
        state_code="FL",
        original_principal_cents=500,
        interest_rate_bps=0,
        filing_costs_cents=0,
    )

    granted = validate_success(api.request_writ(ctx["action"]["id"], EO))
    assert granted["weekly_withholding_cents"] == 500, (
        "the 500-cent payoff binds below the 10,000-cent percentage cap"
    )
    assert read_action(ctx["action"]["id"])["status"] == "WRIT_REQUESTED"


# ==========================================================================
# The federal-floor boundary
# ==========================================================================
def test_earnings_exactly_at_the_federal_floor_yield_no_writ(api):
    """PRD §3.5: "The second is the federal floor: disposable earnings less thirty
    times the federal minimum hourly wage of 725 cents, that is, less 21,750
    cents, with any negative result treated as zero."
    PRD §3.5: "The floor boundary is exact — weekly disposable earnings of exactly
    21,750 cents yield a federal-floor cap of zero and therefore a withholding of
    zero, while 21,751 cents yield a cap of one cent and a valid writ."
    PRD §3.5: "A withholding of zero is refused with `ERR_GARNISHMENT_BELOW_FLOOR`."

    Design: Difficulty/boundary_precision_check/garnishment_floor_exact_equality_at_thirty_times_minimum_wage
    """
    ctx = setup_drafted_wage_garnishment(
        21_750,
        debtor_overrides={"full_name": "Debtor At Floor", "head_of_household": False},
        filing_overrides={"fee_cents": 0},
        court_case_number="CV-2026-0601",
        filing_costs_cents=0,
    )

    validate_error(
        api.request_writ(ctx["action"]["id"], EO),
        ApiErrorId.ERR_GARNISHMENT_BELOW_FLOOR.value,
        422,
    )
    assert read_action(ctx["action"]["id"])["status"] == "DRAFT"


def test_one_cent_above_the_federal_floor_yields_a_one_cent_writ(api):
    """PRD §3.5: "The floor boundary is exact — weekly disposable earnings of
    exactly 21,750 cents yield a federal-floor cap of zero and therefore a
    withholding of zero, while 21,751 cents yield a cap of one cent and a valid
    writ."
    PRD §3.5: "for a wage garnishment it stores the computed
    `weekly_withholding_cents` on the action, while for a bank levy it leaves
    `levy_hold_cents` at 0 until service actually freezes money"

    Design: Difficulty/boundary_precision_check/garnishment_floor_exact_equality_at_thirty_times_minimum_wage
    """
    ctx = setup_drafted_wage_garnishment(
        21_751,
        debtor_overrides={"full_name": "Debtor Above Floor", "head_of_household": False},
        filing_overrides={"fee_cents": 0},
        court_case_number="CV-2026-0602",
        filing_costs_cents=0,
    )

    granted = validate_success(api.request_writ(ctx["action"]["id"], EO))
    assert granted["weekly_withholding_cents"] == 1
    assert granted["status"] == "WRIT_REQUESTED"
    assert read_action(ctx["action"]["id"])["weekly_withholding_cents"] == 1


# ==========================================================================
# Serving a bank levy and releasing it
# ==========================================================================
def test_serving_a_bank_levy_freezes_the_hold_and_taxes_the_sheriff_fee(api):
    """PRD §3.5: "The **bank levy hold** is computed against the linked finding,
    whose `asset_type` must be `BANK_ACCOUNT`. Take the finding's
    `available_cents`, subtract an automatic statutory exemption of 175,000 cents,
    and take the smaller of that difference and the judgment's
    `total_payoff_cents` from a payoff replay as of the current clock date; if the
    result is negative, the hold is zero."
    PRD §3.5: "For a bank levy, `levy_hold_cents` is computed first, against the
    payoff **before** the sheriff's fee is added to the judgment, and that many
    cents are moved out of the finding's `available_cents` and into its
    `frozen_cents`."
    PRD §3.5: "Only afterwards is `sheriff_fee_cents` — which stands at 0 from
    drafting until this moment — set to 12,500 cents, added to the judgment's
    `costs_balance_cents`, and the judgment's balances replayed."

    Design: Difficulty/compensating_invariant/levy_release_conserves_asset_custody_total
    """
    ctx = setup_requested_bank_levy(
        finding_value_cents=900_000, court_case_number="CV-2026-0902",
        filing_overrides={"fee_cents": 0},
    )
    before = read_finding(ctx["finding"]["id"])
    assert before["available_cents"] == 900_000
    assert before["frozen_cents"] == 0
    assert before["swept_cents"] == 0

    served = validate_success(api.serve_writ(ctx["action"]["id"], "2026-08-01", EO))
    assert served["levy_hold_cents"] == 725_000
    assert served["sheriff_fee_cents"] == 12_500

    finding = read_finding(ctx["finding"]["id"])
    assert finding["available_cents"] == 175_000
    assert finding["frozen_cents"] == 725_000
    assert finding["swept_cents"] == 0
    assert_custody_conservation(finding)
    assert read_judgment(ctx["judgment"]["id"])["costs_balance_cents"] == 57_500


def test_releasing_the_levy_restores_custody_but_not_the_sheriff_fee(api):
    """PRD §3.5: "From `SERVED` or `SUSPENDED` it returns `levy_hold_cents` from
    the finding's `frozen_cents` to its `available_cents`, leaves `swept_cents`
    alone, and zeroes `levy_hold_cents`; from `WRIT_REQUESTED` there is nothing
    frozen to return."
    PRD §2.11: "Serving and releasing therefore form a compensating pair that
    restores the split exactly — even though the sheriff's fee charged to the
    judgment at service is never refunded."
    PRD §2.11: "Asset custody obeys a conservation law that must hold at every
    instant: for any asset finding, `available_cents` plus `frozen_cents` plus
    `swept_cents` equals `estimated_value_cents`."

    Design: Difficulty/compensating_invariant/levy_release_conserves_asset_custody_total
    """
    ctx = setup_served_bank_levy(
        finding_value_cents=900_000, court_case_number="CV-2026-0903",
        filing_overrides={"fee_cents": 0},
    )
    frozen = read_finding(ctx["finding"]["id"])
    assert frozen["frozen_cents"] == 725_000

    released = validate_success(api.release_writ(ctx["action"]["id"], EO))
    assert released["status"] == "RELEASED"
    assert released["levy_hold_cents"] == 0

    finding = read_finding(ctx["finding"]["id"])
    assert finding["available_cents"] == 900_000
    assert finding["frozen_cents"] == 0
    assert finding["swept_cents"] == 0
    assert_custody_conservation(finding)
    assert read_judgment(ctx["judgment"]["id"])["costs_balance_cents"] == 57_500, (
        "the sheriff's fee already charged is not refunded"
    )


# ==========================================================================
# The half-open occupation window
# ==========================================================================
def _two_levies_on_one_account():
    """One 10,000,000-cent account carrying a levy served 2026-08-01 and a second
    levy whose writ has been requested but not yet served."""
    ctx = setup_served_bank_levy(
        finding_value_cents=10_000_000,
        court_case_number="CV-2026-0801",
        filing_overrides={"fee_cents": 0},
    )
    ctx["second_action"] = draft_enforcement_action(
        ctx["judgment"]["id"], ctx["finding"]["id"], "BANK_LEVY"
    )
    ctx["second_action"] = validate_success(
        api_client.request_writ(ctx["second_action"]["id"], EO)
    )
    return ctx


def test_a_second_levy_overlapping_the_occupation_window_is_refused(api):
    """PRD §3.5: "Service also opens an occupation window and that window may not
    collide: `expires_on` is set to 120 days after `served_on`, and the half-open
    interval running from `served_on` up to but not including `expires_on` must
    not overlap the equivalent interval of any other enforcement action on the
    same `asset_finding_id` whose status is `SERVED` or `SUSPENDED`."
    PRD §3.5: "Touching endpoints do not overlap, so a new levy that begins
    exactly on a prior levy's `expires_on` is permitted; anything genuinely
    overlapping is `ERR_LEVY_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/levy_half_open_interval_conflict_and_adjacency_on_asset_finding
    """
    ctx = _two_levies_on_one_account()
    assert ctx["action"]["levy_hold_cents"] == 5_335_411
    assert ctx["action"]["expires_on"] == "2026-11-29"

    advance_clock("2026-11-29T00:00:00Z", EO)

    validate_error(
        api.serve_writ(ctx["second_action"]["id"], "2026-11-28", EO),
        ApiErrorId.ERR_LEVY_WINDOW_CONFLICT.value,
        409,
    )


def test_a_levy_beginning_on_the_prior_expiry_date_is_permitted(api):
    """PRD §3.5: "Touching endpoints do not overlap, so a new levy that begins
    exactly on a prior levy's `expires_on` is permitted; anything genuinely
    overlapping is `ERR_LEVY_WINDOW_CONFLICT`."
    PRD §2.11: "Asset custody obeys a conservation law that must hold at every
    instant: for any asset finding, `available_cents` plus `frozen_cents` plus
    `swept_cents` equals `estimated_value_cents`."

    Design: Difficulty/resource_temporal_overlap/levy_half_open_interval_conflict_and_adjacency_on_asset_finding
    """
    ctx = _two_levies_on_one_account()
    advance_clock("2026-11-29T00:00:00Z", EO)

    served = validate_success(
        api.serve_writ(ctx["second_action"]["id"], "2026-11-29", EO)
    )
    assert served["status"] == "SERVED"
    assert served["levy_hold_cents"] == 4_489_589
    assert served["expires_on"] == "2027-03-29"

    finding = read_finding(ctx["finding"]["id"])
    assert finding["frozen_cents"] == 9_825_000
    assert finding["available_cents"] == 175_000
    assert finding["swept_cents"] == 0
    assert_custody_conservation(finding)


# ==========================================================================
# Corner coverage
# ==========================================================================
def test_the_levy_hold_is_capped_by_the_remaining_payoff(api):
    """PRD §3.5: "Take the finding's `available_cents`, subtract an automatic
    statutory exemption of 175,000 cents, and take the smaller of that difference
    and the judgment's `total_payoff_cents` from a payoff replay as of the current
    clock date; if the result is negative, the hold is zero."
    PRD §3.5: "Service also opens an occupation window and that window may not
    collide: `expires_on` is set to 120 days after `served_on`, and the half-open
    interval running from `served_on` up to but not including `expires_on` must
    not overlap the equivalent interval of any other enforcement action on the
    same `asset_finding_id` whose status is `SERVED` or `SUSPENDED`."

    Design: Corner/calculations/bank_levy_hold_capped_by_remaining_payoff_not_by_account_balance
    """
    ctx = setup_requested_bank_levy(
        finding_value_cents=10_000_000,
        court_case_number="CV-2026-3006",
        original_principal_cents=100_000,
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )

    served = validate_success(api.serve_writ(ctx["action"]["id"], "2026-08-01", EO))
    assert served["levy_hold_cents"] == 100_000, (
        "the 100,000-cent payoff binds below the 9,825,000-cent account headroom"
    )
    assert served["expires_on"] == "2026-11-29"

    finding = read_finding(ctx["finding"]["id"])
    assert finding["available_cents"] == 9_900_000
    assert finding["frozen_cents"] == 100_000
    assert finding["swept_cents"] == 0
    assert read_judgment(ctx["judgment"]["id"])["costs_balance_cents"] == 12_500


def test_an_account_at_exactly_the_auto_exemption_has_nothing_leviable(api):
    """PRD §3.5: "A hold of zero is refused with `ERR_NO_LEVIABLE_FUNDS`, and that
    check is applied twice — once as a feasibility test when the writ is
    requested, and again at service, because the account balance or the payoff may
    have moved in between."
    PRD §3.5: "Take the finding's `available_cents`, subtract an automatic
    statutory exemption of 175,000 cents, and take the smaller of that difference
    and the judgment's `total_payoff_cents` from a payoff replay as of the current
    clock date; if the result is negative, the hold is zero."

    Design: Corner/errors/no_leviable_funds_at_exactly_the_auto_exemption_balance
    """
    ctx = setup_perfected_judgment(
        court_case_number="CV-2026-6001",
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )
    at_exemption = create_verified_finding(
        ctx["judgment"]["id"], "inv-1",
        identifier_last4="0000", estimated_value_cents=175_000,
    )
    above_exemption = create_verified_finding(
        ctx["judgment"]["id"], "inv-1",
        identifier_last4="0001", estimated_value_cents=175_001,
    )
    action_at = draft_enforcement_action(
        ctx["judgment"]["id"], at_exemption["id"], "BANK_LEVY"
    )
    action_above = draft_enforcement_action(
        ctx["judgment"]["id"], above_exemption["id"], "BANK_LEVY"
    )

    validate_error(
        api.request_writ(action_at["id"], EO),
        ApiErrorId.ERR_NO_LEVIABLE_FUNDS.value,
        422,
    )
    assert read_action(action_at["id"])["status"] == "DRAFT"

    granted = validate_success(api.request_writ(action_above["id"], EO))
    assert granted["status"] == "WRIT_REQUESTED"


def test_releasing_an_already_released_writ_is_an_invalid_transition(api):
    """PRD §3.5: "**Release** is requested by an `EnforcementOfficer` or a
    `ComplianceOfficer` and is legal from three states, as `WRIT_REQUESTED →
    RELEASED`, `SERVED → RELEASED` or `SUSPENDED → RELEASED`."
    PRD §3.5: "All three of `COLLECTED`, `RELEASED` and `QUASHED` are terminal."
    PRD §2.8: "The target resource sits in one of the states from which the
    requested transition is legal — otherwise `ERR_INVALID_STATE` and HTTP 409.
    This applies to every state-transition endpoint."

    Design: Corner/state_machines/releasing_an_already_released_action_rejected_as_invalid_state
    """
    ctx = setup_requested_bank_levy(
        finding_value_cents=900_000,
        court_case_number="CV-2026-2006",
        interest_rate_bps=0,
        filing_costs_cents=0,
        filing_overrides={"fee_cents": 0},
    )

    released = validate_success(api.release_writ(ctx["action"]["id"], EO))
    assert released["status"] == "RELEASED"

    validate_error(
        api.release_writ(ctx["action"]["id"], EO),
        ApiErrorId.ERR_INVALID_STATE.value,
        409,
    )
    assert read_finding(ctx["finding"]["id"])["available_cents"] == 900_000


def test_drafting_a_new_writ_while_the_judgment_is_stayed_is_refused(api):
    """PRD §3.5: "Drafting is also one of the three operations blocked while the
    judgment's `enforcement_posture` is `STAYED`, which surfaces as
    `ERR_ENFORCEMENT_STAYED`."
    PRD §2.8: "The judgment's `enforcement_posture` is not `STAYED` — otherwise
    `ERR_ENFORCEMENT_STAYED` and HTTP 409. This guards exactly three operations:
    drafting an enforcement action, requesting its writ, and serving it."

    Design: Corner/validations/enforcement_write_blocked_while_the_judgment_is_stayed
    """
    ctx = setup_stayed_judgment(
        finding_value_cents=900_000,
        court_case_number="CV-2026-4012",
        filing_overrides={"fee_cents": 0},
    )
    assert ctx["judgment"]["enforcement_posture"] == "STAYED"

    validate_error(
        api.create_enforcement_action(
            create_enforcement_action_payload(
                ctx["judgment"]["id"], ctx["finding"]["id"], ctx["judgment"]["version"]
            ),
            CM,
        ),
        ApiErrorId.ERR_ENFORCEMENT_STAYED.value,
        409,
    )
    assert read_judgment(ctx["judgment"]["id"])["status"] == "ACTIVE"
