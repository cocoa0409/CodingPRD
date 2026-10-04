"""Firm registration defaults, account creation, model cycles and remaining corners."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    NON_EXISTENT_UUID,
    setup_second_firm,
    setup_firm_with_agreement,
    setup_household,
    open_account,
    create_pending_account,
    refetch_firm,
    refetch_account,
    refetch_household,
    refetch_model,
    setup_clock,
    setup_model_cycle_scenario,
    setup_configured_system,
    setup_approved_model,
    credit_lot_position,
    refetch_transfer,
)
"""Firm registration defaults, account creation, model cycles and remaining corners."""
"""Firm registration defaults, account creation, model cycles and remaining corners."""

ADVISOR = TEST_USERS["advisor_ops_headers"]
CUSTODY = TEST_USERS["custody_officer_headers"]
ADMIN = TEST_USERS["admin_headers"]
CHAIR = TEST_USERS["committee_chair_headers"]


class TestFirmRegistration:

    def test_a_newly_registered_firm_is_born_suspended(self):
        """PRD §3.1: "The registration response is a `201 Created` carrying the firm,
        whose `custody_agreement_status` begins at `PENDING`, whose
        `entitlement_count` begins at 0, and whose `household_fee_basis_total_cents`
        begins at 0."
        PRD §3.1: "Because the firm has no executed agreement at this point, the
        posture derivation of §2.4 lands on rule 1 and the firm is born `SUSPENDED`
        with `posture_reason_code` `CUSTODY_AGREEMENT_NOT_EXECUTED`."

        Design: Corner/entities/firm_create_is_posture_suspended_until_agreement_executes
        """
        setup_clock()
        firm = validate_success(api_client.create_firm(
            {"legal_name": "Bay Meridian Wealth Advisors", "crd_number": "CRD-118044",
             "home_state_code": "CA"},
            ADMIN,
        ), 201)
        assert firm["legal_name"] == "Bay Meridian Wealth Advisors"
        assert firm["crd_number"] == "CRD-118044"
        assert firm["home_state_code"] == "CA"
        assert firm["custody_agreement_status"] == "PENDING"
        assert firm["firm_posture"] == "SUSPENDED"
        assert firm["posture_reason_code"] == "CUSTODY_AGREEMENT_NOT_EXECUTED"
        assert firm["entitlement_count"] == 0
        assert firm["household_fee_basis_total_cents"] == 0
        assert firm["supervision_evidence_status"] == "UNKNOWN"

    def test_an_onboarded_firm_reads_back_its_recomputed_fields(self):
        """PRD §2.8: "`household_fee_basis_total_cents` on the firm is the sum of
        `household_fee_basis_cents` across every household of the firm, and it is the
        firm-level mirror of the household-level basis."
        PRD §3.1: "the firm's own `custody_agreement_status` is set to `EXECUTED` with
        `agreement_executed_at` stamped to the same instant."

        Design: Corner/entities/firm_get_round_trips_derived_fields_after_full_onboarding
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-110001")
        credit_lot_position(account["id"], firm["id"])

        refreshed = refetch_firm(firm["id"])
        assert refreshed["custody_agreement_status"] == "EXECUTED"
        assert refreshed["agreement_executed_at"] is not None
        assert refreshed["firm_posture"] == "OPEN"
        assert refreshed["posture_reason_code"] is None
        assert refreshed["entitlement_count"] == 1
        assert refreshed["household_fee_basis_total_cents"] == 100_000_000
        assert refreshed["supervision_evidence_status"] == "UNKNOWN"

    def test_the_firm_list_paginates_with_the_default_window(self):
        """PRD §2.3: "`limit` caps the number of items returned; it defaults to 10,
        and the platform accepts no value below 1 or above 100. `offset` skips a
        number of items from the front of the result set; it defaults to 0."
        PRD §2.3: "`has_more` is true exactly when further rows remain beyond the
        current page."

        Design: Corner/entities/firm_list_paginates_and_filters_by_posture
        """
        setup_clock()
        firm_one, agreement = setup_firm_with_agreement()
        firm_two = setup_second_firm()

        data, meta = validate_paginated(api_client.list_firms(ADMIN))
        assert len(data) == 2
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 2
        assert meta["has_more"] is False

        filtered = validate_success(
            api_client.list_firms(ADMIN, params={"firm_posture": "SUSPENDED"}), 200
        )
        assert len(filtered) == 1
        assert filtered[0]["id"] == firm_two["id"]

    def test_an_unknown_firm_id_reports_the_firm_specific_error(self):
        """PRD §2.9: "A path or body reference that names an `AdvisorFirm` which does
        not exist yields `ERR_FIRM_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/firm_get_with_unknown_id_returns_firm_not_found
        """
        setup_clock()
        res = api_client.get_firm(NON_EXISTENT_UUID, ADMIN)
        error = validate_error(res, "ERR_FIRM_NOT_FOUND", expected_status=404)
        assert len(error["message"].strip()) > 0

    def test_client_supplied_system_fields_do_not_replace_the_server_identity(self):
        """PRD §2.8: "`id` — a unique, server-minted identifier for the resource. It
        is a UUID. It carries no type prefix and no entity-name segment; two resources
        of different entities are distinguished by which collection the client asked
        for, never by the shape of the identifier."

        Design: Corner/entities/system_fields_are_ignored_when_supplied_by_client
        """
        setup_clock()
        firm = validate_success(api_client.create_firm(
            {"legal_name": "Ignored System Fields Advisors", "crd_number": "CRD-909090",
             "home_state_code": "NV"},
            ADMIN,
        ), 201)
        assert isinstance(firm["id"], str)
        assert len(firm["id"]) == 36
        assert firm["id"].count("-") == 4
        assert "CRD-909090" not in firm["id"]

        reread = validate_success(api_client.get_firm(firm["id"], ADMIN), 200)
        assert reread["id"] == firm["id"]


class TestAccountCreation:

    def test_omitting_a_named_input_field_fails_account_creation(self):
        """PRD §3.3: "The creating `AdvisorOperationsLead` supplies the
        `household_id`, the servicing `firm_id`, an `account_number`, an
        `account_type` and the client's `householding_consent`."

        Design: Corner/entities/account_create_requires_all_input_fields
        """
        firm, agreement = setup_firm_with_agreement()
        household = setup_household(firm["id"])

        res = api_client.create_account(
            {"household_id": household["id"], "firm_id": firm["id"],
             "account_number": "RIA-111001", "householding_consent": "OP_IN"},
            ADVISOR,
        )
        assert res.status_code >= 400, "account_type is a named input and must be required"
        assert res.json().get("response_type") == "error"

    def test_a_complete_payload_creates_a_pending_account(self):
        """PRD §3.3: "A new account begins at `account_status` `PENDING`".
        PRD §3.3: "Its `model_portfolio_id` is null until a model is assigned".

        Design: Corner/entities/account_create_requires_all_input_fields
        """
        firm, agreement = setup_firm_with_agreement()
        household = setup_household(firm["id"])
        account = validate_success(api_client.create_account(
            {"household_id": household["id"], "firm_id": firm["id"],
             "account_number": "RIA-111002", "account_type": "INDIVIDUAL",
             "householding_consent": "OP_IN"},
            ADVISOR,
        ), 201)
        assert account["account_number"] == "RIA-111002"
        assert account["account_status"] == "PENDING"
        assert account["model_portfolio_id"] is None

        rows = validate_success(
            api_client.list_accounts(ADVISOR, params={"household_id": household["id"]}), 200
        )
        assert len(rows) == 1

    def test_the_fee_basis_takes_the_greater_of_value_and_cost(self):
        """PRD §3.3: "The account's `market_value_cents` is the sum over the lots
        applied to it of the quantity at the valuation price, divided by ten billion."
        PRD §3.6: "The traditional basis is the sum over the account's positions of
        the greater of that position's market value and its cost basis, rounded half
        up."

        Design: Corner/entities/account_computed_fee_basis_results_from_lot_values
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-110001")
        credit_lot_position(
            account["id"], firm["id"], quantity_micros=4_000_000_000,
            valuation_price_micros=250_000_000, sent_cost_basis_cents=160_000_000,
        )

        billed = refetch_account(account["id"])
        assert billed["market_value_cents"] == 100_000_000
        assert billed["account_fee_basis_cents"] == 160_000_000
        assert billed["billable"] is True
        assert refetch_household(household["id"])["household_fee_basis_cents"] == 160_000_000

    def test_an_entity_account_is_never_billable_and_starts_unbilled(self):
        """PRD §2.6: "An account's `billable` flag is derived from `account_type` — it
        is true when the type is `INDIVIDUAL`, `JOINT`, `TRUST`, `IRA`, `ROTH_IRA` …
        and false for `ENTITY` accounts, which are custody-only and never billable."
        PRD §2.8: "`billed_period_count` on an account counts the settled billing
        periods in which the account was included in a fee basis."

        Design: Corner/entities/entity_creation_defaults_and_non_billable_entity_account
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("BILLING",))
        household = setup_household(firm["id"])
        normal = open_account(household["id"], firm["id"], "RIA-112001")
        entity = open_account(
            household["id"], firm["id"], "RIA-112002",
            account_type="ENTITY", householding_consent="NONE",
        )
        config = setup_configured_system("WARN")
        assert config["config_key"] == "CUSTODY_PLATFORM_DEFAULTS"
        assert config["database_invariant_enforcement"] == "WARN"
        assert config["platform_fee_enabled"] is True

        assert refetch_account(normal["id"])["billed_period_count"] == 0
        assert refetch_account(entity["id"])["billable"] is False
        assert refetch_household(household["id"])["household_fee_basis_cents"] == 0


class TestModelApprovalCycle:

    def test_the_approval_cycle_bumps_the_round_counter(self):
        """PRD §3.4: "Because rebalancing returns a model to `APPROVED` through the
        same path, each traversal of the loop bumps the round counter, so a model that
        has been approved, rebalanced and approved again is observably on round 2."

        Design: Difficulty/non_linear_state_machine/model_portfolio_approval_cycle_bumps_round
        """
        firm, agreement, household, account, model = setup_model_cycle_scenario()
        first = validate_success(
            api_client.approve_model(model["id"], {}, CHAIR, row=refetch_model(model["id"])), 200
        )
        assert first["model_status"] == "APPROVED"
        round_1 = first["approval_round_number"]

        current = refetch_model(model["id"])
        validate_success(api_client.rebalance_model(
            model["id"], {"expected_model_portfolio_version": current["version"]}, ADVISOR, row=current), 200)
        assert refetch_model(model["id"])["model_status"] == "REBALANCING"

        second = validate_success(api_client.approve_model(model["id"], {}, CHAIR, row=refetch_model(model["id"])), 200)
        assert second["model_status"] == "APPROVED"
        assert second["approval_round_number"] == round_1 + 1
        assert refetch_model(model["id"])["approval_round_number"] == 2

    def test_the_rebalancing_edge_is_also_reachable_from_active(self):
        """PRD §3.4: "Rebalancing is available from both `APPROVED` and `ACTIVE`".
        PRD §3.4: "On success the model becomes `ACTIVE`, every account of the firm
        assigned to this model that is still `PENDING` is opened".

        Design: Difficulty/non_linear_state_machine/model_portfolio_approval_cycle_bumps_round
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("MODEL_MANAGEMENT", "TRADING_AUTHORIZATION"))
        household = setup_household(firm["id"])
        pending = create_pending_account(household["id"], firm["id"], "RIA-700002")
        model = setup_approved_model(firm["id"], targets=(("VTI", 10000),))
        validate_success(api_client.set_account_model(
            pending["id"], {"model_portfolio_id": model["id"]}, ADVISOR,
            row=refetch_account(pending["id"]),
        ), 200)

        activated = validate_success(api_client.activate_model(model["id"], {}, CHAIR, row=refetch_model(model["id"])), 200)
        assert activated["model_status"] == "ACTIVE"
        assert refetch_account(pending["id"])["account_status"] == "OPEN"

        current = refetch_model(model["id"])
        rebalanced = validate_success(api_client.rebalance_model(
            model["id"], {"expected_model_portfolio_version": current["version"]}, ADVISOR, row=current), 200)
        assert rebalanced["model_status"] == "REBALANCING"


class TestAccountActivationGates:

    def test_activation_is_refused_while_the_entitlement_is_only_requested(self):
        """PRD §3.3: "A `CustodyOperationsOfficer` moves a `PENDING` account to `OPEN`
        when the firm's posture is `OPEN` or `LIMITED`, when the firm holds an executed
        agreement, and when at least one of the firm's entitlements with code
        `TRADING_AUTHORIZATION` or `BILLING` is `GRANTED`. If the firm holds
        entitlements but the one that applies is not granted, the refusal is
        `ERR_ENTITLEMENT_NOT_GRANTED`."

        Design: Difficulty/cross_entity_state_dependency/account_activation_requires_firm_entitlement_and_current_agreement
        """
        firm, agreement = setup_firm_with_agreement()
        household = setup_household(firm["id"])
        account = create_pending_account(household["id"], firm["id"], "RIA-105001")
        validate_success(api_client.create_entitlement(
            {"firm_id": firm["id"], "entitlement_code": "TRADING_AUTHORIZATION",
             "requested_custody_agreement_id": agreement["id"]},
            ADVISOR,
        ), 201)

        res = api_client.activate_account(account["id"], {}, CUSTODY, row=account)
        validate_error(res, "ERR_ENTITLEMENT_NOT_GRANTED", expected_status=403)
        assert refetch_account(account["id"])["account_status"] == "PENDING"

    def test_granting_the_entitlement_lets_the_same_activation_succeed(self):
        """PRD §3.2: "On success `effective_from` is stamped with the current instant,
        the derived `payload_integrity_verified` becomes true, and the firm's
        `entitlement_count` increases by one."
        PRD §3.3: "A newly opened account triggers the owning household to recompute
        `household_fee_basis_cents`."

        Design: Difficulty/cross_entity_state_dependency/account_activation_requires_firm_entitlement_and_current_agreement
        """
        firm, agreement = setup_firm_with_agreement()
        household = setup_household(firm["id"])
        account = create_pending_account(household["id"], firm["id"], "RIA-105002")
        requested = validate_success(api_client.create_entitlement(
            {"firm_id": firm["id"], "entitlement_code": "TRADING_AUTHORIZATION",
             "requested_custody_agreement_id": agreement["id"]},
            ADVISOR,
        ), 201)

        granted = validate_success(api_client.grant_entitlement(requested["id"], {}, CUSTODY, row=requested), 200)
        assert granted["entitlement_status"] == "GRANTED"
        assert granted["effective_from"] is not None
        assert granted["payload_integrity_verified"] is True

        opened = validate_success(api_client.activate_account(account["id"], {}, CUSTODY, row=account), 200)
        assert opened["account_status"] == "OPEN"
        assert granted["entitlement_status"] == "GRANTED"


class TestCornerCalculations:

    def test_a_zero_quantity_lot_still_participates_in_grading(self):
        """PRD §3.3: "Lots are graded regardless of size, including `quantity_micros`
        of 0, which contributes nothing to the carried total but still participates in
        grading; a rejected transfer contributes nothing at all and its lots are
        discarded."
        PRD §3.3: "`cost_basis_complete` is true exactly when every received position
        was stamped with a `HIGH`-confidence basis."

        Design: Corner/calculations/chronological_carryover_grades_are_position_independent
        """
        firm, agreement = setup_firm_with_agreement(entitlement_codes=("TRADING_AUTHORIZATION",))
        household = setup_household(firm["id"])
        account = open_account(household["id"], firm["id"], "RIA-500001")

        transfer = validate_success(api_client.create_asset_transfer(
            {"receiving_account_id": account["id"], "firm_id": firm["id"],
             "delivering_firm_name": "Prior Custodian LLC", "method": "ACAT"},
            ADVISOR,
        ), 201)
        for spec in (
            {"symbol": "BND", "quantity_micros": 2_000_000_000, "sent_cost_basis_cents": 2_400_000,
             "lot_inventory_date": "2027-01-02T00:00:00Z", "valuation_price_micros": 90_000_000},
            {"symbol": "VTI", "quantity_micros": 4_000_000_000, "sent_cost_basis_cents": 1_200_000,
             "lot_inventory_date": "2020-01-02T00:00:00Z", "valuation_price_micros": 250_000_000},
            {"symbol": "AAAU", "quantity_micros": 0, "sent_cost_basis_cents": 500,
             "lot_inventory_date": "2020-01-03T00:00:00Z", "valuation_price_micros": 1_000_000_000},
        ):
            validate_success(api_client.create_transfer_lot(transfer["id"], spec, ADVISOR), 201)
        validate_success(api_client.transfer_out(transfer["id"], {}, ADVISOR, row=transfer), 200)
        credited = validate_success(api_client.mark_received(transfer["id"], {}, CUSTODY, row=refetch_transfer(transfer["id"])), 200)

        assert credited["carryover_cents"] == 1_200_500
        assert credited["cost_basis_complete"] is False

        lots = {
            lot["symbol"]: lot
            for lot in validate_success(
                api_client.list_transfer_lots(transfer["id"], ADVISOR), 200
            )
        }
        assert len(lots) == 3
        assert lots["AAAU"]["basis_confidence_grade"] == "HIGH"
        assert lots["VTI"]["basis_confidence_grade"] == "HIGH"
        assert lots["BND"]["basis_confidence_grade"] == "MEDIUM"


class TestModelWeightTotals:

    def test_a_weight_total_short_of_ten_thousand_is_refused(self):
        """PRD §3.4: "The invariant that governs the whole model is that the target
        weights must sum to exactly 10000 basis points at approval time; any operation
        that checks it — adding or replacing a target line, or approving the model — is
        refused with `ERR_MODEL_WEIGHTS_INVALID` (HTTP 422) when the sum differs from
        10000 by any amount."

        Design: Corner/validations/model_weights_must_total_exactly_ten_thousand_bps
        """
        firm, agreement = setup_firm_with_agreement(
            entitlement_codes=("MODEL_MANAGEMENT", "TRADING_AUTHORIZATION")
        )
        model = validate_success(api_client.create_model(
            {"firm_id": firm["id"], "model_name": "Laddered Municipals"}, ADVISOR,
        ), 201)
        validate_success(api_client.create_model_target(
            model["id"], {"symbol": "VTI", "target_weight_bps": 9999}, ADVISOR,
        ), 201)

        res = api_client.approve_model(model["id"], {}, CHAIR, row=refetch_model(model["id"]))
        validate_error(res, "ERR_MODEL_WEIGHTS_INVALID", expected_status=422)
        assert refetch_model(model["id"])["model_status"] == "DRAFT"

    def test_reaching_exactly_ten_thousand_admits_the_approval(self):
        """PRD §3.4: "On success `model_status` becomes `APPROVED`, `drift_approved_at`
        is stamped, and `approval_round_number` increases by one."

        Design: Corner/validations/model_weights_must_total_exactly_ten_thousand_bps
        """
        firm, agreement = setup_firm_with_agreement(
            entitlement_codes=("MODEL_MANAGEMENT", "TRADING_AUTHORIZATION")
        )
        model = validate_success(api_client.create_model(
            {"firm_id": firm["id"], "model_name": "Laddered Municipals"}, ADVISOR,
        ), 201)
        validate_success(api_client.create_model_target(
            model["id"], {"symbol": "VTI", "target_weight_bps": 9999}, ADVISOR,
        ), 201)
        validate_success(api_client.create_model_target(
            model["id"], {"symbol": "BND", "target_weight_bps": 1}, ADVISOR,
        ), 201)

        approved = validate_success(api_client.approve_model(model["id"], {}, CHAIR, row=refetch_model(model["id"])), 200)
        assert approved["model_status"] == "APPROVED"
        assert approved["drift_approved_at"] is not None