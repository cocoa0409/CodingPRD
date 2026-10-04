"""Transitive cascades: issuer offboard and device lost (queue A)."""
from test_helpers import (
    ADMIN,
    get_success_data,
    make_cardholder_headers,
    setup_provisioned_token,
    validate_paginated,
)


def test_offboard_cascades_account_close_and_token_deactivate(api):
    """PRD section 3.7: "Offboarding, from either ACTIVE or SUSPENDED, is
    terminal (OFFBOARDED) and comprehensive: every card account of the issuer
    in OPEN or RESTRICTED moves to CLOSED, and each closed account cascades to
    its tokens, moving every ACTIVE or SUSPENDED token to DEACTIVATED with
    deactivated_reason ISSUER_REVOKE and a DEACTIVATION event per token."

    Design: Difficulty/transitive_cascade/issuer_offboard_cascades_account_close_token_deactivate_event_append
    """
    ns = setup_provisioned_token(api)
    issuer = get_success_data(api.offboard_issuer(ns["issuer"]["id"], ADMIN))
    assert issuer["status"] == "OFFBOARDED"
    account = get_success_data(api.get_card_account(ns["account"]["id"]))
    assert account["status"] == "CLOSED"
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["status"] == "DEACTIVATED"
    assert token["deactivated_reason"] == "ISSUER_REVOKE"


def test_offboard_appends_deactivation_event_to_token(api):
    """PRD section 3.7: "each closed account cascades to its tokens, moving
    every ACTIVE or SUSPENDED token to DEACTIVATED with deactivated_reason
    ISSUER_REVOKE and a DEACTIVATION event per token" and section 2.12: "Every
    state change or counter-affecting decision on a token that the workflows of
    section 3 describe as 'appending a TokenEvent' must produce exactly one such
    record."

    Design: Difficulty/transitive_cascade/issuer_offboard_cascades_account_close_token_deactivate_event_append
    """
    ns = setup_provisioned_token(api)
    get_success_data(api.offboard_issuer(ns["issuer"]["id"], ADMIN))
    resp = api.list_token_events(ns["token"]["id"])
    events, _ = validate_paginated(resp)
    types = [e["event_type"] for e in events]
    assert types[0] == "ACTIVATION"
    assert types[-1] == "DEACTIVATION", f"expected trailing DEACTIVATION, got {types}"


def test_report_lost_suspends_tokens_and_clears_default(api):
    """PRD section 3.2: "Reporting a device lost ... sets is_lost true, stamps
    reported_lost_at, and flips posture to LOST. The same report sweeps the
    device: every ACTIVE payment token bound to it moves to SUSPENDED (recorded
    with reason lost-device), each such token's suspension_count increments by
    one, a SUSPENSION token event is appended to each, and the device's
    default_card_id is cleared."

    Design: Difficulty/transitive_cascade/device_report_lost_cascades_token_suspend_and_default_clear
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    d, t = ns["device"]["id"], ns["token"]["id"]
    dev = get_success_data(api.get_device(d))
    get_success_data(
        api.set_default_card(
            d, {"token_id": t, "expected_device_version": dev["version"]}, ch
        )
    )
    device = get_success_data(api.report_device_lost(d, ch))
    assert device["security_posture"] == "LOST"
    token = get_success_data(api.get_payment_token(t))
    assert token["status"] == "SUSPENDED"
    assert token["suspension_count"] == 1
    device = get_success_data(api.get_device(d))
    assert device["default_card_id"] is None


def test_report_lost_appends_suspension_event(api):
    """PRD section 3.2: "every ACTIVE payment token bound to it moves to
    SUSPENDED (recorded with reason lost-device), each such token's
    suspension_count increments by one, a SUSPENSION token event is appended to
    each, and the device's default_card_id is cleared."

    Design: Difficulty/transitive_cascade/device_report_lost_cascades_token_suspend_and_default_clear
    """
    ns = setup_provisioned_token(api)
    ch = make_cardholder_headers(ns["cardholder"]["id"])
    get_success_data(api.report_device_lost(ns["device"]["id"], ch))
    resp = api.list_token_events(ns["token"]["id"])
    events, _ = validate_paginated(resp)
    types = [e["event_type"] for e in events]
    assert "SUSPENSION" in types, f"expected SUSPENSION event, got {types}"
