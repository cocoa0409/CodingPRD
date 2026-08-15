"""Fraud alert queue: priority computation, claiming, expiry, reopen loop,
resolution contact requirements, cardholder respond path."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_card,
    create_active_ruleset,
    create_manual_alert,
    claim_alert,
    create_and_complete_contact,
    resolve_alert,
    parse_iso8601,
    post_txn,
    set_clock,
    get_success_data,
    make_analyst_headers,
    make_cardholder_headers,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_alert_created_in_open_with_initial_priority(api):
    """PRD §3.4: "Both sources start in `OPEN` with `assigned_to_user_id` null,
    `reopen_count` 0, and `sla_expires_at` set to creation plus 72 hours." and
    "`band_points` is frozen — 25 for a `MANUAL` alert"; "`priority` is the tier
    points (0 for `LOW`, 100 for `MEDIUM`, 200 for `HIGH`) plus the frozen
    `band_points`".

    Design: Corner/state_machines/alert_created_in_open_with_initial_priority
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-SM3", cardholder_name="Sm Three")
    card = create_card(acct["id"], "PT-SM3")
    alert = create_manual_alert(acct["id"], card["id"])
    assert alert["alert_status"] == "OPEN"
    assert alert["assigned_to_user_id"] is None
    assert alert["reopen_count"] == 0
    assert alert["priority"] == 25, f"LOW 0 + manual band 25 expected 25, got {alert['priority']}"
    # PRD pins the sla_expires_at *value* ("creation plus 72 hours"); the
    # fractional-digit format of computed timestamps is not pinned (§2.4 scopes
    # "three fractional digits" to created_at/updated_at), so compare instants.
    assert parse_iso8601(alert["sla_expires_at"]) == parse_iso8601("2026-08-04T00:00:00Z"), (
        f"sla must be created_at + 72h, got {alert['sla_expires_at']}"
    )


def test_alert_expires_after_sla_and_locks(api):
    """PRD §2.5: "An unresolved alert whose logical-clock time has reached
    `sla_expires_at` (creation plus 72 hours) flips from `OPEN`, `IN_REVIEW`, or
    `CONTACT_PENDING` to `EXPIRED`; `EXPIRED` is terminal."

    Design: Corner/state_machines/alert_expires_after_sla_and_locks
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-SM4", cardholder_name="Sm Four")
    card = create_card(acct["id"], "PT-SM4")
    alert = create_manual_alert(acct["id"], card["id"])
    set_clock("2026-08-04T00:00:00Z")
    fetched = validate_success(api.get_fraud_alert(alert["id"], MANAGER))
    assert fetched["alert_status"] == "EXPIRED", "at exactly +72h the alert must be EXPIRED (>= boundary)"
    resp = api.claim_fraud_alert(alert["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestAlertPriorityTierEvalOrder:
    def test_first_manual_alert_gets_low_tier_points(self, api):
        """PRD §3.4: "first, the account's `risk_tier` is computed **excluding the
        alert being created**"; "`priority` is the tier points (0 for `LOW`, 100
        for `MEDIUM`, 200 for `HIGH`) plus the frozen `band_points`, and it never
        changes thereafter except through escalation."

        Design: Difficulty/combinatorial_formula/alert_priority_tier_eval_order
        """
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CF3", cardholder_name="Prio Order")
        card = create_card(acct["id"], "PT-CF3", product_type="DEBIT", network="MASTERCARD")
        m1 = create_manual_alert(acct["id"], card["id"])
        assert m1["priority"] == 25, f"0 open alerts at creation: LOW 0 + 25 expected 25, got {m1['priority']}"

    def test_second_alert_excludes_itself_and_priorities_freeze(self, api):
        """PRD §3.4: "Creating a new alert never recomputes older alerts'
        priorities."; "the tier is `HIGH` when at least two alerts are open
        (statuses `OPEN`, `IN_REVIEW`, or `CONTACT_PENDING`)" (§3.1).

        Design: Difficulty/combinatorial_formula/alert_priority_tier_eval_order
        """
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-CF3", cardholder_name="Prio Order")
        card = create_card(acct["id"], "PT-CF3", product_type="DEBIT", network="MASTERCARD")
        m1 = create_manual_alert(acct["id"], card["id"])
        m2 = create_manual_alert(acct["id"], card["id"])
        assert m2["priority"] == 125, (
            f"exactly 1 OTHER open alert at M2's creation: MEDIUM 100 + 25 expected 125, got {m2['priority']}"
        )
        m1_after = validate_success(api.get_fraud_alert(m1["id"], MANAGER))
        assert m1_after["priority"] == 25, "M1 priority must stay frozen"
        account = validate_success(api.get_account(acct["id"], MANAGER))
        assert account["risk_tier"] == "HIGH", "2 open alerts >= 2 -> HIGH"
        m2_after = validate_success(api.get_fraud_alert(m2["id"], MANAGER))
        assert m2_after["priority"] == 125, "account tier rising afterwards must not recompute M2"


def test_alert_claim_twice_rejected(api):
    """PRD §3.4: "claiming an alert that is already `IN_REVIEW` fails with
    `ERR_INVALID_STATE` (HTTP 409)"; "A `FraudAnalyst` claims an `OPEN` alert,
    moving it to `IN_REVIEW` and stamping `assigned_to_user_id` with their own
    `X-User-ID`".

    Design: Corner/state_machines/alert_claim_twice_rejected
    """
    acct = create_account("ACCT-SM12", cardholder_name="Sm Twelve")
    card = create_card(acct["id"], "PT-SM12")
    alert = create_manual_alert(acct["id"], card["id"])
    claimed = validate_success(api.claim_fraud_alert(alert["id"], make_analyst_headers("analyst-1")))
    assert claimed["assigned_to_user_id"] == "analyst-1"
    resp = api.claim_fraud_alert(alert["id"], make_analyst_headers("analyst-2"))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    current = validate_success(api.get_fraud_alert(alert["id"], MANAGER))
    assert current["assigned_to_user_id"] == "analyst-1"


def test_fraud_alert_list_filter_by_status(api):
    """PRD §2.7: "alerts by `account_id`, `card_id`, `auth_transaction_id`,
    `alert_status`, or `assigned_to_user_id`".

    Design: Corner/endpoints/fraud_alert_list_filter_by_status
    """
    acct = create_account("ACCT-EP2", cardholder_name="Ep Two")
    card = create_card(acct["id"], "PT-EP2")
    a1 = create_manual_alert(acct["id"], card["id"])
    a2 = create_manual_alert(acct["id"], card["id"])
    claim_alert(a2["id"])
    data, meta = validate_paginated(
        api.list_fraud_alerts(MANAGER, params={"alert_status": "OPEN", "account_id": acct["id"]})
    )
    assert meta["total_count"] == 1
    assert data[0]["id"] == a1["id"]


class TestResolveRequiresMatchingCompletedContact:
    def _setup_claimed_alert(self, api):
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-V8", cardholder_name="Val Eight")
        card = create_card(acct["id"], "PT-V8")
        alert = create_manual_alert(acct["id"], card["id"])
        claim_alert(alert["id"])
        return acct, card, alert

    def test_resolve_without_contact_rejected(self, api):
        """PRD §3.5: "an alert with no matching fresh contact is rejected with
        `ERR_CONTACT_REQUIRED`".

        Design: Corner/validations/resolve_requires_matching_completed_contact
        """
        _acct, _card, alert = self._setup_claimed_alert(api)
        resp = api.resolve_fraud_alert(alert["id"], {"resolution": "FRAUD"}, make_analyst_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_CONTACT_REQUIRED, expected_status=409)

    def test_resolve_with_unreachable_contact_rejected(self, api):
        """PRD §3.5: "an `UNREACHABLE` outcome never satisfies any resolution."

        Design: Corner/validations/resolve_requires_matching_completed_contact
        """
        _acct, _card, alert = self._setup_claimed_alert(api)
        create_and_complete_contact(alert["id"], "UNREACHABLE")
        resp = api.resolve_fraud_alert(alert["id"], {"resolution": "FRAUD"}, make_analyst_headers("analyst-1"))
        validate_error(resp, ApiErrorId.ERR_CONTACT_REQUIRED, expected_status=409)
        current = validate_success(api.get_fraud_alert(alert["id"], MANAGER))
        assert current["alert_status"] == "CONTACT_PENDING"


class TestAlertReopenLoopWithCounter:
    def _setup_resolved_twice(self, api):
        """Manual alert on a txn; cycle 1 LEGIT -> reopen; cycle 2 FRAUD; two reopens
        consumed."""
        set_clock("2026-08-01T00:00:00Z")
        acct = create_account("ACCT-NL2", cardholder_name="Re Open")
        card = create_card(acct["id"], "PT-NL2", product_type="CREDIT", network="VISA")
        create_active_ruleset()
        txn = post_txn(card["id"], 1000, "M-NL2", channel="CNP", origin_country="US")
        alert = create_manual_alert(acct["id"], card["id"], auth_transaction_id=txn["id"])
        claim_alert(alert["id"])
        create_and_complete_contact(alert["id"], "CONFIRMED_LEGIT")
        resolve_alert(alert["id"], "LEGIT")
        get_success_data(api.reopen_fraud_alert(alert["id"], {"reason": "cardholder called back"}, ANALYST))
        set_clock("2026-08-01T01:01:00Z")
        create_and_complete_contact(alert["id"], "CONFIRMED_FRAUD")
        resolve_alert(alert["id"], "FRAUD")
        get_success_data(api.reopen_fraud_alert(alert["id"], {"reason": "second review"}, ANALYST))
        set_clock("2026-08-01T02:02:00Z")
        create_and_complete_contact(alert["id"], "CONFIRMED_FRAUD", channel="SMS")
        resolve_alert(alert["id"], "FRAUD")
        return acct, card, txn, alert

    def test_third_reopen_rejected_at_limit(self, api):
        """PRD §3.5: "`reopen_count` must be below 2, else `ERR_REOPEN_LIMIT_EXCEEDED`
        (HTTP 409)"; "A successful reopen increments `reopen_count` by 1".

        Design: Difficulty/non_linear_state_machine/alert_reopen_loop_with_counter
        """
        _acct, _card, _txn, alert = self._setup_resolved_twice(api)
        resp = api.reopen_fraud_alert(alert["id"], {"reason": "third attempt"}, ANALYST)
        validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED, expected_status=409)
        current = validate_success(api.get_fraud_alert(alert["id"], MANAGER))
        assert current["alert_status"] == "RESOLVED_FRAUD"
        assert current["reopen_count"] == 2

    def test_latest_resolution_wins_across_reopen_cycles(self, api):
        """PRD §3.5: "Latest resolution wins on the transaction: a later `LEGIT`
        resolution may overwrite an earlier `CONFIRMED_FRAUD` disposition and vice
        versa."

        Design: Difficulty/non_linear_state_machine/alert_reopen_loop_with_counter
        """
        _acct, _card, txn, alert = self._setup_resolved_twice(api)
        fetched = validate_success(api.get_auth_transaction(txn["id"], MANAGER))
        assert fetched["final_disposition"] == "CONFIRMED_FRAUD", (
            "the second cycle's FRAUD resolution must overwrite the first cycle's LEGIT"
        )


def test_latest_resolution_wins_disposition(api):
    """PRD §3.5: "Latest resolution wins on the transaction: a later `LEGIT`
    resolution may overwrite an earlier `CONFIRMED_FRAUD` disposition and vice
    versa."

    Design: Corner/state_machines/latest_resolution_wins_disposition
    """
    set_clock("2026-08-01T00:00:00Z")
    acct = create_account("ACCT-SM13", cardholder_name="Sm Thirteen")
    card = create_card(acct["id"], "PT-SM13")
    create_active_ruleset()
    txn = post_txn(card["id"], 1000, "M-SM13", channel="CNP", origin_country="US")
    a1 = create_manual_alert(acct["id"], card["id"], auth_transaction_id=txn["id"])
    a2 = create_manual_alert(acct["id"], card["id"], auth_transaction_id=txn["id"])
    claim_alert(a1["id"])
    claim_alert(a2["id"])
    create_and_complete_contact(a1["id"], "CONFIRMED_FRAUD")
    resolve_alert(a1["id"], "FRAUD")
    mid = validate_success(api.get_auth_transaction(txn["id"], MANAGER))
    assert mid["final_disposition"] == "CONFIRMED_FRAUD"
    set_clock("2026-08-01T01:01:00Z")
    create_and_complete_contact(a2["id"], "CONFIRMED_LEGIT", channel="SMS")
    resolve_alert(a2["id"], "LEGIT")
    final = validate_success(api.get_auth_transaction(txn["id"], MANAGER))
    assert final["final_disposition"] == "CONFIRMED_LEGIT", "the later LEGIT resolution must win"


def test_cardholder_respond_creates_contact_and_resolves(api):
    """PRD §3.5: "A `Cardholder` may instead respond directly through the
    self-service respond action with an `outcome`, which creates an
    already-`COMPLETED` `IN_APP` contact and resolves the alert in one step — this
    path works even while the alert is still `OPEN`."; PRD §3.5: "if the card is
    still `ACTIVE`, it is soft-blocked with `block_reason` `CONFIRMED_FRAUD`";
    PRD §3.5: "`created_by_user_id` set to the analyst (or `SYSTEM` for
    cardholder-initiated `IN_APP` contacts)".

    Design: Corner/endpoints/cardholder_respond_creates_contact_and_resolves
    """
    acct = create_account("ACCT-EP4", cardholder_name="Ep Four")
    card = create_card(acct["id"], "PT-EP4", product_type="DEBIT", network="MASTERCARD")
    alert = create_manual_alert(acct["id"], card["id"])
    resolved = validate_success(
        api.respond_fraud_alert(
            alert["id"], {"outcome": "CONFIRMED_FRAUD"}, make_cardholder_headers(acct["id"])
        )
    )
    assert resolved["alert_status"] == "RESOLVED_FRAUD"
    contacts, meta = validate_paginated(
        api.list_verification_contacts(MANAGER, params={"alert_id": alert["id"]})
    )
    assert meta["total_count"] == 1
    contact = contacts[0]
    assert contact["channel"] == "IN_APP"
    assert contact["contact_status"] == "COMPLETED"
    assert contact["outcome"] == "CONFIRMED_FRAUD"
    assert contact["created_by_user_id"] == "SYSTEM"
    card_after = validate_success(api.get_card(card["id"], MANAGER))
    assert card_after["card_status"] == "SOFT_BLOCKED"
    assert card_after["block_reason"] == "CONFIRMED_FRAUD"
