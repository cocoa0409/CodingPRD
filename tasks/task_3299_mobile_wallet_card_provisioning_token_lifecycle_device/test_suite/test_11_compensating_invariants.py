"""Compensating invariants (queue A): open-disputed cents and active token count."""
from test_helpers import (
    DESK,
    OPERATOR,
    approved_authorization,
    create_dispute_payload,
    get_success_data,
    make_cardholder_headers,
    setup_provisioned_token,
)


def _setup_two_approvals(api):
    ns = setup_provisioned_token(api)
    auth_a = approved_authorization(api, ns["token"], amount_cents=10000,
                                    cryptogram="cgm-a")
    auth_b = approved_authorization(api, ns["token"], amount_cents=20000,
                                    cryptogram="cgm-b", merchant_id="m-2")
    return ns, auth_a, auth_b


def test_open_dispute_adds_exactly_the_disputed_amount(api):
    """PRD section 3.7: "The system tracks open exposure per account as
    total_disputed_cents — the sum of amount_cents over disputes in OPEN
    status traced to that account — and resolution removes the dispute's
    amount from that open set." Opening a 10000-cent dispute moves the
    account's open_disputed_cents from 0 to exactly 10000.

    Design: Difficulty/compensating_invariant/dispute_open_resolve_leaves_open_disputed_total_unchanged
    """
    ns, auth_a, _b = _setup_two_approvals(api)
    base = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert base["open_disputed_cents"] == 0
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(
        api.open_dispute(auth_a["id"], create_dispute_payload(10000, reason="DUPLICATE"), ch)
    )
    mid = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert mid["open_disputed_cents"] == 10000


def test_resolve_removes_exactly_the_disputed_amount(api):
    """PRD section 3.7: "The conservation invariant holds across
    create-and-resolve pairs: the platform-wide sum of open disputed amounts
    changes by exactly the disputed amount at creation and by exactly its
    negation at resolution." After resolve WON the account's
    open_disputed_cents returns to 0 with zero drift.

    Design: Difficulty/compensating_invariant/dispute_open_resolve_leaves_open_disputed_total_unchanged
    """
    ns, auth_a, _b = _setup_two_approvals(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    dispute = get_success_data(
        api.open_dispute(auth_a["id"], create_dispute_payload(10000, reason="DUPLICATE"), ch)
    )
    get_success_data(api.resolve_dispute(dispute["id"], {"outcome": "WON"}, OPERATOR))
    final = get_success_data(api.get_account_risk(ns["account"]["id"], DESK))
    assert final["open_disputed_cents"] == 0
    assert final["open_dispute_count"] == 0


def test_suspend_drops_active_token_count_to_zero(api):
    """PRD section 3.2: the device tracks "an active_token_count of tokens
    currently ACTIVE on it (starting at 0)". Suspending the device's only
    token removes it from the ACTIVE count: the device reads back 0.

    Design: Difficulty/compensating_invariant/token_suspend_resume_cycle_leaves_device_active_token_count_unchanged
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    device = get_success_data(api.get_device(ns["device"]["id"]))
    assert device["active_token_count"] == 1
    get_success_data(api.suspend_token(ns["device"]["id"], ns["token"]["id"], ch))
    device = get_success_data(api.get_device(ns["device"]["id"]))
    assert device["active_token_count"] == 0


def test_resume_restores_active_token_count_exactly(api):
    """PRD section 3.2: the device tracks "an active_token_count of tokens
    currently ACTIVE on it (starting at 0)". The full suspend+resume pair
    restores the pre-suspend count exactly, and repeating the pair keeps the
    count at 1 with no drift.

    Design: Difficulty/compensating_invariant/token_suspend_resume_cycle_leaves_device_active_token_count_unchanged
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d, t = ns["device"]["id"], ns["token"]["id"]
    for _ in range(2):
        get_success_data(api.suspend_token(d, t, ch))
        get_success_data(api.resume_token(d, t, ch))
        device = get_success_data(api.get_device(d))
        assert device["active_token_count"] == 1
