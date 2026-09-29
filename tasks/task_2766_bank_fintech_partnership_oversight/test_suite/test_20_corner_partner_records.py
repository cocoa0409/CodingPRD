"""Partner registration defaults, the read round trip, listing and the
per-collection not-found codes."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    create_partner_payload,
    is_valid_uuid,
    make_internal_audit_headers,
    make_risk_committee_headers,
    validate_error,
    validate_paginated,
    validate_success,
    INTERNAL_AUDIT_1,
    PO,
)

IA = make_internal_audit_headers(INTERNAL_AUDIT_1)
RC_READER = make_risk_committee_headers("rc_1")

NORTHBEAM = {
    "legal_name": "Northbeam Pay Inc",
    "business_model": "CARD_ISSUING",
    "funding_stage": "SERIES_B_PLUS",
    "months_runway": 24,
    "disclosed_complaints_per_10k": 12.50,
    "end_user_account_count": 100000,
}


class TestPartnerRecord:
    def test_registration_returns_every_declared_default_the_client_never_supplied(self):
        """The new partner is stored with a `status` of `PROSPECT`, an `oversight_posture` of
        `OPEN`, a `capability_tier` of `UNRATED`, a `version` of 1, and its `created_by_user_id` set
        to the acting `X-User-ID`.

        Design: Corner/entities/partner_create_returns_every_declared_field_at_its_declared_default
        """
        response = api_client.create_partner(create_partner_payload(**NORTHBEAM), PO)
        partner = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

        assert is_valid_uuid(partner["id"])
        assert partner["legal_name"] == "Northbeam Pay Inc"
        assert partner["business_model"] == "CARD_ISSUING"
        assert partner["status"] == "PROSPECT"
        assert partner["oversight_posture"] == "OPEN"
        assert partner["capability_tier"] == "UNRATED"
        assert partner["version"] == 1
        assert partner["parent_partner_id"] is None
        assert float(partner["latest_composite_score"]) == 0.0
        assert partner["complaint_rate_bps"] == 0
        assert partner["required_reserve_cents"] == 0
        assert partner["reserve_shortfall_cents"] == 0
        assert float(partner["concentration_ratio_pct"]) == 0.00
        assert partner["cumulative_paid_out_cents"] == 0
        assert partner["cumulative_bank_fee_cents"] == 0
        assert partner["total_complaint_count"] == 0
        assert partner["open_complaint_count"] == 0
        assert partner["escalated_complaint_count"] == 0
        assert partner["resolved_complaint_count"] == 0
        assert partner["withdrawn_complaint_count"] == 0
        assert partner["open_sanctions_alert_count"] == 0
        assert partner["consecutive_shortfall_cycles"] == 0
        assert partner["growth_breach_count"] == 0
        assert partner["unreconciled_variance_cents"] == 0
        assert partner["created_by_user_id"] == PO["X-User-ID"]

    def test_a_third_line_reader_round_trips_the_stored_record(self):
        """`InternalAudit` is third-line assurance exercising the audit-access right reserved in
        the program agreement. It holds read access across every collection and exactly two
        settlement-integrity writes: it may reconcile a settlement batch, an ability it shares with
        `ProgramOfficer`, and it is the only role that may clear a settlement variance once one has
        been raised.

        Design: Corner/entities/partner_get_by_id_round_trips_the_stored_record
        """
        created = validate_success(
            api_client.create_partner(create_partner_payload(**NORTHBEAM), PO), 201
        )
        fetched = validate_success(api_client.get_partner(created["id"], IA), 200)
        assert fetched["id"] == created["id"]
        assert float(fetched["disclosed_complaints_per_10k"]) == 12.50
        assert fetched["end_user_account_count"] == 100000
        assert fetched["months_runway"] == 24
        assert fetched["funding_stage"] == "SERIES_B_PLUS"
        assert fetched["created_at"] is not None
        assert fetched["updated_at"] is not None
        assert fetched["version"] == 1

    def test_listing_pages_filters_and_counts_the_filtered_set_not_the_page(self):
        """List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta`
        object, where `total_count` is the number of rows matching the filters before pagination is
        applied and `has_more` states whether any matching row remains beyond the current page.

        Design: Corner/entities/partners_list_paginates_filters_and_reports_total_count_and_has_more
        """
        root = validate_success(
            api_client.create_partner(create_partner_payload(**NORTHBEAM), PO), 201
        )
        lending = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Northbeam Lending LLC",
                    business_model="LENDING",
                    funding_stage="SERIES_A",
                    months_runway=18,
                    disclosed_complaints_per_10k=30.00,
                    end_user_account_count=5000,
                    parent_partner_id=root["id"],
                ),
                PO,
            ),
            201,
        )
        wallet = validate_success(
            api_client.create_partner(
                create_partner_payload(
                    legal_name="Northbeam Wallet LLC",
                    business_model="DEPOSIT_WALLET",
                    funding_stage="SEED",
                    months_runway=9,
                    disclosed_complaints_per_10k=0.00,
                    end_user_account_count=0,
                    parent_partner_id=root["id"],
                ),
                PO,
            ),
            201,
        )

        page1, meta1 = validate_paginated(
            api_client.list_partners(RC_READER, {"limit": 2, "offset": 0})
        )
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api_client.list_partners(RC_READER, {"limit": 2, "offset": 2})
        )
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

        children, _ = validate_paginated(
            api_client.list_partners(RC_READER, {"parent_partner_id": root["id"]})
        )
        assert sorted(row["id"] for row in children) == sorted([lending["id"], wallet["id"]])

        prospects, _ = validate_paginated(api_client.list_partners(RC_READER, {"status": "PROSPECT"}))
        assert len(prospects) == 3

        wallets, _ = validate_paginated(
            api_client.list_partners(RC_READER, {"business_model": "DEPOSIT_WALLET"})
        )
        assert [row["id"] for row in wallets] == [wallet["id"]]

        default_page, default_meta = validate_paginated(api_client.list_partners(RC_READER))
        assert len(default_page) == 3
        assert default_meta["limit"] == 10, "limit defaults to 10"
        assert default_meta["offset"] == 0, "offset defaults to 0"

    def test_an_unallocated_partner_id_returns_the_partner_specific_not_found(self):
        """Path ids are resolved **left to right**, and the first segment that names no existing row
        determines the error. The not-found error is specific to the collection that segment
        addresses.

        Design: Corner/entities/partner_get_with_an_unknown_id_returns_partner_not_found
        """
        response = api_client.get_partner(NON_EXISTENT_UUID, PO)
        error = validate_error(response, ApiErrorId.ERR_PARTNER_NOT_FOUND, 404)
        assert error["error_id"] != ApiErrorId.ERR_VALIDATION.value
        assert error["message"]
        assert response.json()["response_type"] == "error"

    def test_all_ten_sibling_collections_report_their_own_not_found_code(self):
        """The not-found error is specific to the collection that segment addresses:
        `ERR_PARTNER_NOT_FOUND`, `ERR_REVIEW_NOT_FOUND` for a diligence review,
        `ERR_AGREEMENT_NOT_FOUND`, `ERR_MARKETING_REVIEW_NOT_FOUND`,
        `ERR_CUSTODY_ACCOUNT_NOT_FOUND`, `ERR_BATCH_NOT_FOUND` for a settlement batch,
        `ERR_LEDGER_ENTRY_NOT_FOUND`, `ERR_COMPLAINT_NOT_FOUND`, `ERR_ALERT_NOT_FOUND`,
        `ERR_CYCLE_NOT_FOUND` or `ERR_PLAN_NOT_FOUND` for a wind-down plan. All are HTTP 404.

        Design: Corner/entities/every_collection_reports_its_own_not_found_code_on_an_unknown_path_id
        """
        probes = [
            (api_client.get_diligence_review, ApiErrorId.ERR_REVIEW_NOT_FOUND),
            (api_client.get_agreement, ApiErrorId.ERR_AGREEMENT_NOT_FOUND),
            (api_client.get_marketing_review, ApiErrorId.ERR_MARKETING_REVIEW_NOT_FOUND),
            (api_client.get_custody_account, ApiErrorId.ERR_CUSTODY_ACCOUNT_NOT_FOUND),
            (api_client.get_settlement_batch, ApiErrorId.ERR_BATCH_NOT_FOUND),
            (api_client.get_ledger_entry, ApiErrorId.ERR_LEDGER_ENTRY_NOT_FOUND),
            (api_client.get_complaint, ApiErrorId.ERR_COMPLAINT_NOT_FOUND),
            (api_client.get_alert, ApiErrorId.ERR_ALERT_NOT_FOUND),
            (api_client.get_cycle, ApiErrorId.ERR_CYCLE_NOT_FOUND),
            (api_client.get_wind_down_plan, ApiErrorId.ERR_PLAN_NOT_FOUND),
        ]
        seen = []
        for reader, expected in probes:
            error = validate_error(reader(NON_EXISTENT_UUID, IA), expected, 404)
            assert error["error_id"] != ApiErrorId.ERR_PARTNER_NOT_FOUND.value
            seen.append(error["error_id"])
        assert len(set(seen)) == 10, f"the ten collections must report ten distinct codes: {seen}"
