"""Networks, partner registration, tracking links and the shape of a stored row."""

import pytest
from prd_bench_local_runner.testing import NON_EXISTENT_UUID

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_AFFILIATE_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_NETWORK_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_append_only_row,
    assert_cents,
    assert_created,
    assert_error_response,
    assert_field,
    assert_fields,
    assert_fresh_creation,
    assert_list_response,
    assert_null,
    assert_object_response,
    assert_one_decimal_score,
    assert_pagination_meta,
)
from test_helpers.fixtures import (
    create_network,
    mint_link,
    pin_clock,
    read_affiliate,
)
from test_helpers.test_users import (
    ANONYMOUS,
    COMPLIANCE_ANALYST,
    FINANCE_ANALYST,
    PARTNER_MANAGER,
    PROGRAM_ADMIN,
    TRACKING_INGESTOR,
)

CLOCK = f.JUL_05_00_00


class TestNetworkRegistration:
    def test_create_network_returns_declared_fields_and_version_one(self, api):
        """A new network answers its declared fee model at version 1, and the read agrees.

        PRD §2.4: "`version` is an integer that starts at 1 on creation and increments
        by exactly 1 on every mutation of that row, including mutations that only touch
        derived fields such as a balance, a counter or a score."

        Design: Corner/entities/create_network_returns_declared_fields_and_version_one
        """
        pin_clock(api, CLOCK)

        created = assert_created(
            api.create_network(
                f.network_payload(
                    name="Corner Network HYBRID",
                    fee_model="HYBRID",
                    fee_bps=375,
                    flat_fee_cents=0,
                    statement_currency="USD",
                ),
                PROGRAM_ADMIN,
            )
        )

        assert_fields(
            created,
            {
                "name": "Corner Network HYBRID",
                "fee_model": "HYBRID",
                "statement_currency": "USD",
            },
        )
        assert_cents(created, "flat_fee_cents", 0)
        assert created["fee_bps"] == 375, "fee_bps must be stored as the integer 375"
        assert_fresh_creation(created)

        fetched = assert_object_response(api.get_network(created["id"], FINANCE_ANALYST))
        assert_fields(
            fetched,
            {
                "id": created["id"],
                "name": "Corner Network HYBRID",
                "fee_model": "HYBRID",
                "fee_bps": 375,
                "flat_fee_cents": 0,
                "statement_currency": "USD",
                "version": 1,
            },
        )

    @pytest.mark.parametrize(
        "fee_model,fee_bps,flat_fee_cents,statement_currency",
        [
            pytest.param(
                "PERCENT_OF_COMMISSION", 375, 500, "USD", id="flat_fee_must_be_zero"
            ),
            pytest.param("FLAT_PER_CONVERSION", 100, 25, "USD", id="fee_bps_must_be_zero"),
            pytest.param("HYBRID", 375, 0, "JPY", id="currency_outside_enumeration"),
        ],
    )
    def test_create_network_with_cross_field_fee_violations_rejected(
        self, api, fee_model, fee_bps, flat_fee_cents, statement_currency
    ):
        """Each cross-field fee constraint on a network fails on its own with a 400.

        PRD §3.1: "`fee_bps` is the percentage component in basis points, from 0 to
        3000, and must be 0 when the fee model is `FLAT_PER_CONVERSION`;
        `flat_fee_cents` is the per-conversion flat component, from 0 to 1000 cents, and
        must be 0 when the fee model is `PERCENT_OF_COMMISSION`."

        Design: Corner/entities/create_network_with_cross_field_fee_violations_rejected
        """
        pin_clock(api, CLOCK)

        response = api.create_network(
            f.network_payload(
                fee_model=fee_model,
                fee_bps=fee_bps,
                flat_fee_cents=flat_fee_cents,
                statement_currency=statement_currency,
            ),
            PROGRAM_ADMIN,
        )

        assert_error_response(response, ERR_INVALID_REQUEST, 400)


class TestPartnerRegistration:
    def test_get_affiliate_returns_stored_input_and_zeroed_computed_defaults(self, api):
        """A freshly registered partner exposes server-computed defaults it never supplied.

        PRD §3.1: "Every counter and balance starts at zero: `attributed_conversion_count`,
        `new_customer_attributed_count`, `coupon_assisted_conversion_count`,
        `accrued_balance_cents`, `reserved_balance_cents`, `lifetime_paid_cents`,
        `open_violation_case_count` and `tracking_link_count` are all 0,
        `fraud_risk_score` is 0, and `fraud_risk_score_trailing` is 0.0."

        Design: Corner/entities/get_affiliate_returns_stored_input_and_zeroed_computed_defaults
        """
        pin_clock(api, CLOCK)
        network = create_network(api)

        created = assert_created(
            api.create_affiliate(
                {
                    "legal_name": "Beacon Content LLC",
                    "contact_email": "beacon@example.com",
                    "partner_type": "CONTENT",
                    "network_id": network["id"],
                    "payout_currency": "USD",
                },
                ANONYMOUS,
            )
        )

        partner = assert_object_response(
            api.get_affiliate(created["id"], PARTNER_MANAGER)
        )
        assert_fields(
            partner,
            {
                "legal_name": "Beacon Content LLC",
                "contact_email": "beacon@example.com",
                "partner_type": "CONTENT",
                "network_id": network["id"],
                "payout_currency": "USD",
                "status": "PENDING_APPLICATION",
                "suspension_cause": "NONE",
                "sub_affiliate_depth": 0,
                "fraud_risk_score": 0,
                "attributed_conversion_count": 0,
                "new_customer_attributed_count": 0,
                "coupon_assisted_conversion_count": 0,
                "open_violation_case_count": 0,
                "tracking_link_count": 0,
                "tax_document_status": "NONE",
                "version": 1,
            },
        )
        assert_null(partner, "parent_affiliate_id")
        assert_one_decimal_score(partner, "fraud_risk_score_trailing", 0.0)
        assert_cents(partner, "accrued_balance_cents", 0)
        assert_cents(partner, "reserved_balance_cents", 0)
        assert_cents(partner, "lifetime_paid_cents", 0)
        # §3.5: a fresh `CONTENT` partner "scores 4500 less its type discount, which
        # places `CONTENT` and `INFLUENCER` partners at 4500 in `MEDIUM`".
        assert partner["incrementality_score_bps"] == 4500, (
            "registration computes the incrementality score from the zeroed counters"
        )
        assert_field(partner, "incrementality_tier", "MEDIUM")

    def test_list_affiliates_paginates_with_total_count_and_filters_by_partner_type(
        self, api
    ):
        """Three partners page two at a time and narrow to one under a partner-type filter.

        PRD §2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, where `total_count` counts every row
        matching the filters before paging is applied and `has_more` states whether any
        row remains beyond the current page."

        Design: Corner/entities/list_affiliates_paginates_with_total_count_and_filters_by_partner_type
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        for partner_type in ("CONTENT", "CONTENT", "COUPON"):
            assert_created(
                api.create_affiliate(
                    f.affiliate_payload(network["id"], partner_type=partner_type),
                    ANONYMOUS,
                )
            )

        first_rows, first_meta = assert_list_response(
            api.list_affiliates(PROGRAM_ADMIN, {"limit": 2, "offset": 0})
        )
        assert_pagination_meta(
            first_meta, limit=2, offset=0, total_count=3, has_more=True
        )
        assert len(first_rows) == 2, "a limit of 2 must return exactly two rows"

        second_rows, second_meta = assert_list_response(
            api.list_affiliates(PROGRAM_ADMIN, {"limit": 2, "offset": 2})
        )
        assert_pagination_meta(
            second_meta, offset=2, total_count=3, has_more=False
        )
        assert len(second_rows) == 1, "the second page holds the remaining row"

        coupon_rows, coupon_meta = assert_list_response(
            api.list_affiliates(
                PROGRAM_ADMIN, {"partner_type": "COUPON", "limit": 10, "offset": 0}
            )
        )
        assert_pagination_meta(coupon_meta, total_count=1, has_more=False)
        assert_field(coupon_rows[0], "partner_type", "COUPON")

    def test_get_affiliate_unknown_id_returns_not_found(self, api):
        """An unknown but well-formed partner id answers the partner's own 404 code.

        PRD §2.10 rule 3: "A partner identifier resolves to an existing partner —
        otherwise `ERR_AFFILIATE_NOT_FOUND` (404)."

        Design: Corner/entities/get_affiliate_unknown_id_returns_not_found
        """
        pin_clock(api, CLOCK)

        response = api.get_affiliate(NON_EXISTENT_UUID, PROGRAM_ADMIN)

        assert_error_response(response, ERR_AFFILIATE_NOT_FOUND, 404)

    def test_create_affiliate_missing_required_partner_type_returns_invalid_request(
        self, api
    ):
        """Omitting `partner_type` is a malformed registration and persists nothing.

        PRD §2.10 rule 14: "Every required body field is present with its declared type,
        every enum value is a declared member of its enumeration, every integer respects
        its declared range, and every instant is a well-formed ISO 8601 value — otherwise
        `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/create_affiliate_missing_required_partner_type_returns_invalid_request
        """
        pin_clock(api, CLOCK)
        network = create_network(api)

        response = api.create_affiliate(
            {
                "legal_name": "Nameless LLC",
                "contact_email": "nameless@example.com",
                "network_id": network["id"],
                "payout_currency": "USD",
            },
            ANONYMOUS,
        )

        assert_error_response(response, ERR_INVALID_REQUEST, 400)
        _rows, meta = assert_list_response(
            api.list_affiliates(PROGRAM_ADMIN, {"limit": 10, "offset": 0})
        )
        assert_pagination_meta(meta, total_count=0)

    def test_create_affiliate_with_unknown_network_id_returns_not_found(self, api):
        """A body-borne network reference is resolved, not stored blindly.

        PRD §2.5: "A partner registration naming an unknown network fails with
        `ERR_NETWORK_NOT_FOUND`, and one naming an unknown `parent_affiliate_id` fails
        with `ERR_AFFILIATE_NOT_FOUND`."

        Design: Corner/entities/create_affiliate_with_unknown_network_id_returns_not_found
        """
        pin_clock(api, CLOCK)

        response = api.create_affiliate(
            f.affiliate_payload(NON_EXISTENT_UUID, partner_type="CONTENT"), ANONYMOUS
        )

        assert_error_response(response, ERR_NETWORK_NOT_FOUND, 404)
        _rows, meta = assert_list_response(
            api.list_affiliates(PROGRAM_ADMIN, {"limit": 10, "offset": 0})
        )
        assert_pagination_meta(meta, total_count=0)

    def test_create_application_under_unknown_affiliate_returns_not_found(self, api):
        """The leftmost path identifier decides the 404 on a nested write.

        PRD §2.5: "Several collections are reachable one segment below their owner, and
        requests against them resolve identifiers strictly left to right."

        Design: Corner/entities/create_application_under_unknown_affiliate_returns_not_found
        """
        pin_clock(api, CLOCK)

        response = api.create_application(
            NON_EXISTENT_UUID,
            f.application_payload(
                site_url="https://ghost.example", monthly_traffic_estimate=1000
            ),
            PARTNER_MANAGER,
        )

        assert_error_response(response, ERR_AFFILIATE_NOT_FOUND, 404)
        _rows, meta = assert_list_response(
            api.list_applications(PROGRAM_ADMIN, {"limit": 10, "offset": 0})
        )
        assert_pagination_meta(meta, total_count=0)


class TestTrackingLinkDefaults:
    def test_create_tracking_link_omitting_optional_fields_applies_declared_defaults(
        self, api
    ):
        """A minted link defaults to a 30-day window with the device graph off.

        PRD §3.4: "`cookie_window_days` is the length of the attribution lookback in
        days, an integer from 1 to 90 that defaults to 30 when omitted, and
        `device_graph_enabled` is a boolean defaulting to false which, when true, permits
        cross-device matching on the household identifier as well as the device
        identifier."

        Design: Corner/entities/create_tracking_link_omitting_optional_fields_applies_declared_defaults
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = assert_created(
            api.create_affiliate(
                f.affiliate_payload(network["id"], partner_type="CONTENT"), ANONYMOUS
            )
        )

        link = assert_created(
            api.create_tracking_link(
                partner["id"],
                {
                    "landing_url": "https://retail.example/apparel",
                    "sub_id": "beacon-apparel",
                },
                PARTNER_MANAGER,
            )
        )

        assert_fields(
            link,
            {
                "cookie_window_days": 30,
                "device_graph_enabled": False,
                "status": "ACTIVE",
                "affiliate_id": partner["id"],
                "sub_id": "beacon-apparel",
                "version": 1,
            },
        )
        assert_null(link, "disabled_reason")

        # §3.4: "minting it increments the owning partner's `tracking_link_count` and `version`."
        owner = read_affiliate(api, partner["id"])
        assert_fields(owner, {"tracking_link_count": 1, "version": 2})


class TestAppendOnlyRows:
    def test_click_event_rows_expose_no_version_and_have_no_mutation_endpoint(self, api):
        """An ingested click carries `id` and `created_at` and nothing mutable.

        PRD §2.4: "Four resources are append-only records of something that happened and
        are never edited after creation: the click event, the attribution decision, the
        monitoring scan, and the commission ledger entry."

        Design: Corner/entities/click_event_rows_expose_no_version_and_have_no_mutation_endpoint
        """
        pin_clock(api, CLOCK)
        network = create_network(api)
        partner = assert_created(
            api.create_affiliate(
                f.affiliate_payload(network["id"], partner_type="CONTENT"), ANONYMOUS
            )
        )
        link = mint_link(
            api,
            partner["id"],
            sub_id="beacon-apparel",
            cookie_window_days=30,
            device_graph_enabled=False,
        )
        click = assert_created(
            api.ingest_click(
                link["id"],
                f.click_payload(
                    occurred_at=f.JUL_04_10_00,
                    device_id="D1",
                    click_type="ORGANIC_CLICK",
                    referrer_domain="beacon.example",
                ),
                TRACKING_INGESTOR,
            )
        )

        rows, meta = assert_list_response(
            api.list_clicks(link["id"], COMPLIANCE_ANALYST, {"limit": 10, "offset": 0})
        )

        assert_pagination_meta(meta, total_count=1)
        assert_field(rows[0], "id", click["id"])
        assert_append_only_row(rows[0])
        assert_fields(
            rows[0],
            {
                "tracking_link_id": link["id"],
                "occurred_at": f.JUL_04_10_00,
                "device_id": "D1",
                "click_type": "ORGANIC_CLICK",
                "is_trademark_term": False,
            },
        )

    def test_create_conversion_with_client_supplied_status_fields_input_ignored(self, api):
        """A smuggled status, commission and id on an order are ignored, not honoured.

        PRD §3.5: "A new order begins at `UNATTRIBUTED` on the first and
        `PENDING_VALIDATION` on the second, with `gross_commission_cents`,
        `payable_commission_cents`, `clawed_back_cents` and `returned_amount_cents` all
        zeroed, and with `attributed_affiliate_id`, `attributed_click_id` and
        `commission_policy_id` all null."

        Design: Corner/entities/create_conversion_with_client_supplied_status_fields_input_ignored
        """
        pin_clock(api, CLOCK)

        payload = f.conversion_payload(
            order_ref="ORD-SYS-1",
            order_total_cents=100000,
            product_category="APPAREL",
            customer_ref="CUST-SYS",
            is_new_customer=False,
            placed_at="2026-07-01T09:00:00.000Z",
            device_id="D1",
            other_channel_touch="NONE",
        )
        payload.update(
            {
                "attribution_status": "AFFILIATE_ATTRIBUTED",
                "gross_commission_cents": 999999,
                "id": "client-supplied-id",
            }
        )
        order = assert_created(api.create_conversion(payload, TRACKING_INGESTOR))

        assert order["id"] != "client-supplied-id", (
            "§2.4 mints the id server-side: clients never supply it"
        )
        assert_fields(
            order,
            {
                "attribution_status": "UNATTRIBUTED",
                "validation_status": "PENDING_VALIDATION",
                "candidate_click_count": 0,
            },
        )
        assert_cents(order, "gross_commission_cents", 0)
        assert_cents(order, "payable_commission_cents", 0)
        assert_cents(order, "clawed_back_cents", 0)
        assert_cents(order, "returned_amount_cents", 0)
        assert_null(
            order,
            "attributed_affiliate_id",
            "attributed_click_id",
            "commission_policy_id",
        )
        assert_fresh_creation(order)
