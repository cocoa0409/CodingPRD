"""Authorization voids: state gate, same-day window, retailer ownership, and
the compensating VOID_CREDIT restoring purse balances exactly."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_retailer_system_headers,
    validate_error,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestVoidGates:
    def test_void_already_voided_transaction_rejected(self, api):
        """PRD §3.7: "the transaction must still be `AUTHORIZED` — an already
        `VOIDED` or already `SETTLED` transaction is rejected with
        `ERR_TXN_NOT_VOIDABLE`"

        Design: Corner/state_machines/void_already_voided_transaction_rejected
        """
        ctx = fx.setup_pos_ready(api)
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 800}])[0]
        fx.void_authorization(api, txn["id"], ctx.retailer["id"])
        resp = api.void_authorization(
            txn["id"], make_retailer_system_headers(ctx.retailer["id"]))
        validate_error(resp, ApiErrorId.ERR_TXN_NOT_VOIDABLE)

    def test_void_on_next_calendar_day_rejected(self, api):
        """PRD §3.7: "the current clock's UTC calendar date must equal the
        transaction's `created_at` UTC calendar date, with any later day
        rejected as `ERR_VOID_WINDOW_EXPIRED`."
        PRD §3.9: "A settlement day runs from the contract's
        `settlement_cutoff_hour_utc` (hour 0 by default) on one day to the same
        hour on the next, including the start instant and excluding the end
        instant."

        Design: Corner/validations/void_on_next_calendar_day_rejected
        """
        ctx = fx.setup_pos_ready(
            api, contract_overrides={"settlement_cutoff_hour_utc": 6})
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 800}])[0]
        # 2026-09-03T02:00:00Z: the next UTC calendar day, but the 06:00 cutoff
        # has not run, so the transaction is still AUTHORIZED.
        fx.set_clock(api, "2026-09-03T02:00:00Z")
        resp = api.void_authorization(
            txn["id"], make_retailer_system_headers(ctx.retailer["id"]))
        validate_error(resp, ApiErrorId.ERR_VOID_WINDOW_EXPIRED)
        txns = validate_success(
            api.list_retailer_authorizations(ctx.retailer["id"], ADMIN), 200)
        assert txns[0]["txn_status"] == "AUTHORIZED", (
            "the rejected void must leave the transaction AUTHORIZED"
        )

    def test_retailer_cannot_void_other_retailers_transaction(self, api):
        """PRD §2.1: "When `X-User-Role` is `RetailerSystem`, `X-User-ID` is the
        `id` of the acting `Retailer`; the retailer identified in the request
        path, the retailer that owns a transaction being voided, and the
        retailer filing a settlement dispute must each equal `X-User-ID`, or the
        request is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/retailer_cannot_void_other_retailers_transaction
        """
        ctx = fx.setup_pos_ready(api)
        fx.add_retailer(api, ctx, retailer_name="R2", key="retailer_b",
                        with_item_file=False)
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 800}])[0]
        resp = api.void_authorization(
            txn["id"], make_retailer_system_headers(ctx.retailer_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        txns = validate_success(
            api.list_retailer_authorizations(ctx.retailer["id"], ADMIN), 200)
        assert txns[0]["txn_status"] == "AUTHORIZED"


class TestVoidCompensation:
    def test_authorization_void_restores_purse_balance(self, api):
        """PRD §3.7: "A successful void flips the transaction from `AUTHORIZED`
        to `VOIDED`, stamps `voided_at`, and posts a `VOID_CREDIT` of the exact
        debited amount to each purse the authorization debited, restoring each
        purse's balance exactly."

        Design: Difficulty/compensating_invariant/authorization_void_restores_purse_balance
        """
        ctx = fx.setup_pos_ready(api)  # FOOD purse at 30000
        purse_id = ctx.purses["FOOD"]["id"]
        pre = fx.get_purse(api, purse_id)
        A.assert_purse_balances(pre, ledger_balance_cents=30000,
                                spendable_balance_cents=30000)

        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 800}])[0]
        mid = fx.get_purse(api, purse_id)
        A.assert_purse_balances(mid, ledger_balance_cents=29200)

        voided = fx.void_authorization(api, txn["id"], ctx.retailer["id"])
        assert voided["txn_status"] == "VOIDED"
        post = fx.get_purse(api, purse_id)
        # The compensating pair leaves both views at their pre-action values.
        A.assert_purse_balances(post, ledger_balance_cents=30000,
                                spendable_balance_cents=30000)
        entries = fx.list_ledger(api, purse_id)
        A.assert_ledger_entry_types(
            entries, ["POST_CREDIT", "PURCHASE_DEBIT", "VOID_CREDIT"])
        assert entries[2]["amount_cents"] == 800

    def test_void_restores_each_charged_purse_exactly(self, api):
        """PRD §3.7: "A successful void flips the transaction from `AUTHORIZED`
        to `VOIDED`, stamps `voided_at`, and posts a `VOID_CREDIT` of the exact
        debited amount to each purse the authorization debited, restoring each
        purse's balance exactly."

        Design: Difficulty/compensating_invariant/authorization_void_restores_purse_balance
        """
        ctx = fx.setup_pos_ready(
            api, program_types=("FOOD", "CASH"),
            allotments={"FOOD": 30000, "CASH": 20000},
            item_entries=[
                f.item_entry(),
                f.item_entry(upc=f.DEFAULTS["NON_FOOD_UPC"], food_eligible=False),
            ])
        txn = fx.place_purchase(
            api, ctx.retailer["id"], ctx.card["id"],
            items=[f.purchase_item(unit_price_cents=300),
                   f.purchase_item(upc=f.DEFAULTS["NON_FOOD_UPC"],
                                   unit_price_cents=200)])
        assert txn["food_charge_cents"] == 300 and txn["cash_charge_cents"] == 200

        fx.void_authorization(api, txn["id"], ctx.retailer["id"])
        food = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(food, ledger_balance_cents=30000,
                                spendable_balance_cents=30000)
        A.assert_purse_balances(cash, ledger_balance_cents=20000,
                                spendable_balance_cents=20000)
        food_voids = fx.list_ledger(api, food["id"], entry_type="VOID_CREDIT")
        cash_voids = fx.list_ledger(api, cash["id"], entry_type="VOID_CREDIT")
        assert [e["amount_cents"] for e in food_voids] == [300]
        assert [e["amount_cents"] for e in cash_voids] == [200]

    def test_void_reversal_visible_on_immediate_reread(self, api):
        """PRD §3.7: "A successful void flips the transaction from `AUTHORIZED`
        to `VOIDED`, stamps `voided_at`, and posts a `VOID_CREDIT` of the exact
        debited amount to each purse the authorization debited, restoring each
        purse's balance exactly."
        PRD §2.7: "Every purse exposes two computed balances, both derived from
        its ledger at read time."

        Design: Corner/consistency_model/void_reversal_visible_on_immediate_reread
        """
        ctx = fx.setup_pos_ready(api)
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 800}])[0]
        resp = api.void_authorization(
            txn["id"], make_retailer_system_headers(ctx.retailer["id"]))
        data = validate_success(resp, 200)
        assert data["txn_status"] == "VOIDED"
        # The very next reads already reflect the compensation.
        purse = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        A.assert_purse_balances(purse, spendable_balance_cents=30000)
        void_entries = fx.list_ledger(api, ctx.purses["FOOD"]["id"],
                                      entry_type="VOID_CREDIT")
        assert len(void_entries) == 1
        assert void_entries[0]["amount_cents"] == 800
