"""Point-of-sale authorizations: the no-spill split-tender waterfall, the
withdrawal multiple rule, the no-cash-purse rule, and the daily withdrawal
limit boundary."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_retailer_system_headers,
    validate_error,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestSplitTenderNoSpill:
    def test_food_shortfall_rejected_despite_idle_cash_purse(self, api):
        """PRD §3.7: "Charging follows a no-spill waterfall: each bucket is
        bounded by its own purse and buckets never cross-charge."
        PRD §3.7: "If the disaster and food charges together cannot cover the
        food total, the authorization is rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/combinatorial_formula/split_tender_food_cash_no_spill
        """
        ctx = fx.setup_pos_ready(api, program_types=("FOOD", "CASH"),
                                 allotments={"FOOD": 2000, "CASH": 20000})
        retailer_id = ctx.retailer["id"]
        # Food bucket 2500 exceeds the food purse's 2000 even though the cash
        # purse idles at 20000: no cross-purse spill.
        resp = api.create_authorization(
            retailer_id,
            f.purchase_payload(ctx.card["id"], items=[
                f.purchase_item(unit_price_cents=2500)]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)
        food = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(food, spendable_balance_cents=2000)
        A.assert_purse_balances(cash, spendable_balance_cents=20000)
        # Nothing was debited: the food ledger holds only the POST_CREDIT.
        entries = fx.list_ledger(api, food["id"])
        A.assert_ledger_entry_types(entries, ["POST_CREDIT"])

    def test_cash_shortfall_rejected_with_food_bucket_untouched(self, api):
        """PRD §3.7: "Charging follows a no-spill waterfall: each bucket is
        bounded by its own purse and buckets never cross-charge."
        PRD §3.7: "Otherwise the `cash_charge_cents` is the smaller of the cash
        total and the cash purse's spendable balance, and a shortfall is
        rejected with `ERR_INSUFFICIENT_FUNDS`."

        Design: Difficulty/combinatorial_formula/split_tender_food_cash_no_spill
        """
        ctx = fx.setup_pos_ready(
            api, program_types=("FOOD", "CASH"),
            allotments={"FOOD": 2000, "CASH": 20000},
            item_entries=[
                f.item_entry(),  # 111111111111 food-eligible
                f.item_entry(upc=f.DEFAULTS["NON_FOOD_UPC"], food_eligible=False),
            ])
        retailer_id = ctx.retailer["id"]
        # Cash bucket 25000 exceeds the cash purse's 20000; the food bucket
        # (100) fits but may not subsidize the shortfall.
        resp = api.create_authorization(
            retailer_id,
            f.purchase_payload(ctx.card["id"], items=[
                f.purchase_item(unit_price_cents=100),
                f.purchase_item(upc=f.DEFAULTS["NON_FOOD_UPC"],
                                unit_price_cents=25000),
            ]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS)
        food = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(food, spendable_balance_cents=2000)
        A.assert_purse_balances(cash, spendable_balance_cents=20000)


class TestWithdrawalRules:
    def test_withdrawal_multiple_violation_rejected(self, api):
        """PRD §3.7: "The `withdrawal_amount_cents` must be an exact multiple of
        the contract's `cash_withdrawal_multiple_cents` (500 cents by default),
        else `ERR_WITHDRAWAL_MULTIPLE`."

        Design: Corner/validations/withdrawal_multiple_violation_rejected
        """
        ctx = fx.setup_pos_ready(api, program_types=("CASH",),
                                 allotments={"CASH": 60000})
        retailer_id = ctx.retailer["id"]
        resp = api.create_authorization(
            retailer_id,
            f.withdrawal_payload(ctx.card["id"], withdrawal_amount_cents=1001),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_WITHDRAWAL_MULTIPLE)

    def test_withdrawal_without_cash_purse_rejected(self, api):
        """PRD §3.7: "The case must hold a cash purse that is not `CLOSED`, else
        `ERR_NO_CASH_PURSE`."

        Design: Corner/validations/withdrawal_without_cash_purse_rejected
        """
        ctx = fx.setup_pos_ready(api)  # FOOD-only contract
        retailer_id = ctx.retailer["id"]
        resp = api.create_authorization(
            retailer_id,
            f.withdrawal_payload(ctx.card["id"], withdrawal_amount_cents=500),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_NO_CASH_PURSE)

    def test_withdrawal_at_exact_daily_limit_allowed(self, api):
        """PRD §3.7: "if that usage plus the requested amount exceeds the
        contract's `cash_withdrawal_daily_limit_cents` (50000 cents by default),
        the request is rejected with `ERR_DAILY_LIMIT_EXCEEDED`, while landing
        exactly on the limit is allowed because only a strictly greater total
        rejects."

        Design: Difficulty/boundary_precision_check/withdrawal_at_exact_daily_limit_allowed
        """
        ctx = fx.setup_pos_ready(api, program_types=("FOOD", "CASH"),
                                 allotments={"FOOD": 1000, "CASH": 60000})
        retailer_id = ctx.retailer["id"]
        card_id = ctx.card["id"]
        w1 = fx.place_withdrawal(api, retailer_id, card_id,
                                 withdrawal_amount_cents=30000)
        assert w1["cash_charge_cents"] == 30000
        # Cumulative 50000 == the limit: allowed (strictly-greater rejects).
        w2 = fx.place_withdrawal(api, retailer_id, card_id,
                                 withdrawal_amount_cents=20000)
        assert w2["cash_charge_cents"] == 20000
        # The next 500 would make 50500 > 50000.
        resp = api.create_authorization(
            retailer_id,
            f.withdrawal_payload(card_id, withdrawal_amount_cents=500),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_DAILY_LIMIT_EXCEEDED)
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(cash, spendable_balance_cents=10000)

    def test_voided_withdrawal_does_not_count_toward_daily_limit(self, api):
        """PRD §3.7: "The daily usage is the sum of `WITHDRAWAL_DEBIT` amounts
        on the case's cash purse whose `created_at` falls within the current UTC
        calendar day — from midnight inclusive to the next midnight exclusive —
        and whose transaction is not `VOIDED`"

        Design: Difficulty/boundary_precision_check/withdrawal_at_exact_daily_limit_allowed
        """
        ctx = fx.setup_pos_ready(api, program_types=("FOOD", "CASH"),
                                 allotments={"FOOD": 1000, "CASH": 60000})
        retailer_id = ctx.retailer["id"]
        card_id = ctx.card["id"]
        fx.place_withdrawal(api, retailer_id, card_id, withdrawal_amount_cents=30000)
        w2 = fx.place_withdrawal(api, retailer_id, card_id,
                                 withdrawal_amount_cents=20000)
        # Same-day void: the 20000 withdrawal leaves the daily usage total.
        fx.void_authorization(api, w2["id"], retailer_id)
        # Usage is back to 30000, so another 20000 lands exactly on the limit.
        w3 = fx.place_withdrawal(api, retailer_id, card_id,
                                 withdrawal_amount_cents=20000)
        assert w3["cash_charge_cents"] == 20000
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(cash, spendable_balance_cents=10000)
