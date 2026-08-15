"""Fraud ring detection threshold and confirm/dismiss compensation."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_active_ruleset,
    post_txn,
    set_clock,
    get_success_data,
)

MANAGER = TEST_USERS["manager_headers"]


class TestRingDetectBelowMinimumAccounts:
    def _seed_accounts(self, api, count):
        """Create `count` accounts, each with a card holding 2 APPROVE txns at
        M-V14 inside [08-01, 08-04). The ACTIVE ruleset must exist before any
        authorization intake (§3.3: otherwise intake is ERR_NO_ACTIVE_RULESET)."""
        create_active_ruleset()
        accounts = []
        for suffix in ["A", "B", "C"][:count]:
            acct = create_account(f"ACCT-V14{suffix}", cardholder_name=f"Ring {suffix}")
            card = create_card(
                acct["id"], f"PT-V14{suffix}",
                product_type="CREDIT" if suffix != "B" else "DEBIT",
                network="VISA" if suffix != "B" else "MASTERCARD",
            )
            post_txn(card["id"], 1000, "M-V14", channel="CHIP", origin_country="US")
            post_txn(card["id"], 2000, "M-V14", channel="CHIP", origin_country="US")
            accounts.append((acct, card))
        return accounts

    def test_two_qualifying_accounts_rejected(self, api):
        """PRD §3.9: "When at least 3 accounts qualify, a `FraudRing` is created in
        `SUSPECTED` ... Fewer than 3 qualifying accounts — exactly 3 succeeds — is
        rejected with `ERR_RING_THRESHOLD_NOT_MET` (HTTP 409)."

        Design: Corner/validations/ring_detect_below_minimum_accounts
        """
        set_clock("2026-08-02T00:00:00Z")
        self._seed_accounts(api, 2)
        resp = api.detect_fraud_ring(
            {
                "signal_type": "COMMON_MERCHANT",
                "merchant_id": "M-V14",
                "window_start": "2026-08-01T00:00:00Z",
                "window_end": "2026-08-04T00:00:00Z",
            },
            MANAGER,
        )
        validate_error(resp, ApiErrorId.ERR_RING_THRESHOLD_NOT_MET, expected_status=409)

    def test_exactly_three_accounts_succeeds(self, api):
        """PRD §3.9: "When at least 3 accounts qualify, a `FraudRing` is created in
        `SUSPECTED` together with a `RingMembership` per member account recording
        the account's `evidence_txn_count`; `member_count` mirrors the membership
        count. Fewer than 3 qualifying accounts — exactly 3 succeeds — is rejected
        with `ERR_RING_THRESHOLD_NOT_MET` (HTTP 409)."

        Design: Corner/validations/ring_detect_below_minimum_accounts
        """
        set_clock("2026-08-02T00:00:00Z")
        self._seed_accounts(api, 3)
        ring = validate_success(
            api.detect_fraud_ring(
                {
                    "signal_type": "COMMON_MERCHANT",
                    "merchant_id": "M-V14",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-04T00:00:00Z",
                },
                MANAGER,
            ),
            expected_status=201,
        )
        assert ring["ring_status"] == "SUSPECTED"
        assert ring["member_count"] == 3


class TestRingConfirmDismissCompensation:
    def _setup_suspected_ring(self, api):
        """Three accounts each with 2 APPROVE txns at M-RG; ring detected."""
        set_clock("2026-08-02T00:00:00Z")
        accts_cards = []
        for i, suffix in enumerate(["RG1", "RG2", "RG3"]):
            acct = create_account(f"ACCT-{suffix}", cardholder_name=f"Ring {i + 1}")
            card = create_card(
                acct["id"], f"PT-{suffix}",
                product_type="CREDIT" if suffix != "RG2" else "DEBIT",
                network="VISA" if suffix != "RG2" else "MASTERCARD",
            )
            accts_cards.append((acct, card))
        create_active_ruleset()
        for _acct, card in accts_cards:
            post_txn(card["id"], 1000, "M-RG", channel="CHIP", origin_country="US")
            post_txn(card["id"], 2000, "M-RG", channel="CHIP", origin_country="US")
        ring = get_success_data(
            api.detect_fraud_ring(
                {
                    "signal_type": "COMMON_MERCHANT",
                    "merchant_id": "M-RG",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-04T00:00:00Z",
                },
                MANAGER,
            ),
            expected_status=201,
        )
        return accts_cards, ring

    def test_confirm_raises_watch_and_tier(self, api):
        """PRD §3.9: "Confirming a `SUSPECTED` ring moves it to `CONFIRMED` and
        cascades: every card of every member account whose `fraud_flag` is `CLEAN`
        becomes `WATCH`; every member account's `risk_tier` is recomputed";
        §3.1: tier is `MEDIUM` when "any card carries `fraud_flag` equal to
        `WATCH`".

        Design: Corner/state_machines/ring_confirm_dismiss_compensation
        """
        accts_cards, ring = self._setup_suspected_ring(api)
        validate_success(api.confirm_fraud_ring(ring["id"], MANAGER))
        a1, k1 = accts_cards[0]
        card = validate_success(api.get_card(k1["id"], MANAGER))
        assert card["fraud_flag"] == "WATCH"
        account = validate_success(api.get_account(a1["id"], MANAGER))
        assert account["risk_tier"] == "MEDIUM"
        memberships, meta = validate_paginated(
            api.list_ring_memberships(MANAGER, params={"ring_id": ring["id"]})
        )
        assert meta["total_count"] == 3
        for m in memberships:
            assert m["evidence_txn_count"] == 2

    def test_dismiss_confirmed_ring_compensates_flags(self, api):
        """PRD §3.9: "Dismissal from `CONFIRMED` compensates: the cards that this
        ring's confirmation raised to `WATCH` return to `CLEAN` (cards that are
        `COMPROMISED` remain so), and member accounts' tiers are recomputed."

        Design: Corner/state_machines/ring_confirm_dismiss_compensation
        """
        accts_cards, ring = self._setup_suspected_ring(api)
        validate_success(api.confirm_fraud_ring(ring["id"], MANAGER))
        validate_success(api.dismiss_fraud_ring(ring["id"], MANAGER))
        a1, k1 = accts_cards[0]
        card = validate_success(api.get_card(k1["id"], MANAGER))
        assert card["fraud_flag"] == "CLEAN", "dismiss must compensate the WATCH flag it raised"
        account = validate_success(api.get_account(a1["id"], MANAGER))
        assert account["risk_tier"] == "LOW", "tier must be recomputed back to LOW"
