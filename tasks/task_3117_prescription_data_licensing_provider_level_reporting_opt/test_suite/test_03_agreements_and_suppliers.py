"""Agreements and suppliers: exclusivity half-open windows, amendment OCC,
supplier suspension cascade, agreement resume compensation, and terminal
lockdown."""
from test_helpers import (
    ApiErrorId,
    create_agreement,
    create_cell,
    create_methodology,
    create_supplier,
    get_success_data,
    setup_active_agreement,
    setup_validated_batch,
    submit_batch,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DAM, PA
from test_helpers.test_users import make_supplier_operator_headers


class TestExclusivityWindowOverlap:
    def test_adjacent_window_allowed_and_overlap_rejected(self, api):
        """PRD §3.2: "The exclusivity window is half-open: the start date is included, the end date
        is excluded. The system rejects a new agreement whose window overlaps — under that same
        half-open convention, meaning the new start falls strictly before an existing window's end
        while the existing start falls strictly before the new end — any agreement of the same
        supplier and the same `data_domain` whose `status` is `DRAFT`, `ACTIVE`, or `SUSPENDED`;
        `TERMINATED` agreements are excluded from the overlap check, and mere adjacency (the new
        start equals an existing end) does not constitute overlap. A violating submission is
        rejected with `ERR_AGREEMENT_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/agreement_exclusivity_half_open_adjacency
        """
        supplier = create_supplier(name="PharmCo5")
        first = create_agreement(
            supplier["id"],
            exclusivity_start_date="2026-01-01",
            exclusivity_end_date="2026-06-01",
        )
        assert first["status"] == "DRAFT"
        adjacent = create_agreement(
            supplier["id"],
            exclusivity_start_date="2026-06-01",
            exclusivity_end_date="2026-12-01",
        )
        assert adjacent["status"] == "DRAFT", "adjacency (start == existing end) is allowed"
        resp = api.create_agreement(
            supplier["id"],
            {
                "data_domain": "RETAIL_SCRIPTS",
                "exclusivity_start_date": "2026-05-31",
                "exclusivity_end_date": "2026-07-01",
                "royalty_budget_cents": 1000000,
            },
            DAM,
        )
        validate_error(resp, ApiErrorId.ERR_AGREEMENT_WINDOW_OVERLAP)

    def test_same_window_different_domain_allowed(self, api):
        """PRD §3.2: "The system rejects a new agreement whose window overlaps — under that same
        half-open convention, meaning the new start falls strictly before an existing window's end
        while the existing start falls strictly before the new end — any agreement of the same
        supplier and the same `data_domain` whose `status` is `DRAFT`, `ACTIVE`, or `SUSPENDED`;
        `TERMINATED` agreements are excluded from the overlap check, and mere adjacency (the new
        start equals an existing end) does not constitute overlap."

        Design: Difficulty/resource_temporal_overlap/agreement_exclusivity_half_open_adjacency
        """
        supplier = create_supplier(name="PharmCo5b")
        create_agreement(
            supplier["id"],
            exclusivity_start_date="2026-01-01",
            exclusivity_end_date="2026-06-01",
        )
        other_domain = create_agreement(
            supplier["id"],
            data_domain="CLAIMS_ADJUDICATION",
            exclusivity_start_date="2026-02-01",
            exclusivity_end_date="2026-03-01",
        )
        assert other_domain["status"] == "DRAFT", (
            "exclusivity is per (supplier, data_domain): a different domain never conflicts"
        )


class TestAgreementAmendmentOCC:
    def test_stale_expected_version_rejected_412(self, api):
        """PRD §2.5: "Likewise, amending a data acquisition agreement requires
        `expected_agreement_version` equal to the agreement's current `version`; an intervening
        activate, suspend, resume, or prior amendment legitimately advanced the version, so a
        stale amendment base is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/errors/stale_version_amend_agreement_returns_412
        """
        supplier, agreement = setup_active_agreement()
        stale_version = agreement["version"] - 1  # version captured before activate bumped it
        resp = api.amend_agreement(
            agreement["id"],
            {"expected_agreement_version": stale_version, "royalty_budget_cents": 2000000},
            DAM,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

    def test_current_version_amend_succeeds_and_counts(self, api):
        """PRD §3.2: "The request must carry `expected_agreement_version` per §2.5, and a proposed
        end date that would overlap a sibling non-`TERMINATED` agreement of the same supplier and
        domain is rejected with `ERR_AGREEMENT_WINDOW_OVERLAP` under the same half-open rule. Each
        successful amendment increments `amendment_count` by 1 (and, as every mutation does, bumps
        the agreement's `version`)."

        Design: Corner/errors/stale_version_amend_agreement_returns_412
        """
        supplier, agreement = setup_active_agreement()
        amended = validate_success(
            api.amend_agreement(
                agreement["id"],
                {
                    "expected_agreement_version": agreement["version"],
                    "royalty_budget_cents": 2000000,
                },
                DAM,
            )
        )
        assert amended["amendment_count"] == 1
        assert amended["royalty_budget_cents"] == 2000000


class TestSupplierSuspensionCascade:
    def test_suspend_cascades_to_active_agreements_only(self, api):
        """PRD §3.1: "Suspending a supplier — a `DataAcquisitionManager` action valid only while the
        supplier is `ACTIVE` — transitions it to `SUSPENDED` and fires the agreement cascade:
        every agreement of that supplier currently `ACTIVE` transitions to `SUSPENDED`, and each
        of those agreement transitions fires its own three-link cascade into batches, cells, and
        deliveries (§3.3)."

        Design: Corner/state_machines/supplier_suspend_cascades_to_agreements
        """
        supplier = create_supplier(name="SC")
        active_agreement = create_agreement(supplier["id"])
        get_success_data(api.activate_agreement(active_agreement["id"], DAM))
        draft_agreement = create_agreement(supplier["id"], data_domain="CLAIMS_ADJUDICATION")
        assert draft_agreement["status"] == "DRAFT"

        suspended = validate_success(api.suspend_supplier(supplier["id"], DAM))
        assert suspended["status"] == "SUSPENDED"
        cascaded = validate_success(api.get_agreement(active_agreement["id"], DAM))
        assert cascaded["status"] == "SUSPENDED", "ACTIVE agreement cascades to SUSPENDED"
        untouched = validate_success(api.get_agreement(draft_agreement["id"], DAM))
        assert untouched["status"] == "DRAFT", "a DRAFT agreement is untouched by the cascade"


class TestAgreementResumeCompensation:
    def test_resume_returns_quarantined_batches_to_validated(self, api):
        """PRD §3.2: "Resuming a `SUSPENDED` agreement requires the supplier to be `ACTIVE`
        (`ERR_AGREEMENT_NOT_ACTIVE` otherwise) and returns every `QUARANTINED` batch of the
        agreement to `VALIDATED` — de-identification must be redone from there — while the
        projection cells remain `PENDING_RESTATEMENT` until they are individually recomputed
        (§3.5)."

        Design: Corner/state_machines/resume_returns_quarantined_batches_to_validated
        """
        supplier, agreement, batch = setup_validated_batch(
            batch_overrides={"period_code": "2026-08", "record_count": 100}
        )
        methodology = create_methodology(name="M-RES")
        cell = create_cell(
            methodology["id"],
            geography_code="CA-SOUTH",
            specialty="CARDIOLOGY",
            period_code="2026-08",
            supplier_ids=[supplier["id"]],
        )
        validate_success(api.suspend_agreement(agreement["id"], DAM))
        quarantined = validate_success(api.get_batch(batch["id"], PA))
        assert quarantined["status"] == "QUARANTINED"

        resumed = validate_success(api.resume_agreement(agreement["id"], DAM))
        assert resumed["status"] == "ACTIVE"
        restored = validate_success(api.get_batch(batch["id"], PA))
        assert restored["status"] == "VALIDATED"
        assert restored["deidentification_profile_id"] is None
        cell_now = validate_success(api.get_cell(cell["id"], PA))
        assert cell_now["status"] == "PENDING_RESTATEMENT", (
            "resume does not auto-restate cells; they stay PENDING_RESTATEMENT until recompute"
        )


class TestTerminalAgreementLockdown:
    def test_resume_terminated_agreement_rejected(self, api):
        """PRD §3.2: "Once `TERMINATED`, an agreement never leaves that state."

        Design: Corner/state_machines/terminated_agreement_lockdown_rejected
        """
        supplier = create_supplier(name="ST", supplier_type="DISTRIBUTOR", state_code="NV")
        agreement = create_agreement(supplier["id"], data_domain="DISTRIBUTION_SHIPMENTS")
        terminated = validate_success(api.terminate_agreement(agreement["id"], DAM))
        assert terminated["status"] == "TERMINATED"
        resp = api.resume_agreement(agreement["id"], DAM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api.get_agreement(agreement["id"], DAM))
        assert fetched["status"] == "TERMINATED"
