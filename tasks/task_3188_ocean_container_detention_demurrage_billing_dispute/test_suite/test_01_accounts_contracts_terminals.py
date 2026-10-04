"""Onboarding, defaults, uniqueness, and shape tests: accounts, contracts, terminals."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_account,
    create_account_payload,
    create_active_contract,
    create_contract,
    create_terminal,
    get_success_data,
    make_contract_manager_headers,
    make_customer_rep_headers,
    validate_error,
    validate_success,
)


class TestCustomerAccountCreation:
    def test_account_creation_defaults_applied(self):
        """PRD §3.1: "The account is born `ACTIVE` with `credit_hold` false and
        `outstanding_balance_cents` at zero; both the flag and the balance are
        system-managed thereafter."

        Design: Corner/entities/customer_account_creation_defaults_applied
        """
        resp = api_client.create_customer_account(
            create_account_payload(account_code="ACCT-D1", legal_name="Defaults Co"),
            make_contract_manager_headers("cm-1"),
        )
        data = validate_success(resp, 201)
        assert data["status"] == "ACTIVE"
        assert data["credit_hold"] is False
        assert data["outstanding_balance_cents"] == 0
        assert data["version"] == 1

    def test_duplicate_account_code_rejected(self):
        """PRD §3.1: "The `account_code` is unique across all accounts — a
        duplicate is rejected with `ERR_CAPACITY_OR_CONFLICT`."

        Design: Corner/entities/customer_account_duplicate_account_code_rejected
        """
        create_account(account_code="ACCT-DUP", legal_name="First")
        resp = api_client.create_customer_account(
            create_account_payload(account_code="ACCT-DUP", legal_name="Second"),
            make_contract_manager_headers("cm-1"),
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_OR_CONFLICT)


class TestServiceContractRules:
    def test_free_days_range_enforced(self):
        """PRD §3.1: "two free-time allowances — `demurrage_free_days` and
        `detention_free_days`, each an integer from 0 to 30 inclusive".

        Design: Corner/entities/service_contract_free_days_range_enforced
        """
        account = create_account(account_code="ACCT-R1", legal_name="Range Co")
        bad = api_client.create_service_contract(
            account["id"],
            {
                "contract_ref": "CTR-R1-BAD",
                "demurrage_free_days": 31,
                "detention_free_days": 5,
                "demurrage_rate_schedule": "STANDARD",
                "detention_rate_schedule": "STANDARD",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
            make_contract_manager_headers("cm-1"),
        )
        validate_error(bad, ApiErrorId.ERR_INVALID_REQUEST)

        ok = api_client.create_service_contract(
            account["id"],
            {
                "contract_ref": "CTR-R1-OK",
                "demurrage_free_days": 30,
                "detention_free_days": 5,
                "demurrage_rate_schedule": "STANDARD",
                "detention_rate_schedule": "STANDARD",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": "2026-12-31T00:00:00Z",
            },
            make_contract_manager_headers("cm-1"),
        )
        data = validate_success(ok, 201)
        assert data["demurrage_free_days"] == 30

    def test_inverted_window_rejected_but_single_day_window_legal(self):
        """PRD §3.1: "a coverage window bounded by `effective_from` and
        `effective_to`, both inclusive UTC calendar dates with the end no
        earlier than the start."

        Design: Difficulty/resource_temporal_overlap/contract_effective_window_overlap_blocks_double_coverage
        """
        account = create_account(account_code="ACCT-P", legal_name="Palm Exports")
        inverted = api_client.create_service_contract(
            account["id"],
            {
                "contract_ref": "CTR-P-BAD",
                "demurrage_free_days": 2,
                "detention_free_days": 5,
                "demurrage_rate_schedule": "STANDARD",
                "detention_rate_schedule": "STANDARD",
                "effective_from": "2026-10-01T00:00:00Z",
                "effective_to": "2026-09-01T00:00:00Z",
            },
            make_contract_manager_headers("cm-1"),
        )
        validate_error(inverted, ApiErrorId.ERR_INVALID_REQUEST)

        one_day = api_client.create_service_contract(
            account["id"],
            {
                "contract_ref": "CTR-P-1DAY",
                "demurrage_free_days": 2,
                "detention_free_days": 5,
                "demurrage_rate_schedule": "STANDARD",
                "detention_rate_schedule": "STANDARD",
                "effective_from": "2026-09-01T00:00:00Z",
                "effective_to": "2026-09-01T00:00:00Z",
            },
            make_contract_manager_headers("cm-1"),
        )
        created = validate_success(one_day, 201)
        activated = api_client.activate_service_contract(
            created["id"], make_contract_manager_headers("cm-1")
        )
        data = validate_success(activated, 200)
        assert data["status"] == "ACTIVE"

    def test_single_day_contract_activation_rejected_after_window_closes(self):
        """PRD §3.1: "Activation is permitted only when the current
        logical-clock date falls within the contract's effective window — a date
        before `effective_from` or after `effective_to` is rejected with
        `ERR_CONTRACT_NOT_IN_EFFECT`".

        Design: Difficulty/resource_temporal_overlap/contract_effective_window_overlap_blocks_double_coverage
        """
        from test_helpers import set_clock

        account = create_account(account_code="ACCT-P2", legal_name="Palm Exports II")
        contract = create_contract(
            account["id"],
            contract_ref="CTR-P2-1DAY",
            demurrage_free_days=2,
            detention_free_days=5,
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-09-01T00:00:00Z",
        )
        set_clock("2026-09-02T00:00:00Z", make_contract_manager_headers("cm-1"))
        resp = api_client.activate_service_contract(
            contract["id"], make_contract_manager_headers("cm-1")
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_IN_EFFECT)

    def test_contract_expires_when_clock_passes_effective_to(self):
        """PRD §3.1: "Thereafter, when the logical clock advances past
        `effective_to`, the contract transitions automatically to `EXPIRED`."

        Design: Corner/state_machines/system_transition_contract_expires_past_effective_to
        """
        from test_helpers import set_clock

        account = create_account(account_code="ACCT-EX", legal_name="Expiry Co")
        contract = create_active_contract(
            account["id"],
            contract_ref="CTR-EX",
            effective_from="2026-09-01T00:00:00Z",
            effective_to="2026-09-10T00:00:00Z",
        )
        set_clock("2026-09-11T00:00:00Z", make_contract_manager_headers("cm-1"))
        resp = api_client.get_service_contract(
            contract["id"], make_contract_manager_headers("cm-1")
        )
        data = validate_success(resp)
        assert data["status"] == "EXPIRED"


class TestTerminalHolidayShape:
    def test_holiday_carries_no_version_or_updated_at(self):
        """PRD §2.5: "`TerminalHoliday`, `ChargeAccrual`, and `Payment` carry
        only `id` and `created_at`; both `updated_at` and `version` are absent
        from these entities."

        Design: Corner/entities/terminal_holiday_immutable_no_version_field
        """
        terminal = create_terminal(terminal_code="OAK", gate_closed_weekends=True)
        resp = api_client.create_terminal_holiday(
            terminal["id"],
            {"holiday_date": "2026-09-07T00:00:00Z", "name": "Labor Day"},
            # TerminalOperator
            {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"},
        )
        data = validate_success(resp, 201)
        assert data.get("id"), "holiday must carry id"
        assert data.get("created_at"), "holiday must carry created_at"
        assert "version" not in data
        assert "updated_at" not in data
