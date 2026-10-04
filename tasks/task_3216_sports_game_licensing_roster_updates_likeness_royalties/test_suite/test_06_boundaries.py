"""Difficulty queue A, rule 6: boundary_precision_check — both instances."""
from test_helpers import (
    ADMIN,
    create_active_agreement,
    create_audit_case_payload,
    create_finalized_statement,
    create_royalty_statement_payload,
    create_season_payload,
    set_clock,
    get_success_data,
    validate_error,
    validate_success,
)
from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import create_roster_batch_payload
from test_helpers.test_users import (
    TEST_USERS,
    make_league_auditor_headers,
    make_roster_operator_headers,
    make_union_auditor_headers,
)

LIVEOPS = TEST_USERS["liveops_manager_headers"]
FINANCE = TEST_USERS["finance_controller_headers"]


class TestAuditWindowBoundary:
    def _setup_two_finalized_statements(self, api):
        """Agreement audit_window_days=30; two identical statements finalized at
        clock 2026-09-10. Returns (agreement, statement1, statement2)."""
        agreement = create_active_agreement(audit_window_days=30)
        statements = []
        for _ in range(2):
            stmt = get_success_data(
                api_client.create_royalty_statement(
                    create_royalty_statement_payload(agreement["id"]), FINANCE
                )
            )
            get_success_data(api_client.compute_provisional(stmt["id"], FINANCE))
            statements.append(stmt)
        set_clock("2026-09-10T00:00:00Z")
        for stmt in statements:
            get_success_data(api_client.finalize_statement(stmt["id"], FINANCE))
        return agreement, statements[0], statements[1]

    def test_audit_at_exactly_window_days_after_finalization_allowed(self, api):
        """PRD §3.8: "Opening requires the referenced statement to be FINALIZED
        and the clock date to fall within the agreement's audit_window_days
        after finalization; a missed window is ERR_AUDIT_WINDOW_MISSED."
        PRD §2.4: "Date comparisons throughout this document are inclusive on
        both bounds unless stated otherwise."

        Design: Difficulty/boundary_precision_check/audit_window_boundary_day_exactly_allowed
        """
        agreement, stmt1, _ = self._setup_two_finalized_statements(api)
        set_clock("2026-10-10T00:00:00Z")  # exactly 30 days after 2026-09-10
        case = get_success_data(
            api_client.create_audit_case(
                create_audit_case_payload(agreement["id"], stmt1["id"],
                                          opened_by_role="LEAGUE_AUDITOR"),
                make_league_auditor_headers("league-aud-1"),
            ),
            expected_status=201,
        )
        assert case["audit_status"] == "OPEN"
        stmt_after = get_success_data(api_client.get_royalty_statement(stmt1["id"], FINANCE))
        assert stmt_after["statement_status"] == "DISPUTED"

    def test_audit_one_day_past_window_rejected(self, api):
        """PRD §3.8: "Opening requires the referenced statement to be FINALIZED
        and the clock date to fall within the agreement's audit_window_days
        after finalization; a missed window is ERR_AUDIT_WINDOW_MISSED."

        Design: Difficulty/boundary_precision_check/audit_window_boundary_day_exactly_allowed
        """
        agreement, _, stmt2 = self._setup_two_finalized_statements(api)
        set_clock("2026-10-11T00:00:00Z")  # 31 days after finalization
        resp = api_client.create_audit_case(
            create_audit_case_payload(agreement["id"], stmt2["id"],
                                      opened_by_role="UNION_AUDITOR"),
            make_union_auditor_headers("union-aud-1"),
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_WINDOW_MISSED.value)


class TestEmptyRosterBatchRejected:
    def test_validate_rejects_zero_entries(self, api):
        """PRD §3.3: "Validation moves the batch from DRAFT to VALIDATED; it
        requires at least one entry (an empty batch is ERR_EMPTY_BATCH)."

        Design: Difficulty/boundary_precision_check/empty_roster_batch_rejected_at_validate
        """
        agreement = create_active_agreement()
        season = get_success_data(
            api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
        )
        batch = get_success_data(
            api_client.create_roster_batch(
                create_roster_batch_payload(season["id"], batch_label="EMPTY"),
                make_roster_operator_headers("op-1"),
            )
        )
        resp = api_client.validate_roster_batch(
            batch["id"], make_roster_operator_headers("op-1")
        )
        validate_error(resp, ApiErrorId.ERR_EMPTY_BATCH.value)

    def test_batch_remains_draft_after_empty_rejection(self, api):
        """PRD §3.3: "A RosterOperator creates a RosterBatch under a season with
        a batch_label such as WEEK_05_UPDATE and the operator's own id recorded
        in submitted_by; the batch starts in DRAFT."

        Design: Difficulty/boundary_precision_check/empty_roster_batch_rejected_at_validate
        """
        agreement = create_active_agreement()
        season = get_success_data(
            api_client.create_season(create_season_payload(agreement["id"]), LIVEOPS)
        )
        batch = get_success_data(
            api_client.create_roster_batch(
                create_roster_batch_payload(season["id"], batch_label="EMPTY"),
                make_roster_operator_headers("op-1"),
            )
        )
        api_client.validate_roster_batch(batch["id"], make_roster_operator_headers("op-1"))
        batch_after = get_success_data(
            api_client.get_roster_batch(batch["id"], make_roster_operator_headers("op-1"))
        )
        assert batch_after["batch_status"] == "DRAFT", (
            f"a rejected validate must not advance the batch; "
            f"got {batch_after['batch_status']}"
        )
