"""
The evaluation order of the validation ladder and the twelve not-found codes.

Every test starts against an empty database and builds each precondition from
the endpoints the PRD declares.
"""

import pytest

from test_helpers import (
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    DIRECTOR_HEADERS,
    KAM_HEADERS,
    MONDAY_AUG_03,
    MONDAY_AUG_17,
    MONDAY_AUG_31,
    NEVER_MINTED_UUID,
    NON_EXISTENT_UUID,
    SPECIALIST_HEADERS,
    AccrualMethod,
    AllocationPosture,
    AllocationStatus,
    ApiErrorId,
    DeductionStatus,
    FactSource,
    FactType,
    PromotionLifecycleStatus,
    SpendStatus,
    TradingStatus,
    assert_money,
    assert_ratio,
    create_promotion_payload,
    create_tpr_tactic_payload,
    current_allocation_version,
    instant,
    match_deduction_payload,
    post_accrual,
    read_allocation,
    read_customer,
    read_deduction,
    read_promotion,
    run_activation,
    set_clock,
    setup_approved_allocation,
    setup_brand,
    setup_customer,
    setup_deduction,
    setup_draft_allocation,
    setup_program,
    setup_volume_fact,
    validate_error,
    validate_success,
)


def _restricted_cell_with_a_second_submitted_promotion(api):
    """
    A cell whose whole balance is committed to one overspending promotion, with a
    sibling promotion left in `SUBMITTED` awaiting approval.

    The overspend cascade turns the cell's posture to `RESTRICTED` and puts the
    retailer on credit hold, so an approval of the sibling violates the posture
    rung, the fiscal-capacity rungs and the credit-hold rung all at once.
    """
    set_clock(api, instant(MONDAY_AUG_03))
    program = setup_program(
        api,
        total_budget_amount=5000000.00,
        accrual_method_default=AccrualMethod.CONSUMPTION.value,
    )
    brand = setup_brand(
        api, program["id"],
        list_price_per_case=24.00, cogs_per_case=8.70, baseline_units_per_week=600,
    )
    customer = setup_customer(api, program["id"])
    allocation = setup_approved_allocation(
        api, program["id"], customer["id"], brand["id"],
        planned_amount=2500.00, baseline_units=40000, planned_incremental_units=20000,
    )

    promotions = []
    for units in (2000, 1800):
        promotion = validate_success(
            api.create_promotion(
                create_promotion_payload(
                    allocation["id"],
                    current_allocation_version(api, allocation["id"]),
                    window_start=MONDAY_AUG_03,
                    window_end=MONDAY_AUG_31,
                    accrual_method=AccrualMethod.CONSUMPTION.value,
                ),
                KAM_HEADERS,
            ),
            expected_status=201,
        )
        validate_success(
            api.create_tactic(
                promotion["id"],
                create_tpr_tactic_payload(
                    planned_units=units, rate_per_case=1.250,
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31,
                ),
                KAM_HEADERS,
            ),
            expected_status=201,
        )
        promotions.append(promotion)

    funded, awaiting = promotions
    validate_success(api.submit_promotion(funded["id"], KAM_HEADERS))
    validate_success(api.approve_promotion(funded["id"], DIRECTOR_HEADERS))
    awaiting = validate_success(api.submit_promotion(awaiting["id"], KAM_HEADERS))

    run_activation(api)
    setup_volume_fact(
        api, customer["id"], brand["id"],
        fact_type=FactType.CONSUMPTION.value, period_start=MONDAY_AUG_03,
        units=2100, source=FactSource.EDI_852.value,
    )
    post_accrual(api, funded["id"], MONDAY_AUG_03)

    return {
        "program": program,
        "brand": brand,
        "customer": customer,
        "allocation": allocation,
        "funded": funded,
        "awaiting": awaiting,
    }


class TestApproveRungPrecedence:
    """Posture at rung 42 outranks the fiscal capacity checks at rungs 95 and 96."""

    def test_the_restricted_posture_is_reported_and_not_the_exhausted_balance(self, api):
        """
        One approval violates the posture rung, the balance rung and the credit
        hold rung together, and only the posture refusal may come back.

        PRD: "A single malformed or ill-timed request commonly violates several rules at once. The response must be deterministic, so all validation rules carry an explicit precedence and **the first rule that fails determines the response; no later rule is evaluated**."
        PRD: "**Rung 42** — the funding allocation's `posture` is `OPEN`, on promotion create and promotion approve: `ERR_ALLOCATION_POSTURE_RESTRICTED`. Accrual posting, deduction handling and analysis are deliberately **not** gated by posture — the ledger must keep recording money that has already been spent."
        PRD: "**Rung 95** — allocation dollars suffice, on promotion approve: `ERR_ALLOCATION_BALANCE_INSUFFICIENT`."
        PRD: "And the fiscal capacity checks (rungs 95 through 98) are evaluated **last** of all, so a promotion approval that is simultaneously missing its commitment paperwork and over its allocation balance reports the missing paperwork."

        Design: Difficulty/priority_pair_validation_conflict/approve_posture_state_outranks_allocation_balance_fiscal
        """
        context = _restricted_cell_with_a_second_submitted_promotion(api)

        overspent = read_promotion(api, context["funded"]["id"])
        assert_money(overspent["planned_total_spend"], 2500.00, "planned_total_spend")
        assert_ratio(overspent["spend_ratio"], 1.0500, "spend_ratio")
        assert overspent["spend_status"] == SpendStatus.OVERSPENT.value

        cell = read_allocation(api, context["allocation"]["id"])
        assert cell["posture"] == AllocationPosture.RESTRICTED.value
        assert cell["overspend_event_count"] == 1
        assert_money(cell["available_amount"], 0.00, "available_amount")

        awaiting = read_promotion(api, context["awaiting"]["id"])
        assert_money(awaiting["planned_total_spend"], 2250.00, "planned_total_spend")

        held = read_customer(api, context["customer"]["id"])
        assert held["trading_status"] == TradingStatus.CREDIT_HOLD.value

        validate_error(
            api.approve_promotion(context["awaiting"]["id"], DIRECTOR_HEADERS),
            ApiErrorId.ALLOCATION_POSTURE_RESTRICTED.value,
        )

    def test_the_refused_approval_commits_nothing_to_the_cell(self, api):
        """
        The refused approval is a complete no-op: the sibling stays `SUBMITTED`
        and the cell's committed figures still reflect only the funded promotion.

        PRD: "`committed_amount` is the sum of `planned_total_spend` across child promotions whose `lifecycle_status` is `APPROVED`, `LIVE`, `ENDED` or `ANALYZED`, rounded half up to 2 decimal places; promotions in `DRAFT`, `SUBMITTED`, `CHANGES_REQUESTED` or `WITHDRAWN` reserve nothing."
        PRD: "**Rung 42** — the funding allocation's `posture` is `OPEN`, on promotion create and promotion approve: `ERR_ALLOCATION_POSTURE_RESTRICTED`. Accrual posting, deduction handling and analysis are deliberately **not** gated by posture — the ledger must keep recording money that has already been spent."
        PRD: "**Rung 96** — allocation incremental units suffice, on promotion approve: `ERR_UNITS_EXCEED_UNRESERVED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_posture_state_outranks_allocation_balance_fiscal
        """
        context = _restricted_cell_with_a_second_submitted_promotion(api)

        validate_error(
            api.approve_promotion(context["awaiting"]["id"], DIRECTOR_HEADERS),
            ApiErrorId.ALLOCATION_POSTURE_RESTRICTED.value,
        )

        awaiting = read_promotion(api, context["awaiting"]["id"])
        assert awaiting["lifecycle_status"] == PromotionLifecycleStatus.SUBMITTED.value
        assert awaiting["approved_by_user_id"] is None

        cell = read_allocation(api, context["allocation"]["id"])
        assert_money(cell["committed_amount"], 2500.00, "committed_amount")
        assert_money(cell["available_amount"], 0.00, "available_amount")
        assert cell["committed_units"] == 2000
        assert cell["unreserved_units"] == 18000
        assert cell["posture"] == AllocationPosture.RESTRICTED.value


class TestNotFoundFamily:
    """Each path variable carries its own refusal code."""

    @pytest.mark.parametrize(
        "getter_name,expected_error",
        [
            ("get_program", ApiErrorId.PROGRAM_NOT_FOUND),
            ("get_brand", ApiErrorId.BRAND_NOT_FOUND),
            ("get_customer", ApiErrorId.CUSTOMER_NOT_FOUND),
            ("get_budget_allocation", ApiErrorId.ALLOCATION_NOT_FOUND),
            ("get_promotion", ApiErrorId.PROMOTION_NOT_FOUND),
            ("get_tactic", ApiErrorId.TACTIC_NOT_FOUND),
            ("get_document", ApiErrorId.DOCUMENT_NOT_FOUND),
            ("get_volume_fact", ApiErrorId.VOLUME_FACT_NOT_FOUND),
            ("get_accrual", ApiErrorId.ACCRUAL_NOT_FOUND),
            ("get_deduction", ApiErrorId.DEDUCTION_NOT_FOUND),
            ("get_dispute", ApiErrorId.DISPUTE_NOT_FOUND),
            ("get_compliance_audit", ApiErrorId.AUDIT_NOT_FOUND),
        ],
    )
    def test_an_unassigned_identifier_reports_the_code_of_the_entity_addressed(
        self, api, getter_name, expected_error
    ):
        """
        The same syntactically valid but never-minted identifier produces a
        different refusal on each single-resource read.

        PRD: "The path variables the service uses are `programId`, `brandId`, `customerId`, `allocationId`, `promotionId`, `tacticId`, `documentId`, `factId`, `accrualId`, `deductionId`, `disputeId` and `auditId`, and that is also their resolution precedence when more than one appears. Each has its own refusal: `ERR_PROGRAM_NOT_FOUND`, `ERR_BRAND_NOT_FOUND`, `ERR_CUSTOMER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND`, `ERR_PROMOTION_NOT_FOUND`, `ERR_TACTIC_NOT_FOUND`, `ERR_DOCUMENT_NOT_FOUND`, `ERR_VOLUME_FACT_NOT_FOUND`, `ERR_ACCRUAL_NOT_FOUND`, `ERR_DEDUCTION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND` and `ERR_AUDIT_NOT_FOUND`, each with HTTP 404."

        Design: Corner/entities/unresolvable_path_ids_each_map_to_their_own_404_code
        """
        getter = getattr(api, getter_name)
        validate_error(
            getter(NEVER_MINTED_UUID, DIRECTOR_HEADERS), expected_error.value
        )


class TestLadderPrecedencePairs:
    """Adjacent rungs, each proved by a request that violates both at once."""

    def test_the_dead_path_id_is_reported_before_the_dead_body_reference(self, api):
        """
        A match request whose `deductionId` and whose body `promotion_id` are both
        unresolvable reports the path identifier, and the body reference is never
        reached.

        PRD: "Path identifiers are resolved first, left to right, in the order they appear in the URL."
        PRD: "Only after every path identifier resolves are the foreign keys in the request body resolved, in the order the fields appear in that endpoint's input list: `program_id`, then `brand_id`, then `customer_id`, then `allocation_id`, then `promotion_id`, then `deduction_id`, then `reverses_entry_id`, then `supersedes_deduction_id`."
        PRD: "**Rung 20** — every path identifier resolves, left to right, on every endpoint with path parameters: the not-found family of §2.7."
        PRD: "**Rung 21** — every body foreign key resolves, in input-list order, on every endpoint with foreign keys in its body: the same not-found family."

        Design: Corner/validations/path_id_existence_outranks_body_reference_existence
        """
        validate_error(
            api.match_deduction(
                NEVER_MINTED_UUID, match_deduction_payload(NON_EXISTENT_UUID),
                SPECIALIST_HEADERS,
            ),
            ApiErrorId.DEDUCTION_NOT_FOUND.value,
        )

    def test_an_unauthorised_caller_is_turned_away_before_existence_is_probed(self, api):
        """
        A `ComplianceAuditor` locking a program that does not exist is refused for
        its role, so the 403 leaks nothing about whether the program is real.

        PRD: "**Rung 3** — the caller's role appears in the target endpoint's role list, on every endpoint: `ERR_ROLE_NOT_PERMITTED`."
        PRD: "**Rung 20** — every path identifier resolves, left to right, on every endpoint with path parameters: the not-found family of §2.7."
        PRD: "Once the role is recognised, it is checked against the set of roles the target endpoint permits; a recognised role that is not on that list is refused with `ERR_ROLE_NOT_PERMITTED` (HTTP 403)."

        Design: Corner/validations/role_authorisation_outranks_path_id_existence
        """
        validate_error(
            api.lock_program(NEVER_MINTED_UUID, AUDITOR_HEADERS),
            ApiErrorId.ROLE_NOT_PERMITTED.value,
        )

    def test_the_missing_version_field_is_reported_before_the_claim_status(self, api):
        """
        Validating a never-matched claim without `expected_promotion_version` has
        two defects; the request-shape rung answers first and the claim is left
        exactly as it was booked.

        PRD: "**Rung 10** — request shape and field-level well-formedness, on every endpoint: `ERR_INVALID_REQUEST`."
        PRD: "**Rung 47** — the deduction's `status` permits the requested transition, on deduction match, validate, settle and dispute: `ERR_DEDUCTION_STATE_INVALID`."
        PRD: "A `TradeFinanceAnalyst` validates a claim that is currently `MATCHED`, supplying `expected_promotion_version`."
        PRD: "A new claim is created in `status` `RECEIVED` with `promotion_id`, `validation_basis`, `entitled_amount`, `validated_amount`, `variance_amount`, `matched_by_user_id`, `validated_by_user_id` and `settled_at` all null."

        Design: Corner/validations/malformed_body_outranks_deduction_state_precondition
        """
        program = setup_program(api, total_budget_amount=500000.00)
        customer = setup_customer(api, program["id"])
        deduction = setup_deduction(
            api, customer["id"], claimed_amount=900.00, deduction_date=MONDAY_AUG_03
        )
        assert deduction["status"] == DeductionStatus.RECEIVED.value

        validate_error(
            api.validate_deduction(deduction["id"], {}, ANALYST_HEADERS),
            ApiErrorId.INVALID_REQUEST.value,
        )

        after = read_deduction(api, deduction["id"])
        assert after["status"] == DeductionStatus.RECEIVED.value
        assert after["validated_amount"] is None
        assert after["promotion_id"] is None

    def test_the_replayed_allocation_version_is_reported_before_the_draft_status(self, api):
        """
        A promotion create against a `DRAFT` cell, carrying the version read from a
        sibling cell that was approved, is refused for the stale version rather
        than for the unapproved parent.

        PRD: "**Rung 30** — `expected_allocation_version` matches the referenced allocation's `version`, on promotion create: `ERR_STALE_ALLOCATION_VERSION`."
        PRD: "**Rung 41** — the funding allocation is `APPROVED`, on promotion create and promotion submit: `ERR_ALLOCATION_NOT_APPROVED`."
        PRD: "If that value does not equal the allocation's current `version`, the create is refused with `ERR_STALE_ALLOCATION_VERSION` (HTTP 412)."
        PRD: "Promotions may be created against a cell only once it is `APPROVED`; a promotion create or submit against a `DRAFT` cell is refused with `ERR_ALLOCATION_NOT_APPROVED` (HTTP 409)."

        Design: Corner/validations/stale_allocation_version_outranks_allocation_approval_state
        """
        program = setup_program(api, total_budget_amount=500000.00)
        brand = setup_brand(
            api, program["id"],
            list_price_per_case=24.00, cogs_per_case=8.70, baseline_units_per_week=1200,
        )
        customer = setup_customer(api, program["id"])
        draft = setup_draft_allocation(
            api, program["id"], customer["id"], brand["id"],
            planned_amount=60000.00, baseline_units=20000, planned_incremental_units=10000,
        )
        approved = setup_approved_allocation(
            api, program["id"], customer["id"], brand["id"],
            planned_amount=40000.00, baseline_units=10000, planned_incremental_units=8000,
        )
        assert draft["status"] == AllocationStatus.DRAFT.value
        assert draft["version"] == 1
        assert approved["status"] == AllocationStatus.APPROVED.value
        assert approved["version"] == 2

        validate_error(
            api.create_promotion(
                create_promotion_payload(
                    draft["id"], approved["version"],
                    window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_17,
                    accrual_method=AccrualMethod.CONSUMPTION.value,
                ),
                KAM_HEADERS,
            ),
            ApiErrorId.STALE_ALLOCATION_VERSION.value,
        )

        untouched = read_allocation(api, draft["id"])
        assert untouched["status"] == AllocationStatus.DRAFT.value
        assert untouched["version"] == 1
