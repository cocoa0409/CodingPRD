"""Feed batch pipeline: royalty tiers, QA floor and bonus boundary, budget cap,
the reject/reprocess cycle, state gating, and royalty spend reconciliation."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_deid_profile,
    setup_accepted_batch,
    setup_active_agreement,
    setup_deidentified_batch,
    setup_received_batch,
    setup_validated_batch,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import DAM, PA, PO
from test_helpers.test_users import make_supplier_operator_headers


class TestRoyaltyCombinatorics:
    def test_tiered_royalty_with_qa_bonus_computes_exact_cents(self, api):
        """PRD §3.3: "The royalty itself is computed on the batch's `record_count` using marginal
        tiers in cents per record: the first ten thousand records earn nothing, records from ten
        thousand and one through fifty thousand earn 3 cents each, and every record beyond fifty
        thousand earns 5 cents each."
        PRD §3.3: "Finally, if the batch's `deid_qa_score` is at least 0.98, a quality bonus of
        10 percent is applied on top."

        Design: Difficulty/combinatorial_formula/royalty_tiered_marginal_with_qa_bonus
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 10000000},
            batch_overrides={"record_count": 60000},
        )
        accepted = validate_success(api.accept_batch(batch["id"], {"deid_qa_score": 0.99}, PO))
        assert accepted["royalty_cents"] == 187000, (
            f"(40000*3 + 10000*5) * 1.0 * 1.10 must be 187000, got {accepted['royalty_cents']}"
        )
        assert accepted["status"] == "ACCEPTED"

    def test_accept_debits_agreement_royalty_budget(self, api):
        """PRD §3.3: "The result is rounded half-up exactly once, at the very end, to integer cents
        and recorded as the batch's `royalty_cents`; the agreement's `royalty_spent_cents` is
        incremented by the same amount."

        Design: Difficulty/combinatorial_formula/royalty_tiered_marginal_with_qa_bonus
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 10000000},
            batch_overrides={"record_count": 60000},
        )
        accepted = validate_success(api.accept_batch(batch["id"], {"deid_qa_score": 0.99}, PO))
        fetched = validate_success(api.get_agreement(agreement["id"], DAM))
        assert fetched["royalty_spent_cents"] == accepted["royalty_cents"] == 187000


class TestQaBonusThresholdBoundary:
    def test_exactly_0_98_earns_the_bonus(self, api):
        """PRD §3.3: "Finally, if the batch's `deid_qa_score` is at least 0.98, a quality bonus of
        10 percent is applied on top."

        Design: Difficulty/boundary_precision_check/qa_bonus_threshold_at_exact_0_98
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 10000000},
            batch_overrides={"record_count": 20000},
        )
        accepted = validate_success(api.accept_batch(batch["id"], {"deid_qa_score": 0.98}, PO))
        assert accepted["royalty_cents"] == 33000, (
            f"exactly 0.98 qualifies: 30000 * 1.10 = 33000, got {accepted['royalty_cents']}"
        )

    def test_just_below_0_98_earns_no_bonus(self, api):
        """PRD §3.3: "Finally, if the batch's `deid_qa_score` is at least 0.98, a quality bonus of
        10 percent is applied on top."

        Design: Difficulty/boundary_precision_check/qa_bonus_threshold_at_exact_0_98
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 10000000},
            batch_overrides={"record_count": 20000},
        )
        accepted = validate_success(api.accept_batch(batch["id"], {"deid_qa_score": 0.9799}, PO))
        assert accepted["royalty_cents"] == 30000, (
            f"0.9799 is below the threshold: 10000*3 * 1.0 = 30000, got {accepted['royalty_cents']}"
        )


class TestBatchRejectReprocessCycle:
    def test_reject_from_deidentified_clears_profile(self, api):
        """PRD §3.3: "Rejection is the off-ramp: a `PrivacyOfficer` may reject a batch in either
        `VALIDATED` or `DEIDENTIFIED` status, optionally supplying a `reason`. Rejecting a
        `DEIDENTIFIED` batch additionally clears its `deidentification_profile_id` to null."

        Design: Difficulty/non_linear_state_machine/batch_reject_reprocess_cycle
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            batch_overrides={"record_count": 20000}
        )
        rejected = validate_success(api.reject_batch(batch["id"], PO, payload={"reason": "qa fail"}))
        assert rejected["status"] == "REJECTED"
        assert rejected["deidentification_profile_id"] is None, (
            "rejecting a DEIDENTIFIED batch must clear the profile reference"
        )

    def test_reprocess_validate_accept_completes_the_cycle(self, api):
        """PRD §3.3: "From `REJECTED`, the owning `SupplierOperator` may reprocess the batch, moving
        it to `REPROCESSED` — the operator must own the agreement's supplier
        (`ERR_FORBIDDEN_OWNERSHIP` otherwise) — and a subsequent validation pass returns it to
        `VALIDATED` for another run at the pipeline."
        PRD §3.3: "Validation, performed by a `DataAcquisitionManager`, moves a batch from
        `RECEIVED` — or, after a supplier's rework, from `REPROCESSED` — to `VALIDATED`; the
        agreement must still be `ACTIVE`."

        Design: Difficulty/non_linear_state_machine/batch_reject_reprocess_cycle
        """
        supplier, agreement, profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 10000000},
            batch_overrides={"record_count": 20000},
        )
        validate_success(api.reject_batch(batch["id"], PO, payload={"reason": "qa fail"}))
        reprocessed = validate_success(
            api.reprocess_batch(batch["id"], make_supplier_operator_headers(supplier["id"]))
        )
        assert reprocessed["status"] == "REPROCESSED"
        revalidated = validate_success(api.validate_batch(batch["id"], DAM))
        assert revalidated["status"] == "VALIDATED", "the cycle returns the batch to VALIDATED"
        validate_success(
            api.deidentify_batch(batch["id"], {"deidentification_profile_id": profile["id"]}, PO)
        )
        accepted = validate_success(api.accept_batch(batch["id"], {"deid_qa_score": 0.95}, PO))
        assert accepted["status"] == "ACCEPTED"
        assert accepted["royalty_cents"] == 30000, (
            f"20000 records, PHARMACY multiplier 1.0, no QA bonus: 30000, "
            f"got {accepted['royalty_cents']}"
        )


class TestBatchStateGating:
    def test_accept_directly_from_received_rejected(self, api):
        """PRD §3.3: "A batch in the wrong state for either step is rejected with
        `ERR_BATCH_INVALID_STATE`."

        Design: Corner/state_machines/batch_accept_from_received_rejected
        """
        _supplier, _agreement, batch = setup_received_batch(
            batch_overrides={"record_count": 100}
        )
        resp = api.accept_batch(batch["id"], {"deid_qa_score": 0.99}, PO)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)
        fetched = validate_success(api.get_batch(batch["id"], PA))
        assert fetched["status"] == "RECEIVED"
        assert fetched["royalty_cents"] is None

    def test_validate_blocked_when_agreement_suspended(self, api):
        """PRD §3.3: "Validation, performed by a `DataAcquisitionManager`, moves a batch from
        `RECEIVED` — or, after a supplier's rework, from `REPROCESSED` — to `VALIDATED`; the
        agreement must still be `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/batch_validate_blocked_when_agreement_suspended
        """
        supplier, agreement, batch = setup_received_batch(
            batch_overrides={"record_count": 5000}
        )
        validate_success(api.suspend_agreement(agreement["id"], DAM))
        resp = api.validate_batch(batch["id"], DAM)
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        fetched = validate_success(api.get_batch(batch["id"], PA))
        assert fetched["status"] == "RECEIVED", (
            "a RECEIVED batch is untouched by the suspension quarantine cascade"
        )

    def test_validate_succeeds_while_agreement_active(self, api):
        """PRD §3.3: "Validation, performed by a `DataAcquisitionManager`, moves a batch from
        `RECEIVED` — or, after a supplier's rework, from `REPROCESSED` — to `VALIDATED`; the
        agreement must still be `ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/batch_validate_blocked_when_agreement_suspended
        """
        _supplier, _agreement, batch = setup_received_batch(
            batch_overrides={"record_count": 5000}
        )
        validated = validate_success(api.validate_batch(batch["id"], DAM))
        assert validated["status"] == "VALIDATED"


class TestAcceptPriorityAndFiscalGuards:
    def test_accept_rejected_batch_reports_state_not_fiscal(self, api):
        """PRD §2.8: "Every request passes through a fixed priority cascade. Authentication and role
        checks come first, then ownership checks, then existence checks on path identifiers and
        body foreign keys (validated left to right, so the first unresolvable identifier is the
        one reported with `ERR_NOT_FOUND`), then request-body schema checks
        (`ERR_INVALID_REQUEST`), then optimistic-concurrency checks, then generic and
        domain-specific state checks, then business safety rules (re-identification prohibition,
        opt-out violation, jurisdiction restriction, QA floor), then business temporal rules
        (window overlap, delivery window, audit cooldown), then business referential rules
        (version currency, deliverable cells, duplicate opt-out), and finally fiscal rules
        (royalty budget, entitlement balance). When several rules could reject the same request,
        the earliest rule in this ordering wins."

        Design: Difficulty/priority_pair_validation_conflict/batch_accept_state_beats_fiscal
        """
        supplier, agreement, batch = setup_received_batch(
            agreement_overrides={"royalty_budget_cents": 0},
            batch_overrides={"record_count": 20000},
        )
        validate_success(api.validate_batch(batch["id"], DAM))
        validate_success(api.reject_batch(batch["id"], PO))
        resp = api.accept_batch(batch["id"], {"deid_qa_score": 0.99}, PO)
        validate_error(resp, ApiErrorId.ERR_BATCH_INVALID_STATE)
        fetched = validate_success(api.get_batch(batch["id"], PA))
        assert fetched["status"] == "REJECTED"
        assert fetched["royalty_cents"] is None
        agreement_now = validate_success(api.get_agreement(agreement["id"], DAM))
        assert agreement_now["royalty_spent_cents"] == 0

    def test_accept_on_exhausted_budget_reports_fiscal(self, api):
        """PRD §3.3: "Second, accepting must not breach the agreement's royalty cap: the sum of the
        agreement's current `royalty_spent_cents` and the royalty computed for this batch must
        not exceed `royalty_budget_cents`, or the acceptance is rejected with
        `ERR_ROYALTY_BUDGET_EXHAUSTED` (HTTP 402)."

        Design: Difficulty/priority_pair_validation_conflict/batch_accept_state_beats_fiscal
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 100},
            batch_overrides={"record_count": 20000},
        )
        resp = api.accept_batch(batch["id"], {"deid_qa_score": 0.95}, PO)
        validate_error(resp, ApiErrorId.ERR_ROYALTY_BUDGET_EXHAUSTED)
        fetched = validate_success(api.get_batch(batch["id"], PA))
        assert fetched["status"] == "DEIDENTIFIED"
        assert fetched["royalty_cents"] is None
        agreement_now = validate_success(api.get_agreement(agreement["id"], DAM))
        assert agreement_now["royalty_spent_cents"] == 0

    def test_accept_nonexistent_batch_returns_not_found(self, api):
        """PRD §2.8: "Every request passes through a fixed priority cascade. Authentication and role
        checks come first, then ownership checks, then existence checks on path identifiers and
        body foreign keys (validated left to right, so the first unresolvable identifier is the
        one reported with `ERR_NOT_FOUND`), then request-body schema checks
        (`ERR_INVALID_REQUEST`), then optimistic-concurrency checks, then generic and
        domain-specific state checks, then business safety rules (re-identification prohibition,
        opt-out violation, jurisdiction restriction, QA floor), then business temporal rules
        (window overlap, delivery window, audit cooldown), then business referential rules
        (version currency, deliverable cells, duplicate opt-out), and finally fiscal rules
        (royalty budget, entitlement balance). When several rules could reject the same request,
        the earliest rule in this ordering wins."

        Design: Corner/validations/accept_nonexistent_batch_returns_not_found
        """
        resp = api.accept_batch(NON_EXISTENT_UUID, {"deid_qa_score": 0.99}, PO)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestRoyaltyBudgetCap:
    def test_budget_exhausted_rejects_accept_402(self, api):
        """PRD §3.3: "Second, accepting must not breach the agreement's royalty cap: the sum of the
        agreement's current `royalty_spent_cents` and the royalty computed for this batch must
        not exceed `royalty_budget_cents`, or the acceptance is rejected with
        `ERR_ROYALTY_BUDGET_EXHAUSTED` (HTTP 402)."

        Design: Corner/errors/royalty_budget_exhausted_on_accept_returns_402
        """
        supplier, agreement, _profile, batch = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 1000},
            batch_overrides={"record_count": 20000},
        )
        resp = api.accept_batch(batch["id"], {"deid_qa_score": 0.95}, PO)
        validate_error(resp, ApiErrorId.ERR_ROYALTY_BUDGET_EXHAUSTED)
        fetched = validate_success(api.get_batch(batch["id"], PA))
        assert fetched["status"] == "DEIDENTIFIED"
        assert fetched["royalty_cents"] is None
        agreement_now = validate_success(api.get_agreement(agreement["id"], DAM))
        assert agreement_now["royalty_spent_cents"] == 0


class TestRoyaltySpentReconciliation:
    def test_royalty_spent_accumulates_across_accepts(self, api):
        """PRD §3.3: "The result is rounded half-up exactly once, at the very end, to integer cents
        and recorded as the batch's `royalty_cents`; the agreement's `royalty_spent_cents` is
        incremented by the same amount."

        Design: Corner/cross_cutting_layers/agreement_royalty_spent_reconciles_across_accepts
        """
        supplier, agreement, profile, batch1 = setup_deidentified_batch(
            agreement_overrides={"royalty_budget_cents": 1000000},
            batch_overrides={"record_count": 20000},
        )
        batch2 = submit_batch(agreement["id"], supplier["id"], record_count=20000)
        validate_success(api.validate_batch(batch2["id"], DAM))
        validate_success(
            api.deidentify_batch(
                batch2["id"], {"deidentification_profile_id": profile["id"]}, PO
            )
        )
        validate_success(api.accept_batch(batch1["id"], {"deid_qa_score": 0.95}, PO))
        after_first = validate_success(api.get_agreement(agreement["id"], DAM))
        assert after_first["royalty_spent_cents"] == 30000, (
            f"first accept must debit 30000, got {after_first['royalty_spent_cents']}"
        )
        validate_success(api.accept_batch(batch2["id"], {"deid_qa_score": 0.95}, PO))
        after_second = validate_success(api.get_agreement(agreement["id"], DAM))
        assert after_second["royalty_spent_cents"] == 60000, (
            f"second accept must bring the total to 60000, got {after_second['royalty_spent_cents']}"
        )


class TestBatchListingAndCreate:
    def test_agreement_filter_with_pagination(self, api):
        """PRD §2.3: "List endpoints accept two optional query parameters. `limit` caps the number of
        returned items; it defaults to 10, with a minimum of 1 and a maximum of 100. `offset`
        specifies how many items to skip and defaults to 0. All list endpoints return resources
        sorted by `created_at` in ascending order. The `meta` object of a list response carries
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/batches_list_filter_and_pagination
        """
        supplier1, agreement1 = setup_active_agreement(
            supplier_overrides={"name": "S1"}, agreement_overrides={"royalty_budget_cents": 1000000}
        )
        supplier2, agreement2 = setup_active_agreement(
            supplier_overrides={"name": "S2", "state_code": "NV"},
            agreement_overrides={"royalty_budget_cents": 1000000},
        )
        for count in (10, 20, 30):
            submit_batch(agreement1["id"], supplier1["id"], record_count=count)
        submit_batch(agreement2["id"], supplier2["id"], record_count=40)

        page1, meta1 = validate_paginated(
            api.list_batches(PA, params={"agreement_id": agreement1["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_batches(PA, params={"agreement_id": agreement1["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_computed_royalty_field_ignores_client_input(self, api):
        """PRD §3.3: "The batch is born `RECEIVED`, with `deidentification_profile_id`,
        `deid_qa_score`, and `royalty_cents` all null."

        Design: Corner/entities/batch_create_royalty_input_ignored
        """
        supplier, agreement = setup_active_agreement(
            agreement_overrides={"royalty_budget_cents": 1000000}
        )
        payload = {
            "agreement_id": agreement["id"],
            "period_code": "2026-08",
            "record_count": 100,
            "royalty_cents": 999999,
        }
        data = validate_success(
            api.create_batch(payload, make_supplier_operator_headers(supplier["id"])),
            expected_status=201,
        )
        assert data["royalty_cents"] is None, (
            "royalty_cents is computed at acceptance; the injected value must be ignored"
        )

    def test_batch_create_on_draft_agreement_rejected(self, api):
        """PRD §3.3: "A `SupplierOperator` submits a feed batch by supplying the `agreement_id` of an
        agreement, a `period_code` in `YYYY-MM` format, and a `record_count` of at least 1. The
        agreement must belong to the operator's own supplier (else `ERR_FORBIDDEN_OWNERSHIP`) and
        must be `ACTIVE` (else `ERR_AGREEMENT_NOT_ACTIVE`)."

        Design: Corner/validations/batch_create_on_draft_agreement_rejected
        """
        from test_helpers import create_agreement, create_supplier

        supplier = create_supplier(name="SDR")
        agreement = create_agreement(supplier["id"], royalty_budget_cents=1000000)
        assert agreement["status"] == "DRAFT"
        resp = api.create_batch(
            {
                "agreement_id": agreement["id"],
                "period_code": "2026-08",
                "record_count": 100,
            },
            make_supplier_operator_headers(supplier["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE)
        rows, meta = validate_paginated(
            api.list_batches(PA, params={"agreement_id": agreement["id"]})
        )
        assert meta["total_count"] == 0 and rows == []
