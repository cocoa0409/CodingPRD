"""Corner / errors — window-expiry on late transfer accept."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers.fixtures import (
    create_firm,
    create_firm_user,
    create_plus_plan,
    get_subscription,
    initiate_transfer_to_firm,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import make_company_user_headers


class TestWindowExpiredOnLateTransferAccept:
    def test_err_window_expired_triggered_on_late_transfer_accept(self, client):
        """PRD 3.10: "The client's primary admin accepts a client-pending
        transfer with `expected_subscription_version` per §2.6, provided the
        transfer has not expired ... A transfer left unresolved past
        `expires_at` expires automatically when the clock passes, and acting
        on an expired transfer is rejected with `ERR_TRANSFER_EXPIRED`
        (HTTP 400)."

        PRD 2.6 catalogs `ERR_WINDOW_EXPIRED` for time-window checks across
        transfer/grant/export/reactivate.

        Design: Corner/errors/err_window_expired_triggered_on_late_transfer_accept
        """
        reset_clock(client)
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Late Co"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        subscription = scenario["subscription"]

        firm = create_firm(client, firm_name="Late Firm")
        firm_admin = create_firm_user(
            client, firm["id"], is_firm_admin=True, email="fa@late.example"
        )
        transfer = initiate_transfer_to_firm(
            client, company["id"], subscription["id"], firm["id"], firm_admin["id"]
        )

        # Advance past the 14-day transfer window.
        set_clock(client, "2026-09-20T00:00:00Z")

        current = get_subscription(client, company["id"])
        response = client.client_accept_billing_transfer(
            company["id"], transfer["id"],
            {"expected_subscription_version": current["version"]},
            headers=make_company_user_headers(admin["id"]),
        )
        # PRD names ERR_TRANSFER_EXPIRED for the expired-accept path; the
        # design instance expects ERR_WINDOW_EXPIRED.  Both encode the same
        # rejection — accept whichever the implementation chose.
        body = response.json()
        err_id = body.get("data", {}).get("error_id")
        assert response.status_code == 400, (
            "expired transfer accept must be rejected: {0}".format(response.text)
        )
        assert err_id in (E.ERR_WINDOW_EXPIRED, E.ERR_TRANSFER_EXPIRED), (
            "expected window-expired or transfer-expired; got {0}".format(err_id)
        )
