"""Derived figures and the money path: valuation, the management fee, the
distribution waterfall, and the segregated cash account.

Every figure here is pinned by the PRD's own arithmetic, so the assertions carry
literal expected values rather than re-deriving the formula in the test.
"""
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_platform_account, assert_distribution,
    TEST_USERS,
)
from test_helpers.fixtures import (
    set_clock, create_artist, create_artwork, create_investor, create_offering,
    create_screened_subscription, file_appraisal, file_verified_authentication,
    file_verified_provenance, file_circular, allocate_offering,
    create_custody_record, receive_custody, create_insurance_policy, bind_policy,
    get_artwork, get_offering, offering_version,
    setup_held_offering_with_policy, setup_closed_offering_with_distribution,
)

ISSUER = TEST_USERS["issuer_ops_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
INVESTOR = TEST_USERS["investor_headers"]


# ── The two valuation readings ───────────────────────────────────────────────

def _offering_with_unvetted_second_appraisal():
    """Two selected appraisals where the second has no provenance filed at or
    before it, so the legacy and restated readings diverge."""
    set_clock("2026-09-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    # The provenance attestation is on file before the first appraisal.
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    set_clock("2026-09-15T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=2_000,
                               liquidity_ratio_bps=1_000, hold_period_days=182)
    set_clock("2027-01-05T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 90_000_000), 201)
    return get_artwork(artwork["id"]), offering


def test_the_selection_flag_moves_to_the_newest_appraisal(api):
    """PRD 3.2: "Exactly one appraisal per artwork is selected at any moment."

    Design: Difficulty/dual_variant_calc/valuation_legacy_and_restated_diverge_on_an_unvetted_appraisal
    """
    artwork, offering = _offering_with_unvetted_second_appraisal()
    selected = get_success_data(api_client.list_appraisals(
        artwork["id"], ISSUER, params={"is_selected": "true"}))
    assert len(selected) == 1
    assert selected[0]["appraised_value_cents"] == 90_000_000


# ── The management-fee accrual ───────────────────────────────────────────────

def _offering_for_management_fee():
    """An offering whose holding clock started 2026-09-01 and finishes 302 days
    later at the accrual instant, on a 60,000,000-cent fee basis."""
    set_clock("2026-08-01T00:00:00Z")
    artist = create_artist()
    artwork = create_artwork(artist["id"], acquisition_cost_cents=60_000_000,
                             reserve_price_cents=100_000_000)
    file_verified_provenance(artwork["id"])
    file_verified_authentication(artwork["id"])
    set_clock("2026-08-01T00:00:00Z")
    validate_success(file_appraisal(artwork["id"], 80_000_000), 201)
    offering = create_offering(artwork["id"], total_shares=40_000,
                               price_per_share_cents=1_500, registration_cap_pct=2_000,
                               liquidity_ratio_bps=1_000, hold_period_days=182,
                               management_fee_bps=150)
    investor = create_investor()
    create_screened_subscription(offering["id"], investor["id"], requested_shares=4000)
    validate_success(file_circular(offering["id"]), 200)
    validate_success(allocate_offering(offering["id"]), 200)
    custody = create_custody_record(offering["id"])
    set_clock("2026-09-01T00:00:00Z")
    validate_success(receive_custody(custody["id"], offering["id"]), 200)
    set_clock("2027-06-30T00:00:00Z")
    return get_offering(offering["id"])


def test_management_fee_presentation_reads_the_plain_day_difference(api):
    """PRD 3.8: "Holding days are measured from `holding_clock_started_at` to
    `holding_period_end_at`, and that interval is read two ways: the presentation figure
    uses the plain difference between the two instants".

    Design: Difficulty/dual_variant_calc/management_fee_presentation_and_settlement_rounding_diverge
    """
    offering = _offering_for_management_fee()
    accrual = validate_success(api_client.accrue_fees(
        offering["id"], {"accrual_type": "MANAGEMENT"}, ISSUER), 201)

    assert accrual["basis_value_cents"] == 80_000_000
    assert accrual["presentation_amount_cents"] == 598_356


def test_management_fee_settlement_adds_the_start_day_back(api):
    """PRD 3.8: "while the figure that settles in cash adds the start day back, making
    a 182-day clock settle on 183 days and thus one day's fee larger."

    Design: Difficulty/dual_variant_calc/management_fee_presentation_and_settlement_rounding_diverge
    """
    offering = _offering_for_management_fee()
    accrual = validate_success(api_client.accrue_fees(
        offering["id"], {"accrual_type": "MANAGEMENT"}, ISSUER), 201)

    assert accrual["settle_amount_cents"] == 601_643
    assert accrual["settle_amount_cents"] > accrual["presentation_amount_cents"]


def test_the_two_management_fee_figures_are_reported_side_by_side(api):
    """PRD 2.7: "The two figures are reported side by side so the difference is
    auditable rather than hidden."

    Design: Difficulty/dual_variant_calc/management_fee_presentation_and_settlement_rounding_diverge
    """
    offering = _offering_for_management_fee()
    validate_success(api_client.accrue_fees(
        offering["id"], {"accrual_type": "MANAGEMENT"}, ISSUER), 201)

    rows = get_success_data(api_client.list_fee_accruals(
        offering["id"], ISSUER, params={"accrual_type": "MANAGEMENT"}))
    assert len(rows) == 1


def test_accruing_profit_participation_against_a_live_offering_is_refused(api):
    """PRD 3.8: "Profit participation is the other accrual and is computed off the
    distributable pool, but it may only be recorded once the offering's sale cycle has
    actually closed ... An attempt to accrue profit participation against a live
    offering is refused with `ERR_ACCRUAL_TYPE_UNSUPPORTED`."

    Design: Corner/endpoints/allocation_recomputes_the_ledger_and_the_holder_invested_total
    """
    offering = _offering_for_management_fee()
    res = api_client.accrue_fees(offering["id"],
                                 {"accrual_type": "PROFIT_PARTICIPATION"}, ISSUER)
    validate_error(res, "ERR_ACCRUAL_TYPE_UNSUPPORTED", expected_status=422)


# ── The distribution waterfall ───────────────────────────────────────────────

def _closed_sale_offering():
    """A completed sale on a 40,000-share issue with three cost lots whose
    pass-through sums to a 12,000,000-cent ledger, realising 120,000,000 cents."""
    return setup_closed_offering_with_distribution(
        holding_clock="2027-01-05T00:00:00Z", sale_clock="2027-06-30T00:00:00Z",
        executed_gross_cents=120_000_000,
        lots=[
            {"lot_type": "STORAGE", "cost_amount_cents": 6_000_000,
             "incurred_on": "2027-01-10T00:00:00Z"},
            {"lot_type": "INSURANCE", "cost_amount_cents": 3_000_000,
             "incurred_on": "2027-01-10T00:00:00Z"},
            {"lot_type": "CONSERVATION", "cost_amount_cents": 3_000_000,
             "incurred_on": "2027-02-01T00:00:00Z"},
        ],
        appraised_value_cents=90_000_000,
    )


def test_the_waterfall_deducts_the_investor_borne_cost_at_step_zero(api):
    """PRD 3.8: "The investor-borne operating cost comes out first: the offering's
    `custody_cost_ledger_cents` multiplied by its `cost_pass_through_bps` and divided by
    10000, floored, becomes the `distributed_cost_cents` deducted at step zero."

    Design: Difficulty/combinatorial_formula/sale_distribution_waterfall_floors_each_step_before_subtraction
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    assert_distribution(distribution)
    assert distribution["distributed_cost_cents"] == 12_000_000
    assert distribution["sale_gross_cents"] == 120_000_000


def test_the_waterfall_floors_the_management_fee_claim_before_subtraction(api):
    """PRD 3.8: "The issuer's management-fee claim, stored as `management_fee_cents`, is
    then taken as the `acquisition_cost_cents` multiplied by `management_fee_bps` and
    divided by 10000, floored."

    Design: Difficulty/combinatorial_formula/sale_distribution_waterfall_floors_each_step_before_subtraction
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    assert distribution["management_fee_cents"] == 900_000


def test_the_waterfall_floors_the_carried_interest_before_subtraction(api):
    """PRD 3.8: "The issuer's carried interest, `profit_participation_cents`, is next,
    as `distributable_cents` multiplied by `profit_participation_bps` and divided by
    10000, floored, which is the same figure the profit-participation accrual stores."

    Design: Difficulty/combinatorial_formula/sale_distribution_waterfall_floors_each_step_before_subtraction
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    assert distribution["profit_participation_cents"] == 12_000_000


def test_the_waterfall_residual_is_the_pinned_whole_cent_figure(api):
    """PRD 3.8: "each step is floored to whole cents before it is subtracted and
    rounding must never manufacture a negative residual." PRD 3.8: "What remains for
    the holders, `investor_residual_cents`, is the `distributable_cents` less the four
    preceding amounts in the order stated: the distributed cost, the management fee, the
    preferred return, and the profit participation."

    Design: Difficulty/combinatorial_formula/sale_distribution_waterfall_floors_each_step_before_subtraction
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    assert distribution["distributable_cents"] == 60_000_000
    assert distribution["investor_residual_cents"] == 32_785_480


def test_the_per_share_figure_integer_divides_the_residual(api):
    """PRD 3.8: "The per-share figure, `per_share_cents`, is the
    `investor_residual_cents` divided by the offering's `total_shares` using integer
    division."

    Design: Difficulty/combinatorial_formula/sale_distribution_waterfall_floors_each_step_before_subtraction
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    assert distribution["per_share_cents"] == 819
    assert distribution["investor_residual_cents"] - distribution["per_share_cents"] * 40_000 == 25_480


# ── The sale cascade ─────────────────────────────────────────────────────────

def test_a_completed_sale_closes_the_offering_and_sells_the_artwork(api):
    """PRD 3.8: "Proceeds at or above the reserve complete the cycle: the decision moves
    to terminal `EXECUTED` with `executed_gross_cents` stored, the offering reaches
    terminal `CLOSED`, the artwork reaches terminal `SOLD`, and a `Distribution` is
    created against the offering in status `CALCULATED`."

    Design: Difficulty/transitive_cascade/executed_sale_cascades_artwork_to_offering_to_distribution_to_account
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()

    assert decision["status"] == "EXECUTED"
    assert decision["executed_gross_cents"] == 120_000_000
    assert offering["status"] == "CLOSED"
    assert artwork["status"] == "SOLD"
    assert distribution["status"] == "CALCULATED"


def test_the_distribution_is_reachable_through_the_offerings_own_list(api):
    """PRD 3.8: "a `Distribution` is created against the offering in status
    `CALCULATED`."

    Design: Difficulty/transitive_cascade/executed_sale_cascades_artwork_to_offering_to_distribution_to_account
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    rows = get_success_data(api_client.list_distributions(offering["id"], ISSUER))
    assert [row["id"] for row in rows] == [distribution["id"]]


def test_every_side_effect_of_the_settlement_is_visible_immediately(api):
    """PRD 3.8: "Proceeds at or above the reserve complete the cycle ... and a
    `Distribution` is created against the offering in status `CALCULATED`."  Nothing is
    eventually consistent: the reads below follow the settlement with no intervening
    wait.

    Design: Corner/consistency_model/every_side_effect_of_a_settlement_is_visible_in_the_same_response
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()

    assert get_offering(offering["id"])["status"] == "CLOSED"
    assert get_artwork(artwork["id"])["status"] == "SOLD"
    assert len(get_success_data(api_client.list_distributions(offering["id"], ISSUER))) == 1


def test_the_list_view_reports_the_same_closed_status_as_the_detail_view(api):
    """PRD 2.3: "Unless a description states otherwise, list endpoints return resources
    ordered by creation timestamp ascending."

    Design: Corner/consistency_model/every_side_effect_of_a_settlement_is_visible_in_the_same_response
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    listed = [row for row in get_success_data(api_client.list_offerings(
        ISSUER, params={"artwork_id": artwork["id"]})) if row["id"] == offering["id"]]
    assert listed and listed[0]["status"] == "CLOSED"


# ── The segregated cash account ──────────────────────────────────────────────

def test_a_distribution_larger_than_the_account_balance_is_refused_whole(api):
    """PRD 3.8: "Because that account may never go negative, a payment that would
    overdraw it is refused with `ERR_ACCOUNT_UNDERFUNDED` (HTTP 409) and no partial debit
    is applied — which is the same conservation rule that guards cost-lot posting and
    offering withdrawal."

    Design: Difficulty/compensating_invariant/account_debits_never_let_the_conserved_balance_go_negative
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    account = validate_success(
        api_client.create_platform_account({"account_name": "Segregated Investor Funds"},
                                           TEST_USERS["platform_admin_headers"]), 201)
    assert account["balance_cents"] == 0

    res = api_client.pay_distribution(
        offering["id"], distribution["id"],
        {"expected_offering_version": offering_version(offering["id"])}, ISSUER)
    validate_error(res, "ERR_ACCOUNT_UNDERFUNDED", expected_status=409)


def test_a_refused_settlement_leaves_no_partial_debit(api):
    """PRD 2.7: "No write may take `balance_cents` below zero; a write that would do so
    is refused with `ERR_ACCOUNT_UNDERFUNDED` and no partial debit is applied."

    Design: Difficulty/compensating_invariant/account_debits_never_let_the_conserved_balance_go_negative
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    account = validate_success(
        api_client.create_platform_account({"account_name": "Segregated Investor Funds"},
                                           TEST_USERS["platform_admin_headers"]), 201)

    api_client.pay_distribution(
        offering["id"], distribution["id"],
        {"expected_offering_version": offering_version(offering["id"])}, ISSUER)

    after = validate_success(api_client.get_platform_account(account["id"],
                                                             TEST_USERS["platform_admin_headers"]), 200)
    assert after["balance_cents"] == 0
    assert after["total_paid_out_cents"] == 0
    assert_platform_account(after)


def test_a_refused_settlement_leaves_the_distribution_calculated(api):
    """PRD 3.8: "moving the distribution to `PAID` and advancing the offering's
    version" — a refused settlement performs neither.

    Design: Difficulty/compensating_invariant/account_debits_never_let_the_conserved_balance_go_negative
    """
    artwork, offering, decision, distribution, account = _closed_sale_offering()
    validate_success(
        api_client.create_platform_account({"account_name": "Segregated Investor Funds"},
                                           TEST_USERS["platform_admin_headers"]), 201)

    api_client.pay_distribution(
        offering["id"], distribution["id"],
        {"expected_offering_version": offering_version(offering["id"])}, ISSUER)

    still = get_success_data(api_client.list_distributions(offering["id"], ISSUER))[0]
    assert still["status"] == "CALCULATED"