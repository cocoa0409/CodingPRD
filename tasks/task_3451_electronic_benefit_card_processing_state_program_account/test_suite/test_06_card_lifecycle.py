"""The card lifecycle: mailing delay, activation, the PIN lock/unlock cycle,
and the replacement fee waterfall (free allowance, CASH-then-FOOD priority,
waiver)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_cardholder_headers,
    make_retailer_system_headers,
    validate_error,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


def _bad_pin_purchase(api, ctx, pin="9999", unit_price_cents=100):
    """One PURCHASE authorization attempt with a wrong PIN (error expected)."""
    retailer_id = ctx.retailer["id"]
    return api.create_authorization(
        retailer_id,
        f.purchase_payload(ctx.card["id"], pin=pin,
                           items=[f.purchase_item(unit_price_cents=unit_price_cents)]),
        make_retailer_system_headers(retailer_id),
    )


class TestCardMailingAndActivation:
    def test_activate_card_before_mailing_rejected(self, api):
        """PRD §3.6: "Activation stores the supplied secret in `pin_secret`
        (masked as `****` in every response), resets `pin_fail_count` to zero,
        and stamps `activated_at`."
        PRD §3.6: "a card still in `ISSUED`, where the mail delay has not yet
        elapsed, is rejected with `ERR_CARD_NOT_MAILED`."

        Design: Corner/state_machines/activate_card_before_mailing_rejected
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        card = fx.issue_card(api, ctx.case["id"])  # ISSUED; clock not advanced
        resp = api.activate_card(card["id"], f.activate_card_payload("1234"),
                                 make_cardholder_headers(ctx.case["id"]))
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_MAILED)
        assert fx.get_card(api, card["id"])["card_status"] == "ISSUED"


class TestPinLockCycle:
    def test_pin_lock_and_reset_cycle(self, api):
        """PRD §3.6: "A mismatch increments `pin_fail_count` by 1 and is
        rejected with `ERR_PIN_MISMATCH`; when the count reaches the contract's
        `pin_max_failures` (3 by default), the card flips from `ACTIVE` to
        `PIN_LOCKED`. A `PIN_LOCKED` card short-circuits any later authorization
        with `ERR_PIN_LOCKED` before the PIN is even compared."
        PRD §3.6: "The reset stores the new secret, zeroes `pin_fail_count`, and
        returns a locked card to `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/card_pin_lock_cycle_unlock_via_reset
        """
        ctx = fx.setup_pos_ready(api)  # active card, pin 1234
        card_id = ctx.card["id"]

        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        mid = fx.get_card(api, card_id)
        assert mid["card_status"] == "ACTIVE" and mid["pin_fail_count"] == 2, (
            f"boundary not yet reached at 2 mismatches: {mid['card_status']}/{mid['pin_fail_count']}"
        )

        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        locked = fx.get_card(api, card_id)
        assert locked["card_status"] == "PIN_LOCKED"

        # The state short-circuit beats PIN comparison: even the CORRECT pin
        # is rejected with ERR_PIN_LOCKED.
        retailer_id = ctx.retailer["id"]
        resp = api.create_authorization(
            retailer_id,
            f.purchase_payload(card_id, pin="1234",
                               items=[f.purchase_item(unit_price_cents=100)]),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_PIN_LOCKED)

        reset = fx.reset_pin_as_csr(api, card_id, new_pin="4321")
        assert reset["card_status"] == "ACTIVE"
        assert reset["pin_fail_count"] == 0
        txn = fx.place_purchase(api, retailer_id, card_id,
                                items=[f.purchase_item(unit_price_cents=100)],
                                pin="4321")
        assert txn["total_cents"] == 100

    def test_successful_pin_verification_resets_mismatch_counter(self, api):
        """PRD §3.6: "A mismatch increments `pin_fail_count` by 1 and is
        rejected with `ERR_PIN_MISMATCH`; when the count reaches the contract's
        `pin_max_failures` (3 by default), the card flips from `ACTIVE` to
        `PIN_LOCKED`."
        PRD §3.6: "The counter tracks consecutive mismatches, so a successful
        verification resets it to zero."

        Design: Difficulty/non_linear_state_machine/card_pin_lock_cycle_unlock_via_reset
        """
        ctx = fx.setup_pos_ready(api)
        card_id = ctx.card["id"]
        retailer_id = ctx.retailer["id"]

        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        # A successful verification between mismatches resets the counter.
        txn = fx.place_purchase(api, retailer_id, card_id,
                                items=[f.purchase_item(unit_price_cents=100)])
        assert txn["total_cents"] == 100
        assert fx.get_card(api, card_id)["pin_fail_count"] == 0

        # Two fresh mismatches must NOT lock the card (would be 4 without reset).
        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        validate_error(_bad_pin_purchase(api, ctx), ApiErrorId.ERR_PIN_MISMATCH)
        card = fx.get_card(api, card_id)
        assert card["card_status"] == "ACTIVE"
        assert card["pin_fail_count"] == 2


class TestReplacementFees:
    def test_replace_already_replaced_card_rejected(self, api):
        """PRD §3.6: "Requesting a PIN reset — or a replacement — for a card in
        `ISSUED`, `MAILED`, `REPLACED`, or `DEACTIVATED` is rejected with
        `ERR_REPLACEMENT_NOT_ALLOWED`."

        Design: Corner/state_machines/replace_already_replaced_card_rejected
        """
        ctx = fx.setup_pos_ready(api)
        fx.replace_card(api, ctx.card["id"], ctx.case["id"])  # card1 -> REPLACED
        resp = api.replace_card(ctx.card["id"], make_cardholder_headers(ctx.case["id"]))
        validate_error(resp, ApiErrorId.ERR_REPLACEMENT_NOT_ALLOWED)

    def test_first_replacement_uses_free_allowance(self, api):
        """PRD §3.6: "1. Free allowance first. If the case's
        `replacements_in_window` is below the contract's
        `free_replacements_per_365d` (one free replacement per trailing 365 days
        by default), the fee is zero: the new card's `fee_charged_cents` records
        0 and `fee_waived` is false. Evaluation stops."
        PRD §3.3: "Every case exposes a computed `replacements_in_window`: the
        count of the case's cards whose `replacement_of_card_id` is not null and
        whose `created_at` falls within the trailing 365 days before the current
        clock — the input to the replacement-fee waterfall of Section 3.6."

        Design: Corner/cross_cutting_layers/first_replacement_uses_free_allowance
        """
        ctx = fx.setup_pos_ready(api)
        card2 = fx.replace_card(api, ctx.card["id"], ctx.case["id"])
        assert card2["fee_charged_cents"] == 0
        assert card2["fee_waived"] is False, (
            "the free allowance is not a waiver: fee_waived must be false"
        )
        case = fx.get_case(api, ctx.case["id"])
        assert case["replacements_in_window"] == 1

    def test_second_replacement_debits_cash_purse_before_food(self, api):
        """PRD §3.6: "2. Program-priority debit. For each program in the fixed
        priority order `CASH` first, then `FOOD`: if the case holds a purse of
        that program that is not `CLOSED`, the candidate fee is the program's
        `replacement_fee_cents` override when set, otherwise the contract's
        `default_replacement_fee_cents` (250 cents by default). If that purse's
        `spendable_balance_cents` covers the full fee, a `FEE_DEBIT` of the fee
        posts to the purse with `reference_id` set to the new card's id, the new
        card's `fee_charged_cents` records the fee, `fee_waived` is false, and
        evaluation stops."

        Design: Difficulty/combinatorial_formula/replacement_fee_purse_priority_and_waiver_order
        """
        ctx = fx.setup_pos_ready(api, program_types=("FOOD", "CASH"),
                                 allotments={"FOOD": 30000, "CASH": 1000})
        # Replacement #1 consumes the single free allowance.
        card2 = fx.replace_card(api, ctx.card["id"], ctx.case["id"])
        assert card2["fee_charged_cents"] == 0
        assert card2["fee_waived"] is False
        fx.set_clock(api, "2026-09-03T12:00:00Z")  # card2 mailed (24h elapsed)
        fx.activate_card(api, card2["id"], ctx.case["id"])

        # Replacement #2: CASH purse (1000 spendable >= 250 fee) absorbs it even
        # though the FOOD purse holds 30000.
        card3 = fx.replace_card(api, card2["id"], ctx.case["id"])
        assert card3["fee_charged_cents"] == 250
        assert card3["fee_waived"] is False
        cash = fx.get_purse(api, ctx.purses["CASH"]["id"])
        A.assert_purse_balances(cash, spendable_balance_cents=750)
        food = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        A.assert_purse_balances(food, spendable_balance_cents=30000)
        fee_entries = fx.list_ledger(api, cash["id"], entry_type="FEE_DEBIT")
        assert len(fee_entries) == 1
        assert fee_entries[0]["amount_cents"] == 250
        assert fee_entries[0]["reference_id"] == card3["id"]

    def test_replacement_fee_waived_when_no_purse_can_absorb(self, api):
        """PRD §3.6: "3. Waiver last. If no purse absorbed the fee, the fee is
        waived: the new card's `fee_charged_cents` is 0 and `fee_waived` is
        true."
        PRD §3.6: "there are no partial debits: a purse either absorbs the full
        fee or evaluation moves on."

        Design: Difficulty/combinatorial_formula/replacement_fee_purse_priority_and_waiver_order
        """
        ctx = fx.setup_pos_ready(api, allotments={})  # FOOD purse at 0 spendable
        card2 = fx.replace_card(api, ctx.card["id"], ctx.case["id"])
        assert card2["fee_charged_cents"] == 0 and card2["fee_waived"] is False
        fx.set_clock(api, "2026-09-03T12:00:00Z")
        fx.activate_card(api, card2["id"], ctx.case["id"])
        # Free allowance consumed; the only purse (FOOD, 0 spendable) cannot
        # absorb 250 -> full waiver.
        card3 = fx.replace_card(api, card2["id"], ctx.case["id"])
        assert card3["fee_charged_cents"] == 0
        assert card3["fee_waived"] is True
        food = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        A.assert_purse_balances(food, ledger_balance_cents=0,
                                spendable_balance_cents=0)
        assert fx.list_ledger(api, food["id"], entry_type="FEE_DEBIT") == []
