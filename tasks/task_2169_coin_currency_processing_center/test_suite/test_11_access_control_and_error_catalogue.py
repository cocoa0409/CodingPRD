"""Authentication, role authorization, account ownership and the 404 family."""

from test_helpers import (
    ApiErrorId,
    CARRIER_1,
    FED_AGENT_1,
    MANAGER_1,
    TELLER_1,
    create_counterfeit_report_payload,
    create_vault_payload,
    headers_with_unknown_role,
    headers_without_user_id,
    make_carrier_headers,
    make_compliance_headers,
    make_customer_account_holder_headers,
    make_fed_agent_headers,
    make_manager_headers,
    make_teller_headers,
    prepare_cash_letter,
    read_fed_deposit,
    read_account,
    read_session_lots,
    read_ticket,
    setup_bag_with_fit_and_unfit_lots,
    setup_counted_bag,
    setup_intake_ticket,
    setup_processing_center,
    validate_error,
    validate_success,
)

MISSING_IDS = {
    "vault": "00000000-0000-4000-8000-000000000001",
    "customer": "00000000-0000-4000-8000-000000000002",
    "bag": "00000000-0000-4000-8000-000000000003",
    "machine": "00000000-0000-4000-8000-000000000004",
    "session": "00000000-0000-4000-8000-000000000005",
    "report": "00000000-0000-4000-8000-000000000006",
    "claim": "00000000-0000-4000-8000-000000000007",
    "fed_deposit": "00000000-0000-4000-8000-000000000008",
    "coin_order": "00000000-0000-4000-8000-000000000009",
    "lot": "00000000-0000-4000-8000-00000000000a",
}


class TestAuthentication:
    def test_a_request_without_the_user_id_header_is_unauthenticated(self, api):
        """PRD §2.1: "Every request to this API must carry two headers: `X-User-ID`,
        identifying the caller, and `X-User-Role`, naming the caller's role. If either header
        is absent, empty, or blank, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP
        401)."
        PRD §2.6: "1. **Authentication.** Both `X-User-ID` and `X-User-Role` present and
        non-blank — `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/missing_x_user_headers_returns_unauthenticated
        """
        response = api.create_vault(
            create_vault_payload(vault_code="CV-C46", name="Headerless Vault"),
            headers_without_user_id("VaultManager"),
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert response.status_code == 401, (
            f"ERR_UNAUTHENTICATED must be HTTP 401, got {response.status_code}"
        )

    def test_a_role_outside_the_declared_six_is_unauthenticated_not_forbidden(self, api):
        """PRD §2.1: "The same `ERR_UNAUTHENTICATED` rejection applies when `X-User-Role`
        carries a value that is not one of the six roles this system recognises."
        PRD §2.1: "The six roles are `VaultManager`, `VaultTeller`, `ArmoredCarrier`,
        `ComplianceOfficer`, `CustomerAccountHolder`, and `FederalReserveAgent`."
        PRD §2.6: "2. **Role recognition.** `X-User-Role` names one of the six declared roles
        — `ERR_UNAUTHENTICATED` (401)."

        Design: Corner/rbac/unrecognized_role_header_returns_unauthenticated
        """
        response = api.create_vault(
            create_vault_payload(vault_code="CV-C47", name="Bad Role Vault"),
            headers_with_unknown_role("u-nite-1", "NightAuditor"),
        )
        validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value)
        assert response.status_code == 401, (
            f"An unrecognised role is 401, not 403; got {response.status_code}"
        )


class TestRoleAuthorization:
    def test_the_armored_carrier_cannot_verify_the_drop(self, api):
        """PRD §2.1: "When an authenticated caller's role is not listed among the roles
        permitted for the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `VaultTeller` works the floor: verifying drops, extending provisional
        credit, scheduling and running counting sessions, and releasing or taking back coin."
        PRD §4: "| POST | `/cash-vault/deposit-tickets/{id}/verify` | Verify the drop: bag
        count matches the manifest and every bag is physically in the vault. | `VaultTeller` |"

        Design: Corner/rbac/armored_carrier_cannot_verify_a_deposit_ticket
        """
        scenario = setup_intake_ticket(
            bag_specs=[
                {
                    "bag_type": "CURRENCY",
                    "declared_amount_cents": 50_000,
                    "declared_note_count": 50,
                    "declared_coin_weight_grams": 0,
                }
            ]
        )

        response = api.verify_deposit_ticket(
            scenario["ticket"]["id"], make_carrier_headers(CARRIER_1)
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        assert response.status_code == 403

        assert read_ticket(scenario["ticket"]["id"])["status"] == "INTAKE", (
            "A forbidden call must not move the ticket"
        )

    def test_the_vault_teller_cannot_settle_the_ticket(self, api):
        """PRD §2.1: "When an authenticated caller's role is not listed among the roles
        permitted for the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `VaultManager` runs the processing center: vault posture, coin inventory
        positions, deposit holds, settlements, discrepancy-claim decisions, Federal Reserve
        cash letters, and coin-order approvals."
        PRD §4: "| POST | `/cash-vault/deposit-tickets/{id}/settle` | Settle the ticket using
        deposit_credit_amount variant FINAL and reconcile the provisional credit. |
        `VaultManager` |"

        Design: Corner/rbac/vault_teller_cannot_settle_a_deposit_ticket
        """
        scenario = setup_counted_bag(tier="PREMIUM", credit_branch="provisional")
        assert scenario["ticket"]["status"] == "SETTLEMENT_READY"

        response = api.settle_deposit_ticket(
            scenario["ticket"]["id"], make_teller_headers(TELLER_1)
        )
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        assert response.status_code == 403

        ticket = read_ticket(scenario["ticket"]["id"])
        assert ticket["status"] == "SETTLEMENT_READY", (
            f"The ticket must not settle, got {ticket['status']}"
        )
        assert ticket["final_settlement_cents"] == 0
        account = read_account(scenario["account"]["id"])
        assert account["ledger_balance_cents"] == 0, "No funds may be collected"
        assert account["provisional_credit_cents"] == 100_000, (
            "The PREMIUM advance is still outstanding, got "
            f"{account['provisional_credit_cents']}"
        )

    def test_the_federal_reserve_agent_cannot_ship_a_cash_letter(self, api):
        """PRD §2.1: "When an authenticated caller's role is not listed among the roles
        permitted for the endpoint being called, the request is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.1: "A `FederalReserveAgent` is the Federal Reserve counterparty that confirms
        cash letters and posts credit advices."
        PRD §4: "| POST | `/cash-vault/fed-deposits/{id}/submit` | Ship the cash letter to the
        Federal Reserve. | `VaultManager` |"

        Design: Corner/rbac/federal_reserve_agent_cannot_submit_a_cash_letter
        """
        scenario = setup_bag_with_fit_and_unfit_lots()
        fed_deposit = prepare_cash_letter(
            scenario["vault"]["id"],
            [scenario["fit_lot"]["id"]],
            cash_letter_number="CL-C51",
            deposit_date="2026-08-04",
        )

        response = api.submit_fed_deposit(fed_deposit["id"], make_fed_agent_headers(FED_AGENT_1))
        validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE.value)
        assert response.status_code == 403

        assert read_fed_deposit(fed_deposit["id"])["status"] == "PREPARED", (
            "The cash letter must stay PREPARED"
        )
        lot = read_session_lots(scenario["session"]["id"], category="FIT")[0]
        assert lot["status"] == "ATTACHED", (
            f"The attached lot must not move to DEPOSITED, got {lot['status']}"
        )


class TestAccountOwnership:
    def test_an_account_holder_cannot_read_another_depositors_statement(self, api):
        """PRD §2.1: "`CustomerAccountHolder` is different: it is entity-backed. When
        `X-User-Role` is `CustomerAccountHolder`, `X-User-ID` is the `id` of the acting
        `CustomerAccount`, and ownership checks on any resource that references a
        `CustomerAccount` compare that resource's account reference to `X-User-ID`."
        PRD §2.1: "This ownership check guards ten operations: reading one customer account,
        reading a customer statement, reading one deposit ticket, reading one sealed bag,
        filing a discrepancy claim, resubmitting a discrepancy claim, reading one discrepancy
        claim, placing a coin order, reading one coin order, and reading a coin order's lines.
        A mismatch is rejected with `ERR_ACCOUNT_OWNERSHIP` (HTTP 403)."

        Design: Corner/rbac/account_holder_cannot_read_another_customers_statement
        """
        owner_a = setup_processing_center(with_machine=False)["account"]
        owner_b = setup_processing_center(with_machine=False)["account"]

        response = api.get_customer_statement(
            owner_b["id"], make_customer_account_holder_headers(owner_a["id"])
        )
        validate_error(response, ApiErrorId.ERR_ACCOUNT_OWNERSHIP.value)
        assert response.status_code == 403, (
            f"A cross-account read is 403, not 404; got {response.status_code}"
        )

        own_statement = api.get_customer_statement(
            owner_b["id"], make_customer_account_holder_headers(owner_b["id"])
        )
        statement = validate_success(own_statement, 200)
        assert statement["customer_account_id"] == owner_b["id"], (
            "The depositor may read its own statement"
        )


class TestNotFoundCatalogue:
    def test_each_collection_returns_its_own_not_found_error(self, api):
        """PRD §2.5: "The not-found errors are entity-specific: `ERR_VAULT_NOT_FOUND`,
        `ERR_CUSTOMER_NOT_FOUND`, `ERR_TICKET_NOT_FOUND`, `ERR_BAG_NOT_FOUND`,
        `ERR_MACHINE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_LOT_NOT_FOUND`,
        `ERR_REPORT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_FED_DEPOSIT_NOT_FOUND`, and
        `ERR_COIN_ORDER_NOT_FOUND`, all returning HTTP 404."
        PRD §2.5: "This body-reference resolution applies to the creation of deposit tickets,
        sealed bags, counting machines, count sessions, counterfeit reports, discrepancy
        claims, cash letters, and coin orders."

        Design: Corner/errors/not_found_errors_are_entity_specific_across_collections
        """
        manager = make_manager_headers(MANAGER_1)
        checks = [
            (api.get_vault(MISSING_IDS["vault"], manager), ApiErrorId.ERR_VAULT_NOT_FOUND),
            (
                api.get_customer_account(MISSING_IDS["customer"], manager),
                ApiErrorId.ERR_CUSTOMER_NOT_FOUND,
            ),
            (api.get_sealed_bag(MISSING_IDS["bag"], manager), ApiErrorId.ERR_BAG_NOT_FOUND),
            (
                api.get_counting_machine(MISSING_IDS["machine"], manager),
                ApiErrorId.ERR_MACHINE_NOT_FOUND,
            ),
            (
                api.get_count_session(MISSING_IDS["session"], manager),
                ApiErrorId.ERR_SESSION_NOT_FOUND,
            ),
            (
                api.get_counterfeit_report(MISSING_IDS["report"], manager),
                ApiErrorId.ERR_REPORT_NOT_FOUND,
            ),
            (
                api.get_discrepancy_claim(MISSING_IDS["claim"], manager),
                ApiErrorId.ERR_CLAIM_NOT_FOUND,
            ),
            (
                api.get_fed_deposit(MISSING_IDS["fed_deposit"], manager),
                ApiErrorId.ERR_FED_DEPOSIT_NOT_FOUND,
            ),
            (
                api.get_coin_order(MISSING_IDS["coin_order"], manager),
                ApiErrorId.ERR_COIN_ORDER_NOT_FOUND,
            ),
            (
                api.create_counterfeit_report(
                    create_counterfeit_report_payload(MISSING_IDS["lot"], 10_000, 2),
                    make_compliance_headers("u-cmp-1"),
                ),
                ApiErrorId.ERR_LOT_NOT_FOUND,
            ),
        ]

        for response, expected in checks:
            validate_error(response, expected.value)
            assert response.status_code == 404, (
                f"{expected.value} must be HTTP 404, got {response.status_code}"
            )
