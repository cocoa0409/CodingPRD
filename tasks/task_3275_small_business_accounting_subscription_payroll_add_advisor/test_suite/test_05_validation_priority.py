"""Validation priority conflicts — pairs of error categories where one
must surface ahead of the other.

PRD 2.9 fixes a deterministic validation order: state-machine legality
(ERR_INVALID_STATE_TRANSITION) is checked before the seat-limit fiscal check
(ERR_SEAT_LIMIT_REACHED), and referential checks (statement window overlap)
come before temporal checks (window expiry).
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
    complete_recon,
    create_company,
    create_company_user,
    create_essentials_plan,
    create_plus_plan,
    create_primary_admin,
    create_simple_start_plan,
    reset_clock,
    set_clock,
    setup_company_with_active_subscription,
)
from test_helpers.test_users import (
    PLATFORM_ADMIN,
    make_company_user_headers,
)


class TestStateBeatsBusinessFiscal:
    """An INVALID_STATE_TRANSITION (priority 6) wins over a SEAT_LIMIT
    (priority 14) when both would fire on the same request."""

    def test_second_accept_on_active_user_yields_invalid_state_not_seat_limit(self, client):
        """PRD 2.9: "State-machine legality (`ERR_INVALID_STATE_TRANSITION`)
        is checked next, then the subscription writability gate
        (`ERR_SUBSCRIPTION_NOT_WRITABLE`), then feature gating
        (`ERR_FEATURE_NOT_IN_TIER`), then segregation of duties
        (`ERR_REQUIRES_PRIMARY_ADMIN`). Business-referential checks — ...
        come before uniqueness (`ERR_DUPLICATE`) and enum-domain checks
        (`ERR_INVALID_ENUM`). Fiscal checks follow: the seat limit
        (`ERR_SEAT_LIMIT_REACHED`) and billing-state blocks
        (`ERR_BILLING_STATE_BLOCKED`)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_seat_limit_priority
        """
        reset_clock(client)
        plan = create_simple_start_plan(client)  # max_seats=1
        company = create_company(client, plan["id"], legal_name="Lambda Corp")
        admin = create_primary_admin(client, company["id"])
        accept_user(client, company["id"], admin["id"])
        # admin is ACTIVE; occupied=1 == max_seats.
        # A second accept on the same (already ACTIVE) admin would violate the
        # state machine (INVITED -> ACTIVE only).  It also would violate the
        # seat limit if state passed.  State must win.
        response = client.accept_company_user(
            company["id"], admin["id"],
            headers=make_company_user_headers(admin["id"]),
        )
        validate_error(response, E.ERR_INVALID_STATE_TRANSITION)
        err_body = response.json()["data"]
        assert err_body["error_id"] != E.ERR_SEAT_LIMIT_REACHED, (
            "seat-limit is a fiscal check and must NOT preempt the earlier "
            "state-machine legality check"
        )

    def test_seat_limit_alone_fires_when_state_is_clean(self, client):
        """PRD 3.2: "The seat check counts users of the company in `INVITED`
        or `ACTIVE` status — `DISABLED` users do not occupy seats — and
        rejects the invite or acceptance when adding one more would take the
        occupied count strictly above `max_seats`; at exactly `max_seats` the
        add still succeeds. The rejection is `ERR_SEAT_LIMIT_REACHED` (HTTP
        400)."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_fiscal_seat_limit_priority
        """
        reset_clock(client)
        plan = create_simple_start_plan(client)  # max_seats=1
        company = create_company(client, plan["id"], legal_name="Lambda2 Corp")
        admin = create_primary_admin(client, company["id"])
        accept_user(client, company["id"], admin["id"])
        # occupied=1; inviting a second user (INVITED) breaches max_seats.
        response = client.create_company_user(
            company["id"],
            f.create_company_user_payload(company["id"], email="u2@l.example"),
            headers=make_company_user_headers(admin["id"]),
        )
        validate_error(response, E.ERR_SEAT_LIMIT_REACHED)


class TestBusinessReferentialBeatsTemporal:
    """ERR_STATEMENT_WINDOW_OVERLAP (priority 10) wins over temporal checks
    (priority 16) when the same payload is bad on both."""

    def _setup_completed_recon(self, client):
        plan = create_plus_plan(client)
        scenario = setup_company_with_active_subscription(
            client, plan_id=plan["id"], legal_name="Mu Corp"
        )
        company = scenario["company"]
        admin = scenario["admin"]
        connection = add_bank_connection(
            client, company["id"], admin["id"],
            institution_name="BofA", external_account_mask="7777",
        )
        # Existing COMPLETED recon [2026-08-01, 2026-08-31].
        recon = complete_recon(
            client, company["id"], admin["id"], connection["id"],
            statement_period_start="2026-08-01T00:00:00Z",
            statement_period_end="2026-08-31T00:00:00Z",
            statement_ending_balance_cents=0,
        )
        return scenario, connection, recon

    def test_overlap_wins_over_malformed_window(self, client):
        """PRD 2.9: "Business-referential checks — reconciliation window
        overlap (`ERR_STATEMENT_WINDOW_OVERLAP`) and the single-in-flight
        migration rule (`ERR_MIGRATION_ALREADY_IN_FLIGHT`) — come before
        uniqueness (`ERR_DUPLICATE`) and enum-domain checks
        (`ERR_INVALID_ENUM`). Fiscal checks follow: ... Temporal checks —
        window expiry (`ERR_WINDOW_EXPIRED`) and bank consent
        (`ERR_CONSENT_EXPIRED`) — are next."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_recon_overlap
        """
        reset_clock(client)
        scenario, connection, _recon = self._setup_completed_recon(client)
        company = scenario["company"]
        admin = scenario["admin"]

        # Window [2026-08-15, 2026-08-10]: both overlaps the COMPLETED window
        # AND has end < start (temporal inversion).  Referential must surface.
        response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-08-15T00:00:00Z",
                statement_period_end="2026-08-10T00:00:00Z",
                statement_ending_balance_cents=0,
            ),
            headers=make_company_user_headers(admin["id"]),
        )
        validate_error(response, E.ERR_STATEMENT_WINDOW_OVERLAP)

    def test_overlap_alone_also_surfaces_referential_error(self, client):
        """PRD 3.7: "the statement window must not intersect any existing
        `IN_PROGRESS` or `COMPLETED` reconciliation for the same bank
        connection. Because both ends of every window are closed, adjacency
        counts as overlap — a window whose start equals another window's end
        collides; true adjacency requires starting the day after the other's
        end. Violations are rejected with `ERR_STATEMENT_WINDOW_OVERLAP`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_temporal_recon_overlap
        """
        reset_clock(client)
        scenario, connection, _recon = self._setup_completed_recon(client)
        company = scenario["company"]
        admin = scenario["admin"]

        # Well-formed window that overlaps [2026-08-01, 2026-08-31].
        response = client.create_reconciliation(
            company["id"],
            f.create_reconciliation_payload(
                company["id"], connection["id"],
                statement_period_start="2026-08-15T00:00:00Z",
                statement_period_end="2026-09-15T00:00:00Z",
                statement_ending_balance_cents=0,
            ),
            headers=make_company_user_headers(admin["id"]),
        )
        validate_error(response, E.ERR_STATEMENT_WINDOW_OVERLAP)
