"""Resource temporal overlap — closed-interval recon windows and the
migration-job lifetime window.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
)

from test_helpers import api_errors as E
from test_helpers import factories as f
from test_helpers.fixtures import (
    add_bank_connection,
    complete_recon,
    create_company,
    create_plus_plan,
    create_primary_admin,
    accept_user,
    reset_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestReconWindowClosedIntervalSemantics:
    """Closed interval on both ends: adjacency at the boundary IS overlap."""

    def _setup_completed_recon(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Sigma Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        connection = add_bank_connection(
            client, company["id"], admin["id"],
            institution_name="Chase", external_account_mask="2222",
        )
        # Existing COMPLETED recon [2026-08-01, 2026-08-31].
        recon1 = complete_recon(
            client, company["id"], admin["id"], connection["id"],
            statement_period_start="2026-08-01T00:00:00Z",
            statement_period_end="2026-08-31T00:00:00Z",
            statement_ending_balance_cents=0,
        )
        return scenario, connection, recon1

    def test_adjacent_start_equal_to_existing_end_is_overlap(self, client):
        """PRD 3.7: "Because both ends of every window are closed, adjacency
        counts as overlap — a window whose start equals another window's end
        collides; true adjacency requires starting the day after the other's
        end. Violations are rejected with `ERR_STATEMENT_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/recon_window_closed_interval_overlap_and_adjacency
        """
        reset_clock(client)
        scenario, connection, _r1 = self._setup_completed_recon(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = make_company_user_headers(admin["id"])

        # New window starts 2026-08-31 — the same day the existing window ends.
        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-08-31T00:00:00Z",
                statement_period_end="2026-09-30T00:00:00Z",
                statement_ending_balance_cents=0,
            ),
            headers=admin_headers,
        )
        # Creation may succeed; overlap fires at start.  If create already
        # rejects with the overlap, that also satisfies the rule.
        if create_response.status_code >= 400:
            validate_error(create_response, E.ERR_STATEMENT_WINDOW_OVERLAP)
            return
        recon2 = get_success_data(create_response)
        start_response = client.start_reconciliation(
            company["id"], recon2["id"], headers=admin_headers
        )
        validate_error(start_response, E.ERR_STATEMENT_WINDOW_OVERLAP)

    def test_true_adjacency_end_plus_one_day_succeeds(self, client):
        """PRD 3.7: "true adjacency requires starting the day after the
        other's end."

        Design: Difficulty/resource_temporal_overlap/recon_window_closed_interval_overlap_and_adjacency
        """
        reset_clock(client)
        scenario, connection, _r1 = self._setup_completed_recon(client)
        company = scenario["company"]
        admin = scenario["admin"]
        admin_headers = make_company_user_headers(admin["id"])

        # New window starts 2026-09-01 — the day after the existing end.
        create_response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-09-01T00:00:00Z",
                statement_period_end="2026-09-30T00:00:00Z",
                statement_ending_balance_cents=0,
            ),
            headers=admin_headers,
        )
        recon3 = get_success_data(create_response)
        start_response = client.start_reconciliation(
            company["id"], recon3["id"], headers=admin_headers
        )
        started = get_success_data(start_response)
        assert started["recon_status"] == "IN_PROGRESS"


class TestMigrationInFlightLifetimeWindow:
    """Only one in-flight (QUEUED or CONVERTING) migration per company."""

    def _setup_company(self, client):
        plan = create_plus_plan(client)
        company = create_company(client, plan["id"], legal_name="Tau Corp")
        admin = create_primary_admin(client, company["id"])
        accept_user(client, company["id"], admin["id"])
        return company, admin, make_company_user_headers(admin["id"])

    def test_second_migration_while_first_queued_rejected(self, client):
        """PRD 3.9: "Only one migration job may be in flight per company:
        creating a second while one is `QUEUED` or `CONVERTING` is rejected
        with `ERR_MIGRATION_ALREADY_IN_FLIGHT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/migration_in_flight_lifetime_window_overlap
        """
        reset_clock(client)
        company, admin, admin_headers = self._setup_company(client)

        first_response = client.create_migration_job(
            company["id"],
            f.create_migration_job_payload(
                company["id"], source_product="DESKTOP_PRO",
                source_file_size_bytes=1000000, target_list_entries=50000,
            ),
            headers=admin_headers,
        )
        first = get_success_data(first_response)
        assert first["migration_status"] == "QUEUED"

        second_response = client.create_migration_job(
            company["id"],
            f.create_migration_job_payload(
                company["id"], source_product="DESKTOP_PREMIER",
                source_file_size_bytes=2000000, target_list_entries=60000,
            ),
            headers=admin_headers,
        )
        validate_error(second_response, E.ERR_MIGRATION_ALREADY_IN_FLIGHT)

    def test_window_releases_when_first_is_cancelled(self, client):
        """PRD 3.9: "A job still `QUEUED` or `CONVERTING` can be cancelled —
        by the platform or the requesting company user, or automatically when
        the subscription is cancelled."

        Design: Difficulty/resource_temporal_overlap/migration_in_flight_lifetime_window_overlap
        """
        reset_clock(client)
        company, admin, admin_headers = self._setup_company(client)

        first_response = client.create_migration_job(
            company["id"],
            f.create_migration_job_payload(company["id"]),
            headers=admin_headers,
        )
        first = get_success_data(first_response)

        cancel_response = client.cancel_migration_job(
            company["id"], first["id"], headers=admin_headers
        )
        cancelled = get_success_data(cancel_response)
        assert cancelled["migration_status"] == "CANCELLED"

        # The lifetime window is released — a new job may be created.
        second_response = client.create_migration_job(
            company["id"],
            f.create_migration_job_payload(
                company["id"], source_product="DESKTOP_PREMIER",
            ),
            headers=admin_headers,
        )
        second = get_success_data(second_response)
        assert second["migration_status"] == "QUEUED"
