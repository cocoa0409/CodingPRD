"""Case status lifecycle (suspension, closure, terminal lockdown, OCC), the
expungement/dormancy/card cascade, disaster expiry with FIFO attribution, and
the dormant-case reactivation path."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    instants_equal,
    make_cardholder_headers,
    make_retailer_system_headers,
    validate_error,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestCaseStatusGates:
    def test_suspended_case_blocks_purchase(self, api):
        """PRD §3.3: "A `StateAdmin` may suspend an `OPEN` case (`OPEN` to
        `SUSPENDED`) and reinstate it (`SUSPENDED` to `OPEN`) without
        preconditions. Suspension is an administrative hold: purses of a
        `SUSPENDED` case are skipped by allotment runs, and the case-open gate
        of Section 2.8 blocks authorizations, claim filing, card issuance, card
        activation, and card replacement for the case with `ERR_CASE_NOT_OPEN`
        while the hold lasts."

        Design: Corner/state_machines/suspended_case_blocks_purchase
        """
        ctx = fx.setup_pos_ready(api)
        fx.set_case_status(api, ctx.case["id"], "SUSPENDED")
        resp = api.create_authorization(
            ctx.retailer["id"],
            f.purchase_payload(ctx.card["id"],
                               items=[f.purchase_item(unit_price_cents=100)]),
            make_retailer_system_headers(ctx.retailer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CASE_NOT_OPEN)
        fx.set_case_status(api, ctx.case["id"], "OPEN")
        txn = fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])[0]
        assert txn["total_cents"] == 100

    def test_closed_case_is_terminal_for_status_changes(self, api):
        """PRD §3.10: "`CLOSED` is terminal for the case: any further status
        change is rejected with `ERR_INVALID_STATE`, as is any transition a
        resource's current state does not allow anywhere in the system."

        Design: Corner/state_machines/closed_case_is_terminal_for_status_changes
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)  # no allotment: all purse balances are 0
        closed = fx.set_case_status(api, ctx.case["id"], "CLOSED")
        assert closed["account_status"] == "CLOSED"
        version = fx.get_case(api, ctx.case["id"])["version"]
        # Even with the current OCC version, the terminal state rejects.
        resp = api.set_case_status(
            ctx.case["id"],
            f.case_status_payload("SUSPENDED",
                                  expected_case_account_version=version),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_case_close_with_nonzero_balance_rejected(self, api):
        """PRD §3.10: "second, every purse of the case must have a
        `ledger_balance_cents` of zero, else `ERR_CASE_BALANCE_NONZERO` — the
        ledger view governs here, so scheduled future money blocks closure even
        though it was never spendable."

        Design: Corner/validations/case_close_with_nonzero_balance_rejected
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        fx.fund_case(api, ctx)  # 30000 posting still SCHEDULED at this clock
        version = fx.get_case(api, ctx.case["id"])["version"]
        resp = api.set_case_status(
            ctx.case["id"],
            f.case_status_payload("CLOSED", expected_case_account_version=version),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_BALANCE_NONZERO)

    def test_stale_case_version_rejected_on_status_change(self, api):
        """PRD §2.10: "If the supplied value no longer matches the case's
        current `version` — because another writer has advanced the case's
        version since the client last read it, for example through a legal
        transition such as `SUSPENDED` to `OPEN` — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from acting on a
        stale view of the account."

        Design: Corner/cross_cutting_layers/stale_case_version_rejected_on_status_change
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        v1 = fx.get_case(api, ctx.case["id"])["version"]
        suspended = fx.set_case_status(api, ctx.case["id"], "SUSPENDED")
        assert suspended["account_status"] == "SUSPENDED"
        # The suspend advanced the version; replaying v1 is stale.
        resp = api.set_case_status(
            ctx.case["id"],
            f.case_status_payload("OPEN", expected_case_account_version=v1),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert fx.get_case(api, ctx.case["id"])["account_status"] == "SUSPENDED", (
            "the rejected call must change nothing"
        )


class TestExpungementCascade:
    def test_expungement_dormancy_card_deactivation_chain(self, api):
        """PRD §3.5: "The eligibility instant is the purse's `last_activity_at`
        plus the inactivity window; the notice instant is the eligibility
        instant minus the lead. When the current clock is at or after the notice
        instant but still before the eligibility instant, and no notice has been
        recorded, the sweep records the notice by stamping
        `expungement_notice_sent_at`. When the current clock reaches or passes
        the eligibility instant — the boundary is inclusive — the sweep expunges
        the purse: every `AVAILABLE` posting of that purse flips to `EXPUNGED`
        together, a single `EXPUNGE_DEBIT` of the purse's full
        `ledger_balance_cents` zeroes the ledger, and the notice flag resets to
        null."
        PRD §3.5: "When the expungement sweep has just expunged a case's purses
        and, afterwards, every purse of the case has a `ledger_balance_cents` of
        zero and no posting of the case remains in `SCHEDULED` or `AVAILABLE`,
        an `OPEN` case flips to `DORMANT`; in the same cascade every card of the
        case in `ISSUED`, `MAILED`, `ACTIVE`, or `PIN_LOCKED` flips to
        `DEACTIVATED`."

        Design: Difficulty/transitive_cascade/expungement_dormancy_card_deactivation_chain
        """
        ctx = fx.setup_pos_ready(api)  # FOOD 30000; card ACTIVE at 09-02T12:00
        fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])
        # last_activity 2026-09-02T12:00Z; eligibility = +90d = 2026-12-01T12:00Z;
        # notice = eligibility - 30d = 2026-11-01T12:00Z.
        purse_id = ctx.purses["FOOD"]["id"]

        fx.set_clock(api, "2026-11-01T12:00:00Z")
        purse = fx.get_purse(api, purse_id)
        assert instants_equal(purse["expungement_notice_sent_at"],
                              "2026-11-01T12:00:00Z"), (
            f"notice must be stamped at the sweep clock, got {purse['expungement_notice_sent_at']}"
        )
        # A notice is not an expungement: the balance is untouched.
        A.assert_purse_balances(purse, ledger_balance_cents=29900)

        fx.set_clock(api, "2026-12-01T11:59:59Z")
        assert fx.get_case(api, ctx.case["id"])["account_status"] == "OPEN"

        fx.set_clock(api, "2026-12-01T12:00:00Z")  # inclusive eligibility edge
        purse = fx.get_purse(api, purse_id)
        A.assert_purse_balances(purse, ledger_balance_cents=0)
        assert purse["expungement_notice_sent_at"] is None
        posting = fx.list_postings(api, purse_id)[0]
        assert posting["posting_status"] == "EXPUNGED"
        # Link 2: all purses zero and no live postings -> case DORMANT.
        assert fx.get_case(api, ctx.case["id"])["account_status"] == "DORMANT"
        # Link 3: dormancy deactivates the case's cards.
        assert fx.get_card(api, ctx.card["id"])["card_status"] == "DEACTIVATED"

    def test_new_activity_restarts_inactivity_clock_and_clears_notice(self, api):
        """PRD §3.5: "Because every new ledger entry refreshes
        `last_activity_at` and clears the notice, any activity restarts the
        inactivity clock from that entry's timestamp."
        PRD §2.5: "Any new ledger entry on a purse sets that purse's
        `last_activity_at` to the entry's `created_at` and clears the purse's
        `expungement_notice_sent_at` back to null."

        Design: Difficulty/transitive_cascade/expungement_dormancy_card_deactivation_chain
        """
        ctx = fx.setup_pos_ready(api)
        fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])  # 09-02T12:00
        purse_id = ctx.purses["FOOD"]["id"]

        fx.set_clock(api, "2026-11-15T12:00:00Z")  # notice window already open
        purse = fx.get_purse(api, purse_id)
        assert purse["expungement_notice_sent_at"] is not None

        # New ledger activity restarts the inactivity clock and clears the flag.
        fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])
        purse = fx.get_purse(api, purse_id)
        assert purse["expungement_notice_sent_at"] is None
        assert instants_equal(purse["last_activity_at"], "2026-11-15T12:00:00Z")
        A.assert_purse_balances(purse, ledger_balance_cents=29800)

        # The OLD eligibility instant (2026-12-01T12:00Z) now passes harmlessly.
        fx.set_clock(api, "2026-12-01T12:00:00Z")
        purse = fx.get_purse(api, purse_id)
        A.assert_purse_balances(purse, ledger_balance_cents=29800)
        assert fx.list_postings(api, purse_id)[0]["posting_status"] == "AVAILABLE"
        assert fx.get_case(api, ctx.case["id"])["account_status"] == "OPEN"


class TestDisasterExpiry:
    def test_disaster_expiry_fifo_unspent_portion(self, api):
        """PRD §3.5: "`DISASTER` purses are exempt from expungement entirely.
        Instead, the disaster-expiry sweep — step 2 of the pipeline, running
        before expungement — flips an `AVAILABLE` posting of a `DISASTER` purse
        to `EXPIRED` once the current clock reaches or passes the posting's
        `available_at` plus the effective disaster expiry window: the program's
        `disaster_expiry_days` override when set, otherwise the contract's
        `default_disaster_expiry_days` (30 days by default), again with an
        inclusive boundary. An `EXPIRY_DEBIT` of the posting's unspent portion
        posts to the disaster purse at that moment."
        PRD §3.5: "The unspent portion is computed by first-in-first-out
        allocation. The purse's consuming debits — the purchase, withdrawal, and
        fee debits — are replayed in `created_at` ascending order against the
        purse's postings that ever reached `AVAILABLE`, ordered by
        `available_at` ascending with `created_at` ascending as the tie-break
        (never by id), and each debit is allocated to the oldest posting that
        still has remaining unspent balance before any amount flows to a newer
        posting."

        Design: Corner/calculations/disaster_expiry_fifo_unspent_portion
        """
        ctx = fx.setup_active_contract(api, program_types=("FOOD", "DISASTER"))
        fx.add_retailer(api, ctx)
        fx.set_clock(api, "2026-09-05T00:00:00Z")
        fx.add_case(api, ctx)  # food + disaster purses; created inside 2026-09
        # Posting A: prorated to round_half_up(30000 * 26 / 30) = 26000,
        # available 2026-09-05T06:00Z (creation-date clamp).
        fx.run_allotment(api, ctx.contract["id"], ctx.programs["DISASTER"]["id"],
                         benefit_month="2026-09", amount_cents=30000)
        # Posting B: full 4000, available 2026-10-01T06:00Z (bucket 0).
        fx.run_allotment(api, ctx.contract["id"], ctx.programs["DISASTER"]["id"],
                         benefit_month="2026-10", amount_cents=4000)
        fx.add_active_card(api, ctx, activate_at="2026-09-06T12:00:00Z")
        fx.set_clock(api, "2026-09-10T12:00:00Z")
        txn = fx.place_purchase(api, ctx.retailer["id"], ctx.card["id"],
                                items=[f.purchase_item(unit_price_cents=1500)])
        # The disaster purse absorbs the food-eligible charge first.
        assert txn["disaster_charge_cents"] == 1500

        # A expires at 2026-09-05T06:00Z + 30 days = 2026-10-05T06:00Z (inclusive).
        fx.set_clock(api, "2026-10-05T06:00:00Z")
        purse_id = ctx.purses["DISASTER"]["id"]
        purse = fx.get_purse(api, purse_id)
        # FIFO: the 1500 debit consumed the OLDER posting A first, so A's
        # unspent portion is 26000 - 1500 = 24500 and only B's 4000 remains.
        A.assert_purse_balances(purse, ledger_balance_cents=4000,
                                spendable_balance_cents=4000)
        postings = fx.list_postings(api, purse_id)  # ordered available_at ASC
        assert postings[0]["posting_status"] == "EXPIRED"
        assert postings[1]["posting_status"] == "AVAILABLE"
        expiry = fx.list_ledger(api, purse_id, entry_type="EXPIRY_DEBIT")
        assert [e["amount_cents"] for e in expiry] == [24500]


class TestDormantReactivation:
    def test_reactivated_dormant_case_cards_stay_deactivated(self, api):
        """PRD §3.4: "If the owning case is `DORMANT`, the availability bubbles
        up: the case flips from `DORMANT` back to `OPEN`, though its cards
        remain `DEACTIVATED`, so spending power returns only through a
        replacement card under the fee rules of Section 3.6."
        PRD §3.7: "the card must be able to spend — a card in `ISSUED`,
        `MAILED`, `REPLACED`, or `DEACTIVATED` is rejected with
        `ERR_CARD_NOT_ACTIVE`"

        Design: Corner/state_machines/reactivated_dormant_case_cards_stay_deactivated
        """
        ctx = fx.setup_pos_ready(api)  # FOOD 30000; card ACTIVE at 09-02T12:00
        fx.place_purchases(api, ctx, [{"unit_price_cents": 100}])
        # Expunge everything: last activity 09-02T12:00 + 90d = 12-01T12:00Z.
        fx.set_clock(api, "2026-12-01T12:00:00Z")
        assert fx.get_case(api, ctx.case["id"])["account_status"] == "DORMANT"
        assert fx.get_card(api, ctx.card["id"])["card_status"] == "DEACTIVATED"

        # A December run (the current month; DORMANT cases are eligible) posts a
        # benefit whose available_at (2026-12-01T06:00Z) is already past.
        fx.run_allotment(api, ctx.contract["id"], ctx.programs["FOOD"]["id"],
                         benefit_month="2026-12", amount_cents=30000)
        fx.set_clock(api, "2026-12-01T12:00:01Z")  # the sweep flips it AVAILABLE
        case = fx.get_case(api, ctx.case["id"])
        assert case["account_status"] == "OPEN", (
            f"availability must bubble DORMANT back to OPEN, got {case['account_status']}"
        )
        purse = fx.get_purse(api, ctx.purses["FOOD"]["id"])
        A.assert_purse_balances(purse, spendable_balance_cents=30000)
        # But the deactivated card is never resurrected.
        resp = api.create_authorization(
            ctx.retailer["id"],
            f.purchase_payload(ctx.card["id"],
                               items=[f.purchase_item(unit_price_cents=100)]),
            make_retailer_system_headers(ctx.retailer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE)
