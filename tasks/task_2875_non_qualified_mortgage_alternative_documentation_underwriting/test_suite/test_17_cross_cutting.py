"""Cross-cutting layers: optimistic concurrency riding on top of cascades, where the
version a client echoes is moved by a write it never issued.
"""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_STALE_LOAN_FILE_VERSION,
    ERR_STALE_POOL_VERSION,
)
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    SECURITIZATION_ANALYST,
    underwriter,
)

INVESTOR = "INV-ALPHA"
SEASONING = {"FORECLOSURE": 36, "SHORT_SALE": 24, "DEED_IN_LIEU": 24,
             "BK_CH7": 24, "BK_CH13": 12, "MODIFICATION": 12,
             "MORTGAGE_LATE_60": 12}


def test_a_suspension_invalidates_the_version_a_worksheet_create_echoes(api):
    """The concurrency check reads a version that the suspension cascade just moved.

    PRD 2.7: "A request to `POST /income-worksheets` must carry
    `expected_loan_file_version` as a mandatory field whose value is the `version` the
    client last observed on the target loan file. If that value does not equal the loan
    file's current `version`, the create is rejected with `ERR_STALE_LOAN_FILE_VERSION`
    (HTTP 412)."

    PRD 2.4: "an integer `version` that starts at 1 and increments by one each time the
    resource is mutated"

    PRD 3.8: "The file's `Underwriter` supplies a `suspension_reason`, the file moves
    `UNDERWRITING → SUSPENDED`, the condition note is recorded, and the determination
    snapshot is invalidated"

    PRD 3.4: "Opening is permitted while the file is in `DOC_TYPE_SELECTED`,
    `UNDERWRITING` or `SUSPENDED`" and "A new worksheet is born in `DRAFT` status, and its
    creation increments the loan file's `version` by one."

    PRD 2.8: "`ERR_STALE_LOAN_FILE_VERSION` — on `POST /income-worksheets`." sits at
    position 8, above the state band, so the identical body is refused on the version
    alone while the suspended state remains a perfectly legal one to open against.

    Design: Corner/cross_cutting_complexity_layers/corner_occ_worksheet_create_rejects_stale_loan_file_version
    """
    program = fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion OCC",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        seasoning_matrix=SEASONING)
    borrower = fx.create_borrower(api, legal_name="Stale Stan", fico_score=720,
                                 monthly_debt_obligations_cents=90000,
                                 verified_liquid_assets_cents=67222226,
                                 age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "ASSET_DEPLETION", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       300000, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    observed = fx.get_loan_file(api, loan_file["id"], uw)
    stale_version = observed["version"]

    fx.suspend(api, loan_file["id"], uw,
               "Awaiting updated brokerage statement")

    body = F.worksheet_payload(loan_file["id"], "ASSET_DEPLETION",
                               stale_version,
                               asset_bucket_checking_cents=15000000,
                               asset_bucket_brokerage_cents=22222225,
                               asset_bucket_retirement_cents=30000001)
    refused = api.create_worksheet(body, uw)
    validate_error(refused, ERR_STALE_LOAN_FILE_VERSION)

    # The suspension is the mutation that moved the file out from under the writer,
    # and it left the file in a state that may still be opened against.
    suspended = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_version(suspended, stale_version + 1)
    A.assert_fields(suspended, {"status": "SUSPENDED",
                                "atr_documentation_status": "INCOMPLETE",
                                "safe_harbor_class": "NOT_EVALUATED"})

    body["expected_loan_file_version"] = suspended["version"]
    worksheet = validate_success(api.create_worksheet(body, uw), 201)

    A.assert_fields(worksheet, {"loan_file_id": loan_file["id"],
                                "method": "ASSET_DEPLETION",
                                "status": "DRAFT"})
    A.assert_version(worksheet, 1)
    listed = api.list_worksheets(loan_file["id"], uw)
    rows = validate_success(listed)
    A.assert_ids_equal(rows, [worksheet["id"]], "worksheet ids")
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 1, False)
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_version(after, stale_version + 2)
    A.assert_fields(after, {"status": "SUSPENDED"})


def test_every_pool_write_consumes_the_version_the_previous_write_produced(api):
    """Two membership writes and a settlement, each refused when it replays a version.

    PRD 2.7: "A request to `POST /securitization-pools/{id}/loans` must carry
    `expected_pool_version` as a mandatory field whose value is the `version` the analyst
    last observed on the target pool. A mismatch with the pool's current `version` is
    rejected with `ERR_STALE_POOL_VERSION` (HTTP 412)." and "The same
    `expected_pool_version` field, with the same rejection code and status, is required on
    `POST /securitization-pools/{id}/removals`."

    PRD 3.9: "On success the loan's `pool_id` is set, the three pool metrics are
    recomputed, the pool's `version` increments by one"

    PRD 3.9: "On success the named loan's `pool_id` is cleared, the three metrics are
    recomputed, and `version` increments by one; a settlement finalisation moves the pool
    `OPEN → SETTLED`, which is terminal, and leaves all three metrics at zero."

    PRD 3.9: "Because removal recomputes rather than subtracts, removing a loan restores
    the pre-assignment aggregates exactly." and "When the aggregate balance is zero the
    coupon is 0.0000 rather than undefined."

    PRD 2.8: "`ERR_STALE_POOL_VERSION` — on `POST /securitization-pools/{id}/loans` and
    `POST /securitization-pools/{id}/removals`." stands at position 9, above both
    "`ERR_POOL_STATE_INVALID` — on `POST /securitization-pools/{id}/loans` and `POST
    /securitization-pools/{id}/removals`." at 16 and "`ERR_LOAN_ALREADY_POOLED` — on `POST
    /securitization-pools/{id}/loans`." at 33, so a replayed version is reported even
    though the same replay is also a double assignment.

    Design: Corner/cross_cutting_complexity_layers/corner_occ_pool_writes_reject_stale_pool_version
    """
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR Pool OCC", min_dscr=1.1000,
        max_ltv_pct=85.00, min_fico=660, min_reserves_months=6,
        min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True, seasoning_matrix=SEASONING)
    borrower = fx.create_borrower(api, legal_name="Pooled Pia", fico_score=700,
                                 monthly_debt_obligations_cents=0,
                                 verified_liquid_assets_cents=5000000,
                                 age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT",
        purpose="PURCHASE", lien_position="FIRST", note_rate_pct=8.750,
        apor_pct=6.100, term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        gross_market_rent_cents=620000, lease_rent_cents=640000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       600000, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-07-01T00:00:00Z", 80000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.approve(api, loan_file["id"], uw)
    closed = fx.close(api, loan_file["id"])
    A.assert_fields(closed, {"status": "CLOSED", "securitization_eligible": True})

    pool = fx.create_pool(api, "P-2026-09-OCC", INVESTOR, 200000000)
    v1 = pool["version"]
    A.assert_fields(pool, {"status": "OPEN", "member_loan_count": 0})

    delivered = fx.assign_loan(api, pool["id"], loan_file["id"], v1)

    A.assert_fields(delivered, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_money(delivered["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_decimal_equals(delivered["weighted_avg_coupon_pct"], "8.7500", 4,
                            "weighted_avg_coupon_pct")
    A.assert_version(delivered, v1 + 1)
    v2 = delivered["version"]

    # Replaying the consumed version is refused on the version, not on membership.
    replayed = api.assign_loan_to_pool(
        pool["id"], F.pool_assignment_payload(loan_file["id"], v1),
        SECURITIZATION_ANALYST)
    validate_error(replayed, ERR_STALE_POOL_VERSION)

    emptied = fx.remove_loan(api, pool["id"], "ANALYST_DISCRETION", v2,
                             loan_file["id"])

    A.assert_fields(emptied, {"member_loan_count": 0, "status": "OPEN"})
    A.assert_money(emptied["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_decimal_equals(emptied["weighted_avg_coupon_pct"], "0.0000", 4,
                            "weighted_avg_coupon_pct")
    A.assert_version(emptied, v2 + 1)
    v3 = emptied["version"]

    # The removal consumed v2 in its turn, so the settlement may not reuse it.
    stale_settlement = api.remove_from_pool(
        pool["id"], F.pool_removal_payload("SETTLEMENT_FINALIZED", v2),
        SECURITIZATION_ANALYST)
    validate_error(stale_settlement, ERR_STALE_POOL_VERSION)

    settled = fx.remove_loan(api, pool["id"], "SETTLEMENT_FINALIZED", v3)

    A.assert_fields(settled, {"status": "SETTLED", "member_loan_count": 0})
    A.assert_money(settled["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_decimal_equals(settled["weighted_avg_coupon_pct"], "0.0000", 4,
                            "weighted_avg_coupon_pct")
    A.assert_version(settled, v3 + 1)
    final = validate_success(api.get_pool(pool["id"], SECURITIZATION_ANALYST))
    A.assert_fields(final, {"status": "SETTLED", "member_loan_count": 0})
    A.assert_version(final, v3 + 1)
    detached = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_is_null(detached, "pool_id")
