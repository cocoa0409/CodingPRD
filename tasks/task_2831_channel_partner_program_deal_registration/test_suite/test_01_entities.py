"""Entity surface: what a create returns, which defaults are applied, what a read reports,
how a list pages, and which foreign keys are resolved before the payload is inspected."""

import pytest
from test_helpers import (
    ANALYST,
    DIRECTOR,
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_certification,
    assert_certification_record,
    assert_common_fields,
    assert_order_invoice,
    assert_paging_meta,
    assert_partner,
    create_account,
    create_partner,
    make_partner_headers,
    read_partner,
    seed_gold_distributor_with_allocation,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPartnerRow:
    def test_enrolment_returns_every_program_field_seeded_at_the_entry_tier(self, api):
        """PRD §3.1: "A newly enrolled partner starts at `tier` `REGISTERED` with `tier_status`
        `COMPLIANT` and `standing_reason` null, with `portal_entitlement_level` `BASIC`, and with
        `cert_credit_total`, `trailing_revenue_cents`, `marketing_qualified_spend_cents` and
        `open_conflict_count` all at 0."
        PRD §2.4: "Every resource further carries `version`, an integer that begins at 1 on
        creation and increases by exactly 1 on every mutation of that row."

        Design: Corner/entities/partner_creation_returns_all_program_fields
        """
        set_clock("2026-01-05T00:00:00.000Z")

        response = api.create_partner(
            {
                "company_name": "Aster Systems",
                "partner_type": "RESELLER",
                "marketing_commitment_cents": 500000,
            },
            ANALYST,
        )
        partner = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert "meta" in body and "data" in body

        assert_partner(partner)
        assert partner["company_name"] == "Aster Systems"
        assert partner["partner_type"] == "RESELLER"
        assert partner["marketing_commitment_cents"] == 500000

        assert partner["tier"] == "REGISTERED"
        assert partner["tier_status"] == "COMPLIANT"
        assert partner["standing_reason"] is None
        assert partner["portal_entitlement_level"] == "BASIC"

        assert partner["cert_credit_total"] == 0
        assert partner["trailing_revenue_cents"] == 0
        assert partner["marketing_qualified_spend_cents"] == 0
        assert partner["open_conflict_count"] == 0

        assert partner["version"] == 1
        assert partner["created_at"] == "2026-01-05T00:00:00.000Z"
        assert partner["updated_at"] == "2026-01-05T00:00:00.000Z"

    def test_an_omitted_commitment_defaults_to_zero_and_is_vacuously_attained(self, api):
        """PRD §3.1: "The enrolling analyst may also supply `marketing_commitment_cents`, the
        annual marketing spend the partner contractually commits to, which must not be negative
        and defaults to 0 when omitted."
        PRD §3.1: "Because a commitment of 0 makes the partner vacuously compliant on marketing,
        `marketing_attainment_pct` reads exactly 1.0000 on such a partner."

        Design: Corner/entities/partner_defaults_applied_when_marketing_commitment_omitted
        """
        set_clock("2026-01-05T00:00:00.000Z")

        partner = validate_success(
            api.create_partner(
                {"company_name": "Borealis Resellers", "partner_type": "RESELLER"}, ANALYST
            ),
            201,
        )

        assert partner["marketing_commitment_cents"] == 0
        assert partner["marketing_attainment_pct"] == pytest.approx(1.0, abs=1e-9)
        assert partner["tier_status"] == "COMPLIANT"
        assert partner["standing_reason"] is None

    def test_a_read_returns_the_stored_row_unchanged_for_the_channel_director(self, api):
        """PRD §2.4: "Every resource in this service carries a server-minted `id` that is a UUID
        string with no type prefix of any kind."
        PRD §2.4: "All twelve resource types — `Partner`, `CertificationRecord`, `Account`,
        `AccountMapping`, `DealRegistration`, `ConflictCase`, `SpecialPricingRequest`,
        `MdfAllocation`, `MdfClaim`, `ProofOfPerformance`, `OrderInvoice` and `PerformanceReview`
        — carry all four of these properties; none of them omits `updated_at` or `version`."

        Design: Corner/entities/partner_get_returns_the_stored_row
        """
        set_clock("2026-01-05T00:00:00.000Z")
        created = create_partner(
            company_name="Cinder Networks",
            partner_type="RESELLER",
            marketing_commitment_cents=250000,
        )

        response = api.get_partner(created["id"], DIRECTOR)
        fetched = validate_success(response)
        assert response.json()["response_type"] == "object"

        assert fetched["id"] == created["id"]
        assert fetched["company_name"] == "Cinder Networks"
        assert fetched["partner_type"] == "RESELLER"
        assert fetched["marketing_commitment_cents"] == 250000
        assert fetched["tier"] == "REGISTERED"
        assert fetched["portal_entitlement_level"] == "BASIC"
        assert fetched["version"] == 1
        assert fetched == created, "the read must report exactly the row the create returned"

    def test_the_partner_list_pages_and_filters_on_the_declared_program_filters(self, api):
        """PRD §2.3: "List responses carry `"response_type": "array"`, and their `meta` object
        carries the four pagination fields `limit`, `offset`, `total_count` and `has_more`, where
        `total_count` is the number of rows matching the filters before paging is applied and
        `has_more` is true exactly when rows remain beyond the current page."
        PRD §2.10: "Partners may be filtered by `tier`, `tier_status` and `partner_type`."

        Design: Corner/entities/partners_list_paginates_with_total_count_and_has_more
        """
        set_clock("2026-01-05T00:00:00.000Z")
        create_partner(company_name="Aster Systems", partner_type="RESELLER")
        create_partner(company_name="Borealis Resellers", partner_type="RESELLER")
        distributor = create_partner(
            company_name="Northwind Distribution", partner_type="DISTRIBUTOR"
        )

        first_response = api.list_partners(ANALYST, params={"limit": 2, "offset": 0})
        rows, meta = validate_paginated(first_response)
        assert first_response.json()["response_type"] == "array"
        assert len(rows) == 2
        assert_paging_meta(meta, limit=2, offset=0, total_count=3, has_more=True)

        rows, meta = validate_paginated(api.list_partners(ANALYST, params={"limit": 2, "offset": 2}))
        assert len(rows) == 1
        assert_paging_meta(meta, limit=2, offset=2, total_count=3, has_more=False)

        rows, meta = validate_paginated(
            api.list_partners(ANALYST, params={"partner_type": "DISTRIBUTOR"})
        )
        assert [row["id"] for row in rows] == [distributor["id"]]
        assert meta["total_count"] == 1
        assert meta["has_more"] is False


class TestRequiredInputsAndEnums:
    def test_a_draft_without_the_forecast_amount_is_a_request_shape_failure(self, api):
        """PRD §3.3: "The partner drafts it by naming its own `partner_id`, the `account_id` being
        pursued, the `product_line` being registered (`PLATFORM_SUITE`, `ANALYTICS_ADDON` or
        `SUPPORT_SERVICES`), the forecast value `expected_amount_cents`, and the forecast close
        instant `expected_close_date`."
        PRD §2.8: "Any violation yields `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/deal_registration_create_missing_required_expected_amount_rejected
        """
        set_clock("2026-01-05T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Iva Sorel", track="TECH_ASSOCIATE")
        account = create_account(account_name="Granite Health", region_code="NA")

        validate_error(
            api.create_deal_registration(
                {
                    "partner_id": partner["id"],
                    "account_id": account["id"],
                    "product_line": "ANALYTICS_ADDON",
                    "expected_close_date": "2026-08-31T00:00:00.000Z",
                },
                make_partner_headers(partner["id"]),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        rows, meta = validate_paginated(
            api.list_deal_registrations(ANALYST, params={"partner_id": partner["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0

    def test_an_activity_type_outside_the_declared_enum_is_refused_without_committing_cents(
        self, api
    ):
        """PRD §3.7: "A partner files a claim against an open period by naming the
        `allocation_id`, an `activity_type` of `EVENT`, `DIGITAL_CAMPAIGN` or
        `CONTENT_SYNDICATION`, and the `requested_cents` it wants reimbursed, which must be
        strictly greater than 0."
        PRD §3.7: "The full `requested_cents` is committed against the pool immediately:
        `committed_cents` increases by that amount and `available_cents` is recomputed."

        Design: Corner/entities/mdf_claim_create_with_invalid_enum_activity_type_rejected
        """
        seed = seed_gold_distributor_with_allocation()
        allocation_id = seed["allocation"]["id"]
        partner_id = seed["partner"]["id"]
        assert seed["partner"]["tier"] == "GOLD"

        validate_error(
            api.create_mdf_claim(
                {
                    "allocation_id": allocation_id,
                    "activity_type": "TRADE_SHOW",
                    "requested_cents": 10000,
                },
                make_partner_headers(partner_id),
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        allocation = validate_success(api.get_mdf_allocation(allocation_id, ANALYST))
        assert allocation["allocated_cents"] == 273000
        assert allocation["committed_cents"] == 0
        assert allocation["available_cents"] == 273000

        rows, _ = validate_paginated(api.list_allocation_mdf_claims(allocation_id, ANALYST))
        assert rows == []


class TestServerOwnedFields:
    def test_a_client_supplied_margin_is_ignored_and_the_pipeline_is_recomputed(self, api):
        """PRD §3.6: "The band never looks at any other order; the only inputs to the whole
        pipeline are the order's own `list_amount_cents` and `order_type`, the partner's `tier` and
        `partner_type` at creation, the linked registration's status and window, and the newest
        un-expired granted special pricing request on that registration."
        PRD §3.6: "A new order is stored with `status` `PENDING`, `invoiced_at` null,
        `credit_memo_cents` 0 and `credit_reason` null, and its entire margin structure is resolved
        and frozen at that moment."

        Design: Corner/entities/order_invoice_computed_margin_recomputed_ignoring_extra_field_input
        """
        set_clock("2026-01-05T00:00:00.000Z")
        partner = create_partner(
            company_name="Northwind Distribution", partner_type="DISTRIBUTOR"
        )

        order = validate_success(
            api.create_order_invoice(
                {
                    "partner_id": partner["id"],
                    "order_type": "STOCKING",
                    "list_amount_cents": 10000000,
                    "margin_pct": 0.5,
                    "invoice_amount_cents": 1,
                },
                ANALYST,
            ),
            201,
        )
        assert_order_invoice(order)

        assert order["margin_pct"] == pytest.approx(0.1350, abs=1e-9), (
            "0.10 REGISTERED base plus 0.02 stocking plus 0.015 MID band, not the client's 0.5"
        )
        assert order["invoice_amount_cents"] == 8650000
        assert order["margin_value_cents"] == 1350000
        assert order["volume_band"] == "MID"
        assert order["status"] == "PENDING"
        assert order["credit_memo_cents"] == 0
        assert order["invoiced_at"] is None

        assert read_partner(partner["id"])["trailing_revenue_cents"] == 0

    def test_certification_credit_weight_and_status_are_written_by_the_server(self, api):
        """PRD §3.1: "The `track` is one of `SALES_PRO`, `TECH_ASSOCIATE` or `TECH_EXPERT`, and it
        fixes the record's `credit_weight` at creation and forever after: a `SALES_PRO` record is
        worth 1 credit, a `TECH_ASSOCIATE` record 2 credits, and a `TECH_EXPERT` record 4."
        PRD §3.1: "Recording a certification triggers a full recomputation of the partner's
        `cert_credit_total`, which is the sum of `credit_weight` across every certification record
        belonging to that partner whose `status` is `ACTIVE`."

        Design: Corner/entities/certification_system_fields_are_server_generated
        """
        set_clock("2026-01-05T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")

        record = validate_success(
            api.create_certification(
                partner["id"],
                {
                    "engineer_name": "Iva Sorel",
                    "track": "TECH_EXPERT",
                    "issued_at": "2025-06-01T00:00:00.000Z",
                    "expires_at": "2028-06-01T00:00:00.000Z",
                },
                ANALYST,
            ),
            201,
        )
        assert_certification_record(record)
        assert_common_fields(record, "CertificationRecord")

        assert record["credit_weight"] == 4
        assert record["status"] == "ACTIVE"
        assert record["version"] == 1
        assert record["created_at"] == "2026-01-05T00:00:00.000Z"
        assert record["updated_at"] == record["created_at"]

        reloaded = read_partner(partner["id"])
        assert reloaded["cert_credit_total"] == 4
        assert reloaded["portal_entitlement_level"] == "BASIC"


class TestExistenceOfPathsAndForeignKeys:
    def test_reading_an_account_that_was_never_created_is_a_typed_404(self, api):
        """PRD §2.8: "A missing `Account` named by a path segment or by a body `account_id` yields
        `ERR_ACCOUNT_NOT_FOUND` (404) — guarding the single account read, the direct-pursuit
        declaration, the account's registration list, the account's conflict-case list, drafting a
        deal registration, and proposing an account mapping."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific
        error."

        Design: Corner/entities/account_get_with_unknown_id_returns_not_found
        """
        set_clock("2026-01-05T00:00:00.000Z")

        response = api.get_account(NON_EXISTENT_UUID, ANALYST)
        validate_error(response, ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]

    def test_a_certification_cannot_be_recorded_under_a_partner_that_does_not_exist(self, api):
        """PRD §2.8: "A missing `Partner` named by a path segment or by a body `partner_id` yields
        `ERR_PARTNER_NOT_FOUND` (404) — this guards reading a partner, patching a partner,
        recording and listing that partner's certifications, opening a fund period, pricing an
        order, preparing a performance review, proposing an account mapping, and drafting a deal
        registration."
        PRD §2.8: "Path identifiers are resolved strictly left to right, and only then are body
        foreign keys resolved in the order they are declared."

        Design: Corner/entities/certification_create_under_unknown_partner_returns_not_found
        """
        set_clock("2026-01-05T00:00:00.000Z")

        validate_error(
            api.create_certification(
                NON_EXISTENT_UUID,
                {
                    "engineer_name": "Iva Sorel",
                    "track": "TECH_EXPERT",
                    "issued_at": "2025-06-01T00:00:00.000Z",
                    "expires_at": "2028-06-01T00:00:00.000Z",
                },
                ANALYST,
            ),
            ApiErrorId.ERR_PARTNER_NOT_FOUND.value,
            404,
        )

        rows, meta = validate_paginated(api.list_certifications(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_body_foreign_key_is_resolved_even_though_it_never_appears_in_the_path(self, api):
        """PRD §2.10: "Entities in this service are peer collections joined by declared foreign
        keys; nothing is nested for identity."
        PRD §2.8: "A missing `Account` named by a path segment or by a body `account_id` yields
        `ERR_ACCOUNT_NOT_FOUND` (404) — guarding the single account read, the direct-pursuit
        declaration, the account's registration list, the account's conflict-case list, drafting a
        deal registration, and proposing an account mapping."

        Design: Corner/entities/deal_registration_create_with_unknown_account_fk_returns_not_found
        """
        set_clock("2026-01-05T00:00:00.000Z")
        partner = create_partner(company_name="Aster Systems", partner_type="RESELLER")
        add_certification(partner["id"], engineer_name="Iva Sorel", track="TECH_ASSOCIATE")

        validate_error(
            api.create_deal_registration(
                {
                    "partner_id": partner["id"],
                    "account_id": NON_EXISTENT_UUID,
                    "product_line": "ANALYTICS_ADDON",
                    "expected_amount_cents": 400000,
                    "expected_close_date": "2026-08-31T00:00:00.000Z",
                },
                make_partner_headers(partner["id"]),
            ),
            ApiErrorId.ERR_ACCOUNT_NOT_FOUND.value,
            404,
        )

        rows, _ = validate_paginated(
            api.list_deal_registrations(ANALYST, params={"partner_id": partner["id"]})
        )
        assert rows == []
