"""Counterparty onboarding and field-level entity rules (PRD §2.1, §2.4, §3.1, §3.3)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_seller,
    create_approved_seller,
    create_approved_servicer,
    create_active_agreement,
    create_active_llpa_matrix,
    set_clock,
    setup_counterparty_chain,
    create_draft_loan,
    create_pool_for,
    create_underwritten_loan,
    deliver_loan,
    make_seller_officer_headers,
    api_client,
)

ADMIN = TEST_USERS["gse_admin_headers"]


class TestCounterpartyRegistration:
    def test_seller_create_returns_all_declared_fields_pending_approval(self, api):
        """PRD §3.1: "A new seller starts in `PENDING_APPROVAL` with
        `approval_cycle` at 1 and `probation_relief_enabled` set to false."

        Design: Corner/entities/seller_create_returns_all_declared_fields_pending_approval
        """
        set_clock()
        resp = api.create_seller(
            {
                "legal_name": "Meridian Lending",
                "seller_number": "S-1001",
                "net_worth_cents": 500000000,
                "qc_defect_rate_bps": 100,
            },
            ADMIN,
        )
        from test_helpers import validate_success, assert_seller

        data = validate_success(resp, expected_status=201)
        assert_seller(data)
        assert data["status"] == "PENDING_APPROVAL"
        assert data["approval_cycle"] == 1
        assert data["probation_relief_enabled"] is False
        assert data["net_worth_cents"] == 500000000
        assert data["qc_defect_rate_bps"] == 100
        assert data["version"] == 1

    def test_seller_number_uniqueness_enforced(self, api):
        """PRD §3.1: "Any reuse of an already-registered `seller_number`,
        `servicer_number`, `pool_number`, or `loan_number` is rejected with
        `ERR_DUPLICATE_IDENTIFIER`."

        Design: Corner/entities/seller_number_uniqueness_enforced
        """
        from test_helpers import validate_error

        set_clock()
        create_seller(seller_number="S-1001")
        resp = api.create_seller(
            {
                "legal_name": "Copycat Lending",
                "seller_number": "S-1001",
                "net_worth_cents": 500000000,
                "qc_defect_rate_bps": 100,
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_IDENTIFIER)


class TestOversightDefaults:
    def test_payment_event_create_omitting_nothing_uses_no_defaults(self, api):
        """PRD §3.8: "An administrator opens a `SubservicerOversight` record
        with the `servicer_id` of the master servicer doing the overseeing, the
        `subservicer_id` being overseen, an `oversight_period_start`, an
        `oversight_period_end` strictly after the start, and an optional
        `findings_count` defaulting to 0. The record opens in `OPEN` status."

        Design: Corner/entities/payment_event_create_omitting_nothing_uses_no_defaults
        """
        from test_helpers import create_approved_servicer, create_subservicer_oversight_payload
        from test_helpers import set_clock, validate_success

        set_clock()
        v1 = create_approved_servicer()
        v2 = create_approved_servicer(legal_name="Sub Servicing", servicer_number="V-2002")
        data = validate_success(
            api.create_subservicer_oversight(
                create_subservicer_oversight_payload(
                    v1["id"], v2["id"],
                    oversight_period_start="2026-06-01T00:00:00Z",
                    oversight_period_end="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            ),
            expected_status=201,
        )
        assert data["findings_count"] == 0
        assert data["status"] == "OPEN"


class TestLoanRegistration:
    def test_delivered_loan_price_pinned_forever_across_grid_swap(self, api):
        """PRD §2.10: "All provisional pricing (pipeline projections) uses
        whichever grid is currently `ACTIVE`; final pricing at delivery pins
        the grid active at the delivery instant onto the loan and is immune to
        later grid swaps."
        PRD §3.5: "The row's `llpa_bps` is pinned onto the loan as
        `applied_llpa_bps`, and these two pinned values never change afterward
        — later grid swaps do not touch delivered or purchased loans."

        Design: Difficulty/dual_variant_calc/llpa_provisional_revalues_pipeline_final_pins_loan_price
        """
        from test_helpers import (
            create_active_llpa_matrix, standard_llpa_row, get_loan, validate_success,
        )

        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-PIN")
        deliver_loan(loan, pool, seller)
        delivered = get_loan(loan["id"])
        assert delivered["applied_llpa_bps"] == 100
        assert delivered["delivery_price_cents"] == 396000000
        # Grid swap to 25 bps: the delivered loan's pinned price must not move.
        create_active_llpa_matrix(
            rows=[standard_llpa_row(llpa_bps=25)],
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2027-09-01T00:00:00Z",
        )
        after_swap = get_loan(loan["id"])
        assert after_swap["applied_llpa_bps"] == 100
        assert after_swap["delivery_price_cents"] == 396000000

    def test_loan_create_computes_ltv_and_ignores_client_status(self, api):
        """PRD §3.3: "At creation the system computes `ltv_bp`, the
        loan-to-value ratio in basis points: ten thousand times
        `unpaid_principal_balance_cents`, divided by `appraised_value_cents`,
        rounded half-up to an integer."
        PRD §3.3: "New loans begin in `DRAFT` status with `au_status` of
        `NOT_SUBMITTED`, `consecutive_on_time_payments` at 0,
        `independent_validation_complete` false, `relief_tier` of `NONE`,
        `pool_id` null, and no `delivered_at`."

        Design: Corner/entities/loan_create_computes_ltv_and_ignores_client_status
        """
        from test_helpers import validate_success

        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(
            seller, servicer, agreement,
            loan_number="LN-LTV",
            unpaid_principal_balance_cents=333333300,
            appraised_value_cents=400000000,
            credit_score=700,
            occupancy="SECOND_HOME",
            product_type="ARM_5_1",
        )
        # 10000 * 333333300 / 400000000 = 8333.3325 -> round-half-up -> 8333
        assert loan["ltv_bp"] == 8333
        assert loan["status"] == "DRAFT"
        assert loan["au_status"] == "NOT_SUBMITTED"
        assert loan["relief_tier"] == "NONE"
        assert loan["consecutive_on_time_payments"] == 0
        assert loan["independent_validation_complete"] is False
        assert loan["pool_id"] is None

    def test_loan_get_unknown_id_returns_not_found(self, api):
        """PRD §2.9: "Next, every identifier referenced in the path and the
        body must exist — `ERR_NOT_FOUND` (HTTP 404) otherwise."

        Design: Corner/entities/loan_get_unknown_id_returns_not_found
        """
        from test_helpers import validate_error

        set_clock()
        resp = api.get_loan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_loans_list_paginates_with_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The
        `offset` parameter specifies how many items to skip and defaults to 0."
        PRD §2.3: "The `meta` object of every list response carries the four
        pagination fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/loans_list_paginates_with_total_count_and_has_more
        """
        from test_helpers import validate_paginated

        seller, servicer, agreement, _ = setup_counterparty_chain()
        for i in range(1, 4):
            create_draft_loan(seller, servicer, agreement, loan_number=f"LN-PG{i}")

        page1, meta1 = validate_paginated(
            api.list_loans(ADMIN, params={"seller_id": seller["id"], "limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_loans(ADMIN, params={"seller_id": seller["id"], "limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_loan_create_with_invalid_occupancy_enum_rejected(self, api):
        """PRD §3.3: "A `SellerOfficer` registers a loan application by
        providing the `seller_id` of the selling lender, the `servicer_id` of
        the servicer of record, the `agreement_id` under which the loan will be
        delivered, a seller-assigned `loan_number` unique across all loans, the
        primary `borrower_name`, the `unpaid_principal_balance_cents`, the
        `appraised_value_cents` at origination, the representative
        `credit_score` (an integer from 300 to 850), the `occupancy` (one of
        `PRIMARY_RESIDENCE`, `SECOND_HOME`, `INVESTMENT`), and the
        `product_type` (one of `FIXED_30`, `FIXED_15`, `ARM_5_1`)."
        PRD §5: `ERR_INVALID_REQUEST` — 400 Bad Request.

        Design: Corner/entities/loan_create_with_invalid_occupancy_enum_rejected
        """
        from test_helpers import validate_error

        seller, servicer, agreement, _ = setup_counterparty_chain()
        headers = make_seller_officer_headers(seller["id"])
        resp = api.create_loan(
            {
                "seller_id": seller["id"],
                "servicer_id": servicer["id"],
                "agreement_id": agreement["id"],
                "loan_number": "LN-BAD",
                "borrower_name": "Bad Enum",
                "unpaid_principal_balance_cents": 400000000,
                "appraised_value_cents": 500000000,
                "credit_score": 740,
                "occupancy": "RENTAL",
                "product_type": "FIXED_30",
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        # No loan persisted with that loan_number.
        from test_helpers import validate_paginated

        data, _ = validate_paginated(api.list_loans(ADMIN, params={"seller_id": seller["id"]}))
        assert all(loan["loan_number"] != "LN-BAD" for loan in data)

    def test_loan_create_missing_required_field_rejected(self, api):
        """PRD §3.3: "A `SellerOfficer` registers a loan application by
        providing the `seller_id` of the selling lender, the `servicer_id` of
        the servicer of record, the `agreement_id` under which the loan will be
        delivered, a seller-assigned `loan_number` unique across all loans, the
        primary `borrower_name`, the `unpaid_principal_balance_cents`, the
        `appraised_value_cents` at origination, the representative
        `credit_score` (an integer from 300 to 850), the `occupancy` (one of
        `PRIMARY_RESIDENCE`, `SECOND_HOME`, `INVESTMENT`), and the
        `product_type` (one of `FIXED_30`, `FIXED_15`, `ARM_5_1`)."
        PRD §5: `ERR_INVALID_REQUEST` — 400 Bad Request.

        Design: Corner/entities/loan_create_missing_required_field_rejected
        """
        from test_helpers import validate_error

        seller, servicer, agreement, _ = setup_counterparty_chain()
        headers = make_seller_officer_headers(seller["id"])
        resp = api.create_loan(
            {
                "seller_id": seller["id"],
                "servicer_id": servicer["id"],
                "agreement_id": agreement["id"],
                "loan_number": "LN-MISS",
                "borrower_name": "Missing Field",
                "unpaid_principal_balance_cents": 400000000,
                "appraised_value_cents": 500000000,
                "occupancy": "PRIMARY_RESIDENCE",
                "product_type": "FIXED_30",
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_fk_integrity_loan_with_unknown_seller_rejected(self, api):
        """PRD §2.9: "Next, every identifier referenced in the path and the
        body must exist — `ERR_NOT_FOUND` (HTTP 404) otherwise."

        Design: Corner/entities/fk_integrity_loan_with_unknown_seller_rejected
        """
        from test_helpers import validate_error

        seller, servicer, agreement, _ = setup_counterparty_chain()
        headers = make_seller_officer_headers(seller["id"])
        resp = api.create_loan(
            {
                "seller_id": NON_EXISTENT_UUID,
                "servicer_id": servicer["id"],
                "agreement_id": agreement["id"],
                "loan_number": "LN-ORPHAN",
                "borrower_name": "Or Phan",
                "unpaid_principal_balance_cents": 400000000,
                "appraised_value_cents": 500000000,
                "credit_score": 740,
                "occupancy": "PRIMARY_RESIDENCE",
                "product_type": "FIXED_30",
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
