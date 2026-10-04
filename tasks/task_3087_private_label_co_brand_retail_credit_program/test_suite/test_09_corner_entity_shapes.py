"""Corner coverage for entity creation, retrieval, listing and defaults."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    onboard_partner,
    setup_program,
    setup_program_with_account,
    post_promo_purchase,
    make_cardholder_headers,
    MINIMUM_CHARGE_CENTS_DEFAULT,
    SETTLEMENT_TERMS_DAYS_DEFAULT,
    DISPUTE_GRACE_DAYS_DEFAULT,
    RENEWAL_NOTICE_DAYS_DEFAULT,
    PURCHASE_RIGHT_RATE_DEFAULT,
)


class TestPartnerCreationShape:

    def test_partner_creation_returns_the_declared_fields_and_starts_active(self, api, admin_headers):
        """PRD §3.1: "A `ProgramAdmin` begins a partnership by creating a
        `RetailPartner` with a `retailer_name`, a `loyalty_program_code` naming
        the retailer's own rewards scheme, and an optional `loyalty_link_enabled`
        flag that defaults to true." PRD §3.1: "A new partner starts in `ACTIVE`."

        Design: Corner/entities/partner_create_returns_every_declared_field_and_starts_active
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", admin_headers))
        partner = validate_success(
            api.create_partner({"retailer_name": "Bellwether Home",
                                "loyalty_program_code": "BELLWETHER",
                                "loyalty_link_enabled": False}, admin_headers),
            201,
        )
        assert partner["partner_status"] == "ACTIVE"
        assert partner["loyalty_link_enabled"] is False
        assert partner["version"] == 1
        assert partner["partner_portfolio_exposure_cents"] == 0

    def test_partner_defaults_loyalty_link_enabled_to_true(self, api, admin_headers):
        """PRD §3.1: "an optional `loyalty_link_enabled` flag that defaults to
        true." PRD §3.1: "it is never supplied by a client and is recomputed
        whenever any of the retailer's programs changes its exposure."

        Design: Corner/entities/partner_create_returns_every_declared_field_and_starts_active
        """
        partner = onboard_partner(api, name="Anchorline Outfitters", code="ANCHORLINE")
        assert partner["loyalty_link_enabled"] is True
        assert partner["partner_portfolio_exposure_cents"] == 0


class TestCreditProgramReadShape:

    def test_program_read_round_trips_cycle_day_and_reads_rollups_at_zero(self, api, admin_headers):
        """PRD §3.2: "A `ProgramAdmin` creates a `CreditProgram` with a
        `partner_id`, an `agreement_id`, and a `cycle_day`". PRD §3.2: "A
        first-generation program carries no predecessor at all and leaves the
        field null."

        Design: Corner/entities/credit_program_get_round_trips_declared_fields
        """
        _partner, _agreement, program = setup_program(api)
        fetched = validate_success(api.get_credit_program(program["id"], admin_headers), 200)
        assert fetched["cycle_day"] == 15
        assert fetched["program_status"] == "ACTIVE"
        assert fetched["supersedes_program_id"] is None
        assert fetched["outstanding_receivable_cents"] == 0
        assert fetched["free_look_exposure_cents"] == 0
        assert fetched["program_profitability_cents"] == 0


class TestPromoPlanListingPagination:

    def test_listing_reports_total_count_across_pages(self, api, admin_headers):
        """PRD §2.3: "`total_count` reports the total number of matching resources
        before pagination is applied, and `has_more` reports whether further pages
        remain." PRD §2.3: "`limit` sets the maximum number of items returned in
        one page; it defaults to 10 and must be an integer between 1 and 100
        inclusive."

        Design: Corner/entities/promo_plans_list_paginates_with_total_count_and_has_more
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        post_promo_purchase(api, account["id"], 40000, 6)
        post_promo_purchase(api, account["id"], 50000, 12)
        post_promo_purchase(api, account["id"], 60000, 18)

        first, meta = validate_paginated(
            api.list_promo_plans(admin_headers, {"program_id": program["id"], "limit": 2, "offset": 0})
        )
        assert len(first) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        second, meta2 = validate_paginated(
            api.list_promo_plans(admin_headers, {"program_id": program["id"], "limit": 2, "offset": 2})
        )
        assert len(second) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False

    def test_default_page_size_and_account_filter(self, api, admin_headers):
        """PRD §2.3: "`offset` sets the number of leading items to skip and
        defaults to 0." PRD §3.4: "A new plan starts in `ACTIVE`."

        Design: Corner/entities/promo_plans_list_paginates_with_total_count_and_has_more
        """
        _partner, _agreement, program, account = setup_program_with_account(api)
        post_promo_purchase(api, account["id"], 40000, 6)
        post_promo_purchase(api, account["id"], 50000, 12)
        post_promo_purchase(api, account["id"], 60000, 18)

        default_page, meta = validate_paginated(
            api.list_promo_plans(admin_headers, {"program_id": program["id"]})
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert len(default_page) == 3

        by_account, meta2 = validate_paginated(
            api.list_promo_plans(admin_headers, {"account_id": account["id"]})
        )
        assert len(by_account) == 3


class TestMissingResourceAndRequiredField:

    def test_unknown_account_id_returns_resource_not_found(self, api, admin_headers):
        """PRD §2.9: "Every path-segment identifier and every body-referenced
        foreign key must resolve to an existing resource before an operation
        proceeds, and a failure to resolve is reported with
        `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/account_get_with_unknown_id_returns_resource_not_found
        """
        get_success_data(api.set_clock("2026-09-01T00:00:00Z", admin_headers))
        resp = api.get_account(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND, 404)

    def test_missing_account_id_on_a_purchase_is_invalid_request(self, api, admin_headers):
        """PRD §3.4: "Every request is also expected to carry the standard input
        fields of its endpoint, and a request whose body omits a required input or
        sends a value that does not match its declared type is refused with
        `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/transaction_create_missing_required_account_id_returns_invalid_request
        """
        _partner, _agreement, _program, account = setup_program_with_account(api)
        resp = api.create_transaction(
            {"merchant_name": "Coldgate Bumpers", "amount_cents": 5000,
             "transaction_channel": "IN_STORE"},
            make_cardholder_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        rows, _meta = validate_paginated(
            api.list_transactions(admin_headers, {"account_id": account["id"]})
        )
        assert rows == []


class TestAgreementDefaults:

    def test_omitting_optional_economics_applies_the_declared_defaults(self, api, admin_headers):
        """PRD §3.1: "the agreement sets a default `promo_term_months`, a
        `minimum_charge_cents` purchase floor that defaults to 29900, a
        `settlement_terms_days` invoice window that defaults to 30, a
        `dispute_grace_days` allowance that defaults to 0, a `renewal_notice_days`
        advance-notice requirement that defaults to 90, and a `purchase_right_rate`
        price multiple that defaults to 1.04."

        Design: Corner/entities/agreement_create_omitting_optional_economics_applies_defaults
        """
        partner = onboard_partner(api)
        agreement = validate_success(
            api.create_agreement({"partner_id": partner["id"], "revenue_share_rate": 0.20,
                                  "promo_subsidy_rate": 0.25, "promo_term_months": 18},
                                 admin_headers),
            201,
        )
        assert agreement["minimum_charge_cents"] == MINIMUM_CHARGE_CENTS_DEFAULT == 29900
        assert agreement["settlement_terms_days"] == SETTLEMENT_TERMS_DAYS_DEFAULT == 30
        assert agreement["dispute_grace_days"] == DISPUTE_GRACE_DAYS_DEFAULT == 0
        assert agreement["renewal_notice_days"] == RENEWAL_NOTICE_DAYS_DEFAULT == 90
        assert agreement["purchase_right_rate"] == PURCHASE_RIGHT_RATE_DEFAULT == 1.04

    def test_a_newly_drafted_agreement_starts_draft_at_version_one(self, api, admin_headers):
        """PRD §3.1: "A drafted agreement sits in `DRAFT` until a `ProgramAdmin`
        opens negotiation on it". PRD §2.6: "`version` (integer) — a
        system-managed counter that increments by one on every mutation of the
        resource".

        Design: Corner/entities/agreement_create_ignores_client_supplied_system_fields
        """
        partner = onboard_partner(api)
        agreement = validate_success(
            api.create_agreement({"partner_id": partner["id"], "revenue_share_rate": 0.18,
                                  "promo_subsidy_rate": 0.22, "promo_term_months": 12,
                                  "agreement_status": "ACTIVE", "version": 9},
                                 admin_headers),
            201,
        )
        assert agreement["agreement_status"] == "DRAFT"
        assert agreement["version"] == 1