"""Composite setup helpers for multi-step PRD scenarios.

Every fixture builds preconditions from scratch against a fresh server (the
runner restarts the server before each test) using only PRD-declared endpoints.
Setup calls use the lenient get_success_data() so failures surface as clear
setup errors.
"""
from datetime import timedelta

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client as api
from .constants import (
    CLOCK_START,
    USER_ANALYST_1,
    USER_MANAGER_1,
    USER_ACCOUNTANT_1,
    USER_RECOVERY_1,
)
from .factories import (
    create_account_payload,
    create_card_payload,
    create_rule_set_payload,
    create_auth_transaction_payload,
    create_compromised_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_analyst_headers,
    make_manager_headers,
    make_accountant_headers,
    make_recovery_headers,
    make_gateway_headers,
)

MANAGER = TEST_USERS["manager_headers"]
ANALYST = TEST_USERS["analyst_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]
RECOVERY = TEST_USERS["recovery_headers"]
GATEWAY = TEST_USERS["gateway_headers"]


# ---------------------------------------------------------------------------
# Tier 1: basic entity creation and state progression
# ---------------------------------------------------------------------------

def set_clock(to_iso8601=CLOCK_START):
    """Advance the logical clock. Returns the response data."""
    return get_success_data(api.set_clock({"to_iso8601": to_iso8601}, MANAGER))


def create_account(account_number, cardholder_name="Test Holder", home_country="US"):
    """Create an ACTIVE account. Returns the Account."""
    payload = create_account_payload(
        account_number=account_number,
        cardholder_name=cardholder_name,
        home_country=home_country,
    )
    return get_success_data(api.create_account(payload, MANAGER))


def create_card(account_id, pan_token, product_type="CREDIT", network="VISA"):
    """Issue an ACTIVE, CLEAN card on an ACTIVE account. Returns the Card."""
    payload = create_card_payload(
        account_id=account_id,
        pan_token=pan_token,
        product_type=product_type,
        network=network,
    )
    return get_success_data(api.create_card(payload, MANAGER))


def create_active_ruleset(creator_user_id=USER_ANALYST_1, activator_user_id=USER_MANAGER_1, **overrides):
    """Create a DRAFT ruleset and activate it (segregation: activator != creator).
    Returns the ACTIVE RuleSet."""
    payload = create_rule_set_payload(**overrides)
    creator_headers = (
        make_manager_headers(creator_user_id)
        if creator_user_id.startswith("mgr")
        else make_analyst_headers(creator_user_id)
    )
    rs = get_success_data(api.create_rule_set(payload, creator_headers))
    return get_success_data(api.activate_rule_set(rs["id"], make_manager_headers(activator_user_id)))


def post_txn(card_id, amount_cents, merchant_id, channel="CNP", origin_country="US", mcc="5411"):
    """Submit one authorization through the network gateway. Returns the AuthTransaction."""
    payload = create_auth_transaction_payload(
        card_id=card_id,
        amount_cents=amount_cents,
        merchant_id=merchant_id,
        merchant_category_code=mcc,
        channel=channel,
        origin_country=origin_country,
    )
    return get_success_data(api.create_auth_transaction(payload, GATEWAY), expected_status=201)


def setup_account_with_card_and_ruleset(
    account_number,
    pan_token,
    product_type="CREDIT",
    network="VISA",
    home_country="US",
    clock=CLOCK_START,
    **ruleset_overrides,
):
    """Tier 2: clock set + ACTIVE account + one card + ACTIVE GLOBAL ruleset.
    Returns (account, card, ruleset)."""
    set_clock(clock)
    account = create_account(account_number, home_country=home_country)
    card = create_card(account["id"], pan_token, product_type=product_type, network=network)
    ruleset = create_active_ruleset(**ruleset_overrides)
    return account, card, ruleset


# ---------------------------------------------------------------------------
# Tier 3: alert lifecycle shortcuts
# ---------------------------------------------------------------------------

def create_manual_alert(account_id, card_id, auth_transaction_id=None, creator=None):
    """Create a MANUAL fraud alert. Returns the FraudAlert."""
    payload = {"account_id": account_id, "card_id": card_id}
    if auth_transaction_id is not None:
        payload["auth_transaction_id"] = auth_transaction_id
    return get_success_data(
        api.create_fraud_alert(payload, creator or ANALYST), expected_status=201
    )


def claim_alert(alert_id, analyst_user_id=USER_ANALYST_1):
    """OPEN -> IN_REVIEW under the given analyst. Returns the alert."""
    return get_success_data(
        api.claim_fraud_alert(alert_id, make_analyst_headers(analyst_user_id))
    )


def create_and_complete_contact(alert_id, outcome, analyst_user_id=USER_ANALYST_1, channel="VOICE"):
    """Create a contact (alert IN_REVIEW -> CONTACT_PENDING) and complete it.
    Returns the COMPLETED VerificationContact."""
    headers = make_analyst_headers(analyst_user_id)
    contact = get_success_data(
        api.create_verification_contact({"alert_id": alert_id, "channel": channel}, headers),
        expected_status=201,
    )
    return get_success_data(
        api.complete_verification_contact(contact["id"], {"outcome": outcome}, headers)
    )


def resolve_alert(alert_id, resolution, analyst_user_id=USER_ANALYST_1, fraud_credit_cents=None):
    """Resolve an alert FRAUD or LEGIT. Returns the resolved alert."""
    payload = {"resolution": resolution}
    if fraud_credit_cents is not None:
        payload["fraud_credit_cents"] = fraud_credit_cents
    return get_success_data(
        api.resolve_fraud_alert(alert_id, payload, make_analyst_headers(analyst_user_id))
    )


def resolve_txn_fraud_via_manual_alert(
    account_id,
    card_id,
    txn_id,
    analyst_user_id=USER_ANALYST_1,
    fraud_credit_cents=None,
):
    """Full Tier-3 lifecycle: manual alert on txn -> claim -> contact CONFIRMED_FRAUD
    -> resolve FRAUD. Leaves the transaction CONFIRMED_FRAUD. Returns the alert."""
    alert = create_manual_alert(account_id, card_id, auth_transaction_id=txn_id)
    claim_alert(alert["id"], analyst_user_id)
    create_and_complete_contact(alert["id"], "CONFIRMED_FRAUD", analyst_user_id)
    return resolve_alert(alert["id"], "FRAUD", analyst_user_id, fraud_credit_cents)


def setup_confirmed_fraud_txn(
    account_number,
    pan_token,
    amount_cents,
    merchant_id,
    product_type="CREDIT",
    network="VISA",
    channel="CNP",
    origin_country="US",
    clock=CLOCK_START,
    fraud_credit_cents=None,
):
    """Tier 5: account + card + active ruleset + one scored txn + manual alert
    resolved FRAUD. Returns dict with account, card, ruleset, txn, alert.

    The account is left with no open alerts: if the intake scored REVIEW, the
    auto-created SCORING_REVIEW alert (PRD §3.3: "A `REVIEW` decision creates
    exactly one `FraudAlert`") is resolved FRAUD as well — otherwise the
    dangling OPEN alert would keep the account at exactly one open alert and
    force `risk_tier` MEDIUM per §3.1, surprising tier/alert-count assertions."""
    account, card, ruleset = setup_account_with_card_and_ruleset(
        account_number, pan_token, product_type=product_type, network=network, clock=clock
    )
    txn = post_txn(card["id"], amount_cents, merchant_id, channel=channel, origin_country=origin_country)
    alert = resolve_txn_fraud_via_manual_alert(
        account["id"], card["id"], txn["id"], fraud_credit_cents=fraud_credit_cents
    )
    if txn["decision"] == "REVIEW":
        # Resolve the auto-created SCORING_REVIEW alert FRAUD too (latest
        # resolution wins with the same outcome, so the txn stays
        # CONFIRMED_FRAUD). The 61-minute clock bump respects the per-account
        # 60-minute contact gap (§3.5).
        auto_alerts, _meta = validate_paginated(
            api.list_fraud_alerts(
                MANAGER,
                params={"auth_transaction_id": txn["id"], "alert_status": "OPEN"},
            )
        )
        assert len(auto_alerts) == 1 and auto_alerts[0]["source"] == "SCORING_REVIEW", (
            f"expected the auto-created SCORING_REVIEW alert, got {auto_alerts}"
        )
        bumped = (_parse_clock(clock) + timedelta(minutes=61)).strftime("%Y-%m-%dT%H:%M:%SZ")
        set_clock(bumped)
        claim_alert(auto_alerts[0]["id"])
        create_and_complete_contact(auto_alerts[0]["id"], "CONFIRMED_FRAUD")
        resolve_alert(auto_alerts[0]["id"], "FRAUD")
    return {"account": account, "card": card, "ruleset": ruleset, "txn": txn, "alert": alert}


def _parse_clock(iso: str):
    """Parse a clock literal like 2026-08-01T00:00:00Z into an aware datetime."""
    from datetime import datetime, timezone

    s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Tier 4: loss / recovery accumulation
# ---------------------------------------------------------------------------

def create_booked_loss(account_id, txn_ids, accountant_user_id=USER_ACCOUNTANT_1):
    """Create + book a loss entry. Returns the BOOKED LossEntry."""
    loss = get_success_data(
        api.create_loss_entry(
            {"account_id": account_id, "transaction_ids": txn_ids}, ACCOUNTANT
        ),
        expected_status=201,
    )
    return get_success_data(
        api.book_loss_entry(loss["id"], make_accountant_headers(accountant_user_id))
    )


def create_finalized_loss(account_id, txn_ids, final_amount_cents, accountant_user_id=USER_ACCOUNTANT_1):
    """Create + book + finalize a loss. Returns the FINALIZED LossEntry."""
    loss = create_booked_loss(account_id, txn_ids, accountant_user_id)
    return get_success_data(
        api.finalize_loss_entry(
            loss["id"], {"final_amount_cents": final_amount_cents},
            make_accountant_headers(accountant_user_id),
        )
    )


def create_accepted_filing(loss_id, claimed_cents, network_reference, filer_user_id=USER_RECOVERY_1):
    """File a recovery and mark it ACCEPTED. Returns the ACCEPTED RecoveryFiling."""
    filing = get_success_data(
        api.create_recovery_filing(
            {
                "loss_entry_id": loss_id,
                "network_reference": network_reference,
                "claimed_cents": claimed_cents,
            },
            make_recovery_headers(filer_user_id),
        ),
        expected_status=201,
    )
    return get_success_data(
        api.mark_filing_outcome(filing["id"], {"outcome": "ACCEPTED"}, RECOVERY)
    )


# ---------------------------------------------------------------------------
# Tier 4b: compromise-event cascade
# ---------------------------------------------------------------------------

def create_and_confirm_event(merchant_id, window_start, window_end, event_reference, network_source="CAMS"):
    """Intake + confirm a compromised-card event. Returns the CONFIRMED event."""
    payload = create_compromised_event_payload(
        network_source=network_source,
        event_reference=event_reference,
        merchant_id=merchant_id,
        window_start=window_start,
        window_end=window_end,
    )
    event = get_success_data(api.create_compromised_card_event(payload, MANAGER), expected_status=201)
    return get_success_data(api.confirm_compromised_card_event(event["id"], MANAGER))


def get_decision_for_card(card_id):
    """Return the (single) ReissueDecision attached to a card."""
    data, _meta = validate_paginated(
        api.list_reissue_decisions(MANAGER, params={"card_id": card_id})
    )
    assert len(data) == 1, f"expected exactly one reissue decision for card {card_id}, got {len(data)}"
    return data[0]
