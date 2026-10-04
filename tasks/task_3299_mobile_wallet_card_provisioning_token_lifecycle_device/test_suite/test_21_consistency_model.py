"""Corner: consistency model — cascade visible in the immediately following read."""
from test_helpers import (
    ADMIN,
    get_success_data,
    setup_provisioned_token,
)


def test_issuer_suspend_cascade_visible_in_same_request_response_chain(api):
    """PRD section 3.7: "Suspending an ACTIVE issuer — ACTIVE -> SUSPENDED —
    cascades: every ACTIVE payment token with that issuer_id moves to
    SUSPENDED, each with suspension_count incremented and a SUSPENSION event
    appended." The cascade is immediately consistent: a plain GET on the token
    right after the suspend returns SUSPENDED.

    Design: Corner/consistency model/issuer_suspend_cascade_visible_in_same_request_response_chain
    """
    ns = setup_provisioned_token(api)
    get_success_data(api.suspend_issuer(ns["issuer"]["id"], ADMIN))
    token = get_success_data(api.get_payment_token(ns["token"]["id"]))
    assert token["status"] == "SUSPENDED"
    assert token["suspension_count"] == 1
