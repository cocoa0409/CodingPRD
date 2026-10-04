"""Contract stand-up, program configuration, and case-opening rules.

Covers format/uniqueness constraints on case identifiers, program typing and
DISASTER window semantics, the contract-ACTIVE gate, body-reference existence,
and contract-closure obligations.
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    validate_error,
    validate_success,
)
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]
CSR_A = TEST_USERS["csr_headers"]


class TestCaseIdentifierRules:
    def test_case_identifier_format_violation_rejected(self, api):
        """PRD §3.3: "The `case_identifier` is exactly ten decimal digits; a
        malformed identifier is rejected with `ERR_CASE_IDENTIFIER_INVALID`, and
        one that already exists within the same contract is rejected with
        `ERR_CASE_IDENTIFIER_DUPLICATE`."

        Design: Corner/entities/case_identifier_format_violation_rejected
        """
        ctx = fx.setup_active_contract(api)
        resp = api.create_case_account(
            f.case_account_payload(ctx.contract["id"], case_identifier="ABC123"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_IDENTIFIER_INVALID)

    def test_case_identifier_duplicate_rejected(self, api):
        """PRD §3.3: "The `case_identifier` is exactly ten decimal digits; a
        malformed identifier is rejected with `ERR_CASE_IDENTIFIER_INVALID`, and
        one that already exists within the same contract is rejected with
        `ERR_CASE_IDENTIFIER_DUPLICATE`."

        Design: Corner/entities/case_identifier_duplicate_rejected
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx, case_identifier="0000000007",
                    head_of_household_name="H Y1")
        resp = api.create_case_account(
            f.case_account_payload(ctx.contract["id"], case_identifier="0000000007",
                                   head_of_household_name="H Y2"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CASE_IDENTIFIER_DUPLICATE)

    def test_missing_case_identifier_returns_invalid_request(self, api):
        """PRD §3.3: "A `StateAdmin` opens a case account within an `ACTIVE`
        contract by supplying the `contract_id`, a `case_identifier`, and the
        `head_of_household_name`."
        PRD §2.8: "19. Field formats and request shape: `ERR_INVALID_REQUEST`
        plus the dedicated format identifiers `ERR_CASE_IDENTIFIER_INVALID`,
        `ERR_UPC_INVALID`, and `ERR_WITHDRAWAL_MULTIPLE`."

        Design: Corner/entities/missing_case_identifier_returns_invalid_request
        """
        ctx = fx.setup_active_contract(api)
        resp = api.create_case_account(
            {"contract_id": ctx.contract["id"], "head_of_household_name": "H V"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestProgramRules:
    def test_program_type_enum_violation_rejected(self, api):
        """PRD §3.1: "Creating a program requires the `contract_id` and a
        `program_type` of `FOOD`, `CASH`, or `DISASTER`"
        PRD §2.8: "19. Field formats and request shape: `ERR_INVALID_REQUEST`
        plus the dedicated format identifiers `ERR_CASE_IDENTIFIER_INVALID`,
        `ERR_UPC_INVALID`, and `ERR_WITHDRAWAL_MULTIPLE`."

        Design: Corner/entities/program_type_enum_violation_rejected
        """
        contract = fx.create_contract(api)
        resp = api.create_program(
            f.program_payload(contract["id"], program_type="MEDICAL"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_food_program_rejected(self, api):
        """PRD §3.1: "Program type is constrained per contract: at most one
        `FOOD` and at most one `CASH` program may exist, and a second of either
        is rejected with `ERR_PROGRAM_TYPE_DUPLICATE`. `DISASTER` programs may
        repeat, but their closed windows may not touch or overlap another
        `DISASTER` window of the same contract — unlike item windows, even
        adjacency conflicts — and a violation is rejected with
        `ERR_DISASTER_WINDOW_OVERLAP`."

        Design: Corner/validations/duplicate_food_program_rejected
        """
        ctx = fx.setup_active_contract(api, activate=False)
        resp = api.create_program(
            f.program_payload(ctx.contract["id"], program_type="FOOD"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_TYPE_DUPLICATE)
        # A DISASTER program with a window remains legal in the same contract.
        resp2 = api.create_program(
            f.program_payload(ctx.contract["id"], program_type="DISASTER",
                              disaster_window_start="2026-09-10",
                              disaster_window_end="2026-09-20"),
            ADMIN,
        )
        disaster = validate_success(resp2, 201)
        assert disaster["program_type"] == "DISASTER"

    def test_disaster_window_adjacency_conflicts_closed_interval(self, api):
        """PRD §3.1: "`DISASTER` programs may repeat, but their closed windows
        may not touch or overlap another `DISASTER` window of the same contract
        — unlike item windows, even adjacency conflicts — and a violation is
        rejected with `ERR_DISASTER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/disaster_window_closed_interval_adjacency_conflicts
        """
        ctx = fx.setup_active_contract(api)
        fx.create_program(api, ctx.contract["id"], program_type="DISASTER",
                          disaster_window_start="2026-09-10",
                          disaster_window_end="2026-09-25")
        # Adjacent under CLOSED semantics (start == other's end) conflicts.
        resp = api.create_program(
            f.program_payload(ctx.contract["id"], program_type="DISASTER",
                              disaster_window_start="2026-09-25",
                              disaster_window_end="2026-10-05"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DISASTER_WINDOW_OVERLAP)
        # NOTE: whether a window starting the day AFTER another's end (no
        # shared date, no gap) also "touches" is not uniquely derivable from
        # the PRD sentence — both readings of "may not touch or overlap ...
        # even adjacency conflicts" are faithful — so that branch is not
        # asserted here.

    def test_disaster_window_true_overlap_rejected(self, api):
        """PRD §3.1: "`DISASTER` programs may repeat, but their closed windows
        may not touch or overlap another `DISASTER` window of the same contract
        — unlike item windows, even adjacency conflicts — and a violation is
        rejected with `ERR_DISASTER_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/disaster_window_closed_interval_adjacency_conflicts
        """
        ctx = fx.setup_active_contract(api)
        fx.create_program(api, ctx.contract["id"], program_type="DISASTER",
                          disaster_window_start="2026-09-10",
                          disaster_window_end="2026-09-25")
        # Interior overlap [09-20, 10-05] vs existing [09-10, 09-25].
        resp = api.create_program(
            f.program_payload(ctx.contract["id"], program_type="DISASTER",
                              disaster_window_start="2026-09-20",
                              disaster_window_end="2026-10-05"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DISASTER_WINDOW_OVERLAP)
        # The rejected program was not created: only FOOD + the first DISASTER.
        programs = fx.list_contract_programs(api, ctx.contract["id"])
        assert len(programs) == 2, f"expected 2 programs after rejection, got {len(programs)}"


class TestContractStateGates:
    def test_case_creation_before_contract_active_rejected(self, api):
        """PRD §3.1: "Every other business operation is stricter than program
        creation: case creation, retailer onboarding, item-file upload,
        allotment runs, and authorizations each require the contract to be
        `ACTIVE` and are otherwise rejected with `ERR_CONTRACT_NOT_ACTIVE`."

        Design: Corner/validations/case_creation_before_contract_active_rejected
        """
        ctx = fx.setup_active_contract(api, activate=False)
        resp = api.create_case_account(
            f.case_account_payload(ctx.contract["id"]), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_ACTIVE)

    def test_contract_close_with_open_cases_rejected(self, api):
        """PRD §3.1: "Closing a contract — from `ACTIVE` or `SUSPENDED` to
        `CLOSED`, which is terminal — carries three obligation preconditions,
        each surfaced as `ERR_CONTRACT_HAS_OPEN_OBLIGATIONS`: every case account
        of the contract must already be `CLOSED`, no settlement batch of the
        contract may remain in `CUTOFF` or `DISPUTED`, and no skimming claim of
        the contract may remain in `FILED` or `UNDER_INVESTIGATION`."

        Design: Corner/validations/contract_close_with_open_cases_rejected
        """
        ctx = fx.setup_active_contract(api)
        fx.add_case(api, ctx)
        resp = api.set_contract_status(
            ctx.contract["id"], f.contract_status_payload("CLOSED"), ADMIN
        )
        validate_error(resp, ApiErrorId.ERR_CONTRACT_HAS_OPEN_OBLIGATIONS)


class TestBodyReferenceExistence:
    def test_nonexistent_body_reference_returns_reference_not_found(self, api):
        """PRD §2.9: "Request-body references are validated next:
        `contract_id`, `case_account_id`, `card_id`, `settlement_batch_id`, and
        every element of a claim's `authorization_ids` must each identify an
        existing resource, or the request is rejected with
        `ERR_REFERENCE_NOT_FOUND`."

        Design: Corner/validations/nonexistent_body_reference_returns_reference_not_found
        """
        fx.create_contract(api)
        resp = api.create_card(f.card_payload(NON_EXISTENT_UUID), CSR_A)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND)
