"""PaymentToken suspend/resume cycle (queue A non_linear_state_machine)."""
from test_helpers import (
    get_success_data,
    make_cardholder_headers,
    setup_provisioned_token,
)


def test_suspend_resume_cycle_repeats_and_counts(api):
    """PRD section 3.5: "Suspending a token — ACTIVE -> SUSPENDED — requires
    the token to be ACTIVE (else ERR_INVALID_STATE), increments its
    suspension_count by one, and appends a SUSPENSION event. Resuming —
    SUSPENDED -> ACTIVE — ... A successful resume appends a RESUMPTION event."
    Two full ACTIVE->SUSPENDED->ACTIVE cycles leave the token ACTIVE with
    suspension_count exactly 2.

    Design: Difficulty/non_linear_state_machine/payment_token_suspend_resume_cycle_repeats_and_counts
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d, t = ns["device"]["id"], ns["token"]["id"]
    get_success_data(api.suspend_token(d, t, ch))
    get_success_data(api.resume_token(d, t, ch))
    get_success_data(api.suspend_token(d, t, ch))
    token = get_success_data(api.resume_token(d, t, ch))
    assert token["status"] == "ACTIVE", f"expected ACTIVE, got {token['status']}"
    assert token["suspension_count"] == 2, (
        f"expected suspension_count 2, got {token['suspension_count']}"
    )


def test_third_suspend_after_two_cycles_succeeds(api):
    """PRD section 3.5: "Suspending a token — ACTIVE -> SUSPENDED — requires
    the token to be ACTIVE (else ERR_INVALID_STATE), increments its
    suspension_count by one, and appends a SUSPENSION event." The cycle is
    repeatable: after two suspend/resume pairs a third suspend from ACTIVE
    succeeds and raises suspension_count to 3.

    Design: Difficulty/non_linear_state_machine/payment_token_suspend_resume_cycle_repeats_and_counts
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d, t = ns["device"]["id"], ns["token"]["id"]
    for _ in range(2):
        get_success_data(api.suspend_token(d, t, ch))
        get_success_data(api.resume_token(d, t, ch))
    token = get_success_data(api.suspend_token(d, t, ch))
    assert token["status"] == "SUSPENDED"
    assert token["suspension_count"] == 3
