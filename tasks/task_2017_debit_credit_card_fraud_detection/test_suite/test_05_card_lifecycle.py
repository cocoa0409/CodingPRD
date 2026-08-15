"""Card lifecycle: block/unblock cycles, parallel fraud_flag dimension, terminal
lockdown, replacement cascade, compromised unblock gating."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_active_ruleset,
    parse_iso8601,
    post_txn,
    set_clock,
    get_success_data,
    create_and_confirm_event,
    get_decision_for_card,
    make_analyst_headers,
    make_manager_headers,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def _account_card(account_number, pan_token, product_type="CREDIT", network="VISA"):
    acct = create_account(account_number)
    card = create_card(acct["id"], pan_token, product_type=product_type, network=network)
    return acct, card


def test_card_computed_status_input_ignored(api):
    """PRD §3.1: "The `card_status` dimension starts at `ACTIVE`".

    Design: Corner/entities/card_computed_status_input_ignored
    """
    acct = create_account("ACCT-EN3", cardholder_name="Ent Three")
    payload = {
        "account_id": acct["id"],
        "pan_token": "PT-EN3",
        "product_type": "CREDIT",
        "network": "VISA",
        "card_status": "HARD_CLOSED",
    }
    created = validate_success(api.create_card(payload, MANAGER), expected_status=201)
    assert created["card_status"] == "ACTIVE", (
        f"client-supplied card_status must be ignored; got {created['card_status']}"
    )


def test_card_create_invalid_enum_rejected(api):
    """PRD §2.6: "request shape — required fields, enum membership, `amount_cents`
    at least 1 where required, well-formed dates" (priority 6); PRD §3.1:
    "`product_type` (`DEBIT` or `CREDIT`)".

    Design: Corner/entities/card_create_invalid_enum_rejected
    """
    acct = create_account("ACCT-EN4", cardholder_name="Ent Four")
    payload = {
        "account_id": acct["id"],
        "pan_token": "PT-EN4",
        "product_type": "AMEX",
        "network": "VISA",
    }
    resp = api.create_card(payload, MANAGER)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_card_unblock_from_active_rejected(api):
    """PRD §3.1: card_status "may move to `SOFT_BLOCKED` ... from `SOFT_BLOCKED`
    back to `ACTIVE` via an unblock" — unblock is defined only from
    `SOFT_BLOCKED`, so an `ACTIVE` card fails the state-machine precondition
    (§2.6: "state-machine preconditions (priority 7" -> `ERR_INVALID_STATE`).

    Design: Corner/state_machines/card_unblock_from_active_rejected
    """
    _acct, card = _account_card("ACCT-SM1", "PT-SM1")
    resp = api.unblock_card(card["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_card(card["id"], MANAGER))
    assert current["card_status"] == "ACTIVE"


def test_hard_closed_card_is_terminal(api):
    """PRD §3.1: card_status may move "from either `ACTIVE` or `SOFT_BLOCKED` to the
    terminal states `HARD_CLOSED` ... or `REPLACED`"; no transition leaves
    `HARD_CLOSED`, so further block/unblock attempts fail with `ERR_INVALID_STATE`
    (§2.6 priority 7).

    Design: Corner/state_machines/hard_closed_card_is_terminal
    """
    _acct, card = _account_card("ACCT-SM2", "PT-SM2", product_type="DEBIT", network="MASTERCARD")
    get_success_data(
        api.block_card(card["id"], {"block_type": "HARD", "reason": "CONFIRMED_FRAUD"}, MANAGER)
    )
    r1 = api.unblock_card(card["id"], MANAGER)
    validate_error(r1, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    r2 = api.block_card(card["id"], {"block_type": "SOFT", "reason": "ANALYST_REVIEW"}, MANAGER)
    validate_error(r2, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_card(card["id"], MANAGER))
    assert current["card_status"] == "HARD_CLOSED"


class TestCardBlockUnblockCycleWithParallelFlag:
    def _setup_cycle(self, api):
        """One full block/unblock cycle, then a second SOFT block; then a compromise
        confirm flips fraud_flag to COMPROMISED while card_status holds."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-NL1", cardholder_name="En Ell")
        card = create_card(acct["id"], "PT-NL1", product_type="CREDIT", network="VISA")
        create_active_ruleset()
        set_clock("2026-08-02T00:00:00Z")
        post_txn(card["id"], 40000, "M-C1", channel="CNP", origin_country="US")
        get_success_data(api.block_card(card["id"], {"block_type": "SOFT", "reason": "ANALYST_REVIEW"}, ANALYST))
        get_success_data(api.unblock_card(card["id"], ANALYST))
        get_success_data(api.block_card(card["id"], {"block_type": "SOFT", "reason": "CUSTOMER_REQUEST"}, ANALYST))
        return acct, card

    def test_confirm_moves_flag_but_not_status(self, api):
        """PRD §3.1: "A card carries two independent state dimensions on the same
        row." and "confirming a compromised-card event flags matched cards
        `COMPROMISED`".

        Design: Difficulty/non_linear_state_machine/card_block_unblock_cycle_with_parallel_flag
        """
        _acct, card = self._setup_cycle(api)
        create_and_confirm_event(
            "M-C1", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", "CAMS-NL1",
        )
        fetched = validate_success(api.get_card(card["id"], MANAGER))
        assert fetched["card_status"] == "SOFT_BLOCKED", (
            f"confirm must not move card_status, got {fetched['card_status']}"
        )
        assert fetched["fraud_flag"] == "COMPROMISED"
        assert fetched["block_reason"] == "CUSTOMER_REQUEST"

    def test_block_unblock_cycle_restores_active_and_clears_reason(self, api):
        """PRD §3.1: "`block_reason` ... is null whenever `card_status` is `ACTIVE`
        — an unblock clears it to null."

        Design: Difficulty/non_linear_state_machine/card_block_unblock_cycle_with_parallel_flag
        """
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-NL1", cardholder_name="En Ell")
        card = create_card(acct["id"], "PT-NL1", product_type="CREDIT", network="VISA")
        blocked = get_success_data(
            api.block_card(card["id"], {"block_type": "SOFT", "reason": "ANALYST_REVIEW"}, ANALYST)
        )
        assert blocked["card_status"] == "SOFT_BLOCKED"
        assert blocked["block_reason"] == "ANALYST_REVIEW"
        unblocked = get_success_data(api.unblock_card(card["id"], ANALYST))
        assert unblocked["card_status"] == "ACTIVE"
        assert unblocked["block_reason"] is None


class TestUnblockCompromisedRequiresDeclinedDecision:
    def _setup_compromised_soft_blocked(self, api):
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account("ACCT-CE2", cardholder_name="Cross Two")
        card = create_card(acct["id"], "PT-CE2", product_type="CREDIT", network="VISA")
        create_active_ruleset()
        post_txn(card["id"], 40000, "M-CE2", channel="CNP", origin_country="US")
        create_and_confirm_event("M-CE2", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", "ADC-CE2", network_source="ADC")
        decision = get_decision_for_card(card["id"])
        get_success_data(
            api.block_card(card["id"], {"block_type": "SOFT", "reason": "COMPROMISE_EVENT"}, ANALYST)
        )
        return acct, card, decision

    def test_unblock_rejected_while_decision_pending(self, api):
        """PRD §3.1: "Unblocking a card is gated by the compromise rule: if the
        card's `fraud_flag` is `COMPROMISED` and no `ReissueDecision` for that card
        has been `DECLINED`, the unblock is rejected with `ERR_CARD_COMPROMISED`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/unblock_compromised_requires_declined_decision
        """
        _acct, card, decision = self._setup_compromised_soft_blocked(api)
        assert decision["decision"] == "PENDING"
        resp = api.unblock_card(card["id"], ANALYST)
        validate_error(resp, ApiErrorId.ERR_CARD_COMPROMISED, expected_status=409)

    def test_unblock_succeeds_after_decline_downgrades_flag(self, api):
        """PRD §3.1: "declining a reissue decision downgrades the exposed card from
        `COMPROMISED` to `WATCH`, which is the risk-acceptance path that makes the
        card eligible for unblocking again."

        Design: Difficulty/cross_entity_state_dependency/unblock_compromised_requires_declined_decision
        """
        _acct, card, decision = self._setup_compromised_soft_blocked(api)
        # exposure 40000 <= 50000 so an analyst may decline
        decided = validate_success(
            api.decide_reissue_decision(
                decision["id"],
                {"decision": "DECLINE", "rationale": "cardholder verified all transactions; risk accepted"},
                make_analyst_headers("analyst-1"),
            )
        )
        assert decided["decision"] == "DECLINED"
        flagged = validate_success(api.get_card(card["id"], MANAGER))
        assert flagged["fraud_flag"] == "WATCH"
        unblocked = validate_success(api.unblock_card(card["id"], ANALYST))
        assert unblocked["card_status"] == "ACTIVE"
        assert unblocked["block_reason"] is None


class TestStateBeatsSafetyOnUnblock:
    def test_state_error_reported_not_safety(self, api):
        """PRD §2.6: "state-machine preconditions (priority 7 ...)" precede "safety
        and segregation-of-duties rules (priority 8, including
        `ERR_CARD_COMPROMISED` ...)"; "the failure that is reported is the one with
        the lowest priority number; later checks are masked by earlier ones."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_unblock
        """
        card = self._setup_hard_closed_compromised(api)
        resp = api.unblock_card(card["id"], MANAGER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

    def test_rejected_unblock_leaves_card_unchanged(self, api):
        """PRD §2.6: "later checks are masked by earlier ones" — the request fails
        at the state check, so neither the card_status nor the parallel
        `fraud_flag` dimension may move; §3.1: "A card carries two independent
        state dimensions on the same row."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_safety_on_unblock
        """
        card = self._setup_hard_closed_compromised(api)
        api.unblock_card(card["id"], MANAGER)
        current = validate_success(api.get_card(card["id"], MANAGER))
        assert current["card_status"] == "HARD_CLOSED"
        assert current["fraud_flag"] == "COMPROMISED"

    def _setup_hard_closed_compromised(self, api):
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account("ACCT-PP2", cardholder_name="Pee Two")
        card = create_card(acct["id"], "PT-PP2", product_type="DEBIT", network="MASTERCARD")
        create_active_ruleset()
        post_txn(card["id"], 40000, "M-PP2", channel="CNP", origin_country="US")
        create_and_confirm_event("M-PP2", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", "ADC-PP2", network_source="ADC")
        get_success_data(
            api.block_card(card["id"], {"block_type": "HARD", "reason": "COMPROMISE_EVENT"}, MANAGER)
        )
        return card


class TestReplacementCascade:
    def _setup_confirmed_event(self, api, account_number, pan_token, product_type, network, merchant, event_ref):
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account(account_number)
        card = create_card(acct["id"], pan_token, product_type=product_type, network=network)
        create_active_ruleset()
        post_txn(card["id"], 40000, merchant, channel="CNP", origin_country="US")
        create_and_confirm_event(merchant, "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", event_ref)
        decision = get_decision_for_card(card["id"])
        return acct, card, decision

    def test_replacement_chain_reverse_lookup(self, api):
        """PRD §3.1: "A card carries a self-referential `replaces_card_id`, which is
        null on original cards and points to the replaced card on a replacement
        minted by a reissue decision"; PRD §2.7: "cards may be filtered by
        `account_id` or `replaces_card_id`".

        Design: Corner/entities/replacement_chain_reverse_lookup
        """
        _acct, card, decision = self._setup_confirmed_event(
            api, "ACCT-EN5", "PT-EN5", "DEBIT", "MASTERCARD", "M-EN5", "CAMS-EN5"
        )
        decided = validate_success(
            api.decide_reissue_decision(decision["id"], {"decision": "APPROVE"}, MANAGER)
        )
        replacement_id = decided["replacement_card_id"]
        assert replacement_id
        cards, meta = validate_paginated(
            api.list_cards(MANAGER, params={"replaces_card_id": card["id"]})
        )
        assert meta["total_count"] == 1
        assert cards[0]["id"] == replacement_id
        replacement = validate_success(api.get_card(replacement_id, MANAGER))
        assert replacement["replaces_card_id"] == card["id"]
        assert replacement["fraud_flag"] == "WATCH"

    def test_replacement_card_supersedes_and_cancels_notices(self, api):
        """PRD §3.1: "the replacement inherits the account, `product_type`, and
        `network`, receives a fresh server-minted `pan_token`, starts `ACTIVE` with
        `fraud_flag` equal to `WATCH`, and its creation cancels every `ACTIVE`
        travel notice of the replaced card."

        Design: Corner/state_machines/replacement_card_supersedes_and_cancels_notices
        """
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account("ACCT-SM10", cardholder_name="Sm Ten")
        card = create_card(acct["id"], "PT-SM10", product_type="CREDIT", network="VISA")
        notice = get_success_data(
            api.create_travel_notice(
                {
                    "card_id": card["id"],
                    "region_country": "MX",
                    "start_date": "2026-08-10",
                    "end_date": "2026-08-20",
                },
                ANALYST,
            ),
            expected_status=201,
        )
        create_active_ruleset()
        post_txn(card["id"], 40000, "M-SM10", channel="CNP", origin_country="US")
        create_and_confirm_event("M-SM10", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", "CAMS-SM10")
        decision = get_decision_for_card(card["id"])
        decided = validate_success(
            api.decide_reissue_decision(decision["id"], {"decision": "APPROVE"}, make_analyst_headers("analyst-1"))
        )
        replacement_id = decided["replacement_card_id"]

        old_card = validate_success(api.get_card(card["id"], MANAGER))
        assert old_card["card_status"] == "REPLACED"
        replacement = validate_success(api.get_card(replacement_id, MANAGER))
        assert replacement["fraud_flag"] == "WATCH"
        assert replacement["card_status"] == "ACTIVE"
        assert replacement["product_type"] == "CREDIT"
        assert replacement["network"] == "VISA"
        assert replacement["replaces_card_id"] == card["id"]
        notice_after = validate_success(api.get_travel_notice(notice["id"], MANAGER))
        assert notice_after["notice_status"] == "CANCELLED"

    def test_event_closes_when_all_decisions_terminal(self, api):
        """PRD §3.6: "Once no `ReissueDecision` of the event remains `PENDING` —
        every one is `APPROVED`, `DECLINED`, or `AUTO_APPROVED` — the event itself
        transitions from `CONFIRMED` to `CLOSED`, checked after each decision and
        on clock advances."

        Design: Corner/state_machines/event_closes_when_all_decisions_terminal
        """
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account("ACCT-SM9", cardholder_name="Sm Nine")
        card = create_card(acct["id"], "PT-SM9", product_type="DEBIT", network="MASTERCARD")
        create_active_ruleset()
        post_txn(card["id"], 40000, "M-SM9", channel="CNP", origin_country="US")
        event = create_and_confirm_event("M-SM9", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z", "ADC-SM9", network_source="ADC")
        decision = get_decision_for_card(card["id"])

        mid = validate_success(api.get_compromised_card_event(event["id"], MANAGER))
        assert mid["event_status"] == "CONFIRMED", "one PENDING decision keeps the event open"

        validate_success(api.decide_reissue_decision(decision["id"], {"decision": "APPROVE"}, MANAGER))
        after = validate_success(api.get_compromised_card_event(event["id"], MANAGER))
        assert after["event_status"] == "CLOSED"

    def test_reissue_auto_approve_after_due_date(self, api):
        """PRD §2.5: "A reissue decision still in `PENDING` whose `due_at` (the
        parent event's `confirmed_at` plus 5 days) has been reached flips to
        `AUTO_APPROVED` and fires the same replacement-card cascade as a manual
        approval."; PRD §3.6: auto-approval "stamps `decided_by_user_id` as
        `SYSTEM`".

        Design: Corner/state_machines/reissue_auto_approve_after_due_date
        """
        set_clock("2026-08-02T00:00:00Z")
        acct = create_account("ACCT-SM8", cardholder_name="Sm Eight")
        card = create_card(acct["id"], "PT-SM8", product_type="CREDIT", network="VISA")
        create_active_ruleset()
        post_txn(card["id"], 40000, "M-SM8", channel="CNP", origin_country="US")
        event = get_success_data(
            api.create_compromised_card_event(
                {
                    "network_source": "CAMS",
                    "event_reference": "CAMS-SM8",
                    "merchant_id": "M-SM8",
                    "window_start": "2026-08-01T00:00:00Z",
                    "window_end": "2026-08-03T00:00:00Z",
                },
                MANAGER,
            ),
            expected_status=201,
        )
        set_clock("2026-08-02T12:00:00Z")
        get_success_data(api.confirm_compromised_card_event(event["id"], MANAGER))
        decision = get_decision_for_card(card["id"])
        # PRD pins the due_at *value* ("confirmed_at plus 5 days"); the
        # fractional-digit format of computed timestamps is not pinned (§2.4
        # scopes "three fractional digits" to created_at/updated_at), so compare
        # instants.
        assert parse_iso8601(decision["due_at"]) == parse_iso8601("2026-08-07T12:00:00Z"), (
            f"due_at must be confirmed_at + 5 days, got {decision['due_at']}"
        )
        set_clock("2026-08-07T12:00:00Z")
        fetched = validate_success(api.get_reissue_decision(decision["id"], MANAGER))
        assert fetched["decision"] == "AUTO_APPROVED"
        assert fetched["decided_by_user_id"] == "SYSTEM"
        assert fetched["replacement_card_id"]
        replacement = validate_success(api.get_card(fetched["replacement_card_id"], MANAGER))
        assert replacement["fraud_flag"] == "WATCH"
        assert replacement["card_status"] == "ACTIVE"
        old_card = validate_success(api.get_card(card["id"], MANAGER))
        assert old_card["card_status"] == "REPLACED"
