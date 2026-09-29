"""
Retailer paperwork: commitment coverage, evidence and class-restricted verify.

PRD §3.5 separates the commitment document that gates approval from the evidence
document that feeds deduction valuation, makes verification a payload-dependent
authorisation check, and derives `commitment_verified` from the promotion's own
`DISPLAY` and `FEATURE` lines — which is why a TPR-only plan needs no paperwork.
"""

from test_helpers import (
    ApiErrorId,
    MONDAY_AUG_03,
    MONDAY_AUG_10,
    MONDAY_AUG_17,
    MONDAY_AUG_24,
    MONDAY_AUG_31,
    assert_money,
    assert_ratio,
    create_commitment_document_payload,
    create_evidence_document_payload,
    instant,
    read_allocation,
    read_promotion,
    setup_commitment_document,
    setup_draft_promotion,
    setup_promotion_with_display_line,
    setup_tactic,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCommitmentVerificationStampsTheVerifier:
    """Verifying the commitment paperwork records who did it and flips coverage."""

    def test_commitment_document_verification_stamps_the_verifier(
        self, api, key_account_manager
    ):
        """
        Verification moves the document to `VERIFIED`, stamps the caller and covers the display line.

        PRD: "A new document is created in `status` `SUBMITTED` with `verified_by_user_id` null, and a `SUBMITTED` document counts for absolutely nothing: neither commitment coverage nor deduction valuation looks at it until it is verified."
        PRD: "A successful verification moves `status` `SUBMITTED` → `VERIFIED`, records the caller's identifier in `verified_by_user_id`, and then branches by class with equal consequence in each direction: for a `COMMITMENT` document the promotion's coverage is recomputed and `commitment_verified` may flip from false to true; for an `EVIDENCE` document the row's `units_verified` begins counting toward the entitlement calculation for that promotion's deductions."
        PRD: "`commitment_verified` is true when every member of the required set appears in the covered set."

        Design: Corner/state_machines/commitment_document_verification_stamps_the_verifier
        """
        context = setup_promotion_with_display_line(
            api,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_31,
            },
            planned_units=500,
            fixed_fee=1000.05,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_17,
        )
        promotion_id = context["promotion"]["id"]
        assert context["promotion"]["commitment_verified"] is False

        document = setup_commitment_document(
            api,
            promotion_id,
            doc_type="SIGNED_LOI",
            covers_tactic_type="DISPLAY",
            received_at=instant("2026-07-28", hour=14, minute=30),
        )
        assert document["status"] == "SUBMITTED"
        assert document["verified_by_user_id"] is None
        assert read_promotion(api, promotion_id)["commitment_verified"] is False

        verified = validate_success(
            api.verify_document(document["id"], key_account_manager)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["version"] == 2
        assert verified["verified_by_user_id"] == key_account_manager["X-User-ID"]

        promotion = read_promotion(api, promotion_id)
        assert promotion["commitment_verified"] is True
        assert_money(
            promotion["tactic_subtotal_amount"], 1000.05, "tactic_subtotal_amount"
        )
        assert_ratio(promotion["allowance_rate"], 0.000, "allowance_rate")
        assert_money(promotion["planned_total_spend"], 1000.05, "planned_total_spend")
        assert_money(
            context["tactic"]["line_planned_spend"], 1000.05, "line_planned_spend"
        )


class TestDocumentVerificationIsSingleShot:
    """`VERIFIED` is terminal, whoever calls the second time."""

    def test_document_verification_is_single_shot(
        self, api, key_account_manager, key_account_manager_alt
    ):
        """
        A second verification by another manager is refused and rewrites nothing.

        PRD: "The document must still be `SUBMITTED`; `VERIFIED` is terminal, so verifying twice is refused with `ERR_DOCUMENT_ALREADY_VERIFIED` (HTTP 409)."
        PRD: "**Rung 45** — the document is still `SUBMITTED`, on document verify: `ERR_DOCUMENT_ALREADY_VERIFIED`."

        Design: Corner/state_machines/document_verification_is_single_shot
        """
        context = setup_draft_promotion(
            api, window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31
        )
        document = setup_commitment_document(
            api,
            context["promotion"]["id"],
            doc_type="SIGNED_LOI",
            covers_tactic_type="ALL",
            received_at=instant(MONDAY_AUG_03, hour=9, minute=30),
        )

        verified = validate_success(
            api.verify_document(document["id"], key_account_manager)
        )
        assert verified["status"] == "VERIFIED"
        assert verified["version"] == 2
        assert verified["verified_by_user_id"] == key_account_manager["X-User-ID"]

        validate_error(
            api.verify_document(document["id"], key_account_manager_alt),
            ApiErrorId.DOCUMENT_ALREADY_VERIFIED.value,
        )

        after = validate_success(
            api.get_document(document["id"], key_account_manager)
        )
        assert after["status"] == "VERIFIED"
        assert after["version"] == 2
        assert after["verified_by_user_id"] == key_account_manager["X-User-ID"]


class TestVacuousCommitmentCoverage:
    """A TPR-only plan has an empty required set and needs no paperwork."""

    def test_commitment_coverage_is_vacuously_true_for_a_tpr_only_promotion(
        self, api, finance_analyst, director
    ):
        """
        `commitment_verified` is true from creation and stays true as TPR lines arrive.

        PRD: "The **required** set is the collection of tactic types among `DISPLAY` and `FEATURE` that appear on the promotion's lines whose `status` is `PLANNED`, `ACTIVE` or `COMPLETED`; `TPR` lines never require commitment paperwork."
        PRD: "The empty case matters: a promotion carrying only `TPR` lines has an empty required set, and its `commitment_verified` is therefore true with no paperwork at all."

        Design: Corner/calculations/commitment_coverage_is_vacuously_true_for_a_tpr_only_promotion
        """
        context = setup_draft_promotion(
            api, window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_31
        )
        promotion_id = context["promotion"]["id"]
        assert context["promotion"]["commitment_verified"] is True

        for window in ((MONDAY_AUG_03, MONDAY_AUG_10), (MONDAY_AUG_17, MONDAY_AUG_24)):
            setup_tactic(
                api,
                promotion_id,
                "TPR",
                planned_units=1000,
                rate_per_case=1.000,
                window_start=window[0],
                window_end=window[1],
            )
        assert read_promotion(api, promotion_id)["commitment_verified"] is True

        evidence = validate_success(
            api.create_document(
                promotion_id,
                create_evidence_document_payload(
                    doc_type="SCAN_DATA",
                    covers_tactic_type="ALL",
                    received_at=instant(MONDAY_AUG_10, hour=9),
                    units_verified=900,
                ),
                finance_analyst,
            ),
            expected_status=201,
        )
        verified = validate_success(
            api.verify_document(evidence["id"], finance_analyst)
        )
        assert verified["doc_class"] == "EVIDENCE"
        assert verified["status"] == "VERIFIED"
        assert verified["units_verified"] == 900

        rows, meta = validate_paginated(
            api.list_promotion_documents(
                promotion_id, director, params={"doc_class": "COMMITMENT"}
            )
        )
        assert rows == []
        assert meta["total_count"] == 0

        promotion = read_promotion(api, promotion_id)
        assert promotion["commitment_verified"] is True
        assert_money(
            promotion["tactic_subtotal_amount"], 2000.00, "tactic_subtotal_amount"
        )
        assert_money(promotion["planned_total_spend"], 2000.00, "planned_total_spend")


class TestDisplayPromotionNeedsCommitmentPaperwork:
    """A display line without verified paperwork blocks approval."""

    def test_display_promotion_needs_a_verified_commitment_document(
        self, api, key_account_manager, director
    ):
        """
        A well-funded display promotion is still refused approval for missing paperwork.

        PRD: "**Rung 85** — commitment paperwork covers every display and feature line, on promotion approve: `ERR_COMMITMENT_DOCUMENTATION_MISSING`."
        PRD: "The **covered** set is built from the promotion's documents whose `doc_class` is `COMMITMENT` and whose `status` is `VERIFIED`: a document whose `covers_tactic_type` is `ALL` contributes all three of `TPR`, `DISPLAY` and `FEATURE`, and any other document contributes exactly the single type it names."
        PRD: "And the fiscal capacity checks (rungs 95 through 98) are evaluated **last** of all, so a promotion approval that is simultaneously missing its commitment paperwork and over its allocation balance reports the missing paperwork."

        Design: Corner/errors/display_promotion_needs_a_verified_commitment_document
        """
        context = setup_promotion_with_display_line(
            api,
            promotion_overrides={
                "window_start": MONDAY_AUG_03,
                "window_end": MONDAY_AUG_17,
            },
            planned_units=2000,
            fixed_fee=3000.00,
            window_start=MONDAY_AUG_03,
            window_end=MONDAY_AUG_17,
        )
        promotion_id = context["promotion"]["id"]

        submitted = validate_success(
            api.submit_promotion(promotion_id, key_account_manager)
        )
        assert submitted["lifecycle_status"] == "SUBMITTED"
        assert submitted["commitment_verified"] is False
        assert_money(submitted["planned_total_spend"], 3000.00, "planned_total_spend")

        validate_error(
            api.approve_promotion(promotion_id, director),
            ApiErrorId.COMMITMENT_DOCUMENTATION_MISSING.value,
        )

        promotion = read_promotion(api, promotion_id)
        assert promotion["lifecycle_status"] == "SUBMITTED"
        assert promotion["commitment_verified"] is False
        assert promotion["approved_by_user_id"] is None

        allocation = read_allocation(api, context["allocation"]["id"])
        assert_money(allocation["committed_amount"], 0.00, "committed_amount")
        assert allocation["committed_units"] == 0


class TestVerificationSplitByDocumentClass:
    """Each document class has exactly one role that may verify it."""

    def test_document_verification_is_split_by_document_class(
        self, api, key_account_manager, finance_analyst
    ):
        """
        Each role is refused on the other class and succeeds on its own.

        PRD: "Verification is class-restricted, and this is a payload-dependent authorisation check rather than a plain role check, because both roles appear on the endpoint."
        PRD: "A `COMMITMENT` document may be verified only by a `KeyAccountManager`; an `EVIDENCE` document only by a `TradeFinanceAnalyst`."
        PRD: "The wrong pairing is refused with `ERR_DOCUMENT_CLASS_ROLE_MISMATCH` (HTTP 403)."

        Design: Corner/rbac/document_verification_is_split_by_document_class
        """
        context = setup_draft_promotion(
            api, window_start=MONDAY_AUG_03, window_end=MONDAY_AUG_10
        )
        promotion_id = context["promotion"]["id"]

        commitment = validate_success(
            api.create_document(
                promotion_id,
                create_commitment_document_payload(
                    doc_type="SIGNED_LOI",
                    covers_tactic_type="ALL",
                    received_at=instant(MONDAY_AUG_03),
                ),
                key_account_manager,
            ),
            expected_status=201,
        )
        assert commitment["status"] == "SUBMITTED"
        assert commitment["units_verified"] == 0

        evidence = validate_success(
            api.create_document(
                promotion_id,
                create_evidence_document_payload(
                    doc_type="DISPLAY_PHOTO",
                    covers_tactic_type="TPR",
                    received_at=instant(MONDAY_AUG_03),
                    units_verified=300,
                ),
                finance_analyst,
            ),
            expected_status=201,
        )

        validate_error(
            api.verify_document(commitment["id"], finance_analyst),
            ApiErrorId.DOCUMENT_CLASS_ROLE_MISMATCH.value,
        )
        validate_error(
            api.verify_document(evidence["id"], key_account_manager),
            ApiErrorId.DOCUMENT_CLASS_ROLE_MISMATCH.value,
        )

        verified_commitment = validate_success(
            api.verify_document(commitment["id"], key_account_manager)
        )
        assert verified_commitment["status"] == "VERIFIED"
        assert verified_commitment["verified_by_user_id"] == (
            key_account_manager["X-User-ID"]
        )

        verified_evidence = validate_success(
            api.verify_document(evidence["id"], finance_analyst)
        )
        assert verified_evidence["status"] == "VERIFIED"
        assert verified_evidence["verified_by_user_id"] == (
            finance_analyst["X-User-ID"]
        )
        assert verified_evidence["units_verified"] == 300

        assert read_promotion(api, promotion_id)["lifecycle_status"] == "DRAFT"
