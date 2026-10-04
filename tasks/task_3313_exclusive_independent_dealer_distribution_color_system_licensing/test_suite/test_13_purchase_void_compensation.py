"""Rolling spend conservation under void compensation."""
from test_helpers import (
    api_client,
    make_dealer_principal_headers,
    post_purchase,
    set_clock,
    setup_contractor,
    setup_onboarded_dealer,
    validate_success,
)


class TestVoidCompensation:
    def test_void_returns_rolling_spend_to_pre_post_value(self, api):
        """PRD section 3.6: "Voiding a purchase, done by the
        `DealerPrincipal` whose `X-User-ID` equals the dealer that sponsors
        the purchase's contractor account, moves it from `POSTED` to
        `VOIDED`; the account's `rolling_net_spend_cents` is recomputed with
        the voided purchase excluded and the tier re-derived."

        Design: Difficulty/compensating_invariant/rolling_spend_conservation_under_void_compensation
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        contractor = setup_contractor(dealer_id)
        headers = make_dealer_principal_headers(dealer_id)
        # Seed to exactly SILVER: 10000 units at flat 100 = 1000000.
        post_purchase(dealer_id, contractor["id"], ctx["line"]["id"], units=10000)
        # Advance past the purchase month so the seed enters the trailing
        # twelve-full-calendar-month window of PRD section 2.6.
        set_clock("2026-10-01T00:00:00Z")
        before = validate_success(api.get_contractor(contractor["id"], headers))
        assert before["rolling_net_spend_cents"] == 1_000_000
        assert before["tier"] == "SILVER"
        posted = post_purchase(dealer_id, contractor["id"], ctx["line"]["id"], units=100)
        assert posted["invoice_cents"] == 9500
        # Advance again so the second purchase (posted in October) also
        # enters the trailing window before the mid-state read.
        set_clock("2026-11-01T00:00:00Z")
        mid = validate_success(api.get_contractor(contractor["id"], headers))
        assert mid["rolling_net_spend_cents"] == 1_009_500
        validate_success(api.void_purchase(posted["id"], headers))
        after = validate_success(api.get_contractor(contractor["id"], headers))
        assert after["rolling_net_spend_cents"] == 1_000_000
        assert after["tier"] == "SILVER"

    def test_void_marks_purchase_voided(self, api):
        """PRD section 3.6: "Voiding a purchase, done by the
        `DealerPrincipal` whose `X-User-ID` equals the dealer that sponsors
        the purchase's contractor account, moves it from `POSTED` to
        `VOIDED`; the account's `rolling_net_spend_cents` is recomputed with
        the voided purchase excluded and the tier re-derived."

        Design: Difficulty/compensating_invariant/rolling_spend_conservation_under_void_compensation
        """
        ctx = setup_onboarded_dealer()
        dealer_id = ctx["dealer"]["id"]
        contractor = setup_contractor(dealer_id)
        posted = post_purchase(dealer_id, contractor["id"], ctx["line"]["id"], units=5)
        assert posted["status"] == "POSTED"
        voided = validate_success(
            api.void_purchase(posted["id"], make_dealer_principal_headers(dealer_id))
        )
        assert voided["status"] == "VOIDED"
