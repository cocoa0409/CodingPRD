"""Optimistic concurrency on offer withdrawal (PRD §2.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_and_approve_resource,
    create_and_open_run,
    create_owner,
    get_success_data,
    make_resource_owner_headers,
    seal_run,
    setup_forecast_locked_year,
    submit_offer,
    validate_error,
)

ADMIN = TEST_USERS["market_admin_headers"]


class TestWithdrawOcc:
    def test_withdraw_with_pre_seal_run_version_rejected_stale(self, api):
        """PRD §2.7: "Because sealing a run advances its version and freezes
        every offer's price terms, a withdrawal carrying a pre-seal version is
        rejected with `ERR_STALE_VERSION` (HTTP 412) rather than as a plain
        state error."

        Design: Corner/cross_cutting_layers/occ_stale_auction_run_version_on_withdraw
        """
        dy, zone, forecast = setup_forecast_locked_year()
        owner = create_owner()
        resource, _ = create_and_approve_resource(owner["id"], zone["id"], dy["id"])
        run = create_and_open_run(dy["id"])
        offer = submit_offer(resource["id"], owner["id"], run["id"],
                             offer_mw=10.0, offer_price_per_mw_day=70.0)
        run_pre_seal = get_success_data(api.get_auction_run(run["id"], ADMIN))
        seal_run(run["id"])
        resp = api.withdraw_offer(
            offer["id"], run_pre_seal["version"],
            make_resource_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
        offer_after = get_success_data(api.get_offer(offer["id"], ADMIN))
        assert offer_after["status"] == "SEALED"
