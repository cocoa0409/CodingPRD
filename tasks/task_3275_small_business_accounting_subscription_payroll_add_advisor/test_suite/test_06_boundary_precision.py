"""Boundary precision — exact seat-limit threshold and exact zero-difference
recon completion.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    accept_user,
    activate_subscription,
    add_bank_connection,
    add_category,
    create_company,
    create_company_user,
    create_essentials_plan,
    create_plus_plan,
    create_primary_admin,
    get_subscription,
    ingest_txn,
    reset_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestSeatLimitBoundary:
    """At exactly max_seats the add succeeds; at max_seats+1 it is rejected."""

    def _setup_company_at_seat_capacity(self, client):
        """ESSENTIALS plan with max_seats=3, company occupied to 3."""
        plan = create_essentials_plan(client)
        company = create_company(client, plan["id"], legal_name="Nu Corp")
        admin = create_primary_admin(client, company["id"])
        accept_user(client, company["id"], admin["id"])
        admin_headers = make_company_user_headers(admin["id"])
        # Two more INVITED users brings occupied to 3.
        create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="u2@n.example", display_name="U2",
        )
        create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="u3@n.example", display_name="U3",
        )
        return plan, company, admin, admin_headers

    def test_at_max_seats_occupied_add_succeeds(self, client):
        """PRD 3.2: "The seat check counts users of the company in `INVITED`
        or `ACTIVE` status — `DISABLED` users do not occupy seats — and
        rejects the invite or acceptance when adding one more would take the
        occupied count strictly above `max_seats`; at exactly `max_seats`
        the add still succeeds."

        Design: Difficulty/boundary_precision_check/seat_limit_max_seats_exactly_allowed_plus_one_rejected
        """
        reset_clock(client)
        plan = create_essentials_plan(client)  # max_seats=3
        company = create_company(client, plan["id"], legal_name="Nu2 Corp")
        admin = create_primary_admin(client, company["id"])
        # occupied=1 (INVITED admin).  Invite two more — occupied 2 then 3, OK.
        admin_headers = make_company_user_headers(admin["id"])
        # The inviting actor must exist; but the admin hasn't accepted yet —
        # the FIRST invite can be done by PlatformAdmin.  Subsequent invites
        # need an ACTIVE admin.  Accept the admin first.
        accept_user(client, company["id"], admin["id"])
        create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="x@n2.example", display_name="X",
        )
        # Now occupied = 2 (admin ACTIVE + 1 INVITED).  Add the third: should succeed.
        third = create_company_user(
            client, company["id"], actor_headers=admin_headers,
            email="y@n2.example", display_name="Y",
        )
        assert third["user_status"] == "INVITED"

    def test_above_max_seats_rejected_with_seat_limit(self, client):
        """PRD 3.2: "The rejection is `ERR_SEAT_LIMIT_REACHED` (HTTP 400)
        and, as a merchandising hook, sets `pending_upgrade_prompt` on the
        subscription."

        Design: Difficulty/boundary_precision_check/seat_limit_max_seats_exactly_allowed_plus_one_rejected
        """
        reset_clock(client)
        plan, company, admin, admin_headers = self._setup_company_at_seat_capacity(client)

        # occupied=3 == max_seats.  Adding a 4th must be rejected.
        response = client.create_company_user(
            company["id"],
            f.create_company_user_payload(company["id"], email="u4@n.example"),
            headers=admin_headers,
        )
        validate_error(response, E.ERR_SEAT_LIMIT_REACHED)

        # The merchandising hook sets pending_upgrade_prompt.
        subscription = get_subscription(client, company["id"])
        assert subscription["pending_upgrade_prompt"] is True

        # The 4th user was NOT created.
        users_response = client.list_company_users(
            company["id"], headers=PLATFORM_ADMIN
        )
        body = users_response.json()
        rows = body.get("data") if isinstance(body, dict) else []
        if isinstance(rows, list):
            assert len(rows) == 3


class TestReconDifferenceZeroBoundary:
    """complete() requires difference_cents == 0 exactly; 1 cent off rejects."""

    def _setup_company_with_categorized_txn(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Omicron Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        connection = add_bank_connection(
            client, company["id"], admin["id"],
            institution_name="Citi", external_account_mask="5555",
        )
        category = add_category(
            client, company["id"], admin["id"], name="Misc", tax_line="SCH-C-L27"
        )
        txn = ingest_txn(
            client, company["id"], connection["id"],
            posted_at="2026-09-10T00:00:00Z", amount_cents=-1000,
            payee_raw="STAPLES",
        )
        admin_headers = make_company_user_headers(admin["id"])
        client.categorize_bank_transaction(
            company["id"], txn["id"], {"category_id": category["id"]},
            headers=admin_headers,
        )
        return scenario, connection, txn

    def test_off_by_one_cent_rejects_completion(self, client):
        """PRD 3.7: "Completing a reconciliation requires `difference_cents`
        to be exactly zero — zero and only zero; any residual is rejected
        with `ERR_RECON_DIFFERENCE_NOT_ZERO` (HTTP 400)."

        Design: Difficulty/boundary_precision_check/recon_difference_zero_exactly_required
        """
        reset_clock(client)
        scenario, connection, _txn = self._setup_company_with_categorized_txn(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = make_company_user_headers(admin["id"])

        # statement_ending_balance_cents=-999 vs cleared=-1000 -> difference=-1.
        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-09-01T00:00:00Z",
                statement_period_end="2026-09-30T00:00:00Z",
                statement_ending_balance_cents=-999,
            ),
            headers=admin_headers,
        )
        recon = get_success_data(create_response)
        client.start_reconciliation(company["id"], recon["id"], headers=admin_headers)

        complete_response = client.complete_reconciliation(
            company["id"], recon["id"], headers=admin_headers
        )
        validate_error(complete_response, E.ERR_RECON_DIFFERENCE_NOT_ZERO)

        # State is unchanged on failure.
        after = get_success_data(
            client.get_reconciliation(company["id"], recon["id"],
                                       headers=PLATFORM_ADMIN)
        )
        assert after["recon_status"] == "IN_PROGRESS"

    def test_exactly_zero_completes(self, client):
        """PRD 3.7: "Completing a reconciliation requires `difference_cents`
        to be exactly zero — zero and only zero; any residual is rejected
        with `ERR_RECON_DIFFERENCE_NOT_ZERO` (HTTP 400). On completion every
        `CATEGORIZED` transaction in the window cascades to
        `MATCHED_RECONCILED` with its `reconciled_in_id` set — locking those
        transactions against further modification — and `completed_at` is
        stamped."

        Design: Difficulty/boundary_precision_check/recon_difference_zero_exactly_required
        """
        reset_clock(client)
        scenario, connection, txn = self._setup_company_with_categorized_txn(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = make_company_user_headers(admin["id"])

        # statement_ending_balance_cents=-1000 == cleared -> difference=0.
        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-09-01T00:00:00Z",
                statement_period_end="2026-09-30T00:00:00Z",
                statement_ending_balance_cents=-1000,
            ),
            headers=admin_headers,
        )
        recon = get_success_data(create_response)
        client.start_reconciliation(company["id"], recon["id"], headers=admin_headers)
        completed = client.complete_reconciliation(
            company["id"], recon["id"], headers=admin_headers
        )
        body = get_success_data(completed)
        assert body["recon_status"] == "COMPLETED"
        assert body["difference_cents"] == 0
        assert body.get("completed_at"), "completed_at must be stamped"

        # The in-window CATEGORIZED txn cascaded to MATCHED_RECONCILED.
        txn_after = get_success_data(
            client.get_bank_transaction(company["id"], txn["id"],
                                          headers=PLATFORM_ADMIN)
        )
        assert txn_after["txn_status"] == "MATCHED_RECONCILED"
        assert txn_after.get("reconciled_in_id") == recon["id"]
