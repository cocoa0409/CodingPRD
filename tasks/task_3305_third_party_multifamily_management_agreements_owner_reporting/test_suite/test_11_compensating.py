"""Compensating invariant: claim reserve hold + settlement release (PRD §2.9, §3.8, §3.9)."""
from test_helpers import (
    get_success_data,
    open_statement,
    post_ledger_entry,
    set_clock,
    setup_managed_property,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ACCT = TEST_USERS["acct_headers"]
RISK = TEST_USERS["risk_headers"]


class TestClaimReserveConservation:
    def test_claim_reserve_hold_alone_reduces_distribution(self, api, acct_headers):
        """PRD §3.9: "Beginning review moves the claim from `OPEN` to
        `UNDER_REVIEW` and places a contingent hold: the property's cash
        available is reduced by `reserved_amount_cents` for as long as the
        reserve stands."

        Design: Difficulty/compensating_invariant/claim_reserve_hold_and_release_conserves_distributable_cash
        """
        fx = setup_managed_property(legal_name="Conserve2 Owner LP",
                                    property_name="Conserve2 Property", unit_count=400,
                                    distribution_day_of_month=28)
        prop, resident = fx["prop"], fx["resident"]
        post_ledger_entry(prop, "RENT", 60000000, "2026-09",
                          collected_month="2026-09", resident_id=resident["id"])
        st = open_statement(prop, period_month="2026-09", basis="CASH")
        rp = get_success_data(
            api.create_report(
                prop["id"],
                {"period_month": "2026-09", "package_type": "MONTHLY_OWNER"},
                ACCT,
            )
        )
        set_clock("2026-10-01T00:00:00Z")

        # No claim at all: distribution is cash - fees - floor.
        closed = validate_success(api.close_statement(st["id"], acct_headers))
        assert closed["management_fee_total_cents"] == 7200000
        rp_base = validate_success(api.get_report(rp["id"], acct_headers))
        assert rp_base["distribution_amount_cents"] == 32800000, (
            "60000000 - 7200000 - 20000000 == 32800000 with no claim holds"
        )
